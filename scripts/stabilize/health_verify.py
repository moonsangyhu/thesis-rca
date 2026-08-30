"""Comprehensive health verification for 100% cluster restoration between trials."""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts.fault_inject.base import kubectl, ssh_node
from scripts.fault_inject.config import WORKER_NODES
from experiments.shared.infra import _check_port

logger = logging.getLogger(__name__)

NAMESPACE = "boutique"
EXPECTED_DEPLOYMENTS = 12
DISK_THRESHOLD_PCT = 80
DISK_USAGE_MARKER = "__V23_DISK_USAGE_PCT__="
KUBELET_STATS_MAX_AGE_SECONDS = 300
SSH_DISK_PROBE_TIMEOUT_SECONDS = 5
ORIGINAL_MANIFEST = (
    Path(__file__).resolve().parents[2] / "k8s" / "app" / "online-boutique.yaml"
)


def comprehensive_health_check(
    max_retries: int = 3,
    retry_delay: int = 30,
) -> tuple[bool, list[str]]:
    """
    Verify 100% cluster restoration. Returns (ok, issues).

    Checks:
    1. All nodes Ready, no DiskPressure/MemoryPressure
    2. All 12 deployments: readyReplicas == replicas
    3. No Failed/Pending/CrashLoopBackOff pods
    4. No residual NetworkPolicy, ResourceQuota, LimitRange
    5. All service endpoints populated and fault-mutated Service fields exact
    6. Disk usage < 80% on all workers
    7. Prometheus and Loki functional
    """
    for attempt in range(max_retries):
        issues = _run_all_checks()
        if not issues:
            logger.info("Comprehensive health check PASSED (attempt %d)", attempt + 1)
            return True, []
        logger.warning(
            "Health check attempt %d/%d failed: %s",
            attempt + 1, max_retries, issues,
        )
        if attempt < max_retries - 1:
            time.sleep(retry_delay)

    return False, issues


def _run_all_checks() -> list[str]:
    """Run all 7 checks, return list of issues (empty = all passed)."""
    issues = []
    issues.extend(_check_nodes())
    issues.extend(_check_deployments())
    issues.extend(_check_pods())
    issues.extend(_check_residuals())
    issues.extend(_check_endpoints())
    issues.extend(_check_service_specs())
    issues.extend(_check_disk_usage())
    issues.extend(_check_monitoring())
    return issues


def _check_nodes() -> list[str]:
    """Check 1: All nodes Ready, no pressure conditions."""
    issues = []
    try:
        raw = kubectl("get", "nodes", "-o", "json", namespace="")
        data = json.loads(raw)
        for node in data.get("items", []):
            name = node["metadata"]["name"]
            conditions = {c["type"]: c["status"] for c in node["status"].get("conditions", [])}
            if conditions.get("Ready") != "True":
                issues.append(f"Node {name} not Ready")
            if conditions.get("DiskPressure") == "True":
                issues.append(f"Node {name} DiskPressure")
            if conditions.get("MemoryPressure") == "True":
                issues.append(f"Node {name} MemoryPressure")
    except Exception as e:
        issues.append(f"Node check failed: {e}")
    return issues


def _check_deployments() -> list[str]:
    """Check 2: All deployments have desired == ready replicas."""
    issues = []
    try:
        raw = kubectl("get", "deployments", "-o", "json")
        data = json.loads(raw)
        items = data.get("items", [])
        if len(items) < EXPECTED_DEPLOYMENTS:
            issues.append(f"Only {len(items)} deployments (expected {EXPECTED_DEPLOYMENTS})")
        for dep in items:
            name = dep["metadata"]["name"]
            desired = dep["spec"].get("replicas", 1)
            ready = dep["status"].get("readyReplicas", 0)
            if ready != desired:
                issues.append(f"Deploy {name}: ready={ready}/{desired}")
    except Exception as e:
        issues.append(f"Deployment check failed: {e}")
    return issues


def _check_pods() -> list[str]:
    """Check 3: No Failed/Pending/CrashLoop pods."""
    issues = []
    try:
        raw = kubectl("get", "pods", "-o", "json")
        data = json.loads(raw)
        for pod in data.get("items", []):
            name = pod["metadata"]["name"]
            phase = pod["status"].get("phase", "")
            if phase in ("Failed", "Pending"):
                issues.append(f"Pod {name} phase={phase}")
                continue
            # Check container statuses for CrashLoop/ImagePull
            for cs in pod["status"].get("containerStatuses", []):
                waiting = cs.get("state", {}).get("waiting", {})
                reason = waiting.get("reason", "")
                if reason in ("CrashLoopBackOff", "ImagePullBackOff", "CreateContainerConfigError"):
                    issues.append(f"Pod {name} container={cs['name']} {reason}")
    except Exception as e:
        issues.append(f"Pod check failed: {e}")
    return issues


def _check_residuals() -> list[str]:
    """Check 4: No residual NetworkPolicy, ResourceQuota, LimitRange."""
    issues = []
    for resource in ("networkpolicy", "resourcequota", "limitrange"):
        try:
            raw = kubectl("get", resource, "--no-headers")
            count = len([l for l in raw.strip().split("\n") if l.strip()]) if raw.strip() else 0
            if count > 0:
                issues.append(f"Residual {resource}: {count}")
        except Exception:
            pass  # Resource type may not exist
    return issues


