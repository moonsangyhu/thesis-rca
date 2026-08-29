"""
Recovery/stabilization scripts for each fault type.

Reverts fault injection and restores cluster to healthy state.
"""
import logging
from pathlib import Path
import subprocess
import time

import yaml

from scripts.fault_inject.base import (
    kubectl, kubectl_apply, kubectl_delete, kubectl_patch,
    kubectl_get_json, ssh_node,
)
from scripts.fault_inject.config import (
    F4_T3_STRESS_BYTES,
    F4_T3_STRESS_LOG_FILE,
    F4_T3_NODE_NAME,
    F4_T3_STRESS_RECEIPT_FILE,
    F4_T3_STRESS_TIMEOUT_SECONDS,
    F4_T3_STRESS_VM_WORKERS,
    F4_T4_NODEFS_PATH,
    F4_T4_NODE_NAME,
    F4_T4_PARENT_DIR,
    F4_T4_TARGET_AVAILABLE_PERCENT,
    F4_T4_WORK_PREFIX,
    NAMESPACE,
    WORKER_NODES,
)

logger = logging.getLogger(__name__)

# Original Online Boutique manifest in the checked-out experiment revision.
# Recovery must not depend on the optional GitOps scratch clone under /tmp.
ORIGINAL_MANIFEST = str(
    Path(__file__).resolve().parents[2] / "k8s" / "app" / "online-boutique.yaml"
)

F4_T4_RECOVERY_ATTEMPTS = 10
F4_T4_CONDITION_POLL_ATTEMPTS = 15
F4_T4_RETRY_DELAY_SECONDS = 2
F6_POLICY_NAMES = {
    1: "fault-deny-all",
    2: "fault-block-cart",
    3: "fault-block-payment",
    4: "fault-block-dns",
    5: "fault-block-redis",
}
F2_CRASH_COMMAND = ["/bin/sh", "-c", "exit 1"]


