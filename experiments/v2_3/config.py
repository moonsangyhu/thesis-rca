"""Frozen V2.3 constants used by the offline review harness."""

EXPERIMENT = "v2.3"
REQUESTED_MODEL = "gpt-5.6-terra"
PROVIDER = "codex-cli-chatgpt-subscription"

CONDITIONS = ("runtime", "length_placebo", "blind_procedural_rag")
FAULTS = tuple(f"F{i}" for i in range(1, 13))
TRIALS = (1, 2, 3, 4, 5)
K_GENERATIONS = 3
M_JUDGES = 3
GENERATOR_OUTPUT_LIMIT = 2048
JUDGE_OUTPUT_LIMIT = 512
PRIMARY_THRESHOLD = 0.5
ROBUSTNESS_THRESHOLDS = (0.6, 0.7)
SCHEDULE_SEED = 20260809
PILOT_FAULT_ID = "F7"
PILOT_TRIAL = 1
PILOT_MANIFEST_SCHEMA = "v2.3-pilot-campaign-5"
MAIN_MANIFEST_SCHEMA = "v2.3-main-campaign-7"
COPILOT_SESSION_MAX_AIC = 30
# The primary campaign runs sequentially while a fault remains injected.  The
# SDK's process-group watchdog adds its fixed 30-second cleanup grace to this
# deadline; the value below is the inference deadline passed to both the SDK
# request and its parent watchdog.
PRIMARY_COPILOT_TIMEOUT_SECONDS = 300
COPILOT_ACCOUNT_LOGIN = "moonsangyhu"
FLUX_RECONCILIATION_POLICY = "suspend-flux-root-then-app-during-incident"

EXPECTED_ROWS = len(FAULTS) * len(TRIALS) * len(CONDITIONS)
EXPECTED_GENERATOR_CALLS = EXPECTED_ROWS * K_GENERATIONS
EXPECTED_JUDGE_CALLS = EXPECTED_GENERATOR_CALLS * M_JUDGES
EXPECTED_CALLS = EXPECTED_GENERATOR_CALLS + EXPECTED_JUDGE_CALLS

# F7-t5's fixed 5m Deployment rollout has repeatedly produced a non-ready
# currencyservice rather than the pre-registered latency/throttling phenotype.
# Keep the immutable ground-truth row for audit, but exclude that invalid
# treatment from the live estimand instead of relabelling rollout failure as
# CPU throttling.  The offline fixture remains the full 60-incident grid.
MAIN_EXCLUDED_INCIDENTS = frozenset({("F7", 5)})
MAIN_INCIDENTS = tuple(
    (fault_id, trial)
    for fault_id in FAULTS
    for trial in TRIALS
    if (fault_id, trial) not in MAIN_EXCLUDED_INCIDENTS
)
MAIN_EXPECTED_INCIDENTS = len(MAIN_INCIDENTS)
MAIN_EXPECTED_ROWS = MAIN_EXPECTED_INCIDENTS * len(CONDITIONS)
MAIN_EXPECTED_GENERATOR_CALLS = MAIN_EXPECTED_ROWS * K_GENERATIONS
MAIN_EXPECTED_JUDGE_CALLS = MAIN_EXPECTED_GENERATOR_CALLS * M_JUDGES
MAIN_EXPECTED_CALLS = MAIN_EXPECTED_GENERATOR_CALLS + MAIN_EXPECTED_JUDGE_CALLS
