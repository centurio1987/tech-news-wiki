import types
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import common as C  # noqa: E402
import fetch as F  # noqa: E402


def _feed():
    return C.Feed(name="S", url="https://s.com/rss", kind="rss", audience=["dev"], lang="en", weight=1.0)


def test_entry_to_item_normalizes_and_keys():
    import time
    entry = types.SimpleNamespace(
        title="<b>Hello</b> &amp; World",
        link="https://s.com/a?utm_source=x&id=1",
        id="guid-1",
        summary="<p>body</p>",
        published_parsed=time.strptime("2026-06-01 00:00:00", "%Y-%m-%d %H:%M:%S"),
    )
    item = F.entry_to_item(_feed(), entry, "2026-06-01T09:00:00+09:00", "2026-06-01")
    assert item["url"] == "https://s.com/a?id=1"       # 추적 파라미터 제거
    assert "<" not in item["title"] and "&amp;" not in item["title"]
    assert item["published"].startswith("2026-06-01")
    assert item["key"]  # guid 기반 안정 키


def test_entry_to_item_propagates_trust():
    import time
    feed = C.Feed(name="S", url="https://s.com/rss", kind="rss", audience=["dev"],
                  lang="en", weight=1.0, trust=1.2)
    entry = types.SimpleNamespace(
        title="T", link="https://s.com/a", id="g",
        summary="s", published_parsed=time.strptime("2026-06-01 00:00:00", "%Y-%m-%d %H:%M:%S"),
    )
    item = F.entry_to_item(feed, entry, "2026-06-01T09:00:00+09:00", "2026-06-01")
    assert item["trust"] == 1.2


def test_passes_since():
    it = {"published": "2026-06-05T00:00:00+00:00"}
    assert F.passes_since(it, "2026-06-01")
    assert not F.passes_since(it, "2026-06-10")
    assert F.passes_since({"published": None}, "2026-06-10")  # 미상은 포함
    assert F.passes_since(it, None)


def test_prune_seen_drops_old(monkeypatch):
    from datetime import datetime, timezone, timedelta
    fixed = datetime(2026, 6, 30, tzinfo=timezone(timedelta(hours=9)))
    monkeypatch.setattr(C, "now_kst", lambda: fixed)
    seen = {"recent": "2026-06-20", "old": "2026-01-01"}
    kept = F.prune_seen(seen)
    assert "recent" in kept and "old" not in kept


def test_seen_roundtrip_and_rebuild(tmp_path, monkeypatch):
    # ROOT 를 임시 디렉토리로 돌려 파일 I/O 격리
    monkeypatch.setattr(C, "ROOT", tmp_path)
    (tmp_path / "state").mkdir()
    seen = {"k1": "2026-06-01", "k2": "2026-06-02"}
    F.write_seen_atomic(seen)
    assert F.load_seen() == seen

    # raw items 로부터 재구성
    d = tmp_path / "raw" / "feeds" / "2026-06-03"
    d.mkdir(parents=True)
    import json
    (d / "items.jsonl").write_text(
        json.dumps({"key": "k3", "fetched_date": "2026-06-03"}) + "\n", encoding="utf-8")
    rebuilt = F.rebuild_seen_from_raw()
    assert rebuilt == {"k3": "2026-06-03"}


def test_load_seen_skips_corrupt_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ROOT", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "seen.jsonl").write_text(
        '{"key":"ok","date":"2026-06-01"}\nNOT JSON\n\n{"nokey":1}\n', encoding="utf-8")
    assert F.load_seen() == {"ok": "2026-06-01"}


def test_fetch_retries_youtube_transient_404(monkeypatch):
    import httpx
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(404)
        return httpx.Response(200, content=b"<feed/>")

    url = "https://www.youtube.com/feeds/videos.xml?channel_id=X"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert F.fetch_feed_bytes(client, url) == b"<feed/>"
    assert calls["n"] == 3


def test_fetch_no_retry_on_permanent_404(monkeypatch):
    import httpx
    import pytest
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            F.fetch_feed_bytes(client, "https://example.com/feed")
    assert calls["n"] == 1  # 일반 404 는 영구 오류 — 재시도 없음


def test_fetch_retries_500_then_gives_up(monkeypatch):
    import httpx
    import pytest
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            F.fetch_feed_bytes(client, "https://example.com/feed")
    assert calls["n"] == 1 + F.FETCH_RETRIES
