# 실험 버전 히스토리

각 버전은 `experiments/v{N}/` 독립 모듈. 공유 인프라는 `experiments/shared/`.

## 본류 버전

| 버전 | 핵심 변경 | 결과(A/B, ≥0.5) | 디렉토리 |
|------|----------|----------|----------|
| **v2** | 힌트 제거 + Chain-of-Thought (공정 baseline 시작점) | 26% / 42% | `experiments/v2/` |
| **v3** | v2 + Harness (Evaluator + Retry + Evidence Verification) | 30% / 40% | `experiments/v3/` |
| **v6** | SOP-Guided Prompt (단계별 진단 절차서) — 회귀, 실패 | 26% / 38% | `experiments/v6/` |
| **v7** | V6 + Step 3 역추적 + 증거 다중성 규칙 + **F11/F12 네트워크 Fault 도입** | 22% / 38% | `experiments/v7/` |
| **v8** | V7 + 확장 네트워크 메트릭 (gRPC latency, TCP retransmissions) — 가설 기각, 환경 오염 발견 | 25% / 35% | `experiments/v8/` |
| **v10** | 클러스터 재구축 후 **re-baseline** + V9 Pre-Trial State Validator 탑재 (현재) | 42% / 50% | `experiments/v10/` |

## 아카이브된 버전 (저유용 — `archive/` 로 이동, 2026-06-20)

사유 상세: [`archive/DEPRECATED.md`](../archive/DEPRECATED.md)

| 버전 | 핵심 변경 | 아카이브 사유 |
|------|----------|----------|
| ~~v1~~ | 장애 힌트 제공 + 단순 프롬프트 | 힌트 누설(B 84%) → 공정 비교 불가, 구 스키마 |
| ~~v4~~ | System A retry 비활성화 (v3에서 -12.2pp 확인) | 곁가지 튜닝, 80행 부분 실행 |
| ~~v5~~ | Symptom Extraction → Diagnosis 2단계 분리 | **미실행** (CSV 빈 파일) |
| ~~v9~~ | Pre-Trial State Validator | **미실행** — validator 코드는 V10에 흡수됨. 단 계획·리뷰 문서는 `docs/plans/`에 유지(live 코드 설계 근거) |

## 실행 방법

```bash
python -m experiments.v{N}.run                      # 전체 실행
python -m experiments.v{N}.run --fault F1 --trial 3  # 단일 실험
python -m experiments.v{N}.run --dry-run              # 테스트
python -m experiments.v{N}.run --resume               # 이어하기
```
