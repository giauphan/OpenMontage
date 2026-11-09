#!/usr/bin/env python3
"""Request director artifacts from a coding agent supervised on the local host."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

from lib.local_agent_handoff import HandoffError, request_local_agent


ALLOWED_OUTPUTS = frozenset({
    "artifacts/script_vi.json", "artifacts/script_en_US.json", "artifacts/script.json",
    "artifacts/news_visual_plan.json", "artifacts/template_selection.json", "artifacts/template_content.json",
    "hyperframes/index.html", "hyperframes_reels/index.html",
})
MAX_FILE_BYTES = 4_000_000


def run_director_handoff(project: Path, handoff_root: Path, prompt: str, system: str, *, timeout_seconds: float) -> None:
    raw_project = Path(project)
    if any(part == ".." for part in raw_project.parts) or raw_project.is_symlink():
        raise HandoffError("invalid project directory")
    project = raw_project.resolve()
    if not project.is_dir() or project.is_symlink():
        raise HandoffError("invalid project directory")
    raw_research = project / "artifacts" / "research_brief.json"
    if raw_research.is_symlink() or raw_research.parent.is_symlink():
        raise HandoffError("invalid research brief")
    research = raw_research.resolve()
    try:
        research.relative_to(project)
    except ValueError as exc:
        raise HandoffError("invalid research brief path") from exc
    if not research.is_file() or research.stat().st_size > MAX_FILE_BYTES:
        raise HandoffError("invalid research brief")
    previous = {}
    for relative in sorted(ALLOWED_OUTPUTS):
        rel_p = Path(relative)
        if any(part == ".." for part in rel_p.parts) or rel_p.is_absolute():
            continue
        raw_path = project / rel_p
        if raw_path.is_symlink() or raw_path.parent.is_symlink():
            continue
        path = raw_path.resolve()
        try:
            path.relative_to(project)
        except ValueError:
            continue
        if path.is_file() and path.stat().st_size <= MAX_FILE_BYTES:
            previous[relative] = path.read_text(encoding="utf-8")
    captured_text = []
    raw_capture_dir = project / "artifacts" / "news_source_capture"
    if raw_capture_dir.is_symlink() or raw_capture_dir.parent.is_symlink():
        has_valid_capture_dir = False
    else:
        capture_dir = raw_capture_dir.resolve()
        try:
            capture_dir.relative_to(project)
            has_valid_capture_dir = capture_dir.is_dir()
        except ValueError:
            has_valid_capture_dir = False
    if has_valid_capture_dir:
        for path in sorted(capture_dir.glob("*.extracted.json"))[:5]:
            if path.is_symlink():
                continue
            p_res = path.resolve()
            try:
                p_res.relative_to(capture_dir)
            except ValueError:
                continue
            if not p_res.is_file() or p_res.stat().st_size > MAX_FILE_BYTES:
                continue
            try:
                data = json.loads(p_res.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("text"), str):
                    captured_text.append(data["text"][:20000])
            except (OSError, ValueError):
                continue
    payload = {"project_id": project.name, "server_project_dir": str(project), "prompt": prompt,
               "system": system, "research_brief": research.read_text(encoding="utf-8"), "existing_files": previous,
               "captured_source_text": "\n\n".join(captured_text)}
    response = request_local_agent(handoff_root, "director", payload, timeout_seconds=timeout_seconds)
    files = response.get("files")
    if not isinstance(files, dict) or not files:
        raise HandoffError("director response contains no artifacts")
    for relative, value in files.items():
        if relative not in ALLOWED_OUTPUTS or not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > MAX_FILE_BYTES:
            raise HandoffError("director response contains an invalid artifact")
        if any(part == ".." for part in Path(relative).parts) or Path(relative).is_absolute():
            raise HandoffError("director response contains an invalid artifact")

    project_fd = os.open(str(project), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for relative, value in files.items():
            directory, name = relative.split("/", 1)
            try:
                os.mkdir(directory, mode=0o755, dir_fd=project_fd)
            except FileExistsError:
                pass
            try:
                directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=project_fd)
            except OSError as exc:
                raise HandoffError("invalid artifact directory") from exc
            temporary = ".director-" + uuid.uuid4().hex
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=directory_fd)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(value)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
                os.close(directory_fd)
    finally:
        os.close(project_fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--system", required=True)
    args = parser.parse_args()
    raw_proj = Path(args.project)
    if any(part == ".." for part in raw_proj.parts) or raw_proj.is_symlink():
        print("error: invalid project path", file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parents[1]
    try:
        run_director_handoff(raw_proj, Path(os.environ.get("OPENMONTAGE_AGENT_HANDOFF_DIR") or root / "data" / "local_agent_handoff"),
                             args.prompt, args.system, timeout_seconds=float(os.environ.get("OPENMONTAGE_AGENT_HANDOFF_TIMEOUT", "1800")))
    except (HandoffError, OSError, ValueError) as exc:
        print(f"local director handoff failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"is_error": False, "result": "local director handoff completed"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
