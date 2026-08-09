# 논문 심층 분석: Overestimation in LLM Evaluation — Data Contamination’s Impact

> 분석일: 2026-08-09
> 분석자: 20년차 SRE 전문가 관점
> 논문: Muhammed Yusuf Kocyigit 외, 2025, ICML 2025, PMLR 267:31105–31132
> URL: https://proceedings.mlr.press/v267/kocyigit25a.html
> PDF: https://raw.githubusercontent.com/mlresearch/v267/main/assets/kocyigit25a/kocyigit25a.pdf
> 근거 등급: **인접 방법론 근거** — machine translation pre-training contamination 연구이며 RAG/RCA 연구가 아니다.

## 1. 한 줄 요약

입력과 정답이 함께 노출된 오염은 실제 능력 향상 없이 평가 점수를 최대 30 BLEU까지 부풀렸으므로, thesis-rca의 “fault 설명+정답 라벨” 자기 런북 회수는 진단 추론과 분리된 contamination 조건으로 취급해야 한다.

## 2. 핵심 문제와 기존 한계

benchmark contamination 연구는 흔히 이미 학습된 black-box 모델에서 overlap을 추정하므로, clean baseline을 모르고 오염 시점·형식·빈도를 독립적으로 바꾸기 어렵다. 이 논문은 깨끗한 train–test split에서 출발해 오염을 의도적으로 주입함으로써 점수 인플레이션을 인과적으로 측정한다.

thesis-rca의 V2.2 문제는 pre-training contamination과 동일하지 않다. 모델 가중치가 평가 예시를 본 것이 아니라, 평가 시 retrieval이 주입 fault의 정답 라벨을 포함한 자기 런북을 제공한 **test-time retrieval leakage**다. 다만 “입력 단서와 목표 출력의 결합 노출이 평가 점수를 실제 일반화보다 크게 높인다”는 통제 원리는 직접 전이된다.

## 3. 핵심 기법과 원리

연구진은 다음 파이프라인을 구성했다.

`8-gram overlap 탐지·제거 → 1B/8B clean baseline 공동 학습 → 동일 checkpoint에서 오염 branch → clean WMT’24와 contaminated WMT’23 동시 평가`

- 1B·8B decoder-only Transformer를 같은 데이터·hyperparameter로 325B tokens, 155K steps, context 4,096, batch 512로 학습했다.
- subword 8-gram 검색에서 source 또는 target token의 최장 일치 구간이 **70% 초과**면 contaminated로 판정했다. 기존 test 예시 약 10%를 발견해 제거했다.
- 오염 독립변수는 형식(`Source`, `Target`, paired prompted `Full`), 시점(학습 30%·60%·90%·30–90% 균등), 빈도(1·10·100 copies)다.
- WMT’23 10개 language pair의 contaminated set과 겹치는 WMT’24 5개 pair의 non-contaminated set을 비교했다.
- checkpoint branching은 초기화·이전 학습 이력을 공유해 총 학습 budget을 **53.6%** 줄이고 branch 간 변동을 억제했다.

## 4. 실험 결과와 비평

### 검증된 정량 결과

- paired source-target를 test prompt와 같은 형식으로 넣은 `Full` contamination은 1B에서 최대 약 **9 BLEU**, 8B에서 최대 **30 BLEU**의 과대평가를 만들었다. 8B의 평균 inflation은 1B의 **2.5배**였다(§5, Figure 2).
- 같은 task의 오염되지 않은 WMT’24와 비교하면 `Full` 조건의 WMT’23 개선이 최대 **26 BLEU** 더 컸다(§5.1, Figure 3). 이는 일반 번역 능력 향상보다 test-specific inflation임을 지지한다.
- source-only와 target-only는 전 언어에서 일관된 상승을 만들지 않았고, copy 수 증가에도 전체 효과가 유의하게 커지지 않았다. 입력-정답의 결합 형식이 핵심이었다.
- 초기 오염의 약 **70 BLEU** 순간 spike는 약 100K step 뒤 약 **40 BLEU**로 줄었지만, 후반 노출은 최종 격차가 더 오래 남았다. 균등 분산 오염은 sharp peak 없이도 최종 inflation이 컸다(§5.2, Figure 4).
- 사전학습 데이터에 의도적인 언어 표현이 없는 Achinese·Wolof·Yoruba에서는 8B 오염 모델도 BLEU 증가가 대체로 **1–3 points 이내**였다(Table 4).

### 설계 강점

