---
title: "{{title}}"
status: "{{status}}"
created: "{{created}}"
source: "{{source}}"
url: "{{url}}"
next_experiment_candidate: "TBD"
---

# {{title}}

## 1. 한 줄 판단

TBD — 이 아이디어가 `thesis-rca`의 다음 실험에 들어갈 만큼 강한지 아직 판정하지 않았다.

## 2. 사용자 입력에서 보존할 아이디어

{{idea}}

## 3. 왜 중요해 보였는가

{{why}}

## 4. thesis-rca 매핑

- 연결되는 현재 약점: TBD
- 관련 fault type: TBD
- 관련 시스템: System A / System B / evaluator / harness / cluster state / RAG 중 TBD
- 관련 기존 산출물:
  - `results/analysis_v8.md` 또는 최신 분석: TBD
  - `docs/plans/experiment_plan_v9.md` 또는 최신 계획: TBD

## 5. 실험 가설 초안

> V{N}에서 **TBD 독립변수 하나**를 추가/변경하면, V{N-1} 대비 **TBD 지표**가 개선된다. 단, **TBD guardrail**은 악화되지 않아야 한다.

## 6. 변수 정의

| 구분 | 내용 |
|---|---|
| 독립변수 | TBD |
| 종속변수 / primary metric | TBD |
| Guardrail metric | TBD |
| 통제변수 | 모델 `gpt-4o-mini`, fault set, trial count, ground truth, 실험 harness |
| Baseline | 직전 실험 버전 System B + 필요 시 System A |

## 7. 구현 후보

예상 변경 경로:

- `experiments/v{N}/`: TBD
- `experiments/shared/`: TBD
- `src/collector/`: TBD
- `src/processor/`: TBD
- `src/rag/`: TBD
- `scripts/stabilize/`: TBD

## 8. 반증 조건

이 아이디어는 다음 중 하나가 나오면 기각한다.

- Primary metric 개선이 없음
- Guardrail metric 악화가 thesis 주장보다 큼
- 구현 변경이 여러 독립변수를 동시에 바꿔 인과 해석 불가
- 논문 기법이 현재 K8s RCA bottleneck과 직접 연결되지 않음

## 9. 승격 전 체크리스트

- [ ] 원 논문 URL/DOI/arXiv 확인
- [ ] 공식 repo 또는 artifact 확인, 가능하면 재현 조건 기록
- [ ] `docs/papers/{slug}.md` 정식 읽기 노트 작성
- [ ] 기존 실험 실패 패턴과 연결
- [ ] 단일 독립변수로 축소
- [ ] baseline/metric/guardrail 확정
- [ ] 구현 범위와 rollback 경로 명시

## 10. Advisor note

TBD — 논문을 정식으로 읽기 전까지는 novelty나 효과를 주장하지 않는다.
