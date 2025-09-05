"""
Unit tests for TTSService

Tests cover:
- Configuration loading and validation
- Text validation and character counting
- API request building and payload validation
- Error handling scenarios
- Retry logic
- Voice configuration management
"""

import pytest
import asyncio
import json
import tempfile
import os
from unittest.mock import Mock, AsyncMock, patch, mock_open
from pathlib import Path

import aiohttp
import aioresponses

from app.services.tts_service import (
    TTSService,
    TTSServiceError,
    TTSConfigError,
    TTSAPIError
)


class TestTTSServiceConfiguration:
    """Test TTS service configuration management"""
    
    @pytest.fixture
    def sample_tts_config(self):
        return {
            "app": {
                "appid": "test_app_id",
                "token": "test_token",
                "cluster": "test_cluster"
            },
            "user": {
                "uid": "test_user_id"
            },
            "audio": {
                "voice_type": "BV001_streaming",
                "encoding": "mp3",
                "speed_ratio": 1.0,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0
            },
            "request": {
                "text_type": "plain",
                "operation": "query",
                "with_frontend": 1,
                "frontend_type": "unitTson"
            },
            "api": {
                "host": "openspeech.bytedance.com",
                "endpoint": "/api/v1/tts"
            }
        }
    
    @pytest.fixture
    def sample_voice_config(self):
        return {
            "online_voices": {
                "chinese": {
                    "general": [
                        {
                            "name": "灿灿",
                            "voice_type": "BV700_streaming",
                            "timestamp_support": True,
                            "emotions": ["通用", "愉悦", "开心"],
                            "languages": ["中文"]
                        },
                        {
                            "name": "通用女声",
                            "voice_type": "BV001_streaming",
                            "timestamp_support": True,
                            "emotions": [],
                            "languages": ["中文"]
                        }
                    ]
                }
            }
        }
    
    def test_init_with_config_files(self, sample_tts_config, sample_voice_config):
        """Test initialization with configuration files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create config files
            tts_config_path = os.path.join(temp_dir, "tts_config.json")
            voice_config_path = os.path.join(temp_dir, "voice_config.json")
            
            with open(tts_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_tts_config, f)
            
            with open(voice_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_voice_config, f)
            
            # Initialize service
            service = TTSService(tts_config_path, voice_config_path)
            
            assert service.config == sample_tts_config
            assert service.voice_config == sample_voice_config
            assert service.config_path == tts_config_path
            assert service.voice_config_path == voice_config_path
    
    def test_init_missing_config_file(self):
        """Test initialization with missing config file"""
        with pytest.raises(TTSConfigError, match="TTS config file not found"):
            TTSService("non_existent_config.json", "non_existent_voice.json")
    
    def test_init_invalid_json(self):
        """Test initialization with invalid JSON"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "invalid.json")
            voice_config_path = os.path.join(temp_dir, "voice.json")
            
            # Create invalid JSON file
            with open(config_path, 'w') as f:
                f.write("{ invalid json }")
            
            with open(voice_config_path, 'w') as f:
                json.dump({}, f)
            
            with pytest.raises(TTSConfigError, match="Invalid JSON"):
                TTSService(config_path, voice_config_path)
    
    def test_reload_config(self, sample_tts_config, sample_voice_config):
        """Test configuration reload"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tts_config_path = os.path.join(temp_dir, "tts_config.json")
            voice_config_path = os.path.join(temp_dir, "voice_config.json")
            
            # Create initial configs
            with open(tts_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_tts_config, f)
            
            with open(voice_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_voice_config, f)
            
            service = TTSService(tts_config_path, voice_config_path)
            original_appid = service.config['app']['appid']
            
            # Modify config
            sample_tts_config['app']['appid'] = "new_app_id"
            with open(tts_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_tts_config, f)
            
            # Reload
            service.reload_config()
            
            assert service.config['app']['appid'] == "new_app_id"
            assert service.config['app']['appid'] != original_appid


class TestTextValidationAndProcessing:
    """Test text validation and processing functionality"""
    
    @pytest.fixture
    def tts_service(self, sample_tts_config, sample_voice_config):
        """Create TTS service for testing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tts_config_path = os.path.join(temp_dir, "tts_config.json")
            voice_config_path = os.path.join(temp_dir, "voice_config.json")
            
            with open(tts_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_tts_config, f)
            
            with open(voice_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_voice_config, f)
            
            yield TTSService(tts_config_path, voice_config_path)
    
    def test_count_characters_chinese(self, tts_service):
        """Test character counting for Chinese text"""
        text = "你好世界！Hello123"
        result = tts_service.count_characters(text)
        
        assert result['total_chars'] == len(text)
        assert result['chinese'] == 4  # 你好世界
        assert result['english'] == 5  # Hello
        assert result['numbers'] == 3  # 123
        assert result['punctuation'] == 1  # ！
    
    def test_count_characters_english(self, tts_service):
        """Test character counting for English text"""
        text = "Hello, World! 123"
        result = tts_service.count_characters(text)
        
        assert result['total_chars'] == len(text)
        assert result['chinese'] == 0
        assert result['english'] == 10  # HelloWorld
        assert result['numbers'] == 3  # 123
        assert result['punctuation'] == 2  # , !
        assert result['spaces'] == 2
    
    def test_validate_text_empty(self, tts_service):
        """Test validation of empty text"""
        is_valid, error = tts_service.validate_text("")
        assert not is_valid
        assert "empty" in error.lower()
        
        is_valid, error = tts_service.validate_text("   ")
        assert not is_valid
        assert "empty" in error.lower()
    
    def test_validate_text_too_long(self, tts_service):
        """Test validation of text that's too long"""
        # Create text longer than 1024 UTF-8 bytes
        long_text = "你好" * 600  # Each Chinese char is 3 bytes in UTF-8
        is_valid, error = tts_service.validate_text(long_text)
        
        assert not is_valid
        assert "too long" in error.lower()
    
    def test_validate_text_valid(self, tts_service):
        """Test validation of valid text"""
        text = "Hello, this is a valid text for TTS generation."
        is_valid, error = tts_service.validate_text(text)
        
        assert is_valid
        assert error == ""
    
    def test_split_text_short(self, tts_service):
        """Test text splitting for short text"""
        text = "Short text"
        chunks = tts_service.split_text(text)
        
        assert len(chunks) == 1
        assert chunks[0] == text
    
    def test_split_text_by_sentences(self, tts_service):
        """Test text splitting by sentences"""
        text = "第一句话。第二句话！第三句话？"
        chunks = tts_service.split_text(text, max_length=50)  # Force splitting
        
        assert len(chunks) >= 1
        # Should split by sentence boundaries
        assert all("。" in chunk or "！" in chunk or "？" in chunk for chunk in chunks)
    
    def test_split_text_very_long(self, tts_service):
        """Test splitting very long text"""
        # Create text that needs splitting
        long_sentence = "这是一个很长的句子" * 20
        chunks = tts_service.split_text(long_sentence, max_length=100)
        
        assert len(chunks) > 1
        # All chunks should be within limit
        assert all(len(chunk.encode('utf-8')) <= 100 for chunk in chunks)


