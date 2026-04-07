"""V4 context builder: anomaly-first reranking, noise reduction, GitOps filtering."""
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RCAContextV4:
    """V4 structured context with anomaly-first ordering."""
    # Anomaly summary (top section)
    anomaly_summary: str = ""

    # Error logs
    error_logs: str = ""

    # Detailed evidence (bottom section)
    events_detail: str = ""
    full_pod_status: str = ""
    full_node_status: str = ""

    # System B additions
    correlated_changes: str = ""
    rag_context: str = ""

    # Metadata
    fault_id: str = ""
    trial: int = 0
    system: str = ""

    def to_system_a_context(self) -> str:
        """Format context for System A: anomaly-first ordering."""
        sections = []
        if self.anomaly_summary:
            sections.append(f"## ANOMALY SUMMARY\n{self.anomaly_summary}")
        if self.error_logs:
            sections.append(f"## Error Logs\n{self.error_logs}")
        sections.append("## Detailed Evidence")
        if self.events_detail:
            sections.append(f"### Kubernetes Events\n{self.events_detail}")
        if self.full_pod_status:
            sections.append(f"### Full Pod Status\n{self.full_pod_status}")
        if self.full_node_status:
            sections.append(f"### Full Node Status\n{self.full_node_status}")
        return "\n\n".join(sections)

    def to_system_b_context(self) -> str:
        """Format context for System B: anomaly-first + correlated changes + RAG."""
        sections = []
        if self.anomaly_summary:
            sections.append(f"## ANOMALY SUMMARY\n{self.anomaly_summary}")
        if self.correlated_changes:
            sections.append(f"## CORRELATED CHANGES (GitOps)\n{self.correlated_changes}")
        if self.rag_context:
            sections.append(f"## Knowledge Base (RAG Retrieved)\n{self.rag_context}")
        if self.error_logs:
            sections.append(f"## Error Logs\n{self.error_logs}")
        sections.append("## Detailed Evidence")
        if self.events_detail:
            sections.append(f"### Kubernetes Events\n{self.events_detail}")
        if self.full_pod_status:
            sections.append(f"### Full Pod Status\n{self.full_pod_status}")
        if self.full_node_status:
            sections.append(f"### Full Node Status\n{self.full_node_status}")
        return "\n\n".join(sections)

    def to_context(self) -> str:
        if self.system == "A":
            return self.to_system_a_context()
        return self.to_system_b_context()


