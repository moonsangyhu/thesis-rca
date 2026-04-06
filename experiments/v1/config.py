"""v1 experiment configuration."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_CSV = RESULTS_DIR / "experiment_results.csv"
RAW_DIR = RESULTS_DIR / "raw"
GROUND_TRUTH_CSV = RESULTS_DIR / "ground_truth.csv"

MAX_TOKENS = 1024

CSV_HEADERS = [
    "timestamp", "fault_id", "trial", "system",
    "identified_fault_type", "correct", "root_cause",
    "confidence", "affected_components", "remediation",
    "model", "latency_ms", "prompt_tokens", "completion_tokens",
    "error",
]
