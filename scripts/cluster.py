"""tech-news-wiki 클러스터링 (stage 2).

raw/feeds/DATE/items.jsonl 를 읽어 유사 항목을 묶고, 클러스터 응집도(cohesion)가
임계값 이상인 것만 LLM 샘플링 대상(coherent)으로 승격한다. 나머지는 loose(개별 항목)로
압축 나열한다. 결과는 raw/feeds/DATE/clusters.json (LLM 큐레이션의 진입점).

컨텍스트 부하 방지 원리:
- 비슷한 기사(교차 피드 중복 포함)를 한 클러스터로 묶고, 대표 소수만 요약과 함께 노출.
- cohesion >= τ 인 클러스터에서만 대표를 '샘플링'하고, 총량은 max_samples 로 제한.
- 임베딩은 TF-IDF(char_wb n-gram) — 한국어·영어 혼재에 언어 무관하게 견고, 오프라인·결정적.

Usage:
  uv run scripts/cluster.py [--date YYYY-MM-DD] [--config PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

_WORD_RE = re.compile(r"[0-9A-Za-z가-힣]+")
_URL_RE = re.compile(r"https?://\S+")


def _cluster_text(item: dict) -> str:
    """클러스터링용 텍스트. URL 보일러플레이트를 제거해 실제 주제 유사도만 남긴다.

    YouTube 항목은 설명(summary)이 구독/디스코드 링크 등 채널 공통 보일러플레이트로
    가득 차 '같은 채널'끼리 잘못 뭉치므로, **제목만** 사용한다.
    """
    if item.get("kind") == "youtube":
        raw = item.get("title", "")
    else:
        raw = f"{item.get('title','')} {item.get('summary','')}"
    return _URL_RE.sub(" ", raw).strip() or " "
_STOP = {
    # en
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is",
    "are", "be", "how", "why", "what", "new", "your", "you", "we", "it", "this",
    "that", "from", "at", "as", "by", "show", "hn", "vs",
    "https", "http", "www", "com", "discord", "youtube", "subscribe",
    # ko (조사/흔한 어미 일부)
    "그리고", "그러나", "위한", "관한", "대한", "있는", "하는", "이제", "오늘",
}


def _rep_view(item: dict, full_summary: bool) -> dict:
    v = {
        "key": item.get("key"),
        "title": item.get("title"),
        "url": item.get("url"),
        "source": item.get("source"),
        "published": item.get("published"),
        "audience": item.get("audience", []),
        "trust": float(item.get("trust", 1.0)),
    }
    if full_summary:
        v["summary"] = item.get("summary", "")
    else:
        s = item.get("summary", "") or ""
        v["summary"] = (s[:140].rstrip() + "…") if len(s) > 140 else s
    return v


def _keywords(members: list[dict], top: int = 5) -> list[str]:
    counts: dict[str, int] = {}
    for m in members:
        text = f"{m.get('title','')} {m.get('summary','')}"
        for tok in _WORD_RE.findall(text.lower()):
            if len(tok) < 2 or tok.isdigit() or tok in _STOP:
                continue
            counts[tok] = counts.get(tok, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[:top]]


def _connected_components(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _cohesion(sim: np.ndarray, idx: list[int]) -> float:
    """멤버 간 평균 쌍별 코사인. 싱글턴은 0.0(응집도 정의 불가 → loose 로)."""
    if len(idx) < 2:
        return 0.0
    sub = sim[np.ix_(idx, idx)]
    m = len(idx)
    total = sub.sum() - np.trace(sub)         # 대각(자기유사도=1) 제외
    return float(total / (m * (m - 1)))


def _centroid_sims(tfidf, idx: list[int]) -> dict[int, float]:
    """각 멤버의 클러스터 centroid(평균 TF-IDF 벡터)에 대한 코사인. O(N) (거리 게이트).

    "클러스터 중심과의 거리" 요구를 직접 구현: pairwise 평균이 아니라 중심 벡터 기준.
    """
    sub = tfidf[idx]                                   # sparse (len(idx) × V)
    centroid = np.asarray(sub.mean(axis=0))           # (1 × V)
    sims = cosine_similarity(sub, centroid).ravel()   # (len(idx),)
    return {i: float(s) for i, s in zip(idx, sims)}


def _recency_days(published: str | None, ref_date: str) -> int | None:
    """게시일로부터 기준일(ref_date, KST YYYY-MM-DD)까지의 경과일.

    게시일 누락/파싱 실패 → None. 미래 일자(기준일보다 나중) → 0으로 클램프.
    """
    if not published:
        return None
    try:
        pub = date.fromisoformat(str(published)[:10])
        ref = date.fromisoformat(ref_date)
    except ValueError:
        return None
    return max((ref - pub).days, 0)


def _gate_hint(corroboration: int, max_trust: float) -> str:
    """게이트웨이#1 결정론 힌트(결정표 — 구현자 편차 제거).

    strong        : 독립 출처 ≥2 그리고 max_trust ≥ 1.0
    single-source : 독립 출처 == 1
    check         : 그 외(저신뢰 다출처 등)
    """
    if corroboration >= 2 and max_trust >= 1.0:
        return "strong"
    if corroboration == 1:
        return "single-source"
    return "check"


def _rank_representatives(sim: np.ndarray, idx: list[int], items: list[dict], k: int) -> list[int]:
    """중심성(멤버 평균 유사도) 내림차순, 동점 시 weight, 요약 길이 순으로 상위 k."""
    def centrality(i: int) -> float:
        others = [j for j in idx if j != i]
        return float(np.mean([sim[i, j] for j in others])) if others else 0.0

    ordered = sorted(
        idx,
        key=lambda i: (centrality(i), float(items[i].get("weight", 1.0)), len(items[i].get("summary", "") or "")),
        reverse=True,
    )
    return ordered[:k]


def cluster_items(items: list[dict], cfg: C.ClusterConfig, date: str) -> dict:
    """순수 함수: 항목 리스트 → clusters.json 매니페스트 딕셔너리. (파일 I/O 없음)"""
    n = len(items)
    manifest: dict = {
        "date": date,
        "coherent": [],
        "loose": [],
        "stats": {"items": n, "clusters": 0, "coherent": 0, "sampled": 0, "outliers_excluded": 0},
    }
    if n == 0:
        return manifest

    if n == 1:
        v = _rep_view(items[0], full_summary=False)
        v["recency_days"] = _recency_days(items[0].get("published"), date)
        v["gate_hint"] = "single-source"
        manifest["loose"].append(v)
        manifest["stats"].update(clusters=1, coherent=0, sampled=0, outliers_excluded=0)
        return manifest

    texts = [_cluster_text(it) for it in items]
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    tfidf = vec.fit_transform(texts)
    sim = cosine_similarity(tfidf)
    np.fill_diagonal(sim, 1.0)

    edges: list[tuple[int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] >= cfg.sim_link:
                edges.append((i, j))

    components = _connected_components(n, edges)

    coherent_clusters = []   # (size, cohesion, idx, coh)
    loose_idx: list[int] = []
    for comp in components:
        coh = _cohesion(sim, comp)
        if len(comp) >= 2 and coh >= cfg.cohesion_threshold:
            coherent_clusters.append((len(comp), coh, comp))
        else:
            loose_idx.extend(comp)

    # 큰(핫한)·응집도 높은 클러스터 우선, max_samples 예산 내에서 대표 배정
    coherent_clusters.sort(key=lambda t: (t[0], t[1]), reverse=True)
    budget = cfg.max_samples
    cid = 0
    outliers_total = 0
    for size, coh, comp in coherent_clusters:
        # ── 거리 게이트: centroid 코사인 < member_sim_min 인 멤버는 아웃라이어 ──
        csims = _centroid_sims(tfidf, comp)
        core = [i for i in comp if csims[i] >= cfg.member_sim_min]
        outliers = [i for i in comp if csims[i] < cfg.member_sim_min]
        # 작은 클러스터 폴백: core 가 1개 이하로 붕괴하면 게이트 미적용(원본 유지)
        if len(core) <= 1:
            core, outliers = comp, []
        core_members = [items[i] for i in core]

        # 대표 샘플은 core 에서만 선정 (먼 항목은 ingest 자료에서 제외)
        k = cfg.sample_k + (1 if len(core) >= 5 else 0)
        k = min(k, 3, len(core))
        if budget <= 0:
            k = 0
        else:
            k = min(k, budget)
        reps_idx = _rank_representatives(sim, core, items, k) if k > 0 else []
        budget -= len(reps_idx)

        # ── 게이트웨이#1 결정론 신호 (core 기준) ──
        domains = {C.domain_of(m.get("url", "")) for m in core_members}
        domains.discard("")
        corroboration = len(domains) if domains else len({m.get("source") for m in core_members})
        max_trust = max((float(m.get("trust", 1.0)) for m in core_members), default=1.0)
        recencies = [d for d in (_recency_days(m.get("published"), date) for m in core_members) if d is not None]
        recency_days = min(recencies) if recencies else None

        outliers_total += len(outliers)
        manifest["coherent"].append({
            "cluster_id": cid,
            "size": size,
            "cohesion": round(coh, 3),
            "audience": sorted({a for m in core_members for a in m.get("audience", [])}),
            "keywords": _keywords(core_members),
            "corroboration": corroboration,
            "max_trust": round(max_trust, 2),
            "recency_days": recency_days,
            "gate_hint": _gate_hint(corroboration, max_trust),
            "representatives": [_rep_view(items[i], full_summary=True) for i in reps_idx],
            "core_member_ids": [items[i].get("key") for i in core],
            "all_member_ids": [items[i].get("key") for i in comp],
            "excluded_outliers": [
                {"key": items[i].get("key"), "title": items[i].get("title"),
                 "centroid_sim": round(csims[i], 3)}
                for i in outliers
            ],
        })
        cid += 1

    for i in sorted(loose_idx):
        v = _rep_view(items[i], full_summary=False)
        v["recency_days"] = _recency_days(items[i].get("published"), date)
        v["gate_hint"] = "single-source"
        manifest["loose"].append(v)

    sampled = sum(len(c["representatives"]) for c in manifest["coherent"])
    manifest["stats"].update(
        clusters=len(components),
        coherent=len(manifest["coherent"]),
        sampled=sampled,
        outliers_excluded=outliers_total,
    )
    return manifest


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_items(date: str) -> list[dict]:
    path = C.ROOT / "raw" / "feeds" / date / "items.jsonl"
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def latest_date() -> str | None:
    feeds_dir = C.ROOT / "raw" / "feeds"
    if not feeds_dir.exists():
        return None
    dates = sorted(p.name for p in feeds_dir.iterdir() if p.is_dir() and (p / "items.jsonl").exists())
    return dates[-1] if dates else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="tech-news-wiki 클러스터링")
    ap.add_argument("--date", default=None, help="대상 날짜(YYYY-MM-DD). 생략 시 최신")
    ap.add_argument("--config", default=None, help="sources.toml 경로")
    args = ap.parse_args(argv)

    try:
        cfg = C.load_config(args.config).cluster
    except (OSError, ValueError) as e:
        print(f"[config-error] {e}", file=sys.stderr)
        return 1

    date = args.date or latest_date()
    if not date:
        print("[error] 수집된 날짜가 없습니다. 먼저 fetch.py 를 실행하세요.", file=sys.stderr)
        return 1

    items = load_items(date)
    manifest = cluster_items(items, cfg, date)

    out_path = C.ROOT / "raw" / "feeds" / date / "clusters.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    st = manifest["stats"]
    print("\n=== 클러스터링 요약 ===")
    print(f"날짜: {date}  항목: {st['items']}  클러스터: {st['clusters']}  "
          f"coherent: {st['coherent']}  대표 샘플: {st['sampled']}  "
          f"거리게이트 제외: {st.get('outliers_excluded', 0)}  loose: {len(manifest['loose'])}")
    for c in manifest["coherent"]:
        kw = ", ".join(c["keywords"][:4])
        print(f"  · #{c['cluster_id']} size={c['size']} coh={c['cohesion']} "
              f"reps={len(c['representatives'])} hint={c['gate_hint']} "
              f"corrob={c['corroboration']} outliers={len(c['excluded_outliers'])}  [{kw}]")
    print(f"→ {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
