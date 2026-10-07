import copy
from typing import Any, Dict

from lib.multishot_session import MultishotSession
from lib.multishot_prompt_builder import build_multishot_prompt
from lib.multishot_references import gather_references_for_prompt
from lib.multishot_workspace import project_lock

def validate_generation_ready(session: MultishotSession, shot_id: str):
    """Validate that the session is in a known healthy state for generation."""
    state = session._read()
    if shot_id not in state["shots"]:
        raise ValueError(f"Unknown shot: {shot_id}")
    shot = state["shots"][shot_id]

    order = shot["order"]
    # Identify predecessor
    pred_id = None
    pred_order = -1
    for sid, sinfo in state["shots"].items():
        if sinfo["order"] < order and sinfo["order"] > pred_order:
            pred_order = sinfo["order"]
            pred_id = sid

    if pred_id:
        pred_shot = state["shots"][pred_id]
        if pred_shot["status"] != "ACCEPTED":
            raise ValueError(f"Cannot generate {shot_id}: predecessor {pred_id} is not ACCEPTED")

def prepare_shot_prompt(self, shot_id: str, reference_store: dict, reference_review: dict) -> tuple[str, list]:
    from lib.multishot_continuity import continuity_in_for_shot
    with project_lock(self.project_dir):
        state = self._read()
        shots = state["shots"]
        if shot_id not in shots:
            raise ValueError(f"Unknown shot {shot_id}")

        s = shots[shot_id]
        order = s["order"]

        # Validate predecessors
        pred_id = None
        pred_order = -1
        for sid, sinfo in shots.items():
            if sinfo["order"] < order and sinfo["order"] > pred_order:
                pred_order = sinfo["order"]
                pred_id = sid

        if pred_id and shots[pred_id]["status"] != "ACCEPTED":
            raise ValueError(f"Cannot prepare shot {shot_id}: predecessor {pred_id} is not ACCEPTED")

        # Gather necessary artifacts
        artifacts = state["artifacts"]
        shot_def = next(ds for ds in artifacts["shot_plan"]["shots"] if ds["id"] == shot_id)

        continuity_in = continuity_in_for_shot(state.get("continuity", {}), order, pred_id)

        prompt = build_multishot_prompt(
            project_title=artifacts.get("request", {}).get("topic", state.get("project_id", "project")),
            request=artifacts.get("request", {}),
            story=artifacts.get("story", {}),
            character_bible=artifacts.get("character_bible", {}),
            style_bible=artifacts.get("style_bible", {}),
            shot=shot_def,
            continuity_in=continuity_in
        )

        refs = gather_references_for_prompt(reference_store, artifacts["character_bible"], artifacts["style_bible"], shot_def)

        return prompt, refs

def bind_job_spec(self, shot_id: str, revision: int, spec_dict: dict) -> dict:
    from lib.multishot_session import _hash
    from lib.multishot_jobs import JobSpec

    with project_lock(self.project_dir):
        state = self._read()
        shots = state["shots"]
        if shot_id not in shots:
            raise ValueError(f"Unknown shot {shot_id}")

        s = shots[shot_id]
        if s["revision"] != revision:
            raise ValueError(f"Stale bind: requested revision {revision}, but shot is at {s['revision']}")

        spec = JobSpec(**spec_dict)
        spec.validate()

        if spec.shot_id != shot_id:
            raise ValueError("JobSpec shot_id mismatch")
        if spec.revision != revision:
            raise ValueError("JobSpec revision mismatch")

        if spec.duration_sec != s["planned_duration_sec"]:
            raise ValueError("JobSpec duration must match planned_duration_sec")

        spec_hash = _hash(spec_dict)
        out_dict = spec.to_dict()
        out_dict["job_input_hash"] = spec_hash

        # Check idempotency
        if s["status"] != "PENDING" and s.get("bound_input"):
            if s["bound_input"].get("job_input_hash") == spec_hash:
                if s["status"] == "FAILED":
                    s["history"].append({
                        "revision": s["revision"],
                        "status": s["status"],
                        "bound_input": copy.deepcopy(s["bound_input"]),
                        "media_result": copy.deepcopy(s["media_result"]),
                        "review": copy.deepcopy(s["review"])
                    })
                    s["status"] = "BOUND"
                    s["media_result"] = None
                    s["review"] = None
                    self._write(state["revision"], state)
                return copy.deepcopy(s)
            else:
                raise ValueError("Cannot bind changed job_spec in the same revision")

        # Bind the spec
        spec_dict_clone = copy.deepcopy(spec_dict)
        spec_dict_clone["job_input_hash"] = spec_hash
        s["bound_input"] = spec_dict_clone
        s["status"] = "BOUND"

        self._write(state["revision"], state)
        return copy.deepcopy(s)

MultishotSession.prepare_shot_prompt = prepare_shot_prompt
MultishotSession.bind_job_spec = bind_job_spec

