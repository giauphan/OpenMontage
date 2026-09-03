#!/usr/bin/env python3
"""Comprehensive CLAUDE Agent Validation Test Suite.

This test suite verifies that the CLAUDE agent validation pipeline
is working correctly without requiring Docker or CLAUDE API access.
"""

import json
import os
import sys
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# Fix import path to work from root directory
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.claude_agent_validation import CLAUDEAgentValidator, ValidationResult


class MockProcess:
    """Mock subprocess for testing without actual execution."""
    
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestCLAUDEAgentValidation:
    """Test suite for CLAUDE Agent Validation."""
    
    def __init__(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.project_dir = self.test_dir / "test_project"
        self.project_dir.mkdir()
        
        # Create test files
        self._create_test_files()
    
    def _create_test_files(self):
        """Create test project structure."""
        # Create directories
        (self.project_dir / "renders").mkdir()
        (self.project_dir / "artifacts").mkdir()
        
        # Create test video files (minimal non-empty files for testing)
        # These are just placeholders - real tests would use actual video files
        for video_file in ["final_full_vi_9x16.mp4", "final_reels_vi_9x16.mp4"]:
            video_path = self.project_dir / "renders" / video_file
            # Create non-empty placeholder files (1MB of zeros)
            with open(video_path, 'wb') as f:
                f.write(b'\x00' * 1024 * 1024)  # 1MB file
        
        # Create test metadata
        metadata = {
            "title": "Test Video #tintuc #congnghe #ai",
            "description": "Test description",
            "yt_shorts": {"title": "Test #Shorts"},
            "tiktok": {"title": "Test"},
            "fb_video": {"title": "Test"},
            "ig_reels": {"title": "Test"}
        }
        
        with open(self.project_dir / "publish_metadata.json", "w") as f:
            json.dump(metadata, f)
        
        # Create test artifacts
        artifacts = {
            "title": "Test Video",
            "description": "Test description"
        }
        
        with open(self.project_dir / "artifacts" / "script_vi.json", "w") as f:
            json.dump(artifacts, f)
    
    def cleanup(self):
        """Clean up test files."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_technical_contract_validation(self):
        """Test technical contract validation."""
        print("Testing Technical Contract Validation...")
        
        validator = CLAUDEAgentValidator(self.project_dir, strict_mode=True)
        
        # Create a mock video file with filename indicating valid specs
        video_path = self.project_dir / "renders" / "final_full_vi_9x16.mp4"
        video_path.touch()
        
        # Test with non-existent file
        results = validator.validate_technical_contract(self.project_dir / "nonexistent.mp4")
        assert len(results) > 0
        assert not any(r.passed for r in results)
        print(f"✅ Non-existent file test: {len(results)} failures detected")
        
        # Test with empty file
        empty_file = self.project_dir / "empty.mp4"
        empty_file.touch()  # Creates empty file
        results = validator.validate_technical_contract(empty_file)
        assert len(results) > 0
        assert not any(r.passed for r in results)
        print(f"✅ Empty file test: {len(results)} failures detected")
        
        print("✅ Technical Contract Validation Tests PASSED")
    
    def test_content_quality_validation(self):
        """Test content quality validation with mocked subprocess."""
        print("Testing Content Quality Validation...")
        
        validator = CLAUDEAgentValidator(self.project_dir, strict_mode=True)
        
        # Test with valid files
        with patch('subprocess.run') as mock_run:
            # Mock successful validation
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "Validation passed"
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            video_path = self.project_dir / "renders" / "final_full_vi_9x16.mp4"
            results = validator.validate_content_quality(video_path, "ffprobe", "ffmpeg")
            
            assert len(results) > 0
            assert any(r.passed for r in results)
            print(f"✅ Content quality validate test: {len(results)} results")
        
        # Test with failing validation
        with patch('subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_result.stderr = "Error: validation failed\nError: audio too silent"
            mock_run.return_value = mock_result
            
            results = validator.validate_content_quality(video_path, "ffprobe", "ffmpeg")
            assert len(results) > 0
            assert not any(r.passed for r in results)
            print(f"✅ Content quality fail test: {len(results)} failures detected")
        
        print("✅ Content Quality Validation Tests PASSED")
    
    def test_metadata_validation(self):
        """Test metadata validation."""
        print("Testing Metadata Validation...")
        
        validator = CLAUDEAgentValidator(self.project_dir, strict_mode=True)
        
        # Test with valid metadata
        metadata_path = self.project_dir / "publish_metadata.json"
        with patch('subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "Metadata validation passed"
            mock_run.return_value = mock_result
            
            results = validator.validate_metadata(metadata_path)
            assert len(results) > 0
            assert any(r.passed for r in results)
            print(f"✅ Metadata validation test: {len(results)} results")
        
        # Test with missing metadata file
        nonexistent_metadata = self.project_dir / "nonexistent_metadata.json"
        results = validator.validate_metadata(nonexistent_metadata)
        assert len(results) > 0
        assert not any(r.passed for r in results)
        print(f"✅ Missing metadata test: {len(results)} failures detected")
        
        print("✅ Metadata Validation Tests PASSED")
    
    def test_claud_agent_review(self):
        """Test CLAUDE agent review with mocked subprocess."""
        print("Testing CLAUDE Agent Review...")
        
        validator = CLAUDEAgentValidator(self.project_dir, strict_mode=True)
        
        # Mock CLAUDE agent response
        claude_response = json.dumps({
            "visual_quality": {"passed": True, "score": 95, "notes": "Excellent"},
            "audio_sync": {"passed": True, "score": 89, "notes": "Good"},
            "content_appropriateness": {"passed": True, "score": 100, "notes": "Perfect"},
            "brand_compliance": {"passed": True, "score": 92, "notes": "Compliant"},
            "overall_passed": True,
            "summary": "All checks passed"
        })
        
        with patch('subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = claude_response
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            video_path = self.project_dir / "renders" / "final_full_vi_9x16.mp4"
            results = validator.claude_agent_strict_review(video_path, self.project_dir / "publish_metadata.json")

            assert len(results) == 4  # Should have 4 check results
            assert all(r.passed for r in results)
            print(f"✅ CLAUDE agent pass test: {len(results)} checks all passed")
        
        # Test CLAUDE agent failure
        claude_response_fail = json.dumps({
            "visual_quality": {"passed": False, "score": 45, "notes": "Visual artifacts"},
            "audio_sync": {"passed": True, "score": 89, "notes": "Good"},
            "content_appropriateness": {"passed": True, "score": 100, "notes": "Perfect"},
            "brand_compliance": {"passed": False, "score": 30, "notes": "Brand violation"},
            "overall_passed": False,
            "summary": "Validation failed"
        })
        
        with patch('subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = claude_response_fail
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            results = validator.claude_agent_strict_review(video_path, self.project_dir / "publish_metadata.json")

            assert len(results) == 4
            failed_results = [r for r in results if not r.passed]
            assert len(failed_results) == 2  # visual_quality and brand_compliance failed
            print(f"✅ CLAUDE agent fail test: {len(failed_results)} failures detected")
        
        print("✅ CLAUDE Agent Review Tests PASSED")
    
    def test_full_validation_pipeline(self):
        """Test the complete validation pipeline with mocked subprocess."""
        print("Testing Full Validation Pipeline...")
        
        validator = CLAUDEAgentValidator(self.project_dir, strict_mode=True)
        
        # Mock all subprocess calls
        with patch('subprocess.run') as mock_run:
            # Mock successful responses for all validation steps
            def mock_run_func(cmd, *args, **kwargs):
                mock_result = MagicMock()
                
                # Different commands return different results
                cmd_str = ' '.join(cmd)
                if 'validate_render_quality.py' in cmd_str:
                    mock_result.returncode = 0
                    mock_result.stdout = "Render validation passed"
                    mock_result.stderr = ""
                elif 'validate_publish_metadata.py' in cmd_str:
                    mock_result.returncode = 0
                    mock_result.stdout = "Metadata validation passed"
                    mock_result.stderr = ""
                elif 'ffprobe' in cmd[0] or 'ffprobe' in cmd_str:
                    # Handle ffprobe calls - return valid duration
                    mock_result.returncode = 0
                    mock_result.stdout = "45.5"  # Valid duration in seconds
                    mock_result.stderr = ""
                elif 'claude' in cmd[0] or 'claude' in cmd_str:  # CLAUDE agent
                    mock_result.returncode = 0
                    mock_result.stdout = json.dumps({
                        "visual_quality": {"passed": True, "score": 95, "notes": "Excellent"},
                        "audio_sync": {"passed": True, "score": 89, "notes": "Good"},
                        "content_appropriateness": {"passed": True, "score": 100, "notes": "Perfect"},
                        "brand_compliance": {"passed": True, "score": 92, "notes": "Compliant"},
                        "overall_passed": True,
                        "summary": "All checks passed"
                    })
                    mock_result.stderr = ""
                else:
                    mock_result.returncode = 0
                    mock_result.stdout = ""
                    mock_result.stderr = ""
                
                return mock_result
            
            mock_run.side_effect = mock_run_func
            
            # Set up video paths
            video_paths = [
                self.project_dir / "renders" / "final_full_vi_9x16.mp4",
                self.project_dir / "renders" / "final_reels_vi_9x16.mp4"
            ]
            metadata_path = self.project_dir / "publish_metadata.json"
            
            # Execute full validation
            validation_data = validator.execute_validation(
                video_paths=video_paths,
                metadata_path=metadata_path,
                ffprobe_bin="ffprobe",
                ffmpeg_bin="ffmpeg"
            )
            
            # Verify results
            assert validation_data['overall_status'] == 'PASS'
            assert validation_data['total_checks'] > 0
            assert validation_data['passed_checks'] > 0
            assert validation_data['failed_checks'] == 0
            assert validation_data['color'] == '🟢'
            assert validation_data['strict_quality_pass'] is True
            
            print(f"✅ Full pipeline test: {validation_data['total_checks']} checks, all passed")
        
        print("✅ Full Validation Pipeline Tests PASSED")


def main():
    """Main test execution."""
    print("\n" + "="*60)
    print("🧪 CLAUDE AGENT VALIDATION TEST SUITE")
    print("="*60)
    
    # Initialize test suite
    test_suite = TestCLAUDEAgentValidation()
    
    try:
        # Run all tests
        test_suite.test_technical_contract_validation()
        test_suite.test_content_quality_validation()
        test_suite.test_metadata_validation()
        test_suite.test_claud_agent_review()
        test_suite.test_full_validation_pipeline()
        
        print("\n" + "="*60)
        print("🎉 ALL TESTS PASSED!")
        print("="*60)
        print("✅ Technical Contract Validation: PASSED")
        print("✅ Content Quality Validation: PASSED")
        print("✅ Metadata Validation: PASSED")
        print("✅ CLAUDE Agent Review: PASSED")
        print("✅ Full Validation Pipeline: PASSED")
        print("="*60)
        
        return 0
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        test_suite.cleanup()


if __name__ == '__main__':
    sys.exit(main())