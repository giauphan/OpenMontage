#!/usr/bin/env python3
"""Validation Status Logger for Codex Agent Quality Pipeline.

Tracks validation results and provides status reporting for Docker pipeline.
Integrates with cron pipeline logs and provides clear 🟢 PASS / 🔴 FAIL indicators.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional


class ValidationStatusLogger:
    """Tracks and logs Codex agent validation status."""

    def __init__(self, project_dir: Optional[Path] = None):
        # If project_dir is provided, use it for file locations
        self.project_dir = project_dir
        if project_dir is not None:
            # Convert string to Path if needed
            if isinstance(project_dir, str):
                project_dir = Path(project_dir)
            self.STATUS_FILE = project_dir / "validation_status.json"
            self.logs_dir = project_dir / "logs"
            self.LOG_FILE = self.logs_dir / "validation_log.txt"
        else:
            # Default paths for Docker container
            self.STATUS_FILE = Path("/app/validation_status.json")
            self.logs_dir = Path("/app/logs")
            self.LOG_FILE = Path("/app/logs/validation_log.txt")
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        
    def log_validation_result(self, project_id: str, status: str, 
                              total_checks: int, passed: int, failed: int,
                              details: Optional[Dict] = None) -> None:
        """Log validation result to status file and log."""
        
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Create status entry
        entry = {
            "project_id": project_id,
            "timestamp": timestamp,
            "status": status,
            "total_checks": total_checks,
            "passed": passed,
            "failed": failed,
            "color": "🟢" if status == "PASS" else "🔴",
            "strict_quality_pass": status == "PASS",
            "details": details or {}
        }
        
        # Update status file
        self._update_status_file(entry)
        
        # Write to log file
        self._write_to_log_file(entry)
        
        # Print console output
        self._print_console_output(entry)
    
    def _update_status_file(self, entry: Dict) -> None:
        """Update the validation status JSON file."""
        try:
            # Read existing entries
            existing = []
            if self.STATUS_FILE.exists():
                with open(self.STATUS_FILE, 'r', encoding='utf-8') as f:
                    try:
                        existing = json.load(f)
                        if not isinstance(existing, list):
                            existing = [existing]
                    except json.JSONDecodeError:
                        existing = []
            
            # Add new entry
            existing.append(entry)
            
            # Keep only last 100 entries
            if len(existing) > 100:
                existing = existing[-100:]
            
            # Write updated file
            with open(self.STATUS_FILE, 'w', encoding='utf-8') as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
        
        except Exception as e:
            print(f"Warning: Could not update status file: {e}")
    
    def _write_to_log_file(self, entry: Dict) -> None:
        """Write validation entry to log file."""
        try:
            log_line = json.dumps(entry, ensure_ascii=False)
            with open(self.LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"{entry['timestamp']} | {log_line}\n")
        except Exception as e:
            print(f"Warning: Could not write to log file: {e}")
    
    def _print_console_output(self, entry: Dict) -> None:
        """Print formatted console output."""
        print(f"\n{'='*50}")
        print("CODEX AGENT VALIDATION STATUS")
        print(f"{'='*50}")
        print(f"Project: {entry['project_id']}")
        print(f"Timestamp: {entry['timestamp']}")
        print(f"Status: {entry['color']} {entry['status']}")
        print(f"Checks: {entry['passed']}/{entry['total_checks']} passed")
        print(f"{'='*50}")
    
    def get_current_status(self, project_id: Optional[str] = None) -> List[Dict]:
        """Get current validation status, optionally for specific project."""
        try:
            if not self.STATUS_FILE.exists():
                return []
            
            with open(self.STATUS_FILE, 'r', encoding='utf-8') as f:
                entries = json.load(f)
                if not entries:
                    return []
                
            if project_id:
                return [e for e in entries if e.get('project_id') == project_id]
            
            # Return most recent 10 entries
            return entries[-10:] if entries else []
            
        except Exception:
            return []
    
    def get_failure_details(self, project_id: str) -> List[str]:
        """Get failure details for specific project."""
        entries = self.get_current_status(project_id)
        failures = []
        
        for entry in entries:
            if entry.get('status') == 'FAIL':
                if 'details' in entry and 'results' in entry['details']:
                    for result in entry['details']['results']:
                        if not result.get('passed', True):
                            failures.append(f"{result.get('check_name', 'Unknown')}: {result.get('message', 'No message')}")
        
        return failures


def main():
    """Main entry point for status logging."""
    logger = ValidationStatusLogger()
    
    if len(sys.argv) > 1:
        # Parse command line arguments
        import argparse
        parser = argparse.ArgumentParser(description='Validation Status Logger')
        parser.add_argument('project_id', help='Project ID')
        parser.add_argument('status', help='PASS or FAIL')
        parser.add_argument('--total', type=int, default=0, help='Total checks')
        parser.add_argument('--passed', type=int, default=0, help='Passed checks')
        parser.add_argument('--failed', type=int, default=0, help='Failed checks')
        parser.add_argument('--details', help='JSON details file')
        
        args = parser.parse_args()
        
        # Read details if provided
        details = {}
        if args.details and Path(args.details).exists():
            with open(args.details, 'r', encoding='utf-8') as f:
                try:
                    details = json.load(f)
                except:
                    details = {}
        
        # Log the result
        logger.log_validation_result(
            project_id=args.project_id,
            status=args.status,
            total_checks=args.total,
            passed=args.passed,
            failed=args.failed,
            details=details
        )
    else:
        # Show usage
        print("Usage: validation_status.py <project_id> <status> [--total N] [--passed N] [--failed N] [--details file.json]")
        
        # Show recent status
        recent = logger.get_current_status()
        if recent:
            print(f"\nRecent Validation Status:")
            for entry in recent[-5:]:  # Show last 5
                status_icon = entry.get('color', '⚪')
                print(f"{status_icon} {entry.get('project_id', 'Unknown')}: {entry.get('status', 'Unknown')} ({entry.get('passed', 0)}/{entry.get('total_checks', 0)})")


if __name__ == '__main__':
    main()