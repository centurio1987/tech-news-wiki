---
type: source
created: 2026-07-02
updated: 2026-07-02
tags: [소스, 피드, rss]
audience: [dev, po]
sources: [[digests/2026-07-02]]
---

## TL;DR

`scripts/sources.toml`에 등록된 수집 소스 레지스트리. 2026-07-02 재구축 기준 **29개 피드 설정, 26개 정상
수집**(608항목). 각 소스는 `trust`(데이터 신뢰도 prior)를 갖고, 이 값은 검토 게이트웨이#1에 반영된다.

## 개요

- 파이프라인: [[digests/2026-07-02]]의 5단계(수집→클러스터링→게이트웨이#1→ingest→게이트웨이#2).
- 신뢰도 정책: 회사 공식/1차 소스 `trust=1.2`, 애그리게이터(Product Hunt·Ben's Bites) `0.9`, 그 외 기본 `1.0`.

## 주요 사실 (카테고리별)

- **종합·커뮤니티**: GeekNews(ko), Hacker News, Lobsters, Awesome Blogs(ko).
- **개발 심화**: ByteByteGo, The Pragmatic Engineer, InfoQ, The Changelog, GitHub Blog/Changelog, Simon Willison.
- **회사 엔지니어링/테크 블로그 (ORD-002 신규, trust 1.2)**: Netflix TechBlog, Cloudflare, Meta Engineering,
  AWS Architecture, Stripe, 우아한형제들 기술블로그, 카카오 Tech, 토스 기술블로그.
- **AI·제품**: Ben's Bites(0.9), Product Hunt(0.9), Lenny's Newsletter, 요즘IT.
- **YouTube**: Fireship, Theo(t3.gg), ThePrimeagen, Awesome Open Source, TechWorld with Nana,
  Google for Developers — 6채널 전부 ID 검증 완료(2026-07-02, 피드 제목 대조). 초기 실패 3건은
  ID 오류가 아니라 YouTube 엣지 서버의 간헐적 404/500이었고, fetch.py에 재시도 로직을 넣어 해소.

## 수집 상태 (2026-07-02)

> 🕰️ 시점 의존: 2026-07-02 실행 기준. 피드 가용성은 변동.
- 첫 실행 성공 26 / 실패 3(모두 YouTube, 일시적). 재시도 로직 추가 후 dry-run 재검증에서
  **YouTube 6/6 성공**(미수집분 45항목 확인 — 다음 수집 주기에 포함). 회사 블로그 8종 전부 정상.
- 후속 편입 대기(주석): Uber Engineering, Discord Blog, LY(LINE), endoflife.date(API), velopers.kr(경로 미확인).

## 관련

- [[에이전틱 인터넷]] · [[Cloudflare]] · [[Anthropic]] · [[github-copilot]]

## 출처

- `scripts/sources.toml`, `raw/feeds/2026-07-02/` (items.jsonl · clusters.json)
