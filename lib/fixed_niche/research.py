"""Truthful evidence research, claim review, and sandboxed demo execution."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from tools.news.fixed_niche_sources import ALLOWED_PRIMARY_DOMAINS, FixedNicheSourceAdapter

logger = logging.getLogger(__name__)


class ResearchValidationError(ValueError):
    """Raised when research data fails truthfulness, safety, or primary-source policies."""
    pass


class ClaimClassification(str, Enum):
    DOCUMENTED = "DOCUMENTED"
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"


class DemoExecutionProtocol:
    """Executes safe, isolated commands for genuine demo reproductions."""

    ALLOWED_COMMAND_BINARIES = {"python", "python3", "pytest", "git", "node", "npm", "echo", "cat", "ls"}

    def __init__(self, working_dir: Path):
        self.working_dir = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)

    def run_isolated_command(
        self,
        command: str,
        timeout_seconds: int = 15,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Run an isolated test command under strict timeout, binary allowlist, and no shell execution."""
        import shlex

        try:
            cmd_args = shlex.split(command)
        except Exception as e:
            raise ResearchValidationError(f"Invalid command syntax: {e}")

        if not cmd_args:
            raise ResearchValidationError("Empty demo command")

        cmd_bin = Path(cmd_args[0]).name
        if cmd_bin not in self.ALLOWED_COMMAND_BINARIES:
            raise ResearchValidationError(
                f"Disallowed binary in demo command: {cmd_bin}. "
                f"Permitted binaries: {sorted(list(self.ALLOWED_COMMAND_BINARIES))}"
            )

        # Disallow dangerous shell chaining or redirection tokens
        operator_tokens = {";", "&&", "||", "|", ">", "<", ">>", "2>", "&"}
        for arg in cmd_args:
            if arg in operator_tokens:
                raise ResearchValidationError(f"Shell redirection or chaining token disallowed in demo command: {arg}")

        # Disallow path traversal or access to sensitive system directories
        sensitive_prefixes = ("/etc", "/root", "/sys", "/proc", "/dev", "/boot")
        for arg in cmd_args:
            if any(arg == p or arg.startswith(p + "/") for p in sensitive_prefixes):
                raise ResearchValidationError(f"Access to restricted system directory disallowed: {arg}")
            if ".." in arg:
                try:
                    resolved_cand = (self.working_dir / arg).resolve()
                    if not str(resolved_cand).startswith(str(self.working_dir.resolve())):
                        raise ResearchValidationError(f"Path traversal outside sandbox working directory disallowed: {arg}")
                except ResearchValidationError:
                    raise
                except Exception:
                    raise ResearchValidationError(f"Invalid path argument in demo command: {arg}")

        # Security: sanitize environment to prevent leaking secrets/tokens
        allowed_keys = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "COMSPEC")
        env = {k: os.environ[k] for k in allowed_keys if k in os.environ}
        env["HOME"] = str(self.working_dir)
        sandbox_tmp = self.working_dir / ".sandbox_tmp"
        sandbox_tmp.mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = str(sandbox_tmp)

        # Enforce OS-level & Python-level network socket isolation
        audit_file = sandbox_tmp / "sitecustomize.py"
        audit_code = (
            "import sys\n"
            "def audit_hook(event, args):\n"
            "    if event in ('socket.connect', 'socket.bind', 'socket.sendto', 'http.client.connect'):\n"
            "        raise PermissionError(f'Network access blocked in demo sandbox: {event}')\n"
            "try:\n"
            "    sys.addaudithook(audit_hook)\n"
            "except Exception:\n"
            "    pass\n"
        )
        try:
            audit_file.write_text(audit_code, encoding="utf-8")
            existing_pp = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{sandbox_tmp}:{existing_pp}" if existing_pp else str(sandbox_tmp)
        except Exception:
            pass

        if env_vars:
            env.update(env_vars)

        env_signature = hashlib.sha256(
            f"{os.uname().sysname}|{os.uname().machine}|{command}".encode("utf-8")
        ).hexdigest()

        def _apply_sandbox_limits():
            """Enforce POSIX resource limits and process group isolation."""
            try:
                import resource
                resource.setrlimit(resource.RLIMIT_CPU, (timeout_seconds + 5, timeout_seconds + 10))
                max_as = 2 * 1024 * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (max_as, max_as))
                max_fsize = 50 * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_FSIZE, (max_fsize, max_fsize))
            except (ValueError, OSError, AttributeError):
                pass
            try:
                os.setpgrp()
            except (AttributeError, OSError):
                pass

        start_time = time.time()
        try:
            res = subprocess.run(
                cmd_args,
                shell=False,
                cwd=str(self.working_dir),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
                preexec_fn=_apply_sandbox_limits,
            )
            elapsed = time.time() - start_time
            return {
                "command": command,
                "exit_code": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "elapsed_seconds": round(elapsed, 3),
                "env_hash": env_signature,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "verified": res.returncode == 0,
            }
        except subprocess.TimeoutExpired as e:
            return {
                "command": command,
                "exit_code": -1,
                "stdout": str(e.stdout or ""),
                "stderr": f"Command timed out after {timeout_seconds}s",
                "elapsed_seconds": timeout_seconds,
                "env_hash": env_signature,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "verified": False,
            }


