# 실험 계획서: V9 — Pre-Trial State Validator (잔류 fault 자동 정정)

> 작성일: 2026-04-28
> 1차 리비전: 2026-04-28 — `review_v9.md` 필수 수정 5건 반영 (validator 책임 분리·restartCount 임계값·rollout-based wait·resume skipped 정책·F11+F12 skipped 임계값)
> 이전 실험: V8 (Network Signal Enrichment, 시나리오 Beta)
> 분석 근거: `docs/surveys/deep_analysis_v9.md` + `results/analysis_v8.md`
> 호출 흐름: `superpowers:brainstorming` (@experiment-planner wrapper, Auto Mode 자가-답변)
> 리뷰: `docs/plans/review_v9.md`
> 산출물 경로 override: `docs/plans/experiment_plan_v9.md` (CLAUDE.md Output Path Mapping)

---

## 0. 작성 근거 및 가정 명세 (Auto Mode 자가-답변)

본 plan은 사용자에게 직접 질문할 수 없는 환경(Auto Mode + 백그라운드 호출)에서 작성되었다. brainstorming 5축 질문에 대해 합리적 가정으로 자가-답변했으며, 모든 가정을 다음과 같이 명시한다. 사용자(호출자)가 review 단계에서 가정을 변경할 수 있다.

### 0-1. 가정 1 — Stale 판정 알고리즘 = RS-level + Pod-level 결합

`replicas.status.replicas >= 1` AND `RS가 deployment의 current generation이 가리키는 latest RS가 아님` (RS-level) AND/OR `target_service가 아닌 boutique pod가 CrashLoopBackOff/Error/Evicted` (Pod-level). 두 검사 결과의 **합집합**이 stale set.

근거: V8 raw_v8 검증에서 잔류 RS `shippingservice-865585fdff`는 RS-level에서, Evicted pod 잔류는 Pod-level에서 잡힘. 단일 검사로는 누락 위험.

### 0-2. 가정 2 — 단일 변수 식별 = ground_truth `target_service` 기반 화이트리스트 + fault 카테고리 매핑

`ground_truth.csv`의 `target_service` 컬럼이 application service명인 fault(F1-F3, F5-F10)에서는 해당 deployment의 비정상 pod를 fault inject의 의도된 결과로 간주하여 stale에서 제외. worker 노드명인 fault(F4, F11, F12)에서는 모든 boutique deployment의 비정상 pod = stale.

**필수 수정 1 — F11/F12 "node" 카테고리에서 validator 책임 범위 분리** (review_v9 §2.2):
- validator는 **deployment 레벨 잔류 RS/pod**만 정정한다 (rollout-based). 노드 레벨 잔류(tc netem 룰 잔존, 노드 NotReady 상태)는 **`scripts/stabilize/recovery.py` 책임**.
- 직전 trial이 F11/F12 고위험 trial(trial=5, delay≥5000ms or loss≥80%)인 경우:
  1. fault 간 cooldown을 900s → **1500s**로 일시 상향 (recovery.py가 노드 안정화할 시간 확보)
  2. 사전 점검에 `tc qdisc show dev <interface>`를 추가하여 노드 잔류 검증 (results/preflight_v9.txt에 기록)
  3. validator는 노드 상태가 NotReady인 deployment의 pod를 stale로 검출하지 않음 (false positive 차단)
- 이 분리 원칙은 §3-1 코드 스케치의 `_scan()` 진입부에서 노드 NotReady 검사로 구현.

### 0-3. 가정 3 — 정정 강도 = 단계적 (soft → hard → skipped)

1차: `kubectl rollout restart deploy/<name>` + `kubectl rollout status` 대기 (timeout 120s) → 재검증.
2차 (실패 시): `kubectl delete rs <stale-rs> --grace-period=0 --force` + `rollout restart` + rollout status 대기.
3차 (실패 시): trial을 **skipped**로 표시 (CSV `skipped=true`), 통계에서 제외.

**필수 수정 4 — `--resume` skipped trial 처리 정책** (review_v9 §3.2):
- `--resume` 모드에서 skipped trial은 **CSV에 이미 기록되어 있으므로 기본적으로 재시도하지 않음** (V8와 동일 동작).
- 명시적으로 재시도하려면 `--retry-skipped` 플래그 사용. **최대 1회 재시도**, 재시도해도 skipped 발생 시 **영구 skipped 고정** (다시 시도 불가).
- 영구 고정은 CSV `validator_status` 컬럼에 `skipped_permanent`로 기록. 통계 분석에서 분모로 제외.
- 무한 루프 방지: `experiments/v9/run.py`에서 `--retry-skipped` 처리 시 `validator_status == "skipped_permanent"`는 무시.

### 0-4. 가정 4 — 환경 전제조건 재정의 = RAG chunk header 중복 제거 (METRIC ANOMALIES 중복은 raw_v8 실측으로 기각)

`deep_analysis_v9.md` §1-4가 지적한 "METRIC ANOMALIES 중복"은 **raw_v8 120개 파일 grep 결과 0건**으로 실재하지 않음이 확인되었다. 다만 raw_v8 샘플(F11_t1_B)에서 RAG 청크 본문에 source title이 한 번 더 prepend되는 패턴이 실재함:

```
[Source: runbooks/rca-f11-networkdelay.md | Score: 0.85]
# Runbook: F11 - NetworkDelay Root Cause Analysis
# Runbook: F11 - NetworkDelay Root Cause Analysis    ← 중복 (RAG ingest/format 단)
```

따라서 V9 환경 전제조건 = **RAG chunk header 중복 제거 (가설 c 정정판)**. 변경 범위가 작고 단순하며 (5-10줄), 단일 독립변수와 분리 가능 (RAG 청킹/format은 stale RS 검출과 무관). 변경 후 raw_v9 1건 grep으로 검증.

### 0-5. 가정 5 — 통계 검정 = V8 §10-0/§12-4 승계 + V9 고유 추가

V8 plan의 Correctness Judge 판정 규칙(§10-0 a/b/c)과 비열등성 검정(δ=-5pp)을 그대로 승계. V9 고유로 다음 추가:
- skipped trial 통계 처리 (제외 + 별도 reporting)
- validator 메트릭 raw 메타데이터 기록
- F1-F10 비열등성 검정 분모 = 50 − skipped_count

---

## 1. 실험 목적

### 1-1. 이전 실험(V8)에서 발견한 문제점

V8은 "Network Signal Enrichment" (시나리오 Beta)로 60 trial을 완료했으나 **가설 기각**. 핵심 결과:

- F11 B = 2% (1건 부분 점수, 0/5 binary), F12 B = 0% (0/5)
- F1-F10 평균 점수 -12pp 회귀로 보였으나 **binary 기준 McNemar χ² = 0.40 (p ≈ 0.53)** — V7과 통계적 동등 (`results/analysis_v8.md`)
- 따라서 V8의 코드 변경(메트릭 4종 + RAG/런북)은 **binary 정확도에는 거의 영향 없음**. V8 plan §10의 회귀 판정은 score 분포 shift 때문이지 가설의 효과가 아님

