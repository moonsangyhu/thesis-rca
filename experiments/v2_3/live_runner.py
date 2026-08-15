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


class FluxAppGuard:
    """Temporarily suspend one Flux Kustomization with exact-state restore."""

    def __init__(
        self,
        resource_loader: Callable[[], dict],
        suspend_patcher: Callable[[bool | None, str], dict],
        name: str = "app",
    ) -> None:
        self.resource_loader = resource_loader
        self.suspend_patcher = suspend_patcher
        self.name = name

    @staticmethod
    def _identity(resource: dict) -> tuple[str, str, str]:
        metadata = resource.get("metadata", {}) if isinstance(resource, dict) else {}
        return (
            str(metadata.get("namespace") or ""),
            str(metadata.get("name") or ""),
            str(metadata.get("uid") or ""),
        )

    def prepare_recovery_context(self) -> dict:
        resource = self.resource_loader()
        namespace, name, uid = self._identity(resource)
        if (namespace, name) != ("flux-system", self.name) or not uid:
            raise PilotError("Flux Kustomization identity is invalid")
        spec = resource.get("spec", {})
        if not isinstance(spec, dict):
            raise PilotError("Flux Kustomization spec is invalid")
        present = "suspend" in spec
        original = spec.get("suspend", False)
        resource_version = str(
            resource.get("metadata", {}).get("resourceVersion") or ""
        )
        if not isinstance(original, bool):
            raise PilotError("Flux suspend state is invalid")
        if original:
            raise PilotError("Flux Kustomization must be active before the pilot")
        if not resource_version:
            raise PilotError("Flux resourceVersion is missing")
        return {
            "flux_guard_schema": "v2.3-flux-app-guard-1",
            "flux_namespace": namespace,
            "flux_name": name,
            "flux_uid": uid,
            "flux_resource_version": resource_version,
            "flux_original_suspend_present": present,
            "flux_original_suspend": original,
        }

    def _validate_receipt(self, context: dict) -> None:
        required = {
            "flux_guard_schema", "flux_namespace", "flux_name", "flux_uid",
            "flux_resource_version", "flux_original_suspend_present",
            "flux_original_suspend",
        }
        if set(context) != required:
            raise PilotError("Flux recovery receipt schema mismatch")
        if (
            context["flux_guard_schema"] != "v2.3-flux-app-guard-1"
            or (context["flux_namespace"], context["flux_name"])
            != ("flux-system", self.name)
            or not context["flux_uid"]
            or not isinstance(context["flux_resource_version"], str)
            or not context["flux_resource_version"]
            or not isinstance(context["flux_original_suspend_present"], bool)
            or context["flux_original_suspend"] is not False
        ):
            raise PilotError("Flux recovery receipt is invalid")

    def suspend(self, context: dict) -> dict:
        self._validate_receipt(context)
        current = self.resource_loader()
        if self._identity(current) != (
            context["flux_namespace"], context["flux_name"], context["flux_uid"]
        ):
            raise PilotError("Flux identity changed before suspension")
        current_spec = current.get("spec", {})
        current_rv = str(current.get("metadata", {}).get("resourceVersion") or "")
        if (
            current_rv != context["flux_resource_version"]
            or ("suspend" in current_spec)
            != context["flux_original_suspend_present"]
            or current_spec.get("suspend", False)
            != context["flux_original_suspend"]
        ):
            raise PilotError("Flux object changed after recovery receipt was sealed")
        patched = self.suspend_patcher(True, current_rv)
        patched_rv = str(patched.get("metadata", {}).get("resourceVersion") or "")
        if (
            self._identity(patched) != self._identity(current)
            or patched.get("spec", {}).get("suspend") is not True
            or not patched_rv or patched_rv == current_rv
        ):
            raise PilotError("Flux suspension CAS did not succeed")
        suspended = self.resource_loader()
        if (
            self._identity(suspended) != self._identity(current)
            or suspended.get("spec", {}).get("suspend") is not True
        ):
            raise PilotError("Flux suspension did not persist")
        return dict(context)

    def verify_suspended(self, context: dict) -> None:
        self._validate_receipt(context)
        current = self.resource_loader()
        if (
            self._identity(current)
            != (context["flux_namespace"], context["flux_name"], context["flux_uid"])
            or current.get("spec", {}).get("suspend") is not True
        ):
            raise PilotError("Flux suspension did not remain stable")

    def restore(self, context: dict) -> dict:
        self._validate_receipt(context)
        current = self.resource_loader()
        if self._identity(current) != (
            context["flux_namespace"], context["flux_name"], context["flux_uid"]
        ):
            raise PilotError("Flux identity changed before restore")
        current_spec = current.get("spec", {})
        current_rv = str(current.get("metadata", {}).get("resourceVersion") or "")
        if not isinstance(current_spec, dict) or not current_rv:
            raise PilotError("Flux current state is invalid during restore")
        current_present = "suspend" in current_spec
        current_value = current_spec.get("suspend", False)
        exact_original = (
            current_present == context["flux_original_suspend_present"]
            and current_value == context["flux_original_suspend"]
        )
        if exact_original:
            return {
                "flux_restored": True, "flux_exact_original": True,
                "flux_suspend_present": current_present,
                "flux_restore_action": "already-original",
            }
        if current_value is not True:
            # A concurrent actor changed the object after the receipt. Never
            # erase that state merely to recreate the older field shape.
            return {
                "flux_restored": False, "flux_exact_original": False,
                "flux_suspend_present": current_present,
                "flux_restore_action": "external-change-preserved",
            }
        restore_value = (
            context["flux_original_suspend"]
            if context["flux_original_suspend_present"] else None
        )
        patched = self.suspend_patcher(restore_value, current_rv)
        patched_spec = patched.get("spec", {}) if isinstance(patched, dict) else {}
        patched_rv = str(patched.get("metadata", {}).get("resourceVersion") or "")
        if (
            self._identity(patched) != self._identity(current)
            or not patched_rv or patched_rv == current_rv
            or ("suspend" in patched_spec)
            != context["flux_original_suspend_present"]
            or patched_spec.get("suspend", False)
            != context["flux_original_suspend"]
        ):
            raise PilotError("Flux restore CAS did not succeed")
        restored = self.resource_loader()
        spec = restored.get("spec", {}) if isinstance(restored, dict) else {}
        present = "suspend" in spec
        value = spec.get("suspend", False)
        if (
            self._identity(restored) != self._identity(current)
            or present != context["flux_original_suspend_present"]
            or value != context["flux_original_suspend"]
        ):
            raise PilotError("Flux suspend state was not exactly restored")
        return {
            "flux_restored": True, "flux_exact_original": True,
            "flux_suspend_present": present,
            "flux_restore_action": "cas-restored",
        }


