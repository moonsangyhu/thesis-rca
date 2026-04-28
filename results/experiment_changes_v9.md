# V9 실험 코드 변경 이력

## 구현 일자
2026-04-28

## 가설
환경 오염(이전 fault의 잔류 ReplicaSet/pod)이 V8 F11/F12 진단 실패의 dominant cause다. 매 trial 시작 직전 클러스터 state를 검증하고 잔류 fault를 자동 정정하면, LLM 컨텍스트의 dominant signal이 실제 fault로 이동하여 F11/F12 정확도가 ≥ 40%로 향상한다.

근거: V8 raw_v8 100% F11/F12 trial에서 V7 F2 fault 잔류 RS `shippingservice-865585fdff` 활성 (restart count 26→32→36→38 누적). LLM이 합리적으로 이 dominant signal을 root cause로 추론. SynergyRCA StateChecker (arxiv:2506.02490) 패턴 인용.

---

## 수정 사항

### 1. scripts/stabilize/state_validator.py — 신규 (~360 lines)

**SynergyRCA StateChecker 패턴**의 K8s ReplicaSet 도메인 단순화 적용.

핵심 클래스:
- `StaleFinding` dataclass: kind ∈ {stale_rs, abnormal_pod}, name, deployment, detail
- `ValidationResult` dataclass: status ∈ {clean, corrected, skipped}, findings, correction_attempts, elapsed_seconds
- `StateValidator`: 검증 + 정정 orchestrator

#### 핵심 메서드

- **`validate_and_correct(fault_id, trial, max_attempts=2)`**: 진입점. baseline restart counts 캡처 → `_scan` → 발견 시 단계적 정정 → `_wait_stable` (rollout-based) → 재검증.
- **`_scan(fault_id, trial)`**: RS-level + Pod-level 합집합 검사 (가정 §0-1).
  - RS-level: `replicas >= 1` AND `RS != deployment latest RS`
  - Pod-level: target_service whitelist 외 boutique pod가 abnormal
  - F11/F12 (target_type=node): NotReady 노드의 pod는 stale 검출에서 제외 (필수 수정 1, recovery.py 책임 분리)
- **`_is_abnormal(pod)`**: 절대 임계값 ≥ 10 (필수 수정 2) + baseline 대비 +5 carry-over 검사 + Failed/Unknown phase + CrashLoop/ImagePull waiting reason
- **`_correct(findings, attempt)`**: 1차 rollout restart, 2차 force delete RS + rollout restart. deployment set 반환
- **`_wait_stable(deployments, timeout=120)`**: `kubectl rollout status` 기반 (필수 수정 3, 단순 sleep 대체)

#### 헬퍼

- `_compute_latest_rs`: deployment.kubernetes.io/revision annotation 기반으로 latest RS 매핑
- `_owner_deployment`, `_pod_owner_deploy`: ownerReferences 추적
- `_capture_baseline_restarts`: trial 시작 시점 restart count 스냅샷
- `_notready_node_set`: F4/F11/F12에서 노드 가드 (validator 책임 범위 명시)
- `_kubectl_json`, `_kubectl_run`: subprocess wrapper

### 2. experiments/shared/runner.py — Step 0.5 hook + skipped 처리

**변경 전**: `run_trial()`이 inject → wait → collect → RCA → record → recover 순서.

**변경 후**:
- `__init__`에 `validator=None` 파라미터 추가 (V8 이하는 None으로 호환).
- `run_trial()` 진입부에 **Step 0.5 (Pre-Trial State Validation)** 추가:
  - dry_run + validator None이 아니면 `validator.validate_and_correct(fault_id, trial)` 호출
  - status=skipped 시 `_record_skipped()` 후 즉시 return (inject·LLM 호출 안 함)
  - validator 자체 예외 발생 시 try/except로 감싸 trial을 skipped로 처리
- Step 8 (Record results)에 validator metadata 추가 (4개 컬럼 row dict 병합)

#### 추가 메서드

- **`_validator_meta_dict(validator_result, status_default)`**: ValidationResult → CSV row dict (4개 컬럼)
- **`_record_skipped(fault_id, trial, validator_result, ground_truth, error)`**: A/B 각각 skip 레코드 1쌍 + raw에 `{fault}_t{trial}_SKIPPED_{ts}.json` 저장 (validator findings dump)

### 3. experiments/v9/ — V8 fork (5 files)

