"""Offline mocks for V2.2 end-to-end validation (no API key, no cluster).

- mock_signals(): canned signals dict shaped like SignalCollector.collect_all(),
  populating obs + gitops fields so ContextBuilder(system="B") fills everything.
- MockLLMClientMixin: monkeypatch target for call_llm / openai judge call so the
  full 5-arm × k=3 × m=3 pipeline runs deterministically offline.
"""
import json
import random

# Plausible fault-type labels for mock generation (varied to exercise majority vote).
_MOCK_LABELS = ["OOM Kill", "OOM Kill", "Image Pull Failure"]


def mock_signals(fault_id: str = "F1") -> dict:
    """Canned signals dict (obs + gitops) for offline ContextBuilder."""
    return {
        "metrics": {
            "oom_events": [{"pod": "cartservice-abc", "container": "server"}],
            "memory_usage": [
                {"pod": "cartservice-abc", "container": "server",
                 "memory_usage_ratio": 0.99},
            ],
            "pod_status": [],
            "container_restarts": [],
            "node_status": [],
        },
        "logs": {
            "pod_logs": [
                {"pod": "cartservice-abc",
                 "line": "container killed due to memory limit (OOMKilled), exit code 137"},
            ],
        },
        "kubectl": {
            "pods": [
                {"name": "cartservice-abc", "phase": "Running", "containers": [
                    {"name": "server", "ready": False,
                     "waitingReason": "CrashLoopBackOff", "restartCount": 5,
                     "lastTerminatedReason": "OOMKilled", "exitCode": 137},
                ]},
            ],
            "events": [
                {"type": "Warning", "kind": "Pod", "object": "cartservice-abc",
                 "reason": "OOMKilling",
                 "message": "Memory cgroup out of memory: killed process", "count": 3},
            ],
            "nodes": [{"name": "worker-1", "ready": "True", "issues": [], "taints": []}],
        },
        "gitops": {
            "flux": {
                "kustomizations": [
                    {"name": "boutique", "ready": "True",
                     "message": "Applied revision", "revision": "main@sha1:abc123def456"},
                ],
                "helmreleases": [],
            },
            "argocd": {"applications": []},
            "git_history": {
                "recent_commits": [
                    {"hash": "abc123d",
                     "message": "lower cartservice memory limit to 32Mi"},
                ],
                "last_commit_changed_files": ["boutique/cartservice-deploy.yaml"],
            },
        },
        # consumed by runner mock path → RAG block
        "rag_context": (
            "Runbook: OOMKilled remediation. When a container is OOMKilled "
            "(exit code 137), inspect container_memory_working_set_bytes against "
            "the configured memory limit. Raise the limit or fix the memory leak. "
            "Recent commits lowering memory limits are a common trigger."
        ),
    }


def install_mock_llm(engine):
    """Monkeypatch an engine's call_llm + openai judge path to a deterministic mock.

    Generation calls → plausible RCA JSON (label varies per call to exercise
    majority vote / agreement). Judge calls → {"correctness_score", "reasoning"}.
    """
    rng = random.Random(12345)
    state = {"gen_idx": 0}

    def _is_judge(system_prompt: str) -> bool:
        return "impartial judge" in (system_prompt or "").lower()

    def mock_call_llm(prompt, system_prompt, max_tokens, temperature=None, seed=None):
        if _is_judge(system_prompt):
            score = rng.choice([0.7, 0.75, 0.8])
            body = {"correctness_score": score, "reasoning": "mock judge: matches OOM root cause"}
            return json.dumps(body), {"input": 100, "output": 30}
        # generation
        label = _MOCK_LABELS[state["gen_idx"] % len(_MOCK_LABELS)]
        state["gen_idx"] += 1
        body = {
            "reasoning": "mock SOP analysis: pod OOMKilled, memory at limit.",
            "identified_fault_type": label,
            "root_cause": "Container OOMKilled due to memory limit exceeded.",
            "root_cause_ko": "메모리 한계 초과로 컨테이너 OOMKilled.",
            "confidence": 0.9,
            "confidence_2nd": 0.3,
            "affected_components": ["cartservice"],
            "remediation": ["Raise memory limit", "Fix memory leak"],
            "remediation_ko": ["메모리 한계 상향", "메모리 누수 수정"],
            "detail": "OOMKilled with exit code 137 confirms memory limit breach.",
            "detail_ko": "exit code 137 OOMKilled로 메모리 한계 초과 확인.",
            "evidence_chain": [
                {"type": "event", "source": "kubectl events",
                 "content": "OOMKilling", "supports": "OOM"},
            ],
            "alternative_hypotheses": [
                {"hypothesis": "image pull failure", "confidence": 0.2,
                 "reason_rejected": "image pulled successfully"},
            ],
        }
        return json.dumps(body), {"input": 500, "output": 200}

    engine.call_llm = mock_call_llm

    # mock the openai-specific judge path (system_fingerprint capture)
    def mock_call_judge(judge_input):
        raw, tokens = mock_call_llm(judge_input, "impartial judge", 512)
        return raw, tokens, "fp_mock_deadbeef"

    engine._call_judge = mock_call_judge
    return engine
