# 실험 버전 히스토리

각 버전은 `experiments/v{N}/` 독립 모듈. 공유 인프라는 `experiments/shared/`.

## 명명 규칙

- **Try 1 (V1~V9)**: 최초 Proxmox nested 인프라 위 실험 시리즈. 연속 카운터.
- **Try 2 (V2.x)**: 인프라 재구축(Debian 직접 K8s) 후 새로 시작한 시리즈. `V{try}.{seq}` 표기.
  - **V2.1** = try 2의 첫 실험 (옛 V10에서 개명). 이후 V2.2, V2.3, ...
  - 파일·모듈 식별자는 점을 못 쓰므로 `v2_1`로 표기(예: `experiments/v2_1/`, `experiment_results_v2_1.csv`). 표시명은 항상 **V2.1**.

## 본류 버전

| 버전 | 핵심 변경 | 결과(A/B, ≥0.5) | 디렉토리 |
|------|----------|----------|----------|
| **v2** | 힌트 제거 + Chain-of-Thought (공정 baseline 시작점) | 26% / 42% | `experiments/v2/` |
| **v3** | v2 + Harness (Evaluator + Retry + Evidence Verification) | 30% / 40% | `experiments/v3/` |
| **v6** | SOP-Guided Prompt (단계별 진단 절차서) — 회귀, 실패 | 26% / 38% | `experiments/v6/` |
| **v7** | V6 + Step 3 역추적 + 증거 다중성 규칙 + **F11/F12 네트워크 Fault 도입** | 22% / 38% | `experiments/v7/` |
| **v8** | V7 + 확장 네트워크 메트릭 (gRPC latency, TCP retransmissions) — 가설 기각, 환경 오염 발견 | 25% / 35% | `experiments/v8/` |
| **V2.1** (옛 v10) | **Try 2 시작** — 클러스터 재구축 후 re-baseline + V9 Pre-Trial State Validator 탑재 | 34.5% / 43.1% (`≥0.5` 재분석) | `experiments/v2_1/` |
| **V2.2** | 5-arm 처치 분해 + 길이 placebo + 반복 생성·blinded 다수결 채점·임계 sweep | C1 31.7% / GitOps 36.7% / RAG 65.0% / Both 60.0% / Placebo 36.7% (`≥0.5`) | `experiments/v2_2/` |
| **V2.3** | 누출 통제 blind procedural RAG vs 길이 placebo; 반복 campaign lifecycle 결함으로 조기 종료 | **판정 불가** — 완결 campaign 0/49 artifact dirs, 최신 4회 14·37·39·30/59 incidents | `experiments/v2_3/` |
| **V2.4-D** | Primary03 12 incidents의 사전등록 결정론적 lexical concordance; exact freeze/approval 뒤 one-shot hidden scoring | **INVALID** — `UNSUPPORTED_NEGATION` fail-close, 결과·통계·public release 없음 | `experiments/v2_4_deterministic/` |

## 현재 체크포인트

- **최신 종료:** V2.4-D — 2026-09-01 사전등록 `UNSUPPORTED_NEGATION` fail-close로 INVALID 종료
- **핵심 판정:** freeze·approval·117 input gate는 통과했지만 valid 12 pairs가 형성되지 않아 RAG 대 length-placebo RD·discordance·p-value·CI를 계산할 수 없다. 이는 효과 없음의 증거가 아니다.
- **다음 checkpoint:** V2.4-D2 — real input 추가 probe 없이 public linguistic source와 synthetic fixture만으로 total negation instrument revision의 정당성 검토
- **재개 문서:** [`plans/next_experiment_goal_v2_4_d2.md`](plans/next_experiment_goal_v2_4_d2.md)
- **연구 정본:** [`research-charter.md`](research-charter.md)

## 아카이브된 버전 (저유용 — `archive/` 로 이동, 2026-06-20)

사유 상세: [`archive/DEPRECATED.md`](../archive/DEPRECATED.md)

| 버전 | 핵심 변경 | 아카이브 사유 |
|------|----------|----------|
| ~~v1~~ | 장애 힌트 제공 + 단순 프롬프트 | 힌트 누설(B 84%) → 공정 비교 불가, 구 스키마 |
| ~~v4~~ | System A retry 비활성화 (v3에서 -12.2pp 확인) | 곁가지 튜닝, 80행 부분 실행 |
| ~~v5~~ | Symptom Extraction → Diagnosis 2단계 분리 | **미실행** (CSV 빈 파일) |
| ~~v9~~ | Pre-Trial State Validator | **미실행** — validator 코드는 V2.1(옛 V10)에 흡수됨. 단 계획·리뷰 문서는 `docs/plans/`에 유지(live 코드 설계 근거) |

## 실행 방법

```bash
python -m experiments.v{N}.run                      # 전체 실행
python -m experiments.v{N}.run --fault F1 --trial 3  # 단일 실험
python -m experiments.v{N}.run --dry-run              # 테스트
python -m experiments.v{N}.run --resume               # 이어하기
```
