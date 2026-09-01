#!/usr/bin/env python3
"""
Docker Pipeline Health Monitor for Vietnamese Subtitle Generation

Monitors pipeline health in real-time and provides automatic recovery mechanisms.
"""

import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional
import subprocess
import psutil
import threading
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PipelineHealthMonitor:
    """Monitor Docker pipeline health and provide automatic recovery."""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.health_log = self.project_root / "logs" / "pipeline_health.json"
        self.health_log.parent.mkdir(exist_ok=True)
        self.monitoring = False
        self.last_health_check = None
        
    def check_container_health(self) -> Dict[str, bool]:
        """Check Docker container health status."""
        health_status = {}
        
        # Check if containers are running
        try:
            result = subprocess.run([
                "docker", "compose", "ps", "--format", "json"
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                containers = json.loads(result.stdout) if result.stdout.strip() else []
                
                for container in containers:
                    name = container.get('Name', 'unknown')
                    state = container.get('State', 'unknown')
                    health_status[name] = state == 'running'
            else:
                logger.error(f"Failed to check container status: {result.stderr}")
                
        except Exception as e:
            logger.error(f"Error checking container health: {e}")
            
        return health_status
        
    def check_subtitle_generation_health(self) -> Dict[str, any]:
        """Check subtitle generation functionality health."""
        health_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "subtitle_test_passed": False,
            "dependency_status": {},
            "error_messages": []
        }
        
        # Test subtitle generation script
        try:
            test_cmd = [
                "docker", "compose", "run", "--rm", "worker",
                "python3", "-c", """
import sys
sys.path.insert(0, '/app/scripts')
from generate_subtitles_from_text import splitTextToWords, estimateWordDurations
text = 'Test Vietnamese subtitle generation'
words = splitTextToWords(text)
durations = estimateWordDurations(text, 5.0)
print(f'SUCCESS: {len(words)} words, {len(durations)} durations')
"""
            ]
            
            result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0 and "SUCCESS" in result.stdout:
                health_data["subtitle_test_passed"] = True
                logger.info("Subtitle generation test passed")
            else:
                health_data["error_messages"].append(f"Subtitle test failed: {result.stderr}")
                logger.warning(f"Subtitle generation test failed: {result.stderr}")
                
        except Exception as e:
            health_data["error_messages"].append(f"Subtitle test exception: {str(e)}")
            logger.error(f"Error testing subtitle generation: {e}")
            
        return health_data
        
    def check_pipeline_dependencies(self) -> Dict[str, bool]:
        """Check critical pipeline dependencies."""
        dependencies = {
            "ffmpeg": False,
            "ffprobe": False,
            "hyperframes": False,
            "edge-tts": False,
            "python3": False,
            "node": False
        }
        
        for dep in dependencies.keys():
            try:
                cmd = ["docker", "compose", "run", "--rm", "worker", "which", dep]
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                dependencies[dep] = result.returncode == 0
            except Exception as e:
                logger.error(f"Error checking dependency {dep}: {e}")
                
        return dependencies
        
    def run_health_check(self) -> Dict[str, any]:
        """Run comprehensive health check."""
        logger.info("Running pipeline health check...")
        
        health_report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "container_health": self.check_container_health(),
            "subtitle_health": self.check_subtitle_generation_health(),
            "dependencies": self.check_pipeline_dependencies(),
            "overall_status": "unknown"
        }
        
        # Determine overall health status
        container_ok = all(health_report["container_health"].values())
        subtitle_ok = health_report["subtitle_health"]["subtitle_test_passed"]
        deps_ok = all(health_report["dependencies"].values())
        
        if container_ok and subtitle_ok and deps_ok:
            health_report["overall_status"] = "healthy"
        elif container_ok and deps_ok:
            health_report["overall_status"] = "degraded"
        else:
            health_report["overall_status"] = "unhealthy"
            
        # Log health report
        with open(self.health_log, 'w') as f:
            json.dump(health_report, f, indent=2)
            
        logger.info(f"Health check completed: {health_report['overall_status']}")
        return health_report
        
    def attempt_recovery(self) -> bool:
        """Attempt automatic recovery for common issues."""
        logger.info("Attempting pipeline recovery...")
        
        recovery_actions = [
            ("restart_containers", self._restart_containers),
            ("rebuild_containers", self._rebuild_containers),
            ("clear_temp_files", self._clear_temp_files)
        ]
        
        for action_name, action_func in recovery_actions:
            try:
                logger.info(f"Attempting recovery action: {action_name}")
                if action_func():
                    logger.info(f"Recovery action succeeded: {action_name}")
                    
                    # Test if recovery worked
                    time.sleep(10)  # Wait for services to stabilize
                    health = self.run_health_check()
                    if health["overall_status"] in ["healthy", "degraded"]:
                        logger.info("Pipeline recovery successful")
                        return True
                else:
                    logger.warning(f"Recovery action failed: {action_name}")
                    
            except Exception as e:
                logger.error(f"Error during recovery action {action_name}: {e}")
                
        logger.error("All recovery actions failed")
        return False
        
    def _restart_containers(self) -> bool:
        """Restart Docker containers."""
        try:
            subprocess.run(["docker", "compose", "restart"], check=True, timeout=120)
            return True
        except subprocess.CalledProcessError:
            return False
            
    def _rebuild_containers(self) -> bool:
        """Rebuild Docker containers."""
        try:
            subprocess.run(["docker", "compose", "up", "--build", "-d"], check=True, timeout=300)
            return True
        except subprocess.CalledProcessError:
            return False
            
    def _clear_temp_files(self) -> bool:
        """Clear temporary files that might cause issues."""
        try:
            temp_dirs = [
                self.project_root / "logs",
                self.project_root / "projects" / "*" / "hyperframes" / "assets",
                "/tmp"
            ]
            
            for temp_dir in temp_dirs:
                if temp_dir.exists():
                    # Only clear old temp files (older than 1 hour)
                    subprocess.run([
                        "find", str(temp_dir), "-name", "*.tmp", 
                        "-mtime", "+1", "-delete"
                    ], timeout=60)
                    
            return True
        except Exception:
            return False
            
    def start_monitoring(self, interval_seconds: int = 300):
        """Start continuous health monitoring."""
        logger.info(f"Starting pipeline monitoring (interval: {interval_seconds}s)")
        self.monitoring = True
        
        def monitor_loop():
            while self.monitoring:
                try:
                    health = self.run_health_check()
                    self.last_health_check = health
                    
                    if health["overall_status"] == "unhealthy":
                        logger.warning("Pipeline unhealthy, attempting recovery...")
                        self.attempt_recovery()
                        
                    time.sleep(interval_seconds)
                    
                except KeyboardInterrupt:
                    logger.info("Monitoring stopped by user")
                    break
                except Exception as e:
                    logger.error(f"Error in monitoring loop: {e}")
                    time.sleep(60)  # Wait before retrying
                    
        monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        monitor_thread.start()
        
    def stop_monitoring(self):
        """Stop health monitoring."""
        logger.info("Stopping pipeline monitoring")
        self.monitoring = False


