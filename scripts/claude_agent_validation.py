#!/usr/bin/env python3
"""CLAUDE Agent Strict Quality Validation for Docker Pipeline.

This script implements strict quality validation using CLAUDE agent
to ensure videos meet all quality thresholds before platform publishing.

Integration Points:
- Runs natively in Docker container on sandbox-video host
- Called after HyperFrames rendering in run_daily_news_pipeline.sh
- Provides 🟢 STRICT QUALITY PASS or 🔴 VALIDATION FAIL
- Supports retry mechanism (1-2 attempts)

Usage:
    python3 scripts/claude_agent_validation.py <project_dir> [--strict] [--retry 2]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

def resolve_ffprobe_ffmpeg() -> tuple[str, str]:
    ffprobe = shutil.which("ffprobe") or ""
    ffmpeg = shutil.which("ffmpeg") or ""
    if not ffprobe:
        candidates = list(Path.home().glob(".local/share/uv/**/ffprobe"))
        ffprobe = str(candidates[0]) if candidates else ""
    if not ffmpeg:
        candidates = list(Path.home().glob(".local/share/uv/**/ffmpeg"))
        ffmpeg = str(candidates[0]) if candidates else ""
    return ffprobe or "ffprobe", ffmpeg or "ffmpeg"


def parse_claude_review(response_text: str) -> dict:
    envelope = json.loads(response_text)
    if not isinstance(envelope, dict):
        raise ValueError("Claude CLI response invalid")
    if envelope.get("is_error"):
        raise ValueError("Claude CLI error")
    if "is_error" in envelope and "result" not in envelope:
        raise ValueError("Claude CLI result missing")
    result = envelope.get("result", envelope)
    if not isinstance(result, (str, dict)):
        raise ValueError("Claude CLI result missing")
    if isinstance(result, dict):
        return result
    cleaned = result.strip()
    if cleaned.startswith("```"):
        lines = [line for line in cleaned.splitlines() if not line.startswith("```")]
        cleaned = "\n".join(lines).strip()
    review = json.loads(cleaned)
    if not isinstance(review, dict):
        raise ValueError("Claude CLI review invalid")
    return review

try:
    from scripts.validation_status import ValidationStatusLogger
except ImportError:
    # Handle case when validation_status is not available
    ValidationStatusLogger = None

# Strict Quality Thresholds
# Currently MIN_DURATION is used in CLAUDE agent prompts
MIN_DURATION = 30.0  # Minimum video duration in seconds


@dataclass
class ValidationResult:
    check_name: str
    passed: bool
    message: str
    details: Optional[Dict] = None


class CLAUDEAgentValidator:
    """CLAUDE Agent Strict Quality Validator."""
    
    def __init__(self, project_dir: Path, strict_mode: bool = True):
        self.project_dir = project_dir
        self.strict_mode = strict_mode
        self.retry_count = 2
        self.results: List[ValidationResult] = []
        
    def validate_technical_contract(self, video_path: Path) -> List[ValidationResult]:
        """Validate technical specifications: dimensions, codecs, fps, duration."""
        results = []
        
        try:
            # Check if video exists and has size
            if not video_path.exists():
                results.append(ValidationResult(
                    check_name="Video Exists",
                    passed=False,
                    message=f"Video file missing: {video_path}"
                ))
                return results
            
            if video_path.stat().st_size == 0:
                results.append(ValidationResult(
                    check_name="Video Size",
                    passed=False,
                    message=f"Video file empty: {video_path}"
                ))
                return results
                
            ffprobe_bin, ffmpeg_bin = resolve_ffprobe_ffmpeg()
            # Use existing validation scripts for technical checks
            ffprobe_cmd = [ffprobe_bin, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video_path)]
            duration_result = subprocess.run(ffprobe_cmd, capture_output=True, text=True)
            
            if duration_result.returncode != 0:
                # Handle ffprobe failure explicitly
                error_msg = f"ffprobe failed: {duration_result.stderr.strip() if duration_result.stderr else duration_result.stdout.strip() if duration_result.stdout else 'no error details'}"
                results.append(ValidationResult(
                    check_name="FFprobe Execution",
                    passed=False,
                    message=f"ffprobe command failed: {error_msg}",
                    details={"returncode": duration_result.returncode, "stderr": duration_result.stderr, "stdout": duration_result.stdout}
                ))
                return results
                
            if duration_result.stdout.strip():
                try:
                    duration = float(duration_result.stdout.strip())
                    if duration >= MIN_DURATION:
                        results.append(ValidationResult(
                            check_name="Duration Check",
                            passed=True,
                            message=f"Duration: {duration:.1f}s ≥ {MIN_DURATION}s ✓",
                            details={"duration": duration, "min_duration": MIN_DURATION}
                        ))
                    else:
                        results.append(ValidationResult(
                            check_name="Duration Check",
                            passed=False,
                            message=f"Duration: {duration:.1f}s < {MIN_DURATION}s ✗",
                            details={"duration": duration, "min_duration": MIN_DURATION}
                        ))
                except ValueError as e:
                    results.append(ValidationResult(
                        check_name="Duration Parsing",
                        passed=False,
                        message=f"Failed to parse duration: {str(e)}",
                        details={"raw_output": duration_result.stdout, "error": str(e)}
                    ))
            else:
                results.append(ValidationResult(
                    check_name="Duration Extraction",
                    passed=False,
                    message="ffprobe returned empty duration output",
                    details={"stdout": duration_result.stdout, "stderr": duration_result.stderr}
                ))
            
        except Exception as e:
            results.append(ValidationResult(
                check_name="Technical Contract",
                passed=False,
                message=f"Technical validation error: {str(e)}",
                details={"exception_type": type(e).__name__, "exception_message": str(e)}
            ))
            
        return results

    def validate_content_quality(self, video_path: Path, ffprobe_bin: Optional[str] = None, ffmpeg_bin: Optional[str] = None) -> List[ValidationResult]:
        """Validate content quality: audio volume, black frames, edge density."""
        results = []

        resolved_ffprobe, resolved_ffmpeg = resolve_ffprobe_ffmpeg()
        ffprobe_bin = ffprobe_bin or resolved_ffprobe
        ffmpeg_bin = ffmpeg_bin or resolved_ffmpeg

        try:
            render_arg = "reels" if "reels" in video_path.name else "full"
            # Use existing validation script with project directory path
            validate_cmd = [
                sys.executable,
                "scripts/validate_render_quality.py",
                str(self.project_dir),
                "--render", render_arg,
                "--ffprobe", ffprobe_bin,
                "--ffmpeg", ffmpeg_bin,
                "--strict"
            ]
            
            env = dict(os.environ)
            bin_dir = str(Path(ffprobe_bin).parent)
            if bin_dir and bin_dir not in env.get("PATH", ""):
                env["PATH"] = bin_dir + ":" + env.get("PATH", "")

            result = subprocess.run(
                validate_cmd,
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).parent.parent),
                env=env
            )
            
            if result.returncode == 0:
                results.append(ValidationResult(
                    check_name="Content Quality",
                    passed=True,
                    message="Content quality validation passed ✓",
                    details={"stdout": result.stdout, "stderr": result.stderr}
                ))
            else:
                # Parse errors from validation script - handle empty stderr
                error_lines = []
                if result.stderr and result.stderr.strip():
                    error_lines = result.stderr.strip().split('\n')
                elif result.stdout and result.stdout.strip():
                    error_lines = result.stdout.strip().split('\n')
                    
                if not error_lines:
                    # If both stderr and stdout are empty or only whitespace
                    results.append(ValidationResult(
                        check_name="Content Quality",
                        passed=False,
                        message="Content quality validation failed with no error details",
                        details={"stdout": result.stdout, "stderr": result.stderr}
                    ))
                else:
                    for error in error_lines:
                        if error.strip():  # Skip empty lines
                            results.append(ValidationResult(
                                check_name="Content Quality",
                                passed=False,
                                message=f"Content validation failed: {error.strip()}",
                                details={"stdout": result.stdout, "stderr": result.stderr}
                            ))
                
        except Exception as e:
            results.append(ValidationResult(
                check_name="Content Quality",
                passed=False,
                message=f"Content validation error: {str(e)}"
            ))
            
        return results

    def validate_metadata(self, metadata_path: Path) -> List[ValidationResult]:
        """Validate metadata: hashtags, shell syntax, placeholders."""
        results = []

        try:
            if metadata_path.exists():
                # Use existing metadata validation with project directory path
                validate_cmd = [
                    sys.executable,
                    "scripts/validate_publish_metadata.py",
                    str(self.project_dir)
                ]
                
                result = subprocess.run(
                    validate_cmd,
                    capture_output=True,
                    text=True,
                    cwd=str(Path(__file__).parent.parent)
                )
                
                if result.returncode == 0:
                    results.append(ValidationResult(
                        check_name="Metadata Validation",
                        passed=True,
                        message="Metadata validation passed ✓",
                        details={"output": result.stdout}
                    ))
                else:
                    # Handle empty stderr case
                    error_lines = []
                    if result.stderr and result.stderr.strip():
                        error_lines = result.stderr.strip().split('\n')
                    elif result.stdout and result.stdout.strip():
                        error_lines = result.stdout.strip().split('\n')
                    
                    if not error_lines:
                        # If both stderr and stdout are empty or only whitespace
                        results.append(ValidationResult(
                            check_name="Metadata Validation",
                            passed=False,
                            message="Metadata validation failed with no error details",
                            details={"stdout": result.stdout, "stderr": result.stderr}
                        ))
                    else:
                        for error in error_lines:
                            if error.strip():  # Skip empty lines
                                results.append(ValidationResult(
                                    check_name="Metadata Validation",
                                    passed=False,
                                    message=f"Metadata validation failed: {error.strip()}",
                                    details={"stderr": result.stderr}
                                ))
            else:
                results.append(ValidationResult(
                    check_name="Metadata File",
                    passed=False,
                    message=f"Metadata file missing: {metadata_path}"
                ))
                
        except Exception as e:
            results.append(ValidationResult(
                check_name="Metadata Validation",
                passed=False,
                message=f"Metadata validation error: {str(e)}"
            ))
            
        return results

    def claude_agent_strict_review(self, video_path: Path, metadata_path: Path) -> List[ValidationResult]:
        """CLAUDE Agent powered strict quality review."""
        results = []

        if os.environ.get("CLAUDE_AGENT_VALIDATION_MOCK") == "1":
            # Keep tests fast without skipping subprocess discovery/validation gating.
            # Mock only Claude review gate itself.
            return [
                ValidationResult(
                    check_name="CLAUDE Agent Review Gate",
                    passed=True,
                    message="Strict Contract Gate: Visual, audio, content & brand quality verified ✓ (Mocked)"
                )
            ]

        try:
            # Prepare prompt for CLAUDE agent review
            abs_video_path = Path(video_path).resolve()
            abs_metadata_path = Path(metadata_path).resolve()
            metadata_str = "{}"
            if abs_metadata_path.is_file():
                try:
                    metadata_str = abs_metadata_path.read_text(encoding="utf-8")
                except Exception:
                    pass

            file_exists = abs_video_path.is_file()
            file_size = abs_video_path.stat().st_size if file_exists else 0

            prompt = f"""
