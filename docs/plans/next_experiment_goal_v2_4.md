---
title: "다음 checkpoint V2.4 — 무호출 retrospective measurement audit"
derived_from: "results/analysis_v2_3.md (V2.3 독립 비판 분석)"
created: 2026-08-30
prev_experiment: V2.3
next_slug: v2_4
---

# V2.4 — 새 모델 호출 없는 측정 감사

> V2.3 종결 게이트 산출물이다. V2.3을 재개하거나 `Primary05`를 실행하는 계획이 아니다.

## 1. 배경과 단일 목표

V2.3은 단일 campaign 59 incidents·177 rows·2,124 calls를 요구했지만 전체 49개 artifact
directory에 `campaign_complete`가 하나도 없었다. 최신 동일-provider 네 campaign도 서로
다른 revision에서 중단됐으므로 결합할 수 없다. 독립 비평은 최종 가설을 `판정 불가`로
결론냈다.

V2.4의 단일 목표는 **새 LLM 호출이나 fault injection 없이**, Primary03의 보존된 출력에서
same-model judge와 semantic shortcut이 측정 해석을 얼마나 흔들 수 있는지 감사할 수 있는
blinded review package와 분석 계획을 만드는 것이다. 이 작업은 V2.3의 causal estimand를
복구하지 않으며 논문용 방법론·한계 근거만 강화한다.

## 2. 범위와 사전 경계

- 데이터 정본: `artifacts/v2_3_main/v2-3-codex-20260830-primary03/` 하나만 사용한다.
- 표본: outcome과 condition score를 보지 않는 deterministic hash 층화로 12 incidents를 고르고, 각 incident의 3 conditions를 묶어 36 outputs를 만든다.
- 감사 1: reviewer에게 condition·Terra score·fault label을 숨긴 동일 rubric human review package.
- 감사 2: 12 blind-RAG context blocks의 `label exposed / entity exposed / unique mechanism cue / generic procedure` 4축 semantic shortcut rubric.
- 분석: Terra judge와 human 판정 방향, reviewer agreement, semantic cue 빈도를 exploratory로만 보고한다.
- 금지: campaign 결합, confirmatory effect/CI/p-value, V2.2 절대 비교, 기존 CSV/raw 수정, 새 모델 호출, live fault injection.

## 3. Definition of Done

1. deterministic selection seed·hash·층화 규칙과 선택된 12 incident ID를 사전 기록한다.
2. 정답·condition·기존 judge score가 숨겨진 36-output review package와 별도 answer key를 만든다.
3. 4축 semantic audit sheet와 판정 지침을 만든다.
4. human reviewer가 제공되면 inter-rater agreement와 Terra 방향 일치도를 탐색 분석한다. reviewer가 없으면 package 준비 완료까지만 명시하고 사람 점수를 생성하지 않는다.
5. 결과를 논문 주장 가능/불가능 경계에 반영하고 V2.3 artifact를 confirmatory로 승격하지 않는다.
6. feature branch → 한국어 PR까지 완료하며, 머지는 사용자 명시 승인 뒤에만 한다.

## 4. 새 세션 시작 [GOAL] 프롬프트

```text
[GOAL] thesis-rca V2.4 retrospective measurement audit를 새 모델 호출·fault injection 없이 완료한다.

레포: /Users/yumunsang/thesis-rca. 모든 작업은 PR-only 정책을 따른다.

먼저 읽을 것:
- results/analysis_v2_3.md
- docs/plans/next_experiment_goal_v2_4.md
- docs/plans/experiment_plan_v2_3.md
- rules/data-safety.md
- artifacts/v2_3_main/v2-3-codex-20260830-primary03/ (read-only)

목표:
1. outcome/score-blind deterministic hash 층화로 Primary03에서 12 incidents를 선택한다.
2. 3 conditions를 함께 보존한 36-output blinded human review package와 분리된 answer key를 만든다.
3. blind-RAG context용 4축 semantic shortcut audit sheet를 만든다.
4. 사람이 실제로 채점한 값만 분석한다. reviewer가 없으면 점수를 추정·생성하지 않고 package 준비 상태로 끝낸다.
5. 모든 결과는 exploratory measurement audit로만 표현하고 V2.3 campaign을 결합하거나 confirmatory 효과를 만들지 않는다.
6. changelog, 검증, feature branch commit/push, 한국어 PR까지 수행한다. 머지는 사용자 승인 전 금지한다.

가드레일:
- LLM/API/Codex/Copilot 호출 0, K8s mutation 0, fault injection 0.
- 기존 CSV/raw/artifact/ground truth 수정·삭제 금지.
- 정답·condition·기존 judge score가 review package에 노출되면 fail-closed한다.
- reviewer가 없다는 이유로 AI-generated human score를 만들지 않는다.
```

## 5. 이후 실험 재개 문턱

V2.3의 원래 인과 질문이 논문의 필수 주장이어서 live 재실행이 불가피한 경우에만,
V2.4 감사 뒤 **model-free 59-incident lifecycle qualification 완주**를 별도 계획한다. 이 qualification이
query-success receipt, exact recovery, campaign completion을 모두 통과하기 전에는 새 main LLM
campaign을 시작하지 않는다.
