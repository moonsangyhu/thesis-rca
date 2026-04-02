"""Build structured context from collected signals for LLM RCA."""
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RCAContext:
    """Structured context for LLM-based RCA."""
    # System A: observability signals
    pod_status_summary: str = ""
    error_events: str = ""
    metric_anomalies: str = ""
    error_logs: str = ""
    node_status: str = ""

    # System B additions: GitOps context
    gitops_status: str = ""
    git_changes: str = ""

    # System B additions: RAG knowledge
    rag_context: str = ""

    # Metadata
    fault_id: str = ""
    trial: int = 0
    system: str = ""  # "A" or "B"

    def to_system_a_context(self) -> str:
        """Format context for System A (observability only)."""
        sections = []
        if self.pod_status_summary:
            sections.append(f"## Pod Status\n{self.pod_status_summary}")
        if self.error_events:
            sections.append(f"## Kubernetes Events (Warning/Error)\n{self.error_events}")
        if self.metric_anomalies:
            sections.append(f"## Metric Anomalies\n{self.metric_anomalies}")
        if self.error_logs:
            sections.append(f"## Error Logs\n{self.error_logs}")
        if self.node_status:
            sections.append(f"## Node Status\n{self.node_status}")
        return "\n\n".join(sections)

    def to_system_b_context(self) -> str:
        """Format context for System B (+ GitOps + RAG)."""
        parts = [self.to_system_a_context()]
        if self.gitops_status:
            parts.append(f"## GitOps Status (FluxCD/ArgoCD)\n{self.gitops_status}")
        if self.git_changes:
            parts.append(f"## Recent Git Changes\n{self.git_changes}")
        if self.rag_context:
            parts.append(f"## Knowledge Base (RAG Retrieved)\n{self.rag_context}")
        return "\n\n".join(parts)

    def to_context(self) -> str:
        """Format context based on system type."""
        if self.system == "A":
            return self.to_system_a_context()
        return self.to_system_b_context()


