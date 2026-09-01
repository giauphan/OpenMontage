#!/usr/bin/env python3
"""
Test Docker pipeline stability and Vietnamese subtitle functionality.

This script tests the entire Docker pipeline to ensure:
1. Docker containers can start successfully
2. Subtitle generation works in Docker
3. All dependencies are available
4. Error handling works correctly
"""

import subprocess
import sys
import tempfile
import json
from pathlib import Path
from typing import Dict, List, Optional


class DockerPipelineTester:
    """Test Docker pipeline stability and functionality."""
    
    def __init__(self):
        self.root_dir = Path(__file__).parent.parent.parent
        self.test_project = None
    
    def run_command(self, cmd: str, cwd: str = None) -> subprocess.CompletedProcess:
        """Run a command and return the result."""
        print(f"Running: {cmd}")
        try:
            result = subprocess.run(cmd, shell=True, cwd=cwd, 
                                  capture_output=True, text=True, timeout=300)
            return result
        except subprocess.TimeoutExpired as e:
            print(f"Command timed out: {cmd}")
            return e
    
    def test_docker_container_startup(self) -> bool:
        """Test that Docker containers can start successfully."""
        print("🐳 Testing Docker container startup...")
        
        # Test worker container
        cmd = "docker compose run --rm worker echo 'Container started successfully'"
        result = self.run_command(cmd)
        
        if result.returncode != 0:
            print(f"❌ Docker worker container failed to start: {result.stderr}")
            return False
        
        if "Container started successfully" not in result.stdout:
            print(f"❌ Docker worker container output unexpected: {result.stdout}")
            return False
        
        print("✅ Docker container startup successful")
        return True
    
    def test_dependencies_in_container(self) -> bool:
        """Test that all dependencies are available in Docker container."""
        print("🔧 Testing dependencies in Docker container...")
        
        deps_to_check = [
            ("python3", "--version"),
            ("node", "--version"), 
            ("npm", "--version"),
            ("ffmpeg", "-version"),
            ("ffprobe", "-version"),
            ("hyperframes", "--version"),
            ("edge-tts", "--help"),
        ]
        
        failed_deps = []
        
        for dep, args in deps_to_check:
            cmd = f"docker compose run --rm worker {dep} {args}"
            result = self.run_command(cmd)
            
            if result.returncode != 0:
                failed_deps.append(dep)
                print(f"❌ Dependency missing: {dep} - {result.stderr}")
            else:
                print(f"✅ Dependency available: {dep}")
        
        if failed_deps:
            print(f"❌ Missing dependencies: {', '.join(failed_deps)}")
            return False
        
        print("✅ All dependencies available in Docker container")
        return True
    
    def test_python_imports_in_container(self) -> bool:
        """Test that Python imports work in Docker container."""
        print("🐍 Testing Python imports in Docker container...")
        
        python_test_script = """
import sys
modules_to_test = [
    'tools.analysis.transcriber',
    'tools.subtitle.subtitle_gen',
    'scripts.generate_subtitles_from_text'
]

failed = []
for module in modules_to_test:
    try:
        if module.startswith('scripts.'):
            sys.path.insert(0, '/app/scripts')
            import generate_subtitles_from_text
            print(f'✅ {module} - OK')
        else:
            __import__(module)
            print(f'✅ {module} - OK')
    except ImportError as e:
        print(f'❌ {module} - FAILED: {e}')
        failed.append(module)

if failed:
    sys.exit(1)
else:
    print('✅ All Python imports successful')
"""
        
        cmd = f"docker compose run --rm worker python3 -c '{python_test_script}'"
        result = self.run_command(cmd)
        
        if result.returncode != 0:
            print(f"❌ Python imports failed: {result.stderr}")
            return False
        
        return "✅ All Python imports successful" in result.stdout
    
    def test_subtitle_generation_in_container(self) -> bool:
        """Test subtitle generation inside Docker container."""
        print("📝 Testing subtitle generation in Docker container...")
        
        test_text = "Xin chào đây là bản tin kiểm tra phụ đề"
        
        # Create test files in container
        cmd = f"""docker compose run --rm worker bash -c '
            echo "{test_text}" > /tmp/test_narration.txt
            touch /tmp/test_audio.mp3
            python3 /app/scripts/generate_subtitles_from_text.py \\
                --narration-text /tmp/test_narration.txt \\
                --audio-path /tmp/test_audio.mp3 \\
                --output-srt /tmp/test_subtitles.srt \\
                --output-json /tmp/test_timestamps.json \\
                --max-words-per-cue 3
        """
        
        result = self.run_command(cmd)
        
        if result.returncode != 0:
            print(f"❌ Subtitle generation failed: {result.stderr}")
            return False
        
        # Verify files were created
        cmd = "docker compose run --rm worker test -f /tmp/test_subtitles.srt && test -f /tmp/test_timestamps.json"
        result = self.run_command(cmd)
        
        if result.returncode != 0:
            print("❌ Subtitle output files not created")
            return False
        
        print("✅ Subtitle generation in container successful")
        return True
    
    def test_pipeline_script_syntax(self) -> bool:
        """Test that pipeline scripts have valid syntax."""
        print("✅ Testing pipeline script syntax...")
        
        scripts_to_test = [
            "scripts/run_daily_news_pipeline.sh",
            "scripts/generate_subtitles_from_text.py"
        ]
        
        for script in scripts_to_test:
            script_path = self.root_dir / script
            if not script_path.exists():
                print(f"❌ Script not found: {script}")
                return False
        
        # Test shell script syntax
        cmd = "bash -n scripts/run_daily_news_pipeline.sh"
        result = self.run_command(cmd, cwd=str(self.root_dir))
        
        if result.returncode != 0:
            print(f"❌ Shell script syntax error: {result.stderr}")
            return False
        
        # Test Python script syntax
        cmd = "python3 -m py_compile scripts/generate_subtitles_from_text.py"
        result = self.run_command(cmd, cwd=str(self.root_dir))
        
        if result.returncode != 0:
            print(f"❌ Python script syntax error: {result.stderr}")
            return False
        
        print("✅ All pipeline script syntax valid")
        return True
    
    def test_hyperframes_compatibility(self) -> bool:
        """Test HyperFrames CLI compatibility for subtitle support."""
        print("🎬 Testing HyperFrames compatibility...")
        
        # Test HyperFrames CLI version
        cmd = "docker compose run --rm worker hyperframes --version"
        result = self.run_command(cmd)
        
        if result.returncode != 0:
            print(f"❌ HyperFrames CLI failed: {result.stderr}")
            return False
        
        print(f"✅ HyperFrames CLI available: {result.stdout.strip()}")
        
        # Test basic HyperFrames commands
        test_cmds = [
            "hyperframes --help",
            "hyperframes lint --help",
            "hyperframes validate --help"
        ]
        
        for cmd in test_cmds:
            full_cmd = f"docker compose run --rm worker {cmd}"
            result = self.run_command(full_cmd)
            
            if result.returncode != 0:
                print(f"❌ HyperFrames command failed: {cmd} - {result.stderr}")
                return False
            else:
                print(f"✅ HyperFrames command works: {cmd}")
        
        return True
    
    def run_all_tests(self) -> Dict[str, bool]:
        """Run all Docker pipeline stability tests."""
        print("🚀 Starting Docker Pipeline Stability Tests")
        print("=" * 50)
        
        test_results = {}
        
        # Run all tests
        tests = [
            ("Docker Container Startup", self.test_docker_container_startup),
            ("Dependencies in Container", self.test_dependencies_in_container),
            ("Python Imports in Container", self.test_python_imports_in_container),
            ("Subtitle Generation in Container", self.test_subtitle_generation_in_container),
            ("Pipeline Script Syntax", self.test_pipeline_script_syntax),
            ("HyperFrames Compatibility", self.test_hyperframes_compatibility),
        ]
        
        for test_name, test_func in tests:
            print(f"\n🧪 {test_name}...")
            try:
                result = test_func()
                test_results[test_name] = result
                status = "✅ PASS" if result else "❌ FAIL"
                print(f"{status}: {test_name}")
            except Exception as e:
                test_results[test_name] = False
                print(f"❌ ERROR: {test_name} - {e}")
        
        return test_results


def main():
    """Main test runner."""
    tester = DockerPipelineTester()
    results = tester.run_all_tests()
    
    print("\n" + "=" * 50)
    print("📊 Test Results Summary")
    print("=" * 50)
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for test_name, result in results.items():
        status = "⭐" if result else "❌"
        print(f"{status} {test_name}")
    
    print(f"\n📈 {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All Docker pipeline stability tests passed!")
        return 0
    else:
        print("❌ Some tests failed. Check the logs above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())