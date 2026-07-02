"""tech-news-wiki 수집기 (stage 1).

sources.toml 의 피드를 httpx 로 받아 feedparser 로 파싱하고, 신규 항목만
raw/feeds/DATE/items.jsonl 에 항목별 한 줄로 저장한다.

설계 포인트:
- httpx 명시적 timeout + User-Agent 로 먼저 바이트를 받고, feedparser.parse(bytes) 로
  메모리 파싱 → 느린 피드가 전체를 멈추지 않는다.
- 복구 가능한 seen 인덱스(state/seen.jsonl): 유실/손상 시 raw items 를 재스캔해 재구성.
- dedup 키 우선순위 guid → 정규화 URL → source+title+published.
- 저작권: 제목·URL·게시일·피드 제공 요약 발췌만 저장(전문 저장 안 함).
- 실패 피드는 스킵하고 실행 요약 + 종료 코드로 부분 실패를 투명 보고.

Usage:
  uv run scripts/fetch.py [--source NAME]... [--since YYYY-MM-DD]
                          [--limit N] [--dry-run] [--config PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser  # type: ignore
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

USER_AGENT = "tech-news-wiki/0.1 (+https://github.com/; feed collector)"
HTTP_TIMEOUT = 10.0
FETCH_RETRIES = 2       # 첫 시도 외 추가 재시도 횟수
FETCH_BACKOFF = 1.5     # 재시도 간 대기(초)
SEEN_MAX_DAYS = 60
SEEN_MAX_ENTRIES = 20000


# ---------------------------------------------------------------------------
# seen 인덱스
# ---------------------------------------------------------------------------

def seen_path() -> Path:
    return C.ROOT / "state" / "seen.jsonl"


def load_seen() -> dict[str, str]:
    """{dedup_key: 'YYYY-MM-DD'}. 손상 라인은 건너뛴다."""
    p = seen_path()
    out: dict[str, str] = {}
    if not p.exists():
        return out
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                k = rec.get("key")
                if k:
                    out[k] = rec.get("date", "")
            except json.JSONDecodeError:
                continue
    except OSError:
        return out
    return out


def rebuild_seen_from_raw() -> dict[str, str]:
    """seen 인덱스 유실/손상 시 raw/feeds/**/items.jsonl 을 재스캔해 재구성."""
    out: dict[str, str] = {}
    feeds_dir = C.ROOT / "raw" / "feeds"
    if not feeds_dir.exists():
        return out
    for items_file in sorted(feeds_dir.glob("*/items.jsonl")):
        for line in items_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            k = rec.get("key")
            if k:
                out[k] = rec.get("fetched_date", "")
    return out


def prune_seen(seen: dict[str, str]) -> dict[str, str]:
    """최근 SEEN_MAX_DAYS 일 이내 항목만 유지, 그래도 많으면 최신 SEEN_MAX_ENTRIES 개."""
    cutoff = (C.now_kst() - timedelta(days=SEEN_MAX_DAYS)).strftime("%Y-%m-%d")
    kept = {k: d for k, d in seen.items() if (d or "9999") >= cutoff}
    if len(kept) > SEEN_MAX_ENTRIES:
        newest = sorted(kept.items(), key=lambda kv: kv[1], reverse=True)[:SEEN_MAX_ENTRIES]
        kept = dict(newest)
    return kept


def write_seen_atomic(seen: dict[str, str]) -> None:
    """temp 파일 후 atomic rename."""
    p = seen_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"key": k, "date": d}, ensure_ascii=False) for k, d in sorted(seen.items())]
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".seen.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
            if lines:
                fh.write("\n")
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ---------------------------------------------------------------------------
# 피드 수집
# ---------------------------------------------------------------------------

def _transient_status(status: int, url: str) -> bool:
    """재시도할 가치가 있는 상태 코드인가.

    5xx·429 는 일반적 일시 오류. YouTube 피드는 엣지 서버에 따라 같은 URL이
    200/404 를 오가는 것이 실측 확인돼(2026-07-02), youtube.com 에 한해 404 도
    일시 오류로 취급한다.
    """
    if status >= 500 or status == 429:
        return True
    return status == 404 and "youtube.com" in url


def fetch_feed_bytes(client: httpx.Client, url: str) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(1 + FETCH_RETRIES):
        if attempt:
            time.sleep(FETCH_BACKOFF * attempt)
        try:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPStatusError as e:
            last_exc = e
            if not _transient_status(e.response.status_code, url):
                raise
        except httpx.TransportError as e:  # timeout·연결 오류 — 재시도 가치 있음
            last_exc = e
    assert last_exc is not None
    raise last_exc


def entry_to_item(feed: C.Feed, entry, fetched_at: str, fetched_date: str) -> dict:
    title = C.strip_html(getattr(entry, "title", "") or "", max_len=300)
    link = getattr(entry, "link", "") or ""
    guid = getattr(entry, "id", None) or getattr(entry, "guid", None)
    published = C.struct_to_iso(getattr(entry, "published_parsed", None)) \
        or C.struct_to_iso(getattr(entry, "updated_parsed", None))
    summary = C.strip_html(getattr(entry, "summary", "") or "", max_len=600)
    key = C.dedup_key(guid=guid, url=link, source=feed.name, title=title, published=published)
    return {
        "key": key,
        "source": feed.name,
        "kind": feed.kind,
        "audience": feed.audience,
        "lang": feed.lang,
        "weight": feed.weight,
        "trust": feed.trust,
        "title": title,
        "url": C.normalize_url(link),
        "orig_url": link,
        "published": published,
        "fetched_at": fetched_at,
        "fetched_date": fetched_date,
        "summary": summary,
    }


def passes_since(item: dict, since: str | None) -> bool:
    if not since:
        return True
    pub = item.get("published")
    if not pub:
        return True  # 게시일 미상은 필터하지 않고 포함
    return pub[:10] >= since


def append_items(date: str, items: list[dict]) -> Path:
    out_dir = C.ROOT / "raw" / "feeds" / date
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "items.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    return path


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="tech-news-wiki 피드 수집기")
    ap.add_argument("--source", action="append", default=[], help="이 이름의 피드만 수집(반복 가능)")
    ap.add_argument("--since", default=None, help="이 게시일(YYYY-MM-DD) 이후 항목만")
    ap.add_argument("--limit", type=int, default=None, help="피드당 신규 항목 상한")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 요약만 출력")
    ap.add_argument("--config", default=None, help="sources.toml 경로")
    args = ap.parse_args(argv)

    try:
        cfg = C.load_config(args.config)
    except (OSError, ValueError) as e:
        print(f"[config-error] {e}", file=sys.stderr)
        return 1

    for w in cfg.warnings:
        print(w, file=sys.stderr)

    feeds = cfg.feeds
    if args.source:
        wanted = set(args.source)
        feeds = [f for f in feeds if f.name in wanted]
        if not feeds:
            print(f"[error] --source 로 지정한 피드를 찾을 수 없음: {sorted(wanted)}", file=sys.stderr)
            return 1

    seen = load_seen()
    if not seen:
        rebuilt = rebuild_seen_from_raw()
        if rebuilt:
            print(f"[info] seen 인덱스 재구성: raw 에서 {len(rebuilt)}개 키 복원", file=sys.stderr)
            seen = rebuilt

    date = C.run_date()
    fetched_at = C.now_kst().isoformat()

    new_items: list[dict] = []
    ok_feeds = 0
    failed_feeds = 0
    per_feed: list[tuple[str, int, str]] = []  # (name, new_count, status)

    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"}
    with httpx.Client(headers=headers, timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        for feed in feeds:
            try:
                content = fetch_feed_bytes(client, feed.url)
            except (httpx.HTTPError, httpx.InvalidURL) as e:
                failed_feeds += 1
                per_feed.append((feed.name, 0, f"fetch-fail: {type(e).__name__}"))
                print(f"[warn] {feed.name}: fetch 실패 — {e}", file=sys.stderr)
                continue

            parsed = feedparser.parse(content)
            entries = parsed.entries
            if not entries:
                if getattr(parsed, "bozo", 0):
                    failed_feeds += 1
                    per_feed.append((feed.name, 0, "parse-fail (bozo, 0 entries)"))
                    print(f"[warn] {feed.name}: 파싱 실패/빈 피드 — {getattr(parsed, 'bozo_exception', '')}", file=sys.stderr)
                    continue
                ok_feeds += 1
                per_feed.append((feed.name, 0, "empty"))
                continue

            ok_feeds += 1
            feed_new = 0
            for entry in entries:
                item = entry_to_item(feed, entry, fetched_at, date)
                if item["key"] in seen:
                    continue
                if not passes_since(item, args.since):
                    continue
                seen[item["key"]] = date          # 같은 실행 내 중복도 방지
                new_items.append(item)
                feed_new += 1
                if args.limit and feed_new >= args.limit:
                    break
            per_feed.append((feed.name, feed_new, "ok" + (" (bozo)" if getattr(parsed, "bozo", 0) else "")))

    # ── 쓰기 ──
    if not args.dry_run and new_items:
        path = append_items(date, new_items)
        write_seen_atomic(prune_seen(seen))
        print(f"[write] {len(new_items)}개 신규 → {path}", file=sys.stderr)
    elif args.dry_run:
        print("[dry-run] 쓰지 않음", file=sys.stderr)

    # ── 실행 요약 ──
    print("\n=== 수집 요약 ===")
    print(f"날짜(KST): {date}   피드 성공: {ok_feeds}   실패: {failed_feeds}   신규 항목: {len(new_items)}")
    for name, n, status in per_feed:
        mark = "•" if n else " "
        print(f"  {mark} {name:32s} 신규 {n:3d}  [{status}]")

    # ── 종료 코드: 모든 피드 실패 시 2, 정상(0건 포함) 0 ──
    if feeds and failed_feeds == len(feeds):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
