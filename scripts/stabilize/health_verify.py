"""Comprehensive health verification for 100% cluster restoration between trials."""
import json
import logging
import time

from scripts.fault_inject.base import kubectl, ssh_node

logger = logging.getLogger(__name__)

NAMESPACE = "boutique"
EXPECTED_DEPLOYMENTS = 12
DISK_THRESHOLD_PCT = 80


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
    5. All service endpoints populated
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


def _check_disk_usage() -> list[str]:
    """Check 6: Disk usage < threshold on all workers."""
    issues = []
    for node_name in ("worker01", "worker02", "worker03"):
        try:
            raw = ssh_node(node_name, "df / --output=pcent | tail -1", timeout=15)
            pct = int(raw.strip().replace("%", ""))
            if pct >= DISK_THRESHOLD_PCT:
                issues.append(f"{node_name} disk={pct}% (>={DISK_THRESHOLD_PCT}%)")
        except Exception as e:
            issues.append(f"{node_name} disk check failed: {e}")
    return issues


def _check_monitoring() -> list[str]:
    """Check 7: Prometheus and Loki responsive."""
    import socket
    issues = []
    for name, port in [("Prometheus", 9090), ("Loki", 3100)]:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            sock.close()
        except (socket.timeout, ConnectionRefusedError, OSError):
            issues.append(f"{name} (port {port}) not reachable")
    return issues
