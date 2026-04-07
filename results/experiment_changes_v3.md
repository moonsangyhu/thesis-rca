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
