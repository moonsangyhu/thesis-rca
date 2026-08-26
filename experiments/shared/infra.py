"""Infrastructure checks: preflight, health, port-forward management."""
import logging
import os
import shutil
import signal
import subprocess
import time

logger = logging.getLogger(__name__)

KUBECONFIG = os.environ.get("KUBECONFIG", os.path.expanduser("~/.kube/config-k8s-lab"))


def _executable(name: str) -> str:
    """Return an absolute executable path when available for posix_spawn."""
    return shutil.which(name) or name


def _run_kubectl_check(
    command: list[str], *, timeout_seconds: int = 30, timeout_retries: int = 1
) -> subprocess.CompletedProcess[str] | None:
    """Run a read-only kubectl check with bounded transient retry."""
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or timeout_seconds < 1
    ):
        raise ValueError("kubectl check timeout must be a positive integer")
    if (
        isinstance(timeout_retries, bool)
        or not isinstance(timeout_retries, int)
        or timeout_retries not in (0, 1)
    ):
        raise ValueError("kubectl check timeout retries must be zero or one")
    safe_command = [_executable(command[0]), *command[1:]]
    for attempt in range(timeout_retries + 1):
        try:
            process = subprocess.Popen(
                safe_command,
                env={**os.environ, "KUBECONFIG": KUBECONFIG},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # Avoid fork/exec after local ML native threads initialize.
                # These read-only kubectl checks do not create child processes.
                close_fds=False,
            )
        except Exception:
            return None
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            process.communicate()
            if attempt < timeout_retries:
                continue
            return None
        except BaseException:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            process.communicate()
            raise
        return subprocess.CompletedProcess(
            safe_command, process.returncode, stdout=stdout, stderr=stderr
        )
    return None


def _check_port(port: int) -> bool:
    """Check if a local port is responding."""
    import urllib.request
    try:
        url = f"http://localhost:{port}/ready" if port == 3100 else f"http://localhost:{port}/api/v1/status/runtimeinfo"
        req = urllib.request.urlopen(url, timeout=5)
        return req.status == 200
    except Exception:
        return False


def _restart_port_forward(namespace: str, service: str, port: int) -> bool:
    """Kill existing port-forward and restart."""
    listeners = subprocess.run(
        [_executable("lsof"), "-tiTCP:%d" % port, "-sTCP:LISTEN"],
        text=True, capture_output=True, check=False, close_fds=False,
    )
    for value in listeners.stdout.splitlines():
        if value.isdigit():
            try:
                os.kill(int(value), signal.SIGTERM)
            except ProcessLookupError:
                pass
    time.sleep(1)
    subprocess.Popen(
        [_executable("kubectl"), "port-forward", "-n", namespace,
         f"svc/{service}", f"{port}:{port}"],
        env={**os.environ, "KUBECONFIG": KUBECONFIG},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=False,
    )
    time.sleep(3)
    if _check_port(port):
        logger.info("Port-forward %s:%d restarted successfully", service, port)
        return True
    logger.error("Port-forward %s:%d restart FAILED", service, port)
    return False


def preflight_check() -> bool:
    """Verify all infrastructure components before experiment starts."""
    logger.info("=" * 60)
    logger.info("PREFLIGHT CHECK")
    logger.info("=" * 60)
    ok = True

    # 1. kubectl connectivity
    r = _run_kubectl_check(
        ["kubectl", "get", "nodes", "--no-headers"]
    )
    if r is not None and r.returncode == 0:
        node_count = len(r.stdout.strip().split("\n"))
        logger.info("[OK] kubectl: %d nodes reachable", node_count)
    else:
        logger.error("[FAIL] kubectl not reachable — check SSH tunnel")
        ok = False

    # 2. Boutique pods
    r = _run_kubectl_check(
        ["kubectl", "get", "pods", "-n", "boutique", "--no-headers",
         "--field-selector=status.phase=Running"]
    )
    if r is not None and r.returncode == 0:
        pod_count = len([line for line in r.stdout.strip().split("\n") if line.strip()])
        if pod_count >= 12:
            logger.info("[OK] boutique: %d pods running", pod_count)
        else:
            logger.error("[FAIL] boutique: only %d pods running (need >= 12)", pod_count)
            ok = False
    else:
        logger.error("[FAIL] cannot list boutique pods")
        ok = False

    # 3. Prometheus
    if _check_port(9090):
        logger.info("[OK] Prometheus (localhost:9090)")
    else:
        logger.warning("[WARN] Prometheus down — attempting restart...")
        if _restart_port_forward("monitoring", "kube-prometheus-stack-prometheus", 9090):
            logger.info("[OK] Prometheus recovered")
        else:
            logger.error("[FAIL] Prometheus recovery failed")
            ok = False

    # 4. Loki
    if _check_port(3100):
        logger.info("[OK] Loki (localhost:3100)")
    else:
        logger.warning("[WARN] Loki down — attempting restart...")
        if _restart_port_forward("monitoring", "loki", 3100):
            logger.info("[OK] Loki recovered")
        else:
            logger.error("[FAIL] Loki recovery failed")
            ok = False

    logger.info("=" * 60)
    if ok:
        logger.info("PREFLIGHT CHECK PASSED")
    else:
        logger.error("PREFLIGHT CHECK FAILED — fix issues before running")
    logger.info("=" * 60)
    return ok


def health_check(fault_id: str, trial: int) -> bool:
    """Quick health check before each trial. Auto-recovers port-forwards."""
    issues = []

    if not _check_port(9090):
        logger.warning("[HEALTH] Prometheus down before %s t%d — restarting...", fault_id, trial)
        if not _restart_port_forward("monitoring", "kube-prometheus-stack-prometheus", 9090):
            issues.append("Prometheus")

    if not _check_port(3100):
        logger.warning("[HEALTH] Loki down before %s t%d — restarting...", fault_id, trial)
        if not _restart_port_forward("monitoring", "loki", 3100):
            issues.append("Loki")

    # Check running pod count
    r = _run_kubectl_check(
        ["kubectl", "get", "pods", "-n", "boutique", "--no-headers",
         "--field-selector=status.phase=Running"]
    )
    if r is not None and r.returncode == 0:
        pod_count = len([line for line in r.stdout.strip().split("\n") if line.strip()])
        if pod_count < 12:
            logger.warning("[HEALTH] Only %d boutique pods running (need >= 12) before %s t%d",
                           pod_count, fault_id, trial)
            issues.append(f"pods={pod_count}/12")
    else:
        issues.append("pod-check-failed")

    if issues:
        logger.error("[HEALTH] FAILED for %s t%d: %s", fault_id, trial, ", ".join(issues))
        return False

    logger.info("[HEALTH] OK before %s t%d", fault_id, trial)
    return True
