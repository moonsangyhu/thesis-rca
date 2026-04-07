# V3 실험 계획서 리뷰

**리뷰 대상**: `docs/plans/experiment_plan_v3.md`
**리뷰 일시**: 2026-04-07
**리뷰어**: @hypothesis-reviewer

---

## 1. 방법론적 타당성

### 긍정적 평가
계획서는 V3의 핵심 변경을 Harness 하나로 제한하고, 모델을 gpt-4o-mini로 고정하여 독립 변수를 분리하려는 의도가 명확하다.

### 우려 사항

**(a) Harness는 단일 변수가 아니다.** V3는 V2 대비 최소 4가지 변경을 동시에 도입: (i) evidence chain 출력 포맷 추가, (ii) keyword matching 기반 evidence verification, (iii) evaluator에 의한 4차원 평가, (iv) critique 피드백 기반 retry. 어떤 요소가 정확도 향상에 기여했는지 분리 불가.

**권고**: retry_count=0인 trial에서의 V2 대비 정확도 변화를 별도로 분석하여, 프롬프트 변경 효과와 retry 효과를 사후적으로 분리.

**(b) V2와 V3의 system prompt 차이.** V3 SYSTEM_PROMPT에는 evidence chain, alternative_hypotheses, bilingual output 등 V2에 없는 지시사항 포함. 프롬프트 차이를 명시적으로 문서화 필요.

---

## 2. 교란 변수 식별

**(a) 토큰 누적 집계 오류.** retry 시 새 RCAOutput이 생성되어 이전 회차의 토큰 카운트가 소실. 총 비용 과소 집계 가능.

**(b) Retry 시 이전 진단 비전달.** `_generate_with_feedback()`은 evaluator critique만 전달하고 이전 진단 결과를 포함하지 않음. 모델이 자신의 이전 답변을 모른 채 재분석.

**(c) Temperature 미명시.** BaseLLMClient 기본값에 의존. V1/V2와 동일한지 확인 필요. retry 시 동일 temperature면 유사 출력 생성 가능.

**(d) 순서 효과.** System A가 항상 먼저 실행되어 B는 더 안정화된 상태에서 신호 수집 가능. V1/V2 동일 문제이므로 버전 간 비교에는 영향 적으나, A vs B 비교에서 교란 변수.

---

## 3. 자기 평가 편향 (핵심 위험)

- LLM은 자신의 생성물에 체계적으로 높은 점수 부여 경향 (Zheng et al., NeurIPS 2024)
- gpt-4o-mini는 SELF-REFINE에 필요한 모델 강도에 미달 가능 (Madaan et al., NeurIPS 2023)
- should_retry=false 과도 반환, 환각 증거 미탐지 위험

**권고 사후 분석:**
- should_retry=true였으나 이미 correct=1이었던 trial 수 (불필요 retry)
- should_retry=false였으나 correct=0이었던 trial 수 (누락 retry)
- retry 후 correct 1→0 전환 사례 수 (퇴행)

---

## 4. Evidence Verification 한계

**(a) 4자 미만 단어 제외.** "OOM", "CPU", "DNS", "PVC" 같은 K8s 핵심 약어가 매칭에서 제외됨.

**(b) 부분 문자열 매칭.** "service"가 "cartservice", "emailservice" 등 어디서든 매칭되어 faithfulness_score 인위적 상승 가능.

**(c) match_ratio >= 0.5 임계값 근거 부재.** 민감도 분석 필요.

**권고**: faithfulness_score를 "참고 지표"로만 활용. faithfulness_score=1.0이면서 correct=0인 사례 수동 검토.

---

## 5. 통계적 타당성

**(a) Paired 비교 제한.** V2와 V3는 다른 시점에 실행되어 같은 입력 보장 불가. fault_id별 정확도로 paired하면 n=10으로 검정력 매우 낮음. 효과 크기(effect size)와 신뢰 구간 함께 보고 필요.

**(b) 다중 비교 보정.** 5가지 이상 분석 계획에 Bonferroni/Holm-Bonferroni 보정 미적용.

**(c) Retry 효과 표본 크기.** 실제 교정 사례 6-20건 예상. 기술 통계로만 보고하는 것이 적절.

---

## 6. 대안 가설

**(a) 프롬프트 정교화 효과 vs Harness 효과.** V3 prompt가 V2보다 상세하여 Harness 없이도 정확도 향상 가능. 순수 Harness 효과 분리에는 "V3 prompt + evaluator/retry 없음" 조건 필요.

**(b) Retry regression 위험.** 첫 시도 정답이 evaluator의 "증거 부족" 평가로 retry trigger, 두 번째에서 오답 전환 가능. System A에서 특히 위험 (GitOps 컨텍스트 부재로 증거 본질적 부족).

**(c) should_retry 비결정성.** evaluator LLM 재량에 의존하여 재현성 저해. 규칙 기반 임계값(예: overall_score < 6.0이면 retry) 추가 고려.

---

## 7. 발견된 버그

### retry_count 무한루프 (수정됨)

engine.py line 39-55에서 `_generate_with_feedback()`이 새 RCAOutput을 생성하여 retry_count가 0으로 리셋. should_retry가 계속 true이면 무한루프 발생.

**수정**: retry_count를 analyze() 메서드 레벨 변수로 분리 (2026-04-07 수정 완료).

---

## 8. 종합 판단

| 관점 | 평가 | 핵심 권고 |
|------|------|-----------|
| 구성 타당도 | 보통 | Harness 4개 하위 변경 포함, 프롬프트 효과 분리 필요 |
| 내적 타당도 | 주의 필요 | retry_count 버그(수정됨), should_retry 비결정성, 온도 미명시 |
| 외적 타당도 | V1/V2와 동일 | Online Boutique 한정, gpt-4o-mini 한정 |
| 통계적 타당성 | 보통 | paired 비교 제한, 다중 비교 보정 누락 |
| 대안 가설 | 중요 | 프롬프트 정교화 효과, retry regression, 자기평가 편향 |

**결론**: retry_count 버그 수정 + run.py 안정성 반영을 선행 조건으로, **실험 진행 가능**. 나머지 권고사항은 사후 분석에서 반영.
