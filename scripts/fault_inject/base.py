"""Base fault injector with kubectl helpers."""
import json
import logging
import os
import subprocess
import tempfile
from typing import Optional

import yaml

from .config import KUBECONFIG, KUBECTL, NAMESPACE, GIT_REPO_PATH

logger = logging.getLogger(__name__)


def kubectl(*args: str, namespace: str = NAMESPACE, timeout: int = 30) -> str:
    """Run kubectl command."""
    cmd = [KUBECTL]
    if namespace:
        cmd += ["-n", namespace]
    cmd += list(args)

    env = os.environ.copy()
    env["KUBECONFIG"] = KUBECONFIG

    logger.debug("kubectl: %s", " ".join(cmd))
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env=env,
    )
    if result.returncode != 0:
        logger.warning("kubectl stderr: %s", result.stderr.strip())
    return result.stdout


def kubectl_apply(manifest: dict, namespace: str = NAMESPACE) -> str:
    """Apply a manifest dict via kubectl apply -f -."""
    yaml_str = yaml.dump(manifest, default_flow_style=False)
    env = os.environ.copy()
    env["KUBECONFIG"] = KUBECONFIG

    cmd = [KUBECTL, "apply", "-f", "-"]
    if namespace:
        cmd += ["-n", namespace]

    result = subprocess.run(
        cmd,
        input=yaml_str,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
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


def kubectl_get_json(resource: str, name: str = "", namespace: str = NAMESPACE) -> dict:
    """Get resource as JSON."""
    args = ["get", resource]
    if name:
        args.append(name)
    args += ["-o", "json"]
    output = kubectl(*args, namespace=namespace)
    if output:
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {}
    return {}


def ssh_node(node_name: str, command: str, timeout: int = 30) -> str:
    """SSH to a worker node and run a command."""
    from .config import WORKER_NODES
    node = WORKER_NODES.get(node_name)
    if not node:
        raise ValueError(f"Unknown node: {node_name}")

    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-J", f"debian@211.62.97.71:22015",
        f"{node['ssh_user']}@{node['ip']}",
        command,
    ]
    logger.info("SSH to %s: %s", node_name, command)
    result = subprocess.run(
        ssh_cmd, capture_output=True, text=True, timeout=timeout,
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
