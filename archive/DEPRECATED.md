# 아카이브 — 저유용 실험 버전 (2026-06-20)

본 디렉토리는 **유용성이 낮다고 판단된 실험 버전**을 본류에서 분리해 보존한 것이다.
**삭제가 아니라 이동**이며, 모든 파일은 git 히스토리·이 경로에 그대로 남아있다.
원래 경로 구조(`experiments/`, `results/`, `docs/plans/`)를 미러링한다.

> ⚠️ 여기 있는 코드/데이터는 **현재 파이프라인에서 import·참조되지 않음**을 확인하고 이동했다.
> 논문 서사상 다시 필요하면 원위치로 되돌릴 수 있다.

## 아카이브 사유

| 버전 | 사유 | 비고 |
|---|---|---|
| **V1** | 장애 **힌트 제공**으로 정답 누설 → System B 84% 비정상치, 공정 비교 불가. 구 CSV 스키마(eval 컬럼 없음). | "초기 프로토타입". 데이터 파일 `results/experiment_results.csv`는 범용 스크립트(`run_experiment.py`/`analyze.py`)의 기본 출력 경로로 **여전히 참조되어 제자리 유지**. |
| **V4** | System A retry 비활성화만 검증한 **곁가지 튜닝**. 80행 부분 실행(9 fault). 결론("V3 retry가 A를 -12pp 해침")은 한 줄로 요약 가능. | analysis/changes/plan/review 동반 이동. |
| **V5** | Symptom Extraction→Diagnosis 2단계 분리. **한 번도 실행 안 됨**(CSV 빈 파일). | 계획·코드만 존재. |
| **V9** | Pre-Trial State Validator. **한 번도 실행 안 됨**(CSV 빈 파일). validator **코드는 `scripts/stabilize/state_validator.py`로 이미 V10에 흡수**되어 `experiments/v9/` 모듈은 중복. | ⚠️ 단, **`docs/plans/experiment_plan_v9.md`·`docs/plans/review_v9.md`는 제자리 유지** — 살아있는 `state_validator.py`(V10 사용)의 설계 문서이기 때문. |

## 본류에 남은 버전 (참고)

V2(공정 baseline), V3(하네스 무효 입증), V6(SOP 실패), V7(네트워크 fault 도입),
V8(환경 오염 발견·가설 기각), V10(환경 재구축 후 re-baseline, 현재).
각각 다음 단계를 정당화하는 서사라 실패한 것도 보존.

## 정량 결과 스냅샷 (아카이브 대상)

| 버전 | A 정확도 | B 정확도 | 데이터 |
|---|---|---|---|
| V1 | 30% (15/50) | 84% (42/50) | 100행(힌트 누설) |
| V4 | 20% (8/40) | 32% (13/40) | 80행(부분) |
| V5 | — | — | 미실행 |
| V9 | — | — | 미실행 |
