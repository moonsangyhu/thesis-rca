---
title: "Simplifying Root Cause Analysis in Kubernetes with StateGraph and LLM"
status: "candidate"
created: "2026-06-19"
source: "NotebookLM daily paper audio; Slack thread 1781867545.264676"
url: "https://arxiv.org/abs/2506.02490v1"
paper_id: "arXiv:2506.02490v1"
notebooklm: "https://notebooklm.google.com/notebook/16f832a4-bacf-4c2a-a806-3cfe603d72bd"
next_experiment_candidate: "V10-or-later"
---

# Simplifying Root Cause Analysis in Kubernetes with StateGraph and LLM

## 1. 한 줄 판단

**Candidate.** 다음 실험 후보로 남길 가치가 있다. 단, 논문을 그대로 재현하는 방향은 약하고, `StateGraph/MetaGraph-inspired graph-structured context`가 기존 System B 대비 어떤 정보를 실제로 개선하는지 **context-source ablation**으로 검증해야 한다.

## 2. 사용자 입력에서 보존할 아이디어

사용자 판단: “이 논문 괜찮다. 다음 실험 후보로.”

보존할 핵심 아이디어:

- Kubernetes RCA에서 logs/metrics/events를 단순히 concat하지 않고, Kubernetes resource의 spatial/temporal relationship을 graph 구조로 정리한다.
- StateGraph/MetaGraph에서 영감을 받아 LLM에 넣을 context를 선택·구조화한다.
- 다음 실험은 “SynergyRCA 재현”이 아니라, controlled Kubernetes fault injection 환경에서 **graph-structured context가 LLM RCA 정확도와 evidence grounding을 개선하는지**를 검증한다.

## 3. 논문 메타데이터

- 논문: *Simplifying Root Cause Analysis in Kubernetes with StateGraph and LLM*
- 저자: Yong Xiang, Charley Peter Chen, Liyi Zeng, Wei Yin, Xin Liu, Hu Li, Wei Xu
- 출처: arXiv:2506.02490v1
- 발행일: 2025-06-03
- URL: https://arxiv.org/abs/2506.02490v1
- NotebookLM: https://notebooklm.google.com/notebook/16f832a4-bacf-4c2a-a806-3cfe603d72bd

arXiv abstract 기준 핵심 주장:

- SynergyRCA는 LLM + graph database retrieval + expert prompts를 사용한다.
- StateGraph는 Kubernetes resource의 spatial/temporal relationship을 포착한다.
- MetaGraph는 entity connection을 표현한다.
- incident 발생 시 LLM이 관련 resource를 예측하고, SynergyRCA가 MetaGraph/StateGraph를 query하여 RCA context를 제공한다.
- 두 production Kubernetes cluster dataset에서 평균 약 2분 RCA, precision 약 0.90을 주장한다.

## 4. thesis-rca 매핑

- 연결되는 현재 약점:
  - F11/F12 network fault에서 dominant stale signal에 끌리는 문제
  - context가 길어질수록 LLM이 어떤 evidence를 실제로 사용했는지 불명확한 문제
  - GitOps/RAG context의 효과를 “전체 성능”만이 아니라 source별 contribution으로 분해해야 하는 문제
- 관련 fault type:
  - 1차 후보: F6 NetworkPolicy, F8 ServiceEndpoint, F11 NetworkDelay, F12 NetworkLoss
  - 2차 후보: F2 CrashLoopBackOff, F4 NodeNotReady
- 관련 시스템:
  - System B의 context selection / RAG / graph-structured evidence block
  - evaluator의 evidence correctness / hallucination rate
- 관련 기존 산출물:
  - `results/analysis_v8.md`: F11/F12에서 CrashLoopBackOff 잔류 신호가 dominant하게 작용한 근거
  - `docs/surveys/deep_analysis_v9.md`: SynergyRCA StateChecker 패턴이 이미 V9 validator 설계 근거로 등장
  - `docs/plans/experiment_plan_v9.md`: V9는 State Validator가 단일 독립변수이므로, graph context ablation은 V10 이후 후보로 분리하는 것이 타당

## 5. 실험 가설 초안

> V10 또는 이후 실험에서 **graph-structured Kubernetes context selection** 하나를 추가하면, V9/V8의 기존 System B 대비 F6/F8/F11/F12에서 RCA correctness와 evidence grounding이 개선된다. 단, F1-F10 전체 non-regression, input token count, latency는 악화되지 않아야 한다.

