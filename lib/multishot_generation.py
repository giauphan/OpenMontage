"""First-slice generation preflight: validate and bind a JobSpec without network calls.

prepare_generation validates budget/approval/provider/model/settings, revalidates
references and prompt via prepare_shot_prompt, constructs a JobSpec with the
provider-correct prompt_hash, and binds it via bind_job_spec.  No provider
instance, cost reservation, scheduler or network call is made.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import uuid
from pathlib import Path
from typing import Any, Callable

from lib.config_model import BudgetMode
from lib.multishot_jobs import JobSpec, canonical_input_hash
from lib.multishot_session import MultishotSession
from lib.multishot_workspace import project_lock
from tools.cost_tracker import CostTracker

SUPPORTED_PROVIDERS = frozenset({"gateway", "kling_official", "runway"})


class _AtomicCostTracker(CostTracker):
    """CostTracker with atomic local persistence for one generation ledger."""

    def _save(self) -> None:
        if self.cost_log_path is None:
            return
        data = {
            "version": "1.0",
            "budget_total_usd": self.budget_total_usd,
            "budget_reserved_usd": round(self.budget_reserved_usd, 4),
            "budget_spent_usd": round(self.budget_spent_usd, 4),
            "approved_tools": sorted(self._approved_tools),
            "entries": self.entries,
        }
        self.cost_log_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cost_log_path.with_name(
            f".{self.cost_log_path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.cost_log_path)
            if os.name != "nt":
                descriptor = os.open(self.cost_log_path.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)


def _validate_spend(spend_approved: Any, budget_usd: Any, estimated_usd: Any) -> None:
    if spend_approved is not True:
        raise ValueError("spend_approved must be exactly True")
    for name, value in (("budget_usd", budget_usd), ("estimated_usd", estimated_usd)):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ValueError(f"{name} must be a finite positive number, got {value!r}")
    if estimated_usd > budget_usd:
        raise ValueError(
            f"estimated_usd {estimated_usd} exceeds budget_usd {budget_usd}"
        )


def _prompt_hash_for_provider(provider: str, prompt: str, *, model: str = "", settings: dict | None = None, reference_hashes: list | None = None) -> str:
    """Return the prompt_hash value expected by the given provider."""
    if provider == "kling_official":
        return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return canonical_input_hash(
        provider=provider,
        model=model,
        settings=settings or {},
        prompt=prompt,
        reference_hashes=reference_hashes or [],
    )


def prepare_generation(
    project_dir: Path,
    shot_id: str,
    *,
    provider: str,
    model: str,
    settings: dict,
    spend_approved: Any,
    budget_usd: Any,
    estimated_usd: Any,
    reference_store: dict,
    reference_review: dict,
) -> JobSpec:
    """Validate inputs, revalidate references, construct and bind a JobSpec."""
    _validate_spend(spend_approved, budget_usd, estimated_usd)

    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported provider {provider!r}; supported: {sorted(SUPPORTED_PROVIDERS)}"
        )
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a non-empty string")
    if not isinstance(settings, dict):
        raise ValueError("settings must be a dict")

    session = MultishotSession(project_dir)
    prep = session.prepare_shot_prompt(
        shot_id,
        reference_store,
        reference_review,
        provider=provider,
        model=model,
        settings=settings,
    )
    prompt: str = prep["prompt"]
    ordered_refs: list[dict] = prep["references"]
    shot_state: dict = prep["shot"]

    revision: int = shot_state["revision"]
    duration_sec: float = shot_state["planned_duration_sec"]

    reference_hashes = [ref["sha256"] for ref in ordered_refs]
    prompt_hash = _prompt_hash_for_provider(
        provider,
        prompt,
        model=model,
        settings=settings,
        reference_hashes=reference_hashes,
    )

    spec = JobSpec(
        shot_id=shot_id,
        prompt=prompt,
        prompt_hash=prompt_hash,
        reference_hashes=reference_hashes,
        provider=provider,
        model=model,
        duration_sec=duration_sec,
        settings=copy.deepcopy(settings),
        references=copy.deepcopy(ordered_refs),
        revision=revision,
        prompt_compiler_version=prep["prompt_compiler_version"],
    )
    spec.validate()

    session.bind_job_spec(shot_id, revision, _spec_dict(spec))
    return spec


def execute_generation(
    project_dir: Path,
    shot_id: str,
    *,
    provider: str,
    model: str,
    settings: dict,
    spend_approved: Any,
    budget_usd: Any,
    estimated_usd: Any,
    reference_store: dict,
    reference_review: dict,
    provider_factory: Callable[[], Any] | None = None,
    deadline_seconds: float = 900.0,
    max_polls: int = 100,
    poll_interval: float = 5.0,
) -> dict:
    """Execute one prepared shot with durable, approval-gated recovery under a project-wide lock."""
    _validate_spend(spend_approved, budget_usd, estimated_usd)
    if not math.isfinite(deadline_seconds) or deadline_seconds <= 0:
        raise ValueError("deadline_seconds must be finite and positive")
    if not isinstance(max_polls, int) or isinstance(max_polls, bool) or max_polls < 1:
        raise ValueError("max_polls must be a positive integer")
    if not math.isfinite(poll_interval) or poll_interval < 0:
        raise ValueError("poll_interval must be finite and nonnegative")

    project_dir = Path(project_dir)

    # Use cross-process project-wide dedicated generation lock with safe release via project_lock
    lock_target = project_dir / "reports" / "multishot_jobs"
    lock_target.mkdir(parents=True, exist_ok=True)

    with project_lock(lock_target):
        session = MultishotSession(project_dir)
        state_initial = session.get_state()
        if shot_id not in state_initial["shots"]:
            raise ValueError(f"Unknown shot {shot_id}")
        if state_initial["shots"][shot_id].get("status") == "ACCEPTED":
            raise ValueError(f"Shot {shot_id} is already ACCEPTED; cannot re-execute generation")

        spec = prepare_generation(
            project_dir, shot_id,
            provider=provider, model=model, settings=settings,
            spend_approved=spend_approved, budget_usd=budget_usd,
            estimated_usd=estimated_usd, reference_store=reference_store,
            reference_review=reference_review,
        )
        session = MultishotSession(project_dir)
        shot = session.get_state()["shots"][shot_id]
        revision = spec.revision

        if provider_factory is None:
            from lib.multishot_provider import KlingOfficialProvider
            adapter = KlingOfficialProvider()
        else:
            adapter = provider_factory()
        validate_spec = getattr(adapter, "validate_spec", None)
        if not callable(validate_spec):
            raise ValueError("provider adapter must implement validate_spec")
        validate_spec(spec)

        cost_path = project_dir / "reports" / "cost_log.json"
        tracker = _AtomicCostTracker(
            budget_total_usd=float(budget_usd),
            mode=BudgetMode.CAP,
            single_action_approval_usd=float(budget_usd),
            require_approval_for_new_paid_tool=True,
            cost_log_path=cost_path,
        )
        fingerprint = spec.fingerprint()
        entry = _find_generation_entry(
            tracker, provider, shot_id, revision, fingerprint,
            budget_usd, estimated_usd,
        )
        if entry is None:
            entry_id = tracker.estimate(
                provider, f"generate:{shot_id}:r{revision}", float(estimated_usd)
            )
            entry = tracker._find(entry_id)
            entry.update({
                "shot_id": shot_id,
                "revision": revision,
                "input_hash": fingerprint,
                "budget_usd": float(budget_usd),
            })
            tracker._save()
        else:
            entry_id = entry["id"]

        if entry.get("status") == "estimated":
            tracker.approve_tool(provider)
            tracker.reserve(entry_id)
        elif entry.get("status") not in {"reserved", "completed", "failed", "refunded"}:
            raise ValueError("Existing generation cost entry has invalid status")

        spec.cost_reservation_id = entry_id
        state_dir = project_dir / "reports" / "multishot_jobs"
        output_dir = project_dir / "raw" / shot_id / f"r{revision}"
        scheduler = _build_scheduler(
            adapter, session, spec, state_dir, output_dir,
            deadline_seconds, max_polls, poll_interval,
            project_dir,
        )
        outcome = scheduler.run_one(spec)
        outcome_dict = outcome.to_dict()
        status = outcome_dict["status"]

        if status == "completed":
            if shot.get("status") not in {"GENERATED", "ACCEPTED"}:
                session.record_result(shot_id, revision, outcome_dict)
            if entry.get("status") == "reserved":
                tracker.reconcile(entry_id, float(estimated_usd), success=True)
                tracker._find(entry_id)["actual_cost_source"] = "estimate"
                tracker._save()
        elif status in {"failed", "permanently_failed"}:
            if status == "permanently_failed":
                outcome_dict = {**outcome_dict, "status": "failed"}
            if shot.get("status") not in {"FAILED", "GENERATED", "ACCEPTED"}:
                session.record_result(shot_id, revision, outcome_dict)
            # Never refund based solely on error_code; retain reservation.

        result_state = session.get_state()["shots"][shot_id]
        return {
            "status": status,
            "shot": result_state,
            "outcome": outcome_dict,
            "cost": tracker.cost_snapshot(),
            "cost_entry_id": entry_id,
            "cost_entry_status": tracker._find(entry_id)["status"],
        }


def _find_generation_entry(
    tracker: _AtomicCostTracker,
    provider: str,
    shot_id: str,
    revision: int,
    fingerprint: str,
    budget_usd: Any,
    estimated_usd: Any,
) -> dict | None:
    if tracker.budget_total_usd != float(budget_usd):
        raise ValueError(
            f"Ledger budget_total_usd {tracker.budget_total_usd} does not match requested budget_usd {budget_usd}"
        )
    matches = [
        entry for entry in tracker.entries
        if entry.get("tool") == provider
        and entry.get("operation") == f"generate:{shot_id}:r{revision}"
    ]
    if not matches:
        return None
    entry = matches[-1]
    entry_hash = entry.get("input_hash")
    if not entry_hash:
        raise ValueError("Orphaned estimated generation entry detected (missing input_hash); failing closed")
    if entry_hash != fingerprint:
        raise ValueError("Existing generation cost entry input_hash mismatch; failing closed")
    if (entry.get("budget_usd") != float(budget_usd)
            or entry.get("estimated_usd") != round(float(estimated_usd), 4)):
        raise ValueError("Existing generation reservation has changed budget or estimate")
    return entry


def _build_scheduler(
    adapter: Any,
    session: MultishotSession,
    spec: JobSpec,
    state_dir: Path,
    output_dir: Path,
    deadline_seconds: float,
    max_polls: int,
    poll_interval: float,
    project_dir: Path,
):
    from lib.multishot_jobs import JobScheduler
    from lib.multishot_references import validate_generation_ready

    def eligible(current: JobSpec) -> bool:
        try:
            state = session.get_state()
            shot = state["shots"].get(current.shot_id)
            if not shot or shot.get("revision") != current.revision:
                return False
            if shot.get("job_input_hash") != current.fingerprint():
                return False
            bound_input = shot.get("bound_input") or {}
            if bound_input.get("prompt") != current.prompt or bound_input.get("references") != current.references:
                return False

            # Revalidate persisted reference_store with validate_generation_ready and current shot/bible
            ref_store = bound_input.get("reference_store")
            artifacts = state.get("artifacts", {})
            char_bible = artifacts.get("character_bible", {})
            shot_plan_shots = artifacts.get("shot_plan", {}).get("shots", [])
            shot_meta = next((s for s in shot_plan_shots if s["id"] == current.shot_id), None)
            if not ref_store or not shot_meta:
                return False
            validate_generation_ready(ref_store, shot_meta, char_bible)

            predecessor = _predecessor(state, current.shot_id)
            if predecessor is not None and state["shots"][predecessor]["status"] != "ACCEPTED":
                return False
            return True
        except Exception:
            return False

    return JobScheduler(
        adapter,
        max_concurrency=1,
        max_attempts=1,
        deadline_seconds=deadline_seconds,
        max_polls=max_polls,
        poll_interval=poll_interval,
        dest_dir=output_dir,
        state_dir=state_dir,
        eligibility=eligible,
    )


def _predecessor(state: dict, shot_id: str) -> str | None:
    shot = state["shots"][shot_id]
    previous = [
        candidate for candidate in state["shots"].values()
        if candidate["order"] < shot["order"]
    ]
    return max(previous, key=lambda candidate: candidate["order"])["id"] if previous else None


def _spec_dict(spec: JobSpec) -> dict:
    from dataclasses import asdict
    return asdict(spec)
