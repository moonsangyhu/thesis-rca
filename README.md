# GitOps-aware LLM Kubernetes RCA

GitOps-managed Kubernetes에서 LLM 기반 근본 원인 분석(RCA)에 제공되는 Runtime·GitOps·RAG 컨텍스트의 기여를 분해하고, 성능 향상이 evidence leakage·측정 비결정성·실험 오염에서 비롯됐는지 감사하는 석사논문 실험 플랫폼이다.

## 현재 상태

- 최신 완료 실험: **V2.2**
- 다음 실험: **V2.3 — RAG 검색 누출 통제, GitOps 신호 정상화, 동일 캠페인 재수집**
- 모델: `gpt-4o-mini` 고정
- 평가 범위: Kubernetes fault F1–F12 × trial 5

현재 연구질문과 주장 범위는 [`docs/research-charter.md`](docs/research-charter.md)를 단일 정본으로 사용한다.

## 먼저 읽을 문서

| 목적 | 문서 |
|---|---|
| 연구질문·기여·주장 경계 | [`docs/research-charter.md`](docs/research-charter.md) |
| 실험 버전과 결과 색인 | [`docs/experiment-versions.md`](docs/experiment-versions.md) |
| 최신 완료 실험 분석 | [`results/analysis_v2_2.md`](results/analysis_v2_2.md) |
| 다음 실험 재개 | [`docs/plans/next_experiment_goal_v2_3.md`](docs/plans/next_experiment_goal_v2_3.md) |
| 실험 파이프라인 | [`rules/experiment-pipeline.md`](rules/experiment-pipeline.md) |
| 데이터 보호 규칙 | [`rules/data-safety.md`](rules/data-safety.md) |

## 저장소 구조

```text
docs/
  research-charter.md      연구 정본
  experiment-versions.md   실험 버전 색인
  plans/                   실험 계획·리뷰·다음 goal
  papers/                  논문별 선행연구 분석
  surveys/                 조사 범위·종합 서베이·심층 분석
experiments/               버전별 실행 모듈
results/                   불변 원시 결과와 버전별 분석
paper/chapters/            논문 원고
rules/                     연구·실험·데이터 안전 규칙
```

## 정본 원칙

- 실험 계획·코드·결과·분석·원고와 현재 진행 상태는 이 저장소에서만 관리한다.
- 외부 업무위키는 프로젝트 링크와 다른 업무에도 재사용되는 개념만 보유한다.
- 실험 수치의 근거는 `results/analysis_*.md`와 원시 결과로 추적한다.
- 완료된 원시 CSV·JSON과 ground truth는 수정하거나 삭제하지 않는다.
- 모든 변경은 feature branch와 PR을 거친다.