class ContextBuilderV4:
    """V4 context builder: anomaly-first reranking with noise reduction."""

    def build(
        self,
        signals: dict,
        fault_id: str = "",
        trial: int = 0,
        system: str = "A",
        rag_context: str = "",
    ) -> RCAContextV4:
        metrics = signals.get("metrics", {})
        logs = signals.get("logs", {})
        kubectl = signals.get("kubectl", {})
        gitops = signals.get("gitops", {})

        ctx = RCAContextV4(
            fault_id=fault_id, trial=trial, system=system,
            rag_context=rag_context,
        )

        pods = kubectl.get("pods", [])
        nodes = kubectl.get("nodes", [])
        node_metrics = metrics.get("node_status", [])

        # Anomaly summary: unhealthy pods + metric anomalies + node issues
        ctx.anomaly_summary = self._build_anomaly_summary(
            pods, metrics, nodes, node_metrics,
        )

        # Error logs (same as V3)
        ctx.error_logs = self._build_error_logs(logs.get("pod_logs", []))

        # Detailed evidence (bottom)
        ctx.events_detail = self._build_events(kubectl.get("events", []))
        ctx.full_pod_status = self._build_full_pod_status(pods, metrics)
        ctx.full_node_status = self._build_full_node_status(nodes, node_metrics)

        # System B: correlated changes (NOT READY GitOps only)
        if system == "B" and gitops:
            ctx.correlated_changes = self._build_correlated_changes(gitops)

        return ctx

    # ── Anomaly Summary (TOP section) ──────────────────────────

    def _build_anomaly_summary(
        self,
        pods: list[dict],
        metrics: dict,
        nodes: list[dict],
        node_metrics: list[dict],
    ) -> str:
        parts = []

        # 1. Unhealthy pods
        unhealthy = self._get_unhealthy_pods(pods)
        if unhealthy:
            parts.append("### Unhealthy Pods")
            parts.extend(unhealthy)

        # 2. Metric anomalies (ALWAYS included, independent of pod status)
        metric_lines = self._build_metric_anomalies_ranked(metrics)
        if metric_lines:
            parts.append("### Metric Anomalies")
            parts.extend(metric_lines)

        # 3. Node issues
        node_issues = self._get_unhealthy_nodes(nodes, node_metrics)
        if node_issues:
            parts.append("### Node Issues")
            parts.extend(node_issues)

        if not parts:
            return "No anomalies detected."
        return "\n".join(parts)

    def _get_unhealthy_pods(self, pods: list[dict]) -> list[str]:
        """Filter to only unhealthy pods."""
        lines = []
        for pod in pods:
            is_unhealthy = False
            reasons = []

            if pod.get("phase") != "Running":
                is_unhealthy = True
                reasons.append(f"phase={pod['phase']}")

            for c in pod.get("containers", []):
                if not c.get("ready"):
                    is_unhealthy = True
                    reason = c.get("waitingReason", "") or c.get("terminatedReason", "")
                    restarts = c.get("restartCount", 0)
                    r = f"container/{c['name']}: NOT READY"
                    if reason:
                        r += f" ({reason})"
                    if restarts > 0:
                        r += f" restarts={restarts}"
                    reasons.append(r)
                    if c.get("lastTerminatedReason"):
                        reasons.append(
                            f"  last terminated: {c['lastTerminatedReason']}"
                            f" (exit code {c.get('exitCode', '?')})"
                        )
                elif c.get("restartCount", 0) > 0:
                    is_unhealthy = True
                    reasons.append(
                        f"container/{c['name']}: Running but restarts={c['restartCount']}"
                    )

            if is_unhealthy:
                line = f"- {pod['name']}: {pod.get('phase', '?')}"
                if reasons:
                    line += "\n  " + "\n  ".join(reasons)
                lines.append(line)
        return lines

    def _build_metric_anomalies_ranked(self, metrics: dict) -> list[str]:
        """Build metric anomalies ranked by severity (OOM > Quota > Throttle > Endpoints > PVC > Network)."""
        lines = []

        # OOM (highest severity)
        oom = metrics.get("oom_events", [])
        if oom:
            lines.append("- OOMKilled: " + ", ".join(
                f"{o['pod']}/{o['container']}" for o in oom
            ))

        # Quota exceeded
        quota = metrics.get("resource_quota", [])
        if quota:
            lines.append("- Quota near limit (>90%): " + ", ".join(
                f"{q['resource']} ({q['usage_ratio']:.0%})" for q in quota
            ))

        # CPU throttling
        throttle = metrics.get("cpu_throttling", [])
        if throttle:
            lines.append("- CPU throttled: " + ", ".join(
                f"{t['pod']}/{t['container']} ({t['throttle_ratio']:.0%})"
                for t in throttle
            ))

        # Service endpoints=0
        ep = metrics.get("endpoint_status", [])
        if ep:
            lines.append("- Services with 0 endpoints: " + ", ".join(
                e["endpoint"] for e in ep
            ))

        # PVC issues
        pvc = metrics.get("pvc_status", [])
        if pvc:
            lines.append("- PVC issues: " + ", ".join(
                f"{p['pvc']} ({p['phase']})" for p in pvc
            ))

        # Network drops (lowest severity)
        drops = metrics.get("network_drops", [])
        if drops:
            lines.append("- Network policy drops: " + ", ".join(
                f"{d['reason']} {d['direction']} (rate={d['rate']})" for d in drops
            ))

        # Memory pressure
        mem = metrics.get("memory_usage", [])
        if mem:
            lines.append("- High memory usage (>80%): " + ", ".join(
                f"{m['pod']}/{m['container']} ({m['memory_usage_ratio']:.0%})"
                for m in mem
            ))

        return lines

    def _get_unhealthy_nodes(
        self, nodes: list[dict], node_metrics: list[dict],
    ) -> list[str]:
        """Filter to only unhealthy nodes."""
        lines = []
        for n in nodes:
            if n.get("ready") != "True":
                line = f"- {n['name']}: NOT READY (ready={n['ready']})"
                issues = ", ".join(n.get("issues", []))
                if issues:
                    line += f" | issues: {issues}"
                lines.append(line)
            elif n.get("issues"):
                line = f"- {n['name']}: issues: {', '.join(n['issues'])}"
                lines.append(line)

        for nm in node_metrics:
            if not any(nm["node"] in line for line in lines):
                lines.append(f"- {nm['node']}: {nm['condition']} ({nm['status']})")
        return lines

    # ── Events (Detailed Evidence, bottom) ──────────────────────

    def _build_events(self, events: list[dict], max_events: int = 15) -> str:
        """Format K8s events: deduplicate and limit."""
        if not events:
            return "No warning/error events."

        # Deduplicate by (reason, object)
        deduped = {}
        for e in events:
            key = (e.get("reason", ""), e.get("object", ""))
            if key in deduped:
                deduped[key]["count"] = deduped[key].get("count", 1) + e.get("count", 1)
            else:
                deduped[key] = dict(e)

        lines = []
        for e in list(deduped.values())[:max_events]:
            lines.append(
                f"[{e.get('type', '')}] {e.get('kind', '')}/{e.get('object', '')}: "
                f"{e.get('reason', '')} - {e.get('message', '')}"
                f" (count={e.get('count', 1)})"
            )
        remaining = len(deduped) - max_events
        if remaining > 0:
            lines.append(f"... and {remaining} more events")
        return "\n".join(lines)

    # ── Full Pod/Node Status (Detailed Evidence, bottom) ────────

    def _build_full_pod_status(self, pods: list[dict], metrics: dict) -> str:
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

        # Metric-based waiting reasons
        pod_metrics = metrics.get("pod_status", [])
        for m in pod_metrics:
            if "waiting_reason" in m:
                if not any(m["pod"] in line for line in lines):
                    lines.append(f"{m['pod']}: {m['waiting_reason']}")
        return "\n".join(lines)

    def _build_full_node_status(
        self, nodes: list[dict], node_metrics: list[dict],
    ) -> str:
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
        for nm in node_metrics:
            if not any(nm["node"] in line for line in lines):
                lines.append(f"{nm['node']}: {nm['condition']} ({nm['status']})")
        return "\n".join(lines)

    # ── Error Logs (same as V3) ────────────────────────────────

    def _build_error_logs(self, logs: list[dict]) -> str:
        if not logs:
            return "No error logs found."
        lines = []
        for entry in logs[:30]:
            pod = entry.get("pod", "unknown")
            line = entry.get("line", "").strip()
            if len(line) > 300:
                line = line[:300] + "..."
            lines.append(f"[{pod}] {line}")
        if len(logs) > 30:
            lines.append(f"... and {len(logs) - 30} more error log entries")
        return "\n".join(lines)

    # ── Correlated Changes (System B, NOT READY only) ──────────

    def _build_correlated_changes(self, gitops: dict) -> str:
        """GitOps status: only NOT READY items (noise reduction)."""
        parts = []

        # FluxCD
        flux = gitops.get("flux", {})
        ks_list = flux.get("kustomizations", [])
        not_ready_ks = [ks for ks in ks_list if ks.get("ready") != "True"]
        if not_ready_ks:
            parts.append("### FluxCD Kustomizations (NOT READY)")
            for ks in not_ready_ks:
                parts.append(f"- {ks['name']}: {ks.get('message', 'unknown')}")

        hr_list = flux.get("helmreleases", [])
        not_ready_hr = [hr for hr in hr_list if hr.get("ready") != "True"]
        if not_ready_hr:
            parts.append("### FluxCD HelmReleases (NOT READY)")
            for hr in not_ready_hr:
                parts.append(f"- {hr['namespace']}/{hr['name']}: {hr.get('message', 'unknown')}")

        # ArgoCD
        argocd = gitops.get("argocd", {})
        apps = argocd.get("applications", [])
        unhealthy_apps = [
            a for a in apps
            if a.get("health") != "Healthy" or a.get("sync") != "Synced"
        ]
        if unhealthy_apps:
            parts.append("### ArgoCD Applications (Unhealthy/OutOfSync)")
            for app in unhealthy_apps:
                parts.append(f"- {app['name']}: health={app['health']}, sync={app['sync']}")

        # Git changes (always include — context for changes)
        git = gitops.get("git_history", {})
        if git and "error" not in git:
            commits = git.get("recent_commits", [])
            if commits:
                parts.append("### Recent Git Changes")
                for c in commits:
                    parts.append(f"- {c['hash']} {c['message']}")
                files = git.get("last_commit_changed_files", [])
                if files:
                    parts.append(f"  Changed files: {', '.join(files)}")

        if not parts:
            return ""
        return "\n".join(parts)