class TestVoiceConfiguration:
    """Test voice configuration management"""
    
    @pytest.fixture
    def tts_service_with_voices(self, sample_tts_config, sample_voice_config):
        """Create TTS service with voice config"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tts_config_path = os.path.join(temp_dir, "tts_config.json")
            voice_config_path = os.path.join(temp_dir, "voice_config.json")
            
            with open(tts_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_tts_config, f)
            
            with open(voice_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_voice_config, f)
            
            yield TTSService(tts_config_path, voice_config_path)
    
    def test_get_available_voices(self, tts_service_with_voices):
        """Test getting available voices"""
        voices = tts_service_with_voices.get_available_voices()
        
        assert 'general' in voices
        assert len(voices['general']) == 2
        
        # Check voice details
        cancan_voice = next(v for v in voices['general'] if v['name'] == '灿灿')
        assert cancan_voice['voice_type'] == 'BV700_streaming'
        assert cancan_voice['timestamp_support'] is True
    
    def test_get_voice_by_type(self, tts_service_with_voices):
        """Test finding voice by type"""
        voice = tts_service_with_voices.get_voice_by_type('BV700_streaming')
        
        assert voice is not None
        assert voice['name'] == '灿灿'
        assert voice['voice_type'] == 'BV700_streaming'
        
        # Test non-existent voice
        voice = tts_service_with_voices.get_voice_by_type('NON_EXISTENT')
        assert voice is None


class TestAPIRequestBuilding:
    """Test API request building and payload generation"""
    
    @pytest.fixture
    def tts_service(self, sample_tts_config, sample_voice_config):
        """Create TTS service for testing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tts_config_path = os.path.join(temp_dir, "tts_config.json")
            voice_config_path = os.path.join(temp_dir, "voice_config.json")
            
            with open(tts_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_tts_config, f)
            
            with open(voice_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_voice_config, f)
            
            yield TTSService(tts_config_path, voice_config_path)
    
    def test_get_api_url(self, tts_service):
        """Test API URL generation"""
        url = tts_service.get_api_url()
        assert url == "https://openspeech.bytedance.com/api/v1/tts"
    
    @patch.dict(os.environ, {'DOUBAO_ACCESS_TOKEN': 'env_token'})
    def test_get_auth_header_from_env(self, tts_service):
        """Test getting auth header from environment variable"""
        header = tts_service.get_auth_header()
        assert header == {"Authorization": "Bearer;env_token"}
    
    def test_get_auth_header_from_config(self, tts_service):
        """Test getting auth header from config"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(TTSConfigError, match="Access token not configured"):
                tts_service.get_auth_header()
    
    def test_build_request_payload_basic(self, tts_service):
        """Test building basic request payload"""
        text = "Hello world"
        payload = tts_service.build_request_payload(text)
        
        # Check structure
        assert 'app' in payload
        assert 'user' in payload
        assert 'audio' in payload
        assert 'request' in payload
        
        # Check text and reqid
        assert payload['request']['text'] == text
        assert 'reqid' in payload['request']
        assert len(payload['request']['reqid']) > 0
    
    def test_build_request_payload_with_overrides(self, tts_service):
        """Test building request payload with parameter overrides"""
        text = "Hello world"
        voice_type = "BV700_streaming"
        encoding = "wav"
        
        payload = tts_service.build_request_payload(
            text=text,
            voice_type=voice_type,
            encoding=encoding,
            speed_ratio=1.5,
            emotion="happy"
        )
        
        assert payload['audio']['voice_type'] == voice_type
        assert payload['audio']['encoding'] == encoding
        assert payload['audio']['speed_ratio'] == 1.5
        assert payload['audio']['emotion'] == "happy"


@pytest.mark.asyncio
class TestAsyncOperations:
    """Test asynchronous operations and HTTP handling"""
    
    @pytest.fixture
    def tts_service(self, sample_tts_config, sample_voice_config):
        """Create TTS service for async testing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tts_config_path = os.path.join(temp_dir, "tts_config.json")
            voice_config_path = os.path.join(temp_dir, "voice_config.json")
            
            with open(tts_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_tts_config, f)
            
            with open(voice_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_voice_config, f)
            
            yield TTSService(tts_config_path, voice_config_path)
    
    async def test_session_lifecycle(self, tts_service):
        """Test HTTP session lifecycle"""
        assert tts_service.session is None
        
        await tts_service.start()
        assert tts_service.session is not None
        assert isinstance(tts_service.session, aiohttp.ClientSession)
        
        await tts_service.close()
        assert tts_service.session is None
    
    async def test_context_manager(self, tts_service):
        """Test async context manager"""
        async with tts_service as service:
            assert service.session is not None
        
        # Session should be closed after context exit
        assert tts_service.session is None
    
    @patch.dict(os.environ, {'DOUBAO_ACCESS_TOKEN': 'test_token'})
    async def test_synthesize_speech_success(self, tts_service):
        """Test successful speech synthesis"""
        text = "Hello world"
        expected_audio = b"fake_audio_data"
        
        # Mock successful API response
        mock_response = {
            "data": "ZmFrZV9hdWRpb19kYXRh",  # base64 encoded "fake_audio_data"
            "message": "Success"
        }
        
        with aioresponses.aioresponses() as m:
            m.post(
                "https://openspeech.bytedance.com/api/v1/tts",
                payload=mock_response,
                status=200
            )
            
            audio_data = await tts_service.synthesize_speech(text)
            assert audio_data == expected_audio
    
    @patch.dict(os.environ, {'DOUBAO_ACCESS_TOKEN': 'test_token'})
    async def test_synthesize_speech_api_error(self, tts_service):
        """Test API error handling"""
        text = "Hello world"
        
        # Mock API error response
        mock_response = {
            "error": {
                "message": "Invalid voice type",
                "code": 400
            }
        }
        
        with aioresponses.aioresponses() as m:
            m.post(
                "https://openspeech.bytedance.com/api/v1/tts",
                payload=mock_response,
                status=200
            )
            
            with pytest.raises(TTSAPIError, match="API error: Invalid voice type"):
                await tts_service.synthesize_speech(text)
    
    @patch.dict(os.environ, {'DOUBAO_ACCESS_TOKEN': 'test_token'})
    async def test_synthesize_speech_http_error(self, tts_service):
        """Test HTTP error handling"""
        text = "Hello world"
        
        with aioresponses.aioresponses() as m:
            m.post(
                "https://openspeech.bytedance.com/api/v1/tts",
                status=500,
                payload={"error": "Internal server error"}
            )
            
            with pytest.raises(TTSAPIError, match="Request failed after .* attempts"):
                await tts_service.synthesize_speech(text)
    
    async def test_synthesize_speech_invalid_text(self, tts_service):
        """Test synthesis with invalid text"""
        with pytest.raises(TTSServiceError, match="Text validation failed"):
            await tts_service.synthesize_speech("")
    
    @patch.dict(os.environ, {'DOUBAO_ACCESS_TOKEN': 'test_token'})
    async def test_synthesize_to_file(self, tts_service):
        """Test synthesis to file"""
        text = "Hello world"
        expected_audio = b"fake_audio_data"
        
        mock_response = {
            "data": "ZmFrZV9hdWRpb19kYXRh",  # base64 encoded "fake_audio_data"
            "message": "Success"
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "test_output.mp3")
            
            with aioresponses.aioresponses() as m:
                m.post(
                    "https://openspeech.bytedance.com/api/v1/tts",
                    payload=mock_response,
                    status=200
                )
                
                result = await tts_service.synthesize_to_file(text, output_path)
                
                # Check file was created
                assert os.path.exists(output_path)
                
                # Check file content
                with open(output_path, 'rb') as f:
                    file_content = f.read()
                    assert file_content == expected_audio
                
                # Check result info
                assert result['file_path'] == output_path
                assert result['file_size'] == len(expected_audio)
                assert result['text_length'] == len(text)
                assert 'synthesis_time' in result
                assert 'timestamp' in result
    
    @patch.dict(os.environ, {'DOUBAO_ACCESS_TOKEN': 'test_token'})
    async def test_batch_synthesize(self, tts_service):
        """Test batch synthesis"""
        texts = ["Hello", "World", "Test"]
        expected_audio = b"fake_audio_data"
        
        mock_response = {
            "data": "ZmFrZV9hdWRpb19kYXRh",  # base64 encoded "fake_audio_data"
            "message": "Success"
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            with aioresponses.aioresponses() as m:
                # Mock all requests
                for _ in range(len(texts)):
                    m.post(
                        "https://openspeech.bytedance.com/api/v1/tts",
                        payload=mock_response,
                        status=200
                    )
                
                results = await tts_service.batch_synthesize(
                    texts, temp_dir, max_concurrent=2
                )
                
                # Check results
                assert len(results) == len(texts)
                
                for i, result in enumerate(results):
                    assert result['success'] is True
                    assert result['index'] == i
                    assert result['error'] is None
                    assert os.path.exists(result['file_path'])
    
    @patch.dict(os.environ, {'DOUBAO_ACCESS_TOKEN': 'test_token'})
    async def test_batch_synthesize_with_errors(self, tts_service):
        """Test batch synthesis with some failures"""
        texts = ["Hello", "World", "Test"]
        
        with tempfile.TemporaryDirectory() as temp_dir:
            with aioresponses.aioresponses() as m:
                # First request succeeds
                m.post(
                    "https://openspeech.bytedance.com/api/v1/tts",
                    payload={"data": "ZmFrZV9hdWRpb19kYXRh", "message": "Success"},
                    status=200
                )
                # Second request fails
                m.post(
                    "https://openspeech.bytedance.com/api/v1/tts",
                    status=500,
                    payload={"error": "Server error"}
                )
                # Third request succeeds
                m.post(
                    "https://openspeech.bytedance.com/api/v1/tts",
                    payload={"data": "ZmFrZV9hdWRpb19kYXRh", "message": "Success"},
                    status=200
                )
                
                results = await tts_service.batch_synthesize(
                    texts, temp_dir, max_concurrent=1
                )
                
                # Check mixed results
                assert len(results) == len(texts)
                assert results[0]['success'] is True
                assert results[1]['success'] is False
                assert results[2]['success'] is True
                
                # Check error is recorded
                assert "Request failed" in results[1]['error']


class TestErrorHandling:
    """Test error handling scenarios"""
    
    @pytest.fixture
    def tts_service(self, sample_tts_config, sample_voice_config):
        """Create TTS service for error testing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tts_config_path = os.path.join(temp_dir, "tts_config.json")
            voice_config_path = os.path.join(temp_dir, "voice_config.json")
            
            with open(tts_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_tts_config, f)
            
            with open(voice_config_path, 'w', encoding='utf-8') as f:
                json.dump(sample_voice_config, f)
            
            yield TTSService(tts_config_path, voice_config_path)
    
    def test_tts_service_error_inheritance(self):
        """Test exception inheritance"""
        assert issubclass(TTSServiceError, Exception)
        assert issubclass(TTSConfigError, TTSServiceError)
        assert issubclass(TTSAPIError, TTSServiceError)
    
    @pytest.mark.asyncio
    @patch.dict(os.environ, {'DOUBAO_ACCESS_TOKEN': 'test_token'})
    async def test_retry_logic(self, tts_service):
        """Test retry logic with transient errors"""
        text = "Hello world"
        
        with aioresponses.aioresponses() as m:
            # First two requests fail with server error (should retry)
            m.post(
                "https://openspeech.bytedance.com/api/v1/tts",
                status=500,
                payload={"error": "Server error"}
            )
            m.post(
                "https://openspeech.bytedance.com/api/v1/tts",
                status=500,
                payload={"error": "Server error"}
            )
            # Third request succeeds
            m.post(
                "https://openspeech.bytedance.com/api/v1/tts",
                payload={"data": "ZmFrZV9hdWRpb19kYXRh", "message": "Success"},
                status=200
            )
            
            # Should succeed after retries
            audio_data = await tts_service.synthesize_speech(text)
            assert audio_data == b"fake_audio_data"
    
    @pytest.mark.asyncio
    @patch.dict(os.environ, {'DOUBAO_ACCESS_TOKEN': 'test_token'})
    async def test_no_retry_on_client_error(self, tts_service):
        """Test that client errors don't trigger retries"""
        text = "Hello world"
        
        with aioresponses.aioresponses() as m:
            # Client error - should not retry
            m.post(
                "https://openspeech.bytedance.com/api/v1/tts",
                status=400,
                payload={"error": "Bad request"}
            )
            
            with pytest.raises(TTSAPIError, match="HTTP 400"):
                await tts_service.synthesize_speech(text)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])