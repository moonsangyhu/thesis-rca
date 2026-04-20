# 에이전트 & 오케스트레이션 규칙

## 에이전트 목록 (`.claude/agents/`)

| 에이전트 | 역할 | 모델 |
|---------|------|------|
| `@experiment-planner` | 실험 계획 수립 (파라미터 결정, 선행 결과 분석, 계획서 작성) | opus |
| `@hypothesis-reviewer` | 실험 설계 리뷰 (방법론 비평, 교란 변수 식별, 대안 가설 제안). 코드 리뷰 제외 | opus |
| `@code-reviewer` | 코드 리뷰·수정 (이전 실험 교훈 기반 코드 개선, 실험 가설에 따른 코드 수정) | sonnet |
| `@experiment` | 실험 운영 (fault injection, signal collection, RCA, 통계 분석) | sonnet |
| `@experiment-modifier` | 실험 중 시나리오 수정 (실행 중 발생한 문제의 긴급 코드 수정) | sonnet |
| `@results-writer` | 결과 분석·요약 (CSV/JSON → 분석 리포트) | sonnet |
| `@paper-writer` | 논문 작성 (results/ 데이터 기반 학술 글쓰기) | opus |

## 오케스트레이터(Claude Code)의 역할

- 각 단계의 에이전트를 순서대로 호출
- 이전 단계의 산출물(계획서, 리뷰, 코드 수정)을 다음 에이전트에게 전달
- 각 단계 완료 시 사용자에게 요약 보고
- **실험 전**: `/lab-tunnel`로 터널 연결 + preflight check
- **실험 후**: `/lab-restore`로 실험 환경 정상화 확인 후 결과 분석 진행

## 에이전트 간 토론

각 에이전트는 다른 에이전트의 산출물에 대해 의견을 제시하고, 이견이 있으면 근거를 들어 토론한다. 최종 결정은 오케스트레이터(사용자)가 내린다.

## 공통 규칙

- 수정 작업 후 반드시 `/changelog` 스킬로 변경 이력 기록
- feature 브랜치에서의 **중간 커밋**은 `/commit-push` 사용. **main으로의 push 금지**.
- 작업 최종 완료(=main에 반영) 시에는 반드시 `/pr-merge` 스킬로 **한글 PR → 사용자 승인 → rebase 머지** 경로를 따른다. main 브랜치 직접 커밋·머지·푸시는 `hooks/pr-only-guard.sh`가 차단한다.
