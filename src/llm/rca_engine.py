"""LLM-based RCA inference engine for System A/B comparison."""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RCAOutput:
    """Structured RCA output from LLM."""
    fault_id: str
    trial: int
    system: str  # "A" or "B"

    # LLM response (parsed)
    identified_fault_type: str = ""      # predicted fault type (F1~F10)
    root_cause: str = ""
    confidence: float = 0.0
    affected_components: list[str] = field(default_factory=list)
    remediation: list[str] = field(default_factory=list)
    detail: str = ""

    # v2: bilingual
    root_cause_ko: str = ""
    remediation_ko: list[str] = field(default_factory=list)
    detail_ko: str = ""

    # v2: CoT + evidence chain
    reasoning: str = ""
    evidence_chain: list[dict] = field(default_factory=list)
    alternative_hypotheses: list[dict] = field(default_factory=list)
    confidence_2nd: float = 0.0

    # v2: harness — abstention + verification
    abstained: bool = False
    abstention_reason: str = ""
    faithfulness_score: float = 0.0

    # Metadata
    model: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw_response: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "fault_id": self.fault_id,
            "trial": self.trial,
            "system": self.system,
            "identified_fault_type": self.identified_fault_type,
            "root_cause": self.root_cause,
            "confidence": self.confidence,
            "affected_components": self.affected_components,
            "remediation": self.remediation,
            "detail": self.detail,
            "root_cause_ko": self.root_cause_ko,
            "remediation_ko": self.remediation_ko,
            "detail_ko": self.detail_ko,
            "reasoning": self.reasoning,
            "evidence_chain": self.evidence_chain,
            "alternative_hypotheses": self.alternative_hypotheses,
            "confidence_2nd": self.confidence_2nd,
            "abstained": self.abstained,
            "abstention_reason": self.abstention_reason,
            "faithfulness_score": self.faithfulness_score,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "error": self.error,
        }


SYSTEM_PROMPT_V1 = """\
You are an expert Kubernetes Site Reliability Engineer performing root cause analysis.

Given diagnostic context from a Kubernetes cluster, identify:
1. The most likely root cause of the observed issue
2. Which fault category it belongs to (choose ONE from the list below)
3. Affected components
4. Step-by-step remediation

Fault categories:
- F1: OOMKilled (container memory limit exceeded)
- F2: CrashLoopBackOff (container repeatedly crashing)
- F3: ImagePullBackOff (image pull failure)
- F4: NodeNotReady (node unavailable)
- F5: PVCPending (storage claim stuck)
- F6: NetworkPolicy (network connectivity blocked)
- F7: CPUThrottle (CPU resource throttling)
- F8: ServiceEndpoint (service endpoint misconfiguration)
- F9: SecretConfigMap (secret/configmap missing or wrong)
- F10: ResourceQuota (namespace quota exceeded)

Output ONLY valid JSON:
{
  "identified_fault_type": "F1",
  "root_cause": "one-sentence root cause",
  "confidence": 0.0-1.0,
  "affected_components": ["component1", "component2"],
  "remediation": ["step 1", "step 2"],
  "detail": "2-3 sentence technical explanation"
}
"""

# Backward compatibility alias
SYSTEM_PROMPT = SYSTEM_PROMPT_V1

