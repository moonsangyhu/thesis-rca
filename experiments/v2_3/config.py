"""Frozen V2.3 constants used by the offline review harness."""

EXPERIMENT = "v2.3"
REQUESTED_MODEL = "gpt-5.6-terra"
PROVIDER = "copilot"

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
MAIN_MANIFEST_SCHEMA = "v2.3-main-campaign-5"
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
