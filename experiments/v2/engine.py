"""v2 RCA engine: 힌트 제거 + CoT reasoning."""
import logging
import time

from experiments.shared.llm_client import BaseLLMClient
from experiments.shared.output import RCAOutput
from experiments.shared.prompts import USER_PROMPT_TEMPLATE
from .prompts import SYSTEM_PROMPT
from .config import MAX_TOKENS

logger = logging.getLogger(__name__)


class RCAEngineV2(BaseLLMClient):
    """v2: 장애 힌트 없음, CoT 추론, harness 없음."""

    def analyze(
        self,
        context: str,
        fault_id: str = "",
        trial: int = 0,
        system: str = "A",
        ground_truth: dict = None,
    ) -> RCAOutput:
        output = self._generate(context, fault_id, trial, system)
        if ground_truth:
            self.judge_correctness(output, ground_truth)
        return output

    def _generate(
        self, context: str, fault_id: str, trial: int, system: str,
    ) -> RCAOutput:
        output = RCAOutput(
            fault_id=fault_id, trial=trial, system=system, model=self.model,
        )
        prompt = USER_PROMPT_TEMPLATE.format(context=context)

        start = time.time()
        try:
            raw, tokens = self.call_llm(prompt, SYSTEM_PROMPT, MAX_TOKENS)
            output.latency_ms = int((time.time() - start) * 1000)
            output.raw_response = raw
            output.prompt_tokens = tokens.get("input", 0)
            output.completion_tokens = tokens.get("output", 0)

            parsed = self.parse_json(raw)
            output.identified_fault_type = parsed.get("identified_fault_type", "")
            output.root_cause = parsed.get("root_cause", "")
            output.confidence = float(parsed.get("confidence", 0.0))
            output.affected_components = parsed.get("affected_components", [])
            output.remediation = parsed.get("remediation", [])
            output.detail = parsed.get("detail", "")
            output.reasoning = parsed.get("reasoning", "")

        except Exception as e:
            output.latency_ms = int((time.time() - start) * 1000)
            output.error = str(e)
            logger.error("Generator failed: %s", e)

        return output