SYSTEM_PROMPT_V2 = """\
You are an expert Kubernetes Site Reliability Engineer performing root cause analysis.

## Analysis Protocol (Chain-of-Thought)
Think step-by-step BEFORE giving your final answer:

Step 1 - Signal Inventory: List every anomalous signal you observe in the input \
(which pods are unhealthy, which metrics are abnormal, which events/logs indicate errors).

Step 2 - Hypothesis Generation: For each fault category F1~F10, briefly assess whether \
the observed signals could match. List ALL plausible candidates with estimated likelihood.

Step 3 - Evidence Matching: For your top candidate, cite the EXACT signal from the input \
that supports it. Quote the specific metric name/value, log line, event message, or GitOps diff.

Step 4 - Differential Diagnosis: For each alternative candidate, explain the specific signal \
that CONTRADICTS it, or the expected signal that is MISSING to confirm it.

Step 5 - Confidence Assessment: Based on how many signals directly confirm your top hypothesis \
vs how many are ambiguous or contradictory, assign confidence honestly.

## Fault Categories
- F1: OOMKilled (container memory limit exceeded)
- F2: CrashLoopBackOff (container repeatedly crashing)
- F3: ImagePullBackOff (image pull failure)
- F4: NodeNotReady (node unavailable)
- F5: PVCPending (storage claim stuck)
- F6: NetworkPolicy (network connectivity blocked)
- F7: CPUThrottle (CPU resource throttling)
- F8: ServiceEndpoint (service endpoint misconfiguration)
- F9: SecretConfigMap (secret/configmap missing or wrong)
- F10: ResourceQuota (namespace quota exceeded)

## Confidence Calibration
- 0.9-1.0: Unambiguous direct evidence in input (e.g., OOMKilled in pod status reason)
- 0.7-0.9: Strong indirect evidence with minor ambiguity
- 0.5-0.7: Multiple plausible explanations; primary hypothesis is best guess
- Below 0.5: Very ambiguous or insufficient signals; diagnosis is unreliable

## Evidence Requirements (CRITICAL)
Each evidence item MUST quote from the actual input context provided to you. \
Do NOT fabricate or hallucinate evidence that is not present in the input. \
If you cannot find strong supporting signals, lower your confidence accordingly.

## Bilingual Output
Provide root_cause, remediation, and detail in BOTH English and Korean.

## Output Format
Output ONLY valid JSON:
{
  "reasoning": "Your step-by-step chain-of-thought analysis (Steps 1-5 above). Be thorough.",
  "identified_fault_type": "F1",
  "root_cause": "One-sentence root cause in English",
  "root_cause_ko": "한국어 근본 원인 한 문장",
  "confidence": 0.0,
  "confidence_2nd": 0.0,
  "affected_components": ["component1"],
  "remediation": ["step 1 in English", "step 2"],
  "remediation_ko": ["한국어 조치 1", "한국어 조치 2"],
  "detail": "2-3 sentence technical explanation in English",
  "detail_ko": "한국어 기술 설명 2-3문장",
  "evidence_chain": [
    {
      "type": "metric or log or event or gitops_diff",
      "source": "exact source identifier from input",
      "content": "QUOTED text from the input context",
      "supports": "what this evidence indicates"
    }
  ],
  "alternative_hypotheses": [
    {
      "fault_type": "F2",
      "confidence": 0.3,
      "reason_rejected": "specific contradicting signal or missing evidence"
    }
  ]
}
"""

USER_PROMPT_TEMPLATE = """\
Analyze the following Kubernetes cluster diagnostic context and identify the root cause.

{context}

Provide your analysis as JSON only.
"""


