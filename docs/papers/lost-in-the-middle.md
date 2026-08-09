# 논문 심층 분석: Lost in the Middle: How Language Models Use Long Contexts

> 분석일: 2026-08-09
> 분석자: 20년차 SRE 전문가 관점
> 논문: Nelson F. Liu 외, 2024, *Transactions of the Association for Computational Linguistics* 12:157–173
> URL: https://aclanthology.org/2024.tacl-1.9/
> DOI: https://doi.org/10.1162/tacl_a_00638
> 근거 등급: **인접 방법론 근거** — Kubernetes/RCA 연구가 아니라 long-context QA·검색 실험이다.

## 1. 한 줄 요약

관련 증거가 프롬프트의 어디에 놓이는지만 바꿔도 성능이 크게 변하므로, Runtime·GitOps·RAG의 RCA 비교에서는 컨텍스트 길이뿐 아니라 증거 위치와 순서도 독립 교란변수로 통제해야 한다.

## 2. 핵심 문제와 기존 한계

긴 컨텍스트를 입력할 수 있다는 사양과 그 안의 증거를 안정적으로 사용하는 능력은 다르다. 기존 long-context 평가는 주로 최대 길이나 perplexity를 보고했지만, 이 논문은 정답 증거의 위치를 통제해 실제 활용 능력을 측정한다.

RCA에서는 여러 로그·메트릭·manifest·GitOps reconciliation 이벤트를 한 프롬프트에 직렬화한다. 따라서 System B의 향상이 GitOps 정보의 진단 가치가 아니라 중요한 단서가 프롬프트 앞·뒤에 놓인 결과일 수 있고, 반대로 유효한 단서가 중간에 묻혀 GitOps 효과가 과소평가될 수도 있다.

## 3. 핵심 기법과 원리

논문은 두 통제 과제를 사용한다.

1. **Multi-document QA**: NaturalQuestions-Open의 2,655개 질문을 사용하고, 정확히 한 문서만 정답을 포함하도록 구성한다. Contriever로 고른 distractor와 정답 문서의 순서를 바꾸되 정답 자체와 문서 집합은 고정한다.
2. **Key-value retrieval**: 무작위 128-bit UUID key-value 쌍을 JSON에 넣고, 목표 쌍의 위치와 전체 쌍 수만 바꾼다. 자연어 의미라는 교란을 제거한 최소 검색 과제다.

평가 흐름은 다음과 같다.

`동일 질문·동일 증거 집합 → 정답 증거 위치/문서 수만 변경 → greedy decoding → exact-answer accuracy 비교`

GPT-3.5-Turbo/16K, Claude-1.3/100K, MPT-30B-Instruct, LongChat-13B(16K)를 비교했고 일부 GPT-4 실험도 같은 추세를 보였다. 핵심 관찰은 시작과 끝에서 높고 중간에서 낮은 U자형 성능이다.

## 4. 실험 결과와 비평

### 검증된 정량 결과

- 10·20·30개 문서 설정에서 GPT-3.5-Turbo의 multi-document QA 정확도는 증거 위치에 따라 최악 조건에서 **20 percentage points 이상** 하락했다. 20·30문서 최악 조건은 문서를 주지 않은 closed-book 정확도 **56.1%**보다도 낮았다(§2.3, Figure 5, Table 1).
- closed-book/oracle 정확도는 GPT-3.5-Turbo가 **56.1%/88.3%**, GPT-3.5-Turbo-16K가 **56.0%/88.6%**, Claude-1.3이 **48.3%/76.1%**, Claude-1.3-100K가 **48.2%/76.4%**였다(Table 1). 긴 window 자체가 증거 사용 개선을 보장하지 않았다.
- Flan-UL2는 학습 시 최대 길이 안에서는 위치별 best–worst 차이가 **1.9 points**였지만, 학습 길이를 넘으면 U자형 저하가 나타났다(§4.1, Figure 8).
- query를 문맥 앞과 뒤에 모두 둔 query-aware contextualization은 75·140·300 key-value 쌍에서 거의 완벽한 검색을 만들었지만, multi-document QA의 위치 민감성은 거의 개선하지 못했다(§4.2, Figures 7–9).
- 실제 retriever-reader 사례에서 top-20을 넘어 top-50까지 문서를 늘려도 reader 정확도 증가는 GPT-3.5-Turbo 약 **1.5 points**, Claude-1.3 약 **1 point**에 그쳤다(§5, Figure 11).

### 설계 강점

- 문서 집합은 고정하고 정답 문서 위치만 바꾸므로 위치 효과의 인과적 해석이 강하다.
- closed-book과 oracle을 함께 제시해 모델 지식과 컨텍스트 사용의 상·하한을 분리한다.
- 자연어 QA와 synthetic retrieval을 함께 사용해 단순 검색 실패와 의미 추론 실패를 구분한다.

