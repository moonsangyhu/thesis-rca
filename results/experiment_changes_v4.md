# V4 실험 변경 이력

## 변경 목록

### 1. V4 실험 계획서 작성 + 모델 고정 원칙 적용 — 2026-04-07

- **수정 에이전트**: @experiment-planner + 오케스트레이터
- **증상/문제**: V3 하네스가 정확도 개선 실패(Wilcoxon p=1.000). 초기 V4 계획이 모델 변경(gpt-4o-mini→claude-sonnet)을 제안했으나, 모델은 고정 변수여야 함
- **원인**: 논문 기여는 프레임워크(GitOps, 하네스, 컨텍스트)이지 모델 선택이 아님. 모델 변경 시 프레임워크 효과 분리 불가
- **수정 내용**:
  1. `CLAUDE.md`에 모델 고정 원칙 명시 ("실험 간 LLM 모델(gpt-4o-mini) 고정")
  2. `.claude/agents/experiment-planner.md`에서 "모델 변경" 개선 옵션 제거, 모델 고정 경고 추가
  3. V4 계획서를 컨텍스트 최적화 방향으로 재설계: Context Reranking + Fault Layer Prompt + Harness Simplification
  4. `docs/plans/experiment_plan_v4.md` 계획서 작성 (576줄)
- **수정 파일**:
  - `CLAUDE.md:10` — 모델 고정 원칙 추가
  - `.claude/agents/experiment-planner.md:83-86` — 모델 변경 옵션 제거, 모델 고정 경고 추가
  - `docs/plans/experiment_plan_v4.md` — 신규 생성 (V4 실험 계획서)
- **상태**: 수정됨

### 2. V4 실험 설계 리뷰 — 2026-04-07

- **수정 에이전트**: @hypothesis-reviewer
- **증상/문제**: V4 계획서의 방법론적 타당성 검증 필요
- **원인**: 3개 변경 동시 도입(컨텍스트 리랭킹 + Fault Layer 프롬프트 + 하네스 간소화)으로 변수 분리 불가 우려
- **수정 내용**:
  1. 방법론 비평: "context reranking"이 아닌 "context redesign"으로 명명 권고
  2. 교란 변수 식별: Fault Layer 프롬프트의 힌트 효과, 컨텍스트 길이 교란, System A/B 비대칭
  3. 통계 검정 권고: McNemar(n=50)을 주 검정으로 승격, Wilcoxon(n=10) 검정력 부족 지적
  4. 대안 가설 5개 제시 (노이즈 제거, 힌트 효과, LLM 비결정성, EV 제거 효과, 길이 감소)
  5. 리스크 보완: F7 Anomaly Summary 누락 위험, Evaluator-Layer 미연동
  6. 결론: **실험 진행 권고**, Fault Layer 증상 키워드 추상화 필요
- **수정 파일**:
  - `docs/plans/review_v4.md` — 신규 생성 (V4 실험 설계 리뷰)
- **상태**: 수정됨
