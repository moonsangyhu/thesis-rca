"""GitOps context collector (FluxCD + ArgoCD)."""
import json
import logging
import os
import subprocess

from .config import KUBECONFIG, KUBECTL, FLUX_NAMESPACE, ARGOCD_NAMESPACE

logger = logging.getLogger(__name__)


def _run(args: list[str], timeout: int = 30) -> str:
    """Run command and return stdout."""
    env = os.environ.copy()
    env["KUBECONFIG"] = KUBECONFIG
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return result.stdout
    except Exception as e:
        logger.error("Command error: %s", e)
        return ""


class GitOpsCollector:
    """Collect GitOps state from FluxCD and ArgoCD."""

    def collect(self) -> dict:
        """Collect all GitOps signals."""
        return {
            "flux": self._collect_flux(),
            "argocd": self._collect_argocd(),
            "git_history": self._collect_git_diff(),
        }

    def _collect_flux(self) -> dict:
        """Collect FluxCD Kustomization and HelmRelease status."""
        # Kustomizations
        ks_output = _run([
            KUBECTL, "get", "kustomization", "-n", FLUX_NAMESPACE,
            "-o", "json",
        ])
        kustomizations = []
        if ks_output:
            try:
                data = json.loads(ks_output)
                for item in data.get("items", []):
                    meta = item.get("metadata", {})
                    status = item.get("status", {})
                    conditions = status.get("conditions", [])
                    ready_cond = next(
                        (c for c in conditions if c["type"] == "Ready"), {}
                    )
                    kustomizations.append({
                        "name": meta.get("name", ""),
                        "ready": ready_cond.get("status", "Unknown"),
                        "message": ready_cond.get("message", "")[:200],
                        "revision": status.get("lastAppliedRevision", ""),
                        "lastAttempted": status.get("lastAttemptedRevision", ""),
                    })
            except json.JSONDecodeError:
                pass

        # HelmReleases
        hr_output = _run([
            KUBECTL, "get", "helmrelease", "-A", "-o", "json",
        ])
        helmreleases = []
        if hr_output:
            try:
                data = json.loads(hr_output)
                for item in data.get("items", []):
                    meta = item.get("metadata", {})
                    status = item.get("status", {})
                    conditions = status.get("conditions", [])
                    ready_cond = next(
                        (c for c in conditions if c["type"] == "Ready"), {}
                    )
                    helmreleases.append({
                        "name": meta.get("name", ""),
                        "namespace": meta.get("namespace", ""),
                        "ready": ready_cond.get("status", "Unknown"),
                        "message": ready_cond.get("message", "")[:200],
                    })
            except json.JSONDecodeError:
                pass

        # GitRepository source status
        git_output = _run([
            KUBECTL, "get", "gitrepository", "-n", FLUX_NAMESPACE,
            "-o", "json",
        ])
        git_repos = []
        if git_output:
            try:
                data = json.loads(git_output)
                for item in data.get("items", []):
                    meta = item.get("metadata", {})
                    status = item.get("status", {})
                    artifact = status.get("artifact", {})
                    git_repos.append({
                        "name": meta.get("name", ""),
                        "revision": artifact.get("revision", ""),
                        "lastUpdate": artifact.get("lastUpdateTime", ""),
                    })
            except json.JSONDecodeError:
                pass

        return {
            "kustomizations": kustomizations,
            "helmreleases": helmreleases,
            "gitrepositories": git_repos,
        }

    def _collect_argocd(self) -> dict:
        """Collect ArgoCD Application status."""
        output = _run([
            KUBECTL, "get", "application", "-n", ARGOCD_NAMESPACE,
            "-o", "json",
        ])
        applications = []
        if output:
            try:
                data = json.loads(output)
                for item in data.get("items", []):
                    meta = item.get("metadata", {})
                    status = item.get("status", {})
                    health = status.get("health", {})
                    sync = status.get("sync", {})
                    applications.append({
                        "name": meta.get("name", ""),
                        "health": health.get("status", "Unknown"),
                        "sync": sync.get("status", "Unknown"),
                        "revision": sync.get("revision", ""),
                    })
            except json.JSONDecodeError:
                pass

        return {"applications": applications}

    def _collect_git_diff(self) -> dict:
        """Get recent git changes from the FluxCD source repo."""
        repo_path = "/tmp/thesis-rca-work"
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            return {"error": "Git repo not found at /tmp/thesis-rca-work"}

        # Recent commits (last 5)
        log_output = _run([
            "git", "-C", repo_path, "log", "--oneline", "-5",
            "--format=%H|%s|%ai",
        ])
        commits = []
        if log_output:
            for line in log_output.strip().split("\n"):
                parts = line.split("|", 2)
                if len(parts) == 3:
                    commits.append({
                        "hash": parts[0][:8],
                        "message": parts[1],
                        "date": parts[2],
                    })

        # Files changed in last commit
        diff_output = _run([
            "git", "-C", repo_path, "diff", "--name-only", "HEAD~1", "HEAD",
        ])
        changed_files = [
            f for f in diff_output.strip().split("\n") if f
        ] if diff_output else []

        return {
            "recent_commits": commits,
            "last_commit_changed_files": changed_files,
        }
