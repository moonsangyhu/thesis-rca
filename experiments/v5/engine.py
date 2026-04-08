"""v5 RCA engine: 2-stage Symptom Extraction -> Diagnosis pipeline."""
import json
import logging
import time

from experiments.shared.llm_client import BaseLLMClient
from experiments.shared.output import RCAOutput
from experiments.shared.prompts import USER_PROMPT_TEMPLATE
from .prompts import (
    SYMPTOM_EXTRACTION_PROMPT,
    DIAGNOSIS_PROMPT,
    EVALUATOR_PROMPT,
    RETRY_PROMPT_TEMPLATE,
)
from .config import (
    MAX_TOKENS_EXTRACTION,
    MAX_TOKENS_DIAGNOSIS,
    MAX_RETRIES,
    RETRY_ENABLED_A,
    RETRY_ENABLED_B,
    EXTRACTION_FALLBACK_MIN_SIGNALS,
)

logger = logging.getLogger(__name__)


class RCAEngineV5(BaseLLMClient):
    """v5: 2-stage pipeline — Symptom Extraction then Diagnosis."""

    def analyze(
        self,
        context: str,
        fault_id: str = "",
        trial: int = 0,
        system: str = "A",
        ground_truth: dict = None,
    ) -> RCAOutput:
        # Step 1: Symptom Extraction
        symptoms, ext_prompt_tokens, ext_comp_tokens = self._extract_symptoms(context)

        # Fallback: low signal count → V3-style direct diagnosis
        total_signals = symptoms.get("signal_count_summary", {}).get("total_signals", 0)
        if total_signals < EXTRACTION_FALLBACK_MIN_SIGNALS:
            logger.warning(
                "Low signal count (%d < %d), falling back to direct diagnosis",
                total_signals,
                EXTRACTION_FALLBACK_MIN_SIGNALS,
            )
            output = self._direct_diagnose(context, fault_id, trial, system)
            output.prompt_tokens += ext_prompt_tokens
            output.completion_tokens += ext_comp_tokens
            if ground_truth:
                self.judge_correctness(output, ground_truth)
            return output

        logger.info(
            "Extraction: %d signals (%d critical)",
            total_signals,
            symptoms.get("signal_count_summary", {}).get("critical", 0),
        )

        # Step 2: Diagnosis from extracted symptoms
        output = self._diagnose(symptoms, fault_id, trial, system)
        output.prompt_tokens += ext_prompt_tokens
        output.completion_tokens += ext_comp_tokens

        # Step 3: Evidence Verification — SKIP (V3: constant 1.0)
        output.faithfulness_score = 0.0

        # Step 4: Evaluate (against original context)
        eval_result = self._evaluate(context, output)
        output = self._apply_eval(output, eval_result)

        # Step 5: Retry loop (System B only)
        retry_enabled = RETRY_ENABLED_B if system == "B" else RETRY_ENABLED_A
        retry_count = 0
        while eval_result.get("should_retry") and retry_count < MAX_RETRIES and retry_enabled:
            retry_count += 1
            logger.info(
                "Retry %d/%d [%s]: eval_score=%.1f, critique=%s",
                retry_count,
                MAX_RETRIES,
                system,
                eval_result.get("overall_score", 0),
                str(eval_result.get("critique", ""))[:100],
            )
            output = self._diagnose_with_feedback(
                symptoms, fault_id, trial, system, eval_result,
            )
            output.prompt_tokens += ext_prompt_tokens
            output.completion_tokens += ext_comp_tokens
            output.retry_count = retry_count

            eval_result = self._evaluate(context, output)
            output = self._apply_eval(output, eval_result)

        # Step 6: Correctness judge
        if ground_truth:
            self.judge_correctness(output, ground_truth)

        return output

    # ── Step 1: Symptom Extraction ───────────────────────────

    def _extract_symptoms(self, context: str) -> tuple[dict, int, int]:
        """Extract structured symptoms from raw context. Returns (symptoms, prompt_tokens, comp_tokens)."""
        prompt = USER_PROMPT_TEMPLATE.format(context=context)

        try:
            raw, tokens = self.call_llm(
                prompt, SYMPTOM_EXTRACTION_PROMPT, MAX_TOKENS_EXTRACTION,
            )
            symptoms = self.parse_json(raw)

            # Ensure signal_count_summary exists
            if "signal_count_summary" not in symptoms:
                total = 0
                for key in ["pod_anomalies", "node_anomalies", "metric_anomalies",
                            "event_anomalies", "log_anomalies", "gitops_changes"]:
                    items = symptoms.get(key, [])
                    if key in ("pod_anomalies", "node_anomalies"):
                        for item in items:
                            total += len(item.get("signals", []))
                    else:
                        total += len(items)
                symptoms["signal_count_summary"] = {"total_signals": total}

            return symptoms, tokens.get("input", 0), tokens.get("output", 0)

        except Exception as e:
            logger.error("Symptom extraction failed: %s", e)
            return {"signal_count_summary": {"total_signals": 0}}, 0, 0

    # ── Step 2: Diagnosis ────────────────────────────────────

    def _diagnose(
        self, symptoms: dict, fault_id: str, trial: int, system: str,
    ) -> RCAOutput:
        """Diagnose from structured symptoms."""
        output = RCAOutput(
            fault_id=fault_id, trial=trial, system=system, model=self.model,
        )
        symptoms_text = json.dumps(symptoms, indent=2, ensure_ascii=False)
        prompt = f"## Structured Symptom Report\n\n{symptoms_text}"

        start = time.time()
        try:
            raw, tokens = self.call_llm(prompt, DIAGNOSIS_PROMPT, MAX_TOKENS_DIAGNOSIS)
            output.latency_ms = int((time.time() - start) * 1000)
            output.raw_response = raw
            output.prompt_tokens = tokens.get("input", 0)
            output.completion_tokens = tokens.get("output", 0)
            self._parse_rca_output(raw, output)
        except Exception as e:
            output.latency_ms = int((time.time() - start) * 1000)
            output.error = str(e)
            logger.error("Diagnosis failed: %s", e)

        return output

    def _diagnose_with_feedback(
        self,
        symptoms: dict,
        fault_id: str,
        trial: int,
        system: str,
        eval_result: dict,
    ) -> RCAOutput:
        """Re-diagnose with evaluator feedback (retry)."""
        output = RCAOutput(
            fault_id=fault_id, trial=trial, system=system, model=self.model,
        )
        symptoms_text = json.dumps(symptoms, indent=2, ensure_ascii=False)
        prompt = RETRY_PROMPT_TEMPLATE.format(
            critique=eval_result.get("critique", ""),
            evidence_grounding=eval_result.get("evidence_grounding", "?"),
            diagnostic_logic=eval_result.get("diagnostic_logic", "?"),
            differential_completeness=eval_result.get("differential_completeness", "?"),
            confidence_calibration=eval_result.get("confidence_calibration", "?"),
            symptoms=symptoms_text,
        )

        start = time.time()
        try:
            raw, tokens = self.call_llm(prompt, DIAGNOSIS_PROMPT, MAX_TOKENS_DIAGNOSIS)
            output.latency_ms = int((time.time() - start) * 1000)
            output.raw_response = raw
            output.prompt_tokens = tokens.get("input", 0)
            output.completion_tokens = tokens.get("output", 0)
            self._parse_rca_output(raw, output)
        except Exception as e:
            output.latency_ms = int((time.time() - start) * 1000)
            output.error = str(e)
            logger.error("Diagnosis retry failed: %s", e)

        return output

    # ── Fallback: V3-style direct diagnosis ──────────────────

    def _direct_diagnose(
        self, context: str, fault_id: str, trial: int, system: str,
    ) -> RCAOutput:
        """Fallback: V3-style single-prompt diagnosis."""
        from experiments.v3.prompts import SYSTEM_PROMPT as V3_SYSTEM_PROMPT

        output = RCAOutput(
            fault_id=fault_id, trial=trial, system=system, model=self.model,
        )
        prompt = USER_PROMPT_TEMPLATE.format(context=context)

        start = time.time()
        try:
            raw, tokens = self.call_llm(prompt, V3_SYSTEM_PROMPT, MAX_TOKENS_DIAGNOSIS)
            output.latency_ms = int((time.time() - start) * 1000)
            output.raw_response = raw
            output.prompt_tokens = tokens.get("input", 0)
            output.completion_tokens = tokens.get("output", 0)
            self._parse_rca_output(raw, output)
        except Exception as e:
            output.latency_ms = int((time.time() - start) * 1000)
            output.error = str(e)
            logger.error("Direct diagnosis fallback failed: %s", e)

        # Evaluate + retry (same as V3)
        eval_result = self._evaluate(context, output)
        output = self._apply_eval(output, eval_result)

        retry_enabled = RETRY_ENABLED_B if system == "B" else RETRY_ENABLED_A
        retry_count = 0
        while eval_result.get("should_retry") and retry_count < MAX_RETRIES and retry_enabled:
            retry_count += 1
            # Retry with V3 prompt
            retry_prompt = RETRY_PROMPT_TEMPLATE.format(
                critique=eval_result.get("critique", ""),
                evidence_grounding=eval_result.get("evidence_grounding", "?"),
                diagnostic_logic=eval_result.get("diagnostic_logic", "?"),
                differential_completeness=eval_result.get("differential_completeness", "?"),
                confidence_calibration=eval_result.get("confidence_calibration", "?"),
                symptoms=context,
            )
            try:
                raw, tokens = self.call_llm(retry_prompt, V3_SYSTEM_PROMPT, MAX_TOKENS_DIAGNOSIS)
                output.raw_response = raw
                output.prompt_tokens += tokens.get("input", 0)
                output.completion_tokens += tokens.get("output", 0)
                output.retry_count = retry_count
                self._parse_rca_output(raw, output)
            except Exception as e:
                output.error = str(e)
                logger.error("Direct diagnosis retry failed: %s", e)
                break
            eval_result = self._evaluate(context, output)
            output = self._apply_eval(output, eval_result)

        output.faithfulness_score = 0.0
        return output

    # ── Evaluator (V3 identical, uses original context) ──────

    def _evaluate(self, context: str, output: RCAOutput) -> dict:
        """Evaluate diagnosis against original context."""
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
            output.eval_overall_score,
            eval_result.get("should_retry"),
        )
        return output

    # ── Helpers ───────────────────────────────────────────────

    def _parse_rca_output(self, raw: str, output: RCAOutput) -> None:
        """Parse LLM JSON response into RCAOutput fields."""
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
