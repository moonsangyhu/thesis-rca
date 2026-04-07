# V3 실험 변경 이력

## 실험 개요

- **버전**: v3 (CoT + Harness: Evidence Verification + Evaluator + Retry)
- **모델**: gpt-4o-mini (OpenAI)
- **수행 일시**: 2026-04-07~

---

## 변경 이력

### 1. retry_count 무한루프 버그 수정 — 2026-04-07

- **수정 에이전트**: @오케스트레이터 (hypothesis-reviewer 피드백 반영)
- **증상/문제**: `_generate_with_feedback()`이 새 RCAOutput(retry_count=0)을 매번 생성하여, `output.retry_count += 1` 후에도 항상 1이 됨. `1 < MAX_RETRIES(2)` 조건이 영원히 참이므로 should_retry=true 시 무한루프 발생
- **원인**: retry_count를 output 객체에 의존하여 관리했으나, 매 retry마다 output이 새로 생성되어 카운터가 리셋됨
- **수정 내용**: retry_count를 analyze() 메서드 레벨의 별도 변수로 관리. `output.retry_count = retry_count`로 최종값만 기록
- **수정 파일**: `experiments/v3/engine.py:38-55`
- **상태**: 수정됨

### 2. V3 run.py에 V2 안정성 개선사항 4건 반영 — 2026-04-07

- **수정 에이전트**: @오케스트레이터
- **증상/문제**: V2 실행 중 발견된 인프라 문제(Failed pod 누적, health check 부족)에 대한 수정이 V3 run.py에 미반영
- **원인**: V3 코드가 V2 수정 이전에 작성되어 개선사항이 포팅되지 않음
- **수정 내용**:
  1. `from dotenv import load_dotenv; load_dotenv()` 추가 — API 키 로딩
  2. Trial 간 post-trial health check loop 추가 (3회 × 30초 대기)
  3. Fault 전환 시 `kubectl delete pods --field-selector=status.phase=Failed` 실행
  4. Fault 전환 후 health verification (3회 × 60초 대기)
- **수정 파일**: `experiments/v3/run.py:13-14` (dotenv), `experiments/v3/run.py:134-165` (health check + fault transition)
- **상태**: 수정됨

### 3. @code-reviewer 에이전트 신설 + 파이프라인 5단계 확장 — 2026-04-07

- **수정 에이전트**: @오케스트레이터 (사용자 피드백 반영)
- **증상/문제**: hypothesis-reviewer가 실험 리뷰와 코드 리뷰를 동시에 수행하여 역할 불명확. 실험 종료 후 환경 정리 미수행으로 잔여 pod/RS 누적.
- **원인**: 코드 리뷰 전담 에이전트 부재. 실험 파이프라인에 환경 정리 단계 미포함.
- **수정 내용**:
  1. `@code-reviewer` 에이전트 신설 — 이전 실험 교훈 기반 코드 개선 + 실험 가설 기반 코드 수정 전담
  2. `@hypothesis-reviewer`에서 코드 리뷰 제외 명시
  3. 파이프라인 4단계→5단계 확장 (planner→reviewer→code-reviewer→experiment→results-writer)
  4. `@experiment` 에이전트에 실험 완료 후 `/lab-restore` 필수 규칙 추가
- **수정 파일**: `.claude/agents/code-reviewer.md` (신규), `.claude/agents/hypothesis-reviewer.md`, `.claude/agents/experiment.md`, `CLAUDE.md`
- **상태**: 수정됨
