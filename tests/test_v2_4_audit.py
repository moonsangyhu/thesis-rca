import csv
import copy
import hashlib
import io
import os
import socket
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
import urllib.request
from collections import OrderedDict
from pathlib import Path
from unittest.mock import patch

from experiments.v2_4.constants import (
    CORRECTNESS_FIELDS, EXPECTED_CAMPAIGN_ID, SELECTED_INCIDENTS, SEMANTIC_FIELDS,
)
from experiments.v2_4.cli import parser as cli_parser
from experiments.v2_4.identity import (
    GENERATION_FIELDS, INCIDENT_FIELDS, ROW_FIELDS, canonical_identity, opaque_id,
    ordered_ids,
)
from experiments.v2_4.escalation import materialize_all_generation_outputs, validate_all_generation_seal
from experiments.v2_4.io import (
    AuditError, assert_quiescent_chroma, raw_copy_tree, tree_manifest, write_new,
)
from experiments.v2_4.isolation import ExternalCallBlocked, ExternalCallGuard
from experiments.v2_4.metrics import (
    cohen_kappa, confusion, count_boundaries, directional_alert,
    exact_binomial_interval, incident_cluster_kappa_bootstrap, primary_status,
    weighted_kappa,
)
from experiments.v2_4.package import _csv_bytes, _deterministic_zip
from experiments.v2_4.package import build_package, preflight, verify_replay
from experiments.v2_4.reconstruct import StoredDocuments, reconstruct, require_python311
from experiments.v2_4.ratings import (
    analyze_closed, close_correctness, close_semantic, lock_reviewer_profile,
    lock_submission, release_semantic,
)
from experiments.v2_4.scanner import (
    assert_safe_archive_members, encoded_variants, scan_archive, scan_records,
)
from experiments.v2_4.selector import _select, load_primary03, validate_selector_schema


TEST_KEY = bytes(range(32))


def correctness_record(case_id="C-" + "1" * 32):
    values = [case_id, "svc", "cause", "symptoms", "metrics", "logs", "recovery",
              "diagnosis", "candidate cause", "[]", "", "", ""]
    return dict(zip(CORRECTNESS_FIELDS, values))


def semantic_record(context_id="S-" + "2" * 32):
    values = [context_id, "alias", "entity", "mechanism", "signature", "procedure",
              "", "", "", "", "", ""]
    return dict(zip(SEMANTIC_FIELDS, values))


def reviewer_profile(reviewer, phase):
    total, correct = (8, 7) if phase == "correctness" else (6, 5)
    return {
        "reviewer": reviewer, "phase": phase, "qualified_at": "2099-01-01T00:00:00+00:00",
        "years_kubernetes_sre": 2, "certification": "NONE", "certification_verified": False,
        "conflict_disclosure": "No V2.3 access",
        "conflict_status": "NONE", "eligibility_approved_by": "audit-coordinator",
        "training_correct": correct, "training_total": total,
        "attestation": "SIGNED_TRUE",
    }


def session_document(phase, item_ids):
    maximum = 18 if phase == "correctness" else 6
    sessions = []
    remaining = len(item_ids)
    while remaining:
        count = min(maximum, remaining)
        sessions.append({
            "session_id": f"session-{len(sessions)+1}", "item_count": count,
            "started_at": "2026-08-31T01:00:00Z", "ended_at": "2026-08-31T02:00:00Z",
            "break_minutes_before": 0 if not sessions else 15, "fatigue_1_5": 2,
        })
        remaining -= count
    return {
        "phase": phase, "sessions": sessions,
        "items": [
            {"item_id": item_id, "started_at": "2026-08-31T01:00:00Z", "ended_at": "2026-08-31T01:01:00Z"}
            for item_id in item_ids
        ],
        "attestation": "SIGNED_TRUE",
    }


