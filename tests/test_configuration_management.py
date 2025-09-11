"""
Test Configuration Management and Cost Control Features

This test suite verifies the configuration hot-reload, usage tracking,
and cost control functionality implemented for Issue #8.
"""

import pytest
import asyncio
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.services.config_manager import ConfigManager, ConfigurationError
from app.services.usage_tracker import UsageTracker, UsageRecord, CostConfig
from app.services.cost_control import CostController, CostControlConfig, LimitType


class TestConfigurationManager:
    """Test configuration manager with hot-reload functionality"""
    
    @pytest.fixture
    async def temp_config_files(self):
        """Create temporary configuration files for testing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_paths = {}
            
            # Create test TTS config
            tts_config = {
                "app": {"appid": "test", "token": "test_token"},
                "audio": {"voice_type": "test_voice", "encoding": "mp3"},
                "request": {"text_type": "plain"}
            }
            tts_config_path = os.path.join(temp_dir, "tts_config.json")
            with open(tts_config_path, 'w') as f:
                json.dump(tts_config, f)
            config_paths["tts_config"] = tts_config_path
            
            # Create test voice config
            voice_config = {
                "online_voices": {
                    "chinese": {
                        "general": [
                            {"name": "Test Voice", "voice_type": "test_voice"}
                        ]
                    }
                }
            }
            voice_config_path = os.path.join(temp_dir, "voice_config.json")
            with open(voice_config_path, 'w') as f:
                json.dump(voice_config, f)
            config_paths["voice_config"] = voice_config_path
            
            yield config_paths
    
    @pytest.fixture
    async def config_manager(self, temp_config_files):
        """Create config manager with temporary files"""
        validation_schema = {
            "tts_config": {
                "required": ["app", "audio", "request"],
                "types": {"app": dict, "audio": dict, "request": dict}
            }
        }
        
        manager = ConfigManager(temp_config_files, validation_schema)
        await manager.start()
        yield manager
        await manager.stop()
    
    def test_config_loading(self, config_manager):
        """Test basic configuration loading"""
        tts_config = config_manager.get_config("tts_config")
        assert tts_config is not None
        assert tts_config["app"]["appid"] == "test"
        assert tts_config["audio"]["voice_type"] == "test_voice"
        
        voice_config = config_manager.get_config("voice_config")
        assert voice_config is not None
        assert "online_voices" in voice_config
    
    def test_config_validation(self, config_manager):
        """Test configuration validation"""
        results = config_manager.validate_all_configs()
        assert results["tts_config"]["valid"] is True
        assert len(results["tts_config"]["errors"]) == 0
    
    def test_config_update(self, config_manager):
        """Test programmatic configuration updates"""
        updates = {
            "audio": {
                "voice_type": "updated_voice",
                "speed_ratio": 1.5
            }
        }
        
        success = config_manager.update_config("tts_config", updates, save_to_file=False)
        assert success is True
        
        updated_config = config_manager.get_config("tts_config")
        assert updated_config["audio"]["voice_type"] == "updated_voice"
        assert updated_config["audio"]["speed_ratio"] == 1.5
    
    def test_config_history(self, config_manager):
        """Test configuration history tracking"""
        # Make an update to generate history
        config_manager.update_config("tts_config", {"test": "value"}, save_to_file=False)
        
        history = config_manager.get_config_history("tts_config", limit=10)
        assert len(history) >= 1
        assert history[0]["config_name"] == "tts_config"
        assert "timestamp" in history[0]


class TestUsageTracker:
    """Test usage tracking and statistics functionality"""
    
    @pytest.fixture
    async def usage_tracker(self):
        """Create usage tracker with temporary database"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_db:
            db_path = temp_db.name
        
        try:
            tracker = UsageTracker(db_path=db_path, cost_config=CostConfig())
            yield tracker
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)
    
    @pytest.mark.asyncio
    async def test_usage_tracking(self, usage_tracker):
        """Test basic usage record tracking"""
        record = UsageRecord(
            request_id="test-123",
            text="Hello world test text",
            text_length=20,
            utf8_bytes=20,
            voice_type="test_voice",
            encoding="mp3",
            success=True,
            processing_time=1.5,
            file_size=12345,
            session_id="test-session",
            user_id="test-user"
        )
        
        record_id = await usage_tracker.track_usage(record)
        assert record_id is not None
        
        # Verify record was stored
        stats = await usage_tracker.get_usage_stats()
        assert stats["summary"]["total_requests"] == 1
        assert stats["summary"]["successful_requests"] == 1
        assert stats["summary"]["total_characters"] == 20
    
    @pytest.mark.asyncio
    async def test_usage_statistics(self, usage_tracker):
        """Test usage statistics generation"""
        # Create multiple usage records
        for i in range(3):
            record = UsageRecord(
                request_id=f"test-{i}",
                text=f"Test text {i}" * (i + 1),  # Different lengths
                text_length=len(f"Test text {i}" * (i + 1)),
                utf8_bytes=len(f"Test text {i}" * (i + 1)),
                voice_type="test_voice",
                encoding="mp3",
                success=True,
                session_id="test-session"
            )
            await usage_tracker.track_usage(record)
        
        stats = await usage_tracker.get_usage_stats()
        
        assert stats["summary"]["total_requests"] == 3
        assert stats["summary"]["successful_requests"] == 3
        assert stats["summary"]["total_characters"] > 0
        assert len(stats["voice_breakdown"]) > 0
        assert stats["voice_breakdown"][0]["voice_type"] == "test_voice"
    
    @pytest.mark.asyncio
    async def test_current_usage(self, usage_tracker):
        """Test current session usage tracking"""
        session_id = "test-session-current"
        
        record = UsageRecord(
            request_id="current-test",
            text="Current usage test",
            text_length=18,
            utf8_bytes=18,
            voice_type="test_voice",
            encoding="mp3",
            success=True,
            session_id=session_id
        )
        
        await usage_tracker.track_usage(record)
        
        current_usage = await usage_tracker.get_current_usage(session_id)
        assert current_usage["session_id"] == session_id
        assert current_usage["today"]["requests"] == 1
        assert current_usage["today"]["characters"] == 18


