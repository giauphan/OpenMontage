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

    def __init__(self, working_dir: Path):
        self.working_dir = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)

    def run_isolated_command(
        self,
        command: str,
        timeout_seconds: int = 15,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Run an isolated test command under strict timeout and environment recording."""
        # Security: sanitize environment to prevent leaking secrets/tokens
        allowed_keys = ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "COMSPEC")
        env = {k: os.environ[k] for k in allowed_keys if k in os.environ}
        env["HOME"] = str(self.working_dir)
        if env_vars:
            env.update(env_vars)

        env_signature = hashlib.sha256(
            f"{os.uname().sysname}|{os.uname().machine}|{command}".encode("utf-8")
        ).hexdigest()

        start_time = time.time()
        try:
            res = subprocess.run(
                command,
                shell=True,
                cwd=str(self.working_dir),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
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

        # 2. Claim ledger
        claim_confidence = "verified" if url else "unverified"
        claim_class = ClaimClassification.DOCUMENTED.value if url else ClaimClassification.INFERRED.value

        claim_ledger = {
            "schema_version": "1.0",
            "project_id": cid,
            "locale": "en-US",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "claims": [
                {
                    "claim_id": "C001",
                    "statement": f"Observed failure symptom: {title}",
                    "confidence": claim_confidence,
                    "classification": claim_class,
                    "scope": {"market": "US", "locale": "en-US"},
                    "source": {
                        "canonical_url": url,
                        "publisher": publisher,
                        "published_at": published_at,
                    },
                },
                {
                    "claim_id": "C002",
                    "statement": "Architectural root cause in agent session or tool execution boundary",
                    "confidence": claim_confidence,
                    "classification": claim_class,
                    "source": {
                        "canonical_url": url,
                        "publisher": publisher,
                        "published_at": published_at,
                    },
                },
                {
                    "claim_id": "C003",
                    "statement": "Actionable verification checklist for developers to confirm fix in their repo",
                    "confidence": claim_confidence,
                    "classification": claim_class,
                    "source": {
                        "canonical_url": url,
                        "publisher": publisher,
                        "published_at": published_at,
                    },
                },
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