class FilesystemTests(unittest.TestCase):
    def test_output_overwrite_refusal(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "one"
            write_new(path, b"first")
            with self.assertRaises(AuditError):
                write_new(path, b"second")

    def test_input_read_only_and_raw_copy(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            (source / "idx").mkdir(parents=True)
            (source / "chroma.sqlite3").write_bytes(b"sqlite")
            (source / "idx" / "header.bin").write_bytes(b"header")
            (source / "idx" / "data_level0.bin").write_bytes(b"data")
            before = tree_manifest(source)["tree_sha256"]
            source_manifest, copy_manifest = raw_copy_tree(source, Path(root) / "copy")
            self.assertEqual(source_manifest["tree_sha256"], copy_manifest["tree_sha256"])
            self.assertEqual(before, tree_manifest(source)["tree_sha256"])

    def test_chroma_quiescence_rejects_wal(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "chroma.sqlite3").write_bytes(b"db")
            (path / "header.bin").write_bytes(b"h")
            (path / "data_level0.bin").write_bytes(b"d")
            (path / "chroma.sqlite3-wal").write_bytes(b"wal")
            with self.assertRaisesRegex(AuditError, "SNAPSHOT_NOT_QUIESCENT"):
                assert_quiescent_chroma(path)

    def test_tree_rejects_symlink_and_hardlink(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root); target = path / "a"; target.write_bytes(b"x")
            os.symlink(target, path / "link")
            with self.assertRaises(AuditError): tree_manifest(path)
            (path / "link").unlink(); os.link(target, path / "hard")
            with self.assertRaisesRegex(AuditError, "hard-linked"): tree_manifest(path)


class SelectorIdentityTests(unittest.TestCase):
    def test_cli_exposes_complete_lifecycle_subcommands(self):
        action = next(action for action in cli_parser()._actions if action.dest == "command")
        self.assertEqual(
            set(action.choices),
            {"preflight", "build", "profile", "lock", "close-correctness", "release-semantic", "close-semantic", "analyze", "replay", "escalation"},
        )

    def test_preregistered_seed_and_incidents(self):
        seed = (
            "v2.4-measurement-audit-v1|v2-3-codex-20260830-primary03|"
            "50eec65390cd5001dfa0091e10e0697554e4b70a09fff6a97c647d7c23586762|"
            "00ea855a9090ca381ebee65d880b96c2fa05f2fab57792e0b071687d4d6cbc5f"
        )
        self.assertEqual(hashlib.sha256(seed.encode()).hexdigest(),
                         "b6d27015ce04ec86b7296e3762b2a38eb98ba5b5e602ca6c357d7533f62fbbe8")
        incidents = {(f"F{i}", t) for i in range(1, 9) for t in range(1, 6)} - {("F7", 5)}
        self.assertEqual(_select(seed, incidents), SELECTED_INCIDENTS)

    def test_outcome_blind_selector_schema(self):
        valid = {"campaign_id", "fault_id", "trial", "schedule_hash", "corpus_version"}
        validate_selector_schema(valid)
        for forbidden in ("representative_score", "output", "condition", "judge_votes"):
            with self.subTest(forbidden=forbidden), self.assertRaises(AuditError):
                validate_selector_schema(valid | {forbidden})

    def test_primary03_only_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(AuditError, "exact campaign"):
                load_primary03(Path(root) / "other-campaign")

    def test_canonical_identity_and_hmac_domains(self):
        row = OrderedDict((("campaign_id", "캠페인"), ("fault_id", "F1"),
                           ("trial", 2), ("condition", "runtime")))
        payload = canonical_identity(row, ROW_FIELDS)
        self.assertEqual(payload, '{"campaign_id":"캠페인","fault_id":"F1","trial":2,"condition":"runtime"}'.encode())
        one = opaque_id(TEST_KEY, "v2.4/case-id", "C-", payload)
        two = opaque_id(TEST_KEY, "v2.4/other-id", "C-", payload)
        self.assertRegex(one, r"^C-[0-9a-f]{32}$"); self.assertNotEqual(one, two)
        with self.assertRaises(AuditError): canonical_identity(dict(reversed(row.items())), ROW_FIELDS)

    def test_generation_identity_and_reviewer_orders(self):
        generation = OrderedDict((("campaign_id", "c"), ("fault_id", "F1"),
            ("trial", 1), ("condition", "runtime"), ("generation_repeat", 3)))
        self.assertIn(b'"generation_repeat":3', canonical_identity(generation, GENERATION_FIELDS))
        values = [f"C-{value:032x}" for value in range(36)]
        r1 = ordered_ids(TEST_KEY, "R1", "correctness", values)
        r2 = ordered_ids(TEST_KEY, "R2", "correctness", values)
        self.assertEqual(set(r1), set(values)); self.assertEqual(set(r2), set(values)); self.assertNotEqual(r1, r2)


class ReconstructionTests(unittest.TestCase):
    def test_reverse_span_reconstruction_and_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            chroma = Path(root) / "chroma"; chroma.mkdir(); (chroma / "idx").mkdir()
            (chroma / "idx" / "header.bin").write_bytes(b"h"); (chroma / "idx" / "data_level0.bin").write_bytes(b"d")
            text = "  alpha SECRET omega  "
            db = sqlite3.connect(chroma / "chroma.sqlite3")
            db.executescript("create table collections(id text primary key,name text); create table segments(id text primary key,type text,collection text); create table embeddings(id integer primary key,segment_id text,embedding_id text); create table embedding_metadata(id integer,key text,string_value text);")
            db.execute("insert into collections values('c','k8s-rca-knowledge')")
            db.execute("insert into segments values('s','urn:chroma:segment/metadata/sqlite','c')")
            db.execute("insert into embeddings values(1,'s','doc')")
            db.execute("insert into embedding_metadata values(1,'chroma:document',?)", (text,)); db.commit(); db.close()
            expected = "alpha [REDACTED] omega"; digest = hashlib.sha256(expected.encode()).hexdigest()
            raw = {"context_condition": "blind_procedural_rag", "additional_context_hash": digest,
                "retrieval_provenance": {"corpus_version": "corpus", "masked_procedure_hash": digest,
                    "candidates": [{"rank": 1, "source_id": "doc", "chunk_start": 0,
                        "chunk_end": len(text), "score": 1.0, "source_text_hash": hashlib.sha256(text.encode()).hexdigest(),
                        "source_length": len(text), "snapshot_locator": f"corpus:doc:0:{len(text)}"}],
                    "removed_spans": [{"category": "label", "term": "SECRET", "start": 8, "end": 14, "rank": 1}]}}
            before_digest = tree_manifest(chroma)["tree_sha256"]
            with StoredDocuments(chroma) as docs:
                actual, evidence = reconstruct(raw, docs)
                with self.assertRaises(sqlite3.OperationalError):
                    docs.connection.execute("create table forbidden_write(value text)")
            self.assertEqual(actual, expected); self.assertEqual(len(evidence), 1)
            self.assertEqual(before_digest, tree_manifest(chroma)["tree_sha256"])
            for mutation in ("orphan", "type", "term"):
                attacked = copy.deepcopy(raw)
                if mutation == "orphan": attacked["retrieval_provenance"]["removed_spans"][0]["rank"] = 2
                elif mutation == "type": attacked["retrieval_provenance"]["removed_spans"][0]["start"] = "8"
                else: attacked["retrieval_provenance"]["removed_spans"][0]["term"] = "DIFFERENT"
                with self.subTest(mutation=mutation), self.assertRaises(AuditError):
                    with StoredDocuments(chroma) as docs: reconstruct(attacked, docs)
            for mutation in ("source_hash", "locator", "additional_hash"):
                attacked = copy.deepcopy(raw)
                if mutation == "source_hash": attacked["retrieval_provenance"]["candidates"][0]["source_text_hash"] = "0" * 64
                elif mutation == "locator": attacked["retrieval_provenance"]["candidates"][0]["snapshot_locator"] = "wrong"
                else: attacked["additional_context_hash"] = "0" * 64
                with self.subTest(mutation=mutation), self.assertRaises(AuditError):
                    with StoredDocuments(chroma) as docs: reconstruct(attacked, docs)

    def test_utf8_and_python_version_contract(self):
        with self.assertRaises(UnicodeDecodeError): b"\xff".decode("utf-8", "strict")
        require_python311((3, 11))
        with self.assertRaises(AuditError): require_python311((3, 10))


class ScannerArchiveMetricIsolationTests(unittest.TestCase):
    def test_phase_specific_scanners(self):
        self.assertEqual(scan_records("correctness", [correctness_record()])["status"], "PASS")
        self.assertEqual(scan_records("semantic", [semantic_record()])["status"], "PASS")
        with self.assertRaises(AuditError): scan_records("correctness", [semantic_record()])
        with self.assertRaises(AuditError): scan_records("semantic", [correctness_record()])

    def test_leak_scanner_canaries(self):
        for variant in encoded_variants("blind_procedural_rag"):
            record = correctness_record(); record["rationale"] = variant
            with self.subTest(variant=variant), self.assertRaises(AuditError): scan_records("correctness", [record])
        record = correctness_record(); record["rationale"] = "source F3-t4"
        with self.assertRaises(AuditError): scan_records("correctness", [record])
        record = correctness_record(); record["rationale"] = "internal F3 marker"
        with self.assertRaisesRegex(AuditError, "fault identifier"):
            scan_records("correctness", [record])
        record = correctness_record(); record["rationale"] = "ｓｏｕｒｃｅ－ｐｒｉｖａｔｅ"
        with self.assertRaises(AuditError):
            scan_records("correctness", [record], known_identifiers=["source-private"])
        allowed_id = correctness_record()["case_id"]
        scan_records("correctness", [correctness_record()], known_identifiers=[allowed_id])
        misplaced = correctness_record(); misplaced["rationale"] = allowed_id
        with self.assertRaisesRegex(AuditError, "sealed identifier"):
            scan_records("correctness", [misplaced], known_identifiers=[allowed_id])

    def test_archive_safety_and_replay(self):
        for name in ("../key.json", ".hidden.csv", "/absolute.csv", "sheet.xlsx"):
            with self.subTest(name=name), self.assertRaises(AuditError): assert_safe_archive_members([name])
        members = {"sheet.csv": b"a,b\n1,2\n", "instructions.md": b"fixed\n"}
        first = _deterministic_zip(members); self.assertEqual(first, _deterministic_zip(members))
        with zipfile.ZipFile(io.BytesIO(first)) as archive: self.assertEqual(archive.namelist(), sorted(members))

    def test_recursive_archive_scanner_rejects_markdown_fullwidth_and_metadata(self):
        rows = [correctness_record()]
        for marker in ("Terra", "Ｔｅｒｒａ"):
            archive = _deterministic_zip({
                "correctness.csv": _csv_bytes(CORRECTNESS_FIELDS, rows),
                "instructions.md": marker.encode("utf-8"),
            })
            with self.subTest(marker=marker), self.assertRaises(AuditError):
                scan_archive("correctness", archive)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name, payload in (("correctness.csv", _csv_bytes(CORRECTNESS_FIELDS, rows)), ("instructions.md", b"clean")):
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); info.extra = b"\x01\x00\x00\x00"; info.external_attr = 0o100400 << 16
                archive.writestr(info, payload)
        with self.assertRaisesRegex(AuditError, "metadata"):
            scan_archive("correctness", stream.getvalue())

    def test_package_row_counts(self):
        c_rows = [correctness_record(f"C-{value:032x}") for value in range(36)]
        s_rows = [semantic_record(f"S-{value:032x}") for value in range(12)]
        self.assertEqual(len(list(csv.DictReader(io.StringIO(_csv_bytes(CORRECTNESS_FIELDS, c_rows).decode())))), 36)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(_csv_bytes(SEMANTIC_FIELDS, s_rows).decode())))), 12)

    def test_all_generation_108_success_fixture(self):
        seal, payloads = [], {}
        for index in range(108):
            generation_id = f"G-{index:032x}"
            payload = f"archived-output-{index}".encode()
            payloads[generation_id] = payload
            seal.append({
                "generation_id": generation_id, "campaign_id": "campaign",
                "fault_id": f"F{index // 15 + 1}", "trial": index % 5 + 1,
                "condition": ("runtime", "length_placebo", "blind_procedural_rag")[index % 3],
                "generation_repeat": index % 3 + 1,
                "output_text_hash": hashlib.sha256(payload).hexdigest(), "representative": index % 3 == 0,
            })
        self.assertEqual(len(materialize_all_generation_outputs(seal, payloads)), 108)

    def test_n36_gate_abstain_and_metrics(self):
        self.assertEqual(count_boundaries(36), (2, 12))
        for count in range(37):
            expected = "GREEN" if count <= 2 else "RED" if count >= 12 else "GRAY"
            self.assertEqual(primary_status(count, 36, 0), expected)
        result = confusion([1, 0, 1], [1, "A", 0])
        self.assertEqual((result["n_non_abstain"], result["primary_status"]), (2, "GRAY_ABSTAIN"))
        self.assertAlmostEqual(cohen_kappa([0, 0, 1, 1], [0, 1, 0, 1]), 0.0)
        self.assertNotEqual(count_boundaries(36, .10), count_boundaries(36, .25))
        self.assertAlmostEqual(weighted_kappa([0, 1, 2, 3], [0, 1, 2, 3]), 1.0)
        lo, hi = exact_binomial_interval(5, 10)
        self.assertLess(lo, .5); self.assertGreater(hi, .5)
        self.assertFalse(directional_alert(5, 5)["alert"])
        interval = incident_cluster_kappa_bootstrap({
            "i1": [(0, 0), (1, 1), (1, 1)], "i2": [(0, 0), (1, 0), (0, 0)],
        }, repeats=200)
        self.assertIsNotNone(interval)

    def test_execution_isolation(self):
        guard = ExternalCallGuard()
        with guard.enforce():
            for action in (
                lambda: socket.socket(), lambda: socket.getaddrinfo("example.com", 443),
                lambda: urllib.request.urlopen("http://169.254.169.254/latest/meta-data/", timeout=.1),
                lambda: __import__("subprocess").Popen(["kubectl", "get", "pods"]),
                lambda: __import__("subprocess").Popen(["codex", "exec", "x"]),
                lambda: __import__("subprocess").Popen(["copilot", "x"]),
                lambda: os.system("kubectl get pods"),
            ):
                with self.assertRaises(ExternalCallBlocked): action()
        manifest = guard.manifest()
        self.assertEqual(manifest["blocked_attempt_count"], 7)
        self.assertEqual(manifest["zero_call_assurance"], "OBSERVED_ONLY")

    def test_execution_isolation_restores_telemetry_environment(self):
        previous = os.environ.get("ANONYMIZED_TELEMETRY")
        try:
            os.environ["ANONYMIZED_TELEMETRY"] = "caller-value"
            with ExternalCallGuard.enforce(ExternalCallGuard()):
                self.assertEqual(os.environ["ANONYMIZED_TELEMETRY"], "FALSE")
            self.assertEqual(os.environ["ANONYMIZED_TELEMETRY"], "caller-value")
        finally:
            if previous is None:
                os.environ.pop("ANONYMIZED_TELEMETRY", None)
            else:
                os.environ["ANONYMIZED_TELEMETRY"] = previous


