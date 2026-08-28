"""Base fault injector with kubectl helpers."""
import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Optional

import yaml

from .config import KUBECONFIG, KUBECTL, NAMESPACE, GIT_REPO_PATH

logger = logging.getLogger(__name__)


def _kubectl_executable() -> str:
    """Resolve kubectl before spawning to keep macOS on posix_spawn.

    The live runner loads the local sentence-transformer model before it
    performs state validation.  On macOS, a bare executable name together
    with ``close_fds=True`` forces ``subprocess`` through fork/exec, which can
    hang while native ML worker threads are present.  An absolute executable
    and ``close_fds=False`` select the safe posix_spawn path instead.
    """
    return shutil.which(KUBECTL) or KUBECTL


def _ssh_executable() -> str:
    """Resolve SSH so macOS can use the posix_spawn execution path."""
    return shutil.which("ssh") or "ssh"


def kubectl(*args: str, namespace: str = NAMESPACE, timeout: int = 60) -> str:
    """Run kubectl command."""
    cmd = [_kubectl_executable()]
    if namespace:
        cmd += ["-n", namespace]
    cmd += list(args)

    env = os.environ.copy()
    env["KUBECONFIG"] = KUBECONFIG

    logger.debug("kubectl: %s", " ".join(cmd))
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env=env,
        close_fds=False,
    )
    if result.returncode != 0:
        logger.warning("kubectl stderr: %s", result.stderr.strip())
    return result.stdout


def kubectl_apply(manifest: dict, namespace: str = NAMESPACE) -> str:
    """Apply a manifest dict via kubectl apply -f -."""
    yaml_str = yaml.dump(manifest, default_flow_style=False)
    env = os.environ.copy()
    env["KUBECONFIG"] = KUBECONFIG

    cmd = [_kubectl_executable(), "apply", "-f", "-"]
    if namespace:
        cmd += ["-n", namespace]

    result = subprocess.run(
        cmd,
        input=yaml_str,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        close_fds=False,
    )
    if result.returncode != 0:
        logger.error("kubectl apply failed: %s", result.stderr)
    return result.stdout + result.stderr


def kubectl_delete(resource: str, name: str, namespace: str = NAMESPACE) -> str:
    """Delete a K8s resource."""
    return kubectl("delete", resource, name, "--ignore-not-found", namespace=namespace)


def kubectl_patch(
    resource: str,
    name: str,
    patch: dict,
    patch_type: str = "strategic",
    namespace: str = NAMESPACE,
) -> str:
    """Patch a K8s resource."""
    return kubectl(
        "patch", resource, name,
        "--type", patch_type,
        "-p", json.dumps(patch),
        namespace=namespace,
    )


def get_container_image(deployment: str, container: str = "", namespace: str = NAMESPACE) -> str:
    """Get current container image from a deployment (needed for strategic merge patch)."""
    deploy = kubectl_get_json("deployment", deployment, namespace=namespace)
    if not deploy:
        return ""
    containers = deploy.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    for c in containers:
        if not container or c.get("name") == container or len(containers) == 1:
            return c.get("image", "")
    return ""


def kubectl_get_json(
    resource: str,
    name: str = "",
    namespace: str = NAMESPACE,
    timeout: int = 60,
) -> dict:
    """Get resource as JSON."""
    args = ["get", resource]
    if name:
        args.append(name)
    args += ["-o", "json"]
    output = kubectl(*args, namespace=namespace, timeout=timeout)
    if output:
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {}
    return {}


def ssh_node(node_name: str, command: str, timeout: int = 30) -> str:
    """SSH to a worker node and run a command.

    Rebuilt direct K8s lab: nodes are reached directly via host:port. A jump host
    is only used when the node explicitly declares one (``jump``/``proxy`` key).
    """
    from .config import WORKER_NODES
    node = WORKER_NODES.get(node_name)
    if not node:
        raise ValueError(f"Unknown node: {node_name}")

    ssh_cmd = [
        _ssh_executable(),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-p", str(node["port"]),
    ]
    jump = node.get("jump") or node.get("proxy")
    if jump:
        ssh_cmd += ["-J", jump]
    ssh_cmd += [
        f"{node['ssh_user']}@{node['host']}",
        command,
    ]
    logger.info("SSH to %s: %s", node_name, command)
    result = subprocess.run(
        ssh_cmd, capture_output=True, text=True, timeout=timeout,
        # The live runner has already initialized local ML worker threads.
        # On macOS, close_fds=True selects fork/exec and can deadlock the SSH
        # child before it emits health-check markers.  Keep the same
        # posix_spawn-safe contract used by kubectl above.
        close_fds=False,
    )
    return result.stdout + result.stderr


def git_commit_and_push(message: str, files: list[str] = None) -> str:
    """Commit and push changes to the FluxCD repo (for GitOps signal generation)."""
    cmds = []
    if files:
        for f in files:
            cmds.append(["git", "-C", GIT_REPO_PATH, "add", f])
    else:
        cmds.append(["git", "-C", GIT_REPO_PATH, "add", "-A"])

    cmds.append(["git", "-C", GIT_REPO_PATH, "commit", "-m", message])
    cmds.append(["git", "-C", GIT_REPO_PATH, "push"])

    output = ""
    for cmd in cmds:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output += result.stdout + result.stderr + "\n"
        if result.returncode != 0 and "nothing to commit" not in result.stderr:
            logger.warning("Git command failed: %s", result.stderr)
    return output