class Recovery:
    """Recover from injected faults."""

    def __init__(self):
        self._recoverers = {
            "F1": self._recover_f1,
            "F2": self._recover_f2,
            "F3": self._recover_f3,
            "F4": self._recover_f4,
            "F5": self._recover_f5,
            "F6": self._recover_f6,
            "F7": self._recover_f7,
            "F8": self._recover_f8,
            "F9": self._recover_f9,
            "F10": self._recover_f10,
            "F11": self._recover_f11_network_delay,
            "F12": self._recover_f12_network_loss,
        }

    def recover(self, fault_id: str, trial: int, injection_result: dict) -> dict:
        """
        Recover from a fault injection.

        Args:
            fault_id: e.g. "F1"
            trial: trial number
            injection_result: dict returned by FaultInjector.inject()
        """
        logger.info("Recovering from %s trial %d...", fault_id, trial)
        recoverer = self._recoverers.get(fault_id)
        if not recoverer:
            return self._full_reset()

        result = recoverer(trial, injection_result)
        # Clean up failed/evicted pods before waiting
        self._cleanup_failed_pods()
        # Only node-level network faults need a namespace-wide restart to flush
        # stale netem state. Restarting every deployment after resource faults
        # creates unrelated rollout state and can hide an incomplete restore.
        if fault_id in {"F11", "F12"}:
            self._restart_all_deployments()
        # Wait for pods to stabilize
        self._wait_for_healthy()
        # Verify all service endpoints have at least one ready address
        ep_ok, ep_issues = self._verify_endpoints()
        if not ep_ok:
            logger.warning("Endpoint verification issues: %s — retrying after 30s", ep_issues)
            time.sleep(30)
            ep_ok, ep_issues = self._verify_endpoints()
            if not ep_ok:
                logger.error("Endpoint verification still failing: %s", ep_issues)

        # Comprehensive verification (100% restoration guarantee)
        from scripts.stabilize.health_verify import comprehensive_health_check
        ok, issues = comprehensive_health_check(max_retries=3, retry_delay=30)
        if not ok:
            logger.error("Comprehensive health check FAILED: %s — attempting full reset", issues)
            self._full_reset()
            self._wait_for_healthy(timeout=300)
            ok2, issues2 = comprehensive_health_check(max_retries=2, retry_delay=20)
            if not ok2:
                logger.error("CRITICAL: Cluster not fully restored after full reset: %s", issues2)
                result["health_check_passed"] = False
                result["remaining_issues"] = issues2
                return result
        result["health_check_passed"] = True
        return result

    def _full_reset(self) -> dict:
        """Re-apply manifests and remove every known fault NetworkPolicy.

        Applying the Boutique manifest cannot delete an unowned policy.  A
        coordinator/host crash during F6 can therefore survive into the next
        incident unless the bounded, known fault names are removed here.
        """
        logger.info("Full reset: re-applying original manifests")
        for name in F6_POLICY_NAMES.values():
            kubectl_delete("networkpolicy", name)
        result = kubectl("apply", "-f", ORIGINAL_MANIFEST, namespace=NAMESPACE)
        deployments = kubectl_get_json("deployment", namespace=NAMESPACE).get("items", [])
        for deployment in deployments:
            name = deployment.get("metadata", {}).get("name")
            containers = (
                deployment.get("spec", {}).get("template", {}).get("spec", {})
                .get("containers", [])
            )
            if not isinstance(name, str) or not isinstance(containers, list):
                continue
            for index, container in enumerate(containers):
                if isinstance(container, dict) and container.get("command") == F2_CRASH_COMMAND:
                    kubectl_patch(
                        "deployment", name,
                        [{"op": "remove", "path": f"/spec/template/spec/containers/{index}/command"}],
                        patch_type="json",
                    )
        desired_services = {
            document["metadata"]["name"]: document.get("spec", {})
            for document in yaml.safe_load_all(Path(ORIGINAL_MANIFEST).read_text())
            if isinstance(document, dict)
            and document.get("kind") == "Service"
            and isinstance(document.get("metadata", {}).get("name"), str)
        }
        for name, desired in desired_services.items():
            current = kubectl_get_json("service", name, namespace=NAMESPACE).get("spec", {})
            patch = []
            for field in ("selector", "ports"):
                if field in desired and current.get(field) != desired[field]:
                    patch.append({
                        "op": "replace" if field in current else "add",
                        "path": f"/spec/{field}",
                        "value": desired[field],
                    })
            if patch:
                kubectl_patch("service", name, patch, patch_type="json")
        return {"action": "full_reset", "output": result}

    def _wait_for_healthy(self, timeout: int = 300, min_pods: int = 12):
        """Wait until all deployments available AND running pod count >= min_pods."""
        logger.info("Waiting for boutique pods to stabilize...")
        start = time.time()
        while time.time() - start < timeout:
            # Check deployments
            output = kubectl(
                "get", "deployments", "-o",
                "jsonpath={.items[*].status.conditions[?(@.type=='Available')].status}",
            )
            deploys_ok = output and all(s == "True" for s in output.split())

            # Check running pod count
            pod_output = kubectl(
                "get", "pods", "--field-selector=status.phase=Running",
                "--no-headers",
            )
            running_count = len([l for l in pod_output.strip().split("\n") if l.strip()]) if pod_output else 0

            if deploys_ok and running_count >= min_pods:
                logger.info(
                    "All deployments healthy, %d pods running (%.0fs)",
                    running_count, time.time() - start,
                )
                return True
            logger.info(
                "Stabilizing... deploys_ok=%s, running_pods=%d/%d (%.0fs)",
                deploys_ok, running_count, min_pods, time.time() - start,
            )
            time.sleep(10)
        logger.warning("Timeout waiting for healthy state after %ds", timeout)
        return False

    def _cleanup_failed_pods(self):
        """Delete Failed/Evicted pods to prevent accumulation."""
        for phase in ["Failed", "Succeeded"]:
            try:
                output = kubectl("delete", "pods", f"--field-selector=status.phase={phase}")
                if output and "deleted" in output:
                    logger.info("Cleaned up %s pods: %s", phase, output.strip())
            except Exception as e:
                logger.warning("Failed to cleanup %s pods: %s", phase, e)

    def _restart_all_deployments(self):
        """Rollout restart all deployments to flush stale network state (e.g., tc netem residuals)."""
        try:
            deployments = kubectl("get", "deployments", "-o", "name", namespace=NAMESPACE)
            for deployment in deployments.splitlines():
                if deployment.strip():
                    output = kubectl(
                        "rollout", "restart", deployment.strip(), namespace=NAMESPACE
                    )
                    logger.info(
                        "Rollout restart %s: %s",
                        deployment.strip(), (output or "").strip(),
                    )
        except Exception as e:
            logger.warning("Failed to rollout restart deployments: %s", e)

    def _verify_endpoints(self) -> tuple[bool, list[str]]:
        """Verify all services in NAMESPACE have at least one ready endpoint address."""
        issues = []
        try:
            ep_json = kubectl_get_json("endpoints", namespace=NAMESPACE)
            items = ep_json.get("items", []) if ep_json else []
            for ep in items:
                name = ep.get("metadata", {}).get("name", "")
                subsets = ep.get("subsets", [])
                ready_count = sum(
                    len(s.get("addresses", [])) for s in (subsets or [])
                )
                if ready_count == 0:
                    issues.append(f"endpoint/{name}: 0 ready addresses")
            if issues:
                logger.warning("Endpoint issues: %s", issues)
                return False, issues
        except Exception as e:
            logger.warning("Endpoint verification error: %s", e)
            return False, [str(e)]
        return True, []

    # ── Per-fault recovery ─────────────────────────────────────────

    def _recover_f1(self, trial: int, ctx: dict) -> dict:
        """Restore exact sealed memory resources rather than relying on revision history."""
        target = ctx.get("target_service", "")
        container = ctx.get("container_name", "")
        original_limit = ctx.get("original_limit", "")
        original_request = ctx.get("original_request", "")
        if not all((target, container, original_limit, original_request)):
            raise RuntimeError("F1 recovery receipt is incomplete")
        kubectl(
            "set", "resources", f"deployment/{target}",
            f"--containers={container}",
            f"--limits=memory={original_limit}",
            f"--requests=memory={original_request}",
        )
        kubectl("rollout", "status", f"deployment/{target}", "--timeout=120s", timeout=150)
        deployment = kubectl_get_json("deployment", target)
        containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        current = next((item for item in containers if item.get("name") == container), None)
        resources = (current or {}).get("resources", {})
        if (
            resources.get("limits", {}).get("memory") != original_limit
            or resources.get("requests", {}).get("memory") != original_request
        ):
            raise RuntimeError("F1 desired memory state was not exactly restored")
        return {"action": "restore_memory_resources", "target": target}

    def _recover_f2(self, trial: int, ctx: dict) -> dict:
        """Remove command override → rollout undo."""
        target = ctx.get("target_service", "")
        kubectl("rollout", "undo", f"deployment/{target}")
        kubectl("rollout", "status", f"deployment/{target}", "--timeout=120s", timeout=150)
        return {"action": "rollout_undo", "target": target}

    def _recover_f3(self, trial: int, ctx: dict) -> dict:
        """Restore correct image → rollout undo."""
        target = ctx.get("target_service", "")
        kubectl("rollout", "undo", f"deployment/{target}")
        kubectl("rollout", "status", f"deployment/{target}", "--timeout=120s", timeout=150)
        return {"action": "rollout_undo", "target": target}

    def _recover_f4(self, trial: int, ctx: dict) -> dict:
        """Restore node health."""
        node = ctx.get("node", next(iter(WORKER_NODES)))
        recovery_commands = {
            1: [
                "sudo systemctl start kubelet",
            ],
            2: [
                "sudo iptables -D OUTPUT -p tcp --dport 6443 -j DROP",
            ],
            3: [
                None,
            ],
            4: [
                "sudo rm -f /tmp/diskfill",
            ],
            5: [
                "sudo systemctl start containerd",
                "sudo systemctl restart kubelet",
            ],
        }

        if trial == 3:
            return self._recover_f4_memory_stress(node, ctx)
        if trial == 4:
            return self._recover_f4_diskfill(node, ctx)

        commands = recovery_commands.get(trial, ["sudo systemctl start kubelet"])
        outputs = []
        for cmd in commands:
            outputs.append(ssh_node(node, cmd))

        # Uncordon node
        kubectl("uncordon", node, namespace="")
        time.sleep(30)  # Wait for node to rejoin

        return {"action": "restore_node", "node": node, "outputs": outputs}

    def _recover_f4_diskfill(self, node: str, ctx: dict) -> dict:
        required_numbers = (
            "nodefs_device", "nodefs_capacity_bytes",
            "nodefs_pre_available_bytes",
        )
        nonce = ctx.get("diskfill_nonce")
        expected_work = (
            f"{F4_T4_WORK_PREFIX}{nonce}" if isinstance(nonce, str) else ""
        )
        context_work_inode = ctx.get("diskfill_work_inode", 0)
        if (
            node != F4_T4_NODE_NAME
            or ctx.get("diskfill_preexisting") is not False
            or not isinstance(nonce, str) or len(nonce) != 32
            or any(c not in "0123456789abcdef" for c in nonce)
            or ctx.get("diskfill_file") != f"{expected_work}/diskfill"
            or ctx.get("diskfill_receipt_file") != f"{expected_work}/receipt"
            or ctx.get("diskfill_work_dir") != expected_work
            or ctx.get("nodefs_path") != F4_T4_NODEFS_PATH
            or not isinstance(ctx.get("node_uid_before"), str)
            or not ctx.get("node_uid_before")
            or ctx.get("node_ready_before") != "True"
            or ctx.get("node_disk_pressure_before") != "False"
            or ctx.get("nodefs_target_available_percent")
            != F4_T4_TARGET_AVAILABLE_PERCENT
            or any(
                isinstance(ctx.get(name), bool)
                or not isinstance(ctx.get(name), int)
                or ctx[name] <= 0
                for name in required_numbers
            )
            or isinstance(context_work_inode, bool)
            or not isinstance(context_work_inode, int)
            or context_work_inode < 0
        ):
            raise RuntimeError("F4 diskfill recovery receipt is incomplete")

        def observed_node_conditions():
            observed = kubectl_get_json("node", node, namespace="")
            metadata = (
                observed.get("metadata", {})
                if isinstance(observed, dict) else {}
            )
            raw_conditions = (
                observed.get("status", {}).get("conditions")
                if isinstance(observed, dict) else None
            )
            ready = (
                [item.get("status") for item in raw_conditions
                 if isinstance(item, dict) and item.get("type") == "Ready"]
                if isinstance(raw_conditions, list) else []
            )
            disk = (
                [item.get("status") for item in raw_conditions
                 if isinstance(item, dict) and item.get("type") == "DiskPressure"]
                if isinstance(raw_conditions, list) else []
            )
            if (
                not isinstance(observed, dict)
                or observed.get("kind") != "Node"
                or metadata.get("name") != node
                or metadata.get("uid") != ctx["node_uid_before"]
                or len(ready) != 1
                or ready[0] not in {"True", "False", "Unknown"}
                or len(disk) != 1
                or disk[0] not in {"True", "False", "Unknown"}
            ):
                return None
            return ready[0], disk[0]

        command = (
            "sudo sh -c 'set -eu; "
            f"nonce={nonce}; nodefs={F4_T4_NODEFS_PATH}; parent={F4_T4_PARENT_DIR}; "
            f"work={expected_work}; file={expected_work}/diskfill; "
            f"receipt={expected_work}/receipt; "
            f"sealed_device={ctx['nodefs_device']}; "
            f"sealed_capacity={ctx['nodefs_capacity_bytes']}; "
            "test \"$(stat -c %d \"$nodefs\")\" = \"$sealed_device\"; "
            "set -- $(stat -f -c \"%S %b %a\" \"$nodefs\"); "
            "current_capacity=$(( $1 * $2 )); current_available=$(( $1 * $3 )); "
            "test \"$current_capacity\" = \"$sealed_capacity\"; "
            "if test ! -e \"$work\"; then "
            "test $(( current_available * 100 )) -ge $(( sealed_capacity * 10 )); "
            "printf \"__V23_DISK_RECOVERY__=already-absent\\n"
            "__V23_DISK_RECOVERY_CAPACITY__=%s\\n"
            "__V23_DISK_RECOVERY_AVAILABLE__=%s\\n\" "
            "\"$current_capacity\" \"$current_available\"; exit 0; fi; "
            "test -d \"$work\"; test \"$(stat -c %d \"$work\")\" = \"$sealed_device\"; "
            "test \"$(stat -c %u \"$work\")\" = 0; "
            "test \"$(stat -c %a \"$work\")\" = 700; "
            "live_work_inode=$(stat -c %i \"$work\"); "
            f"if test {context_work_inode} -gt 0; then "
            f"test \"$live_work_inode\" = {context_work_inode}; fi; "
            "if test -f \"$receipt\"; then "
            "set -- $(cat \"$receipt\"); schema=$1; rnonce=$2; rdevice=$3; "
            "rwork_inode=$4; rcapacity=$5; rpre=$6; rtarget=$7; "
            "test \"$schema\" = intent -o \"$schema\" = post; "
            "test \"$rnonce\" = \"$nonce\"; "
            "test \"$rdevice\" = \"$sealed_device\"; "
            "test \"$rwork_inode\" = \"$live_work_inode\"; "
            "test \"$rcapacity\" = \"$sealed_capacity\"; "
            f"test \"$rtarget\" = {F4_T4_TARGET_AVAILABLE_PERCENT}; "
            "if test \"$schema\" = post; then "
            "test $# -eq 12; sealed_file_inode=$9; "
            "sealed_file_size=${10}; sealed_file_blocks=${11}; "
            "test -f \"$file\"; "
            "test \"$(stat -c %i \"$file\")\" = \"$sealed_file_inode\"; "
            "test \"$(stat -c %s \"$file\")\" = \"$sealed_file_size\"; "
            "test \"$(stat -c %b \"$file\")\" = \"$sealed_file_blocks\"; "
            "else test $# -eq 7; fi; "
            "else "
            "find \"$work\" -mindepth 1 -maxdepth 1 "
            "! -name diskfill ! -name \"receipt.tmp.*\" | grep -q . && exit 124 || true; "
            "fi; "
            "find \"$work\" -mindepth 1 -maxdepth 1 "
            "! -name diskfill ! -name receipt ! -name \"receipt.tmp.*\" | "
            "grep -q . && exit 125 || true; "
            "rm -f \"$file\" \"$receipt\" \"$receipt\".tmp.*; "
            "rmdir \"$work\"; sync -f \"$parent\"; "
            "test ! -e \"$work\"; "
            "test \"$(stat -c %d \"$nodefs\")\" = \"$sealed_device\"; "
            "set -- $(stat -f -c \"%S %b %a\" \"$nodefs\"); "
            "live_capacity=$(( $1 * $2 )); live_available=$(( $1 * $3 )); "
            "test \"$live_capacity\" = \"$sealed_capacity\"; "
            "test $(( live_available * 100 )) -ge $(( sealed_capacity * 10 )); "
            "printf \"__V23_DISK_RECOVERY__=exact-clean\\n"
            "__V23_DISK_RECOVERY_CAPACITY__=%s\\n"
            "__V23_DISK_RECOVERY_AVAILABLE__=%s\\n\" "
            "\"$live_capacity\" \"$live_available\"'"
        )
        last_output = ""
        for attempt in range(1, F4_T4_RECOVERY_ATTEMPTS + 1):
            try:
                last_output = ssh_node(node, command)
            except (TimeoutError, subprocess.TimeoutExpired) as exc:
                last_output = type(exc).__name__
                time.sleep(F4_T4_RETRY_DELAY_SECONDS)
                continue
            status = [
                line.removeprefix("__V23_DISK_RECOVERY__=")
                for line in last_output.splitlines()
                if line.startswith("__V23_DISK_RECOVERY__=")
            ]
            capacity = [
                line.removeprefix("__V23_DISK_RECOVERY_CAPACITY__=")
                for line in last_output.splitlines()
                if line.startswith("__V23_DISK_RECOVERY_CAPACITY__=")
            ]
            available = [
                line.removeprefix("__V23_DISK_RECOVERY_AVAILABLE__=")
                for line in last_output.splitlines()
                if line.startswith("__V23_DISK_RECOVERY_AVAILABLE__=")
            ]
            if (
                len(status) == len(capacity) == len(available) == 1
                and status[0] in {"exact-clean", "already-absent"}
                and capacity[0].isdigit() and available[0].isdigit()
                and int(capacity[0]) == ctx["nodefs_capacity_bytes"]
                and int(available[0]) * 100
                >= int(capacity[0]) * 10
            ):
                node_conditions = observed_node_conditions()
                if node_conditions is None:
                    last_output = "F4 diskfill recovery node observation malformed"
                    time.sleep(F4_T4_RETRY_DELAY_SECONDS)
                    continue
                kubelet_restarted = False
                condition_check_attempts = 1
                if node_conditions != ("True", "False"):
                    try:
                        restart_output = ssh_node(
                            node,
                            "sudo sh -c 'set -eu; systemctl restart kubelet; "
                            "systemctl is-active --quiet kubelet; "
                            "echo __V23_KUBELET_RESTART__=verified'",
                        )
                    except (TimeoutError, subprocess.TimeoutExpired) as exc:
                        last_output = type(exc).__name__
                        time.sleep(F4_T4_RETRY_DELAY_SECONDS)
                        continue
                    if restart_output.splitlines().count(
                        "__V23_KUBELET_RESTART__=verified"
                    ) != 1:
                        last_output = restart_output
                        time.sleep(F4_T4_RETRY_DELAY_SECONDS)
                        continue
                    kubelet_restarted = True
                    condition_green = False
                    for condition_check_attempts in range(
                        1, F4_T4_CONDITION_POLL_ATTEMPTS + 1
                    ):
                        if observed_node_conditions() == ("True", "False"):
                            condition_green = True
                            break
                        if (
                            condition_check_attempts
                            < F4_T4_CONDITION_POLL_ATTEMPTS
                        ):
                            time.sleep(F4_T4_RETRY_DELAY_SECONDS)
                    if not condition_green:
                        raise RuntimeError(
                            "F4 diskfill node condition did not become GREEN "
                            "after one kubelet restart"
                        )
                kubectl("uncordon", node, namespace="")
                time.sleep(30)
                return {
                    "action": "restore_node_diskfill",
                    "node": node,
                    "diskfill_cleanup_verified": True,
                    "kubelet_restarted": kubelet_restarted,
                    "condition_check_attempts": condition_check_attempts,
                    "attempts": attempt,
                }
            time.sleep(F4_T4_RETRY_DELAY_SECONDS)
        raise RuntimeError(
            "F4 diskfill exact recovery did not reach the node: "
            + last_output[-200:]
        )

    def _recover_f4_memory_stress(self, node: str, ctx: dict) -> dict:
        """Retry an exact pidfile-bound stress cleanup until the node answers."""
        if (
            node != F4_T3_NODE_NAME
            or
            ctx.get("stress_ng_preexisting") is not False
            or ctx.get("stress_receipt_file") != F4_T3_STRESS_RECEIPT_FILE
            or isinstance(ctx.get("stress_vm_workers"), bool)
            or not isinstance(ctx.get("stress_vm_workers"), int)
            or ctx.get("stress_vm_workers") != F4_T3_STRESS_VM_WORKERS
        ):
            raise RuntimeError("F4 memory recovery receipt is incomplete")
        pid = ctx.get("stress_ng_pid")
        start_ticks = ctx.get("stress_ng_start_ticks")
        expected_pid = str(pid) if isinstance(pid, int) and pid > 1 else ""
        expected_start = (
            str(start_ticks) if isinstance(start_ticks, int) and start_ticks > 0 else ""
        )
        command = (
            "sudo sh -c 'set -eu; "
            f"receipt={F4_T3_STRESS_RECEIPT_FILE}; "
            "if [ ! -s \"$receipt\" ]; then "
            "if pgrep '^stress-ng' >/dev/null; then "
            "echo __V23_STRESS_RECOVERY__=awaiting-unsealed; exit 0; fi; "
            f"rm -f \"$receipt\" \"$receipt\".tmp.* {F4_T3_STRESS_LOG_FILE}; "
            "echo __V23_STRESS_RECOVERY__=no-receipt-no-process; exit 0; fi; "
            "read pid sealed_start sealed_hash extra <\"$receipt\"; "
            "case \"$pid\" in *[!0-9]*|\"\") exit 41;; esac; "
            "case \"$sealed_start\" in *[!0-9]*|\"\") exit 45;; esac; "
            "case \"$sealed_hash\" in *[!0-9a-f]*|\"\") exit 46;; esac; "
            "test ${#sealed_hash} -eq 64; test -z \"${extra:-}\"; "
            f"if [ -n \"{expected_pid}\" ] && [ \"$pid\" != \"{expected_pid}\" ]; "
            "then echo __V23_STRESS_RECOVERY__=identity-mismatch; exit 42; fi; "
            f"if [ -n \"{expected_start}\" ] && [ \"$sealed_start\" != \"{expected_start}\" ]; "
            "then echo __V23_STRESS_RECOVERY__=identity-mismatch; exit 43; fi; "
            "if [ -r /proc/$pid/stat ]; then "
            "start=$(awk \"{print \\$22}\" /proc/$pid/stat); "
            "if [ \"$start\" != \"$sealed_start\" ]; "
            "then echo __V23_STRESS_RECOVERY__=identity-mismatch; exit 43; fi; "
            "live_hash=$(sha256sum /proc/$pid/cmdline | awk \"{print \\$1}\"); "
            "if [ \"$live_hash\" != \"$sealed_hash\" ]; then "
            "echo __V23_STRESS_RECOVERY__=identity-mismatch; exit 47; fi; "
            "cmd=$(tr \"\\000\" \" \" </proc/$pid/cmdline); "
            f"case \"$cmd\" in *\"stress-ng --vm {F4_T3_STRESS_VM_WORKERS} "
            f"--vm-bytes {F4_T3_STRESS_BYTES} "
            f"--vm-keep --timeout {F4_T3_STRESS_TIMEOUT_SECONDS}s\"*) ;; *) "
            "echo __V23_STRESS_RECOVERY__=identity-mismatch; exit 44;; esac; "
            "children=$(pgrep -P \"$pid\" || true); "
            "if [ -n \"$children\" ]; then kill -9 $children 2>/dev/null || true; fi; "
            "kill -9 \"$pid\" 2>/dev/null || true; "
            "fi; "
            "if pgrep '^stress-ng' >/dev/null; then "
            "echo __V23_STRESS_RECOVERY__=awaiting-residual; exit 0; fi; "
            f"rm -f \"$receipt\" \"$receipt\".tmp.* {F4_T3_STRESS_LOG_FILE}; "
            "echo __V23_STRESS_RECOVERY__=exact-clean'"
        )
        outputs = []
        for _ in range(30):
            try:
                output = ssh_node(node, command, timeout=8)
            except Exception as exc:
                output = f"ssh-retry:{type(exc).__name__}"
            outputs.append(output)
            if "__V23_STRESS_RECOVERY__=identity-mismatch" in output:
                raise RuntimeError("F4 memory stress recovery identity mismatch")
            if any(marker in output for marker in (
                "__V23_STRESS_RECOVERY__=exact-clean",
                "__V23_STRESS_RECOVERY__=no-receipt-no-process",
            )):
                kubectl("uncordon", node, namespace="")
                time.sleep(30)
                return {
                    "action": "restore_node_memory_stress",
                    "node": node,
                    "stress_cleanup_verified": True,
                    "attempts": len(outputs),
                    "outputs": outputs,
                }
            time.sleep(5)
        raise RuntimeError("F4 memory stress recovery did not reach the node")

    def _recover_f5(self, trial: int, ctx: dict) -> dict:
        """Delete faulty PVC/PV resources."""
        if trial == 1:
            kubectl_delete("pvc", "redis-cart-fault")
        elif trial == 2:
            kubectl_delete("pvc", "prometheus-fault", namespace="monitoring")
            kubectl_delete("pv", "prometheus-capacity-probe-pv", namespace="")
        elif trial == 3:
            kubectl_delete("pvc", "storage-probe-pvc")
            kubectl(
                "scale", "deployment", "local-path-provisioner",
                "--replicas=1", namespace="local-path-storage",
            )
        elif trial == 4:
            kubectl_delete("pvc", "redis-cart-rwx")
        elif trial == 5:
            kubectl_delete("pod", "grafana-storage-probe", namespace="monitoring")
            kubectl_delete("pvc", "grafana-fault-pvc", namespace="monitoring")
            kubectl_delete("pv", "grafana-fault-pv", namespace="")
        return {"action": "cleanup_pvc", "trial": trial}

    def _recover_f6(self, trial: int, ctx: dict) -> dict:
        """Delete injected NetworkPolicies."""
        name = F6_POLICY_NAMES.get(trial, "")
        if name:
            kubectl_delete("networkpolicy", name)
        return {"action": "delete_network_policy", "name": name}

    def _recover_f7(self, trial: int, ctx: dict) -> dict:
        """Restore the exact pre-injection CPU resources and verify desired state."""
        target = ctx.get("target_service", "")
        container = ctx.get("container_name", "")
        original_limit = ctx.get("original_cpu_limit", "")
        original_request = ctx.get("original_cpu_request", "")
        if not all((target, container, original_limit, original_request)):
            raise RuntimeError("F7 recovery receipt is incomplete")
        kubectl(
            "set", "resources", "deployment", target,
            f"--containers={container}",
            f"--limits=cpu={original_limit}",
            f"--requests=cpu={original_request}",
        )
        kubectl("rollout", "status", f"deployment/{target}", "--timeout=120s", timeout=150)
        deployment = kubectl_get_json("deployment", target)
        metadata = deployment.get("metadata", {})
        spec = deployment.get("spec", {})
        status = deployment.get("status", {})
        current = next(
            (
                item for item in spec.get("template", {}).get("spec", {}).get("containers", [])
                if item.get("name") == container
            ),
            None,
        )
        resources = (current or {}).get("resources", {})
        replicas = spec.get("replicas", 0)
        restored = all((
            current is not None,
            resources.get("limits", {}).get("cpu") == original_limit,
            resources.get("requests", {}).get("cpu") == original_request,
            status.get("observedGeneration") == metadata.get("generation"),
            status.get("updatedReplicas", 0) == replicas,
            status.get("readyReplicas", 0) == replicas,
            status.get("availableReplicas", 0) == replicas,
        ))
        if not restored:
            raise RuntimeError("F7 desired CPU state was not fully restored")
        return {
            "action": "restore_cpu_resources",
            "target": target,
            "container_name": container,
            "cpu_limit": original_limit,
            "cpu_request": original_request,
            "desired_state_verified": True,
        }

    def _recover_f8(self, trial: int, ctx: dict) -> dict:
        """Fix service configuration."""
        if trial in (1, 2, 5):
            target = ctx.get("target_service")
            original_ports = ctx.get("original_service_ports")
            if not isinstance(target, str) or not isinstance(original_ports, list):
                raise RuntimeError("F8 service recovery receipt is incomplete")
            service = kubectl_get_json("service", target, namespace=NAMESPACE)
            spec = service.get("spec", {})
            patch = [{
                "op": "replace" if "ports" in spec else "add",
                "path": "/spec/ports",
                "value": original_ports,
            }]
            if trial == 1:
                selector = ctx.get("original_service_selector")
                if not isinstance(selector, dict):
                    raise RuntimeError("F8 selector recovery receipt is incomplete")
                patch.append({
                    "op": "replace" if "selector" in spec else "add",
                    "path": "/spec/selector",
                    "value": selector,
                })
            kubectl_patch("service", target, patch, patch_type="json")
        elif trial == 3:
            # Rollout undo to restore labels
            kubectl("rollout", "undo", "deployment/paymentservice")
            kubectl("rollout", "status", "deployment/paymentservice", "--timeout=120s", timeout=150)
        elif trial == 4:
            target = ctx.get("target_service", "shippingservice")
            container_name = ctx.get("container_name")
            original_probe = ctx.get("original_readiness_probe")
            if not isinstance(container_name, str) or not isinstance(original_probe, dict):
                raise RuntimeError("F8 trial 4 recovery receipt is incomplete")
            deployment = kubectl_get_json("deployment", target, namespace=NAMESPACE)
            containers = (
                deployment.get("spec", {}).get("template", {}).get("spec", {})
                .get("containers", [])
            )
            indexes = [
                index for index, container in enumerate(containers)
                if isinstance(container, dict) and container.get("name") == container_name
            ]
            if len(indexes) != 1:
                raise RuntimeError("F8 trial 4 recovery container is ambiguous")
            kubectl_patch(
                "deployment", target,
                [{
                    "op": "replace",
                    "path": f"/spec/template/spec/containers/{indexes[0]}/readinessProbe",
                    "value": original_probe,
                }],
                patch_type="json",
            )
            kubectl("rollout", "status", f"deployment/{target}", "--timeout=120s", timeout=150)
        return {"action": "restore_service", "trial": trial}

    def _recover_f9(self, trial: int, ctx: dict) -> dict:
        """Fix secrets/configmaps."""
        target = ctx.get("target_service", "")
        if trial == 1:
            container_name = ctx.get("container_name")
            original_env = ctx.get("original_env")
            if not isinstance(container_name, str) or not isinstance(original_env, list):
                raise RuntimeError("F9 trial 1 recovery receipt is incomplete")
            deployment = kubectl_get_json("deployment", target, namespace=NAMESPACE)
            containers = (
                deployment.get("spec", {}).get("template", {}).get("spec", {})
                .get("containers", [])
            )
            indexes = [
                index for index, container in enumerate(containers)
                if isinstance(container, dict) and container.get("name") == container_name
            ]
            if len(indexes) != 1:
                raise RuntimeError("F9 trial 1 recovery container is ambiguous")
            kubectl_patch(
                "deployment", target,
                [{
                    "op": "replace",
                    "path": f"/spec/template/spec/containers/{indexes[0]}/env",
                    "value": original_env,
                }],
                patch_type="json",
            )
        else:
            kubectl("rollout", "undo", f"deployment/{target}")
        # Clean up any dummy secrets
        kubectl_delete("secret", "checkout-secret-bad")
        kubectl("rollout", "status", f"deployment/{target}", "--timeout=120s", timeout=150)
        return {"action": "rollout_undo_and_cleanup", "target": target}

    def _recover_f10(self, trial: int, ctx: dict) -> dict:
        """Remove ResourceQuota/LimitRange."""
        if trial <= 4:
            names = {
                1: "fault-quota",
                2: "fault-quota-cpu",
                3: "fault-quota-mem",
                4: "fault-quota-svc",
            }
            kubectl_delete("resourcequota", names.get(trial, "fault-quota"))
        elif trial == 5:
            kubectl_delete("limitrange", "fault-limitrange")

        return {"action": "delete_quota", "trial": trial}

    # ── F11: Network Delay ──────────────────────────────────────

    def _recover_f11_network_delay(self, trial: int, ctx: dict) -> dict:
        """Remove tc netem delay rules."""
        node_name = ctx.get("node", next(iter(WORKER_NODES)))
        iface = ctx.get("interface", "vmbr0")  # 재구축 랩 노드망 인터페이스(옛 ens18 → vmbr0)
        output = ssh_node(node_name, f"sudo tc qdisc del dev {iface} root 2>/dev/null; echo ok", timeout=15)
        logger.info("F11 recovered: removed netem delay on %s", node_name)
        return {"action": "remove_netem_delay", "node": node_name, "output": output}

    # ── F12: Network Loss ───────────────────────────────────────

    def _recover_f12_network_loss(self, trial: int, ctx: dict) -> dict:
        """Remove tc netem loss rules."""
        node_name = ctx.get("node", next(iter(WORKER_NODES)))
        iface = ctx.get("interface", "vmbr0")  # 재구축 랩 노드망 인터페이스(옛 ens18 → vmbr0)
        output = ssh_node(node_name, f"sudo tc qdisc del dev {iface} root 2>/dev/null; echo ok", timeout=15)
        logger.info("F12 recovered: removed netem loss on %s", node_name)
        return {"action": "remove_netem_loss", "node": node_name, "output": output}