def main():
    """Main health monitoring entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor Docker pipeline health")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--check-only", action="store_true", help="Run single health check")
    parser.add_argument("--monitor", action="store_true", help="Start continuous monitoring")
    parser.add_argument("--interval", type=int, default=300, help="Monitoring interval in seconds")
    parser.add_argument("--recover", action="store_true", help="Attempt recovery if unhealthy")
    
    args = parser.parse_args()
    
    monitor = PipelineHealthMonitor(args.project_root)
    
    if args.check_only:
        health = monitor.run_health_check()
        print(json.dumps(health, indent=2))
        return 0 if health["overall_status"] != "unhealthy" else 1
        
    elif args.monitor:
        try:
            monitor.start_monitoring(args.interval)
            # Keep main thread alive
            while monitor.monitoring:
                time.sleep(1)
        except KeyboardInterrupt:
            monitor.stop_monitoring()
            
    elif args.recover:
        health = monitor.run_health_check()
        if health["overall_status"] == "unhealthy":
            success = monitor.attempt_recovery()
            return 0 if success else 1
        else:
            logger.info("Pipeline is healthy, no recovery needed")
            return 0
    else:
        # Default: single health check
        health = monitor.run_health_check()
        print(f"Pipeline status: {health['overall_status']}")
        return 0 if health["overall_status"] != "unhealthy" else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())