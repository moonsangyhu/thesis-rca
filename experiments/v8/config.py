"""v8 experiment configuration: F11/F12 network fault support + extended network metrics."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_CSV = RESULTS_DIR / "experiment_results_v8.csv"
RAW_DIR = RESULTS_DIR / "raw_v8"
GROUND_TRUTH_CSV = RESULTS_DIR / "ground_truth.csv"

MAX_TOKENS = 2048
MAX_RETRIES = 2

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