class RealInputIntegrationTests(unittest.TestCase):
    campaign = Path(
        "/Users/yumunsang/thesis-rca-v2-3-terra/artifacts/v2_3_main/"
        "v2-3-codex-20260830-primary03"
    )
    ground_truth = Path("/Users/yumunsang/thesis-rca-v2-4-audit/results/ground_truth.csv")
    chroma = Path("/Users/yumunsang/thesis-rca/data/chromadb")

    def setUp(self):
        if not all(path.exists() for path in (self.campaign, self.ground_truth, self.chroma)):
            self.skipTest("authoritative local Primary03 snapshot is unavailable")

    def test_primary03_dry_run_exact_counts(self):
        report = preflight(self.campaign, self.ground_truth, self.chroma)
        self.assertEqual(report["status"], "DRY_RUN_PASS")
        self.assertEqual((report["csv_rows"], report["raw_files"], report["incidents"]), (117, 117, 39))
        self.assertEqual((len(report["selected_incidents"]), report["selected_outputs"]), (12, 36))

    def test_real_package_reconstruction_seal_and_no_human_state(self):
        with tempfile.TemporaryDirectory() as root:
            audit = build_package(
                self.campaign, self.ground_truth, self.chroma, Path(root), "real-fixture", TEST_KEY
            )
            answer = __import__("json").loads((audit / "sealed" / "answer_key.json").read_text())
            status = __import__("json").loads((audit / "manifests" / "status.json").read_text())
            evidence = __import__("json").loads((audit / "sealed" / "reconstruction_evidence.json").read_text())
            commitment = __import__("json").loads((audit / "manifests" / "package_commitment.json").read_text())
            self.assertEqual(len(answer["mapping"]), 36)
            self.assertEqual(len(answer["all_generation_seal"]), 108)
            validate_all_generation_seal(answer["all_generation_seal"])
            self.assertEqual(len({item["generation_id"] for item in answer["all_generation_seal"]}), 108)
            self.assertEqual(len(evidence["items"]), 12)
            self.assertEqual(status["human_ratings"], 0)
            self.assertEqual(status["analysis_status"], "PACKAGE_ONLY")
            self.assertFalse((audit / "analysis").exists())
            self.assertFalse(any("answer" in path.name for path in (audit / "distribution").rglob("*")))
            self.assertEqual(len(list((audit / "distribution").rglob("*correctness.zip"))), 2)
            self.assertEqual(len(list((audit / "sealed" / "pending_semantic").glob("*.zip"))), 2)
            for name, digest in commitment["archives"].items():
                phase = "correctness" if name.endswith("correctness") else "semantic"
                reviewer = name.split("_")[0]
                path = (
                    audit / "distribution" / "correctness" / reviewer.lower() / f"{reviewer}_correctness.zip"
                    if phase == "correctness" else
                    audit / "sealed" / "pending_semantic" / f"{reviewer}_semantic.zip"
                )
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            with self.assertRaisesRegex(AuditError, "BLOCKED_GENERATION_CONTENT_NOT_ARCHIVED"):
                materialize_all_generation_outputs(answer["all_generation_seal"], {})

    def test_build_late_failure_exposes_no_final_or_distribution(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            with patch("experiments.v2_4.package.scan_archive", side_effect=AuditError("injected late failure")):
                with self.assertRaisesRegex(AuditError, "injected late"):
                    build_package(self.campaign, self.ground_truth, self.chroma, root_path, "atomic", TEST_KEY)
            self.assertFalse((root_path / "atomic").exists())
            self.assertEqual(list(root_path.glob(".atomic.staging-*")), [])

    def test_same_audit_sealed_key_replay_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as root:
            audit = build_package(self.campaign, self.ground_truth, self.chroma, Path(root), "same-audit", TEST_KEY)
            self.assertEqual(
                verify_replay(audit, self.campaign, self.ground_truth, self.chroma)["status"], "PASS"
            )

    def test_same_audit_replay_rejects_nonselected_input_drift(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            copied = root_path / EXPECTED_CAMPAIGN_ID
            shutil.copytree(self.campaign, copied)
            audit = build_package(copied, self.ground_truth, self.chroma, root_path / "outputs", "drift", TEST_KEY)
            with (copied / "campaign_events.jsonl").open("ab") as handle:
                handle.write(b"\n")
            with self.assertRaisesRegex(AuditError, "input/source manifest drift"):
                verify_replay(audit, copied, self.ground_truth, self.chroma)

    def test_foreign_campaign_and_row_raw_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            copied = Path(root) / EXPECTED_CAMPAIGN_ID
            shutil.copytree(self.campaign, copied)
            raw_path = copied / "raw_v2_3" / f"{EXPECTED_CAMPAIGN_ID}_F1_t2_runtime.json"
            original = raw_path.read_bytes(); document = __import__("json").loads(original)
            document["campaign_id"] = "foreign-campaign"
            raw_path.write_text(__import__("json").dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(AuditError, "invalid/duplicate raw identity"):
                preflight(copied, self.ground_truth, self.chroma)
            raw_path.write_bytes(original); document = __import__("json").loads(original)
            document["representative_output"]["root_cause"] += " changed"
            raw_path.write_text(__import__("json").dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(AuditError, "representative output mismatch"):
                preflight(copied, self.ground_truth, self.chroma)

    def test_sheet_lock_and_correctness_before_semantic_gate(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            audit = build_package(self.campaign, self.ground_truth, self.chroma, root_path, "phases", TEST_KEY)
            premature_profile = root_path / "premature-semantic-profile.json"
            premature_profile.write_text(__import__("json").dumps(reviewer_profile("R1", "semantic")))
            with self.assertRaisesRegex(AuditError, "correctness CLOSED"):
                lock_reviewer_profile(audit, "R1", "semantic", premature_profile)
            with self.assertRaisesRegex(AuditError, "before correctness"):
                lock_submission(audit, "R1", "semantic", root_path / "missing.csv", root_path / "missing.json")
            disagreement_case = None
            for reviewer in ("R1", "R2"):
                profile_path = root_path / f"{reviewer}-profile.json"
                valid_profile = reviewer_profile(reviewer, "correctness")
                if reviewer == "R1":
                    valid_profile.update({"years_kubernetes_sre": 1, "certification": "CKA", "certification_verified": True})
                profile_path.write_text(__import__("json").dumps(valid_profile))
                if reviewer == "R1":
                    underqualified = reviewer_profile(reviewer, "correctness")
                    underqualified.update({"years_kubernetes_sre": 1, "certification": "NONE", "certification_verified": False})
                    underqualified_path = root_path / "underqualified.json"
                    underqualified_path.write_text(__import__("json").dumps(underqualified))
                    with self.assertRaisesRegex(AuditError, "qualification"):
                        lock_reviewer_profile(audit, reviewer, "correctness", underqualified_path)
                    malformed_time = reviewer_profile(reviewer, "correctness")
                    malformed_time["qualified_at"] = "2099-01-01 00:00:00"
                    malformed_time_path = root_path / "malformed-time.json"
                    malformed_time_path.write_text(__import__("json").dumps(malformed_time))
                    with self.assertRaisesRegex(AuditError, "timestamp"):
                        lock_reviewer_profile(audit, reviewer, "correctness", malformed_time_path)
                lock_reviewer_profile(audit, reviewer, "correctness", profile_path)
                archive_path = audit / "distribution" / "correctness" / reviewer.lower() / f"{reviewer}_correctness.zip"
                with zipfile.ZipFile(archive_path) as archive:
                    records = list(csv.DictReader(io.StringIO(archive.read("correctness.csv").decode())))
                for record in records:
                    record["correctness_0_1_2_A"] = "1"
                if reviewer == "R1":
                    disagreement_case = records[0]["case_id"]
                else:
                    next(item for item in records if item["case_id"] == disagreement_case)["correctness_0_1_2_A"] = "2"
                source = root_path / f"{reviewer}.csv"
                source.write_bytes(_csv_bytes(CORRECTNESS_FIELDS, records))
                metadata = root_path / f"{reviewer}-correctness-session.json"
                record_ids = [record["case_id"] for record in records]
                metadata.write_text(__import__("json").dumps(session_document("correctness", record_ids)))
                if reviewer == "R1":
                    with self.assertRaisesRegex(AuditError, "qualification"):
                        (audit / "ratings" / "reviewer_profiles" / "R1_correctness.json").unlink()
                        lock_submission(audit, reviewer, "correctness", source, metadata)
                    lock_reviewer_profile(audit, reviewer, "correctness", profile_path)
                    mutated = [dict(item) for item in records]; mutated[0]["expected_root_cause"] += " tampered"
                    bad = root_path / "mutated.csv"; bad.write_bytes(_csv_bytes(CORRECTNESS_FIELDS, mutated))
                    with self.assertRaisesRegex(AuditError, "frozen"):
                        lock_submission(audit, reviewer, "correctness", bad, metadata)
                    reordered = root_path / "reordered.csv"; reordered.write_bytes(_csv_bytes(CORRECTNESS_FIELDS, list(reversed(records))))
                    with self.assertRaisesRegex(AuditError, "order"):
                        lock_submission(audit, reviewer, "correctness", reordered, metadata)
                    invalid_sessions = session_document("correctness", record_ids)
                    invalid_sessions["sessions"][1]["break_minutes_before"] = 0
                    invalid_metadata = root_path / "invalid-session.json"
                    invalid_metadata.write_text(__import__("json").dumps(invalid_sessions))
                    with self.assertRaisesRegex(AuditError, "fatigue"):
                        lock_submission(audit, reviewer, "correctness", source, invalid_metadata)
                    invalid_items = session_document("correctness", record_ids)
                    invalid_items["items"][0]["started_at"] = "2026-08-31 01:00:00"
                    invalid_items_path = root_path / "invalid-item-time.json"
                    invalid_items_path.write_text(__import__("json").dumps(invalid_items))
                    with self.assertRaisesRegex(AuditError, "timestamp"):
                        lock_submission(audit, reviewer, "correctness", source, invalid_items_path)
                lock_submission(audit, reviewer, "correctness", source, metadata)
                with self.assertRaises(AuditError):
                    lock_submission(audit, reviewer, "correctness", source, metadata)
            adjudication = root_path / "adjudication.csv"
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=["case_id", "adjudicated_correctness", "rationale"], lineterminator="\n")
            writer.writeheader()
            writer.writerow({"case_id": disagreement_case, "adjudicated_correctness": "1", "rationale": "fixture"})
            adjudication.write_text(stream.getvalue(), encoding="utf-8")
            answer = __import__("json").loads((audit / "sealed" / "answer_key.json").read_text())
            unanimous = next(item["case_id"] for item in answer["mapping"] if item["case_id"] != disagreement_case)
            bad_adjudication = root_path / "bad-adjudication.csv"
            bad_adjudication.write_text(stream.getvalue() + f"{unanimous},1,forbidden unanimous row\n", encoding="utf-8")
            with self.assertRaisesRegex(AuditError, "disagreement IDs only"):
                close_correctness(audit, bad_adjudication)
            from experiments.v2_4 import ratings as ratings_module
            original_write = ratings_module.write_new
            def fail_closed(path, data, mode=0o600):
                if path.name == "phase_correctness_closed.json":
                    raise AuditError("injected close failure")
                return original_write(path, data, mode)
            with patch("experiments.v2_4.ratings.write_new", side_effect=fail_closed):
                with self.assertRaisesRegex(AuditError, "injected close"):
                    close_correctness(audit, adjudication)
            self.assertFalse((audit / "distribution" / "semantic").exists())
            self.assertFalse((audit / "ratings" / "adjudication" / "correctness_closed").exists())
            close_correctness(audit, adjudication)
            self.assertTrue((audit / "manifests" / "phase_correctness_closed.json").is_file())
            self.assertFalse((audit / "distribution" / "semantic").exists())
            self.assertEqual(len(list((audit / "distribution").rglob("*semantic.zip"))), 0)
            with self.assertRaisesRegex(AuditError, "both locked semantic"):
                release_semantic(audit)
            with self.assertRaisesRegex(AuditError, "both review phases"):
                analyze_closed(audit)
            with self.assertRaisesRegex(AuditError, "semantic originals"):
                close_semantic(audit, root_path / "missing-semantic.csv")
            for reviewer in ("R1", "R2"):
                semantic_profile = root_path / f"{reviewer}-semantic-profile.json"
                semantic_profile_document = reviewer_profile(reviewer, "semantic")
                if reviewer == "R1":
                    stale = dict(semantic_profile_document); stale["qualified_at"] = "2000-01-01T00:00:00+00:00"
                    stale_path = root_path / "stale-semantic-profile.json"
                    stale_path.write_text(__import__("json").dumps(stale))
                    with self.assertRaisesRegex(AuditError, "precedes correctness"):
                        lock_reviewer_profile(audit, reviewer, "semantic", stale_path)
                semantic_profile.write_text(__import__("json").dumps(semantic_profile_document))
                lock_reviewer_profile(audit, reviewer, "semantic", semantic_profile)
                if reviewer == "R1":
                    self.assertFalse((audit / "distribution" / "semantic").exists())
                    with self.assertRaisesRegex(AuditError, "both locked semantic"):
                        release_semantic(audit)
                    with self.assertRaisesRegex(AuditError, "must be released"):
                        lock_submission(
                            audit, reviewer, "semantic",
                            root_path / "not-yet-released.csv", root_path / "not-yet-released.json",
                        )
            original_write = ratings_module.write_new
            def fail_semantic_release(path, data, mode=0o600):
                if path.name == "phase_semantic_released.json":
                    raise AuditError("injected semantic release failure")
                return original_write(path, data, mode)
            with patch("experiments.v2_4.ratings.write_new", side_effect=fail_semantic_release):
                with self.assertRaisesRegex(AuditError, "injected semantic release"):
                    release_semantic(audit)
            self.assertFalse((audit / "distribution" / "semantic").exists())
            self.assertFalse((audit / "manifests" / "phase_semantic_released.json").exists())
            release_semantic(audit)
            self.assertEqual(len(list((audit / "distribution").rglob("*semantic.zip"))), 2)
            for reviewer in ("R1", "R2"):
                archive_path = audit / "distribution" / "semantic" / reviewer.lower() / f"{reviewer}_semantic.zip"
                with zipfile.ZipFile(archive_path) as archive:
                    records = list(csv.DictReader(io.StringIO(archive.read("semantic.csv").decode())))
                for record in records:
                    record.update({
                        "severity_L0_L1_L2_L3": "L0", "label_exposed": "false",
                        "entity_exposed": "false", "injection_specific": "false",
                        "generic_procedure": "true", "rationale": "fixture",
                    })
                source = root_path / f"{reviewer}-semantic.csv"
                source.write_bytes(_csv_bytes(SEMANTIC_FIELDS, records))
                metadata = root_path / f"{reviewer}-semantic-session.json"
                metadata.write_text(__import__("json").dumps(session_document(
                    "semantic", [record["context_id"] for record in records]
                )))
                lock_submission(audit, reviewer, "semantic", source, metadata)
            semantic_adjudication = root_path / "semantic-adjudication.csv"
            semantic_adjudication.write_text(
                "context_id,adjudicated_severity,label_exposed,entity_exposed,injection_specific,generic_procedure,rationale\n",
                encoding="utf-8",
            )
            original_write = ratings_module.write_new
            def fail_semantic_closed(path, data, mode=0o600):
                if path.name == "phase_semantic_closed.json":
                    raise AuditError("injected semantic close failure")
                return original_write(path, data, mode)
            with patch("experiments.v2_4.ratings.write_new", side_effect=fail_semantic_closed):
                with self.assertRaisesRegex(AuditError, "injected semantic"):
                    close_semantic(audit, semantic_adjudication)
            self.assertFalse((audit / "ratings" / "adjudication" / "semantic_closed").exists())
            self.assertFalse((audit / "manifests" / "phase_semantic_closed.json").exists())
            close_semantic(audit, semantic_adjudication)
            analysis = analyze_closed(audit)
            self.assertIn("correctness_score_distributions", analysis)
            self.assertIn("reviewer_correctness_weighted_kappa", analysis)
            self.assertEqual(analysis["semantic"]["severity_counts"]["L0"], 12)
            self.assertIsNone(analysis["semantic"]["weighted_kappa_descriptive"])
            self.assertEqual(analysis["semantic"]["semantic_eligibility_status"], "PASS")
            locked_original = audit / "ratings" / "original_locked" / "R1_correctness.csv"
            os.chmod(locked_original, 0o600); locked_original.write_bytes(locked_original.read_bytes() + b"tamper")
            with self.assertRaisesRegex(AuditError, "locked original hash"):
                analyze_closed(audit)


if __name__ == "__main__":
    unittest.main()