**결정적 발견** (raw_v8 샘플링): F11/F12 모든 trial 컨텍스트에서 **V7 F2 fault 잔류 RS `shippingservice-865585fdff`가 활성**. restart count 26→32→36→38 누적. `recovery.py`가 manifest를 재적용하여 새 RS `759b59d959`를 생성했으나, 기존 RS `865585fdff`가 desired=1 상태로 남아 두 RS 공존. LLM은 이 dominant signal(active CrashLoop pod)을 따라 일관되게 "CrashLoopBackOff"로 오진.

**LLM 진단 자체는 합리적** — 컨텍스트에 active CrashLoop pod가 있으면 그것이 root cause라고 추론하는 것이 정상. 문제는 ground truth(NetworkDelay/Loss)와 일치하지 않을 뿐. 즉 **V8 실패의 fundamental cause는 "환경 오염"이지 "신호 부재"가 아님**.

### 1-2. 이번 실험에서 검증할 개선 사항

**독립변수**: Pre-Trial State Validator + 잔류 fault 자동 정정
- 매 trial 시작 직전(`runner.run_trial`의 Step 1 inject 직전) 클러스터 상태 검증
- Stale RS 또는 비정상 pod 발견 시 단계적 정정 (rollout → force delete RS → skipped)
- 정정 성공 trial만 통계 포함, skipped는 별도 reporting

**환경 전제조건** (독립변수 아님):
- RAG chunk header 중복 제거 (raw_v8 실측 기반 정정 — §0-4 참조)

#### 1-2-1. 단일 변수 정당화

**근거 1: V8 데이터로 환경 오염이 dominant cause임이 입증됨**
- F11/F12 raw 100%에서 잔류 RS 검출. 다른 모든 V8 코드 변경(메트릭 4종 + RAG)이 작동했음에도 LLM은 잔류 신호를 우선 선택 → V8 변경의 효과 측정 자체가 불가능했음을 증명
- V9는 이 confounding factor를 제거하여 **이후 모든 실험(V10~)의 측정 정확도를 회복**한다는 전제조건적 의미를 가짐

**근거 2: Validator는 "측정 인프라" 변경이지 "RCA 로직" 변경이 아님**
- 프롬프트(SOP), engine(retry/evidence), context_builder, RAG retriever, LLM 모델 모두 V8과 **완전 동일**
- runner에 Step 0.5만 추가. 이는 trial 격리(experiment isolation)를 강화하는 메소드 변경으로, RCA 로직과 직교

**근거 3: 환경 전제조건(RAG chunk header)과의 분리 가능성**
- RAG chunk header 중복 제거는 ingest/format 단의 5-10줄 변경. State Validator는 runner 단의 별도 모듈
- 두 변경은 코드상 완전히 분리되며, 효과도 부분 분리 가능: header 중복 제거의 효과 ≈ 컨텍스트 토큰 감소 (~5-15 tokens/trial), validator 효과 ≈ F11/F12 진단 가능 trial 비율
- 다만 두 변경의 **상호작용 효과**(header 중복 제거가 RAG 검색 품질에 미세 영향)는 본 실험에서 측정 불가. 이 한계는 분석 리포트에 명시

**근거 4: 문헌 인용 — SynergyRCA StateChecker (arxiv:2506.02490)**
- "verification module that ensures candidate root causes identified through graph traversal are factually valid and causally consistent with the incident before involving the LLM for explanation"
- 본 V9 validator는 SynergyRCA의 StateChecker 패턴을 K8s ReplicaSet 도메인에 단순화 적용한 것. 보고된 precision ≈ 0.90을 본 실험의 stale 검출 정확도 목표로 채택

### 1-3. System B 성능 향상 목표

| 지표 | V8 B | V9 B 목표 | 의미 |
|---|---|---|---|
| F11 + F12 합산 (≥0.5) | 0/10 (0%) | ≥ 4/10 (40%) | **주 기준** — 환경 오염 제거 효과 |
| F1-F10 (≥0.5) | 21/50 (42%) | ≥ 21/50 (42%) | V8 동등 이상 (회귀 허용 -5pp) |
| 전체 (≥0.5) | 21/60 (35%) | ≥ 25/60 (42%) | 부 기준 |

---

## 2. 이전 결과 분석 요약

### 2-1. 전체 정답률 (V8, ≥0.5 cutoff)

| 시스템 | F1-F10 | F11-F12 | 전체 (F1-F12) | V7 대비 |
|---|---|---|---|---|
| System A | n/a (분석 미수행) | 0/10 (0%) | n/a | - |
| System B | 21/50 (42%) | 0/10 (0%) | 21/60 (35%) | **McNemar p≈0.53 (동등)** |
| 평균 점수 | 33.8% | 1% | 28.3% | -10pp (score 분포 shift) |

`results/analysis_v8.md` 표 1-1 + 본 실험자의 추가 paired 검정 (deep_analysis_v9 §1-1).

### 2-2. Fault Type별 V8 B vs V7 B (binary ≥0.5)

| Fault | V7 B | V8 B (≥0.5) | Δ | 진단 패턴 |
|---|---|---|---|---|
| F1 OOMKilled | 1/5 (20%) | 1/5 (20%) | 0 | OOM Kill (1) |
| F2 CrashLoopBackOff | **5/5 (100%)** | **0/5 (0%)** | **-100pp** | CrashLoop(3건 score=0.5만) — **partial** |
| F3 ImagePullBackOff | 3/5 (60%) | 4/5 (80%) | +20pp | Image Pull |
| F4 NodeNotReady | 0/5 (0%) | 0/5 (0%) | 0 | Service Connectivity (구조적 한계) |
| F5 PVCPending | 2/5 (40%) | 1/5 (20%) | -20pp | PVC Provisioning |
| F6 NetworkPolicy | 2/5 (40%) | 1/5 (20%) | -20pp | Network Connectivity |
| F7 CPUThrottle | 3/5 (60%) | 5/5 (100%) | +40pp | CPU Throttling — V8 유일 향상 |
| F8 ServiceEndpoint | 2/5 (40%) | 1/5 (20%) | -20pp | Endpoint Misconfig |
| F9 SecretConfigMap | 2/5 (40%) | 2/5 (40%) | 0 | Secret/ConfigMap |
| F10 ResourceQuota | 3/5 (60%) | 4/5 (80%) | +20pp | ResourceQuota |
| **F11 NetworkDelay** | 0/5 (0%) | 0/5 (0%) | 0 | **CrashLoopBackOff (4) — 환경 오염 오진** |
| **F12 NetworkLoss** | 0/5 (0%) | 0/5 (0%) | 0 | **CrashLoopBackOff (5) — 100% 환경 오염 오진** |

### 2-3. 핵심 실패 원인 Top 3

