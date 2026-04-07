"""v4 RCA engine: CoT + Fault Layer + Evaluator + Retry (System B only), no Evidence Verification."""
import json
import logging
import time

from experiments.shared.llm_client import BaseLLMClient
from experiments.shared.output import RCAOutput
from experiments.shared.prompts import USER_PROMPT_TEMPLATE
from .prompts import SYSTEM_PROMPT, EVALUATOR_PROMPT, RETRY_PROMPT_TEMPLATE
from .config import MAX_TOKENS, MAX_RETRIES, RETRY_ENABLED_A, RETRY_ENABLED_B

logger = logging.getLogger(__name__)


class RCAEngineV4(BaseLLMClient):
    """v4: Fault Layer prompt + anomaly-first context + simplified harness."""

    def analyze(
        self,
        context: str,
        fault_id: str = "",
        trial: int = 0,
        system: str = "A",
        ground_truth: dict = None,
    ) -> RCAOutput:
        # Step 1: Generator
        output = self._generate(context, fault_id, trial, system)

        # Step 2: Evidence Verification REMOVED (V3 showed faithfulness=1.0 constant)
        output.faithfulness_score = 0.0

        # Step 3: Evaluator (kept for both systems — data collection)
        eval_result = self._evaluate(context, output)
        output = self._apply_eval(output, eval_result)

        # Step 4: Retry loop (System B only — V3 showed A retry = -12.2pp)
        retry_enabled = RETRY_ENABLED_B if system == "B" else RETRY_ENABLED_A
        retry_count = 0
        while retry_enabled and eval_result.get("should_retry") and retry_count < MAX_RETRIES:
            retry_count += 1
            logger.info(
                "Retry %d/%d [%s]: eval_score=%.1f, critique=%s",
                retry_count, MAX_RETRIES, system,
                eval_result.get("overall_score", 0),
                str(eval_result.get("critique", ""))[:100],
            )
            output = self._generate_with_feedback(
                context, fault_id, trial, system, eval_result,
            )
            output.retry_count = retry_count
            output.faithfulness_score = 0.0

            eval_result = self._evaluate(context, output)
            output = self._apply_eval(output, eval_result)

        # Final: Correctness judge
        if ground_truth:
            self.judge_correctness(output, ground_truth)

        return output

    # ── Generator ────────────────────────────────────────────

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
            output.root_cause_ko = parsed.get("root_cause_ko", "")
            output.remediation_ko = parsed.get("remediation_ko", [])
            output.detail_ko = parsed.get("detail_ko", "")
            output.confidence_2nd = float(parsed.get("confidence_2nd", 0.0))
            output.evidence_chain = parsed.get("evidence_chain", [])
            output.alternative_hypotheses = parsed.get("alternative_hypotheses", [])

        except Exception as e:
            output.latency_ms = int((time.time() - start) * 1000)
            output.error = str(e)
            logger.error("Generator failed: %s", e)

        return output

    def _generate_with_feedback(
        self,
        context: str,
        fault_id: str,
        trial: int,
        system: str,
        eval_result: dict,
    ) -> RCAOutput:
        """Re-analyze with evaluator critique as feedback."""
        output = RCAOutput(
            fault_id=fault_id, trial=trial, system=system, model=self.model,
        )
        prompt = RETRY_PROMPT_TEMPLATE.format(
            critique=eval_result.get("critique", ""),
            evidence_grounding=eval_result.get("evidence_grounding", "?"),
            diagnostic_logic=eval_result.get("diagnostic_logic", "?"),
            differential_completeness=eval_result.get("differential_completeness", "?"),
            confidence_calibration=eval_result.get("confidence_calibration", "?"),
            context=context,
        )

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
            output.root_cause_ko = parsed.get("root_cause_ko", "")
            output.remediation_ko = parsed.get("remediation_ko", [])
            output.detail_ko = parsed.get("detail_ko", "")
            output.confidence_2nd = float(parsed.get("confidence_2nd", 0.0))
            output.evidence_chain = parsed.get("evidence_chain", [])
            output.alternative_hypotheses = parsed.get("alternative_hypotheses", [])

        except Exception as e:
            output.latency_ms = int((time.time() - start) * 1000)
            output.error = str(e)
            logger.error("Generator retry failed: %s", e)

        return output

    # ── Evaluator ────────────────────────────────────────────

    def _evaluate(self, context: str, output: RCAOutput) -> dict:
        """Independent evaluator: assess diagnosis quality."""
        eval_input = (
            f"## Original Diagnostic Context\n{context}\n\n"
            f"## RCA Diagnosis to Evaluate\n"
            f"- Identified Fault Type: {output.identified_fault_type}\n"
            f"- Confidence: {output.confidence}\n"
            f"- Root Cause: {output.root_cause}\n"
            f"- Reasoning: {output.reasoning}\n"
            f"- Evidence Chain: {json.dumps(output.evidence_chain, ensure_ascii=False)}\n"
            f"- Alternative Hypotheses: {json.dumps(output.alternative_hypotheses, ensure_ascii=False)}\n"
            f"- Remediation: {output.remediation}\n\n"
            f"Evaluate this diagnosis against the original context."
        )

        try:
            raw, tokens = self.call_llm(eval_input, EVALUATOR_PROMPT, 1024)
            output.prompt_tokens += tokens.get("input", 0)
            output.completion_tokens += tokens.get("output", 0)
            return self.parse_json(raw)
        except Exception as e:
            logger.error("Evaluator failed: %s", e)
            return {"overall_score": 0, "should_retry": False, "critique": str(e)}

    def _apply_eval(self, output: RCAOutput, eval_result: dict) -> RCAOutput:
        """Apply evaluator scores to output."""
        output.eval_evidence_grounding = float(eval_result.get("evidence_grounding", 0))
        output.eval_diagnostic_logic = float(eval_result.get("diagnostic_logic", 0))
        output.eval_differential_completeness = float(eval_result.get("differential_completeness", 0))
        output.eval_confidence_calibration = float(eval_result.get("confidence_calibration", 0))
        output.eval_overall_score = float(eval_result.get("overall_score", 0))
        output.eval_critique = eval_result.get("critique", "")
        logger.info(
            "Evaluator: overall=%.1f, should_retry=%s",
            output.eval_overall_score, eval_result.get("should_retry"),
        )
        return output
