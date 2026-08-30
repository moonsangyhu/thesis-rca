# V2.4 실험 변경 이력

### 1. Primary03 무호출 측정 감사 가설 고정 — 2026-08-30

- **수정 에이전트**: @Codex
- **증상/문제**: V2.3은 완결 campaign이 없어 RAG 효과를 판정할 수 없었고, 보존 prefix도 same-model Terra judge와 미실시 semantic shortcut audit에 의존했다. 자동 점수의 타당성을 확인하지 않고 fresh main campaign을 반복하면 잘못된 outcome을 더 정밀하게 재생산할 위험이 있었다.
- **원인**: V2.3 계획의 human-primary calibration과 procedure semantic audit가 운영 attrition 전에 완료되지 않았다. lexical scanner 0건은 의미론적 shortcut 부재를 증명하지 않으며, generator와 judge가 같은 requested model을 사용해 correlated evaluation error 가능성이 남았다.
- **수정 내용**: 모든 이전 결과 CSV를 Python으로 파싱하고 Primary03 117 rows의 조건별 threshold·generation split·paired discordance를 재계산했다. 정답 3건·오답 3건 raw를 질적으로 읽고, 39개 blind procedure를 동결 Chroma와 provenance에서 재구성해 source/masked/additional hash 불일치 0건을 확인했다. V2.4의 1차 가설을 36 representative outputs의 blinded dual-human outcome audit로 고정하고 semantic L0~L3 screen을 자료 적격성 gate로 분리했다. outcome-blind hash 층화 규칙과 선택된 12 incidents를 구현 전에 사전 기록했으며, 새 LLM/K8s 호출은 허용하지 않았다.
- **수정 파일**: `docs/surveys/deep_analysis_v2_4.md:1`, `results/experiment_changes_v2_4.md:1`
- **상태**: 분석 완료 — 상세 experiment plan과 독립 방법론 리뷰 승인 전 package 구현 금지. 기존 CSV/raw/artifact/ground truth 수정 0, LLM/API/Codex/Copilot 호출 0, K8s mutation/fault injection 0.

### 2. 측정 감사 상세 계획과 독립 P0 비평 반영 — 2026-08-30

- **수정 에이전트**: @experiment-planner, fresh @hypothesis-reviewer, @Codex
- **증상/문제**: 초기 V2.4 분석은 36-output human audit의 방향을 제시했지만 measurement method를 독립변수로 오해할 여지, n=36에서 20% Wilson gate의 실제 정수 의미, correctness 이후 semantic reference가 합의판정을 역오염할 순서, Chroma/HMAC/scanner/0-call 격리의 실행 계약이 상세히 고정되지 않았다.
- **원인**: 저비용 triage라는 목적과 통계·자료보안·reviewer workflow를 하나의 검증 가능한 protocol로 아직 변환하지 않았고, 초기 계획 초안은 Step 1/Step 2 뒤 중복 사용자 승인을 요구했다.
- **수정 내용**: 조작 독립변수 없음과 Terra-human paired discordance 하나를 primary estimand로 고정했다. n=36에서 Green 0~2, Gray 3~11, Red 12~36의 Wilson 정수 gate와 abstain/incident-cluster bootstrap을 사전 명시했다. correctness adjudication을 완전 lock·close한 뒤 semantic package를 배포하도록 순서를 교정하고, Chroma quiescence·byte-equivalent reconstruction, phase별 scanner, canonical JSON/HMAC replay, network-none/credential-unmounted execution isolation을 구현 gate로 만들었다. 108 generation identity 선봉인, reviewer qualification·피로 통제, package-only/measurement-complete 상태 분리도 반영했다. fresh reviewer는 P0 8개를 재검증해 8 PASS/0 FAIL, 최종 `approve plan`을 기록했다. Step 3 진입은 plan/review hash bundle에 대한 사용자 단일 명시 승인 뒤로 제한했다.
- **수정 파일**: `docs/plans/experiment_plan_v2_4.md:1`, `docs/plans/review_v2_4.md:1`, `results/experiment_changes_v2_4.md:12`
- **상태**: 설계 완료·승인 대기 — plan SHA-256 `65ce766364f57c1fd2a8fbbf829cd50ba55cdb7d788ad1123a37667c713dcf63`, review SHA-256 `d16b1aea52bbe863d234cba2741a4784606f39c4102cee003bf0a35bd22aed64`. 미해결 비차단 dependency는 qualified R3 adjudicator 확보 여부와 Step 3의 실제 isolation/replay 검증이다. 구현·dry-run·Chroma open/copy·package 생성·사람 채점 0.
