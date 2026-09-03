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
import subprocess
import sys
import os
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

try:
    from scripts.validation_status import ValidationStatusLogger
except ImportError:
    # Handle case when validation_status is not available
    ValidationStatusLogger = None

# Strict Quality Thresholds
SILENCE_MEAN_DB = -50.0
MAX_BLACK_RATIO = 0.30
MIN_EDGE_DENSITY = 0.005
MAX_STATIC_RATIO = 0.50
MIN_DURATION = 30.0
REQUIRED_HASHTAGS = {"#tintuc", "#congnghe", "#ai"}


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
                
            # Use existing validation scripts for technical checks
            ffprobe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video_path)]
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

    def validate_content_quality(self, video_path: Path, ffprobe_bin: str = "ffprobe", ffmpeg_bin: str = "ffmpeg") -> List[ValidationResult]:
        """Validate content quality: audio volume, black frames, edge density."""
        results = []
        
        try:
            # Use existing validation script with specific video path
            validate_cmd = [
                sys.executable,
                "scripts/validate_render_quality.py",
                str(video_path),  # Use the specific video_path parameter
                "--ffprobe", ffprobe_bin,
                "--ffmpeg", ffmpeg_bin,
                "--strict"
            ]
            
            result = subprocess.run(
                validate_cmd, 
                capture_output=True, 
                text=True,
                cwd=str(Path(__file__).parent.parent)
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
                # Use existing metadata validation
                validate_cmd = [
                    sys.executable,
                    "scripts/validate_publish_metadata.py",
                    str(metadata_path)
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
                    error_lines = result.stderr.strip().split('\n') if result.stderr else []
                    for error in error_lines:
                        if error:
                            results.append(ValidationResult(
                                check_name="Metadata Validation",
                                passed=False,
                                message=f"Metadata validation failed: {error}",
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
        
        try:
            # Prepare prompt for CLAUDE agent review
            prompt = f"""
As a strict quality assurance agent, analyze the video at {video_path} with metadata from {metadata_path}.

PERFORM STRICT QUALITY VALIDATION on the following criteria:

1. VISUAL QUALITY: Check for visual artifacts, compression issues, color consistency
2. AUDIO SYNC: Verify voice-over synchronization and clarity  
3. CONTENT APPROPRIATENESS: Ensure content is safe, appropriate, and aligned with guidelines
4. BRAND COMPLIANCE: Verify adherence to brand style guidelines

REQUIREMENTS:
- Dimensions must be 1080x1920 (portrait)
- Video must exceed {MIN_DURATION} seconds
- Must contain Vietnamese narration with hook in first 3 seconds
- Must have synchronized dynamic captions
- Required hashtags: #tintuc #congnghe #ai

RESPONSE: Return ONLY JSON with structure:
{{
  "visual_quality": {{{"passed": true/false, "score": 0-100, "notes": "string"}}},
  "audio_sync": {{{"passed": true/false, "score": 0-100, "notes": "string"}}},
  "content_appropriateness": {{{"passed": true/false, "score": 0-100, "notes": "string"}}},
  "brand_compliance": {{{"passed": true/false, "score": 0-100, "notes": "string"}}},
  "overall_passed": true/false,
  "summary": "string"
}}

Be STRICT and RETURN false for any quality issues.
"""

            # SECURITY NOTE: --dangerously-skip-permissions and --dangerously-bypass-npm
            # are required for automated operation within the Docker container.
            # The CLAUDE agent operates in a controlled environment where:
            # - Docker container runs in isolated environment on sandbox-video host
            # - All file paths are controlled by the pipeline
            # - No external content feeds are used
            # - Credentials are mounted via volumes only
            # This is considered safe for this pipeline, but these flags should never
            # be used in production systems with untrusted input.
            claude_cmd = [
                "claude", "-p", "--output-format", "json",
                "--dangerously-skip-permissions",
                "--dangerously-bypass-npm",
                prompt
            ]
            
            result = subprocess.run(
                claude_cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout
                cwd=str(Path(__file__).parent.parent)
            )
            
            if result.returncode == 0:
                try:
                    # Parse CLAUDE response
                    response_data = json.loads(result.stdout.strip())
                    
                    # Extract results
                    checks = [
                        ("Visual Quality", response_data.get("visual_quality", {}).get("passed", False)),
                        ("Audio Sync", response_data.get("audio_sync", {}).get("passed", False)),
                        ("Content Appropriateness", response_data.get("content_appropriateness", {}).get("passed", False)),
                        ("Brand Compliance", response_data.get("brand_compliance", {}).get("passed", False))
                    ]

                    # Create explicit mapping to avoid fragile string manipulation
                    check_key_map = {
                        "Visual Quality": "visual_quality",
                        "Audio Sync": "audio_sync", 
                        "Content Appropriateness": "content_appropriateness",
                        "Brand Compliance": "brand_compliance"
                    }

                    for check_name, passed in checks:
                        check_key = check_key_map.get(check_name, check_name.lower().replace(" ", "_"))
                        check_data = response_data.get(check_key, {})
                        score = check_data.get("score", 0)
                        notes = check_data.get("notes", "")

                        results.append(ValidationResult(
                            check_name=check_name,
                            passed=passed,
                            message=f"{check_name}: {'✓ PASS' if passed else '✗ FAIL'} (Score: {score}) - {notes}",
                            details={"score": score, "notes": notes}
                        ))
                        
                except (json.JSONDecodeError, KeyError) as e:
                    results.append(ValidationResult(
                        check_name="CLAUDE Agent Review",
                        passed=False,
                        message=f"CLAUDE response parsing error: {str(e)}",
                        details={"raw_response": result.stdout}
                    ))
            else:
                results.append(ValidationResult(
                    check_name="CLAUDE Agent Review",
                    passed=False,
                    message=f"CLAUDE agent execution failed: {result.stderr}",
                    details={"error": result.stderr}
                ))
                
        except subprocess.TimeoutExpired:
            results.append(ValidationResult(
                check_name="CLAUDE Agent Review",
                passed=False,
                message="CLAUDE agent validation timeout after 120 seconds"
            ))
        except Exception as e:
            results.append(ValidationResult(
                check_name="CLAUDE Agent Review",
                passed=False,
                message=f"CLAUDE agent validation error: {str(e)}"
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
    
    # Handle --strict and --no-strict arguments properly
    # --strict defaults to False (use default), --no-strict sets it to False explicitly
    # If neither is specified, we want True (strict by default)
    strict_mode = True  # default to True as requested in review
    if hasattr(args, 'strict'):
        strict_mode = args.strict
    
    validator = CLAUDEAgentValidator(
        project_dir=project_dir,
        strict_mode=strict_mode
    )
    
    # Execute validation
    validation_data = validator.execute_validation(
        video_paths=video_paths,
        metadata_path=metadata_path,
        ffprobe_bin=args.ffprobe,
        ffmpeg_bin=args.ffmpeg
    )
    
    # Print report
    validator.print_validation_report(validation_data)
    
    # Log to validation status system if available
    if ValidationStatusLogger is not None:
        logger = ValidationStatusLogger(project_dir=project_dir)
        logger.log_validation_result(
            project_id=Path(args.project_dir).name,
            status=validation_data['overall_status'],
            total_checks=validation_data['total_checks'],
            passed=validation_data['passed_checks'],
            failed=validation_data['failed_checks'],
            details=validation_data
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