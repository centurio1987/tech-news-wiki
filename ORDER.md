# ORDER

이 파일은 문서로 지시를 받는 창구다. 사용자는 아래 `## 신규 지시` 영역만 편집한다.
완료된 지시는 `## 처리 완료 (COMMITTED)` 영역에 봉인 블록으로 기록되며 편집하지 않는다.

## 신규 지시

<!-- 여기에 새 지시를 적으세요. 처리되면 아래 COMMITTED 영역으로 봉인 이동됩니다. -->

## 처리 완료 (COMMITTED)

<!-- ORDER:COMMITTED id=ORD-001 status=done committed=2026-07-01 -->
<!-- 봉인 구획: 편집 금지. 철회하려면 신규 지시에 reverts=ORD-001 항목을 추가하세요. -->

### ORD-001 — 테크 뉴스 수집·큐레이션 위키 프로젝트 구축 (+ 추천 소스 제안)

<!-- 원문(verbatim): 아래 블록은 신규 지시 영역의 원본을 그대로 보존한다. 수정 금지. -->

> # ORDER
>
> 테크 뉴스를 수집하여, 개발자, po에게 필요한 정보를 wiki로 정리하는 프로젝트를 만들어라. 수집 소스 항목에 더하여 추천하고 싶은 소스가 있으면 제안하라.
>
> ## 수집 소스
>
> - geek news
> - hacker news
> - lobsters
> - https://blog.bytebytego.com/feed
> - https://bensbites.beehiiv.com/feed
> - https://www.producthunt.com/feed
> - https://endoflife.date
> - https://www.velopers.kr/
> - https://awesome-blogs.petabytes.org/feeds?group=all
>
> ### Youtube
>
> | 채널                  | 특징                    |
> | --------------------- | ----------------------- |
> | Fireship              | 신기술 짧고 빠른 요약   |
> | Theo (t3.gg)          | 웹 프레임워크 트렌드    |
> | ThePrimeagen          | 시스템/언어 레벨        |
> | Awesome Open Source   | 오픈소스 프로젝트 소개  |
> | TechWorld with Nana   | DevOps/인프라           |
> | Google for Developers | 구글 공식 기술 업데이트 |

- 결과: 3-스테이지 파이프라인(수집→클러스터링→LLM 큐레이션) + LLM-wiki 구축.
  - **수집** `scripts/fetch.py` (httpx+feedparser, 복구 가능 seen 인덱스, 항목별 JSONL, CLI 계약).
  - **클러스터링** `scripts/cluster.py` (TF-IDF char n-gram → 연결요소 클러스터 → 응집도 게이트로
    대표 샘플만 LLM에 노출 → 컨텍스트 부하 절감). 매니페스트 `raw/feeds/DATE/clusters.json`.
  - **운영 스키마** `CLAUDE.md`(수집/클러스터/비신뢰 콘텐츠/멱등 규칙), `README.md`, `index.md`, `log.md`.
  - **소스** `scripts/sources.toml`: ORDER 지정 소스 반영. 수정 사항 — Ben's Bites는
    `www.bensbites.com/feed`로 교정, 요즘IT는 `/magazine/feed/`로 교정, velopers.kr(피드 경로 미확인)·
    endoflife.date(RSS 없음)는 후속 편입 대기로 주석 처리.
  - **추천 추가 소스(제안 반영)**: The Pragmatic Engineer, InfoQ, The Changelog,
    GitHub Blog/Changelog, Simon Willison, 요즘IT, Lenny's Newsletter, (Stratechery/Mind the Product 후보).
  - **검증**: 단위 테스트 28개 통과(네트워크 불필요), live smoke 21개 피드/406개 항목 수집·
    중복 제거 확인, 샘플 디제스트(`wiki/digests/2026-07-01.md`) + entities/tools/sources 페이지 생성.
  - 외부 검토(ChatGPT codex / Gemini agy) 의견을 반영해 클러스터링·복구 가능 dedup·비신뢰 콘텐츠
  규칙·fixture 테스트 등을 설계에 포함.
  <!-- /ORDER:COMMITTED id=ORD-001 -->

