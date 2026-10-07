import copy
from pathlib import Path
from typing import Any, Dict, List

from lib.multishot_workspace import (
    project_lock,
    write_json_atomic,
    read_json_atomic,
    write_artifact,
    REPORTS_DIR,
    sha256_of_dict,
)
from schemas.multishot import validate
from lib.multishot_schemas import validate_all_cross
from lib.multishot_continuity import initial_continuity, accept_shot, continuity_in_for_shot
from lib.multishot_media import validate_shot_clip, probe_clip

def _hash(data: Any) -> str:
    return sha256_of_dict(data)

def _file_hash(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"

class MultishotSession:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self._path = project_dir / REPORTS_DIR / "multishot_session.json"

    def _read(self) -> dict:
        data = read_json_atomic(self._path)
        if data.get("schema_version") != "1.0":
             raise ValueError("Unsupported schema_version")
        if data.get("project_id") != self.project_dir.name:
            raise ValueError("project_id mismatch")
        for shot_id, shot in data.get("shots", {}).items():
            if shot.get("id") != shot_id:
                raise ValueError("Shot id mismatch within data")
            if "order" not in shot:
                raise ValueError("Shots missing order")
        return data

    def _write(self, expected_revision: int, data: dict):
        if self._path.exists():
            disk = read_json_atomic(self._path)
            if disk.get("revision", 0) != expected_revision:
                raise ValueError(f"Stale session write: expected {expected_revision}, got {disk.get('revision')}")
        elif expected_revision != 0 and not self._path.exists():
            raise ValueError("Session missing, expected 0")

        data["revision"] = expected_revision + 1
        write_json_atomic(self._path, data)

    def initialize(self, planning_artifacts: Dict[str, Any]) -> None:
        required_keys = {"request", "story", "character_bible", "style_bible", "shot_plan"}
        if set(planning_artifacts.keys()) != required_keys:
            raise ValueError(f"Initialize requires exact 5 artifacts, got: {list(planning_artifacts.keys())}")

        validate_all_cross(**planning_artifacts)

        with project_lock(self.project_dir):
            if self._path.exists():
                state = self._read()
                if "artifacts" in state and _hash(state["artifacts"]) == _hash(planning_artifacts):
                    return  # idempotent matching artifacts
                raise ValueError("Session already initialized with different artifacts")

            plan = planning_artifacts["shot_plan"]
            plan_fingerprint = _hash(plan)

            shots = {}
            for shot in plan["shots"]:
                shots[shot["id"]] = {
                    "id": shot["id"],
                    "revision": 1,
                    "order": shot["order"],
                    "planned_duration_sec": shot.get("duration_sec", 5.0),
                    "planned_end_state": copy.deepcopy(shot.get("end_state", {})),
                    "status": "PENDING",
                    "bound_input": None,
                    "media_result": None,
                    "review": None,
                    "history": []
                }

            data = {
                "project_id": self.project_dir.name,
                "schema_version": "1.0",
                "revision": 0,
                "plan_fingerprint": plan_fingerprint,
                "artifacts": copy.deepcopy(planning_artifacts),
                "shots": shots,
                "continuity": initial_continuity(),
                "final_evidence": None,
                "assembly_evidence": None
            }

            from schemas.artifacts import ARTIFACT_NAMES
            for name, art in planning_artifacts.items():
                if name not in ARTIFACT_NAMES:
                    raise ValueError(f"Unknown artifact {name!r}")
                path = self.project_dir / "artifacts" / f"{name}.json"
                write_json_atomic(path, art)

            self._write(0, data)

    def get_state(self) -> dict:
        with project_lock(self.project_dir):
            return copy.deepcopy(self._read())

    def bind_input(self, shot_id: str, prompt: str, references: list) -> dict:
        with project_lock(self.project_dir):
            state = self._read()
            # Mutative operation clears evidence
            state["final_evidence"] = None
            state["assembly_evidence"] = None
            shots = state["shots"]
            if shot_id not in shots:
                raise ValueError(f"Unknown shot {shot_id}")

            s = shots[shot_id]
            order = s["order"]

            # Same logic to find pred
            pred_id = None
            pred_order = -1
            for sid, sinfo in shots.items():
                if sinfo["order"] < order and sinfo["order"] > pred_order:
                    pred_order = sinfo["order"]
                    pred_id = sid

            # Enforces correct contiguous state binding
            continuity_in = continuity_in_for_shot(state.get("continuity", {}), order, pred_id)

            input_val = {
                "prompt": prompt,
                "references": copy.deepcopy(references),
                "continuity_in": continuity_in
            }
            input_hash = _hash(input_val)
            input_val["input_hash"] = input_hash

            # Hashes inside references need to belong to the shot or match character/env keys. This is just basic validation.
            if references:
                from lib.multishot_references import generation_reference_keys
            # Simple validation checks without needing full store
            if not prompt or not str(prompt).strip():
               raise ValueError("Prompt must not be empty")

            if s["status"] != "PENDING" and s.get("bound_input"):
                if s["bound_input"]["input_hash"] == input_hash:
                    if s["status"] == "FAILED":
                        # Record failure into history before returning to BOUND state
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
                    raise ValueError(f"Cannot re-bind a different input without regeneration")

            s["bound_input"] = input_val
            s["status"] = "BOUND"
            self._write(state["revision"], state)
            return copy.deepcopy(s)

    def record_result(self, shot_id: str, revision: int, outcome: dict) -> dict:
        with project_lock(self.project_dir):
            state = self._read()
            s = state["shots"][shot_id]
            if s["revision"] != revision:
                raise ValueError(f"Revision mismatch")
            if s["status"] not in ["BOUND", "GENERATED"]:
                raise ValueError(f"Cannot record result in status {s['status']}")

            bound_input = s.get("bound_input")
            if not bound_input or "input_hash" not in bound_input:
                raise ValueError("Shot does not have bound input")

            if outcome.get("input_hash") != bound_input["input_hash"]:
                raise ValueError("Outcome input_hash mismatch")

            if not outcome.get("status"):
                raise ValueError("Missing outcome status")

            if outcome["status"] == "failed":
                s["status"] = "FAILED"
                s["media_result"] = copy.deepcopy(outcome)
                self._write(state["revision"], state)
                return copy.deepcopy(s)
            elif outcome["status"] != "completed":
                raise ValueError(f"Unknown status {outcome['status']}")

            if not outcome.get("file_path"):
                raise ValueError("Outcome is missing a media file_path")

            path = Path(outcome["file_path"])
            if not path.exists():
                raise ValueError(f"Media file not found at {path}")

            actual_checksum = _file_hash(path)

            # Use actual checksum to verify outcome matches current file
            if outcome.get("content_hash") != actual_checksum:
                 raise ValueError("Current file hash does not match outcome content_hash")

            validation = outcome.get("validation")
            if not isinstance(validation, dict):
                 raise ValueError("Missing validation evidence")
            if validation.get("valid") is not True:
                 raise ValueError("Validation evidence must have valid=True")
            if validation.get("input_hash") != bound_input["input_hash"]:
                 raise ValueError("Validation evidence input_hash mismatch")
            if validation.get("content_hash") != actual_checksum:
                 raise ValueError("Validation evidence content_hash mismatch")

            fresh_probe = probe_clip(str(path), timeout=60.0)
            if not fresh_probe.get("decode_ok") or not fresh_probe.get("has_video"):
                 raise ValueError("Media file is unreadable or has no video stream")

            # Validate against expected duration constraints (freshly)
            expected_duration = s.get("planned_duration_sec", 5.0)
            errors = validate_shot_clip(fresh_probe, planned_duration_sec=expected_duration)
            if errors:
                raise ValueError(f"Outcome failed clip constraints: {errors}")

            # Production scheduler validator form may be {valid, probe}; inspect actual code and support both forms intentionally.
            caller_probe = validation.get("probe", validation)
            for field in ["duration_sec", "fps", "codec", "decode_ok", "has_video", "width", "height"]:
                if field in caller_probe and field in fresh_probe:
                    if caller_probe[field] != fresh_probe[field]:
                         raise ValueError(f"Validation evidence {field} contradicts current media")

            # Persist fresh real validation preserving bindings
            final_outcome = copy.deepcopy(outcome)
            final_outcome["content_hash"] = actual_checksum
            final_outcome["validation"] = fresh_probe
            final_outcome["validation"]["valid"] = True
            final_outcome["validation"]["input_hash"] = bound_input["input_hash"]
            final_outcome["validation"]["content_hash"] = actual_checksum

            s["media_result"] = final_outcome
            s["status"] = "GENERATED"
            self._write(state["revision"], state)
            return copy.deepcopy(s)

    def review_shot(self, shot_id: str, revision: int, accepted: bool, end_state: dict, reviewer: str, notes: str) -> dict:
        with project_lock(self.project_dir):
            state = self._read()
            s = state["shots"][shot_id]
            if s["revision"] != revision:
                raise ValueError(f"Revision mismatch")
            if s["status"] not in ["GENERATED", "ACCEPTED", "REJECTED"]:
                raise ValueError(f"Shot not generated")

            if not isinstance(accepted, bool):
                 raise ValueError("Accepted flag must be a boolean")
            if not reviewer or not str(reviewer).strip():
                 raise ValueError("Reviewer string must not be empty")

            if accepted:
                 # Revalidate current media to avoid accepting changed/missing files
                 if not s.get("media_result") or not s["media_result"].get("file_path"):
                      raise ValueError("Missing media for acceptance")
                 path = Path(s["media_result"]["file_path"])
                 if not path.exists():
                      raise ValueError("Media file lost before acceptance")
                 if _file_hash(path) != s["media_result"]["content_hash"]:
                      raise ValueError("Media file altered since generation")

                 # end_state must be identical to planned
                 if end_state != s.get("planned_end_state", {}):
                     raise ValueError("Accepted end_state must exactly match planned_end_state")

            review_val = {
                "accepted": accepted,
                "end_state": copy.deepcopy(end_state),
                "reviewer": reviewer,
                "notes": notes
            }
            review_hash = _hash(review_val)
            review_val["review_hash"] = review_hash

            if s["status"] in ["ACCEPTED", "REJECTED"] and s.get("review"):
                if s["review"].get("review_hash") == review_hash:
                    return copy.deepcopy(s)
                raise ValueError("Cannot change review without regeneration")

            if accepted:
                 order = s["order"]
                 pred_id = None
                 pred_order = -1
                 for sid, sinfo in state["shots"].items():
                     if sinfo["order"] < order and sinfo["order"] > pred_order:
                         pred_order = sinfo["order"]
                         pred_id = sid
                 if pred_id and state["shots"][pred_id]["status"] != "ACCEPTED":
                     raise ValueError("Predecessor no longer accepted")

                 # Validate end state exactly matches planned end state (unless changed later, which drops acceptance anyway due to changed_state logic)
                 if end_state != s.get("planned_end_state", {}):
                     raise ValueError("Accepted end_state must exactly match planned_end_state")

                 s["review"] = review_val
                 s["status"] = "ACCEPTED"
                 s["continuity_before"] = copy.deepcopy(state["continuity"])

                 # The correct accepted state needs to update the entire contiguous tip
                 state["continuity"] = accept_shot(
                     state["continuity"],
                     shot_id,
                     copy.deepcopy(end_state),
                     expected_order=s["order"],
                     shot_order=s["order"]
                 )
                 s["continuity_after"] = copy.deepcopy(state["continuity"])
            else:
                 s["review"] = review_val
                 s["status"] = "REJECTED"
                 # Rejected/failed shots do not mutate continuity

            self._write(state["revision"], state)
            return copy.deepcopy(s)

    def regenerate_shot(self, shot_id: str, end_state: dict = None) -> list:
        with project_lock(self.project_dir):
            state = self._read()
            s = state["shots"][shot_id]

            s["history"].append({
                "revision": s["revision"],
                "status": s["status"],
                "bound_input": copy.deepcopy(s["bound_input"]),
                "media_result": copy.deepcopy(s["media_result"]),
                "review": copy.deepcopy(s["review"]),
            })

            s["revision"] += 1
            old_end_state = s.get("planned_end_state")
            if end_state is not None:
                s["planned_end_state"] = copy.deepcopy(end_state)

            s["status"] = "PENDING"
            s["bound_input"] = None
            s["media_result"] = None
            s["review"] = None

            changed_state = (end_state is not None and end_state != old_end_state)
            if changed_state:
                 from schemas.multishot import load_schema
                 import jsonschema
                 schema = load_schema("shot_plan")
                 end_state_schema = schema["properties"]["shots"]["items"]["properties"]["end_state"]
                 jsonschema.validate(instance=end_state, schema=end_state_schema)

            # Persist exact accepted snapshots for bounded recovery
            s["continuity_before"] = None
            s["continuity_after"] = None

            # Unhook from any current acceptance
            # Removed meaningless logic on non-iterable accepted_through_shot

            # Identify predecessor to repair continuity tip
            order = s["order"]
            pred_id = None
            pred_order = -1
            for sid, sinfo in state["shots"].items():
                if sinfo["order"] < order and sinfo["order"] > pred_order:
                    pred_order = sinfo["order"]
                    pred_id = sid

            if changed_state or True:
                # Need to run a full pass of recomputing tip and invalidation
                stale_ids = []
                for sid, sinfo in state["shots"].items():
                    if sinfo["order"] > order:
                         if changed_state and sinfo["status"] != "STALE":
                             sinfo["history"].append({
                                 "revision": sinfo["revision"],
                                 "status": sinfo["status"],
                                 "bound_input": copy.deepcopy(sinfo["bound_input"]),
                                 "media_result": copy.deepcopy(sinfo["media_result"]),
                                 "review": copy.deepcopy(sinfo["review"]),
                             })
                             sinfo["revision"] += 1
                             sinfo["status"] = "STALE"
                             sinfo["bound_input"] = None
                             sinfo["media_result"] = None
                             sinfo["review"] = None
                             sinfo["continuity_before"] = None
                             sinfo["continuity_after"] = None
                             stale_ids.append(sid)

                # Fully reconstruct the accepted continuity tip from shot 1 through lowest rejected/pending/stale
                sorted_shots = sorted(state["shots"].values(), key=lambda x: x["order"])
                reconstructed = initial_continuity()
                for tshot in sorted_shots:
                    if tshot["status"] == "ACCEPTED":
                        reconstructed = accept_shot(
                             reconstructed,
                             tshot["id"],
                             tshot.get("planned_end_state", {}),
                             expected_order=tshot["order"],
                             shot_order=tshot["order"]
                        )
                    else:
                        break
                state["continuity"] = reconstructed

                # Assembly invalidated whenever generation changes
                state["final_evidence"] = None
                state["assembly_evidence"] = None

                stale_ids = sorted(stale_ids, key=lambda x: state["shots"][x]["order"])
                self._write(state["revision"], state)
                return stale_ids

    def invalidate_reference(self, reference_key: str) -> list:
        with project_lock(self.project_dir):
            state = self._read()
            # Invalidation clears the final assembly
            state["final_evidence"] = None
            state["assembly_evidence"] = None

            stale_ids = []

            shots_to_regen = []

            for sid, sinfo in state["shots"].items():
                bound = sinfo.get("bound_input")
                if bound and bound.get("references"):
                    found = False
                    for ref in bound["references"]:
                        if ref == reference_key:
                            found = True
                        elif isinstance(ref, dict) and reference_key in ref.values():
                            found = True
                    if found:
                        shots_to_regen.append((sinfo["order"], sid))

            shots_to_regen.sort()
            for _, sid in shots_to_regen:
                s = state["shots"][sid]
                # If already PENDING and no history, it has no downstream acceptance anyway
                s["history"].append({
                    "revision": s["revision"],
                    "status": s["status"],
                    "bound_input": copy.deepcopy(s["bound_input"]),
                    "media_result": copy.deepcopy(s["media_result"]),
                    "review": copy.deepcopy(s["review"]),
                })
                s["revision"] += 1
                s["status"] = "PENDING"
                s["bound_input"] = None
                s["media_result"] = None
                s["review"] = None
                if sid in state["continuity"]:
                    del state["continuity"][sid]
                if sid not in stale_ids:
                    stale_ids.append(sid)

                order = s["order"]
                for dsid, dsinfo in state["shots"].items():
                     if dsinfo["order"] > order:
                         if dsinfo["status"] not in ["STALE", "PENDING"]:
                             dsinfo["history"].append({
                                 "revision": dsinfo["revision"],
                                 "status": dsinfo["status"],
                                 "bound_input": copy.deepcopy(dsinfo["bound_input"]),
                                 "media_result": copy.deepcopy(dsinfo["media_result"]),
                                 "review": copy.deepcopy(dsinfo["review"]),
                             })
                             dsinfo["revision"] += 1
                             dsinfo["status"] = "STALE"
                             dsinfo["bound_input"] = None
                             dsinfo["media_result"] = None
                             dsinfo["review"] = None
                             if dsid in state["continuity"]:
                                 del state["continuity"][dsid]
                             if dsid not in stale_ids:
                                 stale_ids.append(dsid)

            stale_ids = sorted(stale_ids, key=lambda x: state["shots"][x]["order"])
            self._write(state["revision"], state)
            return stale_ids
