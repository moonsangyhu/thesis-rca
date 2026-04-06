"""Shared RCAOutput dataclass for all experiment versions."""
from dataclasses import dataclass, field


@dataclass
class RCAOutput:
    """Structured RCA output from LLM."""
    fault_id: str
    trial: int
    system: str  # "A" or "B"

    # Core diagnosis (all versions)
    identified_fault_type: str = ""
    root_cause: str = ""
    confidence: float = 0.0
    affected_components: list[str] = field(default_factory=list)
    remediation: list[str] = field(default_factory=list)
    detail: str = ""

    # v2+: CoT reasoning
    reasoning: str = ""

    # v3: bilingual
    root_cause_ko: str = ""
    remediation_ko: list[str] = field(default_factory=list)
    detail_ko: str = ""

    # v3: evidence chain + alternatives
    evidence_chain: list[dict] = field(default_factory=list)
    alternative_hypotheses: list[dict] = field(default_factory=list)
    confidence_2nd: float = 0.0

    # v3: harness — evidence verification
    faithfulness_score: float = 0.0

    # v3: harness — evaluator
    eval_evidence_grounding: float = 0.0
    eval_diagnostic_logic: float = 0.0
    eval_differential_completeness: float = 0.0
    eval_confidence_calibration: float = 0.0
    eval_overall_score: float = 0.0
    eval_critique: str = ""
    retry_count: int = 0

    # Correctness evaluation (all versions with ground truth)
    correctness_score: float = 0.0
    correctness_reasoning: str = ""
    correct: int = 0

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
            "reasoning": self.reasoning,
            "root_cause_ko": self.root_cause_ko,
            "remediation_ko": self.remediation_ko,
            "detail_ko": self.detail_ko,
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
            "correctness_score": self.correctness_score,
            "correctness_reasoning": self.correctness_reasoning,
            "correct": self.correct,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "error": self.error,
        }
