# 심층 분석: V2.3-RAG 실험 설계를 위한 개선점 도출

> 분석일: 2026-08-09
> 분석 대상: V2, V2.1, V2.2, V3, V6, V7, V8 결과와 V2.2 raw JSON 300개
> 목적: 정답 누출을 통제한 RAG의 순수 진단 기여를 단일변수 실험으로 검증

## 1. 결론 먼저

V2.3의 최우선 가설은 하나다.

> **동일한 runtime evidence와 동일한 컨텍스트 길이에서, fault label·파일명·정답 entity를 제거한 절차형 RAG는 무관 텍스트 placebo보다 RCA 정확도를 높인다.**

V2.2의 RAG 65.0%는 baseline 31.7%, length placebo 36.7%보다 컸지만 RAG가 포함된 120개 arm-row 중 90개(75%)에서 주입 fault의 자기 런북이 검색됐다. 자기 런북 회수군 정확도는 67.8%, 비회수군은 46.7%였다. 따라서 V2.2는 RAG 총효과는 관찰했지만 절차 지식의 순효과와 정답 누출을 분리하지 못했다.

V2.3은 GitOps 정상화와 context-position 변경을 함께 넣지 않는다. 독립변수는 `context_condition` 한 개이며 수준은 `runtime`, `length_placebo`, `blind_procedural_rag`다. 모델은 V2.2의 `gpt-4o-mini`에서 Copilot CLI–`gpt-5.6-terra`로 바뀌므로 V2.2와 절대 정확도를 비교하지 않고 V2.3 내부 paired contrast만 해석한다.

## 2. 데이터 무결성과 버전 추세

Python `csv` 모듈로 확인한 결과 파일은 7개, 총 960행이다.

| 버전 | 행 | 핵심 관찰 |
|---|---:|---|
| V2 | 100 | 힌트 제거 후 공정 baseline 시작 |
| V2.1 | 120 | B 43.1% vs A 34.5%, McNemar exact p=0.267 |
| V2.2 | 300 | 12 faults × 5 trials × 5 arms 완결 |
| V3 | 100 | harness가 B를 개선하지 못함, faithfulness 상수화 |
| V6 | 100 | SOP의 fault별 개선과 early-confirmation 회귀 공존 |
| V7 | 120 | 네트워크 fault 확장 |
| V8 | 120 | 네트워크 가설 기각, recovery 실패에 의한 오염 발견 |

서로 다른 버전은 모델·prompt·campaign·cluster history가 달라 독립 반복실험처럼 pooling하지 않는다. V2.3 설계 근거를 제공하는 사례군으로만 사용한다.

## 3. V2.2 trial-level 패턴

### 3.1 arm 정확도

| Arm | correct@0.5 | 정확도 |
|---|---:|---:|
| runtime baseline | 19/60 | 31.7% |
| GitOps | 22/60 | 36.7% |
| RAG | 39/60 | 65.0% |
| GitOps+RAG | 36/60 | 60.0% |
| length placebo | 22/60 | 36.7% |

RAG와 placebo의 paired discordance는 `placebo-only=1`, `RAG-only=18`이었다. 하지만 이 차이는 blind RAG 효과가 아니라 self-runbook leakage를 포함한 총효과다.

### 3.2 컨텍스트 길이

300개 row에서 정답군 컨텍스트 길이 중앙값은 9,331자, 오답군은 8,189자였다. 길이와 context source가 함께 변하므로 단순 길이-정확도 연관은 인과효과가 아니다. V2.3에서도 token/character length를 placebo와 사전 허용오차 안에서 맞춰야 한다.

### 3.3 raw JSON 질적 표본

최소 기준에 따라 정답 3개와 오답 3개를 원시 JSON까지 확인했다.

| 판정 | 표본 | 관찰 |
|---|---|---|
| 정답 | F1-t1 runtime | runtime evidence만으로 OOM Kill 식별 |
| 정답 | F1-t1 GitOps | `Git repo not found`가 있어도 runtime 신호로 정답 |
| 정답 | F1-t1 RAG | context에 `F1` self-runbook 식별자가 존재 |
| 오답 | F1-t3 runtime | Network Connectivity Issue로 오진 |
| 오답 | F1-t3 GitOps | readiness/liveness failure에 고착 |
| 오답 | F1-t3 RAG | self-runbook이 있어도 다른 pod 신호에 고착 |

누출은 충분조건이 아니지만 강한 shortcut이다. 따라서 V2.3은 문자열 마스킹뿐 아니라 문서 선택 과정에서 주입 fault와 직접 결합된 문서 ID도 감춰야 한다.

## 4. Evaluator 효과와 측정 제약

- V2.1의 결론은 correctness threshold에 민감했고 0.6에서 순위가 역전됐다.
- V2.2는 생성 `k=3`, blinded judge `m=3`, threshold 0.5/0.6/0.7 sweep으로 측정 안정성을 개선했다.
- V3의 `faithfulness_score`는 100건 모두 1.0으로 상수화돼 evaluator가 유효한 측정기가 아니었다.
- Copilot CLI는 temperature·seed·input-token count를 제공하지 않는다. V2.3은 이를 숨기지 않고 생성 반복과 judge 반복, model ID, session ID, output tokens, AIC를 기록한다.
- generator와 judge가 모두 Terra이므로 self-evaluation bias가 남는다. arm/source 표식을 judge 입력에서 제거하고 일부 표본을 사람이 blind audit해야 한다.