1. **환경 오염 (F11/F12 100% + F2 부분 점수의 일부)**: 잔류 RS `shippingservice-865585fdff` (V7 F2 t4의 잔류물)가 V8 실험 전반에 걸쳐 desired=1로 활성. F11/F12에서 LLM은 이 active CrashLoop pod를 root cause로 합리적으로 추론. F2에서는 의도한 fault와 잔류 fault가 같은 service라 부분 점수만 획득.
2. **F2 score 분포 shift (V7 100% → V8 30% avg)**: judge prompt 동일, 진단(CrashLoopBackOff)도 일관. 컨텍스트가 V8에서 길어졌고(메트릭 4종 추가) root_cause 설명에 추상화가 더해지면서 judge가 1.0 대신 0.5 부여. 본 V9에서는 컨텍스트 길이가 V8과 동일하므로 이 효과는 carry-over.
3. **gRPC 메트릭 fundamental 부재 (시나리오 Beta 한계)**: V8 plan §13 시나리오 A로 확정. V9 범위 밖 (V10에서 가설 b로 다룸).

### 2-4. raw_v8 실측 검증 사항

- **METRIC ANOMALIES 중복** (deep_analysis_v9 §1-4 가설): 120 파일 grep 결과 **0건** — 가설 기각. context_builder 코드 검사로도 단일 emit 확인.
- **RAG chunk header 중복** (실측 발견): F11_t1_B 컨텍스트에서 `# Runbook: F11 - NetworkDelay Root Cause Analysis` 두 번 출력. RAG ingest/format 단에서 발생. **V9 환경 전제조건으로 정정**.
- **GitOps 만성 에러** (실측 발견): "emailservice grpc port duplicate" FluxCD 에러가 모든 V8 trial에서 출력됨. 이는 V9 범위 밖이지만, V10 후보로 §15에 기록.

---

## 3. 개선 사항 상세

### 3-1. [독립변수] scripts/stabilize/state_validator.py — 신규 모듈 (~200 lines)

**위치 결정**: `scripts/stabilize/`에 두어 fault stabilization 흐름의 일환임을 표현. recovery.py와 동일 디렉토리이지만 호출 시점이 다름 (recovery는 trial 종료 후, validator는 trial 시작 직전).

**모듈 인터페이스**:

```python
# scripts/stabilize/state_validator.py (신규)
"""Pre-Trial State Validator: ensure clean cluster state before each trial.

Inspired by SynergyRCA StateChecker pattern (arxiv:2506.02490).
"""
from dataclasses import dataclass
from typing import Literal
import logging

logger = logging.getLogger(__name__)

NAMESPACE = "boutique"

# Fault category map (가정 §0-2)
FAULT_TARGET_TYPE = {
    "F1": "service", "F2": "service", "F3": "service",
    "F4": "node",                                     # worker01-03
    "F5": "service", "F6": "service", "F7": "service",
    "F8": "service", "F9": "service", "F10": "service",
    "F11": "node", "F12": "node",                     # worker01-03
}

@dataclass
class StaleFinding:
    kind: Literal["stale_rs", "abnormal_pod"]
    name: str           # RS or pod name
    deployment: str     # owning deployment
    detail: str         # restart count, phase, reason

@dataclass
class ValidationResult:
    status: Literal["clean", "corrected", "skipped"]
    findings: list[StaleFinding]
    correction_attempts: int
    elapsed_seconds: float


class StateValidator:
    def __init__(self, kubectl_runner, ground_truth_row: dict):
        self.kubectl = kubectl_runner
        self.gt = ground_truth_row  # for target_service whitelist

    def validate_and_correct(
        self, fault_id: str, max_attempts: int = 2,
    ) -> ValidationResult:
        """Run StateChecker; if stale found, attempt correction up to max_attempts."""
        import time
        t0 = time.time()
        attempts = 0
        findings = self._scan(fault_id)
        if not findings:
            return ValidationResult("clean", [], 0, time.time() - t0)

        while findings and attempts < max_attempts:
            attempts += 1
            deployments_to_wait = self._correct(findings, attempt=attempts)
            self._wait_stable(deployments_to_wait, timeout=120)  # rollout-based, 필수 수정 3
            findings = self._scan(fault_id)

        status = "corrected" if not findings else "skipped"
        return ValidationResult(status, findings, attempts, time.time() - t0)

    def _scan(self, fault_id: str) -> list[StaleFinding]:
        """Combine RS-level + Pod-level stale detection (가정 §0-1)."""
        findings = []

        # RS-level: replicas >= 1 AND RS != deployment.status latest RS
        rs_data = self.kubectl.get_replicasets(NAMESPACE)
        deploy_data = self.kubectl.get_deployments(NAMESPACE)
        latest_rs_per_deploy = self._compute_latest_rs(deploy_data, rs_data)
        for rs in rs_data:
            if rs["status"]["replicas"] >= 1:
                deploy_name = self._owner_deployment(rs)
                if rs["metadata"]["name"] != latest_rs_per_deploy.get(deploy_name):
                    findings.append(StaleFinding(
                        kind="stale_rs",
                        name=rs["metadata"]["name"],
                        deployment=deploy_name,
                        detail=f"replicas={rs['status']['replicas']}, not latest",
                    ))

        # Pod-level: abnormal phases NOT belonging to current fault's target_service
        target_type = FAULT_TARGET_TYPE.get(fault_id, "service")
        whitelist_svc = self.gt.get("target_service", "") if target_type == "service" else None

        pods = self.kubectl.get_pods(NAMESPACE)
        for pod in pods:
            phase = pod["status"]["phase"]
            owner_deploy = self._pod_owner_deploy(pod)
            # Skip whitelist (current fault's expected pod)
            if whitelist_svc and owner_deploy == whitelist_svc:
                continue
            # Detect abnormal
            if self._is_abnormal(pod):
                findings.append(StaleFinding(
                    kind="abnormal_pod",
                    name=pod["metadata"]["name"],
                    deployment=owner_deploy,
                    detail=f"phase={phase}, "
                           f"reason={self._extract_reason(pod)}, "
                           f"restarts={self._max_restarts(pod)}",
                ))
        return findings

    def _is_abnormal(self, pod: dict) -> bool:
        """Pod is abnormal if CrashLoopBackOff/Error/Evicted or restart count exceeds threshold.

        Threshold rationale (review_v9.md §2.2 필수 수정 2):
          - restartCount ≥ 5는 정상 운영 baseline에서도 빈번 발생. false positive 위험.
          - V8 raw 잔류 RS 케이스는 restart count 26~38이었음 → 임계값을 ≥ 10으로 상향.
          - 추가로 trial 시작 시점 baseline_restarts을 trial_runner로부터 받아 상대 증가 ≥ 5도 abnormal로 판정 (carry-over 차단).
        """
        phase = pod["status"]["phase"]
        if phase in ("Failed", "Unknown"):
            return True
        for c in pod["status"].get("containerStatuses", []):
            wait_reason = c.get("state", {}).get("waiting", {}).get("reason", "")
            if wait_reason in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"):
                return True
            if c.get("restartCount", 0) >= 10:
                return True
            # 상대 증가 검사: trial 시작 baseline 대비 +5 이상이면 carry-over로 간주
            baseline = self.baseline_restarts.get((pod["metadata"]["name"], c["name"]), 0)
            if c.get("restartCount", 0) - baseline >= 5:
                return True
        return False

    def _correct(self, findings: list[StaleFinding], attempt: int) -> set[str]:
        """Attempt 1: rollout restart. Attempt 2: force delete RS + rollout. Returns set of deployments to wait on."""
        deployments_to_restart = {f.deployment for f in findings if f.deployment}
        if attempt == 1:
            for d in deployments_to_restart:
                logger.info("Validator soft correction: rollout restart deploy/%s", d)
                self.kubectl.rollout_restart_deployment(d, NAMESPACE)
        else:
            for f in findings:
                if f.kind == "stale_rs":
                    logger.info("Validator hard correction: delete rs/%s --force", f.name)
                    self.kubectl.delete_rs(f.name, NAMESPACE, grace_period=0, force=True)
            for d in deployments_to_restart:
                self.kubectl.rollout_restart_deployment(d, NAMESPACE)
        return deployments_to_restart

    def _wait_stable(self, deployments: set[str], timeout: int = 120):
        """Wait for rollout completion using kubectl rollout status (review_v9.md §2.2 필수 수정 3).

        단순 sleep은 rollout 미완료 위험(starting/Pending pod가 다음 trial 컨텍스트에 등장 → LLM이 fault로 오인).
        kubectl rollout status는 deployment의 모든 ReplicaSet이 desired=ready 상태일 때만 0 종료.
        """
        for d in deployments:
            self.kubectl.rollout_status(d, NAMESPACE, timeout_seconds=timeout)

    # --- helpers (compute_latest_rs, owner_deployment, pod_owner_deploy, etc) ---
```

