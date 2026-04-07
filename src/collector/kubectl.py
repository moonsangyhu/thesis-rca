"""kubectl-based collector for K8s state."""
import json
import logging
import os
import subprocess
from datetime import datetime, timezone

from .config import KUBECONFIG, KUBECTL, TARGET_NAMESPACE

logger = logging.getLogger(__name__)


def _run(args: list[str], timeout: int = 30) -> str:
    """Run kubectl command and return stdout."""
    env = os.environ.copy()
    env["KUBECONFIG"] = KUBECONFIG
    cmd = [KUBECTL] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if result.returncode != 0:
            logger.warning("kubectl error: %s", result.stderr.strip())
        return result.stdout
    except subprocess.TimeoutExpired:
        logger.error("kubectl timeout: %s", " ".join(cmd))
        return ""
    except FileNotFoundError:
        logger.error("kubectl not found at %s", KUBECTL)
        return ""


class KubectlCollector:
    """Collect K8s state via kubectl for RCA analysis."""

    def __init__(self, namespace: str = TARGET_NAMESPACE):
        self.namespace = namespace

    def collect(self) -> dict:
        """Collect all kubectl-based signals."""
        return {
            "pods": self._collect_pods(),
            "events": self._collect_events(),
            "services": self._collect_services(),
            "nodes": self._collect_nodes(),
            "describe_unhealthy": self._describe_unhealthy_pods(),
        }

    def _collect_pods(self) -> list[dict]:
        """Get pod status summary."""
        output = _run([
            "get", "pods", "-n", self.namespace,
            "-o", "json",
        ])
        if not output:
            return []
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return []

        pods = []
        for item in data.get("items", []):
            meta = item.get("metadata", {})
            status = item.get("status", {})
            containers = []
            for cs in status.get("containerStatuses", []):
                c = {
                    "name": cs.get("name", ""),
                    "ready": cs.get("ready", False),
                    "restartCount": cs.get("restartCount", 0),
                    "state": list(cs.get("state", {}).keys()),
                }
                # Add terminated/waiting reason
                if "waiting" in cs.get("state", {}):
                    c["waitingReason"] = cs["state"]["waiting"].get("reason", "")
                if "terminated" in cs.get("state", {}):
                    c["terminatedReason"] = cs["state"]["terminated"].get("reason", "")
                    c["exitCode"] = cs["state"]["terminated"].get("exitCode", -1)
                # Last terminated state
                last = cs.get("lastState", {})
                if "terminated" in last:
                    c["lastTerminatedReason"] = last["terminated"].get("reason", "")
                containers.append(c)

            pods.append({
                "name": meta.get("name", ""),
                "phase": status.get("phase", "Unknown"),
                "conditions": [
                    {"type": cond["type"], "status": cond["status"]}
                    for cond in status.get("conditions", [])
                ],
                "containers": containers,
                "nodeName": item.get("spec", {}).get("nodeName", ""),
            })
        return pods

    def _collect_events(self, since_minutes: int = 10) -> list[dict]:
        """Get recent warning/error events within the time window."""
        output = _run([
            "get", "events", "-n", self.namespace,
            "--field-selector", "type!=Normal",
            "--sort-by", ".lastTimestamp",
            "-o", "json",
        ])
        if not output:
            return []
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return []

        now = datetime.now(timezone.utc)
        events = []
        for item in data.get("items", []):
            # Filter by time window to exclude stale events
            ts_str = item.get("lastTimestamp", "")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    age_minutes = (now - ts).total_seconds() / 60
                    if age_minutes > since_minutes:
                        continue
                except (ValueError, TypeError):
                    pass  # keep events with unparseable timestamps

            events.append({
                "type": item.get("type", ""),
                "reason": item.get("reason", ""),
                "message": item.get("message", ""),
                "object": item.get("involvedObject", {}).get("name", ""),
                "kind": item.get("involvedObject", {}).get("kind", ""),
                "count": item.get("count", 1),
                "lastTimestamp": ts_str,
            })
        return events[-30:]  # last 30 events

    def _collect_services(self) -> list[dict]:
        """Get service endpoint status."""
        output = _run([
            "get", "endpoints", "-n", self.namespace,
            "-o", "json",
        ])
        if not output:
            return []
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return []

        services = []
        for item in data.get("items", []):
            name = item.get("metadata", {}).get("name", "")
            subsets = item.get("subsets", [])
            ready_count = sum(
                len(s.get("addresses", [])) for s in subsets
            )
            not_ready_count = sum(
                len(s.get("notReadyAddresses", [])) for s in subsets
            )
            services.append({
                "name": name,
                "ready_endpoints": ready_count,
                "not_ready_endpoints": not_ready_count,
            })
        return services

    def _collect_nodes(self) -> list[dict]:
        """Get node status."""
        output = _run(["get", "nodes", "-o", "json"])
        if not output:
            return []
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return []

        nodes = []
        for item in data.get("items", []):
            name = item.get("metadata", {}).get("name", "")
            conditions = item.get("status", {}).get("conditions", [])
            ready = "Unknown"
            issues = []
            for c in conditions:
                if c["type"] == "Ready":
                    ready = c["status"]
                elif c["status"] == "True" and c["type"] != "Ready":
                    issues.append(c["type"])

            taints = [
                t.get("key", "") for t in item.get("spec", {}).get("taints", [])
            ]
            nodes.append({
                "name": name,
                "ready": ready,
                "issues": issues,
                "taints": taints,
            })
        return nodes

    def _describe_unhealthy_pods(self) -> list[dict]:
        """Describe pods that are not Running/Ready."""
        pods = self._collect_pods()
        unhealthy = [
            p for p in pods
            if p["phase"] != "Running"
            or any(not c["ready"] for c in p["containers"])
        ]

        descriptions = []
        for pod in unhealthy[:5]:  # limit to 5 most interesting
            output = _run([
                "describe", "pod", pod["name"],
                "-n", self.namespace,
            ])
            if output:
                # Extract key sections only
                lines = output.split("\n")
                key_sections = []
                capture = False
                for line in lines:
                    if any(s in line for s in [
                        "Status:", "Reason:", "Message:", "Events:",
                        "Conditions:", "State:", "Last State:",
                        "Warning", "Error", "BackOff",
                    ]):
                        capture = True
                    if capture:
                        key_sections.append(line)
                        if len(key_sections) > 50:
                            break

                descriptions.append({
                    "pod": pod["name"],
                    "describe_excerpt": "\n".join(key_sections[-40:]),
                })
        return descriptions