- clean baseline, contaminated test, 별도 clean test를 함께 두어 memorization과 task generalization을 구분한다.
- checkpoint·data order·initialization을 공유해 단일 오염 변수의 효과를 강하게 격리한다.
- 오염의 형식·시점·빈도·모델 크기를 분해해 단순 “overlap 유무”보다 상세한 메커니즘을 제시한다.

### 한계

- 저자도 인정하듯 각 조건을 여러 random seed/data order로 반복하지 않았고, 단일 canonical ordering·initialization을 사용했다.
- 번역 BLEU의 1–30 points는 RCA correctness score로 환산할 수 없다.
- 1B/8B open model의 pre-training 결과를 closed `gpt-4o-mini`의 test-time RAG에 직접 일반화할 수 없다.

## 5. 실무 적용 가능성

이 논문에서 thesis-rca가 가져올 핵심은 **오염된 평가군과 clean holdout을 동시에 두는 설계**다.

- RAG corpus에서 fault ID, fault name, injection command, expected symptom, root-cause sentence를 span 단위로 표시한다.
- 동일 fault에 대해 `self-runbook`, `masked self-runbook`, `cross-fault runbook`, `no-RAG` 조건을 만든다.
- `masked`는 라벨 문자열만 지우는 수준이 아니라 명령·고유 error string·manifest diff처럼 답을 복원할 수 있는 결합 단서도 단계적으로 제거한다.
- V2.3 fault와 표현이 겹치지 않는 clean holdout fault 또는 paraphrased runbook으로 일반화 여부를 확인한다.
- retrieval 결과마다 source document ID, version, chunk span, fault linkage, mask transform을 raw 결과에 남긴다.

## 6. SRE 직감 평가

실제 runbook은 특정 error string과 “원인→조치”를 함께 담는 경우가 많다. 운영에는 유용하지만, 같은 runbook을 만든 fault injection을 다시 평가하면 diagnosis가 아니라 lookup이 된다. 특히 fault name이 가려져도 injection command, namespace, container name, expected alert의 조합이 사실상 정답 key가 될 수 있다.

반대로 production RAG에서 알려진 runbook을 검색하는 행위 자체가 잘못은 아니다. 연구 질문이 “운영 시스템의 총 유용성”이면 허용할 수 있다. 하지만 thesis-rca의 RQ2처럼 **컨텍스트의 독립적 진단 기여**를 주장하려면 self-runbook 성능과 unseen/generalization 성능을 분리 보고해야 한다.

## 7. 약점과 위험

- pre-training contamination과 retrieval leakage를 같은 현상이라고 서술하면 구성 개념이 흐려진다.
- 문자열 마스킹만 통과한 문서를 “clean”으로 부르면 semantic leakage를 놓친다.
- clean holdout이 다른 fault 난이도나 campaign에서 수집되면 contamination 효과와 dataset shift가 교락된다.
- 높은 RAG 성능을 모두 leakage로 돌리는 것도 오류다. masked·cross-fault 대조군이 있어야 순기여를 추정할 수 있다.

## 8. 우리 실험에의 적용 방안

| 적용 항목 | 구현 수준 | 예상 효과 | 주의사항 |
|---|---:|---|---|
| chunk-level provenance ledger | 중간 | 어떤 답이 어떤 문서에서 왔는지 감사 | 문서 version/hash 보존 |
| self/masked/cross/no-RAG 4조건 | 중간 | retrieval utility와 shortcut 분리 | token length를 맞출 placebo 필요 |
| lexical+semantic leakage scanner | 높음 | 라벨 외 간접 정답 단서 탐지 | 자동 탐지는 수동 표본감사로 검증 |
| clean holdout fault 평가 | 높음 | unseen generalization 확인 | 동일 campaign·난이도 균형 |
| contamination effect의 paired CI | 중간 | 60-case 소표본 불확실성 표시 | fault별 cluster를 고려 |

V2.3의 핵심 estimand는 `self-runbook − masked self-runbook`의 shortcut 성분과 `masked self-runbook − no-RAG`의 잔여 지식 기여를 분리하는 것이다. 논문의 `Full` 대 partial contamination 비교가 이 분해의 방법론적 선례다.

## 9. 핵심 인용

저작권 한도를 지키기 위해 기억할 원문은 짧은 구절만 남긴다.

- “carefully decontaminated train-test split” (§1)
- “up to 30 BLEU points” (Abstract)
- “single canonical ordering” (§6)
