"""
Application Configuration
"""

import os
from typing import Optional

try:
    from pydantic_settings import BaseSettings
except ImportError:
    from pydantic import BaseSettings

class Settings(BaseSettings):
    """Application settings"""
    
    # Basic App Settings
    app_name: str = "TTS Tool"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # Server Settings
    host: str = "127.0.0.1"
    port: int = 8000
    
    # Volcengine TTS Settings
    volcengine_region: str = "cn-north-1"
    volcengine_speech_app_id: Optional[str] = None
    volcengine_speech_cluster: str = "volcano_tts"
    volcengine_speech_access_token: Optional[str] = None
    volcengine_speech_secret_key: Optional[str] = None
    volcengine_tts_resource_id: str = "volc.service_type.10029"
    volcengine_tts_voice_type: str = "BV700_V2_streaming"
    
    # Output Settings
    output_dir: str = "./output"
    max_text_length: int = 10000
    concurrent_requests: int = 3
    
    # TTS API Settings
    tts_host: str = "openspeech.bytedance.com"
    tts_endpoint: str = "/api/v1/tts"
    
    # Additional environment variables that may be present
    ark_api_key: Optional[str] = None
    volcengine_ark_api_key: Optional[str] = None
    volcengine_ark_base_url: Optional[str] = None
    cluster: Optional[str] = None
    voice_type: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "allow"  # Allow extra fields from environment
        
    @property
    def tts_api_url(self) -> str:
        """Get full TTS API URL"""
        return f"https://{self.tts_host}{self.tts_endpoint}"
    
    def validate_tts_config(self) -> bool:
        """Validate required TTS configuration"""
        required_fields = [
            self.volcengine_speech_app_id,
            self.volcengine_speech_access_token,
        ]
        return all(field is not None for field in required_fields)

# Global settings instance
settings = Settings()