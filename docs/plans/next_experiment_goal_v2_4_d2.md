---
title: "다음 checkpoint — V2.4-D2 결정론적 측정도구 개정"
derived_from: "results/analysis_v2_4_deterministic.md"
created: 2026-09-01
prev_experiment: V2.4-D-INVALID
next_slug: v2_4_d2
---

# V2.4-D2 reason-only adaptation gate

## 1. 배경과 단일 목표

V2.4-D는 exact 승인 bundle과 입력 gate를 통과한 뒤 첫 hidden scoring에서
`UNSUPPORTED_NEGATION`으로 fail-close했다. 이는 사전등록 계약대로 동작한 것이므로 원 라운드의
`primary_status`는 영구히 `INVALID`이며 RAG 효과를 지지하거나 반박하지 않는다. 후보 본문, 실패
row·condition·arm, score는 사람이나 agent에게 공개되지 않았지만 reason code 자체는 실입력에서
유래한 저대역폭 정보다.

다음 checkpoint의 단일 목표는 후보를 더 probe하지 않고 **public linguistic sources와 synthetic
counterexample만으로 total negation policy를 새 버전으로 사전 고정할 수 있는지** 검토하는 것이다.
실제 표현에 맞춘 alias·문법 patch는 금지하며, 가능한 설계가 없으면 V2.4-D2를 실행하지 않는다.

## 2. 우선 가설

일반적인 concept-associated negation을 finite 예외 나열이 아닌 결정론적 conservative suppression으로
total 처리하면 unsupported-input missingness를 없앨 수 있다. 다만 acceptance set이 달라지므로 이는
V2.4-D의 bugfix가 아니라 **data-contingent instrument revision**이다. 새 metric 이름과
`CONFIRMATORY_WITH_DISCLOSED_REASON_ONLY_ADAPTATION` 또는 더 보수적인 `EXPLORATORY_ONLY` disposition을
사전에 결정해야 한다.

## 3. Definition of Done

1. V2.4-D INVALID receipt·execution audit·분석과 원 scorer/ontology를 수정 없이 보존한다.
2. candidate/ground-truth 의미 본문, 실패 row/condition/arm, 부분 score를 열거나 재실행으로 탐색하지 않는다.
3. public linguistic reference와 synthetic fixtures만으로 새 negation policy·metric acceptance set·반증
   사례를 문서화한다.
4. reason-code adaptation과 inherited-env 실행 편차를 방법론 disposition에 공개한다.
5. 새 plan·ontology·scorer·tests를 별도 version으로 구현하고 candidate-unmounted fresh safety review와
   full implementation review를 통과시킨다.
6. exact 새 hash bundle을 사용자 승인받은 뒤 단 한 번의 hidden two-replay full scoring을 수행한다.
7. 새 결과가 나오더라도 V2.4-D의 confirmatory 결과로 소급하지 않고 V2.4-D2로만 보고한다.
8. 설계자가 실제 candidate 표현을 알게 되거나 반복 reason-code probe가 발생하면 즉시
   `EXPLORATORY_ONLY`로 강등하거나 실행을 취소한다.

## 4. 새 세션 시작 [GOAL] 프롬프트

```text
[GOAL] thesis-rca V2.4-D2의 reason-only instrument revision 가능성을 검토하고, 정당할 때만 새 버전을 설계한다.

작업 경로: /Users/yumunsang/thesis-rca

먼저 읽을 것:
- results/analysis_v2_4_deterministic.md
- results/evidence_v2_4_deterministic/execution_audit_2ed523e.json
- docs/plans/experiment_plan_v2_4_deterministic.md
- docs/plans/next_experiment_goal_v2_4_d2.md
- rules/experiment-pipeline.md, rules/data-safety.md

목표:
1. V2.4-D를 primary_status=INVALID로 영구 보존한다.
2. 후보/GT 의미 본문과 실패 row·arm·score를 보지 않고 public linguistic sources와 synthetic fixture만 조사한다.
3. unresolved negation을 total하게 처리하는 새 metric의 구성 타당성과 반증 사례를 brainstorming한다.
4. reason-code adaptation 때문에 confirmatory 유지가 가능한지 fresh methodology reviewer가 독립 판정한다.
5. 사용자가 exact design을 승인하기 전에는 구현·실입력 probe·채점을 하지 않는다.

가드레일:
- 실제 candidate 표현에 맞춘 alias/grammar patch 금지.
- real input에 대한 반복 reason-code probe 금지.
- 기존 CSV/raw/ground_truth/scorer/ontology/INVALID evidence 수정·삭제 금지.
- 새 모델/API/K8s 호출 0. 실험은 승인된 경우에도 offline one-shot two-replay만 허용.
- V2.4-D2 결과를 원 V2.4-D confirmatory 결과로 소급 금지.
```

## 5. TickTick 등록

위 [GOAL]의 첫 줄과 본 문서 경로를 TickTick `ai-continue`에 저장한다. 태그는
`claude-handoff`, `thesis-rca`를 사용한다.
