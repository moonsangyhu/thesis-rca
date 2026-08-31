import contextlib
import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from experiments.v2_4_deterministic import analyze, build_ontology, commit_inputs, run, scorer


def candidate(fault="OOMKilled", root="recommendationservice memory limit too low oom killed", remediation=None):
    return json.dumps({"identified_fault_type": fault, "root_cause": root, "remediation": remediation or ["increase memory limit to 96Mi"]}).encode()


def synthetic_candidate(ontology, incident):
    axes = next(item["axes"] for item in ontology["incidents"] if item["incident_id"] == incident)
    def phrase(group):
        matcher = group["any_of"][0]
        return ontology["token_predicates"][matcher["value"]][0] if matcher["kind"] == "token_predicate" else matcher["value"]
    mechanism = " ".join(phrase(group) for group in axes["mechanism"]["positive_paths"][0]["all_of"])
    component = phrase(axes["component_mention"]["positive_paths"][0]["all_of"][0])
    fault = phrase(axes["fault_label_mention"]["positive_paths"][0]["all_of"][0])
    remediation = " ".join(phrase(group) for group in axes["remediation"]["positive_paths"][0]["all_of"])
    return {"identified_fault_type": fault, "root_cause": component + " " + mechanism, "remediation": [remediation]}


class DeterministicSyntheticTests(unittest.TestCase):
    def test_01_ontology_check_only(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(build_ontology.check(root / "experiments/v2_4_deterministic/ontology_v1.json")["incident_count"], 12)

    def test_02_ontology_mutation_controls_score(self):
        root = Path(__file__).resolve().parents[1]
        data = scorer.load_ontology(root / "experiments/v2_4_deterministic/ontology_v1.json")
        original = tempfile.NamedTemporaryFile(suffix=".json", delete=False); original.close()
        mutated = tempfile.NamedTemporaryFile(suffix=".json", delete=False); mutated.close()
        try:
            Path(original.name).write_text(json.dumps(data), encoding="utf-8")
            item = next(x for x in data["incidents"] if x["incident_id"] == "F1-t2")
            item["axes"]["component_mention"]["positive_paths"][0]["all_of"][0]["any_of"][0]["value"] = "synthetic only component"
            Path(mutated.name).write_text(json.dumps(data), encoding="utf-8")
            raw = candidate(root="synthetic only component memory limit too low oom killed")
            self.assertFalse(scorer.score("F1-t2", raw, original.name)["cm"])
            self.assertTrue(scorer.score("F1-t2", raw, mutated.name)["cm"])
        finally:
            Path(original.name).unlink(missing_ok=True); Path(mutated.name).unlink(missing_ok=True)

    def test_03_field_isolation(self):
        result = scorer.score("F1-t2", candidate(fault="none", root="recommendationservice memory limit too low oom killed", remediation=["OOMKilled increase memory limit to 96Mi"]))
        self.assertFalse(result["flm"]); self.assertTrue(result["mca"]); self.assertTrue(result["ra"])

    def test_04_positive_conjunction(self):
        self.assertFalse(scorer.score("F1-t2", candidate(root="recommendationservice memory limit oom killed"))["mca"])

    def test_05_nfkc_casefold(self): self.assertTrue(scorer.match("ＦＲＯＮＴＥＮＤ", ["frontend"]))
    def test_06_separator_equivalence(self): self.assertTrue(scorer.match("redis-cart LOCAL_path", ["redis cart"]))
    def test_07_token_boundary(self): self.assertFalse(scorer.match("frontendish", ["frontend"]))
    def test_08_same_item_ra(self): self.assertFalse(scorer.score("F1-t2", candidate(remediation=["increase", "memory limit to 96Mi"]))["ra"])
    def test_09_ra_contradiction(self):
        result = scorer.score("F1-t2", candidate(remediation=["increase memory limit to 96Mi; decrease memory limit"]))
        self.assertFalse(result["ra"]); self.assertTrue(result["contradiction_ids"])
    def test_10_pre_direct(self): self.assertFalse(scorer.match("not network policy", ["network policy"]))
    def test_11_pre_coord(self): self.assertFalse(scorer.match("no cpu throttling or memory limit", ["memory limit"]))
    def test_12_pre_rule(self): self.assertFalse(scorer.match("rule out network policy", ["network policy"]))
    def test_13_post_rule(self): self.assertFalse(scorer.match("network policy was ruled out", ["network policy"]))
    def test_14_post_cause(self): self.assertFalse(scorer.match("network policy is not the cause", ["network policy"]))
    def test_15_not_only(self): self.assertTrue(scorer.match("not only cpu throttling but memory limit", ["memory limit"]))
    def test_16_clause_scope(self): self.assertTrue(scorer.match("not image pull; digest mismatch", ["digest mismatch"]))
    def test_17_absence_assertion(self): self.assertTrue(scorer.match("no endpoints", ["no endpoints"]))

    def test_18_fail_closed_input_schema_and_limits(self):
        bad = [b'{"identified_fault_type":"x","root_cause":"x","remediation":[]}', b'{"identified_fault_type":"x","identified_fault_type":"x","root_cause":"x","remediation":["x"]}', '{"identified_fault_type":"x","root_cause":"한글","remediation":["x"]}'.encode(), candidate(root="x" * 9000), candidate(root="not because memory limit")]
        for raw in bad:
            with self.subTest(raw=len(raw)):
                with self.assertRaises(scorer.InvalidInput): scorer.validate_candidate_bytes(raw)

    def test_19_static_schema_rejects_extra_and_unknown_predicate(self):
        data = scorer.load_ontology(); data["extra"] = True
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(data, handle); handle.flush()
            with self.assertRaises(scorer.InvalidInput): scorer.load_ontology(handle.name)

    def test_20_hash_only_commitment_redacts_content(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td); raw = root / "raw"; raw.mkdir(); (raw / "one.json").write_bytes(b"CANDIDATE_SECRET"); csv_path = root / "input.csv"; csv_path.write_bytes(b"CSV_SECRET")
            out = io.StringIO(); err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): commit_inputs.main(["--csv", str(csv_path), "--raw-dir", str(raw), "--out", str(root / "commit.json")])
            self.assertNotIn("SECRET", out.getvalue() + err.getvalue())

    def test_21_statistics_known_answers_and_canonical_float(self):
        self.assertEqual(analyze.mcnemar_one_sided(5, 0), .03125); self.assertEqual(analyze.mcnemar_one_sided(4, 0), .0625); self.assertEqual(analyze.mcnemar_one_sided(0, 5), 1)
        self.assertEqual(analyze.canonical_float(-0.0), "0")
        lo, hi = analyze.clopper_pearson(5, 5); self.assertGreater(lo, .45); self.assertEqual(hi, 1.)

    def test_22_primary_pairing_bootstrap_and_summary_flag(self):
        rows = []
        for index, incident in enumerate(run.SELECTED):
            rows.extend([{"incident_id": incident, "condition": "runtime", "jlc_d": False, "full": False}, {"incident_id": incident, "condition": "length_placebo", "jlc_d": False, "full": True}, {"incident_id": incident, "condition": "blind_procedural_rag", "jlc_d": index < 5, "full": False}])
        result = analyze.primary(rows)
        self.assertEqual((result["b"], result["c"], result["p"]), (5, 0, "0.03125")); self.assertTrue(result["remediation_regression_flag"])
        self.assertEqual(analyze.paired_bootstrap([(1, 0), (0, 1)], seed=3, reps=8), analyze.paired_bootstrap([(1, 0), (0, 1)], seed=3, reps=8))

    def _fixture(self, root):
        raw_dir = root / "raw"; raw_dir.mkdir(); csv_path = root / "input.csv"; ontology = scorer.load_ontology()
        identities = [(f"F{fault}", trial, condition) for fault in range(1, 9) for trial in range(1, 6) for condition in run.CONDITIONS][:-3]
        self.assertEqual(len(identities), 117)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["fault_id", "trial", "context_condition"]); writer.writeheader()
            for number, (fault, trial, condition) in enumerate(reversed(identities)):
                writer.writerow({"fault_id": fault, "trial": trial, "context_condition": condition})
                incident = f"{fault}-t{trial}"
                payload = synthetic_candidate(ontology, incident) if incident in run.SELECTED else {"identified_fault_type": "x", "root_cause": "x", "remediation": ["x"]}
                (raw_dir / f"raw-{number:03d}.json").write_text(json.dumps({"fault_id": fault, "trial": trial, "context_condition": condition, "representative_output": payload}), encoding="utf-8")
        commitment = root / "commitment.json"; commit_inputs.main(["--csv", str(csv_path), "--raw-dir", str(raw_dir), "--out", str(commitment)])
        ground_truth = root / "ground_truth.csv"
        with ground_truth.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["fault_id", "trial", "fault_name", "target_service", "expected_root_cause", "expected_recovery_action"]); writer.writeheader()
            for incident in run.SELECTED:
                fault, trial = incident.split("-t"); writer.writerow({"fault_id": fault, "trial": trial, "fault_name": "x", "target_service": "x", "expected_root_cause": "x", "expected_recovery_action": "x"})
        approval = root / "approval.json"; approval.write_text(json.dumps({"approval_version": "v2.4-d-approval-1", "approved_bundle": "synthetic-bundle", "execution_commit": "synthetic-exec", "approval": "APPROVED", "semantic_review_sha256": "synthetic-review", "input_commitment_sha256": hashlib.sha256(commitment.read_bytes()).hexdigest(), "ontology_sha256": hashlib.sha256(Path(scorer.__file__).with_name("ontology_v1.json").read_bytes()).hexdigest(), "scorer_sha256": hashlib.sha256(Path(scorer.__file__).read_bytes()).hexdigest(), "ground_truth_sha256": hashlib.sha256(ground_truth.read_bytes()).hexdigest(), "ground_truth_projection_sha256": run._projection_hash(ground_truth)}), encoding="utf-8")
        return raw_dir, csv_path, commitment, ground_truth, approval

    def test_23_approval_is_checked_before_candidate_metadata(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td); raw_dir, csv_path, commitment, ground_truth, approval = self._fixture(root)
            approval.write_text("{}", encoding="utf-8")
            with mock.patch("experiments.v2_4_deterministic.run.safe_metadata", side_effect=AssertionError("raw opened")):
                with self.assertRaises(run.RunInvalid): run.run_campaign(approval=approval, commitment=commitment, raw_dir=raw_dir, csv_path=csv_path, ground_truth=ground_truth, ontology=Path(scorer.__file__).with_name("ontology_v1.json"), output=root / "out", synthetic=True)

    def test_24_full_synthetic_e2e_and_replay(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td); raw_dir, csv_path, commitment, ground_truth, approval = self._fixture(root); ontology = Path(scorer.__file__).with_name("ontology_v1.json")
            first = run.run_campaign(approval=approval, commitment=commitment, raw_dir=raw_dir, csv_path=csv_path, ground_truth=ground_truth, ontology=ontology, output=root / "one", synthetic=True)
            second = run.run_campaign(approval=approval, commitment=commitment, raw_dir=raw_dir, csv_path=csv_path, ground_truth=ground_truth, ontology=ontology, output=root / "two", synthetic=True)
            self.assertEqual(first["canonical_output_sha256"], second["canonical_output_sha256"])
            with (root / "one/scores.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 36); self.assertEqual({row["condition"] for row in rows}, set(run.CONDITIONS))
            self.assertNotIn("root_cause", (root / "one/score_trace.jsonl").read_text(encoding="utf-8"))

    def test_25_commitment_mismatch_fails(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td); raw_dir, csv_path, commitment, _, _ = self._fixture(root)
            (raw_dir / "raw-000.json").write_bytes(b"changed")
            with self.assertRaises(run.RunInvalid): run.dry_run(commitment, raw_dir, csv_path)


if __name__ == "__main__":
    unittest.main()
