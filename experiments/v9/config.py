"""v9 experiment configuration: Pre-Trial State Validator (V8 fork).

V9 단일 독립변수: validator. 프롬프트/엔진 로직/메트릭 수집은 V8와 완전 동일.
plan: docs/plans/experiment_plan_v9.md (1차 리비전 후, review_v9 필수 5건 반영).
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_CSV = RESULTS_DIR / "experiment_results_v9.csv"
RAW_DIR = RESULTS_DIR / "raw_v9"
GROUND_TRUTH_CSV = RESULTS_DIR / "ground_truth.csv"

MAX_TOKENS = 2048
MAX_RETRIES = 2

# V9 추가 컬럼 (plan §3-3 + 필수 수정 4): skipped 처리용
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
    # V9 신규 컬럼
    "skipped",              # "true" / "false" — validator가 trial을 skip했는지
    "validator_status",     # "clean" / "corrected" / "skipped"
    "validator_findings",   # stale findings 개수 (정수 또는 "exception")
    "validator_attempts",   # 정정 시도 횟수 (0/1/2)
]
