# 활동 로그 (log)

append-only, 시간순(오래된 것 위 → 새 것 아래). 항목 prefix:
`## [YYYY-MM-DD] {kind} | {제목}` (`kind` ∈ `ingest`, `query`, `lint`, `meta`).

## [2026-07-02] meta | ORD-002 — 5단계 게이트웨이 파이프라인으로 완전 재구축

ORDER.md ORD-002 지시("처음부터 다시 구축")에 따라 위키 환경을 재구축.
- 기존 wiki/·raw/·state/index/log 는 `.bak-2026-07-02/`로 백업 후 초기화.
- 파이프라인을 5단계로 확장: 수집 → 클러스터링(**거리 게이트** 추가) → **검토 게이트웨이#1**
  (신뢰도·타당성·정합성, 하이브리드) → wiki ingest → **검토 게이트웨이#2**(graphify 지식그래프).
- `cluster.py`: centroid 거리 게이트(`member_sim_min`)·게이트 신호(corroboration·max_trust·
  recency_days·gate_hint)·`excluded_outliers` 추가. `common.py`/`fetch.py`: 소스 `trust` prior 배선.
- `sources.toml`: 회사 엔지니어링/테크 블로그 소스 추가(Netflix·Cloudflare·Meta·AWS·Stripe·
  우아한형제들·카카오·토스 등), `trust` 필드 도입.
- 테스트 38개 통과(거리 게이트·gate_hint 결정표·trust 신규 포함).

## [2026-07-02] ingest | 첫 재구축 digest (Sonnet 5·Cloudflare 에이전틱 인터넷·GitHub Models 종료)

608항목 수집 → 클러스터링(coherent 7·loose 593·거리게이트 제외 0) → 게이트웨이#1 적용 → ingest.
- 생성: [[digests/2026-07-02]], [[Cloudflare]], [[Anthropic]], [[에이전틱 인터넷]], [[github-copilot]],
  [[tech-news-feeds]].
- 게이트웨이#1: pass(Cloudflare 수익화·Sonnet 5·GitHub Models EOL·Godot AI정책·Coinbase 회고 등),
  hold(Fable 5 세부·jj 마이크로팁), drop(국장 리밸런싱·HN Who is hiring). 상세는 digest `## 게이트 로그`.
- 실패 피드 3(YouTube: ThePrimeagen 404·TechWorld/Google 일시적 500).

## [2026-07-02] lint | 게이트웨이#2 (graphify 지식그래프 검증)

`graphify extract wiki --out . --backend gemini`로 위키 그래프 생성 후 점검.
- 결과: 10 노드 · 10 엣지 · 3 커뮤니티, **orphan 0 · 모순 0 · 이상 허브 없음**(허브=에이전틱 인터넷·Digest,
  의도된 중심). 하이퍼엣지 2건("Agentic Internet Infrastructure & Commerce", "GitHub AI Product Strategy Shift")이
  큐레이션 주제와 일치 → 위키 정합성 확인.
- 되먹임: 자동 수정 불필요(깨진 링크·orphan 없음). **gap**: `Stripe`는 언급되나 전용 엔티티 페이지 없음(후속 후보).
- 산출물 `graphify-out/`(gitignore). graphify 스킬 등록·CLAUDE.md §11 배선 완료.
## [2026-07-02] meta | 운영 보완 — YouTube 재시도·graphify claude-cli 전환·README 사용법

사용자 피드백 4건 반영.
- **YouTube 피드**: 6채널 ID 전부 정확함을 피드 제목 대조로 확인. 실패 원인은 YouTube 엣지 서버의
  간헐적 404/500 → `fetch.py`에 재시도 로직(5xx·429·youtube.com 404, 백오프) 추가. dry-run 6/6 성공.
- **graphify 백엔드**: gemini(+venv에 openai 주입) → **claude-cli**(Claude Code 구독 인증, API 키
  불필요)로 전환, 주입했던 openai 패키지 제거. `GRAPHIFY_CLAUDE_CLI_MODEL=haiku`로 재빌드 —
  11노드·16엣지·orphan 0, 이전에 실패했던 커뮤니티 라벨링도 성공.
- **모델 정책 명문화**: CLAUDE.md §11에 단계별 모델 정책(1–2 Python 무LLM / 3–4 세션 메인 모델 /
  5 claude-cli+haiku) 추가.
- **README 재작성**: 트리거 키워드 표(수집해줘·질문·lint·재구축)·스크립트 옵션·그래프 조회·모델
  정책 상세화. 테스트 41개 통과(재시도 3건 신규).
