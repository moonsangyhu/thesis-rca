"""One-incident V2.3 pilot orchestration with mandatory recovery."""

from __future__ import annotations

import json
import hashlib
import math
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable
from datetime import datetime, timezone

from .authorization import LiveAuthorization
from .conditions import ConditionAssembler, latin_square_schedule, schedule_hash
from .config import PILOT_FAULT_ID, PILOT_TRIAL
from .engine import RCAEngineV2_3
from .ledger import CallLedgerEntry
from .retrieval import BlindProcedure, BlindProcedureBuilder, RetrievalChunk
from .scanner import ForbiddenLexicon, sha256_text
from .storage import SafeOutputStore


class PilotError(RuntimeError):
    pass


class RecoveryFailure(PilotError):
    pass


class F7InjectionValidator:
    """Bind the injector receipt to the live deployment resource state."""

    def __init__(
        self,
        deployment_loader: Callable[[str], dict],
        pod_loader: Callable[[], dict],
    ):
        self.deployment_loader = deployment_loader
        self.pod_loader = pod_loader

    def validate(
        self, fault_id: str, trial: int, ground_truth: dict, injection_result: dict
    ) -> dict:
        target = str(ground_truth.get("target_service") or "").strip()
        expected_identity = {
            "fault_id": fault_id,
            "trial": trial,
            "target_service": target,
            "action": "patch_cpu_limit",
        }
        for key, expected in expected_identity.items():
            actual = injection_result.get(key)
            if key == "trial":
                try:
                    actual = int(actual)
                except (TypeError, ValueError):
                    pass
            if actual != expected:
                raise PilotError(f"post-injection {key} identity mismatch")
        requested = str(injection_result.get("cpu_limit") or "").strip()
        if not requested:
            raise PilotError("post-injection CPU limit is missing")
        deployment = self.deployment_loader(target)
        containers = (
            deployment.get("spec", {}).get("template", {}).get("spec", {})
            .get("containers", [])
        ) if isinstance(deployment, dict) else []
        matched_container_names: set[str] = set()
        for container in containers:
            resources = container.get("resources", {})
            limit = resources.get("limits", {}).get("cpu")
            request = resources.get("requests", {}).get("cpu")
            name = container.get("name")
            if isinstance(name, str) and name and limit == requested and request == requested:
                matched_container_names.add(name)
        if not matched_container_names:
            raise PilotError("post-injection live CPU state does not match injector receipt")
        pod_list = self.pod_loader()
        items = pod_list.get("items", []) if isinstance(pod_list, dict) else []
        matching_pods = []
        for pod in items:
            labels = pod.get("metadata", {}).get("labels", {})
            if target not in {labels.get("app"), labels.get("app.kubernetes.io/name")}:
                continue
            containers = pod.get("spec", {}).get("containers", [])
            resource_match = any(
                container.get("name") in matched_container_names
                and container.get("resources", {}).get("limits", {}).get("cpu") == requested
                and container.get("resources", {}).get("requests", {}).get("cpu") == requested
                for container in containers
            )
            statuses = pod.get("status", {}).get("containerStatuses", [])
            ready = pod.get("status", {}).get("phase") == "Running" and any(
                status.get("name") in matched_container_names
                and status.get("ready") is True
                for status in statuses
            )
            if resource_match and ready:
                matching_pods.append(pod)
        if not matching_pods:
            raise PilotError("post-injection live target pod is not Ready with requested CPU")
        return {
            "status": "verified", "target_service": target,
            "cpu_limit": requested, "ready_pods": len(matching_pods),
        }


@dataclass(frozen=True)
class RetrievedProcedure:
    procedure: BlindProcedure
    lexicon: ForbiddenLexicon
    query: str


class RuntimeEvidenceRenderer:
    """Freeze observability-only signals without fault/trial identifiers."""

    ALLOWED_KEYS = frozenset({"metrics", "logs", "kubectl"})

    def render(self, signals: dict) -> str:
        if not isinstance(signals, dict) or not signals:
            raise PilotError("runtime signal collection is empty")
        unexpected = set(signals) - self.ALLOWED_KEYS
        if unexpected:
            raise PilotError(f"non-runtime signal source detected: {sorted(unexpected)}")
        if not self.ALLOWED_KEYS.issubset(signals):
            raise PilotError("metrics, logs, and kubectl evidence are all required")
        if any(not signals[key] for key in self.ALLOWED_KEYS):
            raise PilotError("runtime signal source is empty")
        return "## Frozen Runtime Evidence\n" + json.dumps(
            signals, sort_keys=True, ensure_ascii=False, default=str,
            separators=(",", ":"),
        )