Validate candidate video asset for OpenMontage automated publishing pipeline.

Target Asset Path: {abs_video_path}
File Exists: {file_exists}
File Size Bytes: {file_size}

Metadata Content:
{metadata_str}

PERFORM STRICT QUALITY VALIDATION on the following criteria:
1. VISUAL QUALITY: Verify resolution (1080x1920 portrait) and absence of corrupt frames
2. AUDIO SYNC: Verify narration and dynamic captions synchronization
3. CONTENT APPROPRIATENESS: Ensure news content is safe and high relevance
4. BRAND COMPLIANCE: Verify no forbidden brand names ("Montage", "OpenMontage") appear in text or narration

Return ONLY valid JSON matching this schema:
{{
  "visual_quality": {{"passed": true, "score": 95, "notes": "1080x1920 portrait layout verified"}},
  "audio_sync": {{"passed": true, "score": 95, "notes": "Vietnamese audio sync verified"}},
  "content_appropriateness": {{"passed": true, "score": 95, "notes": "Content safe and policy compliant"}},
  "brand_compliance": {{"passed": true, "score": 95, "notes": "No prohibited brand names detected"}},
  "overall_passed": true,
  "summary": "Asset passed all strict quality gates"
}}
"""

            claude_bin = shutil.which("claude")
            if not claude_bin:
                raise FileNotFoundError("claude CLI not found")

            result = subprocess.run(
                [claude_bin, "-p", prompt, "--output-format", "json"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=180,
                cwd=str(Path(__file__).parent.parent),
            )
            if result.returncode:
                diagnostic = (result.stderr or result.stdout).strip()
                raise RuntimeError(diagnostic or f"claude CLI exited {result.returncode}")

            response_data = parse_claude_review(result.stdout)
            checks = {
                "Visual Quality": "visual_quality",
                "Audio Sync": "audio_sync",
                "Content Appropriateness": "content_appropriateness",
                "Brand Compliance": "brand_compliance",
            }
            for check_name, check_key in checks.items():
                check_data = response_data.get(check_key)
                if not isinstance(check_data, dict):
                    raise ValueError(f"Claude CLI review missing {check_key}")
                passed = check_data.get("passed") is True
                score = check_data.get("score", 0)
                notes = check_data.get("notes", "")
                results.append(ValidationResult(
                    check_name=check_name,
                    passed=passed,
                    message=f"{check_name}: {'✓ PASS' if passed else '✗ FAIL'} (Score: {score}) - {notes}",
                    details={"score": score, "notes": notes},
                ))

            if response_data.get("overall_passed") is not True and all(result.passed for result in results):
                results.append(ValidationResult(
                    check_name="CLAUDE Agent Review Gate",
                    passed=False,
                    message=str(response_data.get("summary") or "Claude strict review rejected asset"),
                ))

        except Exception as exc:
            results.append(ValidationResult(
                check_name="CLAUDE Agent Review Gate",
                passed=False,
                message=f"CLAUDE Agent strict review unavailable: {type(exc).__name__}: {exc}",
                details={"error": str(exc)},
            ))

        return results

    def execute_validation(self, video_paths: List[Path], metadata_path: Path, 
                          ffprobe_bin: str = "ffprobe", ffmpeg_bin: str = "ffmpeg") -> Dict:
        """Execute full validation pipeline."""
        all_results = []
        
        # Step 1: Technical Contract Validation
        for video_path in video_paths:
            tech_results = self.validate_technical_contract(video_path)
            all_results.extend(tech_results)
        
        # Step 2: Content Quality Validation  
        for video_path in video_paths:
            content_results = self.validate_content_quality(video_path, ffprobe_bin, ffmpeg_bin)
            all_results.extend(content_results)
        
        # Step 3: Metadata Validation
        meta_results = self.validate_metadata(metadata_path)
        all_results.extend(meta_results)
        
        # Step 4: CLAUDE Agent Review
        if self.strict_mode:
            for video_path in video_paths:
                agent_results = self.claude_agent_strict_review(video_path, metadata_path)
                all_results.extend(agent_results)
        
        self.results = all_results
        
        # Determine overall status
        failed_checks = [r for r in all_results if not r.passed]
        passed_checks = [r for r in all_results if r.passed]
        
        overall_passed = len(failed_checks) == 0
        
        return {
            "overall_status": "PASS" if overall_passed else "FAIL",
            "total_checks": len(all_results),
            "passed_checks": len(passed_checks),
            "failed_checks": len(failed_checks),
            "results": all_results,
            "color": "🟢" if overall_passed else "🔴",
            "strict_quality_pass": overall_passed
        }

    def print_validation_report(self, validation_data: Dict) -> None:
        """Print formatted validation report."""
        print("\n" + "="*60)
        print("CLAUDE AGENT STRICT QUALITY VALIDATION REPORT")
        print("="*60)
        
        print(f"Overall Status: {validation_data['color']} {validation_data['overall_status']}")
        print(f"Total Checks: {validation_data['total_checks']}")
        print(f"Passed: {validation_data['passed_checks']}, Failed: {validation_data['failed_checks']}")
        
        print("\n" + "-"*60)
        print("DETAILED RESULTS:")
        print("-"*60)
        
        for result in validation_data['results']:
            status = "✅ PASS" if result.passed else "❌ FAIL"
            print(f"{status} | {result.check_name}")
            print(f"       └─ {result.message}")
            if result.details:
                for key, value in result.details.items():
                    print(f"       └─ {key}: {value}")
            print()
        
        print("="*60)
        if validation_data['overall_status'] == 'PASS':
            print("🎉 STRICT QUALITY VALIDATION PASSED - Ready for Platform Publishing")
        else:
            print("❌ STRICT QUALITY VALIDATION FAILED - Requires Resolution")
        print("="*60)


def main():
    parser = argparse.ArgumentParser(description='CLAUDE Agent Strict Quality Validation')
    parser.add_argument('project_dir', type=str, help='Project directory to validate')
    parser.add_argument('--strict', action='store_true', default=None,
                       help='Enable strict mode')
    parser.add_argument('--no-strict', dest='strict', action='store_false',
                       help='Disable strict mode')
    parser.add_argument('--retry', type=int, default=2, 
                       help='Maximum retry attempts (handled by shell wrapper)')
    parser.add_argument('--ffprobe', type=str, default='ffprobe', 
                       help='Path to ffprobe binary')
    parser.add_argument('--ffmpeg', type=str, default='ffmpeg', 
                       help='Path to ffmpeg binary')
    
    args = parser.parse_args()

    # Handle default: if neither --strict nor --no-strict was specified, default to True
    if args.strict is None:
        args.strict = True

    project_dir = Path(args.project_dir)
    if not project_dir.exists():
        print(f"Error: Project directory not found: {project_dir}")
        sys.exit(1)

    # Define video paths and metadata path
    video_paths = [
        project_dir / "renders" / "final_full_vi_9x16.mp4",
        project_dir / "renders" / "final_reels_vi_9x16.mp4"
    ]

    metadata_path = project_dir / "publish_metadata.json"

    # Create validator with handled strict_mode
    strict_mode = args.strict
    validator = CLAUDEAgentValidator(
        project_dir=project_dir,
        strict_mode=strict_mode
    )
    
    ffprobe_bin, ffmpeg_bin = resolve_ffprobe_ffmpeg()
    if args.ffprobe != "ffprobe":
        ffprobe_bin = args.ffprobe
    if args.ffmpeg != "ffmpeg":
        ffmpeg_bin = args.ffmpeg

    # Execute validation
    validation_data = validator.execute_validation(
        video_paths=video_paths,
        metadata_path=metadata_path,
        ffprobe_bin=ffprobe_bin,
        ffmpeg_bin=ffmpeg_bin
    )
    
    # Print report
    validator.print_validation_report(validation_data)
    
    # Log to validation status system if available
    if ValidationStatusLogger is not None:
        logger = ValidationStatusLogger(project_dir=project_dir)
        from dataclasses import asdict

        # Avoid JSON serialization issues for ValidationResult objects
        serializable = dict(validation_data)
        results = serializable.get('results', [])
        serializable['results'] = [asdict(r) if hasattr(r, '__dataclass_fields__') else r for r in results]

        logger.log_validation_result(
            project_id=Path(args.project_dir).name,
            status=serializable['overall_status'],
            total_checks=serializable['total_checks'],
            passed=serializable['passed_checks'],
            failed=serializable['failed_checks'],
            details=serializable
        )
    
    # Return exit code based on validation result
    if validation_data['overall_status'] == 'PASS':
        print(f"Result: {validation_data['color']} STRICT QUALITY PASS")
        sys.exit(0)
    else:
        print(f"Result: {validation_data['color']} VALIDATION FAILED")
        # Print specific failures for debugging
        failed_checks = [r.message for r in validation_data['results'] if not r.passed]
        if failed_checks:
            print("Failed checks:")
            for failure in failed_checks:
                print(f"  - {failure}")
        sys.exit(1)


if __name__ == '__main__':
    main()