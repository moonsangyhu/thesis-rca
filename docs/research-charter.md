# 연구 정본

이 문서는 `thesis-rca`의 현재 연구질문·기여·증거 범위·다음 행동을 정의하는 단일 정본이다.
실험별 상세 설계와 결과는 링크된 버전 문서에 두며, README나 외부 위키에 같은 상태를 복제하지 않는다.

## 연구 주제

**GitOps-managed Kubernetes에서 LLM 기반 근본 원인 분석의 컨텍스트 기여를 정답 누출·측정 비결정성·실험 오염 통제하에 평가한다.**

단순히 “GitOps 컨텍스트를 추가하면 정확도가 상승한다”는 주장을 목표로 하지 않는다. Runtime, GitOps, RAG가 각각 어떤 장애에서 유효한지 분해하고, 관찰된 성능 차이가 실제 진단 기여인지 shortcut인지 감사하는 것이 중심이다.

## 현재 연구질문

| ID | 연구질문 |
|---|---|
| RQ1 | Runtime-only 대비 GitOps와 RAG 컨텍스트의 독립적인 RCA 기여는 무엇인가? |
| RQ2 | 정답 라벨·fault-specific 런북·manifest diff에 의한 evidence leakage를 통제한 뒤에도 관찰된 성능 향상이 남는가? |
| RQ3 | 채점 임계값, LLM judge 비결정성, 컨텍스트 길이와 수집 시점 교락이 RCA 성능 평가에 미치는 영향은 무엇인가? |
| RQ4 | GitOps desired state·observed state·reconciliation state 중 어떤 신호가 어떤 fault group에서 진단 가능성을 높이는가? |

## 잠정 기여

1. Runtime·GitOps·RAG·길이 placebo를 분리하는 통제 실험 설계
2. fault-label·runbook·manifest 수준의 evidence leakage 감사 절차
3. 반복 생성·blinded 다수결 채점·임계값 sweep을 결합한 측정 신뢰성 평가
4. trial contamination과 수집 캠페인 차이를 포함한 Kubernetes RCA 내적 타당성 위협 분석

기여는 잠정적이다. V2.3은 검색 누출 통제 효과를 판정하기 전에 campaign lifecycle과
evidence completeness가 무너져 조기 종료됐다. 따라서 컨텍스트 효과 주장은 아직 확정하지
않고, 측정 파이프라인 실패 자체를 내적 타당성 근거로 분리한다.

## 현재까지 확인된 증거

### V2.1

- System B 우위는 통계적으로 입증되지 않았다(McNemar exact `p=0.267`).
- 정확도 순위가 채점 임계값 0.5와 0.6 사이에서 역전되어 측정 robustness 문제가 드러났다.
- 상세 근거: [`results/analysis_v2_1.md`](../results/analysis_v2_1.md)

### V2.2

- RAG-only 65.0%, baseline 31.7%로 큰 차이가 관찰됐고 임계값 0.5·0.6·0.7에서 순위가 유지됐다.
- 그러나 RAG trial의 75%가 주입 fault의 정답 라벨을 드러내는 자기 런북을 회수해 retrieval leakage 가능성이 높다.
- GitOps-only와 길이 placebo는 모두 36.7%였다. 다만 GitOps 신호가 fault와 연동되지 않았고 경로 오류도 있어 “GitOps 무용”으로 일반화할 수 없다.
- 상세 근거: [`results/analysis_v2_2.md`](../results/analysis_v2_2.md)

### V2.3

- F7-t5를 사전 제외한 목표는 단일 campaign 59 incidents·177 rows·2,124 logical calls였으나, 전체 49개 artifact directory에서 `campaign_complete`는 0건이었다.
- 최신 Codex-provider 캠페인 네 개는 각각 14·37·39·30 incidents에서 scanner, treatment/recovery, evidence-collection 문제로 중단 또는 무효화됐다.
- 서로 다른 revision의 prefix를 연결하지 않았으며, blind procedural RAG의 순기여는 **판정 불가**다. 이는 효과 없음의 증거가 아니다.
- 상세 근거: [`results/analysis_v2_3.md`](../results/analysis_v2_3.md)

## 주장 경계

- V1의 84%는 힌트 누출 사례이며 성능 근거로 사용하지 않는다.
- 통제된 단일 클러스터·Online Boutique·`gpt-4o-mini` 결과를 production readiness나 일반적 MTTR 개선으로 확대하지 않는다.
- 누출 통제 전 RAG 향상을 추론 능력 향상으로 표현하지 않는다.
- fault-linked GitOps 신호를 재수집하기 전 GitOps의 효과 또는 무효를 단정하지 않는다.
- V2.3의 불완전 campaign prefix를 합쳐 RAG 효과량·CI·p-value를 제시하지 않는다.
- 원시 CSV·JSON과 ground truth는 불변이며, 모든 수치는 해당 분석 문서로 추적 가능해야 한다.

## 현재 상태와 다음 행동

- 최신 종료 실험: **V2.3 — quality/operational futility 조기 종료, 가설 판정 불가**
- 다음 checkpoint: **V2.4 — 새 모델 호출 없는 retrospective human/semantic measurement audit 설계**
- 재개 문서: [`docs/plans/next_experiment_goal_v2_4.md`](plans/next_experiment_goal_v2_4.md)
- 버전 색인: [`docs/experiment-versions.md`](experiment-versions.md)

## 문서 소유권

| 정보 | 정본 위치 |
|---|---|
| 연구질문·기여·주장 범위 | 이 문서 |
| 실험 버전 현황 | `docs/experiment-versions.md` |
| 실험 계획 | `docs/plans/experiment_plan_*.md` |
| 다음 재개 지점 | 최신 `docs/plans/next_experiment_goal_*.md` |
| 원시 결과 | `results/*.csv`, `results/raw_v*/` |
| 결과 해석 | `results/analysis_*.md` |
| 선행연구 | `docs/papers/`, `docs/surveys/` |
| 논문 원고 | `paper/chapters/` |
