# tech-news-wiki

테크 뉴스를 자동 수집하고, 클러스터링으로 압축한 뒤, **두 단계 검토 게이트웨이**를 거쳐 LLM이
**개발자·PO 관점**으로 큐레이션하는 누적형 지식 위키. Karpathy의
[wiki-llm](https://gist.github.com/karpathy) 패턴 위에 수집·클러스터링·검증 파이프라인을 얹었다.

## 어떻게 동작하나 (5단계 파이프라인)

```
sources.toml ─► fetch.py ─► items.jsonl ─► cluster.py ─► clusters.json ─► 게이트웨이#1 ─► wiki ingest ─► 게이트웨이#2
 (소스+trust)   (httpx+     (trust 포함)   (TF-IDF 링 +   (거리게이트+       (신뢰도·타당성  (wiki/ 페이지)  (graphify
               feedparser)               응집도게이트+   게이트신호)         ·정합성, 하이브)                지식그래프)
                                         거리게이트)
```

1. **수집** — 피드를 긁어 중복 제거, 소스별 `trust`(신뢰도 prior) 부착. 일시 오류(5xx·429·
   YouTube 간헐 404)는 자동 재시도.
2. **클러스터링(+거리 게이트)** — 비슷한 기사를 묶고, 클러스터 **중심에서 너무 먼 항목은 대표
   샘플에서 제외**(`excluded_outliers`). 각 클러스터에 게이트 신호(corroboration·max_trust·gate_hint) 부여.
3. **검토 게이트웨이 #1** — 위키화 전, 항목마다 **데이터 신뢰도·문장 타당성·글 전체 정합성** 3축으로
   판정(결정론 신호 + LLM 의미 판단). pass 만 ingest, 판정은 구조화 로그로 기록.
4. **wiki ingest** — 통과분으로 일일 디제스트 + 개념/엔티티/툴 페이지 생성·갱신.
5. **검토 게이트웨이 #2** — `graphify` 지식그래프로 모순·고립·이상 허브를 점검하고 되먹임.

규칙 전문은 [`CLAUDE.md`](./CLAUDE.md).

## 셋업

```bash
uv sync            # 의존성 설치 (httpx, feedparser, scikit-learn)
uv run pytest      # 단위 테스트 (네트워크 불필요)
```

게이트웨이#2는 [`graphify`](https://pypi.org/project/graphifyy/) CLI(v0.9.4)를 쓴다.
백엔드는 **`claude-cli`** — 로컬 `claude`(Claude Code) 구독 인증으로 동작하므로 **별도 API 키가
필요 없다**. `uv tool install graphifyy`로 설치.

## 사용법

### 트리거 키워드 (Claude Code 세션에서)

이 프로젝트 디렉토리에서 Claude Code를 열고 아래처럼 말하면 `CLAUDE.md`의 규칙에 따라 동작한다.

| 말하는 것 | 동작 | CLAUDE.md |
| --- | --- | --- |
| **"수집해줘"** / **"오늘 뉴스 정리해줘"** | 5단계 파이프라인 전체 실행: fetch → cluster → 게이트웨이#1 → digest·위키 페이지 생성 → graphify 검증. 끝나면 생성/갱신/탈락 항목을 요약 보고 | §2 |
| **질문** (예: "요즘 에이전트 인프라 동향은?") | `index.md` → 관련 위키 페이지를 읽고 출처와 함께 답변. 의미 있으면 `wiki/syntheses/`에 저장 | §7 |
| **"lint"** / **"위키 점검"** | 모순·stale·orphan·missing·gap 체크리스트 보고 | §8 |
| **"완전 초기화"** / **"재구축"** | `.bak-날짜/`로 백업 후 재생성 (즉시 삭제 금지) | §1 |

- 같은 날 "수집해줘"를 다시 하면 **멱등**하게 동작한다 — 기존 디제스트를 덮지 않고 신규 항목만 병합.
- 이미 수집된 항목은 `state/seen.jsonl`에 기록돼 재수집되지 않는다.

### 스크립트 직접 실행 (Stage 1–2만)

LLM 없이 수집·클러스터링만 돌릴 수도 있다:

```bash
# 1) 수집 — 신규 항목을 raw/feeds/오늘/items.jsonl 에 저장
uv run scripts/fetch.py
#   --source "GeekNews"     특정 피드만 (반복 지정 가능)
#   --since 2026-06-01      해당 날짜 이후 게시물만
#   --limit 20              피드당 최대 신규 항목 수
#   --dry-run               저장하지 않고 수집 결과만 확인

# 2) 클러스터링 — clusters.json 매니페스트 생성
uv run scripts/cluster.py            # --date YYYY-MM-DD 로 특정 날짜 지정 가능
```

그다음 Claude에게 "오늘 뉴스 정리해줘"라고 하면 이미 만들어진 `clusters.json`부터 이어서 진행한다.

### 지식그래프 조회 (게이트웨이#2 산출물)

```bash
graphify query "에이전틱 인터넷과 관련된 회사는?"   # 의미 질의
graphify path "Cloudflare" "Stripe"                # 두 노드 사이 관계 경로
graphify explain "GitHub Copilot"                  # 노드와 이웃 설명
graphify diagnose multigraph                       # 그래프 건강도 점검
```

그래프 재빌드(콘텐츠가 크게 바뀐 뒤에만):

```bash
GRAPHIFY_CLAUDE_CLI_MODEL=haiku graphify extract wiki --out . --backend claude-cli
GRAPHIFY_CLAUDE_CLI_MODEL=haiku graphify cluster-only . --backend claude-cli
```

### 단계별 모델 정책

| 단계 | 실행 주체 | 모델 | 이유 |
| --- | --- | --- | --- |
| 1–2 수집·클러스터링 | Python (uv) | 없음 | TF-IDF·규칙 기반 — LLM 불필요 |
| 3–4 게이트웨이#1·ingest | Claude Code 세션 | 세션 메인 모델 | 신뢰도·정합성 판정은 의미 판단이 본질 |
| 5 graphify | `claude-cli` 백엔드 | haiku (`GRAPHIFY_CLAUDE_CLI_MODEL`) | 구조화 추출·라벨링은 기계적 — 저비용 모델로 충분 |

## 소스 추가/편집

`scripts/sources.toml`의 `[[feed]]` 블록을 편집한다. `kind`는 `rss`/`atom`/`youtube`,
`audience`는 `["dev"]`/`["po"]`/둘 다. `weight`(클러스터 tiebreak)와 별개로 **`trust`**(데이터
신뢰도 prior, 기본 1.0 · 회사 공식 1.2 · 애그리게이터 0.9)를 줄 수 있다 — 게이트웨이#1에 반영된다.
YouTube는 `channel_id`만 주면 피드 URL이 자동 조립된다. 잘못된 항목은 실행 시 자동 검증되어 비활성
처리되고 경고가 뜬다(전체 실행은 계속). `[cluster]`의 `member_sim_min`으로 거리 게이트 강도를 조절한다.

## 디렉토리

| 경로 | 설명 |
| --- | --- |
| `scripts/` | 수집·클러스터링 파이프라인 |
| `state/seen.jsonl` | 중복 제거 인덱스 (커밋됨, 유실 시 raw에서 자동 복구) |
| `raw/` | 수집 원본 — **불변, 비신뢰 데이터** |
| `wiki/` | LLM이 만든 큐레이션 페이지 |
| `graphify-out/` | 게이트웨이#2 지식그래프 산출물 (gitignore) |
| `index.md` / `log.md` | 카탈로그 / 활동 로그 |
| `ORDER.md` | 문서 기반 지시 창구 (`## 신규 지시`에 적으면 처리 후 봉인) |

## 범위

**현재:** RSS/Atom/YouTube 수집(일시 오류 재시도) · 복구 가능한 중복 제거 · 클러스터링+응집도
게이트+**centroid 거리 게이트** · 소스 `trust` prior · **검토 게이트웨이#1**(신뢰도·타당성·정합성) ·
**게이트웨이#2**(graphify 지식그래프, claude-cli 백엔드) · 멱등 일일 디제스트. 수동 트리거.

**후속(deferred):** velopers.kr 등 비표준 피드 스크레이핑 · endoflife.date API 어댑터 ·
cron 자동 스케줄링 · 다국어 임베딩(교차언어 클러스터링).

> Obsidian으로 이 폴더를 vault로 열면 wikilink 그래프를 탐색할 수 있다.