**예상 효과**:
- F11/F12 trial 진입 시 잔류 RS `shippingservice-865585fdff`가 발견되면 자동 정정 → context의 dominant CrashLoop signal 제거 → LLM이 실제 fault signal에 집중
- F1-F10 trial 격리: 이전 fault 잔류 누적 차단

**리스크 및 대응**:
- F2 trial 시 의도된 CrashLoopBackOff pod를 stale로 오인 → 화이트리스트 (`target_service` deployment의 pod는 제외)로 방지
- 정정 액션이 정상 pod의 graceful shutdown 방해 → soft → hard 단계적 적용
- skipped trial 누적 시 통계적 검증력 저하 → fault당 skipped ≥ 2건이면 reporting에 별도 표기

### 3-2. [독립변수] experiments/shared/runner.py — Step 0.5 hook 추가

**변경 전** (현재 `run_trial` 메서드, L40-65):
```python
def run_trial(self, fault_id, trial, dry_run=False, ground_truth=None):
    # ── Step 1: Inject ──
    if not dry_run:
        injection_result = self.injector.inject(fault_id, trial)
        ...
```

**변경 후**:
```python
def run_trial(self, fault_id, trial, dry_run=False, ground_truth=None):
    gt_row = ground_truth.get((fault_id, trial), {}) if ground_truth else {}

    # ── Step 0.5: Pre-Trial State Validation (NEW in V9) ──
    validator_result = None
    if not dry_run and self.validator is not None:
        logger.info("Validating pre-trial cluster state...")
        validator_result = self.validator.validate_and_correct(fault_id)
        logger.info(
            "Validator: status=%s, findings=%d, attempts=%d, elapsed=%.1fs",
            validator_result.status, len(validator_result.findings),
            validator_result.correction_attempts, validator_result.elapsed_seconds,
        )
        if validator_result.status == "skipped":
            self._record_skipped(fault_id, trial, validator_result)
            logger.warning(
                "Trial SKIPPED: %s t%d (stale not corrected after %d attempts)",
                fault_id, trial, validator_result.correction_attempts,
            )
            return  # do not inject, do not record A/B results

    # ── Step 1: Inject ──
    if not dry_run:
        injection_result = self.injector.inject(fault_id, trial)
        ...
```

**추가 메서드**: `_record_skipped()` — CSV에 `skipped=true` 행을 A/B 각각 추가 + raw에 validator metadata만 저장.

**예상 효과**: 모든 trial이 시작 시점에 깨끗한 상태에서 출발. 잔류 fault 누적 차단.

**리스크 및 대응**:
- validator 자체 실패(kubectl 에러 등) → try/except로 감싸 trial을 skipped로 처리하고 다음 진행
- skipped 처리 코드의 CSV 헤더 호환성 → CSV_HEADERS에 `skipped`, `validator_status`, `validator_findings` 컬럼 추가

### 3-3. [독립변수] experiments/shared/csv_io.py + V9 config — `skipped` 컬럼 + validator metadata

**변경 전**: `experiments/v8/config.py`의 CSV_HEADERS에 skipped 관련 컬럼 없음.

**변경 후 (V9 config)**:
```python
CSV_HEADERS = [
    # ... V8과 동일 컬럼 유지 ...
    "skipped",              # NEW: True if validator skipped this trial
    "validator_status",     # NEW: clean | corrected | skipped
    "validator_findings",   # NEW: count of stale findings
    "validator_attempts",   # NEW: correction attempts (0, 1, 2)
]
```

`csv_io.append_result`는 dict 키 누락 시 빈 문자열 처리하므로 별도 변경 불필요.

### 3-4. [독립변수] experiments/v9/ — V8 fork

V8 디렉토리를 복사하여 V9 생성. 변경:

| 파일 | 변경 내용 |
|---|---|
| `experiments/v9/__init__.py` | export 클래스명을 `RCAEngineV9`로 |
| `experiments/v9/config.py` | CSV/raw 경로를 v9, `CSV_HEADERS`에 skipped 컬럼 4종 추가 |
| `experiments/v9/engine.py` | `RCAEngineV8` → `RCAEngineV9` 명만 변경. **로직·프롬프트 완전 동일** |
| `experiments/v9/prompts.py` | V8과 완전 동일 (SOP 변경 없음) |
| `experiments/v9/run.py` | runner 인스턴스화 시 `validator=StateValidator(...)` 주입 |

### 3-5. [환경 전제조건] RAG chunk header 중복 제거

**위치**: RAG ingest 또는 retriever format 단. `src/rag/` 디렉토리 내. 정확한 파일은 코드 단계(@code-reviewer)에서 결정 — 후보:
- `src/rag/ingest.py` 의 청크 분할 로직
- `src/rag/retriever.py` 의 `format_context()` 메서드

**근거**: raw_v8 실측 (§0-4, §2-4). 5-10줄 변경 예상.

**검증 방법**: V9 dry-run 1건의 raw context에서 RAG 섹션을 grep:
```python
import re
duplicates = re.findall(r'# Runbook: F\d+ - .* Root Cause Analysis\n# Runbook: F\d+', ctx)
assert len(duplicates) == 0, "RAG chunk header still duplicated"
```

### 3-6. [환경 전제조건] RAG 재인덱싱 (chunk header 변경 후)

```bash
python -m src.rag.ingest
```

V8 RAG 일관성 검증과 동일하게 F2 검색 top-3 source가 V8 결과와 동일한지 확인 (V8 plan §7-1 5단계 절차).

---

## 4. 통제 변수 (변경하지 않는 것)

