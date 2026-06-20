# Paper Idea → Thesis Experiment 파이프라인

목적: 하루 1개 논문 소개/오디오를 들은 뒤 사용자가 “이 아이디어 괜찮다, 다음 실험에 적용해보자”라고 말하면, 아이디어가 휘발되지 않고 `thesis-rca`의 다음 실험 후보로 정리·검증·승격되도록 한다.

이 파이프라인은 **아이디어 수집**이 아니라 **실험 후보 생성**이다. 논문에서 좋아 보이는 기법을 바로 실험에 넣지 않는다. 반드시 현재 석사논문 질문, 독립변수, baseline, 평가 가능성에 맞는지 게이트를 통과해야 한다.

---

## 0. 트리거

사용자가 Slack에서 다음과 같이 말하면 이 파이프라인에 진입한다.

- “이 논문 아이디어 thesis-rca에 적용해보자”
- “오늘 논문 괜찮은 것 같아. 다음 실험 후보로 준비해줘”
- “이거 버리지 말고 실험 아이디어로 남겨줘”
- 논문 링크/제목/오디오 요약과 함께 “적용 가능성 봐줘”

입력이 불완전해도 먼저 아이디어 카드를 만들고, 불확실한 항목은 `TBD`로 남긴다. 단, 실험 승격은 불확실성이 해소되기 전까지 금지한다.

---

## 1. 산출물 경로

| 단계 | 산출물 | 경로 |
|---|---|---|
| Intake | 논문 아이디어 카드 | `docs/research_inbox/paper_ideas/YYYY-MM-DD-{slug}.md` |
| Literature backing | 논문별 정식 읽기 노트 | `docs/papers/{slug}.md` |
| Survey integration | 여러 논문 종합 | `docs/surveys/paper_survey_v{N}.md` |
| Experiment promotion | 실험 계획 후보 | `docs/plans/experiment_plan_v{N}.md` 또는 그 초안 |

`docs/research_inbox/paper_ideas/`는 **실험 후보 대기열**이다. 여기에 있다는 사실만으로 채택된 것이 아니다.

---

## 2. 5단계 게이트

### Gate A — Thesis fit

다음 중 최소 1개에 직접 연결되어야 한다.

1. K8s RCA에서 System B의 정보 증강 방식 개선
2. LLM RCA의 컨텍스트 구성/검색/RAG/증거 검증 개선
3. fault isolation, causal consistency, state validation, observability signal selection
4. 현재 약점: F11/F12 network fault, F4 NodeNotReady, evaluator 일관성, trial contamination

연결이 약하면 `status: rejected-for-now`로 보류한다.

### Gate B — 단일 독립변수화 가능성

아이디어는 다음 문장으로 바뀌어야 한다.

> “V{N}에서는 **X 하나만** 바꾸고, V{N-1} 대비 **Y 지표**가 개선되는지 본다.”

X가 여러 개면 분해한다. 예: “graph + new prompt + new metrics”는 세 실험이다.

### Gate C — Baseline and counterfactual

반드시 비교 대상이 있어야 한다.

- Primary baseline: 직전 실험 버전의 System B
- Secondary baseline: System A, 또는 기존 RAG 없는/검증 없는 변형
- Counterfactual: 논문 기법을 적용하지 않았을 때 같은 데이터에서 왜 실패하는가

### Gate D — 측정 가능성

최소 1개 primary metric과 1개 guardrail metric을 정의한다.

- Primary: fault별 correctness_score, binary accuracy(score≥0.5), F11/F12 combined accuracy 등
- Guardrail: F1-F10 non-regression, skipped trial count, context token length, latency, retrieval precision 등

### Gate E — 구현/재현성 위험

다음 항목을 명시한다.

- 필요한 코드 변경 경로
- 외부 의존성/클러스터 변경 여부
- raw 결과 보존 방식
- 실패 시 rollback 방법
- 통계 검정 또는 최소 효과 크기

---

## 3. 카드 작성 규칙

`scripts/research_intake.py`로 카드를 만든다.

```bash
python3 scripts/research_intake.py \
  --title "Paper title" \
  --url "https://..." \
  --source "NotebookLM daily paper audio" \
  --idea "적용하고 싶은 핵심 아이디어" \
  --why "thesis-rca에 중요하다고 판단한 이유" \
  --status candidate
```

카드에는 반드시 다음을 포함한다.

1. 논문/소스 메타데이터
2. 사용자가 좋다고 본 아이디어
3. thesis-rca 매핑
4. 실험 가설 초안
5. 독립변수/종속변수/통제변수
6. 필요한 코드 변경 후보
7. 리스크와 반증 조건
8. 승격 전 필요한 증거

---

## 4. 승격 기준

아이디어 카드는 아래 조건을 만족할 때만 다음 실험 후보로 승격한다.

- [ ] 원 논문 URL/DOI/arXiv 또는 공식 repo가 확인됨
- [ ] `docs/papers/{slug}.md` 수준의 정식 읽기 노트가 있음
- [ ] 현재 실험 약점과 직접 연결됨
- [ ] 단일 독립변수로 분리됨
- [ ] baseline/metric/guardrail이 명확함
- [ ] 구현 범위가 파일 단위로 적힘
- [ ] 실패해도 논문에 쓸 수 있는 반증 결과가 있음

승격 후에는 `rules/experiment-pipeline.md` Step 0.5/Step 1로 연결한다.

---

## 5. Advisor 판단 원칙

약한 아이디어는 명확히 약하다고 표시한다.

- “좋아 보인다”는 채택 근거가 아니다.
- 논문 성능 수치가 좋아도 현재 실험의 bottleneck과 다르면 보류한다.
- implementation-heavy 아이디어는 석사논문 기여가 흐려질 수 있으므로, 실험 변수와 평가 지표를 먼저 고정한다.
- 다음 실험은 항상 **하나의 주장**만 검증해야 한다.

---

## 6. Slack 응답 템플릿

사용자에게는 다음 구조로 보고한다.

```text
요약: 아이디어 카드를 만들었고, 현재 판단은 {candidate/needs-reading/rejected-for-now/ready-for-experiment}입니다.

판단: ...
근거: ...
리스크: ...
다음 액션: ...

파일: docs/research_inbox/paper_ideas/YYYY-MM-DD-{slug}.md
```

가장 중요한 다음 액션은 보통 “원 논문을 정식 읽기 노트로 승격할지 결정” 또는 “단일 독립변수로 쪼개기”다.
