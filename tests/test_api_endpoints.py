"""
Integration tests for FastAPI endpoints
"""

import pytest
import asyncio
from fastapi.testclient import TestClient
from app.main import app

# Create test client
client = TestClient(app)


class TestHealthEndpoint:
    """Test health check endpoint"""
    
    def test_health_check(self):
        """Test health endpoint returns correct status"""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"
        assert "timestamp" in data
        assert "service_status" in data


class TestRootEndpoint:
    """Test root endpoint"""
    
    def test_root_endpoint(self):
        """Test root endpoint returns API information"""
        response = client.get("/")
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == "TTS Tool API"
        assert data["version"] == "1.0.0"
        assert "endpoints" in data
        assert data["endpoints"]["generate"] == "/api/tts/generate"
        assert data["endpoints"]["batch"] == "/api/tts/batch"
        assert data["endpoints"]["voices"] == "/api/voices"
        assert data["endpoints"]["config"] == "/api/config"


class TestVoicesEndpoint:
    """Test voices endpoint"""
    
    def test_get_voices(self):
        """Test voices endpoint returns voice categories"""
        response = client.get("/api/voices")
        assert response.status_code == 200
        
        data = response.json()
        assert "categories" in data
        assert "total_count" in data
        assert isinstance(data["categories"], dict)
        assert data["total_count"] > 0
        
        # Check if we have expected voice categories
        categories = data["categories"]
        assert "general" in categories
        assert len(categories["general"]) > 0
        
        # Check voice structure
        first_voice = categories["general"][0]
        required_fields = ["name", "voice_type", "emotions", "languages", "timestamp_support"]
        for field in required_fields:
            assert field in first_voice


class TestConfigEndpoint:
    """Test configuration endpoints"""
    
    def test_get_config(self):
        """Test get configuration endpoint"""
        response = client.get("/api/config")
        assert response.status_code == 200
        
        data = response.json()
        assert "audio" in data
        assert "api" in data
        assert "limits" in data
        
        # Check audio config
        audio = data["audio"]
        assert "voice_type" in audio
        assert "encoding" in audio
        assert "speed_ratio" in audio
        
        # Check limits
        limits = data["limits"]
        assert "max_text_length" in limits
        assert "supported_encodings" in limits
        assert isinstance(limits["supported_encodings"], list)
    
    def test_update_config(self):
        """Test update configuration endpoint"""
        update_data = {
            "speed_ratio": 1.2,
            "volume_ratio": 0.9,
            "encoding": "wav"
        }
        
        response = client.post("/api/config", json=update_data)
        assert response.status_code == 200
        
        data = response.json()
        assert "message" in data
        assert "updated_fields" in data


class TestTTSEndpoints:
    """Test TTS generation endpoints"""
    
    def test_generate_tts_validation(self):
        """Test TTS generation endpoint validation"""
        # Test with empty text
        invalid_request = {"text": ""}
        response = client.post("/api/tts/generate", json=invalid_request)
        assert response.status_code == 422  # Validation error
        
        # Test with valid request structure (will fail without API credentials)
        valid_request = {
            "text": "测试文本",
            "voice_type": "BV001_streaming",
            "encoding": "mp3",
            "speed_ratio": 1.0
        }
        response = client.post("/api/tts/generate", json=valid_request)
        # Expected to fail due to missing credentials, but structure should be valid
        # We just check it's not a validation error (422)
        assert response.status_code != 422
    
    def test_batch_tts_validation(self):
        """Test batch TTS endpoint validation"""
        # Test with empty items
        invalid_request = {"items": []}
        response = client.post("/api/tts/batch", json=invalid_request)
        assert response.status_code == 422  # Validation error
        
        # Test with valid request structure
        valid_request = {
            "items": [
                {
                    "text": "测试文本1",
                    "voice_type": "BV001_streaming"
                },
                {
                    "text": "测试文本2",
                    "voice_type": "BV002_streaming"
                }
            ],
            "output_dir": "./test_output",
            "max_concurrent": 2
        }
        response = client.post("/api/tts/batch", json=valid_request)
        # Expected to fail due to missing credentials, but structure should be valid
        assert response.status_code != 422


class TestDocumentation:
    """Test API documentation endpoints"""
    
    def test_openapi_docs(self):
        """Test that OpenAPI documentation is available"""
        response = client.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    
    def test_openapi_json(self):
        """Test OpenAPI JSON schema"""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        
        schema = response.json()
        assert "openapi" in schema
        assert "info" in schema
        assert schema["info"]["title"] == "TTS Tool API"
        assert "paths" in schema
        
        # Check that our endpoints are documented
        paths = schema["paths"]
        assert "/health" in paths
        assert "/api/tts/generate" in paths
        assert "/api/voices" in paths
        assert "/api/config" in paths


class TestErrorHandling:
    """Test error handling"""
    
    def test_404_error(self):
        """Test 404 error for non-existent endpoint"""
        response = client.get("/nonexistent")
        assert response.status_code == 404
    
    def test_method_not_allowed(self):
        """Test 405 error for wrong HTTP method"""
        response = client.post("/health")
        assert response.status_code == 405


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])