| 항목 | 파일 | 설명 |
|---|---|---|
| 프롬프트 | `experiments/v9/prompts.py` | V8 SOP 프롬프트 완전 동일 |
| 엔진 로직 | `experiments/v9/engine.py` | V8 RCAEngineV8 로직 그대로 복사 (클래스명만 V9) |
| LLM 모델 | gpt-4o-mini | 고정 |
| Evaluator | V8 EVALUATOR_PROMPT | 동일 |
| Retry 로직 | MAX_RETRIES=2 | 동일 |
| Evidence Verification | `_verify_evidence()` | 동일 |
| Correctness Judge | `judge_correctness()` | 동일 |
| Prometheus 메트릭 4종 (V8 추가분) | `src/collector/prometheus.py` | V8과 동일 (시나리오 Beta 그대로) |
| RAG 런북 (F11/F12) | `docs/runbooks/rca-f11-*.md`, `rca-f12-*.md` | V8과 동일 (header 중복 제거 효과는 §3-5에서) |
| context_builder | `src/processor/context_builder.py` | V8과 동일 |
| F1-F12 fault injection | `scripts/fault_inject/` | 변경 없음 |
| F1-F12 recovery (per-fault) | `scripts/stabilize/recovery.py` | 변경 없음 (validator는 별도 모듈) |
| 평가 방식 | `ground_truth.csv` + judge | 동일 |

---

## 5. 실험 파라미터

| 파라미터 | 값 | 비고 |
|---|---|---|
| 실험 버전 | V9 | |
| 모델 | gpt-4o-mini | 고정 |
| 프로바이더 | openai | |
| Fault types | F1-F12 | 12종 |
| Trials per fault | 5 | |
| 총 trials | 120 (A+B) = 60 pairs (skipped 제외 후 분석) | |
| 시나리오 | Beta (V8 동일, gRPC 메트릭 부재) | gRPC instrumentation은 V10 후보 |
| Collection window | 5분 | Prometheus range query 윈도우 |
| Validator max_attempts | 2 | soft → hard, 실패 시 skipped |
| Validator wait per attempt | 60s | rollout 후 안정화 대기 |
| INJECTION_WAIT | fault별 상이 | F11/F12는 60초 (V8 동일) |
| Cooldown (fault 간) | 900초 (15분) | V8 동일 |
| Cooldown (trial 간) | 60초 | V8 동일 |
| MAX_TOKENS | 2048 | LLM 출력 토큰 |
| MAX_RETRIES | 2 | Evaluator 기반 재시도 |
| TOP_K (RAG) | 5 | RAG 검색 문서 수 |

---

## 6. 코드 수정 체크리스트

### 독립변수 (반드시 수정)

- [ ] `scripts/stabilize/state_validator.py` 신규 생성 (~200 lines)
- [ ] `scripts/stabilize/__init__.py`에 `StateValidator` export 추가
- [ ] `experiments/shared/runner.py` `run_trial()`에 Step 0.5 hook 추가, `_record_skipped()` 메서드 추가, `__init__`에 `validator` 파라미터 추가
- [ ] `experiments/v9/` 디렉토리 생성 (V8 복사 기반)
- [ ] `experiments/v9/config.py` CSV/raw 경로 v9, `CSV_HEADERS`에 4컬럼 추가
- [ ] `experiments/v9/engine.py` 클래스명 RCAEngineV9
- [ ] `experiments/v9/run.py` `validator=StateValidator(...)` 주입
- [ ] `experiments/v9/__init__.py` export 갱신

### 환경 전제조건 (독립변수 아님)

- [ ] `src/rag/{ingest.py | retriever.py}` chunk header 중복 제거 (5-10줄, 정확 위치는 code 단계에서)
- [ ] RAG 재인덱싱: `python -m src.rag.ingest`
- [ ] RAG 재인덱싱 일관성 검증 (F2 top-3 source가 V8과 동일)

### 검증 (dry-run 전)

- [ ] State Validator 단위 시나리오 점검:
  - 깨끗한 상태 → status=clean
  - 의도적으로 stale RS 1개 생성 후 → status=corrected
  - 의도적으로 RS 정정 불가 상태(예: deployment 자체 삭제) → status=skipped
- [ ] V9 dry-run 1건 (예: F11_t1) 실행, raw에서 RAG header 중복 없음 grep 검증
- [ ] V9 dry-run 추가 (F2_t4): 화이트리스트가 의도된 CrashLoop을 stale로 오인하지 않는지 확인

---

## 7. 실행 명령어

### 7-1. 사전 점검 (필수 — 검증 통과 후에만 본 실험 진행)

#### 점검 절차

```bash
# 1. 실험 환경 터널 연결
/lab-tunnel

# 2. State Validator 단위 점검 (수동)
# 2-1. 깨끗한 상태 baseline
python3 -c "
from scripts.stabilize.state_validator import StateValidator
from src.collector.kubectl import KubectlRunner  # 실제 모듈명은 code 단계에서 확정
v = StateValidator(KubectlRunner(), ground_truth_row={})
result = v.validate_and_correct('F1', max_attempts=0)  # 0 attempts = scan only
print(f'baseline status={result.status}, findings={len(result.findings)}')
# 기대: clean (lab-restore 직후라면)
"

# 2-2. Stale RS 시뮬레이션 — 직접 RS scale (선택적, 위험하므로 dry-run 단계로 대체 가능)
# kubectl scale rs <oldrs> --replicas=1 -n boutique
# python3 ... validate_and_correct('F11')
# kubectl get rs -n boutique  # 정정 후 stale RS 0인지 확인

# 3. RAG chunk header 중복 제거 검증
python -m src.rag.ingest
python3 -c "
from src.rag.retriever import KnowledgeRetriever
r = KnowledgeRetriever()
docs = r.query_by_fault('F11')
ctx = r.format_context(docs)
import re
dups = re.findall(r'# Runbook: F\d+ - .* Root Cause Analysis\n# Runbook: F\d+', ctx)
print(f'Header duplicates: {len(dups)} (target=0)')
"

# 4. V8과의 RAG 일관성 (F2 search top-3 동일성)
python3 -c "
from src.rag.retriever import KnowledgeRetriever
r = KnowledgeRetriever()
docs = r.query_by_fault('F2')
print(f'F2 top-3 sources: {[d.short_source for d in docs[:3]]}')
# 기대: V8 결과와 동일 (RAG 본질 변경 없음 검증)
"
```

#### 통과 기준

| 점검 항목 | 통과 기준 | 미통과 시 |
|---|---|---|
| Validator baseline | clean (또는 corrected with attempts=1) | 즉시 lab-restore 후 재시도 |
| Validator stale 시나리오 | corrected | code 단계로 회귀 |
| RAG header 중복 | duplicates = 0 | code 단계로 회귀 |
| RAG F2 일관성 | V8 top-3 source 동일 | 임베딩 재생성 후 재검증 |

### 7-2. dry-run 테스트

#### 7-2-1. 핵심 가설 검증

