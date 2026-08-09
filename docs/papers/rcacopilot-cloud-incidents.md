# 논문 심층 분석: RCACopilot — Automatic RCA via LLMs for Cloud Incidents

> 분석일: 2026-08-09
> 분석 관점: 20년차 cloud SRE
> 논문: Yinfang Chen et al., EuroSys 2024
> DOI: https://doi.org/10.1145/3627703.3629553
> 원문: https://arxiv.org/pdf/2305.15778

## 1. 한 줄 요약

RCACopilot는 on-call engineer가 alert별 진단 workflow를 handler로 만들고, 그 실행 결과를 요약한 뒤 유사 과거 incident를 few-shot CoT로 제공해 root-cause category를 예측하는 Microsoft production RCA 시스템이다.

## 2. 핵심 문제와 기존 한계

실제 cloud incident의 RCA는 logs·metrics·traces·dashboards에 흩어진 정보를 사람이 troubleshooting guide에 따라 수집하는 데 시간이 많이 든다. guide는 오래되거나 불완전하고, 원시 진단 결과는 LLM context에 넣기에는 지나치게 길다. RCACopilot는 이를 **정형 workflow 수집 → 압축 → 유사 사건 기반 분류·설명**으로 분리한다.

## 3. 핵심 기법과 원리

```text
alert type/scope
  -> matching incident handler
  -> action graph가 다중 소스 진단 정보 수집
  -> GPT가 약 120-word summary 생성
  -> FastText로 과거 incident 검색(유사도+시간 가중)
  -> top-k labeled examples를 CoT demonstration으로 구성
  -> GPT-3.5/GPT-4가 category + explanation 생성
```

- **Incident handler**: OCE가 GUI에서 action node와 scope-switching action을 연결한다. 새 alert type은 새 handler를 추가해 확장한다.
- **진단 정보 요약**: 긴 action output을 120 words 안팎으로 압축해 중요 신호를 보존하면서 context burden을 낮춘다.
- **시간 인지 retrieval**: FastText embedding similarity와 incident recency를 결합한다. 과거 label과 summary가 곧 few-shot reasoning example이 된다.
- **분류와 설명**: 알려진 category뿐 아니라 새 category label도 생성할 수 있다.

## 4. 모델·데이터셋·실험 설계

| 항목 | 원문에서 확인한 내용 |
|---|---|
| target | Microsoft global email Transport service, 일일 약 150B messages |
| dataset | 1년간 incident 653건, OCE가 root-cause category 수동 labeling |
| split | train 75%, test 25% |
| models | GPT-3.5-turbo, GPT-4 8K; default GPT-4 |
| retrieval | FastText, best `k=5`, recency weight `alpha=0.3` |
| baselines | FastText, XGBoost, fine-tuned GPT-3.5, GPT-4 Prompt, GPT-4 embedding |
| metrics | Micro-F1, Macro-F1, train/inference time |
| 반복 | 각 실험 3 rounds |
| 배치 | 정보 수집 모듈 30개 이상 Microsoft teams, 4년 이상 사용 |

평가 데이터는 production incident지만 단일 Transport service이고 비공개다. handler matching이 가능한 alert에서 handler activation accuracy는 100%라고 보고하지만, monitor가 incident를 놓치거나 handler가 없으면 시스템이 작동하지 않는다.

## 5. 정량 결과와 ablation

### Root-cause category prediction (Table 2)

| 방법 | Micro-F1 | Macro-F1 | inference seconds |
|---|---:|---:|---:|
| FastText | 0.076 | 0.004 | 0.524 |
| XGBoost | 0.022 | 0.009 | 1.211 |
| fine-tuned GPT-3.5 | 0.103 | 0.144 | 4.262 |
| GPT-4 Prompt (no retrieved examples) | 0.026 | 0.004 | 3.251 |
| GPT-4 embedding variant | 0.257 | 0.122 | 3.522 |
| RCACopilot GPT-3.5 | 0.761 | 0.505 | 4.221 |
| RCACopilot GPT-4 | **0.766** | **0.533** | **4.205** |

