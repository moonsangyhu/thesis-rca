# Research Scope V1 — GitOps-aware LLM Kubernetes RCA 심층 Scoping Review

> 승인일: 2026-08-09
> 상태: 사용자 승인 완료
> 목적: thesis-rca의 근본 배경, 직접·인접 선행연구, 평가 타당성, 학술적 포지셔닝을 하나의 보고서 근거로 구축

## 1. 조사 성격과 목표

본 조사는 exhaustive systematic review를 주장하지 않는 **재현 가능한 심층 scoping review**다. 전통 RCA와 AIOps에서 출발하여 microservice·Kubernetes RCA, LLM 기반 RCA, GitOps evidence, RAG·SOP·agent·graph 접근, evidence leakage와 평가 신뢰성까지 연결한다.

최종 목표는 단순한 최고 정확도 경쟁이 아니라 다음을 밝히는 것이다.

1. Runtime·GitOps·RAG가 제공하는 정보의 종류와 독립적 진단 기여
2. 보고된 성능 향상이 추론인지 shortcut·정답 누출인지 구별하는 방법
3. GitOps desired·observed·reconciliation state가 어떤 fault에서 관측 가능한지
4. thesis-rca가 기존 agent architecture 연구와 구별되는 방어 가능한 연구 공백

## 2. 핵심 질문

| ID | 질문 |
|---|---|
| Q1 | 분산 시스템 RCA에서 root cause 판정은 어떤 인과·증거 조건을 만족해야 하는가? |
| Q2 | 전통 AIOps RCA는 telemetry·topology·change history를 어떻게 결합하며 어디서 실패하는가? |
| Q3 | Kubernetes의 동적 재조정과 cascading symptom은 RCA 구성·내적 타당성을 어떻게 어렵게 하는가? |
| Q4 | LLM RCA의 성능 향상은 SOP, RAG, agent 분리, graph traversal, hypothesis verification 중 무엇에서 발생하는가? |
| Q5 | 성능 향상이 실제 reasoning인지 fault label·runbook·manifest diff·prompt shortcut인지 어떻게 구별하는가? |
| Q6 | GitOps desired·observed·reconciliation state는 어떤 fault에서 진단 정보를 제공하는가? |
| Q7 | 기존 연구는 benchmark, fault taxonomy, 반복 수, judge, 통계, contamination을 얼마나 통제했는가? |
| Q8 | 경쟁 연구 대비 thesis-rca의 방어 가능한 차별점은 무엇인가? |

## 3. 검색 축

| 축 | 대표 검색어 | 목적 |
|---|---|---|
| A. RCA·AIOps 기반 | `root cause analysis causal inference observability AIOps`, `change event correlation` | RCA의 개념적 기반과 전통 방법의 한계 |
| B. Microservice·Kubernetes RCA | `microservice Kubernetes root cause analysis benchmark`, `fault injection telemetry topology causal graph` | 도메인 난점·데이터셋·fault taxonomy |
| C. LLM RCA architecture | `LLM incident root cause analysis agent SOP`, `hypothesize verify graph traversal AIOps` | prompt·RAG·SOP·agent·graph·verify 계보 |
| D. GitOps-aware diagnosis | `GitOps incident diagnosis desired observed state`, `ArgoCD FluxCD reconciliation drift root cause` | 직접 선행연구 존재 여부와 연구 공백 |
| E. RAG·context validity | `RAG evidence leakage runbook`, `retrieval shortcut prompt ablation lost in the middle RCA` | 자기 런북·정답 노출·길이 및 위치 교락 |
| F. Evaluation reliability | `LLM RCA evaluation benchmark contamination`, `LLM judge reliability repeated measures confidence interval` | judge 비결정성·통계·재현성·claim audit |

## 4. 기간과 출처

- 집중 기간: 2023-01-01~2026-08-09
- 배경 기간: 2018~2022
- 2018년 이전: RCA·인과추론·통계의 정전적 기반 문헌만 예외 포함
- 학술 출처: ACM Digital Library, IEEE Xplore, USENIX, SpringerLink, ACL Anthology, arXiv
- 탐색·메타데이터 교차검증: OpenAlex, Semantic Scholar, Google Scholar
- 기술 정의: Kubernetes, Argo CD, Flux, OpenGitOps 공식 문서
- 목표 규모: 18~25개 고유 1차 자료
- 최소 완료 게이트: 논문 5편 이상, 논문별 정량 수치·URL·thesis 적용 가능성 확인

## 5. 선정 기준

- Q1~Q8 중 하나 이상에 직접 답하는 1차 자료
- 전문 접근과 저자·연도·venue·URL 검증 가능
- 시스템, 입력 신호, 모델, baseline, dataset/fault, 표본 수, 평가 지표 추출 가능
- 정량 결과와 ablation 또는 비교 실험 포함
- Kubernetes·microservice·cloud incident RCA에 직접 적용되거나 evaluation validity를 직접 지지
- 최종본과 preprint가 중복되면 최종본 우선

## 6. 제외 기준

- 원문 없이 2차 요약만 존재하는 자료
- 상업 홍보·블로그의 성능 주장
- RCA와 무관한 범용 RAG·agent 연구
- 모델 교체·파인튜닝만 다루며 고정 모델 실험에 적용할 수 없는 연구
- benchmark·baseline·평가 방법이 불명확한 주장
- 동일 연구의 중복 버전

정답 누출 또는 synthetic 설정을 숨긴 채 production 일반화를 주장하는 자료는 성능 근거에서 제외하고 타당성 반례로만 사용한다.

## 7. 보고서 구조

1. 경영진 요약과 핵심 결론
2. RCA의 근본 개념: 증상·원인·인과성·증거
3. Observability·AIOps RCA의 발전
4. Microservice·Kubernetes RCA의 문제 구조
5. LLM RCA architecture 분류
6. GitOps signal model
7. 가장 유사한 논문 비교
8. 평가 방법론과 validity threats
9. V1~V2.2 결과와 문헌의 대응
10. 연구 공백과 thesis 포지셔닝
11. V2.3 및 논문 장별 적용 제안
12. 검색 로그·선정/제외표·claim–evidence ledger

## 8. 사전 포지셔닝 가설

주 포지셔닝은 새 agent architecture보다 **GitOps context의 인과적 기여를 감사하는 평가 연구**다.

- Runtime·GitOps·RAG·길이 placebo를 분리하고 GitOps-specific evidence leakage를 감사한다.
- desired·observed·reconciliation state를 RCA evidence로 모델링한다.
- blind retrieval, masked/full/no-diff, 동일 캠페인 수집, 반복 생성, blinded judge, threshold sweep을 결합한다.
- Flow-of-Action 대비 지식 주입의 순기여와 shortcut을 감사한다.
- SynergyRCA 대비 일반 StateGraph가 아닌 GitOps control-loop evidence를 다룬다.
- Auditable Graph-Guided RCA 대비 GitOps diff·reconciliation leakage까지 감사 범위를 확장한다.
- SpecRCA 대비 reasoning strategy보다 evidence provenance와 evaluation validity를 중심에 둔다.

검색 완료 전에는 `최초`, `유일`, `production-ready`를 주장하지 않는다.

## 9. 산출물과 완료 조건

- 논문별 분석: `docs/papers/{slug}.md`
- 종합 보고서: `docs/surveys/paper_survey_v1.md`
- 변경 이력: 최신 `results/experiment_changes_*.md`에 append-only 기록
- 완료 조건: 18~25개 후보 중 핵심 1차 자료를 검증하고, 최소 5편 이상의 정량 근거·URL·적용 가능성을 명시하며, 직접 선행연구와 인접 근거를 구분
