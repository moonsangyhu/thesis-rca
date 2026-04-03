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

    # v2: harness — evidence verification
    faithfulness_score: float = 0.0

    # v2: harness — evaluator
    eval_evidence_grounding: float = 0.0
    eval_diagnostic_logic: float = 0.0
    eval_differential_completeness: float = 0.0
    eval_confidence_calibration: float = 0.0
    eval_overall_score: float = 0.0
    eval_critique: str = ""
    retry_count: int = 0

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
            "faithfulness_score": self.faithfulness_score,
            "eval_evidence_grounding": self.eval_evidence_grounding,
            "eval_diagnostic_logic": self.eval_diagnostic_logic,
            "eval_differential_completeness": self.eval_differential_completeness,
            "eval_confidence_calibration": self.eval_confidence_calibration,
            "eval_overall_score": self.eval_overall_score,
            "eval_critique": self.eval_critique,
            "retry_count": self.retry_count,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "error": self.error,
        }


# ── Prompts ──────────────────────────────────────────────────

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

EVALUATOR_PROMPT = """\
You are an independent evaluator reviewing a Kubernetes root cause analysis.

You will receive:
1. The original diagnostic context (input signals)
2. An RCA diagnosis produced by another AI system

Your job is to evaluate the diagnosis quality on these criteria:

## Scoring Criteria (1-10 scale)
- **Evidence Grounding (1-10)**: Does each cited evidence actually appear in the input context? Are quotes accurate?
- **Diagnostic Logic (1-10)**: Does the reasoning chain logically connect signals to the conclusion?
- **Differential Completeness (1-10)**: Were alternative hypotheses properly considered and rejected with specific reasons?
- **Confidence Calibration (1-10)**: Is the stated confidence appropriate given the strength of evidence?

## Scoring Guide (calibration examples)
- Score 9-10: All evidence verifiable, logic is airtight, alternatives properly ruled out
- Score 7-8: Most evidence verifiable, logic sound with minor gaps
- Score 5-6: Some evidence unverifiable or logic has gaps, alternatives superficially addressed
- Score 1-4: Significant hallucinated evidence, logical leaps, or missed obvious alternatives

## Few-Shot Calibration Examples

### Example 1: Good diagnosis (score 8-9)
Input context mentions: "cartservice pod OOMKilled, memory_working_set=31.8Mi/32Mi, exit code 137"
Diagnosis: "F1 OOMKilled, confidence 0.95"
Evidence cited: "container_memory_working_set=31.8Mi exceeding 32Mi limit", "OOMKilled 3 events"
→ Evidence Grounding: 9 (all evidence found in input)
→ Diagnostic Logic: 9 (OOMKilled reason + memory metric directly confirms F1)
→ Differential: 8 (ruled out F2 because restart reason is OOM not code error)
→ Calibration: 9 (0.95 appropriate for unambiguous OOMKilled)
→ Overall: 8.75, should_retry: false

### Example 2: Poor diagnosis (score 3-4)
Input context mentions: "cartservice CrashLoopBackOff, BackOff events, no OOMKilled reason visible"
Diagnosis: "F1 OOMKilled, confidence 0.9"
Evidence cited: "memory pressure on node" (NOT in input), "OOMKilled events" (NOT in input)
→ Evidence Grounding: 3 (key evidence fabricated)
→ Diagnostic Logic: 4 (conclusion contradicts available signals)
→ Differential: 5 (did not consider F2 which better matches CrashLoopBackOff)
→ Calibration: 3 (0.9 confidence with fabricated evidence is severe overconfidence)
→ Overall: 3.75, should_retry: true
→ Critique: "Evidence 'OOMKilled events' not found in input. Input shows CrashLoopBackOff, not OOMKilled. Consider F2. Confidence should be much lower."

## Critique Requirements
If score < 7 on any criterion, provide SPECIFIC, ACTIONABLE critique:
- Which evidence was NOT found in the input?
- Which logical step was weak?
- Which alternative hypothesis was inadequately addressed?

Output ONLY valid JSON:
{
  "evidence_grounding": 8,
  "diagnostic_logic": 7,
  "differential_completeness": 6,
  "confidence_calibration": 8,
  "overall_score": 7.25,
  "critique": "Specific actionable feedback for the generator to improve...",
  "should_retry": true
}
"""

RETRY_PROMPT_TEMPLATE = """\
Your previous analysis was reviewed by an independent evaluator. Here is their feedback:

## Evaluator Critique
{critique}

## Evaluator Scores
- Evidence Grounding: {evidence_grounding}/10
- Diagnostic Logic: {diagnostic_logic}/10
- Differential Completeness: {differential_completeness}/10
- Confidence Calibration: {confidence_calibration}/10

Please re-analyze the SAME diagnostic context below, addressing the evaluator's critique.
Pay special attention to the weak areas identified above.

{context}

Provide your revised analysis as JSON only.
"""

