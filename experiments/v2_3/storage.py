"""V2.3-only output store with dedupe and overwrite refusal."""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from pathlib import Path

from .ledger import CallLedgerEntry, ProvenanceError


class OutputSafetyError(RuntimeError):
    pass


class DuplicateResultError(OutputSafetyError):
    pass


class SafeOutputStore:
    """Write only below an explicit non-production output directory."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir).resolve()
        root = Path(__file__).resolve().parents[2]
        production = (root / "results").resolve()
        if self.output_dir == production or production in self.output_dir.parents:
            raise OutputSafetyError("V2.3 offline output may not use production results/")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.csv_path = self.output_dir / "mock_results.csv"
        self.raw_dir = self.output_dir / "raw"
        self.ledger_path = self.output_dir / "call_ledger.jsonl"
        self._keys = self._load_keys()

    def _load_keys(self) -> set[tuple[str, str, int, str]]:
        keys: set[tuple[str, str, int, str]] = set()
        if self.csv_path.exists():
            with self.csv_path.open(newline="") as handle:
                for row in csv.DictReader(handle):
                    key = (row["campaign_id"], row["fault_id"], int(row["trial"]),
                           row["context_condition"])
                    if key in keys:
                        raise DuplicateResultError(f"duplicate existing key: {key}")
                    keys.add(key)
        return keys

    @staticmethod
    def _key(row: dict) -> tuple[str, str, int, str]:
        return (row["campaign_id"], row["fault_id"], int(row["trial"]),
                row["context_condition"])

    @staticmethod
    def _raw_name(key: tuple[str, str, int, str]) -> str:
        components = (key[0], key[1], str(key[2]), key[3])
        if any(re.fullmatch(r"[A-Za-z0-9_.-]+", value) is None for value in components):
            raise OutputSafetyError("unsafe result key component")
        return f"{key[0]}_{key[1]}_t{key[2]}_{key[3]}.json"

    def write_incident(
        self, rows: list[dict], raws: list[dict], ledger_entries: list[dict]
    ) -> None:
        """Validate a complete three-condition incident before any write.

        This prevents validation/dedupe failures from leaving a one- or two-arm
        incident. Filesystem crash atomicity is outside the offline harness, but
        every ordinary failure is discovered before the first artifact opens.
        """
        if len(rows) != 3 or len(raws) != 3:
            raise OutputSafetyError("incident must contain exactly three conditions")
        keys = [self._key(row) for row in rows]
        if len(set(keys)) != 3:
            raise DuplicateResultError("duplicate key inside incident")
        incident_ids = {(key[0], key[1], key[2]) for key in keys}
        if len(incident_ids) != 1:
            raise OutputSafetyError("mixed campaign/fault/trial incident")
        if {key[3] for key in keys} != {
            "runtime", "length_placebo", "blind_procedural_rag"
        }:
            raise OutputSafetyError("incident condition set is incomplete")
        if len(ledger_entries) != 36:
            raise OutputSafetyError("incident must contain exactly 36 call-ledger entries")
        incident_id = next(iter(incident_ids))
        ledger_conditions: dict[str, int] = {}
        sessions: set[str] = set()
        repeat_map: dict[str, set[tuple[str, int, int | None]]] = {}
        for entry in ledger_entries:
            try:
                parsed = CallLedgerEntry(**entry)
                parsed.validate()
            except (TypeError, ProvenanceError) as exc:
                raise OutputSafetyError("malformed call-ledger entry") from exc
            if (entry.get("campaign_id"), entry.get("fault_id"), entry.get("trial")) != incident_id:
                raise OutputSafetyError("call ledger does not match incident")
            if parsed.session_id in sessions:
                raise OutputSafetyError("duplicate call-ledger session")
            sessions.add(parsed.session_id)
            condition = entry.get("context_condition")
            ledger_conditions[condition] = ledger_conditions.get(condition, 0) + 1
            repeat_map.setdefault(condition, set()).add(
                (parsed.role, parsed.generation_repeat, parsed.judge_repeat)
            )
        if ledger_conditions != {
            "runtime": 12, "length_placebo": 12, "blind_procedural_rag": 12
        }:
            raise OutputSafetyError("call ledger condition cardinality mismatch")
        expected_repeats = {
            *(("generator", generation, None) for generation in range(1, 4)),
            *(("judge", generation, judge) for generation in range(1, 4)
              for judge in range(1, 4)),
        }
        if any(repeats != expected_repeats for repeats in repeat_map.values()):
            raise OutputSafetyError("call ledger role/repeat mapping mismatch")
        for row, raw in zip(rows, raws):
            if any(raw.get(name) != row.get(name) for name in (
                "campaign_id", "fault_id", "trial", "context_condition"
            )):
                raise OutputSafetyError("raw/result identity mismatch")
        for key in keys:
            raw_path = self.raw_dir / self._raw_name(key)
            if key in self._keys or raw_path.exists():
                raise DuplicateResultError(f"incident overwrite refused: {key}")
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        staged_paths: list[tuple[Path, Path]] = []
        committed_raws: list[Path] = []
        csv_temp: Path | None = None
        ledger_temp: Path | None = None
        ledger_replaced = False
        existing_ledger = self.ledger_path.read_text() if self.ledger_path.exists() else ""
        try:
            for row, raw in zip(rows, raws):
                key = self._key(row)
                target = self.raw_dir / self._raw_name(key)
                fd, stage_name = tempfile.mkstemp(prefix=".incident-", dir=self.raw_dir)
                stage = Path(stage_name)
                with os.fdopen(fd, "w") as handle:
                    json.dump(raw, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                staged_paths.append((stage, target))

            fd, ledger_name = tempfile.mkstemp(prefix=".ledger-", dir=self.output_dir)
            ledger_temp = Path(ledger_name)
            with os.fdopen(fd, "w") as handle:
                if existing_ledger:
                    handle.write(existing_ledger)
                    if not existing_ledger.endswith("\n"):
                        handle.write("\n")
                for entry in ledger_entries:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

            headers = list(rows[0])
            existing = self.csv_path.read_text() if self.csv_path.exists() else ""
            fd, csv_name = tempfile.mkstemp(prefix=".results-", dir=self.output_dir)
            csv_temp = Path(csv_name)
            with os.fdopen(fd, "w", newline="") as handle:
                if existing:
                    handle.write(existing)
                    if not existing.endswith("\n"):
                        handle.write("\n")
                writer = csv.DictWriter(handle, fieldnames=headers)
                if not existing:
                    writer.writeheader()
                for row in rows:
                    writer.writerow({
                        k: json.dumps(v, ensure_ascii=False)
                        if isinstance(v, (list, dict)) else v
                        for k, v in row.items()
                    })
                handle.flush()
                os.fsync(handle.fileno())

            for stage, target in staged_paths:
                # Targets were resolved and checked before staging; replace is
                # used only to atomically publish a previously absent raw file.
                if target.exists():
                    raise DuplicateResultError(f"raw overwrite refused: {target.name}")
                os.link(stage, target)
                stage.unlink()
                committed_raws.append(target)
            os.replace(ledger_temp, self.ledger_path)
            ledger_temp = None
            ledger_replaced = True
            os.replace(csv_temp, self.csv_path)
            csv_temp = None
            self._keys.update(keys)
        except Exception:
            for stage, _ in staged_paths:
                if stage.exists():
                    stage.unlink()
            for target in committed_raws:
                if target.exists():
                    target.unlink()
            if csv_temp is not None and csv_temp.exists():
                csv_temp.unlink()
            if ledger_temp is not None and ledger_temp.exists():
                ledger_temp.unlink()
            if ledger_replaced:
                if existing_ledger:
                    fd, restore_name = tempfile.mkstemp(
                        prefix=".ledger-restore-", dir=self.output_dir
                    )
                    with os.fdopen(fd, "w") as handle:
                        handle.write(existing_ledger)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(restore_name, self.ledger_path)
                elif self.ledger_path.exists():
                    self.ledger_path.unlink()
            raise
