"""V2.2 experiment configuration: 5-arm ablation + self-consistency + blinded judge.

V2.2 = measurement reliability + treatment decomposition.
Plan: docs/plans/experiment_plan_v2_2.md.

Derived from v2_1/config.py. Adds:
- 5-arm treatment structure (C1_A .. C5_placebo) with length orthogonalization.
- Generation self-consistency k=3 (temperature=0.7), majority-vote label.
- Blinded judge m=3 (temperature=0, seed=42), median-of-votes score.
- Threshold sweep (0.5 primary / 0.6 / 0.7 robustness).
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_CSV = RESULTS_DIR / "experiment_results_v2_2.csv"
RAW_DIR = RESULTS_DIR / "raw_v2_2"
GROUND_TRUTH_CSV = RESULTS_DIR / "ground_truth.csv"  # reuse existing

MAX_TOKENS = 2048

# ── V2.2 treatment / measurement constants ──
ARMS = ["C1_A", "C2_gitops", "C3_rag", "C4_both", "C5_placebo"]
K_SAMPLES = 3          # generation self-consistency samples
M_JUDGE = 3            # judge votes per representative sample
GEN_TEMPERATURE = 0.7  # generation sampling temperature
JUDGE_TEMPERATURE = 0.0
JUDGE_SEED = 42

# Per-block token budget for GitOps / RAG blocks (length orthogonalization).
# Token ~ chars/4 approximation; 600 tokens ~= 2400 chars per block.
T_BLOCK = 600

THRESHOLDS = [0.5, 0.6, 0.7]
PRIMARY_THRESHOLD = 0.5

# ── CSV schema ──
# v2_1 diagnostic/meta columns retained, "system" replaced by "arm",
# eval_* columns dropped (unused in v2.2 — self-consistency loop only).
CSV_HEADERS = [
    "timestamp", "fault_id", "trial", "arm",
    # majority-vote + self-consistency
    "majority_label",          # k=3 majority-vote diagnostic label
    "gen_labels_json",         # list of k labels
    "gen_agreement",           # majority count / k  (0..1)
    "rep_correctness_score",   # representative score (median of voted scores of majority samples)
    "correctness_scores_json", # per-sample voted scores (list)
    "judge_votes_json",        # representative sample's m=3 raw judge scores
    # threshold sweep
    "correct_at_0.5", "correct_at_0.6", "correct_at_0.7",
    # quality / confound diagnostics
    "low_quality_flag",        # 0/1
    "system_fingerprint",
    "gitops_rag_jaccard",      # 0..1
    # diagnosis / meta (identified_fault_type == majority_label)
    "identified_fault_type",
    "confidence",
    "root_cause",
    "reasoning",
    "latency_ms", "prompt_tokens", "completion_tokens",
    "error",
]
