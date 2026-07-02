from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import common as C  # noqa: E402
import cluster as CL  # noqa: E402


def _item(key, title, summary="", source="S", weight=1.0, audience=("dev",)):
    return {
        "key": key, "title": title, "summary": summary, "source": source,
        "url": f"https://ex.com/{key}", "published": "2026-06-01T00:00:00+00:00",
        "weight": weight, "audience": list(audience),
    }


def test_empty_and_singleton():
    cfg = C.ClusterConfig()
    m0 = CL.cluster_items([], cfg, "2026-06-01")
    assert m0["stats"]["items"] == 0 and not m0["coherent"] and not m0["loose"]

    m1 = CL.cluster_items([_item("a", "solo story")], cfg, "2026-06-01")
    assert len(m1["loose"]) == 1 and not m1["coherent"]


def test_duplicates_form_coherent_cluster():
    cfg = C.ClusterConfig(sim_link=0.35, cohesion_threshold=0.5, sample_k=1, max_samples=40)
    items = [
        _item("a", "OpenAI releases GPT-6 with new reasoning", "big model launch"),
        _item("b", "OpenAI releases GPT-6 with new reasoning", "big model launch"),
        _item("c", "완전히 다른 한국어 기사 제목입니다 데브옵스", "쿠버네티스 이야기"),
    ]
    m = CL.cluster_items(items, cfg, "2026-06-01")
    assert m["stats"]["coherent"] == 1
    coh = m["coherent"][0]
    assert coh["size"] == 2
    assert coh["cohesion"] >= 0.5
    assert len(coh["representatives"]) == 1
    # 대표는 full summary 포함
    assert "summary" in coh["representatives"][0]
    # 유니크 한국어 기사는 loose
    assert any(x["key"] == "c" for x in m["loose"])


def test_low_cohesion_goes_loose():
    # 임계값을 비현실적으로 높이면 어떤 것도 coherent 가 되지 않는다
    cfg = C.ClusterConfig(sim_link=0.05, cohesion_threshold=0.999)
    items = [
        _item("a", "rust memory safety"),
        _item("b", "python typing news"),
        _item("c", "go generics update"),
    ]
    m = CL.cluster_items(items, cfg, "2026-06-01")
    assert m["stats"]["coherent"] == 0
    assert len(m["loose"]) == 3


def test_max_samples_budget_enforced():
    cfg = C.ClusterConfig(sim_link=0.3, cohesion_threshold=0.5, sample_k=2, max_samples=3)
    items = []
    # 4개의 뚜렷한 중복쌍 클러스터 (각 size 2)
    for g in range(4):
        t = f"topic{g} " + "word " * (g + 1)
        items.append(_item(f"{g}a", t + "alpha", t))
        items.append(_item(f"{g}b", t + "beta", t))
    m = CL.cluster_items(items, cfg, "2026-06-01")
    assert m["stats"]["sampled"] <= cfg.max_samples


def test_loose_summary_is_truncated():
    cfg = C.ClusterConfig()
    long_sum = "가" * 300
    m = CL.cluster_items([_item("a", "solo", long_sum)], cfg, "2026-06-01")
    s = m["loose"][0]["summary"]
    assert s.endswith("…") and len(s) <= 141


def test_gate_hint_decision_table():
    assert CL._gate_hint(2, 1.0) == "strong"
    assert CL._gate_hint(3, 1.2) == "strong"
    assert CL._gate_hint(2, 0.9) == "check"       # 다출처지만 저신뢰
    assert CL._gate_hint(1, 1.2) == "single-source"
    assert CL._gate_hint(0, 1.2) == "check"


def test_recency_days_handles_missing_and_future():
    assert CL._recency_days(None, "2026-07-02") is None
    assert CL._recency_days("not-a-date", "2026-07-02") is None
    assert CL._recency_days("2026-07-01T00:00:00+00:00", "2026-07-02") == 1
    assert CL._recency_days("2026-08-01", "2026-07-02") == 0   # 미래 → 0 클램프