### 한계

- 2023년 계열 모델 중심이며 `gpt-4o-mini`를 시험하지 않았다.
- 정확도 곡선과 절대 차이는 제시하지만 반복 API 생성에 대한 신뢰구간이나 유의성 검정은 핵심 설계가 아니다.
- NaturalQuestions/Wikipedia QA는 다중 telemetry 간 시간·인과 관계를 요구하는 RCA보다 단순하다.

## 5. 실무 적용 가능성

이 논문의 직접 적용 대상은 모델 개선이 아니라 **thesis-rca의 구성 타당성 감사**다.

- Runtime·GitOps·RAG·length-placebo 조건에서 공통 섹션 순서와 token budget을 고정한다.
- fault별 핵심 evidence span의 시작 token, 전체 token 대비 상대 위치, 앞·뒤 여백을 raw JSON에 기록한다.
- 대표 trial에 대해 핵심 GitOps/RAG evidence를 `front/middle/end`로 순환하는 위치 placebo를 추가한다.
- retrieval top-k를 늘릴 때 retrieval recall과 RCA correctness를 별도로 기록한다. 더 많은 문서가 더 높은 진단 성능을 뜻한다고 가정하지 않는다.
- 유효 증거를 앞쪽으로 재정렬하는 개선을 쓰더라도, 정보 추가 효과와 위치 최적화 효과를 별도 ablation으로 분리한다.

비용은 같은 컨텍스트의 3개 순열을 생성·평가하는 추가 API 호출이다. 모든 60 case에 적용하기보다 fault group별 사전 지정 subset에서 위치 효과를 측정한 뒤 필요 시 확대하는 편이 현실적이다.

## 6. SRE 직감 평가

실제 on-call 프롬프트는 검색 문서보다도 더 불균질하다. alert summary, 최근 로그, resource YAML, Git diff, controller event가 순서대로 붙으면 중간 블록의 중요한 신호가 묻히기 쉽다. 따라서 프롬프트가 성공한 한 사례만 보고 “GitOps evidence가 유효하다”고 결론 내리면 위험하다.

이 통제는 특히 evidence가 짧고 결정적인 manifest mismatch, reconciliation error, rollout revision에서 유용하다. 반면 원인이 긴 시간축에 분산된 cascading fault에서는 단일 span의 위치만 바꾸는 실험이 실제 난도를 충분히 대표하지 못한다.

## 7. 약점과 위험

- 논문의 U자형 결과를 모든 최신 모델과 모든 RCA prompt에 보편 법칙처럼 적용하면 안 된다.
- 문서 순서를 바꾸면 단순 위치뿐 아니라 telemetry의 시간적 서사도 바뀔 수 있다. RCA permutation은 섹션 내부 chronology를 보존해야 한다.
- 관련 증거를 맨 앞에 두는 것은 성능을 높일 수 있지만, retrieval 단계가 정답을 알고 재정렬했다면 새로운 leakage가 된다.
- top-k truncation은 잡음을 줄이지만 원인 후보를 미리 제거해 recall을 훼손할 수 있다.

## 8. 우리 실험에의 적용 방안

| 적용 항목 | 구현 수준 | 예상 효과 | 주의사항 |
|---|---:|---|---|
| `evidence_start_token`, `relative_position` 기록 | 낮음 | 위치 교락 사후 감사 | tokenizer를 조건 간 동일하게 사용 |
| front/middle/end 순환 ablation | 중간 | 컨텍스트 기여와 위치 효과 분리 | 내용·길이·섹션 내부 순서 고정 |
| top-k별 retrieval recall/RCA score 동시 측정 | 중간 | “더 많은 RAG=더 좋은 RCA” 가정 검증 | 자기 런북은 먼저 마스킹 |
| 섹션 순서 randomization seed 기록 | 중간 | order effect 추정 | trial별 무작위화가 fault와 균형을 이루게 함 |
| 위치별 효과크기·paired CI 보고 | 중간 | 단일 accuracy보다 강한 주장 | 같은 case의 paired outcome으로 분석 |

V2.3의 최소 권고안은 **동일 case·동일 evidence에서 위치만 바꾸는 paired audit**다. 이 논문은 RAG 자기 런북 누출 자체를 다루지 않으므로, leakage 차단은 별도의 provenance·masking 통제가 필요하다.

## 9. 핵심 인용

저작권 한도를 지키기 위해 기억할 원문은 짧은 구절만 남긴다.

- “position of relevant information” (§2)
- “U-shaped performance curve” (§2.3)
- “Is More Context Always Better?” (§5)
