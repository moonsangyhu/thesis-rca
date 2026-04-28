"""Pre-Trial State Validator: ensure clean cluster state before each trial.

V9 단일 독립변수. SynergyRCA StateChecker 패턴 (arxiv:2506.02490) 단순화 적용.

매 trial 시작 직전 클러스터 state를 검증하고 잔류 fault(stale ReplicaSet,
abnormal pod)를 자동 정정한다. 정정 실패 시 trial을 skipped로 표시.

플랜 위치: docs/plans/experiment_plan_v9.md §3-1 (코드 스케치 + 1차 리비전 반영).
"""
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

from scripts.fault_inject.config import KUBECONFIG, KUBECTL

logger = logging.getLogger(__name__)

NAMESPACE = "boutique"

# Fault category map (가정 §0-2 + 필수 수정 1)
# - "service": target_service 컬럼이 application service 이름. 해당 deployment의 비정상 pod는
#              fault inject의 의도된 결과로 화이트리스트에 포함.
# - "node": target_service 컬럼이 worker 노드 이름. validator는 deployment 레벨만 정정하고
#           노드 레벨 잔류(tc netem 룰, NodeNotReady)는 recovery.py 책임.
FAULT_TARGET_TYPE = {
    "F1": "service", "F2": "service", "F3": "service",
    "F4": "node",
    "F5": "service", "F6": "service", "F7": "service",
    "F8": "service", "F9": "service", "F10": "service",
    "F11": "node", "F12": "node",
}

DEFAULT_RESTART_THRESHOLD_ABSOLUTE = 10
DEFAULT_RESTART_THRESHOLD_RELATIVE = 5
DEFAULT_ROLLOUT_TIMEOUT = 120


@dataclass
class StaleFinding:
    kind: Literal["stale_rs", "abnormal_pod"]
    name: str
    deployment: str
    detail: str


@dataclass
class ValidationResult:
    status: Literal["clean", "corrected", "skipped"]
    findings: list[StaleFinding]
    correction_attempts: int
    elapsed_seconds: float

    def summary(self) -> str:
        kinds = {}
        for f in self.findings:
            kinds[f.kind] = kinds.get(f.kind, 0) + 1
        kind_str = ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())) or "none"
        return (
            f"status={self.status}, findings={len(self.findings)} ({kind_str}), "
            f"attempts={self.correction_attempts}, elapsed={self.elapsed_seconds:.1f}s"
        )


def _kubectl_json(*args: str) -> dict:
    """Run kubectl with -o json and parse output."""
    cmd = [KUBECTL, "-n", NAMESPACE, *args, "-o", "json"]
    env = os.environ.copy()
    env["KUBECONFIG"] = KUBECONFIG
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, env=env,
        )
        if result.returncode != 0:
            logger.warning("kubectl stderr: %s", result.stderr.strip())
            return {}
        return json.loads(result.stdout) if result.stdout else {}
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        logger.error("kubectl get failed: %s", e)
        return {}


def _kubectl_run(*args: str, timeout: int = 60) -> tuple[int, str, str]:
    cmd = [KUBECTL, "-n", NAMESPACE, *args]
    env = os.environ.copy()
    env["KUBECONFIG"] = KUBECONFIG
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