### Context ablation (Table 3)

- raw DiagnosticInfo only: Micro-F1 0.689, Macro-F1 0.510.
- summarized DiagnosticInfo only: 0.766, 0.533; 요약으로 각각 +0.077, +0.023.
- AlertInfo only: 0.379, 0.245.
- 모든 source를 섞으면 0.440, 0.349로 오히려 하락했다.
- historical example 없는 GPT-4 Prompt는 0.026/0.004였고, `k=5`, `alpha=0.3`이 최적이었다. 더 많은 examples는 단조롭게 개선하지 않았다.
- 3 rounds 모두 Micro-F1 >0.70, Macro-F1 >0.50이라고 보고했지만 round별 값·분산·신뢰구간은 제시하지 않았다.

이 결과는 “정보가 많을수록 좋다”가 아니라 **관련 정보를 압축하고 적절한 과거 사례를 배치하는 것**이 성능의 핵심임을 보여준다. 다만 전체 RCACopilot과 GPT-4 Prompt의 차이는 retrieval, demonstrations, prompt structure가 동시에 달라 순수한 단일 구성요소 효과가 아니다.

## 6. 실험 비평과 재현성

강점은 실제 규모, 장기 배치, 심한 class imbalance에서 micro/macro F1을 모두 보고한 점이다. GPT-3.5와 GPT-4 결과가 거의 같은 것도 framework/context가 모델 크기보다 큰 레버일 수 있음을 시사한다.

그러나 653건의 category 수와 class별 support, confusion matrix, confidence interval, 유의성 검정은 없다. random/temporal split 여부도 명확하지 않아 유사한 recurring incidents가 train/test에 걸쳐 있을 가능성을 배제하기 어렵다. 사람이 만든 handler가 이미 alert별 진단 지식을 담으므로 LLM의 순기여와 workflow의 순기여가 얽혀 있다. 코드·데이터·handlers·prompts가 공개되지 않아 완전 재현은 불가능하다. OCE 만족도도 정량 설문 규모 없이 서술된다.

## 7. SRE 직감 평가

정보 수집 handler는 실제 on-call에서 충분히 유용하다. 반면 새 장애·monitor blind spot·잘못된 scope에서는 100% handler activation 수치가 의미가 없다. 특히 과거 incident의 category를 그대로 demonstration으로 넣는 구조는 recurring incident에는 강하지만, benchmark에서 동일 fault label이나 자기 runbook이 검색되면 reasoning이 아닌 shortcut으로 높은 점수를 낼 수 있다.

## 8. thesis-rca 적용과 차별점

- 직접 근거: V2.2에서 관찰한 “긴/혼합 context가 항상 유리하지 않다”는 문제에 Table 3이 직접 대응한다. length placebo와 source별 arm을 유지할 이유가 강해진다.
- retrieval 설계: recency+similarity 자체보다 retrieved example이 fault label을 노출하는지 먼저 audit해야 한다.
- 차별점: RCACopilot는 production category prediction과 handler reuse를 최적화한다. thesis-rca는 controlled injection에서 Runtime·GitOps·RAG의 인과적 정보 기여, label/runbook/diff leakage, judge robustness를 분리한다.
- 고정 모델 적합성: GPT-3.5와 GPT-4의 Micro-F1 차이가 0.005에 그쳐, `gpt-4o-mini`를 고정하고 context framework를 실험하는 방향과 양립한다. 단 데이터·task 차이 때문에 동일 효과를 기대해서는 안 된다.

## 9. 기억할 핵심 문구

원문의 핵심 표현은 “incident-specific automatic workflows”, “summarized diagnostic information”, “few-shots CoT reasoning”이다. 논문이 주는 가장 중요한 경고는 excess information이 prediction을 악화할 수 있다는 점이다.