class TestCostController:
    """Test cost control and character limits functionality"""
    
    @pytest.fixture
    def cost_controller(self):
        """Create cost controller with test configuration"""
        config = CostControlConfig(
            soft_limit_1000=True,
            hard_limit_5000=True,
            base_cost_per_char=0.001,
            show_cost_estimates=True
        )
        
        mock_usage_tracker = AsyncMock()
        mock_usage_tracker.get_current_usage.return_value = {
            "session_id": "test-session",
            "today": {"requests": 5, "characters": 500, "cost": 0.5}
        }
        
        controller = CostController(config, mock_usage_tracker)
        return controller
    
    def test_cost_estimation(self, cost_controller):
        """Test cost estimation functionality"""
        text = "This is a test text for cost estimation"
        estimate = cost_controller.calculate_cost_estimate(text, "test_voice", "mp3", "cn")
        
        assert estimate.character_count == len(text)
        assert estimate.utf8_bytes >= len(text)
        assert estimate.estimated_cost > 0
        assert estimate.voice_multiplier >= 1.0
        assert estimate.encoding_multiplier >= 0.5
    
    @pytest.mark.asyncio
    async def test_character_limits_under_1000(self, cost_controller):
        """Test behavior with text under 1000 characters"""
        short_text = "Short text under limit"
        session_id = "test-session"
        
        result = await cost_controller.check_limits(short_text, session_id)
        
        assert result.allowed is True
        assert result.requires_confirmation is False
        assert result.cost_estimate is not None
        assert result.cost_estimate.character_count == len(short_text)
    
    @pytest.mark.asyncio
    async def test_character_limits_over_1000(self, cost_controller):
        """Test 1000-character soft limit (confirmation required)"""
        long_text = "A" * 1500  # Over 1000 characters
        session_id = "test-session"
        
        result = await cost_controller.check_limits(long_text, session_id)
        
        assert result.allowed is False
        assert result.requires_confirmation is True
        assert result.confirmation_token is not None
        assert result.limit_exceeded is not None
        assert result.limit_exceeded.limit_type == LimitType.SOFT_LIMIT
    
    @pytest.mark.asyncio
    async def test_character_limits_over_5000(self, cost_controller):
        """Test 5000-character hard limit (blocked)"""
        very_long_text = "A" * 6000  # Over 5000 characters
        session_id = "test-session"
        
        result = await cost_controller.check_limits(very_long_text, session_id)
        
        assert result.allowed is False
        assert result.requires_confirmation is False
        assert result.limit_exceeded is not None
        assert result.limit_exceeded.limit_type == LimitType.HARD_LIMIT
    
    @pytest.mark.asyncio
    async def test_confirmation_flow(self, cost_controller):
        """Test confirmation token generation and validation"""
        long_text = "A" * 1200  # Over 1000 characters
        session_id = "test-session"
        
        # First request should require confirmation
        result1 = await cost_controller.check_limits(long_text, session_id)
        assert result1.requires_confirmation is True
        
        confirmation_token = result1.confirmation_token
        assert confirmation_token is not None
        
        # Second request with confirmation token should be allowed
        result2 = await cost_controller.check_limits(
            long_text, session_id, confirmation_token=confirmation_token
        )
        assert result2.allowed is True
        assert result2.requires_confirmation is False
    
    def test_limits_info(self, cost_controller):
        """Test getting limits and configuration information"""
        info = cost_controller.get_limits_info()
        
        assert "character_limits" in info
        assert "quotas" in info
        assert "cost_settings" in info
        assert len(info["character_limits"]) >= 2  # soft and hard limits
        
        # Check that both 1000 and 5000 limits are configured
        thresholds = [limit["threshold"] for limit in info["character_limits"]]
        assert 1000 in thresholds
        assert 5000 in thresholds


# Integration test
@pytest.mark.asyncio
async def test_integration_cost_control_with_usage_tracking():
    """Integration test for cost control with actual usage tracking"""
    
    # Setup usage tracker
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_db:
        db_path = temp_db.name
    
    try:
        usage_tracker = UsageTracker(db_path=db_path)
        
        # Setup cost controller
        config = CostControlConfig(
            soft_limit_1000=True,
            hard_limit_5000=True,
            base_cost_per_char=0.001
        )
        cost_controller = CostController(config, usage_tracker)
        
        session_id = "integration-test"
        
        # Test with text under limit
        short_text = "Short integration test"
        result = await cost_controller.check_limits(short_text, session_id)
        assert result.allowed is True
        
        # Track usage
        if result.allowed:
            record = UsageRecord(
                request_id="integration-1",
                text=short_text,
                text_length=len(short_text),
                utf8_bytes=len(short_text.encode('utf-8')),
                voice_type="test_voice",
                encoding="mp3",
                success=True,
                session_id=session_id
            )
            await usage_tracker.track_usage(record)
        
        # Verify usage was tracked
        current_usage = await usage_tracker.get_current_usage(session_id)
        assert current_usage["today"]["requests"] == 1
        assert current_usage["today"]["characters"] == len(short_text)
        
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])