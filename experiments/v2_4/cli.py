"""Explicit, lifecycle-safe command line interface for the V2.4 audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io import AuditError
from .escalation import materialize_all_generation_outputs
from .package import build_package, preflight, verify_replay
from .ratings import (
    analyze_closed, close_correctness, close_semantic, lock_reviewer_profile,
    lock_submission, release_semantic,
)


def _inputs(command: argparse.ArgumentParser) -> None:
    command.add_argument("--campaign-dir", type=Path, required=True)
    command.add_argument("--ground-truth", type=Path, required=True)
    command.add_argument("--chroma", type=Path, required=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="python -m experiments.v2_4",
        description="Zero-call Primary03 V2.4 audit lifecycle.",
    )
    commands = result.add_subparsers(dest="command", required=True)
    preflight_command = commands.add_parser("preflight", help="Read-only input validation")
    _inputs(preflight_command)
    build = commands.add_parser("build", help="Atomically build a package-only audit")
    _inputs(build); build.add_argument("--output-root", type=Path, required=True); build.add_argument("--audit-id", required=True)
    profile = commands.add_parser("profile", help="Lock reviewer qualification profile")
    profile.add_argument("--audit-root", type=Path, required=True); profile.add_argument("--reviewer", choices=("R1", "R2"), required=True); profile.add_argument("--phase", choices=("correctness", "semantic"), required=True); profile.add_argument("--source", type=Path, required=True)
    lock = commands.add_parser("lock", help="Lock a reviewer sheet and session metadata")
    lock.add_argument("--audit-root", type=Path, required=True); lock.add_argument("--reviewer", choices=("R1", "R2"), required=True); lock.add_argument("--phase", choices=("correctness", "semantic"), required=True); lock.add_argument("--sheet", type=Path, required=True); lock.add_argument("--session-metadata", type=Path, required=True)
    close_c = commands.add_parser("close-correctness", help="Atomically close correctness review")
    close_c.add_argument("--audit-root", type=Path, required=True); close_c.add_argument("--adjudication", type=Path, required=True)
    release_s = commands.add_parser("release-semantic", help="Release semantic packages after both profiles lock")
    release_s.add_argument("--audit-root", type=Path, required=True)
    close_s = commands.add_parser("close-semantic", help="Close semantic review")
    close_s.add_argument("--audit-root", type=Path, required=True); close_s.add_argument("--adjudication", type=Path, required=True)
    analyze = commands.add_parser("analyze", help="Verify locks and analyze both phases")
    analyze.add_argument("--audit-root", type=Path, required=True)
    replay = commands.add_parser("replay", help="Same-audit sealed-key replay")
    replay.add_argument("--audit-root", type=Path, required=True); _inputs(replay)
    escalation = commands.add_parser("escalation", help="Validate all 108 archived payloads")
    escalation.add_argument("--audit-root", type=Path, required=True); escalation.add_argument("--outputs-dir", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "preflight":
            report = preflight(args.campaign_dir, args.ground_truth, args.chroma)
        elif args.command == "build":
            output = build_package(args.campaign_dir, args.ground_truth, args.chroma, args.output_root, args.audit_id)
            report = {"status": "PACKAGE_ONLY_COMPLETE", "audit_root": str(output), "zero_call_assurance": "OBSERVED_ONLY"}
        elif args.command == "profile":
            report = {"status": "LOCKED", "path": str(lock_reviewer_profile(args.audit_root, args.reviewer, args.phase, args.source))}
        elif args.command == "lock":
            report = {"status": "LOCKED", "path": str(lock_submission(args.audit_root, args.reviewer, args.phase, args.sheet, args.session_metadata))}
        elif args.command == "close-correctness":
            close_correctness(args.audit_root, args.adjudication); report = {"status": "CORRECTNESS_CLOSED"}
        elif args.command == "release-semantic":
            release_semantic(args.audit_root); report = {"status": "SEMANTIC_RELEASED"}
        elif args.command == "close-semantic":
            close_semantic(args.audit_root, args.adjudication); report = {"status": "SEMANTIC_CLOSED"}
        elif args.command == "analyze":
            report = analyze_closed(args.audit_root)
        elif args.command == "replay":
            report = verify_replay(args.audit_root, args.campaign_dir, args.ground_truth, args.chroma)
        else:
            answer = json.loads((args.audit_root / "sealed" / "answer_key.json").read_text("utf-8"))
            payloads = {path.stem: path.read_bytes() for path in args.outputs_dir.glob("*.bin")}
            report = {"status": "PASS", "outputs": len(materialize_all_generation_outputs(answer["all_generation_seal"], payloads))}
    except (AuditError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0