더 엄밀한 형태:

- H1: Raw logs/events concat보다 dependency graph summary를 제공한 조건이 Top-1 RCA accuracy를 높인다.
- H2: graph-structured context는 hallucinated evidence rate를 낮춘다.
- H3: GitOps/change-history context는 configuration-related incidents(F2/F8/F9/F10)에서만 유의미한 contribution을 갖고, network-level incidents(F11/F12)에는 제한적이다.

## 6. 변수 정의

| 구분 | 내용 |
|---|---|
| 독립변수 | Context representation: raw concat vs selected context vs graph-structured context |
| Primary metric | fault별 correctness_score, binary accuracy(score≥0.5), F6/F8/F11/F12 subgroup accuracy |
| Guardrail metric | F1-F10 non-regression, hallucinated evidence rate, input token count, latency |
| 통제변수 | 모델 `gpt-4o-mini`, fault set, trial count, ground truth, 실험 harness, judge prompt |
| Baseline | 직전 안정 버전 System B; 필요 시 System A 및 raw-context condition |
| Counterfactual | 동일 incident에서 graph context 없이 raw logs/events 또는 기존 RAG만 제공했을 때의 실패 패턴 |

## 7. 구현 후보

예상 변경 경로:

- `experiments/v10/`: graph-context ablation experiment runner/config
- `experiments/shared/runner.py`: condition별 context variant 실행이 필요할 수 있음
- `src/processor/context_builder.py`: graph summary block 추가
- `src/collector/kubectl.py`: ownerReference, selector, endpoints, events, deployment/replicaset 관계 수집 강화
- `src/rag/`: runbook/RAG와 graph context를 분리된 evidence block으로 출력
- `scripts/evaluate/analyze.py`: evidence correctness, hallucination rate, token/latency metric 추가

## 8. 바로 구현하면 안 되는 이유

이 아이디어는 강하지만, 지금 바로 V9에 섞으면 안 된다.

- V9의 독립변수는 Pre-Trial State Validator다. graph context를 같이 넣으면 V9 결과 해석이 깨진다.
- SynergyRCA는 production dataset 기반이라, 현재 controlled fault injection 환경과 직접 비교할 수 없다.
- 논문의 StateGraph/MetaGraph schema를 확인하지 않고 구현하면 이름만 graph인 heuristic context가 될 위험이 있다.

## 9. 반증 조건

이 아이디어는 다음 중 하나가 나오면 기각하거나 축소한다.

- Graph context가 raw selected context 대비 accuracy를 개선하지 못함
- evidence correctness는 오르지 않고 token/latency만 증가함
- 개선이 특정 fault 1개에만 국소적이고 일반화되지 않음
- graph 구조가 실제 causality가 아니라 단순 Kubernetes owner tree에 불과해 논문 기여와 연결이 약함
- 구현이 StateGraph, prompt, evaluator, collector를 동시에 바꿔 단일 독립변수 해석이 불가능해짐

## 10. 승격 전 체크리스트

- [x] 원 논문 URL/arXiv 확인
- [x] NotebookLM 링크 확인
- [ ] `docs/papers/synergyrca-stategraph-llm.md` 정식 읽기 노트 작성
- [ ] StateGraph node/edge schema 확인
- [ ] MetaGraph와 StateGraph의 차이 확인
- [ ] LLM input format과 graph query 절차 확인
- [ ] dataset 공개 여부 및 baseline 수준 확인
- [ ] 현재 실험 실패 패턴과 직접 연결되는 ablation 설계 작성
- [ ] 단일 독립변수로 축소
- [ ] baseline/metric/guardrail 확정
- [ ] 구현 범위와 rollback 경로 명시

## 11. Advisor note

이 논문은 관련연구와 다음 실험 후보로 모두 가치가 있다. 그러나 석사논문에서 강한 주장은 “SynergyRCA를 따라 만들었다”가 아니라 다음이어야 한다.

> Kubernetes RCA에서 LLM 성능 향상은 어떤 operational context source와 구조화 방식에서 발생하는가?

따라서 다음 산출물은 implementation이 아니라 `docs/papers/` 정식 읽기 노트와 1페이지 ablation 설계다.