<!-- ORDER:COMMITTED id=ORD-002 status=done committed=2026-07-02 -->
<!-- 봉인 구획: 편집 금지. 철회하려면 신규 지시에 reverts=ORD-002 항목을 추가하세요. -->

### ORD-002 — 5단계 게이트웨이 파이프라인으로 위키 완전 재구축 (거리 게이트 + 회사 블로그)

<!-- 원문(verbatim): 아래 블록은 신규 지시 영역의 원본을 그대로 보존한다. 수정 금지. -->

> # ORDER
>
> 처음부터 다시 구축해라.
> 테크 뉴스를 수집하여, 개발자, po에게 필요한 정보를 wiki로 정리하는 프로젝트를 만들어라. 수집 소스 항목에 더하여 추천하고 싶은 소스가 있으면 제안하라.
> 수집한 소스는 클러스터링 파이프라인을 통과한다. 클러스터에서 거리가 너무 멀다면, wiki ingest에서 사용하는 자료에서 샘플링 하지 않도록 해라.
>
> ## 수집 소스
>
> - geek news
> - hacker news
> - lobsters
> - https://blog.bytebytego.com/feed
> - https://bensbites.beehiiv.com/feed
> - https://www.producthunt.com/feed
> - https://endoflife.date
> - https://www.velopers.kr/
> - https://awesome-blogs.petabytes.org/feeds?group=all
> - 주요 회사 엔지니어링, 테크 블로그
>
> ### Youtube
>
> | 채널                  | 특징                    |
> | --------------------- | ----------------------- |
> | Fireship              | 신기술 짧고 빠른 요약   |
> | Theo (t3.gg)          | 웹 프레임워크 트렌드    |
> | ThePrimeagen          | 시스템/언어 레벨        |
> | Awesome Open Source   | 오픈소스 프로젝트 소개  |
> | TechWorld with Nana   | DevOps/인프라           |
> | Google for Developers | 구글 공식 기술 업데이트 |

- 결과: 대화에서 확장된 5단계 파이프라인으로 재구축 — 수집 → 클러스터링(**centroid 거리 게이트**) →
  **검토 게이트웨이#1**(신뢰도·타당성·정합성, 하이브리드) → wiki ingest → **검토 게이트웨이#2**(graphify 지식그래프).
  - **완전 초기화**: 기존 wiki/·raw/·state/index/log 를 `.bak-2026-07-02/`로 백업 후 재생성.
  - **거리 게이트** `cluster.py`: coherent 클러스터에서 centroid 코사인 < `member_sim_min`(0.30) 멤버를
    아웃라이어로 대표 샘플에서 제외(`excluded_outliers` 기록, 작은 클러스터 폴백). 게이트 신호(corroboration=
    독립 도메인 수·max_trust·recency_days·gate_hint) 부여. `common.py`/`fetch.py`: 소스 `trust` prior 배선.
  - **회사 블로그 추가** `sources.toml`: Netflix·Cloudflare·Meta·AWS·Stripe·우아한형제들·카카오·토스(trust 1.2).
    ORDER 소스 교정 유지(Ben's Bites·요즘IT). 후속 대기: Uber·Discord·LINE·endoflife.date·velopers.kr(주석).
  - **게이트웨이#1** `CLAUDE.md §2.3`: 3축 판정 + 구조화 게이트 로그(JSON) — digest `## 게이트 로그`에 기록.
  - **게이트웨이#2** `CLAUDE.md §11`: graphify 배선(스킬 등록·스니펫·.gitignore) + `graphify extract wiki`로
    그래프 검증(orphan/모순/허브) + 되먹임(경계 준수).
  - **검증**: 단위 테스트 38개 통과(거리 게이트·gate_hint 결정표·trust 신규 포함), live 26/29 피드·608항목 수집,
    digest+횡단 5페이지 생성, graphify 그래프(10노드·orphan 0·모순 0), wiki lint 클린.
  - 외부 검토(ChatGPT codex / Gemini agy) 반영: 삭제 전 백업·centroid 거리 게이트·core/all member 분리·
    도메인 기준 corroboration·gate_hint 결정표·graphify pre-flight·구조화 게이트 로그·fixture 정확 검증.
<!-- /ORDER:COMMITTED id=ORD-002 -->
