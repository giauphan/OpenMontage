#!/usr/bin/env python3
"""
Full publish pipeline: Generate, validate, and publish videos for today and next day with strict CLAUDE agent validation.

This script orchestrates the complete video production and publishing pipeline:
1. Run daily news pipeline (generation + rendering)
2. Apply strict CLAUDE agent validation
3. Publish to platforms for today and next day
4. Monitor and report status

Usage:
    python3 scripts/run_full_publish_pipeline.py [--strict] [--today-only] [--next-day-only] [--dry-run]

Options:
    --strict        Enable mandatory CLAUDE agent strict validation (default: True)
    --today-only    Only publish for today's date
    --next-day-only Only publish for next day's date
    --dry-run       Validate and prepare but don't actually publish
    --force         Bypass validation failures (dangerous)
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = ROOT / "scripts"

class PipelineError(Exception):
    """Pipeline execution error"""
    pass

class FullPublishPipeline:
    """Full video production and publishing pipeline"""

    def __init__(self, strict: bool = True, dry_run: bool = False, force: bool = False):
        self.strict = strict
        self.dry_run = dry_run
        self.force = force
        self.start_time = datetime.now()

        # Validate required scripts exist
        self.required_scripts = [
            "run_daily_news_pipeline.sh",
            "schedule_youtube_today.py",
            "claude_agent_validation.py"
        ]
        self._validate_dependencies()

    def _validate_dependencies(self):
        """Ensure all required scripts exist"""
        missing = []
        for script in self.required_scripts:
            script_path = SCRIPTS_DIR / script
            if not script_path.exists():
                missing.append(str(script_path))

        if missing:
            raise PipelineError(f"Missing required scripts: {', '.join(missing)}")

    def _run_command(self, cmd: List[str], description: str,
                     cwd: Optional[Path] = None, timeout: int = 3600) -> Tuple[int, str, str]:
        """Run command and return (exit_code, stdout, stderr)"""
        logger.info(f"Running: {description}")
        logger.debug(f"Command: {' '.join(cmd)}")

        if self.dry_run:
            logger.info(f"DRY RUN: Would execute {description}")
            return 0, "DRY RUN - command not executed", ""

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd or ROOT,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            if result.stdout:
                logger.debug(f"STDOUT: {result.stdout}")
            if result.stderr:
                logger.debug(f"STDERR: {result.stderr}")

            return result.returncode, result.stdout, result.stderr

        except subprocess.TimeoutExpired:
            error_msg = f"Command timed out after {timeout}s: {description}"
            logger.error(error_msg)
            raise PipelineError(error_msg)
        except Exception as e:
            error_msg = f"Command failed: {description} - {str(e)}"
            logger.error(error_msg)
            raise PipelineError(error_msg)

    def run_daily_pipeline(self) -> bool:
        """Run the daily news pipeline (generation + rendering)"""
        logger.info("🎬 Starting daily news pipeline...")

        pipeline_script = SCRIPTS_DIR / "run_daily_news_pipeline.sh"
        cmd = ["bash", str(pipeline_script)]

        exit_code, stdout, stderr = self._run_command(
            cmd,
            "Daily news pipeline execution",
            timeout=7200  # 2 hour timeout
        )

        if exit_code != 0:
            error_msg = f"Daily pipeline failed with exit code {exit_code}"
            if stderr:
                error_msg += f": {stderr}"
            logger.error(error_msg)
            if not self.force:
                raise PipelineError(error_msg)
            logger.warning("Continuing despite pipeline failure due to --force flag")

        logger.info("✅ Daily news pipeline completed successfully")
        return True

    def validate_projects_strict(self) -> Dict[str, bool]:
        """Run strict CLAUDE agent validation on all projects"""
        logger.info("🔍 Running strict CLAUDE agent validation...")

        # Get active projects from config
        config_path = ROOT / "config" / "publish_schedule.json"
        if not config_path.exists():
            raise PipelineError(f"Publish schedule config not found: {config_path}")

        with open(config_path) as f:
            config = json.load(f)

        active_projects = config.get("active_projects", [])
        if not active_projects:
            logger.warning("No active projects found in publish schedule")
            return {}

        validation_results = {}

        for project_info in active_projects:
            project_id = project_info["project_id"]
            project_path = ROOT / "projects" / project_id

            logger.info(f"Validating project: {project_id}")

            if not project_path.exists():
                logger.error(f"Project directory not found: {project_path}")
                validation_results[project_id] = False
                continue

            # Run CLAUDE agent strict validation
            validation_script = SCRIPTS_DIR / "claude_agent_validation.py"
            cmd = ["python3", str(validation_script), str(project_path)]

            if self.strict:
                cmd.append("--strict")

            exit_code, stdout, stderr = self._run_command(
                cmd,
                f"CLAUDE validation for {project_id}",
                timeout=600  # 10 minute timeout per project
            )

            if exit_code == 0:
                logger.info(f"✅ Project {project_id} passed strict validation")
                validation_results[project_id] = True
            else:
                logger.error(f"❌ Project {project_id} failed strict validation")
                if stderr:
                    logger.error(f"Validation error: {stderr}")
                validation_results[project_id] = False

        # Summary
        passed = sum(validation_results.values())
        total = len(validation_results)
        logger.info(f"Validation summary: {passed}/{total} projects passed")

        if passed < total and not self.force:
            failed_projects = [pid for pid, passed in validation_results.items() if not passed]
            raise PipelineError(
                f"Strict validation failed for projects: {', '.join(failed_projects)}"
            )

        return validation_results

    def publish_for_date(self, target_date: str, date_label: str) -> bool:
        """Publish videos for a specific date"""
        logger.info(f"📤 Publishing videos for {date_label} ({target_date})...")

        scheduler_script = SCRIPTS_DIR / "schedule_youtube_today.py"
        cmd = ["python3", str(scheduler_script), target_date]

        if self.strict:
            cmd.append("--strict")

        exit_code, stdout, stderr = self._run_command(
            cmd,
            f"YouTube scheduling for {date_label}",
            timeout=1200  # 20 minute timeout
        )

        if exit_code != 0:
            error_msg = f"Publishing failed for {date_label} with exit code {exit_code}"
            if stderr:
                error_msg += f": {stderr}"
            logger.error(error_msg)
            if not self.force:
                raise PipelineError(error_msg)
            logger.warning(f"Continuing despite publishing failure for {date_label}")

        logger.info(f"✅ Successfully published videos for {date_label}")
        return True

    def run_full_pipeline(self, today_only: bool = False, next_day_only: bool = False) -> Dict[str, any]:
        """Execute the complete pipeline"""
        results = {
            "start_time": self.start_time.isoformat(),
            "pipeline_success": False,
            "validation_results": {},
            "publish_results": {},
            "errors": []
        }

        try:
            # Step 1: Run daily pipeline (unless publishing only)
            if not (today_only or next_day_only):
                results["pipeline_success"] = self.run_daily_pipeline()
            else:
                logger.info("Skipping daily pipeline - using existing projects")
                results["pipeline_success"] = True

            # Step 2: Strict validation
            if self.strict:
                results["validation_results"] = self.validate_projects_strict()
            else:
                logger.info("Skipping strict validation (--strict not enabled)")
                results["validation_results"] = {"skipped": True}

            # Step 3: Publishing
            today = datetime.now().strftime("%Y-%m-%d")
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

            if not next_day_only:
                try:
                    results["publish_results"]["today"] = self.publish_for_date(today, "today")
                except Exception as e:
                    results["publish_results"]["today"] = False
                    results["errors"].append(f"Today publishing failed: {str(e)}")

            if not today_only:
                try:
                    results["publish_results"]["tomorrow"] = self.publish_for_date(tomorrow, "tomorrow")
                except Exception as e:
                    results["publish_results"]["tomorrow"] = False
                    results["errors"].append(f"Tomorrow publishing failed: {str(e)}")

            # Success if at least one publish succeeded
            publish_success = any(results["publish_results"].values())

            if publish_success:
                logger.info("🎉 Full publish pipeline completed successfully!")
            else:
                logger.error("❌ Full publish pipeline failed - no successful publishes")

        except Exception as e:
            logger.error(f"Pipeline failed: {str(e)}")
            results["errors"].append(str(e))

        # Add timing info
        results["end_time"] = datetime.now().isoformat()
        results["duration_seconds"] = (datetime.now() - self.start_time).total_seconds()

        return results

def main():
    parser = argparse.ArgumentParser(
        description="Full video production and publishing pipeline with strict validation"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=True,
        help="Enable mandatory CLAUDE agent strict validation (default: True)"
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="Disable strict validation"
    )
    parser.add_argument(
        "--today-only",
        action="store_true",
        help="Only publish for today's date"
    )
    parser.add_argument(
        "--next-day-only",
        action="store_true",
        help="Only publish for next day's date"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and prepare but don't actually publish"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass validation failures (dangerous)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Resolve strict setting
    strict = args.strict and not args.no_strict

    if args.today_only and args.next_day_only:
        logger.error("Cannot specify both --today-only and --next-day-only")
        sys.exit(1)

    if args.dry_run:
        logger.info("🧪 Running in DRY RUN mode - no actual changes will be made")

    if args.force:
        logger.warning("⚠️  Running with --force - validation failures will be bypassed")

    # Execute pipeline
    pipeline = FullPublishPipeline(
        strict=strict,
        dry_run=args.dry_run,
        force=args.force
    )

    try:
        results = pipeline.run_full_pipeline(
            today_only=args.today_only,
            next_day_only=args.next_day_only
        )

        # Print summary
        print("\n" + "="*80)
        print("FULL PUBLISH PIPELINE SUMMARY")
        print("="*80)
        print(f"Duration: {results['duration_seconds']:.1f} seconds")
        print(f"Pipeline Success: {'✅' if results['pipeline_success'] else '❌'}")

        if results['validation_results'] and not results['validation_results'].get('skipped'):
            validation_results = results['validation_results']
            passed = sum(1 for v in validation_results.values() if v)
            total = len(validation_results)
            print(f"Validation: {passed}/{total} projects passed")

        publish_results = results['publish_results']
        if publish_results:
            for date_key, success in publish_results.items():
                status = "✅" if success else "❌"
                print(f"Publish {date_key}: {status}")

        if results['errors']:
            print(f"\nErrors ({len(results['errors'])}):")
            for error in results['errors']:
                print(f"  - {error}")

        print("="*80)

        # Exit with appropriate code
        has_errors = bool(results['errors']) or not any(publish_results.values() if publish_results else [True])
        sys.exit(1 if has_errors else 0)

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Pipeline failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()