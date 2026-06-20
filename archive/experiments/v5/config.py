"""v5 experiment configuration: 2-stage Symptom Extraction -> Diagnosis."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_CSV = RESULTS_DIR / "experiment_results_v5.csv"
RAW_DIR = RESULTS_DIR / "raw_v5"
GROUND_TRUTH_CSV = RESULTS_DIR / "ground_truth.csv"

# Step 1: Symptom Extraction
MAX_TOKENS_EXTRACTION = 1536

# Step 2: Diagnosis
MAX_TOKENS_DIAGNOSIS = 2048

# Retry
MAX_RETRIES = 2
RETRY_ENABLED_A = False
RETRY_ENABLED_B = True

# Fallback: extraction signal count가 이 값 미만이면 V3 방식으로 전환
EXTRACTION_FALLBACK_MIN_SIGNALS = 3

CSV_HEADERS = [
    "timestamp", "fault_id", "trial", "system",
    "identified_fault_type", "correct",
    "correctness_score", "correctness_reasoning",
    "root_cause", "root_cause_ko",
    "confidence", "confidence_2nd",
    "affected_components",
    "remediation", "remediation_ko",
    "detail", "detail_ko",
    "reasoning",
    "evidence_chain", "alternative_hypotheses",
    "faithfulness_score",
    "eval_evidence_grounding", "eval_diagnostic_logic",
    "eval_differential_completeness", "eval_confidence_calibration",
    "eval_overall_score", "eval_critique", "retry_count",
    "model", "latency_ms", "prompt_tokens", "completion_tokens",
    "error",
]