| 파일 | 변경 내용 |
|---|---|
| `__init__.py` | `RCAEngineV8` → `RCAEngineV9` export |
| `prompts.py` | V8과 완전 동일 (cp) |
| `engine.py` | 클래스명만 `RCAEngineV9`로 (sed 자동 변환), 로직 완전 동일 |
| `config.py` | RESULTS_CSV→`experiment_results_v9.csv`, RAW_DIR→`raw_v9/`, CSV_HEADERS에 V9 신규 컬럼 4종 추가 (`skipped`, `validator_status`, `validator_findings`, `validator_attempts`) |
| `run.py` | logger name `experiment.v9`, validator 인스턴스화 (`StateValidator(ground_truth=...)`) + `TrialRunner`에 주입. dry_run에서는 validator=None |

### 4. src/rag/retriever.py — chunk header 중복 제거 (환경 전제조건, 가정 §0-4)

**변경 전**: `format_context()`가 `[Source: ...]\n# {doc.title}\n` + content 출력. content가 이미 `# Title`로 시작하면 헤더 2번 출력 (raw_v8 F11_t1_B에서 확인).

**변경 후**: `content.lstrip().startswith("# ")`이면 prepended `# {doc.title}` 생략. 검증: V9 reindex 후 F11 retrieval에서 chunk header 중복 0건 확인.

### 5. RAG 재인덱싱

`python3 -m src.rag.ingest` 1회 실행. 1274 chunks in collection 'k8s-rca-knowledge'.

---

## V8 대비 통제 변수 (변경 없음)

| 항목 | 파일 | 비고 |
|---|---|---|
| LLM 모델 | gpt-4o-mini | 고정 |
| SOP 프롬프트 | `experiments/v9/prompts.py` | V8과 byte-identical |
| RCA 엔진 로직 | `experiments/v9/engine.py` | 클래스명만 변경 |
| Evaluator/Retry | `experiments/shared/llm_client.py` | 변경 없음 |
| Context builder | `src/processor/context_builder.py` | 변경 없음 |
| 메트릭 수집 4종 | `src/collector/prometheus.py` | V8 fix(d2f0c41) 포함, 추가 변경 없음 |
| Fault inject 로직 | `scripts/fault_inject/` | 변경 없음 |
| Recovery 로직 | `scripts/stabilize/recovery.py` | **변경 없음** (validator는 별도 모듈로 추가) |
| Ground truth | `results/ground_truth.csv` | 변경 없음 |

---

## 검증

### 컴파일 + 임포트 검증
- `py_compile`: state_validator.py, runner.py, v9/{__init__,config,engine,run}.py, retriever.py — 통과
- StateValidator 인스턴스화 + ValidationResult/StaleFinding dataclass — 통과
- TrialRunner.__init__ params에 validator 추가 확인 — 통과
- experiments/v9/config.py CSV_HEADERS에 V9 신규 4종 컬럼 확인 — 통과

### 실 클러스터 검증 (lab-restore 직후 clean state)
- F11 t1 validator: status=clean, findings=0, elapsed=0.5s
- F2 t1 validator (whitelist=shippingservice): status=clean, findings=0, elapsed=0.4s
- → false positive 없음, target_service whitelist 정상 작동

### RAG chunk header 중복 검증
- F11 retrieval format_context 출력 grep: `# Runbook: F11 - .* Root Cause Analysis\n# Runbook: F11` 매치 0건 (V8에서는 1+건 발견)

### V9 dry-run (F11 t1)
- experiment_results_v9.csv 헤더 생성 확인
- raw_v9/ 디렉토리 생성 확인
- logger name `experiment.v9` 확인
- 실험 종료 정상 (Slack notify 등록 v9)

---

## 미반영 사항 (review_v9 권장 7건)

권장 수정은 분석 단계(`results/analysis_v9.md`) 또는 sensitivity analysis로 사후 처리:
- 권장 #6 RAG 변경 위치 우선순위 — retriever.py format_context로 결정 (ingest 단 변경 회피)
- 권장 #7 Validator effectiveness operational 정의 — analysis 단계에서 명시
- 권장 #8 System A 분해 보고 — analysis 단계
- 권장 #9 F2 carry-over 리스크 — plan §11 리스크 7으로는 추가 미반영, analysis 단계에서 처리
- 권장 #10 경계 시나리오 — plan §10-3에 promoted (필수 수정 5에 포함)
- 권장 #11 paired 검정 skipped 처리 — analysis 단계
- 권장 #12 F1-F10 baseline 명확화 — analysis 단계 (V7=23 vs V8=21 모두 보고)

---

## 다음 단계

1. `/lab-tunnel` (현재 활성 상태 확인) + 사전 점검 (gRPC 메트릭 부재 → 시나리오 Beta carry-over)
2. dry-run 5건 (F1, F2, F7, F11, F12 + V9 추가: validator effectiveness 측정 가능 여부 검증)
3. 본 실험 (`nohup python -m experiments.v9.run > results/experiment_v9_nohup.log 2>&1 &`)
4. 결과 분석 (`results/analysis_v9.md`)

작성: 2026-04-28 (KST)