class FluxHierarchyGuard:
    """Suspend the self-managing Flux root before its child app object."""

    def __init__(
        self,
        root_guard: FluxAppGuard,
        app_guard: FluxAppGuard,
        settle: Callable[..., None] | None = None,
    ) -> None:
        self.root_guard = root_guard
        self.app_guard = app_guard
        self.settle = settle or self._verify_members

    @staticmethod
    def _verify_members(*members: tuple[FluxAppGuard, dict]) -> None:
        for guard, receipt in members:
            guard.verify_suspended(receipt)

    @staticmethod
    def _validate(context: dict) -> None:
        if (
            not isinstance(context, dict)
            or set(context) != {"flux_hierarchy_schema", "root", "app"}
            or context.get("flux_hierarchy_schema") != "v2.3-flux-hierarchy-1"
            or not isinstance(context.get("root"), dict)
            or not isinstance(context.get("app"), dict)
        ):
            raise PilotError("Flux hierarchy receipt schema mismatch")

    def prepare_recovery_context(self) -> dict:
        return {
            "flux_hierarchy_schema": "v2.3-flux-hierarchy-1",
            "root": self.root_guard.prepare_recovery_context(),
            "app": self.app_guard.prepare_recovery_context(),
        }

    @staticmethod
    def _same_original_object(previous: dict, refreshed: dict) -> bool:
        """Allow only resourceVersion drift while the root becomes quiescent."""
        previous_without_rv = dict(previous)
        refreshed_without_rv = dict(refreshed)
        previous_without_rv.pop("flux_resource_version", None)
        refreshed_without_rv.pop("flux_resource_version", None)
        return previous_without_rv == refreshed_without_rv

    def suspend_with_receipt_observer(
        self,
        context: dict,
        receipt_observer: Callable[[dict], None],
    ) -> dict:
        """Suspend root/app with a durable, post-root app CAS receipt.

        The child resourceVersion can legitimately advance while the root is
        settling.  The refreshed receipt must be durably observed before the
        child mutation so crash recovery always has the exact CAS pre-state.
        """
        self._validate(context)
        if not callable(receipt_observer):
            raise PilotError("Flux hierarchy receipt observer is required")
        self.root_guard.suspend(context["root"])
        self.settle((self.root_guard, context["root"]))

        refreshed_app = self.app_guard.prepare_recovery_context()
        if not self._same_original_object(context["app"], refreshed_app):
            raise PilotError("Flux app identity/original state drifted during root settle")
        refreshed_context = json.loads(json.dumps(context, sort_keys=True))
        refreshed_context["app"] = json.loads(json.dumps(refreshed_app, sort_keys=True))
        receipt_observer(json.loads(json.dumps(refreshed_context, sort_keys=True)))

        self.app_guard.suspend(refreshed_context["app"])
        members = (
            (self.root_guard, refreshed_context["root"]),
            (self.app_guard, refreshed_context["app"]),
        )
        self.settle(*members)
        self._verify_members(*members)
        return json.loads(json.dumps(refreshed_context, sort_keys=True))

    def suspend(self, context: dict) -> dict:
        raise PilotError(
            "Flux hierarchy suspension requires a durable receipt observer"
        )

    def restore(self, context: dict) -> dict:
        self._validate(context)
        errors: list[BaseException] = []
        app_result: dict = {}
        root_result: dict = {}
        try:
            app_result = self.app_guard.restore(context["app"])
            if not app_result.get("flux_exact_original"):
                raise PilotError("Flux app exact restore failed")
        except BaseException as exc:
            errors.append(exc)
        try:
            root_result = self.root_guard.restore(context["root"])
            if not root_result.get("flux_exact_original"):
                raise PilotError("Flux root exact restore failed")
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise PilotError("Flux hierarchy exact restore failed") from errors[0]
        return {
            "flux_restored": True,
            "flux_exact_original": True,
            "flux_suspend_present": {
                "root": root_result.get("flux_suspend_present"),
                "app": app_result.get("flux_suspend_present"),
            },
            "flux_restore_action": {
                "root": root_result.get("flux_restore_action"),
                "app": app_result.get("flux_restore_action"),
            },
        }


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


