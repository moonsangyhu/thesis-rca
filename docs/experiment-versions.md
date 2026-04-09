# 실험 버전 히스토리

각 버전은 `experiments/v{N}/` 독립 모듈. 공유 인프라는 `experiments/shared/`.

| 버전 | 핵심 변경 | 디렉토리 |
|------|----------|----------|
| **v1** | 장애 힌트 제공 + 단순 프롬���트 | `experiments/v1/` |
| **v2** | 힌트 제거 + Chain-of-Thought | `experiments/v2/` |
| **v3** | v2 + Harness (Evaluator + Retry + Evidence Verification) | `experiments/v3/` |
| **v4** | System A retry 비활성화 (v3에서 -12.2pp 성능 저하 확인) | `experiments/v4/` |
| **v5** | Symptom Extraction → Diagnosis 2단계 분리 | `experiments/v5/` |
| **v6** | SOP-Guided Prompt (단계별 진단 절차서) | `experiments/v6/` |
| **v7** | V6 + Step 3 역추적 + 증거 다중성 규칙 | `experiments/v7/` |
| **v8** | V7 + F11/F12 네트워크 Fault + 확장 네트워크 메트릭 (gRPC latency, TCP retransmissions) | `experiments/v8/` |

## 실행 방법

```bash
python -m experiments.v{N}.run                      # 전체 실행
python -m experiments.v{N}.run --fault F1 --trial 3  # 단일 실험
python -m experiments.v{N}.run --dry-run              # 테스트
python -m experiments.v{N}.run --resume               # 이어하기
```
