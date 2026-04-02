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

## 예정 산출물

| 파일 | 설명 |
|------|------|
| `system_a_results.csv` | System A (기준선) 시행별 RCA 출력 |
| `system_b_results.csv` | System B (제안) 시행별 RCA 출력 |
| `evaluation_scores.csv` | 시행별 정확도, 정밀도, 재현율, F1 점수 |
| `ablation_results.csv` | AB-1~AB-5 절삭 실험 결과 |
| `wilcoxon_test.json` | 통계적 유의성 검정 결과 |
