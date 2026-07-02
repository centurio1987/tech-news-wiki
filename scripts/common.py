"""공용 유틸리티: 설정 로딩·검증, 정규화, slug, HTML 제거, dedup 키, 날짜 처리.

fetch.py / cluster.py 가 공유한다. 네트워크 의존성이 없어 단위 테스트가 쉽다.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

# 프로젝트 루트 = 이 파일(scripts/common.py)의 부모의 부모
ROOT = Path(__file__).resolve().parent.parent

KST = timezone(timedelta(hours=9))

ALLOWED_KINDS = {"rss", "atom", "youtube"}
ALLOWED_AUDIENCE = {"dev", "po"}

# URL 정규화 시 제거할 추적 쿼리 파라미터
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "utm_reader", "utm_brand", "utm_social",
    "fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src",
    "source", "cmpid", "sr_share",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SLUG_STRIP_RE = re.compile(r"[^0-9A-Za-z가-힣\- ]+")


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

@dataclass
class Feed:
    name: str
    url: str
    kind: str
    audience: list[str]
    lang: str = "en"
    weight: float = 1.0
    trust: float = 1.0            # 데이터 신뢰도 prior (게이트웨이#1). weight(클러스터 tiebreak)와 별개.
    channel_id: str | None = None


@dataclass
class ClusterConfig:
    sim_link: float = 0.35
    cohesion_threshold: float = 0.5
    sample_k: int = 1
    max_samples: int = 40
    member_sim_min: float = 0.30   # 거리 게이트: centroid 코사인이 이 미만인 멤버는 대표 샘플에서 제외


@dataclass
class Config:
    feeds: list[Feed]
    cluster: ClusterConfig
    warnings: list[str] = field(default_factory=list)


YOUTUBE_FEED_TMPL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def resolve_feed_url(raw: dict[str, Any]) -> str:
    """youtube kind 는 channel_id 로 Atom 피드 URL 을 조립한다."""
    if raw.get("kind") == "youtube" and raw.get("channel_id"):
        return YOUTUBE_FEED_TMPL.format(channel_id=raw["channel_id"])
    return str(raw.get("url", "")).strip()


def load_config(path: Path | str | None = None) -> Config:
    """sources.toml 을 로드하고 스키마를 검증한다.

    잘못된 피드 항목은 비활성 처리(제외)하고 warnings 에 사유를 남긴다.
    전체 실행을 중단시키지 않는다(크래시 금지). 단, 최상위 구조가 깨졌거나
    유효한 피드가 하나도 없으면 ValueError 를 던진다.
    """
    path = Path(path) if path else ROOT / "scripts" / "sources.toml"
    with open(path, "rb") as fh:
        data = tomllib.load(fh)

    warnings: list[str] = []
    feeds: list[Feed] = []
    seen_names: set[str] = set()
    seen_urls: set[str] = set()

    raw_feeds = data.get("feed", [])
    if not isinstance(raw_feeds, list):
        raise ValueError("sources.toml: [[feed]] 배열이 필요합니다.")

    for i, rf in enumerate(raw_feeds):
        name = str(rf.get("name", "")).strip()
        label = name or f"#{i}"
        kind = str(rf.get("kind", "")).strip().lower()
        url = resolve_feed_url(rf)
        audience = rf.get("audience", [])

        if not name:
            warnings.append(f"[skip] 이름 없는 피드(#{i}) — name 필수")
            continue
        if kind not in ALLOWED_KINDS:
            warnings.append(f"[skip] {label}: kind '{kind}' 미허용 (허용: {sorted(ALLOWED_KINDS)})")
            continue
        if not url:
            warnings.append(f"[skip] {label}: url(또는 youtube channel_id) 필요")
            continue
        if not isinstance(audience, list) or not audience:
            warnings.append(f"[skip] {label}: audience 는 비어있지 않은 리스트여야 함")
            continue
        bad_aud = [a for a in audience if a not in ALLOWED_AUDIENCE]
        if bad_aud:
            warnings.append(f"[skip] {label}: audience {bad_aud} 미허용 (허용: {sorted(ALLOWED_AUDIENCE)})")
            continue
        try:
            weight = float(rf.get("weight", 1.0))
        except (TypeError, ValueError):
            warnings.append(f"[skip] {label}: weight 가 숫자가 아님")
            continue
        if not (0.0 < weight <= 10.0):
            warnings.append(f"[skip] {label}: weight {weight} 범위 밖 (0<w<=10)")
            continue
        try:
            trust = float(rf.get("trust", 1.0))
        except (TypeError, ValueError):
            warnings.append(f"[skip] {label}: trust 가 숫자가 아님")
            continue
        if not (0.0 < trust <= 10.0):
            warnings.append(f"[skip] {label}: trust {trust} 범위 밖 (0<t<=10)")
            continue
        if name in seen_names:
            warnings.append(f"[skip] {label}: 중복 name")
            continue
        if url in seen_urls:
            warnings.append(f"[skip] {label}: 중복 url ({url})")
            continue

        seen_names.add(name)
        seen_urls.add(url)
        feeds.append(Feed(
            name=name, url=url, kind=kind,
            audience=[str(a) for a in audience],
            lang=str(rf.get("lang", "en")),
            weight=weight,
            trust=trust,
            channel_id=rf.get("channel_id"),
        ))

    if not feeds:
        raise ValueError("sources.toml: 유효한 피드가 하나도 없습니다.\n" + "\n".join(warnings))

    rc = data.get("cluster", {})
    cluster = ClusterConfig(
        sim_link=float(rc.get("sim_link", 0.35)),
        cohesion_threshold=float(rc.get("cohesion_threshold", 0.5)),
        sample_k=int(rc.get("sample_k", 1)),
        max_samples=int(rc.get("max_samples", 40)),
        member_sim_min=float(rc.get("member_sim_min", 0.30)),
    )
    return Config(feeds=feeds, cluster=cluster, warnings=warnings)


# ---------------------------------------------------------------------------
# 정규화 / 정제
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    """추적 파라미터 제거, fragment 제거, 스킴/호스트 소문자화, 끝 슬래시 정리."""
    if not url:
        return ""
    url = url.strip()
    parts = urlsplit(url)
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    # 기본 포트 제거
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    query.sort()
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def domain_of(url: str) -> str:
    """URL 의 호스트(도메인)를 소문자로 반환, 선행 'www.' 제거.

    게이트웨이#1 의 corroboration(독립 출처 수) 계산에 쓴다. source 이름이 아니라
    도메인을 기준으로 세어, 같은 매체의 재게시가 독립 검증처럼 부풀려지는 것을 막는다.
    호스트가 없으면 빈 문자열.
    """
    if not url:
        return ""
    netloc = urlsplit(url.strip()).netloc.lower()
    if "@" in netloc:                     # userinfo 제거
        netloc = netloc.rsplit("@", 1)[-1]
    if ":" in netloc:                     # 포트 제거
        netloc = netloc.split(":", 1)[0]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def strip_html(text: str, max_len: int = 600) -> str:
    """HTML 태그·엔티티 제거, 제어문자 제거, 공백 정리, 길이 제한.

    비신뢰 데이터를 안전한 플레인 텍스트로 축약한다.
    """
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    # 제어문자 제거 (개행/탭 포함 → 공백)
    text = "".join(ch if unicodedata.category(ch)[0] != "C" else " " for ch in text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rstrip() + "…"
    return text


def slugify(text: str, max_len: int = 80) -> str:
    """파일명/식별자용 안전 slug. 경로 순회 문자를 차단한다.

    한글은 보존, 공백은 하이픈, 나머지 특수문자는 제거. 절대 '/' 나 '..' 를 남기지 않는다.
    """
    if not text:
        return "untitled"
    text = unicodedata.normalize("NFC", text).strip()
    text = _SLUG_STRIP_RE.sub("", text)       # 허용 문자만 남김 (/, ., 등 제거)
    text = _WS_RE.sub("-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    text = text[:max_len].strip("-")
    return text or "untitled"


def dedup_key(*, guid: str | None, url: str, source: str,
              title: str, published: str | None) -> str:
    """중복 판별 키. 우선순위: guid → 정규화 URL → source+title+published.

    반환은 안정적 해시 문자열(짧고 파일 안전).
    """
    if guid and guid.strip():
        basis = "guid:" + guid.strip()
    else:
        nurl = normalize_url(url)
        if nurl:
            basis = "url:" + nurl
        else:
            basis = "stp:" + "|".join([source.strip(), title.strip(), (published or "").strip()])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 날짜
# ---------------------------------------------------------------------------

def now_kst() -> datetime:
    return datetime.now(timezone.utc).astimezone(KST)


def run_date(dt: datetime | None = None) -> str:
    """실행일(KST) YYYY-MM-DD."""
    return (dt or now_kst()).astimezone(KST).strftime("%Y-%m-%d")


def struct_to_iso(struct_time) -> str | None:
    """feedparser 의 published_parsed(time.struct_time, UTC) → ISO8601 문자열."""
    if not struct_time:
        return None
    try:
        dt = datetime(*struct_time[:6], tzinfo=timezone.utc)
        return dt.isoformat()
    except (TypeError, ValueError):
        return None
