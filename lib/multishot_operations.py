"""Session-level multi-shot operation helpers."""

from lib.multishot_session import MultishotSession


def validate_generation_ready(session: MultishotSession, shot_id: str) -> None:
    state = session._read()
    if shot_id not in state["shots"]:
        raise ValueError(f"Unknown shot: {shot_id}")

    shot = state["shots"][shot_id]
    predecessor = max(
        (
            candidate
            for candidate in state["shots"].values()
            if candidate["order"] < shot["order"]
        ),
        key=lambda candidate: candidate["order"],
        default=None,
    )
    if predecessor and predecessor["status"] != "ACCEPTED":
        raise ValueError(
            f"Cannot generate {shot_id}: predecessor {predecessor['id']} is not ACCEPTED"
        )
