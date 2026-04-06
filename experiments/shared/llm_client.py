"""Base LLM client with shared call/parse/judge logic."""
import json
import logging
import time

from .output import RCAOutput
from .prompts import USER_PROMPT_TEMPLATE, CORRECTNESS_JUDGE_PROMPT

logger = logging.getLogger(__name__)


class BaseLLMClient:
    """Shared LLM plumbing: API call, JSON parse, correctness judge."""

    def __init__(self, model: str = "claude-sonnet-4-6", provider: str = "anthropic"):
        self.model = model
        self.provider = provider
        self._client = self._init_client()

    def _init_client(self):
        if self.provider == "anthropic":
            import anthropic
            return anthropic.Anthropic()
        elif self.provider == "openai":
            from openai import OpenAI
            return OpenAI()
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    def call_llm(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> tuple[str, dict]:
        """Call LLM and return (response_text, token_counts)."""
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
    def parse_json(text: str) -> dict:
        """Parse JSON from LLM response, handling markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)

    def judge_correctness(
        self, output: RCAOutput, ground_truth: dict,
    ) -> None:
        """LLM-as-judge: evaluate correctness against ground truth. Mutates output."""
        judge_input = (
            f"## Ground Truth\n"
            f"- Root Cause: {ground_truth.get('expected_root_cause', '')}\n"
            f"- Fault Name: {ground_truth.get('fault_name', '')}\n"
            f"- Injection Method: {ground_truth.get('injection_method', '')}\n"
            f"- Expected Symptoms: {ground_truth.get('primary_symptoms', '')}\n"
            f"- Expected Recovery: {ground_truth.get('expected_recovery_action', '')}\n\n"
            f"## LLM Diagnosis\n"
            f"- Diagnostic Label: {output.identified_fault_type}\n"
            f"- Root Cause: {output.root_cause}\n"
            f"- Detail: {output.detail}\n"
            f"- Remediation: {output.remediation}\n"
        )
        try:
            raw, tokens = self.call_llm(
                judge_input, system_prompt=CORRECTNESS_JUDGE_PROMPT, max_tokens=512,
            )
            output.prompt_tokens += tokens.get("input", 0)
            output.completion_tokens += tokens.get("output", 0)
            result = self.parse_json(raw)
            output.correctness_score = float(result.get("correctness_score", 0.0))
            output.correctness_reasoning = result.get("reasoning", "")
            output.correct = 1 if output.correctness_score >= 0.5 else 0
        except Exception as e:
            logger.error("Correctness judge failed: %s", e)
            output.correctness_score = 0.0
            output.correctness_reasoning = str(e)
