"""V2.2 RCA engine: self-consistency generation (k=3) + blinded judge (m=3).

Simplification vs v2_1 (documented per plan §3-1): the evaluator/retry loop is
DROPPED in v2.2. We focus measurement budget on self-consistency generation
sampling + a blinded multi-vote correctness judge. No _evaluate / retry here.
"""
import json
import logging
import statistics
import time
from collections import Counter

from experiments.shared.llm_client import BaseLLMClient
from experiments.shared.output import RCAOutput
from experiments.shared.prompts import USER_PROMPT_TEMPLATE, CORRECTNESS_JUDGE_PROMPT
from .prompts import SOP_GUIDED_SYSTEM_PROMPT
from .config import (
    MAX_TOKENS, K_SAMPLES, M_JUDGE, GEN_TEMPERATURE, JUDGE_TEMPERATURE,
    JUDGE_SEED, THRESHOLDS,
)

logger = logging.getLogger(__name__)


class RCAEngineV2_2(BaseLLMClient):
    """5-arm × k=3 generation × m=3 blinded judge."""

    # ── single generation sample (reused from v2_1 _generate, temperature-aware) ──

    def _generate(self, context: str, fault_id: str, trial: int, arm: str) -> RCAOutput:
        output = RCAOutput(
            fault_id=fault_id, trial=trial, system=arm, model=self.model,
        )
        prompt = USER_PROMPT_TEMPLATE.format(context=context)
        start = time.time()
        try:
            raw, tokens = self.call_llm(
                prompt, SOP_GUIDED_SYSTEM_PROMPT, MAX_TOKENS,
                temperature=GEN_TEMPERATURE,
            )
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

    # ── blinded multi-vote correctness judge ──

    def judge_voted_blinded(
        self, output: RCAOutput, ground_truth: dict, m: int = M_JUDGE,
    ) -> tuple[list[float], str]:
        """Score one sample with m blinded judge calls.

        Blinding: the judge input carries ONLY the diagnosis (label + root cause
        + detail + remediation) and the ground truth. No arm identifier, no
        mention of which context/source (GitOps/RAG/observability) produced it.

        Returns (raw_scores, system_fingerprint).
        """
        # Reuse shared CORRECTNESS_JUDGE_PROMPT (same rubric as v2_1).
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
        scores: list[float] = []
        fingerprint = ""
        for _ in range(m):
            try:
                raw, tokens, fp = self._call_judge(judge_input)
                if fp and not fingerprint:
                    fingerprint = fp
                output.prompt_tokens += tokens.get("input", 0)
                output.completion_tokens += tokens.get("output", 0)
                result = self.parse_json(raw)
                scores.append(float(result.get("correctness_score", 0.0)))
            except Exception as e:
                logger.error("Judge vote failed: %s", e)
                scores.append(0.0)
        return scores, fingerprint

    def _call_judge(self, judge_input: str) -> tuple[str, dict, str]:
        """Judge call that also returns system_fingerprint when available.

        Falls back to BaseLLMClient.call_llm semantics for non-openai providers
        (no fingerprint). temperature=0 + seed for best-effort determinism.
        """
        if self.provider == "openai":
            extra = {}
            if JUDGE_TEMPERATURE is not None:
                extra["temperature"] = JUDGE_TEMPERATURE
            if JUDGE_SEED is not None:
                extra["seed"] = JUDGE_SEED
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": CORRECTNESS_JUDGE_PROMPT},
                    {"role": "user", "content": judge_input},
                ],
                max_tokens=512,
                response_format={"type": "json_object"},
                **extra,
            )
            text = response.choices[0].message.content
            tokens = {
                "input": response.usage.prompt_tokens,
                "output": response.usage.completion_tokens,
            }
            fp = getattr(response, "system_fingerprint", "") or ""
            return text, tokens, fp
        # other providers: no fingerprint, no temperature/seed
        raw, tokens = self.call_llm(
            judge_input, CORRECTNESS_JUDGE_PROMPT, 512,
        )
        return raw, tokens, ""

    # ── per-arm analysis ──

    def analyze_arm(
        self, context: str, fault_id: str, trial: int, arm: str, ground_truth: dict,
    ) -> dict:
        """Run k=3 generation + m=3 blinded judge for one arm; return CSV row dict + raw."""
        ground_truth = ground_truth or {}

        # 1) generate k samples
        samples = [
            self._generate(context, fault_id, trial, arm) for _ in range(K_SAMPLES)
        ]

        # 2) majority vote over identified_fault_type (first-sample tie-break)
        labels = [s.identified_fault_type for s in samples]
        majority_label, gen_agreement = self._majority(labels)

        # 3) blinded judge m=3 per sample → voted score = median of raw scores
        per_sample_voted: list[float] = []
        per_sample_votes: list[list[float]] = []
        fingerprint = ""
        for s in samples:
            raw_scores, fp = self.judge_voted_blinded(s, ground_truth, m=M_JUDGE)
            if fp and not fingerprint:
                fingerprint = fp
            voted = statistics.median(raw_scores) if raw_scores else 0.0
            per_sample_voted.append(round(float(voted), 4))
            per_sample_votes.append([round(float(x), 4) for x in raw_scores])

        # 4) representative score = median of voted scores of majority-label samples
        rep_indices = [i for i, lab in enumerate(labels) if lab == majority_label]
        rep_scores = [per_sample_voted[i] for i in rep_indices] or per_sample_voted
        rep_correctness_score = (
            round(float(statistics.median(rep_scores)), 4) if rep_scores else 0.0
        )
        # representative sample = first majority-label sample
        rep_idx = rep_indices[0] if rep_indices else 0
        rep_sample = samples[rep_idx]
        judge_votes = per_sample_votes[rep_idx] if per_sample_votes else []

        correct_at = {
            t: (1 if rep_correctness_score >= t else 0) for t in THRESHOLDS
        }

        # aggregate metadata
        total_latency = sum(s.latency_ms for s in samples)
        total_prompt = sum(s.prompt_tokens for s in samples)
        total_completion = sum(s.completion_tokens for s in samples)
        errors = [s.error for s in samples if s.error]

        row = {
            "fault_id": fault_id,
            "trial": trial,
            "arm": arm,
            "majority_label": majority_label,
            "gen_labels_json": json.dumps(labels, ensure_ascii=False),
            "gen_agreement": round(gen_agreement, 4),
            "rep_correctness_score": rep_correctness_score,
            "correctness_scores_json": json.dumps(per_sample_voted),
            "judge_votes_json": json.dumps(judge_votes),
            "correct_at_0.5": correct_at[0.5],
            "correct_at_0.6": correct_at[0.6],
            "correct_at_0.7": correct_at[0.7],
            "system_fingerprint": fingerprint,
            "identified_fault_type": majority_label,
            "confidence": round(float(rep_sample.confidence), 4),
            "root_cause": rep_sample.root_cause,
            "reasoning": rep_sample.reasoning,
            "latency_ms": total_latency,
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "error": "; ".join(errors),
        }

        raw = {
            "fault_id": fault_id,
            "trial": trial,
            "arm": arm,
            "majority_label": majority_label,
            "gen_agreement": round(gen_agreement, 4),
            "rep_correctness_score": rep_correctness_score,
            "context": context,
            "samples": [
                {
                    "label": s.identified_fault_type,
                    "confidence": s.confidence,
                    "root_cause": s.root_cause,
                    "voted_score": per_sample_voted[i],
                    "judge_raw_scores": per_sample_votes[i],
                    "raw_response": s.raw_response,
                    "error": s.error,
                }
                for i, s in enumerate(samples)
            ],
            "system_fingerprint": fingerprint,
        }
        return {"row": row, "raw": raw}

    # ── helpers ──

    @staticmethod
    def _majority(labels: list[str]) -> tuple[str, float]:
        """Majority-vote label with first-sample deterministic tie-break."""
        if not labels:
            return "", 0.0
        counts = Counter(labels)
        top = counts.most_common(1)[0][1]
        # tie-break: pick the first label (in original order) reaching top count
        winners = {lab for lab, c in counts.items() if c == top}
        majority = next(lab for lab in labels if lab in winners)
        agreement = top / len(labels)
        return majority, agreement
