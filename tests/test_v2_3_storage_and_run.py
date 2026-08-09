import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.v2_3.config import EXPECTED_CALLS, EXPECTED_ROWS
from experiments.v2_3.conditions import ConditionAssembler
from experiments.v2_3.engine import RCAEngineV2_3
from experiments.v2_3.mock import DeterministicMockCaller, clean_fixture
from experiments.v2_3.mock import run_dry_run, run_mock_campaign
from experiments.v2_3.run import (
    RealExecutionDisabled, _pilot_budget_manifest_fields, _pilot_identity,
    _verified_git_revision, main,
)
from experiments.v2_3.authorization import AuthorizationError
from experiments.v2_3.storage import DuplicateResultError, OutputSafetyError, SafeOutputStore


class StorageAndRunTests(unittest.TestCase):
    @staticmethod
    def incident_fixture(campaign="c1"):
        conditions = ("runtime", "length_placebo", "blind_procedural_rag")
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        contexts = ConditionAssembler().assemble_all(runtime, procedure, lexicon)
        engine = RCAEngineV2_3(DeterministicMockCaller(campaign), campaign_id=campaign)
        rows = [engine.analyze_condition(
                    contexts[condition], "F1", 1, judge_reference="sealed answer"
                )
                for condition in conditions]
        raws = [dict(row) for row in rows]
        ledger = [entry.to_dict() for entry in engine.ledger.entries]
        return rows, raws, ledger

    def test_full_mock_manifest_is_180_rows_and_2160_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            summary = run_mock_campaign(root)
            self.assertEqual(summary["rows"], EXPECTED_ROWS)
            self.assertEqual(summary["calls"], EXPECTED_CALLS)
            with (root / "mock_results.csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 180)
            keys = {(r["campaign_id"], r["fault_id"], r["trial"], r["context_condition"]) for r in rows}
            self.assertEqual(len(keys), 180)
            self.assertEqual(len(list((root / "raw").glob("*.json"))), 180)
            first_raw = json.loads(next((root / "raw").glob("*.json")).read_text())
            self.assertEqual(len(first_raw["call_ledger"]), 12)
            with (root / "call_ledger.jsonl").open() as handle:
                ledger = [json.loads(line) for line in handle]
            self.assertEqual(len(ledger), 2160)
            self.assertEqual(sum(x["role"] == "generator" for x in ledger), 540)
            self.assertEqual(sum(x["role"] == "judge" for x in ledger), 1620)

    def test_duplicate_key_and_raw_overwrite_are_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SafeOutputStore(Path(temp_dir))
            rows, raws, ledger = self.incident_fixture()
            store.write_incident(rows, raws, ledger)
            with self.assertRaises(DuplicateResultError):
                store.write_incident(rows, raws, ledger)

    def test_incomplete_incident_is_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SafeOutputStore(root)
            row = {"campaign_id": "c1", "fault_id": "F1", "trial": 1,
                   "context_condition": "runtime"}
            with self.assertRaises(OutputSafetyError):
                store.write_incident([row], [{"raw": 1}], [])
            self.assertFalse((root / "mock_results.csv").exists())
            self.assertFalse((root / "raw").exists())

    def test_production_results_path_is_rejected(self):
        project = Path(__file__).resolve().parents[1]
        with self.assertRaises(OutputSafetyError):
            SafeOutputStore(project / "results" / "v2_3_mock")

    def test_raw_result_identity_mismatch_is_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SafeOutputStore(root)
            rows, raws, ledger = self.incident_fixture()
            raws[1]["fault_id"] = "F2"
            with self.assertRaisesRegex(OutputSafetyError, "identity"):
                store.write_incident(rows, raws, ledger)
            self.assertFalse((root / "mock_results.csv").exists())

    def test_duplicate_ledger_session_is_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SafeOutputStore(root)
            rows, raws, ledger = self.incident_fixture()
            ledger[1]["session_id"] = ledger[0]["session_id"]
            with self.assertRaisesRegex(OutputSafetyError, "duplicate"):
                store.write_incident(rows, raws, ledger)
            self.assertFalse((root / "mock_results.csv").exists())

    def test_real_execution_is_disabled_even_with_approval_marker(self):
        with self.assertRaises(RealExecutionDisabled):
            main([])
        with self.assertRaises(RealExecutionDisabled):
            main(["--approve-real"])

    def test_pilot_billing_gate_blocks_before_live_builder(self):
        from unittest.mock import patch
        argv = [
            "--pilot", "--billing-evidence", "/tmp/missing-evidence.json",
            "--approval-id", "pilot-20260809", "--campaign-id", "campaign-20260809",
            "--chroma-dir", "/tmp/missing-chroma",
        ]
        with patch.dict("os.environ", {
            "THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED": "0",
            "THESIS_V23_PILOT_USER_APPROVED": "0",
        }, clear=False), patch("experiments.v2_3.run._run_authorized_pilot") as live:
            with self.assertRaises(AuthorizationError):
                main(argv)
        live.assert_not_called()

    def test_dry_run_has_no_filesystem_or_external_calls(self):
        with patch("experiments.v2_3.mock.SafeOutputStore") as store:
            summary = run_dry_run()
        store.assert_not_called()
        self.assertEqual(summary["rows"], 180)
        self.assertEqual(summary["calls"], 2160)
        self.assertEqual(summary["filesystem_writes"], 0)
        self.assertEqual(summary["external_calls"], 0)

    def test_live_revision_requires_clean_full_git_sha(self):
        clean = [
            type("Result", (), {
                "returncode": 0,
                "stdout": "a" * 40 + "\n",
                "stderr": "",
            })(),
            type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
        ]
        with patch("experiments.v2_3.run.subprocess.run", side_effect=clean):
            self.assertEqual(_verified_git_revision(Path("/tmp")), "a" * 40)
        dirty = [
            type("Result", (), {
                "returncode": 0,
                "stdout": "b" * 40 + "\n",
                "stderr": "",
            })(),
            type("Result", (), {
                "returncode": 0,
                "stdout": " M experiments/v2_3/run.py\n",
                "stderr": "",
            })(),
        ]
        with patch("experiments.v2_3.run.subprocess.run", side_effect=dirty):
            with self.assertRaisesRegex(RuntimeError, "clean"):
                _verified_git_revision(Path("/tmp"))

    def test_live_manifest_identity_is_frozen_to_approved_f7_trial_1(self):
        self.assertEqual(_pilot_identity(), {"fault_id": "F7", "trial": 1})

    def test_live_manifest_records_cli_and_campaign_aic_boundaries(self):
        self.assertEqual(_pilot_budget_manifest_fields(360), {
            "schema_version": "v2.3-pilot-campaign-2",
            "max_campaign_aic": 360,
            "copilot_session_max_aic": 30,
            "flux_reconciliation_policy": "suspend-flux-root-then-app-during-incident",
        })

    def test_retriever_accepts_explicit_live_chroma_directory(self):
        from src.rag.retriever import KnowledgeRetriever

        with tempfile.TemporaryDirectory() as temp_dir, \
                patch("src.rag.retriever.chromadb.PersistentClient") as client, \
                patch("src.rag.retriever.embedding_functions.SentenceTransformerEmbeddingFunction"):
            collection = client.return_value.get_collection.return_value
            collection.count.return_value = 1
            KnowledgeRetriever(chroma_dir=Path(temp_dir))

        client.assert_called_once_with(path=temp_dir)


if __name__ == "__main__":
    unittest.main()