class ContextBuilder:
    """Build RCAContext from raw collected signals."""

    def build(
        self,
        signals: dict,
        fault_id: str = "",
        trial: int = 0,
        system: str = "A",
        rag_context: str = "",
    ) -> RCAContext:
        """
        Build RCAContext from raw collector output.

        Args:
            signals: Output from SignalCollector.collect_all() or collect_observability_only()
            fault_id: e.g. "F1"
            trial: trial number
            system: "A" or "B"
            rag_context: Pre-formatted RAG context string (for System B)
        """
        ctx = RCAContext(
            fault_id=fault_id,
            trial=trial,
            system=system,
            rag_context=rag_context,
        )

        metrics = signals.get("metrics", {})
        logs = signals.get("logs", {})
        kubectl = signals.get("kubectl", {})
        gitops = signals.get("gitops", {})

        ctx.pod_status_summary = self._build_pod_summary(
            kubectl.get("pods", []),
            metrics.get("pod_status", []),
            metrics.get("container_restarts", []),
        )
        ctx.error_events = self._build_events(kubectl.get("events", []))
        ctx.metric_anomalies = self._build_metric_anomalies(metrics)
        ctx.error_logs = self._build_error_logs(logs.get("pod_logs", []))
        ctx.node_status = self._build_node_status(
            kubectl.get("nodes", []),
            metrics.get("node_status", []),
        )

        if system == "B" and gitops:
            ctx.gitops_status = self._build_gitops_status(gitops)
            ctx.git_changes = self._build_git_changes(gitops)

        return ctx

    def _build_pod_summary(
        self,
        pods: list[dict],
        pod_metrics: list[dict],
        restarts: list[dict],
    ) -> str:
        """Summarize pod status."""
        if not pods:
            return "No pod data available."

        lines = []
        for pod in pods:
            status_parts = [f"{pod['name']}: {pod['phase']}"]
            for c in pod.get("containers", []):
                if not c.get("ready"):
                    reason = c.get("waitingReason", "") or c.get("terminatedReason", "")
                    status_parts.append(
                        f"  container/{c['name']}: NOT READY"
                        f"{' (' + reason + ')' if reason else ''}"
                        f" restarts={c.get('restartCount', 0)}"
                    )
                    if c.get("lastTerminatedReason"):
                        status_parts.append(
                            f"    last terminated: {c['lastTerminatedReason']}"
                            f" (exit code {c.get('exitCode', '?')})"
                        )
            lines.append("\n".join(status_parts))

        # Add metrics-based waiting reasons not in kubectl
        metric_reasons = set()
        for m in pod_metrics:
            if "waiting_reason" in m:
                metric_reasons.add(f"{m['pod']}: {m['waiting_reason']}")
        for r in metric_reasons:
            if not any(r.split(":")[0] in line for line in lines):
                lines.append(r)

        return "\n".join(lines)

    def _build_events(self, events: list[dict]) -> str:
        """Format K8s events."""
        if not events:
            return "No warning/error events."
        lines = []
        for e in events:
            lines.append(
                f"[{e.get('type', '')}] {e.get('kind', '')}/{e.get('object', '')}: "
                f"{e.get('reason', '')} - {e.get('message', '')}"
                f" (count={e.get('count', 1)})"
            )
        return "\n".join(lines)

    def _build_metric_anomalies(self, metrics: dict) -> str:
        """Format metric anomalies."""
        parts = []

        # OOM
        oom = metrics.get("oom_events", [])
        if oom:
            parts.append("OOMKilled containers: " + ", ".join(
                f"{o['pod']}/{o['container']}" for o in oom
            ))

        # CPU throttling
        throttle = metrics.get("cpu_throttling", [])
        if throttle:
            parts.append("CPU throttled: " + ", ".join(
                f"{t['pod']}/{t['container']} ({t['throttle_ratio']:.0%})"
                for t in throttle
            ))

        # Memory pressure
        mem = metrics.get("memory_usage", [])
        if mem:
            parts.append("High memory usage (>80% limit): " + ", ".join(
                f"{m['pod']}/{m['container']} ({m['memory_usage_ratio']:.0%})"
                for m in mem
            ))

        # Endpoints
        ep = metrics.get("endpoint_status", [])
        if ep:
            parts.append("Services with 0 endpoints: " + ", ".join(
                e["endpoint"] for e in ep
            ))

        # PVC
        pvc = metrics.get("pvc_status", [])
        if pvc:
            parts.append("PVC issues: " + ", ".join(
                f"{p['pvc']} ({p['phase']})" for p in pvc
            ))

        # Quota
        quota = metrics.get("resource_quota", [])
        if quota:
            parts.append("Quota near limit (>90%): " + ", ".join(
                f"{q['resource']} ({q['usage_ratio']:.0%})" for q in quota
            ))

        # Network drops
        drops = metrics.get("network_drops", [])
        if drops:
            parts.append("Network policy drops: " + ", ".join(
                f"{d['reason']} {d['direction']} (rate={d['rate']})" for d in drops
            ))

        return "\n".join(parts) if parts else "No metric anomalies detected."

    def _build_error_logs(self, logs: list[dict]) -> str:
        """Format error logs (truncated)."""
        if not logs:
            return "No error logs found."
        lines = []
        for entry in logs[:30]:  # limit for LLM context
            pod = entry.get("pod", "unknown")
            line = entry.get("line", "").strip()
            if len(line) > 300:
                line = line[:300] + "..."
            lines.append(f"[{pod}] {line}")
        if len(logs) > 30:
            lines.append(f"... and {len(logs) - 30} more error log entries")
        return "\n".join(lines)

    def _build_node_status(
        self, nodes: list[dict], node_metrics: list[dict]
    ) -> str:
        """Format node status."""
        if not nodes:
            return "No node data available."

        lines = []
        for n in nodes:
            status = "Ready" if n["ready"] == "True" else f"NOT READY (ready={n['ready']})"
            issues = ", ".join(n.get("issues", []))
            taints = ", ".join(n.get("taints", []))
            line = f"{n['name']}: {status}"
            if issues:
                line += f" | issues: {issues}"
            if taints:
                line += f" | taints: {taints}"
            lines.append(line)

        # Add metric-based issues
        for nm in node_metrics:
            if not any(nm["node"] in line for line in lines):
                lines.append(f"{nm['node']}: {nm['condition']} ({nm['status']})")

        return "\n".join(lines)

    def _build_gitops_status(self, gitops: dict) -> str:
        """Format GitOps status."""
        parts = []

        # FluxCD
        flux = gitops.get("flux", {})
        ks_list = flux.get("kustomizations", [])
        if ks_list:
            parts.append("### FluxCD Kustomizations")
            for ks in ks_list:
                status = "Ready" if ks["ready"] == "True" else f"NOT READY: {ks['message']}"
                parts.append(f"- {ks['name']}: {status} (rev: {ks.get('revision', 'N/A')[:12]})")

        hr_list = flux.get("helmreleases", [])
        if hr_list:
            parts.append("### FluxCD HelmReleases")
            for hr in hr_list:
                status = "Ready" if hr["ready"] == "True" else f"NOT READY: {hr['message']}"
                parts.append(f"- {hr['namespace']}/{hr['name']}: {status}")

        # ArgoCD
        argocd = gitops.get("argocd", {})
        apps = argocd.get("applications", [])
        if apps:
            parts.append("### ArgoCD Applications")
            for app in apps:
                parts.append(
                    f"- {app['name']}: health={app['health']}, sync={app['sync']}"
                )

        return "\n".join(parts) if parts else "No GitOps data available."

    def _build_git_changes(self, gitops: dict) -> str:
        """Format recent git changes."""
        git = gitops.get("git_history", {})
        if not git or "error" in git:
            return git.get("error", "No git data available.")

        parts = []
        commits = git.get("recent_commits", [])
        if commits:
            parts.append("Recent commits:")
            for c in commits:
                parts.append(f"  {c['hash']} {c['message']}")

        files = git.get("last_commit_changed_files", [])
        if files:
            parts.append(f"Last commit changed files: {', '.join(files)}")

        return "\n".join(parts) if parts else "No recent git changes."
