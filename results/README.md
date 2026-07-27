# results/ — 실험 증거 정본

이 디렉터리는 Ground Truth, 시행별 원시 출력, 집계 CSV와 버전별 비판 분석을 보관한다. 논문의 실험적 주장은 해당 `analysis` 문서와 원시 데이터로 추적할 수 있어야 한다.

## 불변 데이터

다음 파일은 `rules/data-safety.md`와 hook으로 보호한다.

- `ground_truth.csv`
- `experiment_results*.csv`
- `raw_v*/*.json`

기존 데이터를 수정해 오류를 바로잡지 않는다. 정정이나 재실험은 새 버전의 별도 파일로 추가한다.

## 최신 결과

| 버전 | 분석 | 핵심 판정 |
|---|---|---|
| V2.1 | [`analysis_v2_1.md`](analysis_v2_1.md) | B>A 미입증, 임계값·채점 robustness 문제 발견 |
| V2.2 | [`analysis_v2_2.md`](analysis_v2_2.md) | RAG 우위 관찰, retrieval leakage 가능성 확인; GitOps 신호 손상으로 효과 판정 보류 |

전체 실험 흐름은 [`../docs/experiment-versions.md`](../docs/experiment-versions.md), 현재 연구질문과 주장 경계는 [`../docs/research-charter.md`](../docs/research-charter.md)를 따른다.

## 파일 역할

| 패턴 | 역할 |
|---|---|
| `ground_truth.csv` | F1–F12 × trial 5의 기대 원인과 관측 신호 |
| `experiment_results_v*.csv` | 버전별 집계 결과 |
| `raw_v*/` | 시행별 원시 LLM 입력·출력과 평가 기록 |
| `analysis_v*.md` | 데이터 검증·통계·타당성 비판·다음 가설 |
| `experiment_changes_v*.md` | 버전 간 코드·프롬프트 변경 이력 |

V1의 84% 결과는 힌트 누출이 포함된 아카이브 사례이며 현재 성능 근거로 사용하지 않는다.