```bash
# F11 t1 — Validator clean → inject → 컨텍스트 수집 (LLM 호출은 dry_run으로 skip)
python -m experiments.v9.run --dry-run --fault F11 --trial 1

# F2 t4 — 화이트리스트 검증: shippingservice CrashLoop pod가 fault 의도이므로 stale에서 제외
python -m experiments.v9.run --dry-run --fault F2 --trial 4
```

#### 7-2-2. Validator 거동 점검

```bash
# Stale RS 인위 생성 (F2 t4 직후 잔류 RS 시뮬레이션)
kubectl get rs -n boutique | grep shippingservice  # 두 개 RS 존재 시점
# 다음 trial(F11 t1) dry-run에서 validator가 stale_rs 검출 → corrected → clean state로 진행하는지 확인
python -m experiments.v9.run --dry-run --fault F11 --trial 1 --verbose

# 기대 로그:
#   "Validator: status=corrected, findings=1, attempts=1, elapsed=~62s"
```

#### 7-2-3. dry-run 통과 기준

| 항목 | 통과 기준 |
|---|---|
| F1-F12 dry-run 12건 모두 성공 | validator 무한루프 없음, signal collection 정상 |
| F11 t1 with stale RS injected | corrected 상태로 진행, raw에 validator metadata 기록됨 |
| F2 t4 화이트리스트 | shippingservice CrashLoop pod를 stale로 분류하지 **않음** (의도된 fault) |
| RAG header 중복 | dry-run raw에서 0건 |

### 7-3. 본 실험

```bash
# 전체 실험 (F1-F12 x 5 trials = 60 pairs)
nohup python -m experiments.v9.run > results/experiment_v9_nohup.log 2>&1 &
echo $! > results/experiment_v9.pid

# 진행 모니터링
tail -f results/experiment_v9.log

# Validator 결과 추적 (병렬 터미널)
grep "Validator:" results/experiment_v9.log
```

### 7-4. 부분 실행 (필요 시)

```bash
# F11/F12만 먼저 (핵심 가설)
python -m experiments.v9.run --fault F11
python -m experiments.v9.run --fault F12

# Resume (skipped trial은 재시도)
python -m experiments.v9.run --resume
```

### 7-5. 실험 종료 후

```bash
# 1. 환경 정상화 (필수)
/lab-restore

# 2. 결과 분석 트리거
/experiment-status
# → results/analysis_v9.md 작성으로 이행
```

---

## 8. 예상 소요 시간 및 비용

### 시간

| 단계 | 시간 |
|---|---|
| state_validator.py 작성 + 단위 점검 | 2-3시간 |
| runner.py / V9 fork / config 수정 | 1시간 |
| RAG chunk header 수정 + 재인덱싱 | 30분 |
| 사전 점검 + dry-run | 1시간 |
| 본 실험 (60 pairs + 평균 30s/trial validator overhead) | 11-15시간 |
| 결과 분석 | 1시간 |
| **합계** | **~16-21시간** |

### Validator overhead

- 평균 trial: clean(40%) → 0s overhead, corrected(50%) → 60s overhead, skipped(10%) → 120s overhead → 평균 ~36s/trial 추가
- 60 pairs × 36s ≈ 36분 추가 (위 시간에 포함)

### API 비용 (추정, V8과 거의 동일)

| 항목 | 산출 근거 | 비용 |
|---|---|---|
| Generator 호출 | 120 trials x ~3K tokens | ~$0.72 |
| Evaluator 호출 | 120 trials x ~2K tokens | ~$0.48 |
| Retry 호출 | ~40 retries x ~3K tokens | ~$0.24 |
| Correctness Judge | 120 trials x ~1K tokens | ~$0.24 |
| **합계** | | **~$1.70** |

(skipped trial은 LLM 호출 미발생으로 비용 절감 가능)

---

## 9. 예상 결과

### 9-1. Fault별 예상 정확도 (V9 B vs V8 B, ≥0.5 cutoff)

| Fault | V8 B | V9 B (보수적) | V9 B (낙관적) | 근거 |
|---|---|---|---|---|
| F1 OOMKilled | 1/5 (20%) | 1/5 (20%) | 2/5 (40%) | 잔류 노이즈 제거 미세 효과 |
| F2 CrashLoopBackOff | 0/5 (0%) | 1/5 (20%) | 3/5 (60%) | 화이트리스트로 의도된 fault만 보임, score 분포 회복 가능 |
| F3 ImagePullBackOff | 4/5 (80%) | 4/5 (80%) | 4/5 (80%) | 변경 없음 |
| F4 NodeNotReady | 0/5 (0%) | 0/5 (0%) | 1/5 (20%) | 구조적 한계 |
| F5 PVCPending | 1/5 (20%) | 2/5 (40%) | 2/5 (40%) | 잔류 노이즈 제거 |
| F6 NetworkPolicy | 1/5 (20%) | 2/5 (40%) | 2/5 (40%) | 잔류 노이즈 제거 |
| F7 CPUThrottle | 5/5 (100%) | 5/5 (100%) | 5/5 (100%) | 변경 없음 |
| F8 ServiceEndpoint | 1/5 (20%) | 1/5 (20%) | 2/5 (40%) | 잔류 노이즈 제거 미세 |
| F9 SecretConfigMap | 2/5 (40%) | 2/5 (40%) | 2/5 (40%) | 변경 없음 |
| F10 ResourceQuota | 4/5 (80%) | 4/5 (80%) | 4/5 (80%) | 변경 없음 |
| **F11 NetworkDelay** | **0/5 (0%)** | **2/5 (40%)** | **3/5 (60%)** | **잔류 RS 제거 → 실제 신호로 진단** |
| **F12 NetworkLoss** | **0/5 (0%)** | **2/5 (40%)** | **3/5 (60%)** | **동일** |

### 9-2. 전체 정확도 예상 (≥0.5)

| 범위 | V8 B | V9 B (보수적) | V9 B (낙관적) |
|---|---|---|---|
| F1-F10 | 21/50 (42%) | 22-23/50 (44-46%) | 25/50 (50%) |
| F11-F12 | 0/10 (0%) | 4/10 (40%) | 6/10 (60%) |
| **전체 F1-F12** | **21/60 (35%)** | **26-27/60 (43-45%)** | **31/60 (52%)** |

### 9-3. Validator 거동 예상

| 메트릭 | 예상 값 |
|---|---|
| status=clean trial | ~40% (24/60) |
| status=corrected trial | ~55% (33/60) |
| status=skipped trial | ~5% (3/60, 주로 첫 1-2건의 환경 상태 비정상 시) |
| 평균 correction attempts | 1.1 |

### 9-4. 통계적 유의성 예상

- F11/F12 paired (V8 vs V9): 0/10 → 4-6/10. McNemar discordant pairs ≥ 4, 모두 V9 개선 방향 → p < 0.05 예상.
- F1-F10 paired: 21/50 → 22-25/50. 비열등성 검정 95% CI 하한 > -5pp 예상 (회귀 없음).

---

## 10. 성공 기준 + Correctness Judge 판정 규칙

### 10-0. Correctness Judge 판정 규칙 (V8 §10-0 그대로 승계)

