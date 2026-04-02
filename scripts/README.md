# scripts/ — 실험 자동화

## 목적

장애 주입 실험의 전체 생명주기를 자동화하는 스크립트이다: Online Boutique 애플리케이션에 장애를 주입하고, 시행 간 클러스터를 안정화하며, RCA 파이프라인 출력을 Ground Truth 레이블과 비교 평가한다.

이 스크립트들은 **재현 가능한 실험**을 보장한다 — 50건의 모든 시행에서 동일한 절차, 타이밍, 데이터 수집 프로토콜을 따른다.

## 구조

| 디렉토리 | 설명 |
|----------|------|
| `fault_inject/` | F1~F10 장애 주입 스크립트. 특정 장애를 적용하고(예: F1-OOMKilled의 경우 메모리 limit을 32Mi로 설정), 증상이 나타날 때까지 대기 후 데이터 수집을 트리거한다. |
| `stabilize/` | 주입 후 복구 스크립트. 시행 간 클러스터를 깨끗한 상태로 복원한다: 매니페스트 변경 되돌리기, Pod 헬스 대기, 모니터링 베이스라인 확인. 실험 프로토콜에 따라 시행당 30분 안정화 대기. |
| `evaluate/` | 채점 및 평가 스크립트. System A/B RCA 출력을 `results/ground_truth.csv`와 비교하여 정확도/정밀도/재현율/F1을 산출하고, Wilcoxon signed-rank test로 통계적 유의성을 검정한다. |

## 상태

모든 스크립트는 **예정** — Online Boutique 배포 및 장애 주입 실험 단계에서 구현할 예정이다.

## 실험 프로토콜

```
각 장애 F_i (i = 1..10)에 대해:
  각 시행 t (t = 1..5)에 대해:
    1. 클러스터 안정 상태 확인     (stabilize/)
    2. 장애 F_i 시행 t 주입       (fault_inject/)
    3. 증상 발현 대기 (~2-5분)
    4. 신호 수집                   (src/collector/)
    5. System A RCA 실행           (src/llm/)
    6. System B RCA 실행           (src/rag/ + src/llm/)
    7. 결과 기록                   (results/)
    8. 복구 및 안정화              (stabilize/, 30분 대기)
```