class RuntimeOnlyRetriever:
    """Adapter that never passes fault ID or ground truth into retrieval."""

    def __init__(
        self,
        backend,
        *,
        corpus_version: str,
        top_k: int = 5,
        query_char_limit: int = 4000,
    ):
        if not corpus_version.strip() or top_k < 1 or query_char_limit < 200:
            raise ValueError("invalid runtime retriever configuration")
        self.backend = backend
        self.corpus_version = corpus_version
        self.top_k = top_k
        self.query_char_limit = query_char_limit

    def retrieve(
        self, runtime_context: str, base_lexicon: ForbiddenLexicon
    ) -> RetrievedProcedure:
        raw_query = runtime_context[-self.query_char_limit:]
        builder = BlindProcedureBuilder()
        query, _ = builder.sanitize_runtime_query(
            runtime_context, raw_query, base_lexicon
        )
        docs = self.backend.query(
            query_text=query,
            fault_type=None,
            top_k=self.top_k,
            categories=["debugging", "runbooks", "known-issues"],
        )
        if not docs:
            raise PilotError("runtime-only retrieval returned no documents")
        metadata = tuple(
            value
            for doc in docs
            for value in (
                getattr(doc, "source", ""), getattr(doc, "filename", ""),
                getattr(doc, "title", ""), getattr(doc, "id", ""),
            )
            if value
        )
        lexicon = replace(
            base_lexicon,
            metadata=tuple(dict.fromkeys(base_lexicon.metadata + metadata)),
        )
        chunks = tuple(
            RetrievalChunk(
                source_id=str(doc.id),
                text=str(doc.content),
                score=float(doc.score),
                start=0,
                end=len(str(doc.content)),
            )
            for doc in docs
        )
        procedure = builder.build(
            runtime_context=runtime_context,
            runtime_query=query,
            runtime_query_source=raw_query,
            chunks=chunks,
            corpus_version=self.corpus_version,
            lexicon=lexicon,
        )
        return RetrievedProcedure(procedure=procedure, lexicon=lexicon, query=query)


def _split_values(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").replace(",", ";").split(";")
                 if part.strip())


def build_forbidden_lexicon(
    fault_id: str, trial: int, ground_truth: dict, injection_result: dict
) -> ForbiddenLexicon:
    if ground_truth.get("fault_id") != fault_id:
        raise PilotError("ground truth identity mismatch")
    try:
        ground_truth_trial = int(ground_truth.get("trial"))
    except (TypeError, ValueError) as exc:
        raise PilotError("ground truth trial is invalid") from exc
    if ground_truth_trial != trial:
        raise PilotError("ground truth trial mismatch")
    target = str(ground_truth.get("target_service") or "").strip()
    if not target:
        raise PilotError("ground truth target is missing")
    field_values = tuple(
        str(value) for key, value in sorted(injection_result.items())
        if key not in {
            "kubectl_output", "wait_seconds", "fault_id", "trial",
            "target_service", "action",
        }
        and isinstance(value, (str, int, float))
        and str(value).strip()
        and not str(value).strip().isdigit()
    )
    return ForbiddenLexicon(
        canonical_labels=tuple(dict.fromkeys(filter(None, (
            str(ground_truth.get("fault_name") or "").strip(),
            str(ground_truth.get("expected_root_cause") or "").strip(),
        )))),
        aliases=tuple(dict.fromkeys(
            _split_values(ground_truth.get("expected_log_patterns", ""))
        )),
        entities=tuple(dict.fromkeys(
            (target,) + _split_values(ground_truth.get("affected_components", ""))
        )),
        commands=tuple(dict.fromkeys(filter(None, (
            str(ground_truth.get("injection_method") or "").strip(),
            str(injection_result.get("action") or "").strip(),
        )))),
        field_values=tuple(dict.fromkeys(field_values)),
        harness_markers=(fault_id, "fault injection", "experiment marker"),
    )


def sealed_judge_reference(ground_truth: dict) -> str:
    allowed = (
        "fault_name", "expected_root_cause", "primary_symptoms",
        "expected_metrics", "expected_log_patterns", "expected_recovery_action",
    )
    reference = {key: ground_truth.get(key, "") for key in allowed}
    if not reference["fault_name"] or not reference["expected_root_cause"]:
        raise PilotError("sealed judge reference is incomplete")
    return json.dumps(reference, sort_keys=True, ensure_ascii=False)


