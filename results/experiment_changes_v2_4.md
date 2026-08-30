# V2.4 실험 변경 이력

### 1. Primary03 무호출 측정 감사 가설 고정 — 2026-08-30

- **수정 에이전트**: @Codex
- **증상/문제**: V2.3은 완결 campaign이 없어 RAG 효과를 판정할 수 없었고, 보존 prefix도 same-model Terra judge와 미실시 semantic shortcut audit에 의존했다. 자동 점수의 타당성을 확인하지 않고 fresh main campaign을 반복하면 잘못된 outcome을 더 정밀하게 재생산할 위험이 있었다.
- **원인**: V2.3 계획의 human-primary calibration과 procedure semantic audit가 운영 attrition 전에 완료되지 않았다. lexical scanner 0건은 의미론적 shortcut 부재를 증명하지 않으며, generator와 judge가 같은 requested model을 사용해 correlated evaluation error 가능성이 남았다.
- **수정 내용**: 모든 이전 결과 CSV를 Python으로 파싱하고 Primary03 117 rows의 조건별 threshold·generation split·paired discordance를 재계산했다. 정답 3건·오답 3건 raw를 질적으로 읽고, 39개 blind procedure를 동결 Chroma와 provenance에서 재구성해 source/masked/additional hash 불일치 0건을 확인했다. V2.4의 1차 가설을 36 representative outputs의 blinded dual-human outcome audit로 고정하고 semantic L0~L3 screen을 자료 적격성 gate로 분리했다. outcome-blind hash 층화 규칙과 선택된 12 incidents를 구현 전에 사전 기록했으며, 새 LLM/K8s 호출은 허용하지 않았다.
- **수정 파일**: `docs/surveys/deep_analysis_v2_4.md:1`, `results/experiment_changes_v2_4.md:1`
- **상태**: 분석 완료 — 상세 experiment plan과 독립 방법론 리뷰 승인 전 package 구현 금지. 기존 CSV/raw/artifact/ground truth 수정 0, LLM/API/Codex/Copilot 호출 0, K8s mutation/fault injection 0.
