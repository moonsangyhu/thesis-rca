---
title: "다음 checkpoint — V2.4 qualified human measurement 완료"
derived_from: "results/analysis_v2_4.md"
created: 2026-08-31
prev_experiment: V2.4-package-only
next_slug: v2_4_human_measurement
---

# V2.4 사람 측정 완료 gate

> 파일명은 Experiment Track Step 6의 다음-goal 규약을 따르지만, 이 작업은 새 V2.5 효과
> 실험이 아니다. 아직 `PACKAGE_ONLY`인 V2.4를 실제 사람 평가로 완료하는 continuation이다.

## 1. 배경과 단일 목표

V2.4 기술 package는 `v2-4-primary03-audit-20260831`로 생성됐고 입력·재구성·scanner·
commitment·동일 audit replay가 통과했다. 하지만 사람 rating과 adjudication은 0건이므로
Terra-human discordance, reviewer reliability, semantic L3 eligibility와 Green/Gray/Red는
모두 `NOT_EVALUATED`다.

단일 목표는 **qualified R1/R2가 condition·Terra-blind 상태에서 보존 package를 실제로
평가하고, disagreement-only adjudication까지 완료해 H-V2.4를 판정하는 것**이다. 새 모델
호출, 새 fault injection, V2.3 campaign 결합은 하지 않는다.

## 2. Definition of Done

1. R1/R2 각각 Kubernetes/SRE 실무 2년 이상, 또는 verified CKA/CKAD와 실무 1년 이상을
   구조화 profile로 기록하고 synthetic training을 통과한다. 가능하면 동일 기준의 blind R3를 확보한다.
2. correctness 36건을 reviewer별 독립 평가하고 item/session timestamp와 원본 sheet hash를 lock한다.
3. 두 correctness 제출의 disagreement만 adjudicate하고 correctness phase를 원자적으로 close한다.
4. correctness CLOSED 뒤 semantic training/profile을 lock하고, 두 profile이 모두 유효할 때만
   `release-semantic`으로 12건 package를 최초 공개한다.
5. semantic 12건을 독립 평가·adjudicate하고 분석을 실행한다. 실제 원점수·abstain을 보존하며
   결측을 보간하거나 AI가 사람 점수를 생성하지 않는다.
6. `results/analysis_v2_4.md`를 실제 측정값으로 갱신하고 Terra-human discordance,
   agreement, semantic L0~L3, Green/Gray/Red를 사전등록 규칙 그대로 판정한다.
7. 변경은 feature branch → 한국어 PR까지 진행하고 사용자 승인 전 merge하지 않는다.

## 3. 새 세션 시작 [GOAL] 프롬프트

```text
[GOAL] thesis-rca V2.4 qualified human measurement를 완료한다. 새 V2.5 효과 실험은 시작하지 않는다.

작업 경로: /Users/yumunsang/thesis-rca-v2-4-audit
감사 경로: artifacts/v2_4_measurement_audit/v2-4-primary03-audit-20260831

먼저 읽을 것:
- results/analysis_v2_4.md
- docs/plans/experiment_plan_v2_4.md
- docs/plans/next_experiment_goal_v2_5.md
- docs/issues/experiment_issues_v2_4.md
- rules/experiment-pipeline.md, rules/data-safety.md

목표:
1. 실제 qualified R1/R2(가능하면 blind R3)를 확보하고 phase별 profile/training을 lock한다.
2. correctness 36건을 독립 평가·lock·disagreement-only adjudication·close한다.
3. correctness CLOSED 뒤에만 semantic profile을 lock하고 release-semantic을 실행한다.
4. semantic 12건을 독립 평가·lock·adjudication·close한다.
5. analyzer로 사전등록 metric/gate를 계산하고 fresh results critic이 analysis_v2_4.md를 갱신한다.
6. changelog, 검증, commit/push, 한국어 PR까지 수행한다. merge는 사용자 승인 전 금지한다.

가드레일:
- AI가 human rating, reviewer profile, certification, timestamp, adjudication을 생성하지 않는다.
- LLM/API/Codex/Copilot inference 0, K8s/fault injection 0, 기존 V2.3 입력 수정 0.
- correctness 종료 전 semantic archive 공개 금지. lock 이후 파일 변조 시 fail-closed한다.
- 비대표 generation 72개 본문은 재생성·추정하지 않는다.
- qualified reviewer가 없으면 PACKAGE_READY_AWAITING_HUMAN_REVIEW 상태를 유지하고 멈춘다.
```

## 4. 이후 효과 실험 진입 조건

V2.4 human measurement가 끝나고 결과가 Green/Gray/Red 중 하나로 판정된 뒤에만 다음
RAG→RCA 인과 실험을 설계한다. 그 실험은 model-free 59-incident lifecycle qualification,
완전한 generation payload 보존, OS-level network-none 실행 receipt를 먼저 통과해야 한다.