class StateValidator:
    """Pre-trial cluster state validator + corrector.

    Usage:
        validator = StateValidator(ground_truth_loader)
        result = validator.validate_and_correct(fault_id="F11", max_attempts=2)
        if result.status == "skipped":
            # record CSV with skipped=true and skip this trial
            ...
    """

    def __init__(self, ground_truth: Optional[dict] = None):
        # ground_truth dict: {(fault_id, trial): {target_service: ...}, ...}
        self.ground_truth = ground_truth or {}
        # baseline restart counts captured at trial start (set by validator self before _scan)
        self.baseline_restarts: dict[tuple[str, str], int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_and_correct(
        self,
        fault_id: str,
        trial: int = 0,
        max_attempts: int = 2,
    ) -> ValidationResult:
        """Run StateChecker; if stale found, attempt correction up to max_attempts."""
        t0 = time.time()
        attempts = 0

        # Capture baseline restart counts BEFORE first scan
        # (필수 수정 2: relative-increase 검사용)
        self._capture_baseline_restarts()

        findings = self._scan(fault_id, trial)
        if not findings:
            return ValidationResult("clean", [], 0, time.time() - t0)

        logger.info(
            "Validator initial scan: %d stale findings — %s",
            len(findings),
            [f"{f.kind}/{f.name}" for f in findings],
        )

        while findings and attempts < max_attempts:
            attempts += 1
            deployments_to_wait = self._correct(findings, attempt=attempts)
            self._wait_stable(deployments_to_wait, timeout=DEFAULT_ROLLOUT_TIMEOUT)
            findings = self._scan(fault_id, trial)
            if findings:
                logger.warning(
                    "Validator attempt %d: %d findings remaining",
                    attempts, len(findings),
                )

        status = "corrected" if not findings else "skipped"
        return ValidationResult(status, findings, attempts, time.time() - t0)

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def _scan(self, fault_id: str, trial: int) -> list[StaleFinding]:
        """Combine RS-level + Pod-level stale detection (가정 §0-1).

        F11/F12 (target_type=node)에서는 node NotReady deployment의 pod를 stale로
        검출하지 않음 (recovery.py 책임 분리, 필수 수정 1).
        """
        findings = []

        target_type = FAULT_TARGET_TYPE.get(fault_id, "service")
        whitelist_svc = self._whitelist_service(fault_id, trial, target_type)

        # Node-level guard for F4/F11/F12: skip pods on NotReady nodes (recovery.py 책임)
        notready_nodes = set()
        if target_type == "node":
            notready_nodes = self._notready_node_set()
            if notready_nodes:
                logger.info(
                    "Validator skips pods on NotReady nodes (target_type=node): %s",
                    sorted(notready_nodes),
                )

        # ---- RS-level: replicas >= 1 AND RS != deployment.status latest RS ----
        rs_list = _kubectl_json("get", "rs").get("items", []) or []
        deploy_list = _kubectl_json("get", "deploy").get("items", []) or []
        latest_rs_per_deploy = self._compute_latest_rs(deploy_list, rs_list)

        for rs in rs_list:
            replicas = (rs.get("status") or {}).get("replicas", 0) or 0
            if replicas < 1:
                continue
            rs_name = rs["metadata"]["name"]
            deploy_name = self._owner_deployment(rs)
            if not deploy_name:
                continue
            latest = latest_rs_per_deploy.get(deploy_name)
            if not latest or rs_name == latest:
                continue
            findings.append(StaleFinding(
                kind="stale_rs",
                name=rs_name,
                deployment=deploy_name,
                detail=f"replicas={replicas}, latest={latest}",
            ))

        # ---- Pod-level: abnormal pods NOT in fault target_service whitelist ----
        pod_list = _kubectl_json("get", "pods").get("items", []) or []
        for pod in pod_list:
            owner = self._pod_owner_deploy(pod)
            if whitelist_svc and owner == whitelist_svc:
                continue
            # Node guard (F4/F11/F12): skip pods on NotReady nodes
            node = (pod.get("spec") or {}).get("nodeName", "")
            if node in notready_nodes:
                continue
            if not self._is_abnormal(pod):
                continue
            findings.append(StaleFinding(
                kind="abnormal_pod",
                name=pod["metadata"]["name"],
                deployment=owner or "(unknown)",
                detail=self._pod_detail(pod),
            ))

        return findings

    def _is_abnormal(self, pod: dict) -> bool:
        """Pod is abnormal if Failed/Unknown phase, CrashLoop/ImagePull waiting, or restart count threshold.

        필수 수정 2 (review_v9 §2.2):
          - 절대 임계값 ≥ 10 (V8 raw 잔류 RS 케이스 26~38, 정상 baseline 0~3)
          - 상대 증가 ≥ 5 (carry-over 차단)
        """
        status = pod.get("status") or {}
        phase = status.get("phase", "")
        if phase in ("Failed", "Unknown"):
            return True
        for c in status.get("containerStatuses", []) or []:
            wait_reason = ((c.get("state") or {}).get("waiting") or {}).get("reason", "") or ""
            if wait_reason in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"):
                return True
            rc = c.get("restartCount", 0) or 0
            if rc >= DEFAULT_RESTART_THRESHOLD_ABSOLUTE:
                return True
            baseline = self.baseline_restarts.get(
                (pod["metadata"]["name"], c.get("name", "")), 0,
            )
            if rc - baseline >= DEFAULT_RESTART_THRESHOLD_RELATIVE:
                return True
        return False

    # ------------------------------------------------------------------
    # Correct
    # ------------------------------------------------------------------

    def _correct(self, findings: list[StaleFinding], attempt: int) -> set[str]:
        """Attempt 1: rollout restart. Attempt 2: force delete RS + rollout.

        Returns set of deployment names to wait on.
        """
        deployments = {f.deployment for f in findings if f.deployment and f.deployment != "(unknown)"}
        if attempt == 1:
            for d in deployments:
                logger.info("Validator soft correction: rollout restart deploy/%s", d)
                rc, _, err = _kubectl_run("rollout", "restart", f"deploy/{d}")
                if rc != 0:
                    logger.warning("rollout restart deploy/%s failed: %s", d, err.strip())
        else:
            for f in findings:
                if f.kind == "stale_rs":
                    logger.info("Validator hard correction: delete rs/%s --force", f.name)
                    rc, _, err = _kubectl_run(
                        "delete", "rs", f.name,
                        "--grace-period=0", "--force", "--ignore-not-found",
                    )
                    if rc != 0:
                        logger.warning("delete rs/%s failed: %s", f.name, err.strip())
            for d in deployments:
                _kubectl_run("rollout", "restart", f"deploy/{d}")
        return deployments

    def _wait_stable(self, deployments: set[str], timeout: int = DEFAULT_ROLLOUT_TIMEOUT) -> None:
        """Wait for rollout completion via `kubectl rollout status` (필수 수정 3).

        단순 sleep은 rollout 미완료 위험 — starting/Pending pod가 다음 trial 컨텍스트에 등장.
        """
        for d in sorted(deployments):
            rc, _, err = _kubectl_run(
                "rollout", "status", f"deploy/{d}",
                f"--timeout={timeout}s",
                timeout=timeout + 30,
            )
            if rc != 0:
                logger.warning(
                    "rollout status deploy/%s did not complete in %ds: %s",
                    d, timeout, err.strip(),
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _capture_baseline_restarts(self) -> None:
        self.baseline_restarts.clear()
        pods = _kubectl_json("get", "pods").get("items", []) or []
        for pod in pods:
            for c in (pod.get("status") or {}).get("containerStatuses", []) or []:
                key = (pod["metadata"]["name"], c.get("name", ""))
                self.baseline_restarts[key] = c.get("restartCount", 0) or 0

    def _whitelist_service(self, fault_id: str, trial: int, target_type: str) -> str:
        if target_type != "service":
            return ""
        gt_row = self.ground_truth.get((fault_id, trial), {}) if isinstance(self.ground_truth, dict) else {}
        return (gt_row.get("target_service") or "").strip()

    def _notready_node_set(self) -> set[str]:
        nodes = _kubectl_json("get", "nodes").get("items", []) or []
        notready = set()
        for n in nodes:
            cond = ((n.get("status") or {}).get("conditions") or [])
            ready_status = next(
                (c.get("status") for c in cond if c.get("type") == "Ready"),
                "",
            )
            if ready_status != "True":
                notready.add(n["metadata"]["name"])
        return notready

    @staticmethod
    def _compute_latest_rs(deploy_list: list[dict], rs_list: list[dict]) -> dict[str, str]:
        """Map deployment name → latest RS name (highest revision annotation)."""
        # Group RS by owning deployment
        by_deploy: dict[str, list[dict]] = {}
        for rs in rs_list:
            owners = (rs.get("metadata") or {}).get("ownerReferences", []) or []
            for o in owners:
                if o.get("kind") == "Deployment":
                    by_deploy.setdefault(o["name"], []).append(rs)

        latest = {}
        for deploy_name, items in by_deploy.items():
            best_rev = -1
            best_name = None
            for rs in items:
                anns = (rs.get("metadata") or {}).get("annotations", {}) or {}
                try:
                    rev = int(anns.get("deployment.kubernetes.io/revision", "0"))
                except ValueError:
                    rev = 0
                if rev > best_rev:
                    best_rev = rev
                    best_name = rs["metadata"]["name"]
            if best_name:
                latest[deploy_name] = best_name
        return latest

    @staticmethod
    def _owner_deployment(rs: dict) -> str:
        for o in (rs.get("metadata") or {}).get("ownerReferences", []) or []:
            if o.get("kind") == "Deployment":
                return o.get("name", "")
        return ""

    @staticmethod
    def _pod_owner_deploy(pod: dict) -> str:
        # Pods are owned by RS, not Deployment directly. Strip RS suffix.
        for o in (pod.get("metadata") or {}).get("ownerReferences", []) or []:
            if o.get("kind") == "ReplicaSet":
                rs_name = o.get("name", "")
                # ReplicaSet name = "<deploy>-<hash>"
                if "-" in rs_name:
                    return rs_name.rsplit("-", 1)[0]
                return rs_name
        return ""

    @staticmethod
    def _pod_detail(pod: dict) -> str:
        status = pod.get("status") or {}
        phase = status.get("phase", "?")
        cs = status.get("containerStatuses", []) or []
        max_rc = max((c.get("restartCount", 0) or 0 for c in cs), default=0)
        reasons = []
        for c in cs:
            r = ((c.get("state") or {}).get("waiting") or {}).get("reason", "")
            if r:
                reasons.append(r)
        reason_str = ",".join(reasons) or "-"
        return f"phase={phase}, reasons={reason_str}, max_restarts={max_rc}"


__all__ = ["StateValidator", "ValidationResult", "StaleFinding", "FAULT_TARGET_TYPE"]
