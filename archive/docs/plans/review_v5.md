# V5 실험 계획서 리뷰

> 리뷰일: 2026-04-08
> 리뷰어: hypothesis-reviewer agent
> 대상: V5 Structured Symptom Extraction -> Diagnosis 2단계 분리

---

## 1. 방법론 비평

### 1-1. 긍정적 측면

- **단일 독립변수 변경**: V4의 3변수 동시 변경 실패를 반영한 최소 개입 설계
- **V3 인프라 재사용**: Context Builder, Evaluator, RAG를 V3과 동일하게 유지하여 비교 가능성 확보
- **V4 "분류 잠금" 회피 설계**: "Do NOT diagnose" 명시, fault type 관련 용어 배제

### 1-2. 핵심 우려사항

**(1) 정보 손실 문제 (Information Bottleneck)**
Step 1(~800 토큰 출력)이 원본 컨텍스트(3,000-6,000 토큰)의 정보 병목을 형성. gpt-4o-mini가 Step 1에서 누락한 신호는 Step 2에서 복구 불가. 파싱은 성공하되 핵심 신호가 누락된 경우가 더 위험하며 fallback이 작동하지 않음.

**(2) Step 2의 정보 부족**
원본 로그의 시간순서, 발생 빈도, 문맥적 단서가 JSON 구조화 과정에서 손실. V3에서 정답에 기여한 원본 컨텍스트 요소가 제거되는 셈.

**(3) Evaluator-Generator 정보 비대칭**
Evaluator는 원본 context, Generator(Step 2)는 구조화된 symptoms만 입력. Retry에서 Evaluator가 "원본에 X 신호가 있다"고 지적해도 Generator는 X를 참조 불가.

**(4) MAX_TOKENS_EXTRACTION = 1024의 충분성**
F4, F10처럼 다수 pod가 영향받는 경우 1024 토큰으로 부족할 수 있음.

---

## 2. 교란 변수 식별

### 2-1. LLM 호출 횟수 증가
2회 호출로 총 토큰이 증가. 성능 향상이 "구조 분리" vs "더 많은 연산" 중 어디서 오는지 구분 불가. 사후 분석에서 토큰 사용량과 정확도의 상관관계 분석 필요.

### 2-2. Severity 분류 편향
severity 분류가 Step 2의 Signal Prioritization에 직접 영향. F4에서 DiskPressure가 "critical"로, 실제 원인(kubelet 중지)이 "high"로 분류되는 시나리오를 dry-run에서 확인 필요.

### 2-3. JSON 구조의 프레이밍 효과
type 필드("oom", "cpu_throttle" 등)가 진단을 간접 유도 가능. F1과 F10의 OOMKilled가 모두 "oom"으로 태깅되어 구분이 어려워질 수 있음.

### 2-4. 시간적 교란
V3와 V5 사이 클러스터 상태 변화(DiskPressure 등). paired comparison의 전제(동일 조건) 약화.

---

## 3. V4 실패 패턴 재현 위험

| 측면 | V4 Fault Layer | V5 Symptom Extraction |
|------|---------------|----------------------|
| 잠금 위험 | 높음 (레이어가 진단 범위 제한) | 낮음 (모든 신호가 리포트에 포함) |
| 오분류 복구 | 불가 | 부분 가능 |

V5의 severity 분류는 V4의 Fault Layer보다 잠금 위험이 낮으나, dry-run에서 반드시 검증 필요.

---

## 4. 개선 제안

1. **Signal count threshold fallback**: total_signals < 3이면 V3 fallback 작동
2. **Ground truth signal 자동 검증**: expected_log_patterns 키워드가 raw_evidence에 포함되는지 자동 매칭
3. **Severity 필드 제거 의사결정 기준**: "3개 dry-run 중 2개 이상에서 GT 신호가 non-critical이면 severity 제거"
4. **MAX_TOKENS_EXTRACTION 상향**: 1024 → 1536 고려

---

## 5. 통계 검정 적절성

### 5-1. McNemar Test — 검정력 부족 우려
n=50에서 6pp 차이(40%→46%)는 불일치 쌍 ~10건. 검정력 20% 미만으로 유의성 달성이 매우 어려움.

**권고**:
- 효과 크기(odds ratio) + 95% CI 병행 보고
- 사전 검정력 분석 포함
- 탐색적 분석에 FDR 보정 또는 탐색적임을 명시

### 5-2. Wilcoxon Test
n=10(fault type별)으로 McNemar보다 검정력이 낮음. 보조적/탐색적 분석으로만 위치.

---

## 6. 종합 평가

V5 계획서는 V4 교훈을 잘 반영한 신중한 설계. **승인 권장**.

핵심 리스크 3가지:
1. **정보 병목**: Signal count threshold fallback 추가로 완화
2. **Evaluator-Generator 비대칭**: Retry 효과 제한 가능, 사후 분석 포함
3. **통계적 검정력 부족**: 효과 크기 보고 병행

dry-run 결과에 기반한 의사결정 기준을 사전에 명확히 정의하면 관리 가능.
