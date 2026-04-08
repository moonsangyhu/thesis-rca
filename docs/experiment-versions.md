# 실험 버전 히스토리

각 버전은 `experiments/v{N}/` 독립 모듈. 공유 인프라는 `experiments/shared/`.

| 버전 | 핵심 변경 | 디렉토리 |
|------|----------|----------|
| **v1** | 장애 힌트 제공 + 단순 프롬���트 | `experiments/v1/` |
| **v2** | 힌트 제거 + Chain-of-Thought | `experiments/v2/` |
| **v3** | v2 + Harness (Evaluator + Retry + Evidence Verification) | `experiments/v3/` |
| **v4** | System A retry 비활성화 (v3에서 -12.2pp 성능 저하 확인) | `experiments/v4/` |
| **v5** | Symptom Extraction → Diagnosis 2단�� 분리 | `experiments/v5/` |

## 실행 방법

```bash
python -m experiments.v{N}.run                      # 전체 실행
python -m experiments.v{N}.run --fault F1 --trial 3  # 단일 실험
python -m experiments.v{N}.run --dry-run              # 테스트
python -m experiments.v{N}.run --resume               # 이어하기
```
