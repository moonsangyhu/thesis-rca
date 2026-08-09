# 논문 심층 분석: Rating Roulette — Self-Inconsistency in LLM-As-A-Judge Frameworks

> 분석일: 2026-08-09
> 분석자: 20년차 SRE 전문가 관점
> 논문: Rajarshi Haldar, Julia Hockenmaier, 2025, Findings of EMNLP 2025, 24986–25004
> URL: https://aclanthology.org/2025.findings-emnlp.1361/
> DOI: https://doi.org/10.18653/v1/2025.findings-emnlp.1361
> 근거 등급: **인접 평가 방법론 근거** — NLG judge 연구이며 Kubernetes/RCA 직접 연구가 아니다.

## 1. 한 줄 요약

같은 prompt·hyperparameter로도 LLM judge의 자기일치도가 낮고 단순 agreement accuracy가 이를 가릴 수 있으므로, RCA 평가는 반복 judge·chance-corrected reliability·다수결과 불일치율을 함께 보고해야 한다.

## 2. 핵심 문제와 기존 한계

기존 LLM-as-a-judge 연구는 인간과의 correlation 또는 accuracy를 주로 보고하지만, 같은 judge가 같은 항목을 반복 평가했을 때 같은 결과를 내는지 거의 측정하지 않는다. 단순 percent agreement는 우연 일치와 class imbalance도 교정하지 않는다.

thesis-rca의 0–1 correctness 또는 thresholded score가 단일 judge 호출에서 나오면, System A/B 차이가 모델 성능 차이인지 judge sampling noise인지 구별할 수 없다. 특히 60 case와 fault당 5 trial은 작은 차이에 민감하므로 judge variance가 순위 역전을 만들 수 있다.

## 3. 핵심 기법과 원리

논문은 Llama-3.1-70B-Instruct, DeepSeek-R1-Distill-Qwen, Qwen3-32B를 judge로 사용해 세 benchmark를 같은 prompt·설정으로 **독립 3회** 평가했다.

- **SummaC**: 6개 factual consistency dataset, binary label.
- **SummEval**: 1,700개 summary를 coherence·consistency·fluency·relevance의 1–5 Likert scale로 평가하며, 항목당 expert 3명·crowd 5명의 점수가 있다.
- **MT-Bench**: 80개 질문×30 response pair=2,400 examples 중, human rating이 2개 이상인 761개 subset을 agreement 분석에 사용했다.

binary에는 nominal, Likert와 `model_a/tie/model_b`에는 ordinal distance를 둔 **Krippendorff’s α**를 사용했다. 이 값은 우연 일치와 label distribution을 교정하고, 가변 annotator 수와 missing value를 처리할 수 있다. 초기에는 최대 10회까지 실행했으나 self-reliability가 유의하게 변하지 않아 본 실험은 3회로 정했다.

## 4. 실험 결과와 비평

### 검증된 정량 결과

- SummaC 3회 자기일치도 α는 Llama 3.1 **0.3263**, DeepSeek-R1 **0.6278**, Qwen 3 **0.7883**이었다(Table 1). 최신·대형 모델도 흔히 쓰는 0.8 기준에 미달했다.
- MT-Bench 자기일치도 α는 Llama 3.1 **0.265**, DeepSeek-R1 **0.507**, Qwen 3 **0.563**이었다. Qwen 3도 3회 모두 같은 판정을 한 case는 **61.3%**뿐이었다(§4).
- SummaC human label 대비 balanced accuracy는 단일 run 평균→3회 다수결에서 Llama **59.1±2.06→61.4**, DeepSeek **69.8±0.50→72.3**, Qwen **79.4±0.32→80.6**으로 올랐다(Table 2).
- sampling을 끈 조건은 Llama **58.4**, DeepSeek **69.3**, Qwen **79.2**로, 모두 각 3회 다수결보다 낮았다. 결정론적 decoding만으로 신뢰도와 정확도를 동시에 해결하지 못했다.
- SummEval expert α는 consistency **0.798**, fluency **0.588**, relevance **0.398**였고 crowd α는 전 metric **0.48–0.51**, expert–crowd는 최대 **0.247**이었다(§5.2). human gold도 evaluator 집단과 rubric에 따라 달랐다.
- MT-Bench human–human은 accuracy **0.827**이지만 α는 **0.478**이었다. human 대비 GPT-4는 accuracy **0.671**, α **0.396**이었다(Table 3). chance correction 전 agreement가 신뢰도를 과장할 수 있다.
- SummaC에서 few-shot/CoT는 Qwen 3 α를 default **0.7883**에서 각각 **0.7804/0.7796**으로 소폭 낮췄고, balanced accuracy도 **80.6/80.4**로 개선이 없었다(Appendix C.2).