USER_PROMPT_TEMPLATE = """\
Analyze the following Kubernetes cluster diagnostic context and identify the root cause.

{context}

Provide your analysis as JSON only.
"""


# ── Engine ───────────────────────────────────────────────────

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

    # ── Public API ───────────────────────────────────────────

    def analyze(
        self,
        context: str,
        fault_id: str = "",
        trial: int = 0,
        system: str = "A",
    ) -> RCAOutput:
        """Run RCA analysis with optional harness (v2)."""
        # Step 1: Generator
        output = self._generate(context, fault_id, trial, system)

        if self.prompt_version != "v2":
            return output

        # Step 2: Evidence 교차검증 (system sensor)
        output.evidence_chain, output.faithfulness_score = (
            self._verify_evidence(output.evidence_chain, context)
        )

        # Step 3: Evaluator (independent LLM sensor)
        eval_result = self._evaluate(context, output)
        output = self._apply_eval(output, eval_result)

        # Step 4: Retry loop (iterative feedback)
        max_retries = 2
        while eval_result.get("should_retry") and output.retry_count < max_retries:
            logger.info(
                "Retry %d: eval_score=%.1f, critique=%s",
                output.retry_count + 1,
                eval_result.get("overall_score", 0),
                str(eval_result.get("critique", ""))[:100],
            )
            # Re-generate with evaluator critique as feedback
            output = self._generate_with_feedback(
                context, fault_id, trial, system, eval_result,
            )
            output.retry_count += 1

            # Re-verify evidence
            output.evidence_chain, output.faithfulness_score = (
                self._verify_evidence(output.evidence_chain, context)
            )

            # Re-evaluate
            eval_result = self._evaluate(context, output)
            output = self._apply_eval(output, eval_result)

        return output

    # ── Generator ────────────────────────────────────────────

    def _generate(
        self, context: str, fault_id: str, trial: int, system: str,
    ) -> RCAOutput:
        """Generator LLM: produce RCA diagnosis."""
        output = RCAOutput(
            fault_id=fault_id, trial=trial, system=system, model=self.model,
        )
        prompt = USER_PROMPT_TEMPLATE.format(context=context)

        start = time.time()
        try:
            raw, tokens = self._call_llm(prompt)
            output.latency_ms = int((time.time() - start) * 1000)
            output.raw_response = raw
            output.prompt_tokens = tokens.get("input", 0)
            output.completion_tokens = tokens.get("output", 0)

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
        """Generator retry: re-analyze with evaluator critique as feedback."""
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
            raw, tokens = self._call_llm(prompt)
            output.latency_ms = int((time.time() - start) * 1000)
            output.raw_response = raw
            output.prompt_tokens = tokens.get("input", 0)
            output.completion_tokens = tokens.get("output", 0)

            parsed = self._parse_json(raw)
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
        """Evaluator LLM: independently assess Generator's diagnosis."""
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
            raw, tokens = self._call_llm(
                eval_input, system_prompt=EVALUATOR_PROMPT, max_tokens=1024,
            )
            # Accumulate tokens
            output.prompt_tokens += tokens.get("input", 0)
            output.completion_tokens += tokens.get("output", 0)
            return self._parse_json(raw)
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

    # ── Harness: Evidence Verification (system sensor) ───────

    def _verify_evidence(
        self, evidence_chain: list[dict], input_context: str,
    ) -> tuple[list[dict], float]:
        """Verify that LLM-cited evidence actually exists in the input."""
        if not evidence_chain:
            return evidence_chain, 0.0

        verified = []
        for ev in evidence_chain:
            content = ev.get("content", "")
            source = ev.get("source", "")
            check_text = f"{content} {source}"
            keywords = [w for w in check_text.split() if len(w) > 3]
            if not keywords:
                verified.append(dict(ev, verified=False, match_ratio=0.0))
                continue
            match_count = sum(
                1 for kw in keywords if kw.lower() in input_context.lower()
            )
            match_ratio = match_count / len(keywords)
            verified.append(dict(
                ev, verified=match_ratio >= 0.5, match_ratio=round(match_ratio, 2),
            ))

        faithfulness = sum(1 for e in verified if e["verified"]) / len(verified)
        logger.info(
            "Evidence verification: %d/%d verified (faithfulness=%.2f)",
            sum(1 for e in verified if e["verified"]), len(verified), faithfulness,
        )
        return verified, round(faithfulness, 2)

    # ── LLM Call ─────────────────────────────────────────────

    def _call_llm(
        self,
        prompt: str,
        system_prompt: str = None,
        max_tokens: int = None,
    ) -> tuple[str, dict]:
        """Call LLM and return (response_text, token_counts)."""
        if system_prompt is None:
            system_prompt = SYSTEM_PROMPT_V2 if self.prompt_version == "v2" else SYSTEM_PROMPT_V1
        if max_tokens is None:
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
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)
