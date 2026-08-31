import contextlib
import csv
import hashlib
import io
import json
import os
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


def full_safety_receipt(reviewed_i0):
    """A code-only receipt with every reviewed target content-addressed."""
    repo = Path(__file__).resolve().parents[1]
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
                        approval=approval, commitment=root / "commitment.json", raw_dir=sentinel, csv_path=sentinel,
                        ground_truth=root / "ground_truth.csv", ontology=Path(scorer.__file__).with_name("ontology_v1.json"),
                        output=root / "release", code_candidate="0" * 40, implementation_candidate="1" * 40,
                        approved_bundle="2" * 40, execution_commit="3" * 40,
                    )
            self.assertFalse(sentinel.exists())

    def test_50_synthetic_i0_i1_chain_requires_absent_then_two_additions(self):
        i0, i1, bundle, execution = ("0" * 40, "1" * 40, "2" * 40, "3" * 40)
        approval = {
            "code_candidate": i0, "implementation_candidate": i1,
            "approved_bundle": bundle, "execution_commit": execution,
        }
        with mock.patch("experiments.v2_4_deterministic.run._repo_root", return_value=Path.cwd()), \
             mock.patch("experiments.v2_4_deterministic.run._strict_approval_gate", return_value=approval), \
             mock.patch("experiments.v2_4_deterministic.run._git", side_effect=(execution, "", bundle, i1, i0)), \
             mock.patch("experiments.v2_4_deterministic.run._git_path_must_be_absent") as absent, \
             mock.patch("experiments.v2_4_deterministic.run._exact_diff", side_effect=run.RunInvalid("STOP_AFTER_I0_I1")) as exact_diff:
            with self.assertRaisesRegex(run.RunInvalid, "STOP_AFTER_I0_I1"):
                run._repository_gate(
                    approval_path=Path("synthetic-approval.json"), code_candidate=i0,
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
            legacy=root/"legacy.json"; legacy.write_text(json.dumps(commit_inputs.commit(csv_path,raw)),encoding="utf-8")
            reviewed="a"*40; receipt=root/"receipt.json"; receipt.write_text(json.dumps(full_safety_receipt(reviewed)),encoding="utf-8")
            stdout=io.StringIO()
            with contextlib.redirect_stdout(stdout): self.assertEqual(commit_inputs.main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(out_path),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),0)
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
            legacy=root/"legacy.json"; legacy.write_text(json.dumps(commit_inputs.commit(csv_path,raw)),encoding="utf-8")
            reviewed="a"*40; receipt=root/"receipt.json"; receipt.write_text(json.dumps(full_safety_receipt(reviewed)),encoding="utf-8")
            out=root/"out"; self.assertEqual(commit_inputs.main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(out),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),0)
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
            legacy=root/"legacy.json"; legacy.write_text(json.dumps(commit_inputs.commit(csv_path,raw)),encoding="utf-8")
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
            legacy=root/"legacy.json"; legacy.write_text(json.dumps(commit_inputs.commit(csv_path,raw)),encoding="utf-8")
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
            with mock.patch("experiments.v2_4_deterministic.commit_inputs._redaction_self_test", return_value=evidence), \
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
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); changelog=root/"change.md"; review=root/"review.md"; changelog.write_text("change"); review.write_text("review")
            text="attestation"; deviation={"schema_version":"v2.4-d-machine-parse-deviation-1","status":"NON_INFORMATIVE_MACHINE_PARSE_DEVIATION","confirmatory_disposition":"CONFIRMATORY_WITH_DISCLOSED_NONINFORMATIVE_MACHINE_PARSE_DEVIATION","event_date":"2026-08-31","observed_command":"python3.11 -m unittest -v tests.test_v2_4_audit","best_known_head":"c9c94b4","working_tree_state":"UNCOMMITTED_IMPLEMENTATION_PRESENT","observed_test_result":"28_PASS","original_stdout_sha256":"NOT_RETAINED","original_stderr_sha256":"NOT_RETAINED","process_access_zero":False,"text_egress":False,"v2_4_d_execution":False,"output_derived_tuning":False,"approval_waiver_required":True,"evidence_sources":{"changelog":{"path":"change.md","sha256":hashlib.sha256(changelog.read_bytes()).hexdigest()},"full_implementation_review":{"path":"review.md","sha256":hashlib.sha256(review.read_bytes()).hexdigest()},"conversation_derived_attestation":{"canonical_text":text,"sha256":hashlib.sha256(text.encode()).hexdigest()}}}
            self.assertEqual(run._validate_deviation(deviation,root)["status"],"NON_INFORMATIVE_MACHINE_PARSE_DEVIATION")
            deviation["process_access_zero"]=True
            with self.assertRaises(run.RunInvalid): run._validate_deviation(deviation,root)

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
            legacy=root/"legacy.json"; legacy.write_text(json.dumps(commit_inputs.commit(csv_path,raw)),encoding="utf-8")
            reviewed="a"*40; receipt=root/"receipt.json"; receipt.write_text(json.dumps(full_safety_receipt(reviewed)),encoding="utf-8")
            produced=root/"produced.json"
            self.assertEqual(commit_inputs.main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(produced),"--reviewed-i0",reviewed,"--safety-receipt",str(receipt),"--legacy-reference",str(legacy)]),0)
            envelope=json.loads(produced.read_text())
            self.assertEqual(set(envelope),{"raw_files","raw_count","csv","entry_manifest_sha256","commitment_sha256","provenance"})
            commit_inputs.validate_commitment_schema(envelope,require_provenance=True)
            self.assertEqual(len(run._commitment_gate(produced,raw,csv_path,synthetic=False)[1]),117)

    def test_60_commitment_provenance_and_direct_path_mutations_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(b"id\n")
            for number in range(117): (raw/f"raw-{number:03d}.json").write_bytes(b"x")
            base=commit_inputs.commit(csv_path,raw)
            provenance={"tool_blob_oid":"a"*40,"tool_sha256":"b"*64,"interpreter_path":"/synthetic/python","interpreter_sha256":"c"*64,"python_version":sys.version,"cwd":"/synthetic","argv":["--csv","sha256:"+"d"*64,"--raw-dir","sha256:"+"e"*64,"--out","sha256:"+"f"*64,"--reviewed-i0","sha256:"+"0"*64,"--safety-receipt","sha256:"+"1"*64,"--legacy-reference","sha256:"+"2"*64],"allowlisted_environment":{},"source_root_device_inode":[1,2],"started_utc":"2026-09-01T00:00:00Z","finished_utc":"2026-09-01T00:00:01Z","exit_status":0,"stdout_sha256":"3"*64,"stderr_sha256":"4"*64,"redaction_self_test":{"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0,"fixture_sha256":"5"*64,"sentinel_sha256":"6"*64,"success":{"exit_status":0,"stdout_sha256":"7"*64,"stderr_sha256":"8"*64},"error":{"exit_status":1,"stdout_sha256":"9"*64,"stderr_sha256":"a"*64}},"raw_count":117,"csv_sha256":base["csv"]["sha256"],"entry_manifest_sha256":base["entry_manifest_sha256"],"commitment_sha256":base["commitment_sha256"],"safety_receipt_sha256":"b"*64,"reviewed_i0":"c"*40,"legacy_source_drift":"EXACT_MATCH","operator_attestation":"hash-only streaming"}
            envelope={**base,"provenance":provenance}
            commit_inputs.validate_commitment_schema(envelope,require_provenance=True)
            for mutate in (lambda data:data["provenance"].pop("tool_sha256"),lambda data:data["provenance"].__setitem__("reviewed_code_candidate","c"*40),lambda data:data["raw_files"][0].__setitem__("path","evil.txt"),lambda data:data["raw_files"][0].__setitem__("path","dir\\evil.json")):
                altered=json.loads(json.dumps(envelope)); mutate(altered)
                with self.assertRaises(ValueError): commit_inputs.validate_commitment_schema(altered,require_provenance=True)


if __name__ == "__main__":
    unittest.main()