def _check_endpoints() -> list[str]:
    """Check 5: All service endpoints populated."""
    issues = []
    try:
        raw = kubectl("get", "endpoints", "-o", "json")
        data = json.loads(raw)
        for ep in data.get("items", []):
            name = ep["metadata"]["name"]
            # Skip kubernetes internal services
            if name in ("kubernetes",):
                continue
            subsets = ep.get("subsets", [])
            if not subsets:
                issues.append(f"Endpoint {name}: no subsets (0 endpoints)")
    except Exception as e:
        issues.append(f"Endpoint check failed: {e}")
    return issues


def _desired_service_specs() -> dict[str, dict]:
    return {
        document["metadata"]["name"]: document.get("spec", {})
        for document in yaml.safe_load_all(ORIGINAL_MANIFEST.read_text())
        if isinstance(document, dict)
        and document.get("kind") == "Service"
        and isinstance(document.get("metadata", {}).get("name"), str)
    }


def _normalized_ports(ports: object) -> list[dict] | None:
    if not isinstance(ports, list):
        return None
    normalized = []
    for port in ports:
        if not isinstance(port, dict):
            return None
        normalized.append({
            "name": port.get("name"),
            "port": port.get("port"),
            "targetPort": port.get("targetPort", port.get("port")),
            "protocol": port.get("protocol", "TCP"),
        })
    return normalized


def _check_service_specs() -> list[str]:
    """Reject healthy-looking endpoints whose selector/ports still carry a fault."""
    issues = []
    try:
        live = json.loads(kubectl("get", "services", "-o", "json"))
        by_name = {
            item.get("metadata", {}).get("name"): item.get("spec", {})
            for item in live.get("items", [])
        }
        for name, desired in _desired_service_specs().items():
            current = by_name.get(name)
            if current is None:
                issues.append(f"Service {name} missing")
                continue
            if current.get("selector") != desired.get("selector"):
                issues.append(f"Service {name} selector drift")
            if _normalized_ports(current.get("ports")) != _normalized_ports(
                desired.get("ports")
            ):
                issues.append(f"Service {name} ports drift")
    except Exception as exc:
        issues.append(f"Service spec check failed: {exc}")
    return issues


def _check_disk_usage() -> list[str]:
    """Check 6: Disk usage < threshold on all workers."""
    issues = []
    for node_name in WORKER_NODES:
        try:
            raw = ssh_node(
                node_name,
                "set -eu; "
                "pct=$(LC_ALL=C df -P / | "
                "awk 'NR == 2 {gsub(\"%\", \"\", $5); print $5}'); "
                "case \"$pct\" in ''|*[!0-9]*) exit 41;; esac; "
                f"printf '{DISK_USAGE_MARKER}%s\\n' \"$pct\"",
                timeout=SSH_DISK_PROBE_TIMEOUT_SECONDS,
            )
            values = [
                line.removeprefix(DISK_USAGE_MARKER)
                for line in raw.splitlines()
                if line.startswith(DISK_USAGE_MARKER)
            ]
            if (
                len(values) != 1
                or not values[0].isdigit()
                or not 0 <= int(values[0]) <= 100
            ):
                raise ValueError("disk usage marker is malformed")
            pct = int(values[0])
        except Exception as e:
            try:
                pct = _nodefs_usage_from_kubelet(node_name)
                logger.warning(
                    "SSH disk probe failed for %s (%s); using kubelet nodefs summary",
                    node_name,
                    e,
                )
            except Exception as fallback_error:
                issues.append(
                    f"{node_name} disk check failed: {e}; "
                    f"kubelet fallback failed: {fallback_error}"
                )
                continue
        if pct >= DISK_THRESHOLD_PCT:
            issues.append(f"{node_name} disk={pct}% (>={DISK_THRESHOLD_PCT}%)")
    return issues


def _nodefs_usage_from_kubelet(node_name: str) -> int:
    """Return current rootfs usage from the authenticated kubelet summary API.

    This is a read-only fallback for a transient SSH management-path outage.
    A missing, stale, or internally inconsistent summary remains a health-check
    failure; it must never be interpreted as a healthy disk by default.
    """
    raw = kubectl(
        "get", "--raw", f"/api/v1/nodes/{node_name}/proxy/stats/summary",
        namespace="",
        timeout=15,
    )
    data = json.loads(raw)
    fs = data["node"]["fs"]
    if data["node"].get("nodeName") != node_name:
        raise ValueError("node name does not match kubelet summary")
    capacity = fs["capacityBytes"]
    available = fs["availableBytes"]
    if type(capacity) is not int or type(available) is not int or capacity <= 0:
        raise ValueError("nodefs capacity/availability is invalid")
    if not 0 <= available <= capacity:
        raise ValueError("nodefs availability is outside capacity")
    observed_at = datetime.fromisoformat(fs["time"].replace("Z", "+00:00"))
    age_seconds = (datetime.now(timezone.utc) - observed_at).total_seconds()
    if age_seconds < -5 or age_seconds > KUBELET_STATS_MAX_AGE_SECONDS:
        raise ValueError("nodefs summary is stale or from the future")
    return (capacity - available) * 100 // capacity


def _check_monitoring() -> list[str]:
    """Check 7: Prometheus and Loki APIs return valid functional responses."""
    issues = []
    for name, port in [("Prometheus", 9090), ("Loki", 3100)]:
        if not _check_port(port):
            issues.append(f"{name} API (port {port}) not functional")
    return issues