V8 plan §10-0의 (a) tc netem K8s 포트 제외, (b) NodeNotReady 부작용 부분 정답 0.5, (c) Expected Root Cause 추상화 수준 few-shot 예시 — **모두 V9에 동일 적용**. 사전 정의 변경 없음.

#### 10-0-(d) V9 추가 — Validator 개입 시 판정 규칙

| 시나리오 | 판정 |
|---|---|
| Validator status=clean, LLM 정답 진단 | 정상 정답 (1.0 또는 0.5) |
| Validator status=corrected, LLM 정답 진단 | 정상 정답. validator metadata는 raw에 기록되어 사후 분석 가능 |
| Validator status=skipped | **CSV에 skipped=true, A/B score 모두 비기록**. 통계 분모에서 제외 |
| Validator corrected했으나 LLM이 여전히 잔류 fault로 오진 | 오답 (0.0). **분석 §11에 별도 분류** (validator effectiveness 한계 사례) |

### 10-1. 주 기준 (필수)

1. **F11 + F12 합산 B (≥0.5) ≥ 4/10 (40%)** — 0%에서의 유의미한 개선 (deep_analysis_v9 §8 주 기준)
2. **F1-F10 B (≥0.5) ≥ 21/(50 − skipped_count)** — V8 동등 이상 (회귀 허용 -5pp)
3. **전체 B (≥0.5) ≥ 26/(60 − skipped_count) (≈43%)** — V8(35%) 대비 +8pp
4. **skipped trial 총합 ≤ 6/60 (10%)** — validator 안정성 검증

### 10-2. 부 기준 (바람직)

5. F11 + F12 합산 B ≥ 6/10 (60%)
6. 전체 B ≥ 31/60 (52%)
7. Validator status=clean 비율 ≥ 30%
8. B > A 차이 F1-F12 전체에서 유지 (V8 동등 이상)

### 10-3. 실패 판정 기준

- **F11 + F12 합산 B < 1/10 (10%)** → 환경 오염이 주 원인 가설 기각, V10에서 가설 b (gRPC instrumentation)로 이동
- **F1-F10 B < 18/(50 − skipped_count) (36%)** → V8 대비 6pp 이상 회귀, validator가 정상 fault를 stale로 오인했을 가능성 (분석에서 화이트리스트 logic 검증)
- **skipped trial > 12/60 (20%)** → validator 자체 안정성 부족, soft correction 강도 재검토
- **F11+F12 skipped > 4/10 (40%)** (review_v9 §3.2 필수 수정 5) → 핵심 가설 검증 불가 (validator가 노드 레벨 잔류와 deployment 레벨 잔류를 분리하지 못함). V10에서 recovery.py 강화 + validator 책임 재정의 필요. F11+F12 분모가 ≤ 6이면 통계적 검증력 자체가 부족하여 가설 a 효과 측정 불가능
- **F11+F12 합산 B ∈ [1/10, 3/10]** (review_v9 §6.1 권장 수정 10에서 promoted) → 경계 시나리오. 잔류 RS 정정은 작동했으나 application 메트릭 부재가 fundamental 한계임을 결론. 검증 방법: corrected trial subset에서 정답률 = clean trial subset 정답률이면 메트릭 부재 확정. V10에서 가설 b 우선

---

## 11. 리스크 및 대응

### 리스크 1: Validator의 의도된 fault 오인 (F2 케이스)

**가능성**: 중. F2 trial은 ground_truth `target_service` deployment(예: shippingservice)에 의도적으로 CrashLoopBackOff를 유도. 화이트리스트가 정확해야 함.
**영향**: F2 점수 추가 회귀
**대응**:
1. dry-run F2_t1~t5 모두에서 validator 출력이 `findings=0` 또는 `findings only on non-target-service` 인지 확인
2. ground_truth.csv 모든 F2 행의 `target_service` 컬럼이 정확한 deployment명인지 사전 검증
3. 화이트리스트 매칭은 substring이 아닌 exact match로 (`shippingservice` ≠ `shippingservice-v2`)

### 리스크 2: Validator overhead로 trial 간 cooldown 부족

**가능성**: 낮. validator 평균 36s × 60 pairs = 36분 추가, V8 cooldown 60s로 흡수 가능.
**영향**: 실험 시간 +1-2시간
**대응**: 본 §8에 이미 반영. 추가 조치 불필요.

### 리스크 3: skipped trial 누적

**가능성**: 중. 실험 시작 시 lab-restore 미실행 또는 환경 만성 오염 시 첫 N개 trial 모두 skipped 가능.
**영향**: 통계적 검증력 저하
**대응**:
1. 실험 시작 직전 `/lab-restore` 강제 실행 (사전 점검에 명시)
2. skipped 비율 > 20% 도달 시 실험 즉시 중단, 환경 점검 후 재시작
3. 분석 §10-3 실패 판정에 명시

### 리스크 4: Validator 코드 자체 버그

**가능성**: 중. 신규 200줄 코드.
**영향**: 모든 trial 실패
**대응**:
1. 본 plan §6 단위 점검 3시나리오(clean / corrected / skipped) 통과 후 본 실험 진입
2. validator 자체 예외 시 try/except로 trial을 skipped 처리하고 다음 trial로 진행 (실험 중단 방지)
3. 첫 5 trial(F1_t1~F1_t5) 결과 모니터링 후 이상 시 즉시 중단

### 리스크 5: RAG chunk header 변경의 부작용

**가능성**: 낮. 5-10줄 변경, 본질 RAG 검색 로직 미변경.
**영향**: F2 검색 top-3 source 변경 → V7/V8 baseline 비교 어려워짐
**대응**:
1. 사전 점검 §7-1에서 F2 top-3 source가 V8과 동일한지 명시 검증
2. 차이 발견 시 임베딩 재생성 후 재검증, 그래도 차이 시 환경 전제조건 변경 보류 (V10으로 이월)

### 리스크 6: Validator가 fault inject 직전에 호출되어 timing 미세 변동

**가능성**: 낮. validator 60s wait 후 inject → 실제 fault propagation은 inject 후 60s.
**영향**: trial 간 변동성 증가
**대응**: V8과 동일하게 INJECTION_WAIT 60s 유지. Validator overhead는 inject 시점 기준 정렬 영향 무시 가능 수준.

---

## 12. 통계 검정 계획

V8 plan §12 그대로 승계 + V9 고유 추가.

### 12-1. 주 검정: V9 B vs V8 B (McNemar's test)

같은 (fault, trial) 쌍에 대해 V8 B와 V9 B의 정답/오답을 paired로 비교. **skipped trial은 분모에서 제외**.

| | V9 B 정답 | V9 B 오답 |
|---|---|---|
| V8 B 정답 | a | b |
| V8 B 오답 | c | d |

- McNemar χ² = (b − c)² / (b + c), H0: b = c
- 예상: c >> b (특히 F11/F12에서 0/10 → 4-6/10)

### 12-2. 부 검정: F11/F12 subset (Fisher's exact test)

