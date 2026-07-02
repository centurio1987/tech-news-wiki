import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import common as C  # noqa: E402


def test_normalize_url_strips_tracking_and_fragment():
    a = C.normalize_url("https://Example.com/Post/?utm_source=x&id=7#frag")
    assert a == "https://example.com/Post?id=7"


def test_normalize_url_sorts_query_and_trailing_slash():
    a = C.normalize_url("http://ex.com/p/?b=2&a=1")
    b = C.normalize_url("http://ex.com/p?a=1&b=2")
    assert a == b


def test_normalize_url_default_port_removed():
    assert C.normalize_url("https://ex.com:443/x") == "https://ex.com/x"


def test_strip_html_removes_tags_entities_and_limits():
    out = C.strip_html("<p>Hello&amp; <b>World</b></p>\n\ttrail", max_len=100)
    assert "<" not in out and ">" not in out
    assert "&amp;" not in out and "Hello&" in out
    assert "  " not in out  # 공백 정리


def test_strip_html_truncates():
    out = C.strip_html("x" * 50, max_len=10)
    assert out.endswith("…") and len(out) <= 11


def test_slugify_blocks_path_traversal():
    s = C.slugify("../../etc/passwd")
    assert "/" not in s and ".." not in s


def test_slugify_keeps_korean_and_hyphenates():
    assert C.slugify("관찰자 패턴 Observer") == "관찰자-패턴-Observer"


def test_slugify_empty_defaults():
    assert C.slugify("") == "untitled"
    assert C.slugify("!@#$%") == "untitled"


def test_dedup_key_prefers_guid():
    k1 = C.dedup_key(guid="g1", url="http://a/x", source="S", title="T", published="2026-01-01")
    k2 = C.dedup_key(guid="g1", url="http://different", source="OTHER", title="Z", published=None)
    assert k1 == k2  # guid 동일 → 같은 키


def test_dedup_key_falls_back_to_normalized_url():
    k1 = C.dedup_key(guid=None, url="http://a/x?utm_source=q", source="S", title="T", published=None)
    k2 = C.dedup_key(guid=None, url="http://a/x", source="S2", title="T2", published=None)
    assert k1 == k2  # 정규화 URL 동일


def test_dedup_key_source_title_published_last_resort():
    k1 = C.dedup_key(guid=None, url="", source="S", title="T", published="2026-01-01")
    k2 = C.dedup_key(guid=None, url="", source="S", title="T", published="2026-01-01")
    k3 = C.dedup_key(guid=None, url="", source="S", title="T", published="2026-01-02")
    assert k1 == k2 and k1 != k3


def test_struct_to_iso():
    st = time.strptime("2026-06-01 12:00:00", "%Y-%m-%d %H:%M:%S")
    iso = C.struct_to_iso(st)
    assert iso.startswith("2026-06-01T12:00:00")
    assert C.struct_to_iso(None) is None


def test_run_date_format():
    d = C.run_date()
    assert len(d) == 10 and d[4] == "-" and d[7] == "-"


def _write_toml(tmp_path, body: str) -> Path:
    p = tmp_path / "sources.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_config_valid(tmp_path):
    p = _write_toml(tmp_path, """
[[feed]]
name = "A"
url = "https://a.com/rss"
kind = "rss"
audience = ["dev"]

[cluster]
sim_link = 0.4
cohesion_threshold = 0.6
""")
    cfg = C.load_config(p)
    assert len(cfg.feeds) == 1
    assert cfg.cluster.sim_link == 0.4 and cfg.cluster.cohesion_threshold == 0.6


def test_load_config_skips_invalid_but_keeps_valid(tmp_path):
    p = _write_toml(tmp_path, """
[[feed]]
name = "Good"
url = "https://a.com/rss"
kind = "rss"
audience = ["dev"]

[[feed]]
name = "BadKind"
url = "https://b.com/rss"
kind = "gopher"
audience = ["dev"]

[[feed]]
name = "BadAudience"
url = "https://c.com/rss"
kind = "rss"
audience = ["ceo"]

[[feed]]
name = "Good"
url = "https://dup.com/rss"
kind = "rss"
audience = ["dev"]
""")
    cfg = C.load_config(p)
    names = [f.name for f in cfg.feeds]
    assert names == ["Good"]
    assert len(cfg.warnings) == 3  # BadKind, BadAudience, 중복 Good


def test_load_config_youtube_url_assembled(tmp_path):
    p = _write_toml(tmp_path, """
[[feed]]
name = "YT"
kind = "youtube"
channel_id = "UC123"
audience = ["dev"]
""")
    cfg = C.load_config(p)
    assert cfg.feeds[0].url.endswith("channel_id=UC123")


def test_load_config_trust_default_and_parsed(tmp_path):
    p = _write_toml(tmp_path, """
[[feed]]
name = "Default"
url = "https://a.com/rss"
kind = "rss"
audience = ["dev"]

[[feed]]
name = "Trusted"
url = "https://b.com/rss"
kind = "rss"
audience = ["dev"]
trust = 1.2
""")
    cfg = C.load_config(p)
    by = {f.name: f for f in cfg.feeds}
    assert by["Default"].trust == 1.0      # 기본 1.0 (weight 아님)
    assert by["Trusted"].trust == 1.2


def test_load_config_skips_out_of_range_trust(tmp_path):
    p = _write_toml(tmp_path, """
[[feed]]
name = "Good"
url = "https://a.com/rss"
kind = "rss"
audience = ["dev"]

[[feed]]
name = "BadTrust"
url = "https://b.com/rss"
kind = "rss"
audience = ["dev"]
trust = 0
""")
    cfg = C.load_config(p)
    assert [f.name for f in cfg.feeds] == ["Good"]
    assert any("trust" in w for w in cfg.warnings)


def test_load_config_member_sim_min(tmp_path):
    p = _write_toml(tmp_path, """
[[feed]]
name = "A"
url = "https://a.com/rss"
kind = "rss"
audience = ["dev"]

[cluster]
member_sim_min = 0.42
""")
    cfg = C.load_config(p)
    assert cfg.cluster.member_sim_min == 0.42
    # 미지정 시 기본
    p2 = _write_toml(tmp_path / "d2" if False else tmp_path, """
[[feed]]
name = "A"
url = "https://a.com/rss"
kind = "rss"
audience = ["dev"]
""")
    assert C.load_config(p2).cluster.member_sim_min == 0.30


def test_domain_of():
    assert C.domain_of("https://www.uber.com/blog/x") == "uber.com"
    assert C.domain_of("https://engineering.fb.com/2026/x/") == "engineering.fb.com"
    assert C.domain_of("http://user@host.com:8080/p") == "host.com"
    assert C.domain_of("") == ""


def test_load_config_raises_when_no_valid_feed(tmp_path):
    p = _write_toml(tmp_path, """
[[feed]]
name = "OnlyBad"
kind = "nope"
audience = ["dev"]
url = "https://x"
""")
    try:
        C.load_config(p)
        assert False, "should raise"
    except ValueError:
        pass