class MainOutputStore(PilotOutputStore):
    """Fresh, append-per-incident primary campaign artifact store."""

    def __init__(self, output_dir: Path):
        output_dir = Path(output_dir)
        project_root = Path(__file__).resolve().parents[2]
        allowed_root = (project_root / "artifacts" / "v2_3_main").resolve()
        resolved = output_dir.resolve()
        if allowed_root not in resolved.parents or resolved == allowed_root:
            raise PilotError(
                "main output must be a campaign directory under artifacts/v2_3_main"
            )
        if resolved.exists():
            raise PilotError("main output directory already exists")
        SafeOutputStore.__init__(self, resolved)
        self.csv_path = self.output_dir / "experiment_results_v2_3.csv"
        self.raw_dir = self.output_dir / "raw_v2_3"
        self.ledger_path = self.output_dir / "call_ledger_v2_3.jsonl"
        self._keys = self._load_keys()

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
    flux_guard: object
    retriever: RuntimeOnlyRetriever
    store: PilotOutputStore
    allowed_incidents: frozenset[tuple[str, int]] | None = None
    renderer: RuntimeEvidenceRenderer = RuntimeEvidenceRenderer()
    sleep_fn: Callable[[float], None] = __import__("time").sleep

    def __post_init__(self) -> None:
        self.authorization.revalidate()
        caller_auth = getattr(self.engine.caller, "authorization", None)
        if caller_auth != self.authorization:
            raise PilotError("runner and Terra caller authorization differ")

    def run(self, fault_id: str, trial: int, ground_truth: dict) -> dict:
        self.authorization.revalidate()
        allowed = self.allowed_incidents or frozenset({(PILOT_FAULT_ID, PILOT_TRIAL)})
        if (fault_id, trial) not in allowed:
            if self.allowed_incidents is None:
                raise PilotError(
                    f"V2.3 live pilot is frozen to {PILOT_FAULT_ID} trial {PILOT_TRIAL}"
                )
            raise PilotError(
                f"V2.3 live incident is not authorized: {fault_id} trial {trial}"
            )
        validation = self.validator.validate_and_correct(fault_id=fault_id, trial=trial)
        if getattr(validation, "status", None) not in {"clean", "corrected"}:
            raise PilotError("pre-injection cluster state is not GREEN")

        flux_context: dict = {}
        flux_attempted = False
        injection_result: dict = {}
        injection_attempted = False
        primary_error: BaseException | None = None
        pending: tuple[list[dict], list[dict], list[dict]] | None = None
        try:
            prepare_flux = getattr(self.flux_guard, "prepare_recovery_context", None)
            if not callable(prepare_flux):
                raise PilotError("Flux guard lacks durable recovery receipt support")
            prepared_flux = prepare_flux()
            if not isinstance(prepared_flux, dict) or not prepared_flux:
                raise PilotError("Flux recovery receipt is empty")
            sealed_flux = json.dumps(
                prepared_flux, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            )
            flux_context = json.loads(sealed_flux)
            if hasattr(self.store, "append_event"):
                self.store.append_event(
                    "flux_recovery_receipt_sealed",
                    recovery_context=json.loads(sealed_flux),
                )
            flux_attempted = True
            refreshed_flux: str | None = None

            def seal_refreshed_flux(receipt: dict) -> None:
                nonlocal refreshed_flux
                candidate = json.dumps(
                    receipt, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                )
                if refreshed_flux is not None:
                    raise PilotError("Flux app recovery receipt was refreshed twice")
                if hasattr(self.store, "append_event"):
                    self.store.append_event(
                        "flux_app_recovery_receipt_refreshed",
                        recovery_context=json.loads(candidate),
                    )
                refreshed_flux = candidate

            suspend_with_observer = getattr(
                self.flux_guard, "suspend_with_receipt_observer", None
            )
            if callable(suspend_with_observer):
                suspended_context = suspend_with_observer(
                    json.loads(sealed_flux), seal_refreshed_flux
                )
            else:
                suspended_context = self.flux_guard.suspend(json.loads(sealed_flux))
            returned_flux = json.dumps(
                suspended_context, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            )
            expected_flux = refreshed_flux or sealed_flux
            if returned_flux != expected_flux:
                raise PilotError("Flux guard altered the sealed recovery receipt")
            flux_context = json.loads(expected_flux)
            if hasattr(self.store, "append_event"):
                self.store.append_event(
                    "flux_suspended", namespace="flux-system", name="app"
                )
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
            if hasattr(self.store, "append_event"):
                try:
                    self.store.append_event(
                        "incident_failed", error_type=type(exc).__name__
                    )
                except BaseException:
                    # Diagnostic persistence must never bypass mandatory
                    # post-injection recovery. Preserve the primary failure.
                    pass
        recovery_errors: list[BaseException] = []
        if injection_attempted:
            try:
                recovery_result = self.recovery.recover(
                    fault_id, trial, injection_result
                )
                if recovery_result.get("health_check_passed") is not True:
                    raise RecoveryFailure("post-trial recovery is not GREEN")
            except BaseException as recovery_error:
                recovery_errors.append(recovery_error)
        if flux_attempted:
            try:
                flux_restore = self.flux_guard.restore(flux_context)
                if (
                    flux_restore.get("flux_restored") is not True
                    or flux_restore.get("flux_exact_original") is not True
                ):
                    raise RecoveryFailure("Flux app restore did not PASS")
                if hasattr(self.store, "append_event"):
                    self.store.append_event("flux_restored", **flux_restore)
            except BaseException as flux_error:
                recovery_errors.append(flux_error)
        if recovery_errors:
            if hasattr(self.store, "append_event"):
                try:
                    self.store.append_event(
                        "recovery_failed",
                        error_types=[type(error).__name__ for error in recovery_errors],
                    )
                except BaseException:
                    pass
            detail = (
                f"recovery failed after {type(primary_error).__name__}"
                if primary_error else "recovery failed"
            )
            raise RecoveryFailure(detail) from recovery_errors[0]
        if injection_attempted or flux_attempted:
            if hasattr(self.store, "append_event"):
                self.store.append_event(
                    "recovery_green", fault_id=fault_id, trial=trial
                )
        if primary_error is not None:
            raise primary_error.with_traceback(primary_error.__traceback__)
        if pending is None:
            raise PilotError("pilot incident produced no pending result")
        rows, raws, incident_entries = pending
        self.store.write_incident(rows, raws, incident_entries)
        if hasattr(self.store, "append_event"):
            self.store.append_event(
                "incident_committed", fault_id=fault_id, trial=trial,
                rows=len(rows), calls=len(incident_entries)
            )
        return {
            "fault_id": fault_id,
            "trial": trial,
            "rows": len(rows),
            "calls": len(incident_entries),
            "output_dir": str(self.store.output_dir),
        }