class RCAEngine:
    """LLM-based RCA engine supporting System A/B comparison."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        provider: str = "anthropic",
        prompt_version: str = "v1",
    ):
        self.model = model
        self.provider = provider
        self.prompt_version = prompt_version
        self._client = self._init_client()

    def _init_client(self):
        """Initialize LLM client."""
        if self.provider == "anthropic":
            import anthropic
            return anthropic.Anthropic()
        elif self.provider == "openai":
            from openai import OpenAI
            return OpenAI()
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    def analyze(
        self,
        context: str,
        fault_id: str = "",
        trial: int = 0,
        system: str = "A",
    ) -> RCAOutput:
        """
        Run RCA analysis on given context.

        Args:
            context: Pre-formatted diagnostic context string
            fault_id: Ground truth fault ID (for recording, not shown to LLM)
            trial: Trial number
            system: "A" or "B"

        Returns:
            RCAOutput with parsed results
        """
        output = RCAOutput(
            fault_id=fault_id,
            trial=trial,
            system=system,
            model=self.model,
        )

        prompt = USER_PROMPT_TEMPLATE.format(context=context)

        start = time.time()
        try:
            raw, tokens = self._call_llm(prompt)
            output.latency_ms = int((time.time() - start) * 1000)
            output.raw_response = raw
            output.prompt_tokens = tokens.get("input", 0)
            output.completion_tokens = tokens.get("output", 0)

            # Parse JSON response
            parsed = self._parse_json(raw)
            output.identified_fault_type = parsed.get("identified_fault_type", "")
            output.root_cause = parsed.get("root_cause", "")
            output.confidence = float(parsed.get("confidence", 0.0))
            output.affected_components = parsed.get("affected_components", [])
            output.remediation = parsed.get("remediation", [])
            output.detail = parsed.get("detail", "")

            # v2 fields
            if self.prompt_version == "v2":
                output.reasoning = parsed.get("reasoning", "")
                output.root_cause_ko = parsed.get("root_cause_ko", "")
                output.remediation_ko = parsed.get("remediation_ko", [])
                output.detail_ko = parsed.get("detail_ko", "")
                output.confidence_2nd = float(parsed.get("confidence_2nd", 0.0))
                output.evidence_chain = parsed.get("evidence_chain", [])
                output.alternative_hypotheses = parsed.get("alternative_hypotheses", [])

                # Harness: verify evidence against input context
                output.evidence_chain, output.faithfulness_score = (
                    self._verify_evidence(output.evidence_chain, context)
                )

                # Harness: check abstention
                output = self._check_abstention(output)

        except Exception as e:
            output.latency_ms = int((time.time() - start) * 1000)
            output.error = str(e)
            logger.error("RCA analysis failed: %s", e)

        return output

    def _verify_evidence(
        self, evidence_chain: list[dict], input_context: str,
    ) -> tuple[list[dict], float]:
        """
        Harness: verify that LLM-cited evidence actually exists in the input.
        Returns (verified_evidence_chain, faithfulness_score).
        """
        if not evidence_chain:
            return evidence_chain, 0.0

        verified = []
        for ev in evidence_chain:
            content = ev.get("content", "")
            source = ev.get("source", "")
            # Keyword-based fuzzy matching (LLM may rephrase slightly)
            check_text = f"{content} {source}"
            keywords = [w for w in check_text.split() if len(w) > 3]
            if not keywords:
                ev_copy = dict(ev, verified=False, match_ratio=0.0)
                verified.append(ev_copy)
                continue
            match_count = sum(
                1 for kw in keywords if kw.lower() in input_context.lower()
            )
            match_ratio = match_count / len(keywords)
            ev_copy = dict(ev, verified=match_ratio >= 0.5, match_ratio=round(match_ratio, 2))
            verified.append(ev_copy)

        faithfulness = sum(1 for e in verified if e["verified"]) / len(verified)
        logger.info(
            "Evidence verification: %d/%d verified (faithfulness=%.2f)",
            sum(1 for e in verified if e["verified"]), len(verified), faithfulness,
        )
        return verified, round(faithfulness, 2)

    def _check_abstention(self, output: RCAOutput) -> RCAOutput:
        """
        Harness: multi-layer abstention check.
        Layer 1-2: LLM self-assessment.
        Layer 3-4: system-side independent verification.
        """
        reasons = []

        # Layer 1: LLM self-reported confidence
        if output.confidence < 0.7:
            reasons.append(f"low_confidence({output.confidence:.2f})")

        # Layer 2: narrow gap between 1st and 2nd hypothesis
        if output.confidence_2nd > 0:
            gap = output.confidence - output.confidence_2nd
            if gap < 0.1:
                reasons.append(f"narrow_gap({gap:.2f})")

        # Layer 3: evidence faithfulness (system verification)
        if output.faithfulness_score < 0.5:
            reasons.append(f"low_faithfulness({output.faithfulness_score:.2f})")

        # Layer 4: insufficient evidence count
        if len(output.evidence_chain) < 2:
            reasons.append(f"insufficient_evidence({len(output.evidence_chain)})")

        if reasons:
            output.abstained = True
            output.abstention_reason = "; ".join(reasons)
            logger.info("Abstained: %s", output.abstention_reason)

        return output

    def _call_llm(self, prompt: str) -> tuple[str, dict]:
        """Call LLM and return (response_text, token_counts)."""
        system_prompt = SYSTEM_PROMPT_V2 if self.prompt_version == "v2" else SYSTEM_PROMPT_V1
        max_tokens = 2048 if self.prompt_version == "v2" else 1024

        if self.provider == "anthropic":
            import anthropic
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            tokens = {
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            }
            return text, tokens

        elif self.provider == "openai":
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content
            tokens = {
                "input": response.usage.prompt_tokens,
                "output": response.usage.completion_tokens,
            }
            return text, tokens

        raise ValueError(f"Unknown provider: {self.provider}")

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Parse JSON from LLM response, handling markdown fences."""
        text = text.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)
