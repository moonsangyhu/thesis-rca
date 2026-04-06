"""v2 experiment configuration."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_CSV = RESULTS_DIR / "experiment_results_v2.csv"
RAW_DIR = RESULTS_DIR / "raw"
GROUND_TRUTH_CSV = RESULTS_DIR / "ground_truth.csv"

MAX_TOKENS = 2048

CSV_HEADERS = [
    "timestamp", "fault_id", "trial", "system",
    "identified_fault_type", "correct",
    "correctness_score", "correctness_reasoning",
    "root_cause", "confidence",
    "affected_components", "remediation",
    "detail", "reasoning",
    "model", "latency_ms", "prompt_tokens", "completion_tokens",
    "error",
]