F11/F12 10 trial(skipped 제외) 추출, V8 vs V9.
- V8: 0/10, V9 예상: 4-6/10 → Fisher's exact p < 0.05 예상

### 12-3. 주 가설 검정: V9 A vs V9 B (Wilcoxon signed-rank)

논문의 주 가설 "System B > System A"를 V9 데이터로 검정. validator는 A/B 모두에 동일 적용되므로 효과 직교.

### 12-4. 회귀 검정: F1-F10 V8 B vs V9 B (비열등성, V8 §12-4 승계)

- 비열등성 한계 δ = -5pp (사전 등록, 변경 불가)
- `confint_proportions_2indep(method="wald", compare="diff", alpha=0.05)`
- 95% CI 하한 > -0.05이면 비열등성 입증
- 분모는 50 − skipped_count (V9 고유 보정)

### 12-5. V9 고유: Validator effectiveness 분석

- Stale RS 검출 precision: validator가 stale로 분류한 RS 중 실제 잔류 fault 비율 (raw_v9에서 인공 검증)
- Stale RS 검출 recall: V9 trial 시작 시점에 존재한 실제 잔류 RS 중 validator가 검출한 비율 (운영 중 일부 trial에 의도적 stale 주입 후 측정 — V9에서는 미수행, V10 후보)
- 정정 성공률: corrected 후 재scan에서 findings=0 비율
- Skipped 분포: fault별, trial별 skipped 발생 패턴

### 12-6. V9 고유: Validator metadata 회귀 분석

각 trial의 validator metadata(findings 수, attempts, elapsed)와 LLM 정답률의 상관 분석:
- findings 수가 많을수록 정답률 낮은가? (validator가 부족한 정정만 했을 가능성)
- attempts > 1 trial의 정답률이 attempts = 1 대비 어떻게 다른가?

---

## 13. 실패 시 대안

### 시나리오 A: F11 + F12 합산 B 여전히 < 10%

1. raw_v9의 F11/F12 trial 컨텍스트 sampling — 잔류 RS가 정정되었음에도 LLM이 다른 신호로 오진했는지 확인
2. 만약 잔류 RS는 깨끗한데도 진단 실패: **V8 §13 시나리오 A (gRPC 메트릭 부재)**가 진짜 한계 → V10에서 가설 b (gRPC instrumentation)로 이동
3. 만약 잔류 RS가 여전히 존재: validator scan 알고리즘 버그 → §6 단위 점검 강화

### 시나리오 B: F1-F10 회귀 (B < 36%)

1. raw_v9에서 validator가 의도된 fault를 stale로 오인했는지 확인
2. 화이트리스트 logic 검증 (target_service 매칭 정확성)
3. 회귀 폭이 -10pp 이상이면 V9 폐기, validator 알고리즘 재설계 후 V9.1로 재시도

### 시나리오 C: skipped > 12/60

1. 실험 시작 직전 `/lab-restore` 누락 여부 확인
2. validator 정정 강도 부족: hard correction(force delete RS)이 작동하지 않은 케이스 분석
3. soft → hard 전환 wait 시간 60s → 90s 상향 조정 후 V9.1 재시도

### 시나리오 D: Validator overhead로 timing이 V8 대비 너무 다름

분석 §11에 timing 차이 명시. 본질 결과(F11/F12 정답률)에 영향 없으면 plan 변경 불필요.

---

## 14. 참조 문헌

| 논문/자료 | 핵심 기법 | V9 적용 |
|---|---|---|
| **SynergyRCA** (arxiv:2506.02490, Medium 2026-01) | StateGraph + StateChecker (verification module: factual validity, causal consistency before LLM involvement). Reported precision ≈ 0.90 | **본 V9 핵심 인용**. State Validator는 SynergyRCA StateChecker의 K8s ReplicaSet 도메인 단순화 적용 |
| **CHI 2025 LLM Observability** (dl.acm.org/10.1145/3706599.3719914) | 4대 설계 원칙: Awareness, Monitoring, **Intervention**, Operability | V8가 Awareness만 충족(raw_v8 가시화)했고 Intervention 부재였음을 V9 validator로 보완 |
| LLMRCA: Multilevel RCA Using Multimodal Observability (ACM 2025) | 다중 신호 소스 결합 | V8 단일 변수 정당화에서 인용. V9는 동일 신호 소스 유지(통제 변수)하므로 본 plan에서는 보조 인용 |
| Modern K8s Monitoring (Red Hat 2025) | Prometheus + synthetic probes | 본 V9에서는 신호 추가 없음. 통제 변수 |

---

## 15. V10 후속 실험 후보

V9 결과에 따라 V10에서 시도:

1. **(우선순위 1) gRPC OpenTelemetry interceptor + ServiceMonitor** (deep_analysis_v9 가설 b): V9가 환경 오염을 제거했음에도 F11/F12 < 40%이면 application-level 메트릭 추가 필요. boutique manifest에 interceptor 패치 + monitoring/ServiceMonitor 추가. 시나리오 Beta → Alpha 전환.

2. **(우선순위 2) GitOps "emailservice grpc port duplicate" 만성 에러 수정**: raw_v8/v9 GitOps 섹션에 일관 출력되는 FluxCD 에러. service spec.ports 중복 정의 수정. RAG/GitOps 컨텍스트 품질 향상.

3. **(우선순위 3) Validator effectiveness 측정 강화**: 의도적 stale RS 주입 → recall 측정. 본 V9에서는 운영 중인 환경에 자연 발생하는 stale만 측정.

4. **(우선순위 4) F2 score 분포 회복** (V7 100% → V8 30% → V9 ?): 컨텍스트 길이가 V8과 동일하게 유지되면 V9에서도 partial score 문제 carry-over. judge prompt few-shot 또는 root_cause 출력 specificity 강화.

5. **(우선순위 5) F4 시계열 수집** (V8 plan §15 1순위 carry-over): 노드 NotReady → Ready 회복 후에도 진단 가능한 시계열 신호 수집.

---

## Appendix A — 변경 가정 변경 이력

| 가정 | 출처 | V9 plan 결정 |
|---|---|---|
| 가설 c = METRIC ANOMALIES 중복 제거 | deep_analysis_v9 §1-4 | **기각** (raw_v8 120 파일 grep 0건). RAG chunk header 중복으로 정정 (§0-4) |
| Validator 위치 = `scripts/stabilize/` | brainstorming 자가-답변 | 채택 (recovery.py와 동일 디렉토리, "안정화" 의미 일관) |
| 단계적 정정 (soft → hard → skipped) | brainstorming 자가-답변 | 채택 (안전성과 효과 균형) |
| Stale 검출 = RS-level + Pod-level 결합 | brainstorming 자가-답변 | 채택 |
| 화이트리스트 = ground_truth `target_service` + fault 카테고리 | brainstorming 자가-답변 | 채택 |
| 통계 검정 = V8 §10-0/§12-4 승계 + V9 고유 추가 | brainstorming 자가-답변 | 채택 |

작성: 2026-04-28 (KST)
호출자(사용자) review로 plan critique → review_v9.md 작성 후 code 단계 이행 결정.
