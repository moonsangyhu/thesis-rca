# results/ — 실험 결과

## 목적

Ground Truth 레이블, System A/B의 시행별 RCA 결과, 평가 점수, 통계 분석 등 모든 실험 산출물을 저장한다. 논문의 모든 실험적 주장은 이 디렉토리의 데이터 파일로 추적 가능하다.

## Ground Truth (`ground_truth.csv`)

**50건의 레이블된 장애 사례** (F1~F10 × 5회)로 각 장애 주입 실험의 기대 결과를 정의한다. System A와 System B의 출력은 이 레이블을 기준으로 채점된다.

### 스키마

| 컬럼 | 설명 |
|------|------|
| `fault_id` | 장애 유형 식별자 (F1~F10) |
| `trial` | 장애 유형별 시행 번호 (1~5) |
| `fault_name` | 장애 이름 (예: OOMKilled) |
| `target_service` | 장애 주입 대상 Online Boutique 서비스 |
| `injection_method` | 장애 주입 방법 |
| `expected_root_cause` | Ground Truth 근본 원인 설명 |
| `affected_components` | 장애 영향을 받는 서비스 (쉼표 구분) |
| `severity` | 예상 심각도: critical, high, medium, low |
| `primary_symptoms` | 관측 가능한 증상 (Pod 상태, HTTP 에러 등) |
| `expected_metrics` | 반응해야 하는 Prometheus 메트릭/쿼리 |
| `expected_log_patterns` | Loki에서 예상되는 로그 패턴 |
| `expected_recovery_action` | 올바른 복구 조치 |

### 설계 원칙

- 각 장애 유형은 시행마다 **다른 Online Boutique 서비스**를 대상으로 하여 다양성 확보
- 시행별 주입 방법이 상이함 (예: F1은 frontend, cartservice, checkoutservice 등에서 OOMKilled 테스트)
- 심각도는 **사용자 영향 기준**: critical = 전체 서비스 중단, low = 비핵심 기능 저하

## V1 실험 결과 (`experiment_results.csv`)

> 실험일: 2026-04-02 18:17 ~ 2026-04-03 01:26 (약 7시간)
> 모델: gpt-4o-mini (openai) | 총 토큰: 291,848 | 비용: $0.0521

### 핵심 결과

| | System A (Obs Only) | System B (+ GitOps + RAG) | 차이 |
|---|---|---|---|
| **전체 정확도** | **15/50 (30%)** | **42/50 (84%)** | **+54%p** |

### Fault별 상세

| Fault | 장애 유형 | System A | System B | 차이 | 비고 |
|-------|-----------|----------|----------|------|------|
| F1 | OOMKilled | 1/5 (20%) | 3/5 (60%) | +40%p | A는 F2(CrashLoop)로 오진 |
| F2 | CrashLoopBackOff | 3/5 (60%) | 5/5 (100%) | +40%p | B 완벽 |
| F3 | ImagePullBackOff | 2/5 (40%) | 4/5 (80%) | +40%p | |
| F4 | NodeNotReady | 0/5 (0%) | 3/5 (60%) | +60%p | A 전멸 |
| F5 | PVCPending | 5/5 (100%) | 5/5 (100%) | 0%p | 유일하게 A=B |
| F6 | NetworkPolicy | 0/5 (0%) | 3/5 (60%) | +60%p | A 전멸 |
| F7 | CPUThrottle | 0/5 (0%) | 5/5 (100%) | +100%p | B 완벽, A 전멸 |
| F8 | ServiceEndpoint | 0/5 (0%) | 4/5 (80%) | +80%p | A 전멸 |
| F9 | SecretConfigMap | 0/5 (0%) | 5/5 (100%) | +100%p | B 완벽, A 전멸 |
| F10 | ResourceQuota | 4/5 (80%) | 5/5 (100%) | +20%p | |

### 주요 발견

**1. GitOps 컨텍스트가 결정적인 장애 유형**

F4, F6, F7, F8, F9에서 System A는 0/25 (0%) — observability 신호만으로는 구조적으로 진단 불가능한 장애 유형이 존재한다.

- F7 (CPUThrottle): CPU 제한 메트릭은 보이지만, "왜 제한이 걸렸는지"(배포에서 CPU limit 변경)는 GitOps diff에만 있음
- F9 (SecretConfigMap): Pod 시작 실패는 보이지만, "어떤 secret이 잘못됐는지"는 deployment manifest 변경 이력에 있음
- F6 (NetworkPolicy): 연결 거부 로그는 보이지만, NetworkPolicy 적용 사실은 GitOps에만 있음

**2. Observability만으로 충분한 장애 유형**

F5 (PVCPending)는 A/B 모두 100% — PVC 상태와 이유가 K8s 이벤트에 명확히 기록되므로 추가 컨텍스트 불필요. F10 (ResourceQuota)도 A=80%로 높음 — quota 초과 메시지가 이벤트에 직접 나타남.

**3. System A의 오진 패턴**

System A는 주로 증상이 비슷한 다른 fault로 오진:
- F1(OOMKilled) → F2(CrashLoopBackOff)로 오진: Pod restart는 보이지만 OOM 원인을 구분 못함
- F7(CPUThrottle) → F4(NodeNotReady)로 오진: 느려지는 증상을 노드 문제로 오해
- F8(ServiceEndpoint) → F4로 오진: 서비스 불통을 노드 문제로 오해

### CSV 스키마

| 컬럼 | 설명 |
|------|------|
| `timestamp` | 시행 완료 시각 (ISO 8601) |
| `fault_id` | 장애 유형 (F1~F10) |
| `trial` | 시행 번호 (1~5) |
| `system` | A (observability only) 또는 B (+GitOps+RAG) |
| `identified_fault_type` | LLM이 예측한 장애 유형 |
| `correct` | 정답 여부 (1=정답, 0=오답) |
| `root_cause` | LLM이 출력한 근본 원인 |
| `confidence` | LLM 자체 신뢰도 (0~1) |
| `affected_components` | 영향받는 컴포넌트 목록 |
| `remediation` | 권장 복구 조치 |
| `model` | 사용 모델 (gpt-4o-mini) |
| `latency_ms` | LLM 응답 시간 |
| `prompt_tokens` | 프롬프트 토큰 수 |
| `completion_tokens` | 응답 토큰 수 |
| `error` | 에러 메시지 (있을 경우) |

## 예정 산출물

| 파일 | 설명 |
|------|------|
| `experiment_results_v2.csv` | V2 실험 결과 (Harness Engineering: CoT + Evidence Chain + Evaluator + Retry) |
| `ablation_results.csv` | AB-1~AB-5 절삭 실험 결과 |
| `wilcoxon_test.json` | 통계적 유의성 검정 결과 |
