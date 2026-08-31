import contextlib
import csv
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import sys

_REPO = Path(__file__).resolve().parents[1]
if not (_REPO / "AGENTS.md").is_file() or not (_REPO / ".git").exists() or any(parent.is_symlink() for parent in (_REPO, *_REPO.parents)):
    raise RuntimeError("UNTRUSTED_REPO_BOOTSTRAP")
sys.path.insert(0, str(_REPO))

from experiments.v2_4_deterministic import analyze, build_ontology, commit_inputs, run, scorer


def _digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


def full_safety_receipt_for_root(reviewed_i0, repo):
    """A code-only receipt with every reviewed target content-addressed."""
    targets = []
    for relative in commit_inputs._SAFETY_TARGETS:
        target = repo / relative
        targets.append({"path": relative, "blob_oid": commit_inputs._blob_oid(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    return {
        "reviewer_id": "synthetic-reviewer", "session_id": "synthetic-session", "review_utc": "2026-09-01T00:00:00Z",
        "reviewed_i0": reviewed_i0, "result": "PASS", "status": "PASS", "safety_targets": targets,
        "semantic_review_sha256": _digest("semantic"),
        "interpreter": {"path": str(Path(sys.executable)), "version": sys.version, "sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()},
        "commands": [{"command": "sha256:" + _digest("python -I tests/test_v2_4_deterministic.py"), "exit_status": 0, "stdout_sha256": _digest("stdout"), "stderr_sha256": _digest("stderr")}],
        "fixture_sha256": _digest("fixture"), "sentinel_sha256": _digest("sentinel"),
        "real_source_open_count": 0, "candidate_text_egress": False, "prior_failures_closed": ["P0-closed"],
    }


def full_safety_receipt(reviewed_i0):
    return full_safety_receipt_for_root(reviewed_i0,Path(__file__).resolve().parents[1])


def historical_legacy_reference(csv_path, raw_dir):
    """Synthetic-only shape of the immutable pre-I1 legacy artifact."""
    legacy=commit_inputs.commit(csv_path,raw_dir)
    legacy["csv"]={"path":"historical-input.csv","size":legacy["csv"]["size"],"sha256":legacy["csv"]["sha256"]}
    return legacy


@contextlib.contextmanager
def synthetic_legacy_identity(path):
    """Test-only patch; production identity is fixed and has no CLI/data override."""
    payload=Path(path).read_bytes()
    identity={"blob_oid":commit_inputs._blob_oid_bytes(payload),"sha256":hashlib.sha256(payload).hexdigest()}
    with mock.patch.object(commit_inputs,"HISTORICAL_LEGACY_REFERENCE_IDENTITY",identity):
        yield


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
        mutated = tempfile.NamedTemporaryFile(suffix=".json", delete=False); mutated.close()
        try:
            item = next(x for x in data["incidents"] if x["incident_id"] == "F1-t2")
            item["axes"]["component_mention"]["positive_paths"][0]["all_of"][0]["any_of"][0]["value"] = "synthetic only component"
            Path(mutated.name).write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(scorer.APPROVED_ONTOLOGY_SHA256, hashlib.sha256((root / "experiments/v2_4_deterministic/ontology_v1.json").read_bytes()).hexdigest())
            with self.assertRaises(scorer.InvalidInput): scorer.load_ontology(mutated.name)
        finally:
            Path(mutated.name).unlink(missing_ok=True)

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
            root = Path(td); raw = root / "raw"; raw.mkdir()
            for index in range(117): (raw / f"{index:03d}.json").write_bytes(b"CANDIDATE_SECRET")
            csv_path = root / "input.csv"; csv_path.write_bytes(b"CSV_SECRET")
            out = io.StringIO(); err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): commit_inputs.main(["--csv", str(csv_path), "--raw-dir", str(raw), "--out", str(root / "commit.json")], _internal_self_test=True)
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
        commitment = root / "commitment.json"; commitment.write_text(json.dumps(commit_inputs.commit(csv_path, raw_dir), sort_keys=True, separators=(",", ":")), encoding="utf-8")
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

    def test_26_empty_fault_rejected(self):
        with self.assertRaises(scorer.InvalidInput): scorer.validate_candidate_bytes(candidate(fault=""))
    def test_27_empty_root_rejected(self):
        with self.assertRaises(scorer.InvalidInput): scorer.validate_candidate_bytes(candidate(root=""))
    def test_28_replacement_rejected(self):
        with self.assertRaises(scorer.InvalidInput): scorer.validate_candidate_bytes(candidate(root="\ufffd"))
    def test_29_total_remediation_tokens_rejected(self):
        with self.assertRaises(scorer.InvalidInput): scorer.validate_candidate_bytes(candidate(remediation=["x " * 256] * 5))
    def test_30_neither_coordinate_is_suppressed(self): self.assertFalse(scorer.match("neither cpu throttling nor memory limit", ["memory limit"]))
    def test_31_pre_rule_filler_is_suppressed(self): self.assertFalse(scorer.match("rule out the network policy", ["network policy"]))
    def test_32_post_rule_has_been_is_suppressed(self): self.assertFalse(scorer.match("network policy has been ruled out", ["network policy"]))
    def test_33_post_rule_have_been_is_suppressed(self): self.assertFalse(scorer.match("network policy have been ruled out", ["network policy"]))
    def test_34_ontology_duplicate_key_rejected(self):
        with tempfile.NamedTemporaryFile("w") as handle:
            handle.write('{"ontology_version":"v2.4-d-ontology-1","ontology_version":"v2.4-d-ontology-1"}'); handle.flush()
            with self.assertRaises(scorer.InvalidInput): scorer.load_ontology(handle.name)
    def test_35_ontology_negation_order_rejected(self):
        data=scorer.load_ontology(); data["negation"]["tokens"].reverse()
        with tempfile.NamedTemporaryFile("w") as handle:
            json.dump(data, handle); handle.flush()
            with self.assertRaises(scorer.InvalidInput): scorer.load_ontology(handle.name)
    def test_36_ontology_id_pattern_rejected(self):
        data=scorer.load_ontology(); data["incidents"][0]["incident_id"]="bad"
        with tempfile.NamedTemporaryFile("w") as handle:
            json.dump(data, handle); handle.flush()
            with self.assertRaises(scorer.InvalidInput): scorer.load_ontology(handle.name)
    def test_37_bootstrap_exact_replay(self):
        pairs=[(1,0)]*5+[(0,0)]*7
        self.assertEqual(analyze.paired_bootstrap(pairs, seed=20260831, reps=50000), analyze.paired_bootstrap(pairs, seed=20260831, reps=50000))

    def test_38_full_release_is_single_root_after_two_hidden_runs(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td)
            raw_dir, csv_path, commitment, ground_truth, approval = self._fixture(root)
            release = root / "release"
            result = run.run_full(
                approval=approval, commitment=commitment, raw_dir=raw_dir, csv_path=csv_path,
                ground_truth=ground_truth, ontology=Path(scorer.__file__).with_name("ontology_v1.json"),
                output=release, code_candidate="0" * 40, implementation_candidate="1" * 40,
                approved_bundle="2" * 40, execution_commit="3" * 40, synthetic=True,
            )
            self.assertEqual(result["replay"], "MATCH")
            self.assertTrue((release / "final" / "scores.csv").is_file())
            self.assertTrue((release / "replay" / "scores.csv").is_file())
            self.assertTrue((release / "replay_manifest.json").is_file())
            manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["replay_result"], "MATCH")
            self.assertEqual(manifest["release_contract"]["result_export"], "result_export.csv")
            with (release / "result_export.csv").open(encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 36)

    def test_39_second_hidden_run_failure_never_releases_first_result(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td)
            raw_dir, csv_path, commitment, ground_truth, approval = self._fixture(root)
            release = root / "release"
            original = run.run_campaign
            calls = 0
            def second_fails(**kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise run.RunInvalid("SYNTHETIC_SECOND_FAILURE")
                return original(**kwargs)
            with mock.patch("experiments.v2_4_deterministic.run.run_campaign", side_effect=second_fails):
                with self.assertRaises(run.RunInvalid):
                    run.run_full(
                        approval=approval, commitment=commitment, raw_dir=raw_dir, csv_path=csv_path,
                        ground_truth=ground_truth, ontology=Path(scorer.__file__).with_name("ontology_v1.json"),
                        output=release, code_candidate="0" * 40, implementation_candidate="1" * 40,
                        approved_bundle="2" * 40, execution_commit="3" * 40, synthetic=True,
                    )
            self.assertFalse(release.exists())
            receipt = root / ".release.invalid.json"
            self.assertTrue(receipt.is_file())
            self.assertNotIn("representative_output", receipt.read_text(encoding="utf-8"))

    def test_40_replay_mismatch_never_releases_final_or_replay(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td)
            raw_dir, csv_path, commitment, ground_truth, approval = self._fixture(root)
            release = root / "release"
            first = {"scores.csv": "a", "paired_table.csv": "a", "summary.json": "a", "input_manifest.json": "a", "score_trace.jsonl": "a", "execution.log": "a"}
            second = dict(first); second["scores.csv"] = "different"
            with mock.patch("experiments.v2_4_deterministic.run._file_digest_map", side_effect=(first, second)):
                with self.assertRaisesRegex(run.RunInvalid, "REPLAY_MISMATCH"):
                    run.run_full(
                        approval=approval, commitment=commitment, raw_dir=raw_dir, csv_path=csv_path,
                        ground_truth=ground_truth, ontology=Path(scorer.__file__).with_name("ontology_v1.json"),
                        output=release, code_candidate="0" * 40, implementation_candidate="1" * 40,
                        approved_bundle="2" * 40, execution_commit="3" * 40, synthetic=True,
                    )
            self.assertFalse(release.exists())
            self.assertTrue((root / ".release.invalid.json").is_file())

    def test_41_repository_gate_fails_before_candidate_path_enumeration(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td)
            sentinel = root / "DO_NOT_OPEN_CANDIDATE"
            approval = root / "approval.json"; approval.write_text("{}", encoding="utf-8")
            with mock.patch("experiments.v2_4_deterministic.run.safe_metadata", side_effect=AssertionError("candidate opened")), \
                 mock.patch("experiments.v2_4_deterministic.run._repository_gate", side_effect=run.RunInvalid("GIT_HEAD_INVALID")):
                with self.assertRaisesRegex(run.RunInvalid, "GIT_HEAD_INVALID"):
                    run.run_full(
                        approval=approval, execution_authorization=root / run.EXECUTION_AUTHORIZATION_DOCUMENT, commitment=root / "commitment.json", raw_dir=sentinel, csv_path=sentinel,
                        ground_truth=root / "ground_truth.csv", ontology=Path(scorer.__file__).with_name("ontology_v1.json"),
                        output=root / "release", code_candidate="0" * 40, implementation_candidate="1" * 40,
                        approved_bundle="2" * 40, execution_commit="3" * 40,
                    )
            self.assertFalse(sentinel.exists())

    def test_50_synthetic_i0_i1_chain_requires_absent_then_two_additions(self):
        i0, i1, bundle, execution = ("0" * 40, "1" * 40, "2" * 40, "3" * 40)
        approval = {
            "code_candidate": i0, "implementation_candidate": i1,
            "approved_bundle": bundle,
        }
        with mock.patch("experiments.v2_4_deterministic.run._repo_root", return_value=Path.cwd()), \
             mock.patch("experiments.v2_4_deterministic.run._canonical_approval_path", return_value=Path("synthetic-approval.json")), \
             mock.patch("experiments.v2_4_deterministic.run._canonical_execution_authorization_path", return_value=Path("synthetic-authorization.json")), \
             mock.patch("experiments.v2_4_deterministic.run._stable_metadata_bytes", return_value=(b"{}", {"stable": True})), \
             mock.patch("experiments.v2_4_deterministic.run._strict_approval_value", return_value=approval), \
             mock.patch("experiments.v2_4_deterministic.run._strict_execution_authorization_value", return_value={}), \
             mock.patch("experiments.v2_4_deterministic.run._git", side_effect=(execution, "", bundle, i1, i0)), \
             mock.patch("experiments.v2_4_deterministic.run._git_path_must_be_absent") as absent, \
             mock.patch("experiments.v2_4_deterministic.run._exact_diff", side_effect=run.RunInvalid("STOP_AFTER_I0_I1")) as exact_diff:
            with self.assertRaisesRegex(run.RunInvalid, "STOP_AFTER_I0_I1"):
                run._repository_gate(
                    approval_path=Path("synthetic-approval.json"), execution_authorization_path=Path("synthetic-authorization.json"), code_candidate=i0,
                    implementation_candidate=i1, approved_bundle=bundle, execution_commit=execution,
                )
        absent.assert_called_once_with(Path.cwd(), i0, run.COMMITMENT_DOCUMENT)
        self.assertEqual(
            exact_diff.call_args.args[3],
            (("A", run.COMMITMENT_DOCUMENT), ("A", run.DEVIATION_DOCUMENT)),
        )

    def test_51_modified_commitment_plus_added_deviation_is_rejected(self):
        with mock.patch("experiments.v2_4_deterministic.run._git", return_value=(
            "M\t" + run.COMMITMENT_DOCUMENT + "\nA\t" + run.DEVIATION_DOCUMENT
        )):
            with self.assertRaisesRegex(run.RunInvalid, "GIT_FREEZE_DIFF_INVALID"):
                run._exact_diff(
                    Path.cwd(), "0" * 40, "1" * 40,
                    (("A", run.COMMITMENT_DOCUMENT), ("A", run.DEVIATION_DOCUMENT)),
                )

    def test_52_i0_commitment_path_must_be_missing(self):
        with mock.patch("experiments.v2_4_deterministic.run.subprocess.run", return_value=SimpleNamespace(returncode=1)):
            run._git_path_must_be_absent(Path.cwd(), "0" * 40, run.COMMITMENT_DOCUMENT)
        with mock.patch("experiments.v2_4_deterministic.run.subprocess.run", return_value=SimpleNamespace(returncode=0)):
            with self.assertRaisesRegex(run.RunInvalid, "I0_COMMITMENT_MUST_BE_ABSENT"):
                run._git_path_must_be_absent(Path.cwd(), "0" * 40, run.COMMITMENT_DOCUMENT)

    def test_42_commitment_provenance_redacts_path_and_content_sentinels(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix="PATH_SENTINEL") as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); csv_path=root/"PATH_SENTINEL.csv"; out_path=root/"PATH_SENTINEL.commitment"; content=b"CONTENT_SENTINEL"
            csv_path.write_bytes(content)
            for index in range(117): (raw/f"{index:03d}.json").write_bytes(content)
            legacy=root/"legacy.json"; legacy.write_text(json.dumps(historical_legacy_reference(csv_path,raw)),encoding="utf-8")
            reviewed="a"*40; receipt=root/"receipt.json"; receipt.write_text(json.dumps(full_safety_receipt(reviewed)),encoding="utf-8")
            stdout=io.StringIO()
            with synthetic_legacy_identity(legacy), contextlib.redirect_stdout(stdout): self.assertEqual(commit_inputs.main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(out_path),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),0)
            rendered=out_path.read_text(encoding="utf-8")+stdout.getvalue()
            self.assertNotIn("PATH_SENTINEL", rendered); self.assertNotIn("CONTENT_SENTINEL", rendered)
            provenance=json.loads(out_path.read_text())["provenance"]
            self.assertEqual(provenance["argv"][::2],["--csv","--raw-dir","--out","--reviewed-i0","--safety-receipt","--legacy-reference"])
            self.assertTrue(all(value.startswith("sha256:") for value in provenance["argv"][1::2]))

    def test_43_ancestor_exchange_after_fd_anchor_fails_closed(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); bad=root/"bad"; bad.mkdir(); csv_path=root/"csv"; csv_path.write_bytes(b"x")
            for index in range(117): (raw/f"{index:03d}.json").write_bytes(b"x")
            original=os.listdir
            def exchange(fd):
                values=original(fd)
                raw.rename(root/"raw-original"); raw.symlink_to(bad, target_is_directory=True)
                return values
            with mock.patch("experiments.v2_4_deterministic.commit_inputs.os.listdir", side_effect=exchange):
                with self.assertRaises((ValueError, OSError)): commit_inputs.commit(csv_path, raw)

    def test_44_real_mode_receipt_legacy_and_evidence_provenance(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix="SOURCE_PATH_SENTINEL") as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); csv_path=root/"source.csv"; csv_path.write_bytes(b"CONTENT_SENTINEL")
            for index in range(117): (raw/f"{index:03d}.json").write_bytes(b"CONTENT_SENTINEL")
            legacy=root/"legacy.json"; legacy.write_text(json.dumps(historical_legacy_reference(csv_path,raw)),encoding="utf-8")
            reviewed="a"*40; receipt=root/"receipt.json"; receipt.write_text(json.dumps(full_safety_receipt(reviewed)),encoding="utf-8")
            out=root/"out"
            with synthetic_legacy_identity(legacy): self.assertEqual(commit_inputs.main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(out),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),0)
            data=json.loads(out.read_text()); p=data["provenance"]
            for key in ("tool_blob_oid","tool_sha256","interpreter_path","interpreter_sha256","cwd","argv","allowlisted_environment","source_root_device_inode","redaction_self_test","entry_manifest_sha256","commitment_sha256","safety_receipt_sha256","reviewed_i0","legacy_source_drift"):
                self.assertIn(key,p)
            self.assertTrue(commit_inputs._valid_evidence(p["redaction_self_test"])); self.assertEqual(p["commitment_sha256"],data["commitment_sha256"]); self.assertEqual(p["legacy_source_drift"],"EXACT_MATCH")
            self.assertNotIn("SOURCE_PATH_SENTINEL",out.read_text()); self.assertNotIn("CONTENT_SENTINEL",out.read_text())

    def test_45_cli_error_is_fixed_and_path_free(self):
        err=io.StringIO()
        with contextlib.redirect_stderr(err): code=commit_inputs.main(["--csv","PATH_SENTINEL"])
        self.assertEqual(code,1); self.assertEqual(err.getvalue(),"COMMITMENT_FAILED\n")

    def test_46_redaction_evidence_rejects_skipped_and_incomplete_values(self):
        valid={"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0,"fixture_sha256":"a"*64,"sentinel_sha256":"b"*64,"success":{"exit_status":0,"stdout_sha256":"c"*64,"stderr_sha256":"d"*64},"error":{"exit_status":1,"stdout_sha256":"e"*64,"stderr_sha256":"f"*64}}
        self.assertTrue(commit_inputs._valid_evidence(valid))
        for mutation in ({"status":"SKIPPED"},{"sentinel_match_count":1},{"error":{"exit_status":0,"stdout_sha256":"e"*64,"stderr_sha256":"f"*64}},{"fixture_sha256":"constant"}):
            altered=dict(valid); altered.update(mutation)
            self.assertFalse(commit_inputs._valid_evidence(altered))

    def test_47_receipt_schema_extra_or_target_hash_mismatch_fails_before_output(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"x")
            for index in range(117): (raw/f"{index:03d}.json").write_bytes(b"x")
            legacy=root/"legacy.json"; legacy.write_text(json.dumps(historical_legacy_reference(csv_path,raw)),encoding="utf-8")
            reviewed="a"*40
            for number, mutate in enumerate((lambda receipt: receipt.update({"extra":True}), lambda receipt: receipt["safety_targets"][0].update({"sha256":"0"*64}))):
                receipt_data=full_safety_receipt(reviewed); mutate(receipt_data); receipt=root/f"receipt-{number}.json"; out=root/f"out-{number}.json"; receipt.write_text(json.dumps(receipt_data),encoding="utf-8")
                self.assertEqual(commit_inputs.main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(out),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),1)
                self.assertFalse(out.exists())

    def test_48_invalid_redaction_evidence_blocks_input_open_and_output(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); out=root/"out.json"
            skipped={"status":"SKIPPED"}
            with mock.patch("experiments.v2_4_deterministic.commit_inputs._redaction_self_test", return_value=skipped), \
                 mock.patch("experiments.v2_4_deterministic.commit_inputs._commit_core", side_effect=AssertionError("input opened")):
                self.assertEqual(commit_inputs.main(["--csv",str(root/"csv"),"--raw-dir",str(root/"raw"),"--out",str(out),"--reviewed-i0","a"*40,"--safety-receipt",str(root/"receipt"),"--legacy-reference",str(root/"legacy")]),1)
            self.assertFalse(out.exists())

    def test_49_real_mode_authorization_and_legacy_schema_precede_every_input_open(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"synthetic-raw"; raw.mkdir(); csv_path=root/"synthetic.csv"; csv_path.write_bytes(b"x")
            for index in range(117): (raw/f"{index:03d}.json").write_bytes(b"x")
            legacy=root/"legacy.json"; legacy.write_text(json.dumps(historical_legacy_reference(csv_path,raw)),encoding="utf-8")
            reviewed="a"*40
            evidence={"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0,"fixture_sha256":"a"*64,"sentinel_sha256":"b"*64,"success":{"exit_status":0,"stdout_sha256":"c"*64,"stderr_sha256":"d"*64},"error":{"exit_status":1,"stdout_sha256":"e"*64,"stderr_sha256":"f"*64}}
            cases=[]
            malformed=root/"malformed.json"; malformed.write_text("{}",encoding="utf-8"); cases.append((malformed,legacy))
            cases.append((root/"missing-receipt.json",legacy))
            wrong_i0=full_safety_receipt("b"*40); wrong_i0_path=root/"wrong-i0.json"; wrong_i0_path.write_text(json.dumps(wrong_i0),encoding="utf-8"); cases.append((wrong_i0_path,legacy))
            wrong_target=full_safety_receipt(reviewed); wrong_target["safety_targets"][0]["sha256"]="0"*64; wrong_target_path=root/"wrong-target.json"; wrong_target_path.write_text(json.dumps(wrong_target),encoding="utf-8"); cases.append((wrong_target_path,legacy))
            wrong_tool=full_safety_receipt(reviewed); next(item for item in wrong_tool["safety_targets"] if item["path"].endswith("commit_inputs.py"))["blob_oid"]="0"*40; wrong_tool_path=root/"wrong-tool.json"; wrong_tool_path.write_text(json.dumps(wrong_tool),encoding="utf-8"); cases.append((wrong_tool_path,legacy))
            wrong_interpreter=full_safety_receipt(reviewed); wrong_interpreter["interpreter"]["version"]="wrong"; wrong_interpreter_path=root/"wrong-interpreter.json"; wrong_interpreter_path.write_text(json.dumps(wrong_interpreter),encoding="utf-8"); cases.append((wrong_interpreter_path,legacy))
            bad_legacy=root/"bad-legacy.json"; bad_legacy.write_text("{}",encoding="utf-8"); valid_receipt=root/"valid-receipt.json"; valid_receipt.write_text(json.dumps(full_safety_receipt(reviewed)),encoding="utf-8"); cases.append((valid_receipt,bad_legacy))
            for number, (receipt, legacy_ref) in enumerate(cases):
                with self.subTest(case=number), mock.patch("experiments.v2_4_deterministic.commit_inputs._redaction_self_test", return_value=evidence), \
                     mock.patch("experiments.v2_4_deterministic.commit_inputs._commit_core", side_effect=AssertionError("source opened")) as opened:
                    self.assertEqual(commit_inputs.main(["--csv",str(root/"DO_NOT_OPEN.csv"),"--raw-dir",str(root/"DO_NOT_OPEN.raw"),"--out",str(root/f"out-{number}.json"),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy_ref)]),1)
                    self.assertEqual(opened.call_count,0)
            out=root/"valid-out.json"
            with synthetic_legacy_identity(legacy), mock.patch("experiments.v2_4_deterministic.commit_inputs._redaction_self_test", return_value=evidence), \
                 mock.patch("experiments.v2_4_deterministic.commit_inputs._commit_core", wraps=commit_inputs._commit_core) as opened:
                self.assertEqual(commit_inputs.main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(out),"--reviewed-i0",reviewed,"--safety-receipt",str(valid_receipt),"--legacy-reference",str(legacy)]),0)
                self.assertEqual(opened.call_count,1)
            self.assertTrue(out.is_file())

    def test_53_runtime_ontology_exact_mutation_matrix(self):
        original=scorer.load_ontology()
        mutations=(
            lambda data: data.__setitem__("ontology_version","changed"),
            lambda data: data["normalization"]["clause_boundaries"].reverse(),
            lambda data: data["token_predicates"]["MEMORY_LIMIT_EXCEEDED_V1"].append("extra"),
            lambda data: data["negation"]["syntax"].__setitem__("post_rule","changed"),
            lambda data: data["incidents"][0].__setitem__("trial",1),
            lambda data: data["incidents"][0]["axes"]["mechanism"]["positive_paths"][0]["all_of"][0]["any_of"].append(dict(data["incidents"][0]["axes"]["mechanism"]["positive_paths"][0]["all_of"][0]["any_of"][0])),
        )
        for mutate in mutations:
            data=json.loads(json.dumps(original)); mutate(data)
            with tempfile.NamedTemporaryFile("w",suffix=".json") as handle:
                json.dump(data,handle); handle.flush()
                with self.assertRaises(scorer.InvalidInput): scorer.load_ontology(handle.name)

    def test_54_unresolved_concept_associated_negation_is_invalid(self):
        for text in ("memory limit is not generally relevant", "recommendationservice is never usually implicated"):
            with self.subTest(text=text):
                with self.assertRaises(scorer.InvalidInput): scorer.validate_candidate_bytes(candidate(root=text))
        self.assertFalse(scorer.match("neither cpu throttling nor memory limit",["memory limit"]))
        self.assertTrue(scorer.match("not only cpu throttling but memory limit",["memory limit"]))

    def test_55_producer_runner_canonical_commitment_bridge(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"id\n")
            for number in range(117): (raw/f"{number:03d}.json").write_bytes(b"x")
            envelope=commit_inputs.commit(csv_path,raw); commitment=root/"commitment.json"; commitment.write_text(json.dumps(envelope),encoding="utf-8")
            self.assertEqual(set(envelope),{"raw_files","raw_count","csv","entry_manifest_sha256","commitment_sha256"})
            _, entries, _=run._commitment_gate(commitment,raw,csv_path,synthetic=True)
            self.assertEqual(len(entries),117)
            for remove in ("entry_manifest_sha256","commitment_sha256"):
                malformed=dict(envelope); malformed.pop(remove)
                with self.assertRaises(ValueError): commit_inputs.validate_commitment_schema(malformed,require_provenance=False)

    def test_56_runner_direct_raw_enumeration_rejects_every_unexpected_entry(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"raw"; raw.mkdir()
            for number in range(117): (raw/f"{number:03d}.json").write_bytes(b"x")
            self.assertEqual(len(run.safe_metadata(raw)),117)
            for name, maker in (("extra.txt",lambda path:path.write_bytes(b"x")),("nested",lambda path:path.mkdir()),(".hidden",lambda path:path.write_bytes(b"x"))):
                target=raw/name; maker(target)
                with self.subTest(name=name):
                    with self.assertRaises(run.RunInvalid): run.safe_metadata(raw)
                if target.is_dir(): target.rmdir()
                else: target.unlink()
            (raw/"link.json").symlink_to(raw/"000.json")
            with self.assertRaises(run.RunInvalid): run.safe_metadata(raw)

    def test_57_deviation_exact_schema_and_waiver_values(self):
        self.assertEqual(run.HISTORICAL_DEVIATION_EVIDENCE,{
            "changelog":{"path":"results/experiment_changes_v2_4.md","sha256":"9745dd382a8ef2f7ee120a46e30b09f4efc7948daab0b50583af3c79487bc6ba"},
            "full_implementation_review":{"path":"docs/plans/review_v2_4_deterministic_implementation.md","sha256":"5bceb156ab751e1952b9b90fbd8a4412bd7e1e93d1c595d785bb72391c889e67"},
        })
        self.assertEqual(run.CONVERSATION_DERIVED_ATTESTATION,{"canonical_text":"Conversation-derived operator attestation: on 2026-08-31, python3.11 -m unittest -v tests.test_v2_4_audit machine-parsed Primary03; candidate values or scores were not shown to a human or agent, V2.4-D was not executed, and no output-derived tuning occurred.","sha256":"da2d43ea645c43a568862f48a05af84c3f6d8ab52030c389b462997435eb5ba4"})
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); changelog=root/run.HISTORICAL_DEVIATION_EVIDENCE["changelog"]["path"]; review=root/run.HISTORICAL_DEVIATION_EVIDENCE["full_implementation_review"]["path"]; changelog.parent.mkdir(parents=True); review.parent.mkdir(parents=True); changelog.write_text("historical change"); review.write_text("historical review")
            def git(*args): subprocess.run(["git","-C",str(root),*args],check=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            git("init"); git("add","."); git("-c","user.name=synthetic","-c","user.email=synthetic@example.invalid","commit","-m","snapshot")
            changelog_hash=hashlib.sha256(changelog.read_bytes()).hexdigest(); review_hash=hashlib.sha256(review.read_bytes()).hexdigest(); frozen={"changelog":{"path":str(changelog.relative_to(root)),"sha256":changelog_hash},"full_implementation_review":{"path":str(review.relative_to(root)),"sha256":review_hash}}
            changelog.write_text("alternative historical change"); git("add","."); git("-c","user.name=synthetic","-c","user.email=synthetic@example.invalid","commit","-m","alternative"); alternative_hash=hashlib.sha256(changelog.read_bytes()).hexdigest(); changelog.write_text("mutable current append")
            deviation={"schema_version":"v2.4-d-machine-parse-deviation-1","status":"NON_INFORMATIVE_MACHINE_PARSE_DEVIATION","confirmatory_disposition":"CONFIRMATORY_WITH_DISCLOSED_NONINFORMATIVE_MACHINE_PARSE_DEVIATION","event_date":"2026-08-31","observed_command":"python3.11 -m unittest -v tests.test_v2_4_audit","best_known_head":"c9c94b4","working_tree_state":"UNCOMMITTED_IMPLEMENTATION_PRESENT","observed_test_result":"28_PASS","original_stdout_sha256":"NOT_RETAINED","original_stderr_sha256":"NOT_RETAINED","process_access_zero":False,"text_egress":False,"v2_4_d_execution":False,"output_derived_tuning":False,"approval_waiver_required":True,"evidence_sources":{"changelog":frozen["changelog"],"full_implementation_review":frozen["full_implementation_review"],"conversation_derived_attestation":run.CONVERSATION_DERIVED_ATTESTATION}}
            self.assertEqual(run._validate_deviation(deviation,root,frozen)["status"],"NON_INFORMATIVE_MACHINE_PARSE_DEVIATION")
            alternate=json.loads(json.dumps(deviation)); alternate["evidence_sources"]["changelog"]["sha256"]=alternative_hash
            with self.assertRaises(run.RunInvalid): run._validate_deviation(alternate,root,frozen)
            self_consistent=json.loads(json.dumps(deviation)); self_consistent["evidence_sources"]["conversation_derived_attestation"]={"canonical_text":"arbitrary but self-consistent","sha256":hashlib.sha256(b"arbitrary but self-consistent").hexdigest()}
            with self.assertRaises(run.RunInvalid): run._validate_deviation(self_consistent,root,frozen)
            for mutate in (lambda value:value["evidence_sources"]["changelog"].__setitem__("sha256","0"*64),lambda value:value["evidence_sources"]["changelog"].__setitem__("path","results/other.md")):
                altered=json.loads(json.dumps(deviation)); mutate(altered)
                with self.assertRaises(run.RunInvalid): run._validate_deviation(altered,root,frozen)
            deviation["process_access_zero"]=True
            with self.assertRaises(run.RunInvalid): run._validate_deviation(deviation,root,frozen)

    def test_58_builder_and_runtime_share_exact_validator(self):
        data=scorer.load_ontology(); data["negation"]["tokens"].reverse()
        with tempfile.NamedTemporaryFile("w",suffix=".json") as handle:
            json.dump(data,handle); handle.flush()
            with self.assertRaises(scorer.InvalidInput): scorer.load_ontology(handle.name)
            with self.assertRaises(scorer.InvalidInput): build_ontology.check(Path(handle.name))

    def test_59_full_producer_provenance_bridges_to_runner_without_adapter(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"id\n")
            for number in range(117): (raw/f"raw-{number:03d}.json").write_bytes(b"x")
            legacy=root/"legacy.json"; legacy.write_text(json.dumps(historical_legacy_reference(csv_path,raw)),encoding="utf-8")
            reviewed="a"*40; receipt=root/"receipt.json"; receipt.write_text(json.dumps(full_safety_receipt(reviewed)),encoding="utf-8")
            produced=root/"produced.json"
            with synthetic_legacy_identity(legacy): self.assertEqual(commit_inputs.main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(produced),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),0)
            envelope=json.loads(produced.read_text())
            self.assertEqual(set(envelope),{"raw_files","raw_count","csv","entry_manifest_sha256","commitment_sha256","provenance"})
            commit_inputs.validate_commitment_schema(envelope,require_provenance=True)
            self.assertEqual(len(run._commitment_gate(produced,raw,csv_path,synthetic=False)[1]),117)

    def test_60_commitment_provenance_and_direct_path_mutations_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"id\n")
            for number in range(117): (raw/f"raw-{number:03d}.json").write_bytes(b"x")
            base=commit_inputs.commit(csv_path,raw)
            tool=Path(commit_inputs.__file__).resolve(); interpreter=Path(sys.executable).resolve(); reviewed="c"*40
            stdout=json.dumps({"raw_count":117,"commitment_sha256":base["commitment_sha256"]},separators=(",",":"))+"\n"
            provenance={"tool_blob_oid":commit_inputs._blob_oid(tool),"tool_sha256":hashlib.sha256(tool.read_bytes()).hexdigest(),"interpreter_path":str(interpreter),"interpreter_sha256":hashlib.sha256(interpreter.read_bytes()).hexdigest(),"python_version":sys.version,"cwd":"/synthetic","argv":["--csv","sha256:"+"d"*64,"--raw-dir","sha256:"+"e"*64,"--out","sha256:"+"f"*64,"--reviewed-i0","sha256:"+hashlib.sha256(reviewed.encode()).hexdigest(),"--safety-receipt","sha256:"+"1"*64,"--legacy-reference","sha256:"+"2"*64],"allowlisted_environment":{},"source_root_device_inode":[1,2],"started_utc":"2026-09-01T00:00:00Z","finished_utc":"2026-09-01T00:00:01Z","exit_status":0,"stdout_sha256":hashlib.sha256(stdout.encode()).hexdigest(),"stderr_sha256":hashlib.sha256(b"").hexdigest(),"redaction_self_test":{"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0,"fixture_sha256":"5"*64,"sentinel_sha256":"6"*64,"success":{"exit_status":0,"stdout_sha256":"7"*64,"stderr_sha256":"8"*64},"error":{"exit_status":1,"stdout_sha256":"9"*64,"stderr_sha256":"a"*64}},"raw_count":117,"csv_sha256":base["csv"]["sha256"],"entry_manifest_sha256":base["entry_manifest_sha256"],"commitment_sha256":base["commitment_sha256"],"safety_receipt_sha256":"b"*64,"reviewed_i0":reviewed,"legacy_source_drift":"EXACT_MATCH","operator_attestation":"hash-only streaming"}
            envelope={**base,"provenance":provenance}
            commit_inputs.validate_commitment_schema(envelope,require_provenance=True)
            for mutate in (lambda data:data["provenance"].pop("tool_sha256"),lambda data:data["provenance"].__setitem__("reviewed_code_candidate",reviewed),lambda data:data["provenance"].__setitem__("tool_sha256","0"*64),lambda data:data["provenance"].__setitem__("interpreter_path","/wrong"),lambda data:data["provenance"].__setitem__("stdout_sha256","0"*64),lambda data:data["provenance"].__setitem__("stderr_sha256","0"*64),lambda data:data["provenance"]["argv"].__setitem__(7,"sha256:"+"0"*64),lambda data:data["raw_files"][0].__setitem__("path","evil.txt"),lambda data:data["raw_files"][0].__setitem__("path","dir\\evil.json")):
                altered=json.loads(json.dumps(envelope)); mutate(altered)
                with self.assertRaises(ValueError): commit_inputs.validate_commitment_schema(altered,require_provenance=True)

    def test_61_json_boolean_is_not_a_nonnegative_integer(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"id\n")
            for number in range(117): (raw/f"raw-{number:03d}.json").write_bytes(b"x")
            base=commit_inputs.commit(csv_path,raw)
            def refresh(value):
                value["entry_manifest_sha256"]=hashlib.sha256(json.dumps(value["raw_files"],sort_keys=True,separators=(",",":")).encode()).hexdigest()
                preimage={key:value[key] for key in ("raw_files","raw_count","csv","entry_manifest_sha256")}
                value["commitment_sha256"]=hashlib.sha256(json.dumps(preimage,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
            for mutate in (lambda value:value["raw_files"][0].__setitem__("size",True),lambda value:value["csv"].__setitem__("size",False)):
                altered=json.loads(json.dumps(base)); mutate(altered); refresh(altered)
                with self.assertRaises(ValueError): commit_inputs.validate_commitment_schema(altered,require_provenance=False)
            envelope=json.loads(json.dumps(base)); provenance={"tool_blob_oid":commit_inputs._blob_oid(Path(commit_inputs.__file__).resolve()),"tool_sha256":hashlib.sha256(Path(commit_inputs.__file__).read_bytes()).hexdigest(),"interpreter_path":str(Path(sys.executable).resolve()),"interpreter_sha256":hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),"python_version":sys.version,"cwd":"/synthetic","argv":["--csv","sha256:"+"a"*64,"--raw-dir","sha256:"+"b"*64,"--out","sha256:"+"c"*64,"--reviewed-i0","sha256:"+hashlib.sha256(("d"*40).encode()).hexdigest(),"--safety-receipt","sha256:"+"e"*64,"--legacy-reference","sha256:"+"f"*64],"allowlisted_environment":{},"source_root_device_inode":[1,2],"started_utc":"2026-09-01T00:00:00Z","finished_utc":"2026-09-01T00:00:01Z","exit_status":0,"stdout_sha256":hashlib.sha256((json.dumps({"raw_count":117,"commitment_sha256":base["commitment_sha256"]},separators=(",",":"))+"\n").encode()).hexdigest(),"stderr_sha256":hashlib.sha256(b"").hexdigest(),"redaction_self_test":{"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0,"fixture_sha256":"2"*64,"sentinel_sha256":"3"*64,"success":{"exit_status":0,"stdout_sha256":"4"*64,"stderr_sha256":"5"*64},"error":{"exit_status":1,"stdout_sha256":"6"*64,"stderr_sha256":"7"*64}},"raw_count":117,"csv_sha256":base["csv"]["sha256"],"entry_manifest_sha256":base["entry_manifest_sha256"],"commitment_sha256":base["commitment_sha256"],"safety_receipt_sha256":"8"*64,"reviewed_i0":"d"*40,"legacy_source_drift":"EXACT_MATCH","operator_attestation":"hash-only streaming"}; envelope["provenance"]=provenance
            commit_inputs.validate_commitment_schema(envelope,require_provenance=True)
            envelope["provenance"]["source_root_device_inode"][0]=True
            with self.assertRaises(ValueError): commit_inputs.validate_commitment_schema(envelope,require_provenance=True)

    def test_62_csv_parent_exchange_after_fd_anchor_fails_closed(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); csv_parent=root/"csv-parent"; csv_parent.mkdir(); csv_path=csv_parent/"input.csv"; csv_path.write_bytes(b"x")
            replacement=root/"replacement"; replacement.mkdir(); (replacement/"input.csv").write_bytes(b"x")
            for number in range(117): (raw/f"{number:03d}.json").write_bytes(b"x")
            original=commit_inputs._digest_at
            def exchange(fd,name):
                result=original(fd,name)
                if name=="input.csv":
                    csv_parent.rename(root/"csv-parent-original")
                    csv_parent.symlink_to(replacement,target_is_directory=True)
                return result
            with mock.patch("experiments.v2_4_deterministic.commit_inputs._digest_at",side_effect=exchange):
                with self.assertRaises(ValueError): commit_inputs.commit(csv_path,raw)

    def test_63_receipt_boolean_command_exit_rejects_before_input_open(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); reviewed="a"*40; receipt=root/"receipt.json"; data=full_safety_receipt(reviewed); data["commands"][0]["exit_status"]=False; receipt.write_text(json.dumps(data),encoding="utf-8")
            legacy=root/"legacy.json"; legacy.write_text("{}",encoding="utf-8")
            with mock.patch("experiments.v2_4_deterministic.commit_inputs._redaction_self_test",return_value={"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0,"fixture_sha256":"a"*64,"sentinel_sha256":"b"*64,"success":{"exit_status":0,"stdout_sha256":"c"*64,"stderr_sha256":"d"*64},"error":{"exit_status":1,"stdout_sha256":"e"*64,"stderr_sha256":"f"*64}}), \
                 mock.patch("experiments.v2_4_deterministic.commit_inputs._commit_core",side_effect=AssertionError("input opened")) as opened:
                self.assertEqual(commit_inputs.main(["--csv",str(root/"no.csv"),"--raw-dir",str(root/"no.raw"),"--out",str(root/"out"),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),1)
                self.assertEqual(opened.call_count,0)

    def test_64_legacy_direct_path_schema_blocks_before_input_open(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"x")
            for number in range(117): (raw/f"raw-{number:03d}.json").write_bytes(b"x")
            legacy_data=historical_legacy_reference(csv_path,raw); legacy_data["raw_files"][0]["path"]="nested/bad.json"; legacy=root/"legacy.json"; legacy.write_text(json.dumps(legacy_data),encoding="utf-8")
            reviewed="a"*40; receipt=root/"receipt.json"; receipt.write_text(json.dumps(full_safety_receipt(reviewed)),encoding="utf-8")
            evidence={"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0,"fixture_sha256":"a"*64,"sentinel_sha256":"b"*64,"success":{"exit_status":0,"stdout_sha256":"c"*64,"stderr_sha256":"d"*64},"error":{"exit_status":1,"stdout_sha256":"e"*64,"stderr_sha256":"f"*64}}
            with mock.patch("experiments.v2_4_deterministic.commit_inputs._redaction_self_test",return_value=evidence), \
                 mock.patch("experiments.v2_4_deterministic.commit_inputs._commit_core",side_effect=AssertionError("input opened")) as opened:
                self.assertEqual(commit_inputs.main(["--csv",str(root/"NO_OPEN.csv"),"--raw-dir",str(root/"NO_OPEN.raw"),"--out",str(root/"out"),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),1)
                self.assertEqual(opened.call_count,0)

    def test_65_historical_legacy_csv_shape_is_the_only_accepted_legacy_shape(self):
        self.assertEqual(commit_inputs.HISTORICAL_LEGACY_REFERENCE_IDENTITY,{"blob_oid":"6e5a4cdb0a0950c27b12fc42ea0767da975ab22f","sha256":"c4d9bd1b0ee54a23e1f29a4f6483efe4f051126d5a8020277cad9bf764462085"})
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"x")
            for number in range(117): (raw/f"raw-{number:03d}.json").write_bytes(b"x")
            historical=historical_legacy_reference(csv_path,raw); path=root/"legacy.json"; path.write_text(json.dumps(historical),encoding="utf-8")
            with synthetic_legacy_identity(path): self.assertEqual(commit_inputs._parse_legacy_reference(path)["csv"]["path"],"historical-input.csv")
            active=commit_inputs.commit(csv_path,raw); path.write_text(json.dumps(active),encoding="utf-8")
            with synthetic_legacy_identity(path):
                with self.assertRaises(ValueError): commit_inputs._parse_legacy_reference(path)
            malformed=historical_legacy_reference(csv_path,raw); malformed["csv"]["extra"]=True; path.write_text(json.dumps(malformed),encoding="utf-8")
            with synthetic_legacy_identity(path):
                with self.assertRaises(ValueError): commit_inputs._parse_legacy_reference(path)

    def test_66_shape_valid_fabricated_legacy_identity_blocks_before_input_open(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"x")
            for number in range(117): (raw/f"raw-{number:03d}.json").write_bytes(b"x")
            legacy=root/"fabricated.json"; legacy.write_text(json.dumps(historical_legacy_reference(csv_path,raw)),encoding="utf-8")
            reviewed="a"*40; receipt=root/"receipt.json"; receipt.write_text(json.dumps(full_safety_receipt(reviewed)),encoding="utf-8")
            evidence={"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0,"fixture_sha256":"a"*64,"sentinel_sha256":"b"*64,"success":{"exit_status":0,"stdout_sha256":"c"*64,"stderr_sha256":"d"*64},"error":{"exit_status":1,"stdout_sha256":"e"*64,"stderr_sha256":"f"*64}}
            with mock.patch("experiments.v2_4_deterministic.commit_inputs._redaction_self_test",return_value=evidence), \
                 mock.patch("experiments.v2_4_deterministic.commit_inputs._commit_core",side_effect=AssertionError("input opened")) as opened:
                self.assertEqual(commit_inputs.main(["--csv",str(root/"NO_OPEN.csv"),"--raw-dir",str(root/"NO_OPEN.raw"),"--out",str(root/"out"),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),1)
                self.assertEqual(opened.call_count,0)

    def test_67_receipt_validation_and_digest_bind_the_same_stable_bytes(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); reviewed="a"*40; receipt=root/"receipt.json"; original=full_safety_receipt(reviewed); receipt.write_text(json.dumps(original),encoding="utf-8"); receipt_bytes=receipt.read_bytes()
            raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"x")
            for number in range(117): (raw/f"raw-{number:03d}.json").write_bytes(b"x")
            legacy=root/"legacy.json"; legacy.write_text(json.dumps(historical_legacy_reference(csv_path,raw)),encoding="utf-8")
            parser=commit_inputs._parse_json_bytes; swapped=False
            def parse_then_swap(payload):
                nonlocal swapped
                value=parser(payload)
                if payload==receipt_bytes and not swapped:
                    swapped=True; receipt.write_text(json.dumps(full_safety_receipt(reviewed)|{"session_id":"replacement"}),encoding="utf-8")
                return value
            with synthetic_legacy_identity(legacy), mock.patch("experiments.v2_4_deterministic.commit_inputs._parse_json_bytes",side_effect=parse_then_swap):
                validated,receipt_sha,_,snapshot=commit_inputs._preopen_real_mode(reviewed,receipt,legacy)
            self.assertTrue(swapped); self.assertEqual(validated,original); self.assertEqual(set(snapshot["targets"]),set(commit_inputs._SAFETY_TARGETS)); self.assertEqual(receipt_sha,hashlib.sha256(receipt_bytes).hexdigest()); self.assertNotEqual(receipt_sha,hashlib.sha256(receipt.read_bytes()).hexdigest())

    def test_68_receipt_and_legacy_metadata_symlink_or_ancestor_exchange_blocks_source_open(self):
        evidence={"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0,"fixture_sha256":"a"*64,"sentinel_sha256":"b"*64,"success":{"exit_status":0,"stdout_sha256":"c"*64,"stderr_sha256":"d"*64},"error":{"exit_status":1,"stdout_sha256":"e"*64,"stderr_sha256":"f"*64}}
        for kind in ("receipt-symlink","legacy-symlink","receipt-ancestor","legacy-ancestor"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
                root=Path(td); reviewed="a"*40; receipt_parent=root/"receipt-parent"; legacy_parent=root/"legacy-parent"; receipt_parent.mkdir(); legacy_parent.mkdir(); receipt=receipt_parent/"receipt.json"; receipt.write_text(json.dumps(full_safety_receipt(reviewed)),encoding="utf-8")
                raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"x")
                for number in range(117): (raw/f"raw-{number:03d}.json").write_bytes(b"x")
                legacy=legacy_parent/"legacy.json"; legacy.write_text(json.dumps(historical_legacy_reference(csv_path,raw)),encoding="utf-8")
                target_parent=None; target_name=None
                if kind=="receipt-symlink":
                    link=root/"receipt-link.json"; link.symlink_to(receipt); receipt=link
                elif kind=="legacy-symlink":
                    link=root/"legacy-link.json"; link.symlink_to(legacy); legacy=link
                elif kind=="receipt-ancestor": target_parent=receipt_parent; target_name=receipt.name
                else: target_parent=legacy_parent; target_name=legacy.name
                original_open=os.open; switched=False
                def exchange_open(path,flags,mode=0o777,*,dir_fd=None):
                    nonlocal switched
                    fd=original_open(path,flags,mode) if dir_fd is None else original_open(path,flags,mode,dir_fd=dir_fd)
                    if target_parent is not None and not switched and path==target_name and dir_fd is not None:
                        switched=True; target_parent.rename(root/(target_parent.name+"-moved")); target_parent.symlink_to(root/"replacement",target_is_directory=True)
                    return fd
                with mock.patch("experiments.v2_4_deterministic.commit_inputs._redaction_self_test",return_value=evidence), \
                     mock.patch("experiments.v2_4_deterministic.commit_inputs._commit_core",side_effect=AssertionError("input opened")) as opened, \
                     mock.patch("experiments.v2_4_deterministic.commit_inputs.os.open",side_effect=exchange_open):
                    self.assertEqual(commit_inputs.main(["--csv",str(root/"NO_OPEN.csv"),"--raw-dir",str(root/"NO_OPEN.raw"),"--out",str(root/"out"),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),1)
                    self.assertEqual(opened.call_count,0)

    def test_69_safety_target_single_buffer_rejects_symlink_ancestor_and_mixed_swap(self):
        evidence={"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0,"fixture_sha256":"a"*64,"sentinel_sha256":"b"*64,"success":{"exit_status":0,"stdout_sha256":"c"*64,"stderr_sha256":"d"*64},"error":{"exit_status":1,"stdout_sha256":"e"*64,"stderr_sha256":"f"*64}}
        target_relative="experiments/v2_4_deterministic/analyze.py"
        for kind in ("symlink","ancestor","mixed-second-read"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
                root=Path(td); reviewed="a"*40
                for relative in commit_inputs._SAFETY_TARGETS:
                    target=root/relative; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(("synthetic target "+relative).encode())
                fake_tool=root/"experiments/v2_4_deterministic/commit_inputs.py"; target=root/target_relative; original=target.read_bytes(); alternate=b"swapped target bytes"
                receipt_data=full_safety_receipt_for_root(reviewed,root)
                if kind=="mixed-second-read":
                    record=next(item for item in receipt_data["safety_targets"] if item["path"]==target_relative)
                    record["sha256"]=hashlib.sha256(alternate).hexdigest()
                receipt=root/"receipt.json"; receipt.write_text(json.dumps(receipt_data),encoding="utf-8")
                legacy=root/"legacy.json"; legacy.write_text("{}",encoding="utf-8")
                switched=False; original_open=os.open; original_reader=commit_inputs._read_stable_metadata_bytes
                if kind=="symlink":
                    target.rename(target.with_name("analyze.real")); target.symlink_to(target.with_name("analyze.real"))
                def exchange_open(path,flags,mode=0o777,*,dir_fd=None):
                    nonlocal switched
                    fd=original_open(path,flags,mode) if dir_fd is None else original_open(path,flags,mode,dir_fd=dir_fd)
                    if kind=="ancestor" and not switched and path==target.name and dir_fd is not None:
                        switched=True; target.parent.rename(root/"deterministic-moved"); target.parent.symlink_to(root/"replacement",target_is_directory=True)
                    return fd
                def read_then_swap(path,**kwargs):
                    nonlocal switched
                    result=original_reader(path,**kwargs); payload=result[0] if kwargs.get("with_identity") else result
                    if kind=="mixed-second-read" and Path(path)==target and not switched:
                        switched=True; target.write_bytes(alternate)
                    return result
                with mock.patch.object(commit_inputs,"__file__",str(fake_tool)), \
                     mock.patch("experiments.v2_4_deterministic.commit_inputs._redaction_self_test",return_value=evidence), \
                     mock.patch("experiments.v2_4_deterministic.commit_inputs._commit_core",side_effect=AssertionError("input opened")) as opened, \
                     mock.patch("experiments.v2_4_deterministic.commit_inputs.os.open",side_effect=exchange_open), \
                     mock.patch("experiments.v2_4_deterministic.commit_inputs._read_stable_metadata_bytes",side_effect=read_then_swap):
                    self.assertEqual(commit_inputs.main(["--csv",str(root/"NO_OPEN.csv"),"--raw-dir",str(root/"NO_OPEN.raw"),"--out",str(root/"out"),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),1)
                    self.assertEqual(opened.call_count,0)
                if kind!="symlink": self.assertTrue(switched)

    def test_70_authorization_snapshot_revalidates_before_core_and_before_publication(self):
        evidence={"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0,"fixture_sha256":"a"*64,"sentinel_sha256":"b"*64,"success":{"exit_status":0,"stdout_sha256":"c"*64,"stderr_sha256":"d"*64},"error":{"exit_status":1,"stdout_sha256":"e"*64,"stderr_sha256":"f"*64}}
        for stage,target_relative,expected_core_calls in (("before-core","experiments/v2_4_deterministic/analyze.py",0),("after-core","experiments/v2_4_deterministic/commit_inputs.py",1)):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
                root=Path(td); reviewed="a"*40
                for relative in commit_inputs._SAFETY_TARGETS:
                    target=root/relative; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(("reviewed target "+relative).encode())
                fake_tool=root/"experiments/v2_4_deterministic/commit_inputs.py"; target=root/target_relative
                raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"x")
                for number in range(117): (raw/f"raw-{number:03d}.json").write_bytes(b"x")
                legacy=root/"legacy.json"; legacy.write_text(json.dumps(historical_legacy_reference(csv_path,raw)),encoding="utf-8")
                receipt=root/"receipt.json"; receipt.write_text(json.dumps(full_safety_receipt_for_root(reviewed,root)),encoding="utf-8"); out=root/"out.json"
                original_preopen=commit_inputs._preopen_real_mode; original_core=commit_inputs._commit_core
                def preopen_then_swap(*args):
                    result=original_preopen(*args)
                    if stage=="before-core": target.write_bytes(b"changed after authorization")
                    return result
                def core_then_swap(*args):
                    result=original_core(*args)
                    if stage=="after-core": target.write_bytes(b"changed after source hashing")
                    return result
                with mock.patch.object(commit_inputs,"__file__",str(fake_tool)), \
                     synthetic_legacy_identity(legacy), \
                     mock.patch("experiments.v2_4_deterministic.commit_inputs._redaction_self_test",return_value=evidence), \
                     mock.patch("experiments.v2_4_deterministic.commit_inputs._preopen_real_mode",side_effect=preopen_then_swap), \
                     mock.patch("experiments.v2_4_deterministic.commit_inputs._commit_core",side_effect=core_then_swap) as opened:
                    self.assertEqual(commit_inputs.main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(out),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),1)
                    self.assertEqual(opened.call_count,expected_core_calls)
                self.assertFalse(out.exists())

    def test_71_target_swap_after_schema_validation_blocks_first_output_mutation(self):
        evidence={"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0,"fixture_sha256":"a"*64,"sentinel_sha256":"b"*64,"success":{"exit_status":0,"stdout_sha256":"c"*64,"stderr_sha256":"d"*64},"error":{"exit_status":1,"stdout_sha256":"e"*64,"stderr_sha256":"f"*64}}
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); reviewed="a"*40
            for relative in commit_inputs._SAFETY_TARGETS:
                target=root/relative; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(("reviewed target "+relative).encode())
            fake_tool=root/"experiments/v2_4_deterministic/commit_inputs.py"; changed=root/"experiments/v2_4_deterministic/analyze.py"
            raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"x")
            for number in range(117): (raw/f"raw-{number:03d}.json").write_bytes(b"x")
            legacy=root/"legacy.json"; legacy.write_text(json.dumps(historical_legacy_reference(csv_path,raw)),encoding="utf-8")
            receipt=root/"receipt.json"; receipt.write_text(json.dumps(full_safety_receipt_for_root(reviewed,root)),encoding="utf-8"); out=root/"out.json"; original_validate=commit_inputs.validate_commitment_schema
            def validate_then_swap(*args,**kwargs):
                value=original_validate(*args,**kwargs); changed.write_bytes(b"changed after schema validation"); return value
            with mock.patch.object(commit_inputs,"__file__",str(fake_tool)), \
                 synthetic_legacy_identity(legacy), \
                 mock.patch("experiments.v2_4_deterministic.commit_inputs._redaction_self_test",return_value=evidence), \
                 mock.patch("experiments.v2_4_deterministic.commit_inputs._commit_core",wraps=commit_inputs._commit_core) as opened, \
                 mock.patch("experiments.v2_4_deterministic.commit_inputs.validate_commitment_schema",side_effect=validate_then_swap):
                self.assertEqual(commit_inputs.main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(out),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),1)
                self.assertEqual(opened.call_count,1)
            self.assertFalse(out.exists())

    def test_72_real_publication_refuses_existing_file_or_symlink(self):
        evidence={"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0,"fixture_sha256":"a"*64,"sentinel_sha256":"b"*64,"success":{"exit_status":0,"stdout_sha256":"c"*64,"stderr_sha256":"d"*64},"error":{"exit_status":1,"stdout_sha256":"e"*64,"stderr_sha256":"f"*64}}
        for kind in ("file","symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
                root=Path(td); raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"x")
                for number in range(117): (raw/f"raw-{number:03d}.json").write_bytes(b"x")
                legacy=root/"legacy.json"; legacy.write_text(json.dumps(historical_legacy_reference(csv_path,raw)),encoding="utf-8")
                reviewed="a"*40; receipt=root/"receipt.json"; receipt.write_text(json.dumps(full_safety_receipt(reviewed)),encoding="utf-8"); out=root/"out.json"; preserved=root/"preserved"
                if kind=="file": out.write_bytes(b"preserve")
                else: preserved.write_bytes(b"preserve"); out.symlink_to(preserved)
                with synthetic_legacy_identity(legacy), mock.patch("experiments.v2_4_deterministic.commit_inputs._redaction_self_test",return_value=evidence):
                    self.assertEqual(commit_inputs.main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(out),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),1)
                self.assertEqual((preserved if kind=="symlink" else out).read_bytes(),b"preserve")

    def test_73_ontology_acceptance_freezes_literal_path_polarity_and_provenance(self):
        base=scorer.load_ontology()
        mutations=(
            lambda data:data["incidents"][0]["axes"]["component_mention"]["positive_paths"][0]["all_of"][0]["any_of"][0].__setitem__("value","same-shape replacement"),
            lambda data:data["incidents"][0]["axes"]["component_mention"]["positive_paths"][0].__setitem__("path_id","OTHER_PATH"),
            lambda data:data["incidents"][0]["axes"]["component_mention"]["positive_paths"][0]["all_of"][0]["any_of"][0].__setitem__("polarity","absence_assertion"),
            lambda data:data["incidents"][0]["axes"]["component_mention"]["positive_paths"][0]["all_of"][0]["any_of"][0]["provenance"].__setitem__("source_ref","other"),
        )
        for mutate in mutations:
            data=json.loads(json.dumps(base)); mutate(data)
            with tempfile.NamedTemporaryFile("w",suffix=".json") as handle:
                json.dump(data,handle); handle.flush()
                with self.assertRaises(scorer.InvalidInput): scorer.load_ontology(handle.name)

    def test_74_runner_metadata_duplicate_keys_fail_at_every_nesting_level(self):
        for payload in (b'{"approval":"A","approval":"B"}',b'{"outer":{"key":1,"key":2}}'):
            with self.assertRaises(run.RunInvalid): run._load_json_metadata_bytes(payload)

    def test_75_real_approved_override_requires_lifetime_binding_before_any_input_open(self):
        with mock.patch("experiments.v2_4_deterministic.run._revalidate_full_inputs",side_effect=run.RunInvalid("APPROVAL_LIFETIME_INVALID")) as gate, \
             mock.patch("experiments.v2_4_deterministic.run._open_verified",side_effect=AssertionError("input opened")):
            with self.assertRaisesRegex(run.RunInvalid,"APPROVAL_LIFETIME_INVALID"):
                run.run_campaign(approval=Path("approval"),commitment=Path("unapproved"),raw_dir=Path("raw"),csv_path=Path("csv"),ground_truth=Path("gt"),ontology=Path("ontology"),output=Path("out"),approved_override={},full_authorization={})
        gate.assert_called_once()

    def test_75b_full_binding_rejects_noncanonical_cli_path_before_metadata_open(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); approval={"commitment":{"sha256":"a"*64},"i1_targets":{run.ONTOLOGY_DOCUMENT:{"sha256":"b"*64}}}; preflight={"repository_root":str(root),"verified_identities":{}}
            with mock.patch("experiments.v2_4_deterministic.run._open_verified",side_effect=AssertionError("metadata opened")):
                with self.assertRaises(run.RunInvalid): run._bind_full_inputs(approval,preflight,root/"other.json",root/run.ONTOLOGY_DOCUMENT)

    def test_76_release_manifest_has_independent_methodology_audit_fields(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw,csv_path,commitment,ground_truth,approval=self._fixture(root); release=root/"release"
            run.run_full(approval=approval,commitment=commitment,raw_dir=raw,csv_path=csv_path,ground_truth=ground_truth,ontology=Path(scorer.__file__).with_name("ontology_v1.json"),output=release,code_candidate="0"*40,implementation_candidate="1"*40,approved_bundle="2"*40,execution_commit="3"*40,synthetic=True)
            summary=json.loads((release/"final"/"summary.json").read_text()); manifest=json.loads((release/"manifest.json").read_text())
            self.assertEqual(summary["methodology_disposition"],analyze.METHODOLOGY_DISPOSITION)
            for key in ("primary_status","remediation_regression_flag","methodology_disposition","run1_started_utc","run2_finished_utc","verified_i0_i1_bundle_approval","actual_input_preflight","deviation_flags"):
                self.assertIn(key,manifest)

    def test_77_invalid_receipt_exclusive_tmp_preserves_existing_symlink_and_regular(self):
        for kind in ("regular","symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
                root=Path(td); output=root/"release"; temporary=root/".release.invalid.tmp"; victim=root/"victim"; victim.write_bytes(b"preserve")
                if kind=="regular": temporary.write_bytes(b"preserve")
                else: temporary.symlink_to(victim)
                with self.assertRaises(run.RunInvalid): run._write_invalid_receipt(output,"INVALID")
                self.assertEqual(victim.read_bytes(),b"preserve")

    def test_78_real_repository_gate_rejects_alternate_approval_before_read(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td)
            with mock.patch("experiments.v2_4_deterministic.run._repo_root", return_value=root), \
                 mock.patch("experiments.v2_4_deterministic.run._stable_metadata_bytes", side_effect=AssertionError("approval opened")):
                with self.assertRaisesRegex(run.RunInvalid, "APPROVAL_PATH_MISMATCH"):
                    run._repository_gate(
                        approval_path=root / "copied-approval.md", execution_authorization_path=root / run.EXECUTION_AUTHORIZATION_DOCUMENT, code_candidate="0" * 40,
                        implementation_candidate="1" * 40, approved_bundle="2" * 40,
                        execution_commit="3" * 40,
                    )

    def test_79_canonical_approval_symlink_is_rejected_before_schema_parse(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td)
            canonical = root / run.APPROVAL_DOCUMENT
            canonical.parent.mkdir(parents=True)
            target = root / "approval-target"; target.write_bytes(b"{}")
            canonical.symlink_to(target)
            with mock.patch("experiments.v2_4_deterministic.run._repo_root", return_value=root), \
                 mock.patch("experiments.v2_4_deterministic.run._strict_approval_value", side_effect=AssertionError("schema parsed")):
                with self.assertRaises(run.RunInvalid):
                    run._repository_gate(
                        approval_path=canonical, execution_authorization_path=root / run.EXECUTION_AUTHORIZATION_DOCUMENT, code_candidate="0" * 40,
                        implementation_candidate="1" * 40, approved_bundle="2" * 40,
                        execution_commit="3" * 40,
                    )

    def test_80_approval_snapshot_mutation_blocks_before_other_full_input_open(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td)
            approval_path = root / run.APPROVAL_DOCUMENT
            approval_path.parent.mkdir(parents=True)
            approval_path.write_bytes(b"approved")
            commitment = root / run.COMMITMENT_DOCUMENT
            commitment.parent.mkdir(parents=True, exist_ok=True); commitment.write_bytes(b"commitment")
            ontology = root / run.ONTOLOGY_DOCUMENT
            ontology.parent.mkdir(parents=True, exist_ok=True); ontology.write_bytes(b"ontology")
            approval_bytes, stable = run._stable_metadata_bytes(approval_path, with_identity=True)
            record = {"blob_oid": run._blob_oid_bytes(approval_bytes), "sha256": run._sha256_bytes(approval_bytes)}
            snapshot = {
                "_marker": run._FULL_AUTHORIZATION_MARKER, "root": root,
                "commitment_path": commitment, "ontology_path": ontology,
                "commitment_sha256": run._sha256_bytes(b"commitment"), "ontology_sha256": run._sha256_bytes(b"ontology"),
                "identities": {"approval": "3" * 40}, "i1_targets": {},
                "approval_path": approval_path, "approval_record": record,
                "approval_stable_identity": stable,
            }
            # Same bytes on a replacement inode must still invalidate authority.
            approval_path.rename(approval_path.with_name("approval-old.md"))
            approval_path.write_bytes(b"swapped approval bytes")
            with mock.patch("experiments.v2_4_deterministic.run._open_verified", side_effect=AssertionError("other input opened")):
                with self.assertRaisesRegex(run.RunInvalid, "APPROVAL_LIFETIME_INVALID"):
                    run._revalidate_full_inputs(snapshot, commitment, ontology)

    def test_81_invalid_receipt_parent_exchange_preserves_replacement_victim(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td); parent = root / "parent"; parent.mkdir(); replacement = root / "replacement"; replacement.mkdir()
            output = parent / "release"; victim = replacement / ".release.invalid.json"; victim.write_bytes(b"preserve")
            original_open = os.open; switched = False
            def exchange_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal switched
                fd = original_open(path, flags, mode) if dir_fd is None else original_open(path, flags, mode, dir_fd=dir_fd)
                if not switched and path == ".release.invalid.tmp" and dir_fd is not None:
                    switched = True
                    parent.rename(root / "parent-moved")
                    parent.symlink_to(replacement, target_is_directory=True)
                return fd
            with mock.patch("experiments.v2_4_deterministic.run.os.open", side_effect=exchange_open):
                with self.assertRaisesRegex(run.RunInvalid, "SAFE_PUBLICATION_FAILED"):
                    run._write_invalid_receipt(output, "INVALID")
            self.assertTrue(switched)
            self.assertEqual(victim.read_bytes(), b"preserve")

    def test_82_invalid_receipt_preserves_existing_destination_file_or_symlink(self):
        for kind in ("regular", "symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
                root = Path(td); output = root / "release"; destination = root / ".release.invalid.json"
                victim = root / "victim"; victim.write_bytes(b"preserve")
                if kind == "regular":
                    destination.write_bytes(b"preserve")
                else:
                    destination.symlink_to(victim)
                with self.assertRaisesRegex(run.RunInvalid, "SAFE_PUBLICATION_FAILED"):
                    run._write_invalid_receipt(output, "INVALID")
                self.assertEqual(victim.read_bytes(), b"preserve")
                if kind == "regular":
                    self.assertEqual(destination.read_bytes(), b"preserve")

    def test_83_execution_authorization_schema_is_exact_and_binds_user_approval(self):
        approval = {
            "approved_bundle": "b" * 40,
            "user_approval_utc": "2026-09-01T00:00:00Z",
            "user_approval_text": "synthetic explicit authorization",
        }
        value = {
            "authorization_version": run.EXECUTION_AUTHORIZATION_VERSION,
            "status": run.EXECUTION_AUTHORIZATION_STATUS,
            "execution_commit": "a" * 40,
            "approved_bundle": approval["approved_bundle"],
            "approval_path": run.APPROVAL_DOCUMENT,
            "approval_blob_oid": "c" * 40,
            "approval_sha256": "d" * 64,
            "user_approval_utc": approval["user_approval_utc"],
            "user_approval_text_sha256": hashlib.sha256(approval["user_approval_text"].encode()).hexdigest(),
        }
        self.assertEqual(run._strict_execution_authorization_value(value, approval, execution_commit="a" * 40), value)
        for mutate in (
            lambda item: item.__setitem__("status", "OTHER"),
            lambda item: item.__setitem__("unexpected", "x"),
            lambda item: item.__setitem__("approval_path", "copied-approval.md"),
            lambda item: item.__setitem__("user_approval_text_sha256", "0" * 64),
        ):
            changed = dict(value); mutate(changed)
            with self.assertRaises(run.RunInvalid):
                run._strict_execution_authorization_value(changed, approval, execution_commit="a" * 40)

    def test_84_sidecar_inode_swap_blocks_lifetime_before_other_input_open(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td)
            approval_path = root / run.APPROVAL_DOCUMENT
            approval_path.parent.mkdir(parents=True); approval_path.write_bytes(b"approval")
            sidecar = root / run.EXECUTION_AUTHORIZATION_DOCUMENT
            sidecar.write_bytes(b"sidecar")
            commitment = root / run.COMMITMENT_DOCUMENT
            commitment.write_bytes(b"commitment")
            ontology = root / run.ONTOLOGY_DOCUMENT
            ontology.parent.mkdir(parents=True, exist_ok=True); ontology.write_bytes(b"ontology")
            approval_bytes, approval_stable = run._stable_metadata_bytes(approval_path, with_identity=True)
            sidecar_bytes, sidecar_stable = run._stable_metadata_bytes(sidecar, with_identity=True)
            snapshot = {
                "_marker": run._FULL_AUTHORIZATION_MARKER, "root": root,
                "commitment_path": commitment, "ontology_path": ontology,
                "commitment_sha256": run._sha256_bytes(b"commitment"), "ontology_sha256": run._sha256_bytes(b"ontology"),
                "identities": {"approval": "3" * 40}, "i1_targets": {},
                "approval_path": approval_path,
                "approval_record": {"blob_oid": run._blob_oid_bytes(approval_bytes), "sha256": run._sha256_bytes(approval_bytes)},
                "approval_stable_identity": approval_stable,
                "execution_authorization_path": sidecar,
                "execution_authorization_record": {"blob_oid": run._blob_oid_bytes(sidecar_bytes), "sha256": run._sha256_bytes(sidecar_bytes)},
                "execution_authorization_stable_identity": sidecar_stable,
            }
            sidecar.rename(sidecar.with_name("execution-authorization-old.json"))
            sidecar.write_bytes(b"sidecar")
            with mock.patch("experiments.v2_4_deterministic.run._git_blob_record", return_value=snapshot["approval_record"]), \
                 mock.patch("experiments.v2_4_deterministic.run._open_verified", side_effect=AssertionError("other input opened")):
                with self.assertRaisesRegex(run.RunInvalid, "APPROVAL_LIFETIME_INVALID"):
                    run._revalidate_full_inputs(snapshot, commitment, ontology)

    def test_85_post_a_sidecar_makes_real_i0_i1_b_a_gate_constructible(self):
        """A sidecar created after A binds A without making A self-referential."""
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td)
            def git(*args, capture=False):
                result = subprocess.run(["git", "-C", str(root), *args], check=True, stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return result.stdout.decode().strip() if capture else ""
            def commit(message):
                git("add", ".")
                git("-c", "user.name=synthetic", "-c", "user.email=synthetic@example.invalid", "commit", "-m", message)
                return git("rev-parse", "HEAD", capture=True)
            def record(revision, path):
                oid = git("rev-parse", f"{revision}:{path}", capture=True)
                payload = subprocess.run(["git", "-C", str(root), "cat-file", "blob", oid], check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
                return {"blob_oid": oid, "sha256": hashlib.sha256(payload).hexdigest()}

            git("init"); (root / "AGENTS.md").write_text("synthetic", encoding="utf-8")
            preexisting = set(run.I0_SAFETY_SCOPE) | {"docs/plans/experiment_plan_v2_4_deterministic.md", run.SEMANTIC_REVIEW, run.IMPLEMENTATION_REVIEW}
            for relative in preexisting:
                path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("i0 " + relative, encoding="utf-8")
            i0 = commit("i0")
            for relative in (run.COMMITMENT_DOCUMENT, run.DEVIATION_DOCUMENT):
                path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"{}")
            i1 = commit("i1")
            (root / run.IMPLEMENTATION_REVIEW).write_text("b review", encoding="utf-8")
            bundle = commit("bundle")

            receipt_sha = hashlib.sha256(b"{}").hexdigest()
            approval = {
                "approval_version": "v2.4-d-approval-3", "approval": "APPROVED", "approved_bundle": bundle,
                "implementation_candidate": i1, "code_candidate": i0,
                "semantic_review": {"path": run.SEMANTIC_REVIEW, **record(i1, run.SEMANTIC_REVIEW)},
                "safety_receipt": {"path": "receipt.json", "sha256": receipt_sha, "code_candidate": i0, "tool_blob_oid": record(i0, "experiments/v2_4_deterministic/commit_inputs.py")["blob_oid"]},
                "implementation_review": {"path": run.IMPLEMENTATION_REVIEW, **record(bundle, run.IMPLEMENTATION_REVIEW), "code_candidate": i0, "implementation_candidate": i1},
                "i0_safety_scope": {path: record(i0, path) for path in run.I0_SAFETY_SCOPE},
                "i1_targets": {path: record(i1, path) for path in run.I1_TARGETS},
                "commitment": {"path": run.COMMITMENT_DOCUMENT, "sha256": receipt_sha, "commitment_sha256": "c" * 64, "csv_sha256": "d" * 64, "raw_manifest_sha256": hashlib.sha256(run._canonical([])).hexdigest(), "reviewed_tool_blob_oid": record(i0, "experiments/v2_4_deterministic/commit_inputs.py")["blob_oid"], "safety_receipt_sha256": receipt_sha, "reviewed_i0": i0},
                "ground_truth": {"sha256": run.GT_SHA256, "projection_sha256": run.GT_PROJECTION_SHA256},
                "interpreter": {"path": str(Path(sys.executable).resolve()), "sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(), "version": sys.version},
                "deviation": {"path": run.DEVIATION_DOCUMENT, "sha256": receipt_sha},
                "methodology_waiver_acknowledged": True,
                "user_approval_utc": "2026-09-01T00:00:00Z", "user_approval_text": "synthetic user authorization",
            }
            approval_path = root / run.APPROVAL_DOCUMENT
            approval_path.write_bytes(json.dumps(approval, sort_keys=True).encode())
            execution = commit("approval")
            approval_record = record(execution, run.APPROVAL_DOCUMENT)
            sidecar = root / run.EXECUTION_AUTHORIZATION_DOCUMENT
            sidecar.write_text(json.dumps({
                "authorization_version": run.EXECUTION_AUTHORIZATION_VERSION, "status": run.EXECUTION_AUTHORIZATION_STATUS,
                "execution_commit": execution, "approved_bundle": bundle, "approval_path": run.APPROVAL_DOCUMENT,
                "approval_blob_oid": approval_record["blob_oid"], "approval_sha256": approval_record["sha256"],
                "user_approval_utc": approval["user_approval_utc"], "user_approval_text_sha256": hashlib.sha256(approval["user_approval_text"].encode()).hexdigest(),
            }, sort_keys=True), encoding="utf-8")
            envelope = {"raw_files": [], "raw_count": 117, "csv": {"sha256": "d" * 64}, "commitment_sha256": "c" * 64, "provenance": {"reviewed_i0": i0, "tool_blob_oid": approval["safety_receipt"]["tool_blob_oid"], "safety_receipt_sha256": receipt_sha}}
            with mock.patch("experiments.v2_4_deterministic.run._repo_root", return_value=root), \
                 mock.patch("experiments.v2_4_deterministic.run._verified_external_file", return_value=b"{}"), \
                 mock.patch("experiments.v2_4_deterministic.run._load_json_metadata", return_value=envelope), \
                 mock.patch("experiments.v2_4_deterministic.run._validate_deviation"), \
                 mock.patch("experiments.v2_4_deterministic.commit_inputs.validate_commitment_schema"), \
                 mock.patch("experiments.v2_4_deterministic.run.safe_metadata", side_effect=AssertionError("candidate opened")):
                accepted, preflight = run._repository_gate(
                    approval_path=approval_path, execution_authorization_path=sidecar, code_candidate=i0,
                    implementation_candidate=i1, approved_bundle=bundle, execution_commit=execution,
                )
            self.assertEqual(accepted["approval_version"], "v2.4-d-approval-3")
            self.assertEqual(preflight["execution_authorization"]["record"], {"blob_oid": run._blob_oid_bytes(sidecar.read_bytes()), "sha256": hashlib.sha256(sidecar.read_bytes()).hexdigest()})

    def test_86_sidecar_rejects_alternate_direct_symlink_and_ancestor_symlink(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td)
            canonical = root / run.EXECUTION_AUTHORIZATION_DOCUMENT
            canonical.parent.mkdir(parents=True); target = root / "target"; target.write_bytes(b"{}")
            with self.assertRaisesRegex(run.RunInvalid, "EXECUTION_AUTHORIZATION_PATH_MISMATCH"):
                run._canonical_execution_authorization_path(root, root / "alternate.json")
            canonical.symlink_to(target)
            with self.assertRaises(run.RunInvalid):
                run._stable_metadata_bytes(canonical)
            canonical.unlink()
            docs = root / "docs"; moved = root / "docs-old"; docs.rename(moved); docs.symlink_to(moved, target_is_directory=True)
            with self.assertRaises(run.RunInvalid):
                run._stable_metadata_bytes(canonical)

    def test_87_real_full_mode_requires_sidecar_before_candidate_input(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td)
            with mock.patch("experiments.v2_4_deterministic.run.safe_metadata", side_effect=AssertionError("candidate opened")):
                with self.assertRaisesRegex(run.RunInvalid, "EXECUTION_AUTHORIZATION_REQUIRED"):
                    run.run_full(
                        approval=root / "approval", commitment=root / "commitment", raw_dir=root / "candidate",
                        csv_path=root / "candidate.csv", ground_truth=root / "gt", ontology=root / "ontology",
                        output=root / "release", code_candidate="0" * 40, implementation_candidate="1" * 40,
                        approved_bundle="2" * 40, execution_commit="3" * 40,
                    )


if __name__ == "__main__":
    unittest.main()