def _it(key, title, dom="ex.com", trust=1.0, summary=None):
    return {
        "key": key, "title": title, "summary": summary if summary is not None else title,
        "source": key, "url": f"https://{dom}/{key}",
        "published": "2026-06-01T00:00:00+00:00", "weight": 1.0, "trust": trust,
        "audience": ["dev"],
    }


def test_distance_gate_excludes_centroid_outlier():
    # a,b,c 는 사실상 동일(중심에 가깝다). d 는 일부 단어만 공유해 클러스터에 연결되지만
    # centroid 로부터 멀다 → 거리 게이트로 대표 샘플에서 제외되어야 한다.
    base = "distributed systems consensus raft protocol leader election log replication"
    items = [
        _it("a", base), _it("b", base), _it("c", base),
        _it("d", "distributed systems overview"),
    ]
    cfg = C.ClusterConfig(sim_link=0.1, cohesion_threshold=0.3,
                          member_sim_min=0.6, sample_k=3, max_samples=40)
    m = CL.cluster_items(items, cfg, "2026-06-01")
    assert m["stats"]["coherent"] == 1
    coh = m["coherent"][0]
    excluded = {o["key"] for o in coh["excluded_outliers"]}
    assert "d" in excluded                              # 아웃라이어 제외
    assert "d" not in coh["core_member_ids"]
    assert "d" in coh["all_member_ids"]                 # 전체엔 보존(투명성)
    assert all(r["key"] != "d" for r in coh["representatives"])
    assert m["stats"]["outliers_excluded"] >= 1


def test_distance_gate_small_cluster_fallback():
    # 2-멤버 클러스터에서 member_sim_min 을 극단으로 높여도 게이트가 클러스터를 붕괴시키면 안 된다.
    items = [
        _it("a", "graphql federation gateway schema stitching"),
        _it("b", "graphql federation gateway schema design"),
    ]
    cfg = C.ClusterConfig(sim_link=0.15, cohesion_threshold=0.2,
                          member_sim_min=0.99, sample_k=2, max_samples=40)
    m = CL.cluster_items(items, cfg, "2026-06-01")
    assert m["stats"]["coherent"] == 1                  # 붕괴하지 않음
    coh = m["coherent"][0]
    assert coh["excluded_outliers"] == []               # 폴백: 아무도 제외 안 됨
    assert set(coh["core_member_ids"]) == {"a", "b"}


def test_corroboration_counts_distinct_domains():
    # 동일 스토리, alpha.com(2) + beta.com(1) → distinct 도메인 2 → strong
    items = [
        _it("a", "same big product launch story", dom="alpha.com", trust=1.2),
        _it("b", "same big product launch story", dom="beta.com", trust=1.2),
        _it("c", "same big product launch story", dom="alpha.com", trust=1.2),
    ]
    cfg = C.ClusterConfig(sim_link=0.3, cohesion_threshold=0.5,
                          member_sim_min=0.0, sample_k=3, max_samples=40)
    m = CL.cluster_items(items, cfg, "2026-06-01")
    coh = m["coherent"][0]
    assert coh["corroboration"] == 2
    assert coh["max_trust"] == 1.2
    assert coh["gate_hint"] == "strong"


def test_keywords_extracted_and_stopwords_removed():
    cfg = C.ClusterConfig(sim_link=0.35, cohesion_threshold=0.4)
    items = [
        _item("a", "kubernetes scaling the new cluster", "kubernetes and the cluster"),
        _item("b", "kubernetes scaling the new cluster", "kubernetes and the cluster"),
    ]
    m = CL.cluster_items(items, cfg, "2026-06-01")
    kws = m["coherent"][0]["keywords"]
    assert "kubernetes" in kws
    assert "the" not in kws and "new" not in kws  # 스톱워드 제거
