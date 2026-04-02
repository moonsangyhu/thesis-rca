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
            "model": self.model,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "error": self.error,
        }


SYSTEM_PROMPT = """\
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
    ):
        self.model = model
        self.provider = provider
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

        except Exception as e:
            output.latency_ms = int((time.time() - start) * 1000)
            output.error = str(e)
            logger.error("RCA analysis failed: %s", e)

        return output

    def _call_llm(self, prompt: str) -> tuple[str, dict]:
        """Call LLM and return (response_text, token_counts)."""
        if self.provider == "anthropic":
            import anthropic
            response = self._client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
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
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1024,
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