## 5. GitOps 컨텍스트 분석

V2.2에서 GitOps와 placebo는 모두 36.7%였다. 그러나 GitOps context는 imperative injection과 무관한 `Ready` 상태 및 `Git repo not found` 오류를 포함했다. 이는 GitOps 무효가 아니라 treatment integrity 실패다.

GitOps 정상화는 RAG 누출 통제와 다른 독립변수다. V2.3-RAG에는 GitOps arm을 넣지 않고, blind RAG의 잔존효과가 확인된 다음 V2.4-GitOps에서 별도 검증한다.

## 6. 선행연구에서 가져올 설계 원칙

2026-08-09 작성된 scoping survey와 원문 노트를 설계 입력으로 사용했다.

- **Flow-of-Action**: SOP knowledge ablation은 절차 지식의 기여를 보여주지만, 이름과 정답 label shortcut을 분리 감사해야 한다.
- **Auditable Graph-Guided RCA**: prompt hint를 제거했을 때 headline gain이 크게 줄 수 있으므로 stripped/masked 조건이 필요하다.
- **Controlled Data Contamination**: source와 target의 결합 노출은 실제 능력보다 평가 점수를 부풀릴 수 있다.
- **Judging LLM-as-a-Judge / Rating Roulette**: judge 반복, blinding, swap 또는 사람 audit 없이는 평가 비결정성과 편향이 남는다.
- **Lost in the Middle**: context 위치는 후속 독립변수이며 V2.3의 blind-RAG 처치와 동시에 바꾸지 않는다.

최근 survey는 research worktree에 아직 미통합 상태이므로 V2.3 PR 전에 해당 문헌 산출물의 병합 여부와 링크 무결성을 확인한다.

## 7. 독립 가설 후보

### 가설 A: Blind procedural RAG의 순기여 — 우선순위 1

**변경 변수**: `context_condition`만 변경한다. runtime evidence는 동일하게 공유하고, `length_placebo`와 `blind_procedural_rag`는 길이를 맞춘다.
**데이터 근거**: V2.2 RAG 65.0% vs placebo 36.7%, paired RAG-only 18건이지만 self-runbook 75%.
**메커니즘**: 진단명 없이 recovery/check 절차만 제공해 observation-to-hypothesis mapping을 돕는다.
**대상 faults**: 모든 F1–F12. fault-group 효과는 탐색적으로만 본다.
**예상 효과**: blind-RAG가 placebo보다 최소 +10%p, 95% paired effect CI의 중심이 양수.
**실패 기준**: placebo 대비 차이가 0 이하이거나 threshold 0.5/0.6/0.7에서 방향이 일관되지 않음.
**리스크**: masking 후 문서에 entity·명령·복구 행동이 간접 정답으로 남을 수 있음.
**구현 범위**: V2.3 retriever/masker, 3-arm assembler, leakage scanner, Copilot usage provenance.

### 가설 B: Context 위치 효과 — 우선순위 2, V2.4 이후

**변경 변수**: 동일 blind procedural RAG block의 위치(front/middle/end)만 변경한다.
**근거**: 정답군과 오답군의 context 길이가 다르고 LLM은 긴 context의 중간 evidence를 놓칠 수 있다.
**예상 효과**: 위치별 최대-최소 차이가 10%p 이상이면 position을 통제변수로 승격한다.
**리스크**: V2.3과 동시에 적용하면 blind-RAG 내용 효과와 위치 효과가 교락된다.

### 가설 C: GitOps reconciliation evidence — 우선순위 3, 별도 V2.4-GitOps

**변경 변수**: runtime-only 대비 정상화된 desired/observed/reconciliation evidence 추가.
**근거**: V2.2 GitOps=placebo였지만 context 자체가 손상되어 효과를 판정할 수 없었다.
**예상 효과**: deployment-visible fault에서 runtime 대비 +10%p 이상, infrastructure-only fault에서는 0에 가까운 선택적 효과.
**리스크**: GitOps 경유 injection과 fault taxonomy를 새로 구성해야 해 RAG 실험과 동시 수행할 수 없다.

## 8. 권장 실행 순서와 gate

1. **V2.3-RAG**: runtime / length-placebo / blind-procedural-RAG, Copilot CLI–Terra 고정.
2. 비주입 smoke test 후 **F1 × trial 1 파일럿**으로 JSON 안정성·AIC·leakage scanner·복구 gate 확인.
3. 파일럿 비용으로 전체 AIC를 상한 추정하고 잔여 28,850 AIC 이내일 때만 본실험 승인.
4. 본실험은 동일 campaign에서 paired arm을 연속 실행하고 fault 간 cooldown 및 완전 복구를 강제한다.
5. RAG 잔존효과가 확인된 뒤에만 GitOps를 별도 실험으로 진행한다.

V2.3의 성공은 “Terra가 V2.2보다 높다”가 아니다. **같은 Terra, 같은 incident, 같은 runtime evidence, 같은 길이에서 blind procedural RAG가 placebo보다 높다**가 유일한 1차 주장이다.
