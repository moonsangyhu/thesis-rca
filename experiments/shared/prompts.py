"""Prompts shared across all experiment versions."""

USER_PROMPT_TEMPLATE = """\
Analyze the following Kubernetes cluster diagnostic context and identify the root cause.

{context}

Provide your analysis as JSON only.
"""

CORRECTNESS_JUDGE_PROMPT = """\
You are an impartial judge evaluating whether a Kubernetes root cause diagnosis is correct.

You will receive:
1. The ground truth root cause description
2. The LLM's diagnosed root cause and diagnostic label

## Scoring Rules (0.0-1.0)
- **1.0**: Diagnosis correctly identifies the exact root cause mechanism \
(e.g., ground truth says "OOMKilled due to memory limit exceeded" and diagnosis says \
"container killed by OOM due to insufficient memory limit")
- **0.75-0.9**: Diagnosis identifies the correct fault category but misses specific details \
(e.g., correct fault type but wrong target service, or correct mechanism but vague on specifics)
- **0.5-0.7**: Diagnosis is partially correct — identifies a related symptom but not the true \
root cause (e.g., identifies "pod crashing" but not "OOMKilled specifically")
- **0.1-0.4**: Diagnosis is in the wrong category but shares some surface-level symptoms
- **0.0**: Completely wrong diagnosis

## Important
- Focus on whether the ROOT CAUSE MECHANISM matches, not just the symptoms
- The diagnostic label does not need to match exactly — evaluate semantic equivalence
- If the diagnosis identifies the correct underlying issue using different terminology, score high

Output ONLY valid JSON:
{
  "correctness_score": 0.0,
  "reasoning": "Brief explanation of why this score was assigned"
}
"""