class FixedNicheResearcher:
    """Validates evidence bundles and produces truthful research briefs."""

    FIRST_PERSON_TEST_PATTERNS = [
        re.compile(r"\b(we\s+tested|i\s+tested|in\s+our\s+lab|our\s+benchmark(s)?\s+show|we\s+measured)\b", re.I),
    ]

    def __init__(self):
        self.source_adapter = FixedNicheSourceAdapter()

    @staticmethod
    def compute_file_sha(file_path: Path) -> str:
        """Compute SHA256 checksum of a file on disk."""
        return hashlib.sha256(Path(file_path).read_bytes()).hexdigest()

    def validate_research_brief(self, brief: Dict[str, Any]) -> bool:
        """Verify that research brief URLs and sources meet primary policy and safety rules."""
        sources = brief.get("sources", [])
        canonical_url = brief.get("canonical_url")

        all_urls = [canonical_url] if canonical_url else []
        for s in sources:
            if isinstance(s, dict) and s.get("url"):
                all_urls.append(s["url"])
            elif isinstance(s, str):
                all_urls.append(s)

        for u in all_urls:
            if not self.source_adapter.is_safe_url(u):
                raise ResearchValidationError(f"Disallowed or unsafe source URL: {u}")

        # Check for fake competitor padding
        competitors = brief.get("competitors", [])
        for comp in competitors:
            if isinstance(comp, dict):
                comp_url = comp.get("url", "")
                if comp_url.endswith(".invalid") or comp_url.endswith(".example") or "fake" in comp_url:
                    raise ResearchValidationError(f"Invalid or unverified competitor source: {comp_url}")

        return True

    def verify_script_claims(
        self,
        script_data: Dict[str, Any],
        claim_ledger: List[Dict[str, Any]],
        demo_results: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """Ensure narration claims do not assert firsthand testing without actual demo results."""
        has_verified_demo = bool(demo_results and demo_results.get("verified"))

        sections = script_data.get("sections", [])
        for sec in sections:
            narration = sec.get("narration", "")
            for pattern in self.FIRST_PERSON_TEST_PATTERNS:
                if pattern.search(narration) and not has_verified_demo:
                    match_phrase = pattern.search(narration).group(0)
                    return (
                        False,
                        f"Section {sec.get('section_id')} asserts first-person testing ('{match_phrase}') without verified demo_results",
                    )

        return True, ""

    def check_approval_validity(self, project_dir: Path) -> bool:
        """Check whether the approval signature is valid or invalidated by claim ledger mutations."""
        project_dir = Path(project_dir)
        app_file = project_dir / "approval.json"
        claims_file = project_dir / "artifacts" / "claim_ledger.json"

        if not app_file.is_file() or not claims_file.is_file():
            return False

        try:
            app_data = json.loads(app_file.read_text(encoding="utf-8"))
            if not app_data.get("approved"):
                return False

            recorded_sha = app_data.get("claim_ledger_sha256")
            if not recorded_sha:
                return False

            current_sha = self.compute_file_sha(claims_file)
            return recorded_sha.lower() == current_sha.lower()
        except Exception as e:
            logger.warning(f"Error checking approval validity: {e}")
            return False

    def build_topic_artifacts(
        self,
        candidate: Dict[str, Any],
        project_dir: Path,
        content_kind: str = "evergreen_explainer",
    ) -> Dict[str, Path]:
        """Build canonical and sidecar artifacts for a selected topic."""
        project_dir = Path(project_dir)
        artifacts_dir = project_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        cid = candidate.get("id") or candidate.get("candidate_id") or "cand_01"
        url = candidate.get("canonical_url") or candidate.get("url")
        title = candidate.get("title", "AI Agent Engineering Explainer")
        body = candidate.get("body") or candidate.get("summary") or ""
        publisher = candidate.get("publisher", "Official Documentation")
        published_at = candidate.get("published_at_utc") or candidate.get("published_at")

        # 1. Topic brief sidecar
        topic_brief = {
            "version": "1.0",
            "topic_id": cid,
            "title": title,
            "viewer_question": candidate.get("viewer_question") or f"Why does this agent mechanism fail: {title}?",
            "topic_family": candidate.get("topic_family", "context_memory"),
            "content_kind": content_kind,
            "primary_source_url": url,
            "publisher": publisher,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        topic_brief_path = artifacts_dir / "topic_brief.json"
        topic_brief_path.write_text(json.dumps(topic_brief, indent=2), encoding="utf-8")

        # 2. Claim ledger: Require verifiable ground truth, not automatic verified mark
        # Genuine snapshot provenance verification:
        # 1) Must have actual snapshot text or file on disk
        # 2) Must match snapshot_sha256 if recorded
        # 3) `verified_source: true` without snapshot is strictly rejected
        snap_content = candidate.get("source_snapshot")
        if not snap_content and candidate.get("source_snapshot_path"):
            cand_sp = Path(candidate["source_snapshot_path"])
            if cand_sp.is_file():
                snap_content = cand_sp.read_text(encoding="utf-8")

        symptom = candidate.get("symptom") or f"Observed failure symptom: {title}"
        root_cause = candidate.get("root_cause") or candidate.get("mechanism") or f"Architectural root cause in {candidate.get('topic_family', 'agent execution boundary')}"
        remedy = candidate.get("remedy") or candidate.get("fix") or "Actionable verification checklist for developers to confirm fix in their repo"

        has_verified_snapshot = False
        actual_snap_sha = None

        if snap_content and str(snap_content).strip():
            content_str = str(snap_content).strip()
            actual_snap_sha = hashlib.sha256(content_str.encode("utf-8")).hexdigest()
            recorded_sha = candidate.get("snapshot_sha256")

            # Check semantic grounding: snapshot must contain substantive terms from title or topic domain
            keywords = [
                w.lower() for w in re.findall(r"\b[a-zA-Z]{4,}\b", f"{title} {candidate.get('topic_family', '')} {symptom}")
                if w.lower() not in {"this", "that", "with", "from", "your", "what", "when", "where", "which"}
            ]
            content_lower = content_str.lower()
            domain_terms = (
                "context", "window", "agent", "state", "token", "prompt", "session",
                "model", "schema", "tool", "benchmark", "memory", "coding", "software",
                "developer", "llm", "pipeline", "execution", "boundary", "permission",
                "file", "persistence", "limits", "runtime", "failure", "debug",
            )
            grounded = len(content_str) >= 30 and (
                (bool(keywords) and any(kw in content_lower for kw in keywords))
                or any(term in content_lower for term in domain_terms)
            )

            if recorded_sha:
                if actual_snap_sha.lower() == str(recorded_sha).lower() and grounded:
                    has_verified_snapshot = True
                    (artifacts_dir / "source_snapshot.txt").write_text(content_str, encoding="utf-8")
                else:
                    logger.warning(
                        f"Snapshot validation failed for candidate {cid}: sha_match={actual_snap_sha.lower() == str(recorded_sha).lower()} grounded={grounded}"
                    )
            elif grounded:
                has_verified_snapshot = True
                (artifacts_dir / "source_snapshot.txt").write_text(content_str, encoding="utf-8")

        is_safe_primary = bool(url and self.source_adapter.is_safe_url(url))
        claim_confidence = "verified" if (is_safe_primary and has_verified_snapshot) else "unverified"
        claim_class = ClaimClassification.DOCUMENTED.value if (is_safe_primary and has_verified_snapshot) else ClaimClassification.INFERRED.value

        def _make_claim(claim_id: str, statement: str) -> Dict[str, Any]:
            c: Dict[str, Any] = {
                "claim_id": claim_id,
                "statement": statement,
                "confidence": claim_confidence,
                "classification": claim_class,
                "source": {
                    "canonical_url": url,
                    "publisher": publisher,
                    "published_at": published_at,
                },
            }
            if claim_id == "C001":
                c["scope"] = {"market": "US", "locale": "en-US"}
            if claim_confidence == "verified" and actual_snap_sha:
                c["snapshot_sha256"] = actual_snap_sha
                c["source_snapshot_path"] = "artifacts/source_snapshot.txt"
            return c

        claim_ledger = {
            "schema_version": "1.0",
            "project_id": cid,
            "locale": "en-US",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "claims": [
                _make_claim("C001", symptom),
                _make_claim("C002", root_cause),
                _make_claim("C003", remedy),
            ],
        }
        claim_ledger_path = artifacts_dir / "claim_ledger.json"
        claim_ledger_path.write_text(json.dumps(claim_ledger, indent=2), encoding="utf-8")

        # 3. Canonical research_brief
        research_brief = {
            "topic": title,
            "target_audience": "US software developers working with AI coding agents",
            "canonical_url": url,
            "claims": [c["statement"] for c in claim_ledger["claims"]],
            "sources": [
                {"url": url, "title": f"{publisher} Reference", "used_for": "Core technical mechanism"}
            ],
            "key_takeaways": [
                "Understand the session / boundary failure mode",
                "Apply the verified configuration or schema fix",
                "Verify with a reproducible unit test",
            ],
        }
        research_brief_path = artifacts_dir / "research_brief.json"
        research_brief_path.write_text(json.dumps(research_brief, indent=2), encoding="utf-8")

        return {
            "topic_brief": topic_brief_path,
            "claim_ledger": claim_ledger_path,
            "research_brief": research_brief_path,
        }