class AttemptJournal:
    """Append each validated call before the incident commit."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise PilotError("attempt journal overwrite refused")
        self._sessions: set[str] = set()

    def append(self, entry: CallLedgerEntry) -> None:
        if entry.session_id in self._sessions:
            raise PilotError("duplicate attempt-journal session")
        with self.path.open("a") as handle:
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._sessions.add(entry.session_id)


class ChargedCallJournal:
    """Durably record every completed/timed-out CLI attempt before parsing."""

    REQUIRED = frozenset({
        "attempt_id", "requested_model", "actual_model", "session_id",
        "output_tokens", "ai_credits", "premium_requests",
        "usage_metadata_complete", "started_at", "ended_at", "latency_ms",
        "exit_code", "timed_out", "cli_executable", "temporary_cwd_id",
        "stdout_hash", "stderr_hash",
    })

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise PilotError("charged-call journal overwrite refused")
        self._attempts: set[str] = set()

    def append(self, receipt: dict) -> None:
        if not isinstance(receipt, dict) or set(receipt) != self.REQUIRED:
            raise PilotError("charged-call receipt schema mismatch")
        attempt_id = receipt.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id or attempt_id in self._attempts:
            raise PilotError("charged-call attempt identity is invalid")
        for field in ("stdout_hash", "stderr_hash"):
            value = receipt.get(field)
            if not isinstance(value, str) or len(value) != 64:
                raise PilotError("charged-call content hash is invalid")
        if receipt.get("ai_credits") is not None:
            value = receipt["ai_credits"]
            if (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0
            ):
                raise PilotError("charged-call AIC value is invalid")
        with self.path.open("a") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._attempts.add(attempt_id)


class PilotOutputStore(SafeOutputStore):
    def __init__(self, output_dir: Path):
        output_dir = Path(output_dir)
        project_root = Path(__file__).resolve().parents[2]
        allowed_root = (project_root / "artifacts" / "v2_3_pilot").resolve()
        resolved = output_dir.resolve()
        if allowed_root not in resolved.parents or resolved == allowed_root:
            raise PilotError("pilot output must be a campaign directory under artifacts/v2_3_pilot")
        if resolved.exists():
            raise PilotError("pilot output directory already exists")
        super().__init__(resolved)
        self.csv_path = self.output_dir / "pilot_results.csv"
        self.raw_dir = self.output_dir / "raw"
        self.ledger_path = self.output_dir / "pilot_call_ledger.jsonl"
        self._keys = self._load_keys()

    def write_manifest(self, manifest: dict) -> None:
        path = self.output_dir / "campaign_manifest.json"
        if path.exists():
            raise PilotError("campaign manifest overwrite refused")
        with path.open("x") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())

    def append_event(self, event: str, **details) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **details,
        }
        path = self.output_dir / "campaign_events.jsonl"
        with path.open("a") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def snapshot_tree(paths: tuple[Path, ...]) -> str:
    """Hash frozen corpus/index files by relative locator and bytes."""
    digest = hashlib.sha256()
    files: list[tuple[str, Path]] = []
    for root in paths:
        resolved = Path(root).resolve()
        if not resolved.exists():
            raise PilotError(f"corpus snapshot path missing: {resolved}")
        if resolved.is_file():
            files.append((resolved.name, resolved))
        else:
            for path in resolved.rglob("*"):
                if path.is_file():
                    files.append((f"{resolved.name}/{path.relative_to(resolved)}", path))
    if not files:
        raise PilotError("corpus snapshot contains no files")
    for locator, path in sorted(files):
        digest.update(locator.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass
class PilotIncidentRunner:
    authorization: LiveAuthorization
    engine: RCAEngineV2_3
    injector: object
    recovery: object
    collector: object
    validator: object
    injection_validator: object
    retriever: RuntimeOnlyRetriever
    store: PilotOutputStore
    renderer: RuntimeEvidenceRenderer = RuntimeEvidenceRenderer()
    sleep_fn: Callable[[float], None] = __import__("time").sleep

    def __post_init__(self) -> None:
        self.authorization.revalidate()
        caller_auth = getattr(self.engine.caller, "authorization", None)
        if caller_auth != self.authorization:
            raise PilotError("runner and Terra caller authorization differ")

    def run(self, fault_id: str, trial: int, ground_truth: dict) -> dict:
        self.authorization.revalidate()
        if (fault_id, trial) != (PILOT_FAULT_ID, PILOT_TRIAL):
            raise PilotError(
                f"V2.3 live pilot is frozen to {PILOT_FAULT_ID} trial {PILOT_TRIAL}"
            )
        validation = self.validator.validate_and_correct(fault_id=fault_id, trial=trial)
        if getattr(validation, "status", None) not in {"clean", "corrected"}:
            raise PilotError("pre-injection cluster state is not GREEN")

        injection_result: dict = {}
        injection_attempted = False
        primary_error: BaseException | None = None
        pending: tuple[list[dict], list[dict], list[dict]] | None = None
        try:
            prepare_recovery = getattr(self.injector, "prepare_recovery_context", None)
            if not callable(prepare_recovery):
                raise PilotError("injector lacks pre-mutation recovery receipt support")
            prepared_recovery = prepare_recovery(fault_id, trial)
            if not isinstance(prepared_recovery, dict) or not prepared_recovery:
                raise PilotError("pre-mutation recovery receipt is empty")
            injection_result = dict(prepared_recovery)
            if hasattr(self.store, "append_event"):
                self.store.append_event(
                    "recovery_receipt_sealed", recovery_context=injection_result
                )
            injection_attempted = True
            if hasattr(self.store, "append_event"):
                self.store.append_event("injection_started", fault_id=fault_id, trial=trial)
            injection_result = self.injector.inject(
                fault_id, trial, recovery_context=prepared_recovery
            )
            wait_seconds = int(injection_result.get("wait_seconds", 0))
            if not 0 <= wait_seconds <= 600:
                raise PilotError("invalid injection wait interval")
            self.sleep_fn(wait_seconds)
            injection_validation = self.injection_validator.validate(
                fault_id, trial, ground_truth, injection_result
            )
            if injection_validation.get("status") != "verified":
                raise PilotError("post-injection validator did not PASS")
            if hasattr(self.store, "append_event"):
                self.store.append_event("injection_verified", **injection_validation)
            collected = self.collector.collect_observability_only(window_minutes=5)
            signals = json.loads(json.dumps(collected, ensure_ascii=False, default=str))
            runtime_context = self.renderer.render(signals)
            base_lexicon = build_forbidden_lexicon(
                fault_id, trial, ground_truth, injection_result
            )
            retrieved = self.retriever.retrieve(runtime_context, base_lexicon)
            contexts = ConditionAssembler().assemble_all(
                runtime_context, retrieved.procedure, retrieved.lexicon
            )
            order = latin_square_schedule()[(fault_id, trial)]
            ledger_start = len(self.engine.ledger.entries)
            rows: list[dict] = []
            raws: list[dict] = []
            reference = sealed_judge_reference(ground_truth)
            for condition in order:
                row = self.engine.analyze_condition(
                    contexts[condition], fault_id, trial, judge_reference=reference
                )
                rows.append(row)
                raws.append({
                    **row,
                    "schedule_order": order,
                    "schedule_hash": schedule_hash(latin_square_schedule()),
                    "runtime_context": runtime_context,
                    "runtime_signals": signals,
                    "retrieval_query_hash": sha256_text(retrieved.query),
                    "retrieval_provenance": contexts[condition].retrieval_provenance,
                    "scanner": contexts[condition].scan_report.to_dict(),
                    "injection_result_hash": sha256_text(json.dumps(
                        injection_result, sort_keys=True, ensure_ascii=False, default=str
                    )),
                })
            incident_entries = [
                entry.to_dict() for entry in self.engine.ledger.entries[ledger_start:]
            ]
            for raw in raws:
                raw["call_ledger"] = [
                    entry for entry in incident_entries
                    if entry["context_condition"] == raw["context_condition"]
                ]
            pending = (rows, raws, incident_entries)
        except BaseException as exc:
            primary_error = exc
        if injection_attempted:
            try:
                recovery_result = self.recovery.recover(
                    fault_id, trial, injection_result
                )
                if recovery_result.get("health_check_passed") is not True:
                    raise RecoveryFailure("post-trial recovery is not GREEN")
                if hasattr(self.store, "append_event"):
                    self.store.append_event("recovery_green")
            except BaseException as recovery_error:
                if hasattr(self.store, "append_event"):
                    self.store.append_event(
                        "recovery_failed", error_type=type(recovery_error).__name__
                    )
                detail = (
                    f"recovery failed after {type(primary_error).__name__}"
                    if primary_error else "recovery failed"
                )
                raise RecoveryFailure(detail) from recovery_error
        if primary_error is not None:
            raise primary_error.with_traceback(primary_error.__traceback__)
        if pending is None:
            raise PilotError("pilot incident produced no pending result")
        rows, raws, incident_entries = pending
        self.store.write_incident(rows, raws, incident_entries)
        if hasattr(self.store, "append_event"):
            self.store.append_event(
                "incident_committed", rows=len(rows), calls=len(incident_entries)
            )
        return {
            "fault_id": fault_id,
            "trial": trial,
            "rows": len(rows),
            "calls": len(incident_entries),
            "output_dir": str(self.store.output_dir),
        }
