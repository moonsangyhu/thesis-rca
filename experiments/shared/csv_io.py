"""CSV I/O and raw data saving for experiment results."""
import csv
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def init_csv(csv_path: Path, headers: list[str]):
    """Initialize results CSV with headers if not exists."""
    if not csv_path.exists():
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()


def append_result(result: dict, csv_path: Path, headers: list[str]):
    """Append a single result row to CSV."""
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        row = {k: result.get(k, "") for k in headers}
        # Convert lists to pipe-delimited strings
        for key in ["affected_components", "remediation", "remediation_ko"]:
            if isinstance(row.get(key), list):
                row[key] = "|".join(str(x) for x in row[key])
        # Convert dicts/lists to JSON strings
        for key in ["evidence_chain", "alternative_hypotheses"]:
            if isinstance(row.get(key), (list, dict)):
                row[key] = json.dumps(row[key], ensure_ascii=False)
        # Truncate reasoning for CSV (full version in raw JSON)
        if isinstance(row.get("reasoning"), str) and len(row["reasoning"]) > 200:
            row["reasoning"] = row["reasoning"][:200] + "..."
        writer.writerow(row)


def save_raw(fault_id: str, trial: int, system: str, data: dict, raw_dir: Path):
    """Save raw data (signals, context, LLM response) as JSON."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{fault_id}_t{trial}_{system}_{datetime.now():%Y%m%d_%H%M%S}.json"
    filepath = raw_dir / filename
    with open(filepath, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    logger.info("Raw data saved: %s", filepath)


def get_completed_trials(csv_path: Path) -> set:
    """Read CSV and return set of (fault_id, trial) already completed."""
    completed = set()
    if csv_path.exists():
        with open(csv_path) as f:
            for row in csv.DictReader(f):
                key = (row["fault_id"], int(row["trial"]))
                completed.add(key)
    return completed


def load_ground_truth(csv_path: Path) -> dict:
    """Load ground truth CSV into dict keyed by (fault_id, trial)."""
    gt = {}
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            key = (row["fault_id"], int(row["trial"]))
            gt[key] = row
    return gt