### 설계 강점

- 동일 judge의 반복 판정을 별도 구성개념인 intra-rater reliability로 명시한다.
- binary·ordinal label에 맞는 α distance를 사용하고 accuracy와 나란히 보여 metric inflation을 확인한다.
- single run, 다수결, no-sampling을 직접 비교해 현실적인 완화책의 trade-off를 제시한다.

### 한계

- 사용 judge가 thesis의 `gpt-4o-mini`와 다르며, proprietary 최신 모델로 일반화되지 않는다.
- 3회 다수결의 개선은 보였지만 RCA처럼 객관적 root-cause rubric에서 필요한 반복 수를 산정하지 않는다.
- task subjectivity와 judge model 한계를 완전히 분리하지 못했고, 인간 annotation 자체도 불안정하다.
- “0.8 기준”은 관행적 threshold이지 모든 RCA 의사결정의 보편 기준은 아니다.

## 5. 실무 적용 가능성

V2.3에서는 generation variance와 judge variance를 교차 설계해야 한다.

`case × system × generation_repeat × judge_repeat × blinded_order`

- 같은 생성 답변을 judge에 최소 3회 독립 입력해 judge-only variance를 측정한다.
- 별도로 같은 case를 `gpt-4o-mini`가 여러 번 진단하게 해 generation variance를 측정한다.
- binary correctness에는 Cohen/Fleiss κ 또는 nominal Krippendorff α, ordinal score에는 ordinal α/ICC를 사전 지정한다.
- 최종 label은 다수결로 만들되, unanimous/majority/split과 원 judge score를 모두 보존한다.
- threshold 0.5·0.6·0.7 sweep마다 성능뿐 아니라 judge disagreement와 System A/B 순위 안정성을 보고한다.

## 6. SRE 직감 평가

같은 incident를 같은 rubric으로 평가했는데 판정이 흔들리면, 실험 결과는 on-call 품질보다 측정기 노이즈를 반영한다. 특히 “부분 정답이나 핵심 근거 부족”처럼 경계 사례에서 disagreement가 집중될 가능성이 높다. 단순 평균 accuracy보다 어떤 fault와 score 구간에서 judge가 흔들리는지 보는 것이 개선에 더 유용하다.

다수결은 빠른 완화책이지만 correlated error를 제거하지 않는다. 세 judge 호출이 모두 같은 잘못된 shortcut을 따르면 만장일치 오답이다. 따라서 blinded human audit와 deterministic evidence checks를 작은 calibration subset에 결합해야 한다.

## 7. 약점과 위험

- 생성 반복과 judge 반복을 섞으면 variance source를 식별할 수 없다.
- judge temperature를 0으로 고정해 같은 출력이 나오는 것을 “정확한 평가”로 오해하면 안 된다.
- α만 보고 effect size와 paired uncertainty를 생략하면 System 차이의 연구 질문에 답하지 못한다.
- majority label만 저장하면 disagreement 정보가 사라져 사후 robustness 분석이 불가능하다.
- human gold도 전문가·crowd 간 기준이 다르므로 RCA domain rubric과 annotator training이 필요하다.

## 8. 우리 실험에의 적용 방안

| 적용 항목 | 구현 수준 | 예상 효과 | 주의사항 |
|---|---:|---|---|
| 생성과 judge 반복 ID 분리 | 낮음 | 두 분산원 식별 | raw JSON schema에 둘 다 저장 |
| judge 3회+다수결 | 중간 | single-run noise 완화 | 원 판정과 split rate 보존 |
| nominal/ordinal Krippendorff α | 중간 | 우연 일치 교정 | scale에 맞는 distance 사전 지정 |
| threshold별 disagreement 표 | 낮음 | 0.5/0.6 순위 역전 해석 | threshold를 결과 후 선택하지 않음 |
| fault-stratified human audit | 중간 | domain validity 교정 | blind system·condition label |
| paired bootstrap CI/McNemar | 중간 | 성능차 불확실성 보고 | case pairing과 fault cluster 보존 |

최소 보고 세트는 `raw judge votes`, `majority correctness`, `judge unanimous rate`, `Krippendorff α`, `paired effect estimate+CI`, `threshold sweep`이다. 이 논문은 system-level 통계 검정을 직접 제시하지 않으므로 McNemar/cluster bootstrap의 선택은 thesis 설계에서 별도 정당화해야 한다.

## 9. 핵심 인용

저작권 한도를 지키기 위해 기억할 원문은 짧은 구절만 남긴다.

- “self-reliability” (§1)
- “intra-rater reliability” (§2)
- “three runs” (§3.2)
- “majority vote” (§5.1)
