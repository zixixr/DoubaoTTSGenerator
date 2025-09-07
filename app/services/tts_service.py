"""
TTS Service for Doubao TTS API integration

This module provides an asynchronous TTS service with error handling,
retry logic, and comprehensive configuration support.
"""

import asyncio
import base64
import json
import logging
import os
import uuid
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import aiohttp
import aiofiles
from datetime import datetime
import time

from .file_manager import FileManager


class TTSServiceError(Exception):
    """Base exception for TTS service errors"""
    pass


class TTSConfigError(TTSServiceError):
    """Configuration-related errors"""
    pass


class TTSAPIError(TTSServiceError):
    """API-related errors"""
    pass


class TTSService:
    """
    Asynchronous TTS service for Doubao TTS API
    
    Features:
    - Async HTTP requests with aiohttp
    - Configurable retry logic with exponential backoff
    - Text validation and character counting
    - Support for multiple audio formats
    - Comprehensive error handling and logging
    - Voice and emotion configuration
    """
    
    def __init__(self, config_path: Optional[str] = None, voice_config_path: Optional[str] = None,
                 file_manager: Optional[FileManager] = None):
        """
        Initialize TTS service
        
        Args:
            config_path: Path to tts_config.json file
            voice_config_path: Path to voice_config.json file
            file_manager: Optional file manager instance
        """
        self.logger = logging.getLogger(__name__)
        
        # Configuration paths
        self.config_path = config_path or "tts_config.json"
        self.voice_config_path = voice_config_path or "voice_config.json"
        
        # Configuration data
        self.config: Dict[str, Any] = {}
        self.voice_config: Dict[str, Any] = {}
        
        # HTTP session
        self.session: Optional[aiohttp.ClientSession] = None
        
        # File manager
        self.file_manager = file_manager
        
        # Retry configuration
        self.max_retries = 3
        self.base_delay = 1.0
        self.max_delay = 60.0
        self.backoff_factor = 2.0
        
        # Text limits
        self.max_text_length = 1024  # UTF-8 bytes
        
        # Initialize
        self._load_configurations()
        self._setup_logging()
    
    def _setup_logging(self):
        """Setup logging configuration"""
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def _load_configurations(self):
        """Load TTS and voice configurations from JSON files"""
        try:
            # Load main TTS configuration
            if not os.path.exists(self.config_path):
                raise TTSConfigError(f"TTS config file not found: {self.config_path}")
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
                
            # Load voice configuration
            if not os.path.exists(self.voice_config_path):
                raise TTSConfigError(f"Voice config file not found: {self.voice_config_path}")
                
            with open(self.voice_config_path, 'r', encoding='utf-8') as f:
                self.voice_config = json.load(f)
                
            self.logger.info("Configurations loaded successfully")
            
        except json.JSONDecodeError as e:
            raise TTSConfigError(f"Invalid JSON in config file: {e}")
        except Exception as e:
            raise TTSConfigError(f"Error loading configurations: {e}")
    
    def reload_config(self):
        """Reload configuration files"""
        self.logger.info("Reloading configurations...")
        self._load_configurations()
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
    
    async def start(self):
        """Start the HTTP session"""
        if self.session is None:
            connector = aiohttp.TCPConnector(
                limit=10,
                ttl_dns_cache=300,
                use_dns_cache=True
            )
            timeout = aiohttp.ClientTimeout(total=60)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={'User-Agent': 'DoubaoTTS/1.0'}
            )
            self.logger.info("HTTP session started")
    
    async def close(self):
        """Close the HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None
            self.logger.info("HTTP session closed")
    
    def get_api_url(self) -> str:
        """Get the complete API URL"""
        api_config = self.config.get('api', {})
        host = api_config.get('host', 'openspeech.bytedance.com')
        endpoint = api_config.get('endpoint', '/api/v1/tts')
        return f"https://{host}{endpoint}"
    
    def get_auth_header(self) -> Dict[str, str]:
        """Get authorization header"""
        # Try environment variable first, then config
        access_token = os.getenv('DOUBAO_ACCESS_TOKEN')
        if not access_token:
            access_token = self.config.get('app', {}).get('token')
        
        if not access_token or access_token == 'access_token':
            raise TTSConfigError("Access token not configured. Set DOUBAO_ACCESS_TOKEN env var or update config.")
        
        return {"Authorization": f"Bearer;{access_token}"}
    
    def count_characters(self, text: str) -> Dict[str, int]:
        """
        Count characters in text
        
        Args:
            text: Input text
            
        Returns:
            Dict with character counts: total, utf8_bytes, chinese, english, numbers, punctuation
        """
        import re
        
        utf8_bytes = len(text.encode('utf-8'))
        total_chars = len(text)
        
        # Count different character types
        chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
        english = len(re.findall(r'[a-zA-Z]', text))
        numbers = len(re.findall(r'\d', text))
        punctuation = len(re.findall(r'[^\w\s\u4e00-\u9fff]', text))
        spaces = len(re.findall(r'\s', text))
        
        return {
            'total_chars': total_chars,
            'utf8_bytes': utf8_bytes,
            'chinese': chinese,
            'english': english,
            'numbers': numbers,
            'punctuation': punctuation,
            'spaces': spaces
        }
    
    def validate_text(self, text: str) -> Tuple[bool, str]:
        """
        Validate text for TTS generation
        
        Args:
            text: Input text to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not text or not text.strip():
            return False, "Text cannot be empty"
        
        text = text.strip()
        char_info = self.count_characters(text)
        
        # Check UTF-8 byte length limit
        if char_info['utf8_bytes'] > self.max_text_length:
            return False, f"Text too long: {char_info['utf8_bytes']} bytes (max {self.max_text_length})"
        
        # Check for unsupported characters (basic validation)
        if len(text) > 10000:  # Reasonable character limit
            return False, "Text exceeds reasonable length limit (10,000 characters)"
        
        return True, ""
    
    def split_text(self, text: str, max_length: Optional[int] = None) -> List[str]:
        """
        Split text into chunks that fit within the API limits
        
        Args:
            text: Input text to split
            max_length: Maximum UTF-8 bytes per chunk (default: use config limit)
            
        Returns:
            List of text chunks
        """
        if max_length is None:
            max_length = self.max_text_length
        
        text = text.strip()
        if not text:
            return []
        
        # If text fits within limit, return as is
        if len(text.encode('utf-8')) <= max_length:
            return [text]
        
        # Split by sentences first (Chinese and English punctuation)
        import re
        sentences = re.split(r'[。！？.!?]\s*', text)
        
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            if not sentence.strip():
                continue
                
            sentence = sentence.strip()
            # Add back punctuation if it was split off
            if sentence and not sentence[-1] in '。！？.!?':
                sentence += '。'
            
            # Check if adding this sentence would exceed limit
            test_chunk = current_chunk + (' ' if current_chunk else '') + sentence
            if len(test_chunk.encode('utf-8')) <= max_length:
                current_chunk = test_chunk
            else:
                # Add current chunk if not empty
                if current_chunk:
                    chunks.append(current_chunk)
                
                # Check if single sentence is too long
                if len(sentence.encode('utf-8')) > max_length:
                    # Split long sentence by characters (emergency fallback)
                    words = sentence.split()
                    temp_chunk = ""
                    for word in words:
                        test_word_chunk = temp_chunk + (' ' if temp_chunk else '') + word
                        if len(test_word_chunk.encode('utf-8')) <= max_length:
                            temp_chunk = test_word_chunk
                        else:
                            if temp_chunk:
                                chunks.append(temp_chunk)
                            temp_chunk = word
                    if temp_chunk:
                        current_chunk = temp_chunk
                else:
                    current_chunk = sentence
        
        # Add the last chunk
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
    
    def get_available_voices(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get available voices from voice configuration
        
        Returns:
            Dictionary with voice categories and their voices
        """
        online_voices = self.voice_config.get('online_voices', {})
        result = {}
        
        # Process Chinese voices
        chinese_voices = online_voices.get('chinese', {})
        for category, voices in chinese_voices.items():
            if category not in result:
                result[category] = []
            result[category].extend(voices)
        
        # Process multilingual voices
        multilingual_voices = online_voices.get('multilingual', {})
        for language, voices in multilingual_voices.items():
            category_name = f"multilingual_{language}"
            result[category_name] = voices
        
        # Process dialects
        dialects = online_voices.get('dialects', [])
        if dialects:
            result['dialects'] = dialects
        
        return result
    
    def get_voice_by_type(self, voice_type: str) -> Optional[Dict[str, Any]]:
        """
        Find voice configuration by voice_type
        
        Args:
            voice_type: Voice type identifier
            
        Returns:
            Voice configuration dict or None if not found
        """
        all_voices = self.get_available_voices()
        
        for category_voices in all_voices.values():
            for voice in category_voices:
                if voice.get('voice_type') == voice_type:
                    return voice
        
        return None
    
    async def _make_request_with_retry(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make HTTP request with retry logic
        
        Args:
            request_data: Request payload
            
        Returns:
            API response data
            
        Raises:
            TTSAPIError: When all retries are exhausted
        """
        if not self.session:
            await self.start()
        
        url = self.get_api_url()
        headers = self.get_auth_header()
        headers['Content-Type'] = 'application/json'
        
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                self.logger.info(f"Making TTS API request (attempt {attempt + 1}/{self.max_retries + 1})")
                
                # Send JSON data as raw string to match official demo exactly
                async with self.session.post(url, data=json.dumps(request_data), headers=headers) as response:
                    response_text = await response.text()
                    
                    if response.status == 200:
                        try:
                            response_data = json.loads(response_text)
                            
                            # Check for API errors in response
                            if 'error' in response_data:
                                error_msg = response_data['error'].get('message', 'Unknown API error')
                                raise TTSAPIError(f"API error: {error_msg}")
                            
                            if 'data' not in response_data:
                                raise TTSAPIError("No audio data in response")
                            
                            self.logger.info("TTS API request successful")
                            return response_data
                            
                        except json.JSONDecodeError:
                            raise TTSAPIError(f"Invalid JSON response: {response_text[:200]}...")
                    
                    else:
                        error_msg = f"HTTP {response.status}: {response_text[:200]}"
                        if response.status >= 500:
                            # Server error - retry
                            raise aiohttp.ClientError(error_msg)
                        else:
                            # Client error - don't retry
                            raise TTSAPIError(error_msg)
            
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = min(self.base_delay * (self.backoff_factor ** attempt), self.max_delay)
                    self.logger.warning(f"Request failed, retrying in {delay:.1f}s: {e}")
                    await asyncio.sleep(delay)
                else:
                    break
            
            except TTSAPIError:
                # Don't retry API errors
                raise
        
        # All retries exhausted
        raise TTSAPIError(f"Request failed after {self.max_retries + 1} attempts. Last error: {last_exception}")
    
    def build_request_payload(self, text: str, voice_type: Optional[str] = None, 
                            encoding: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Build TTS API request payload matching official demo format
        
        Args:
            text: Text to synthesize
            voice_type: Voice type (optional, uses config default)
            encoding: Audio encoding (optional, uses config default)
            **kwargs: Additional audio parameters (speed_ratio, volume_ratio, etc.)
            
        Returns:
            Request payload dictionary
        """
        # Build minimal request payload matching official demo exactly
        request_data = {
            "app": {
                "appid": self.config['app']['appid'],
                "token": "access_token",  # Use literal string as in demo
                "cluster": self.config['app']['cluster']
            },
            "user": self.config['user'].copy(),
            "audio": {
                "voice_type": voice_type or self.config['audio']['voice_type'],
                "encoding": encoding or self.config['audio']['encoding'],
                "rate": kwargs.get('sample_rate', self.config['audio'].get('rate', 24000)),
                "speed_ratio": kwargs.get('speed_ratio', self.config['audio'].get('speed_ratio', 1.0)),
                "volume_ratio": kwargs.get('volume_ratio', self.config['audio'].get('volume_ratio', 1.0)),
                "pitch_ratio": kwargs.get('pitch_ratio', self.config['audio'].get('pitch_ratio', 1.0)),
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": "plain",
                "operation": "query",
                "with_frontend": 1,
                "frontend_type": "unitTson"
            }
        }
        
        # Debug: Log the rate being sent to API 
        self.logger.info(f"TTS API request - rate: {request_data['audio']['rate']}Hz, sample_rate in kwargs: {kwargs.get('sample_rate', 'NOT_PROVIDED')}")
        
        return request_data
    
    async def synthesize_speech(self, text: str, voice_type: Optional[str] = None,
                              encoding: str = "mp3", sample_rate: Optional[int] = None, **kwargs) -> bytes:
        """
        Synthesize speech from text
        
        Args:
            text: Text to synthesize
            voice_type: Voice type (optional)
            encoding: Audio encoding format
            **kwargs: Additional parameters
            
        Returns:
            Audio data as bytes
            
        Raises:
            TTSServiceError: For various error conditions
        """
        # Validate text
        is_valid, error_msg = self.validate_text(text)
        if not is_valid:
            raise TTSServiceError(f"Text validation failed: {error_msg}")
        
        # Build request payload
        # Include sample_rate in kwargs if provided
        if sample_rate is not None:
            kwargs['sample_rate'] = sample_rate
        request_data = self.build_request_payload(text, voice_type, encoding, **kwargs)
        
        # Make API request
        response_data = await self._make_request_with_retry(request_data)
        
        # Extract and decode audio data
        audio_data_b64 = response_data['data']
        try:
            audio_bytes = base64.b64decode(audio_data_b64)
            self.logger.info(f"Successfully synthesized {len(audio_bytes)} bytes of audio")
            return audio_bytes
        except Exception as e:
            raise TTSServiceError(f"Failed to decode audio data: {e}")
    
    async def synthesize_to_file(self, text: str, output_path: str, 
                               voice_type: Optional[str] = None, encoding: str = "mp3",
                               use_file_manager: bool = False, custom_filename: Optional[str] = None,
                               filename_template: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Synthesize speech and save to file
        
        Args:
            text: Text to synthesize
            output_path: Output file path (or base directory if using file manager)
            voice_type: Voice type (optional)
            encoding: Audio encoding format
            use_file_manager: Whether to use advanced file management
            custom_filename: Custom filename (when using file manager)
            filename_template: Custom filename template (when using file manager)
            **kwargs: Additional parameters
            
        Returns:
            Dictionary with synthesis info (file_path, file_size, duration, etc.)
        """
        start_time = time.time()
        
        # Synthesize audio
        audio_bytes = await self.synthesize_speech(text, voice_type, encoding, **kwargs)
        
        final_file_path = output_path
        file_manager_result = None
        
        # ULTIMATE EXTENSION FIX: Ensure output_path has proper extension BEFORE any processing
        expected_ext = f".{encoding.lower()}"
        if encoding.lower() == 'pcm':
            expected_ext = '.wav'
        
        if not str(output_path).lower().endswith(expected_ext):
            original_path = output_path
            output_path = f"{output_path}{expected_ext}"
            final_file_path = output_path  # Update final_file_path too
            self.logger.info(f"ULTIMATE EXTENSION FIX: Added {expected_ext} to {original_path} -> {output_path}")
        else:
            self.logger.info(f"ULTIMATE DEBUG: Path already has extension: {output_path}")
        
        # Use file manager if available and requested
        self.logger.info(f"TTS debug - use_file_manager: {use_file_manager}, has_file_manager: {self.file_manager is not None}")
        if use_file_manager and self.file_manager:
            # Build context for file manager
            char_info = self.count_characters(text)
            voice_info = self.get_voice_by_type(voice_type) if voice_type else {}
            
            context = {
                'text': text,
                'text_length': char_info['total_chars'],
                'voice_type': voice_type or self.config.get('audio', {}).get('voice_type'),
                'voice_name': voice_info.get('name', ''),
                'encoding': encoding,
                'language': kwargs.get('language') or voice_info.get('languages', [''])[0] if voice_info.get('languages') else '',
                'emotion': kwargs.get('emotion', ''),
                'category': 'tts_generated',
                # Add batch_id if provided (for batch processing isolation)
                'batch_id': kwargs.get('batch_id') if kwargs.get('batch_id') else None,
                # Add audio parameters to context for conflict resolution
                'rate': kwargs.get('sample_rate', self.config.get('audio', {}).get('rate', 24000)),
                'speed_ratio': kwargs.get('speed_ratio', 1.0),
                'pitch_ratio': kwargs.get('pitch_ratio', 1.0),
                'volume_ratio': kwargs.get('volume_ratio', 1.0)
            }
            
            # Save using file manager
            file_manager_result = await self.file_manager.save_file_with_management(
                audio_data=audio_bytes,
                context=context,
                custom_filename=custom_filename,
                template=filename_template
            )
            
            if file_manager_result['success']:
                final_file_path = file_manager_result['file_path']
            else:
                self.logger.warning(f"File manager failed, falling back to direct save: {file_manager_result.get('error')}")
                # Fall back to direct save below
                use_file_manager = False
        
        # Direct file save (fallback or when not using file manager)
        if not use_file_manager or not file_manager_result or not file_manager_result['success']:
            # DEBUG: Check what output_path we have
            self.logger.info(f"TTS DEBUG: output_path before extension fix: {output_path}")
            
            # EXTENSION FIX: Ensure output path has proper extension
            expected_ext = f".{encoding.lower()}"
            if encoding.lower() == 'pcm':
                expected_ext = '.wav'
            
            self.logger.info(f"TTS DEBUG: expected_ext: {expected_ext}, path ends with ext: {str(output_path).lower().endswith(expected_ext)}")
            
            if not str(output_path).lower().endswith(expected_ext):
                original_path = output_path
                output_path = f"{output_path}{expected_ext}"
                self.logger.info(f"TTS EXTENSION FIX: Added {expected_ext} to {original_path} -> {output_path}")
            else:
                self.logger.info(f"TTS DEBUG: Path already has extension: {output_path}")
            
            # Create output directory if needed
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Save to file
            async with aiofiles.open(output_path, 'wb') as f:
                await f.write(audio_bytes)
            
            final_file_path = output_path
        
        end_time = time.time()
        
        # Gather synthesis info
        char_info = self.count_characters(text)
        synthesis_info = {
            'file_path': final_file_path,
            'file_size': len(audio_bytes),
            'text_length': char_info['total_chars'],
            'utf8_bytes': char_info['utf8_bytes'],
            'voice_type': voice_type or self.config.get('audio', {}).get('voice_type'),
            'encoding': encoding,
            'synthesis_time': end_time - start_time,
            'timestamp': datetime.now().isoformat(),
            'used_file_manager': use_file_manager and file_manager_result and file_manager_result['success'],
            'file_manager_result': file_manager_result
        }
        
        self.logger.info(f"Audio saved to {final_file_path} ({len(audio_bytes)} bytes, {synthesis_info['synthesis_time']:.2f}s)")
        
        return synthesis_info
    
    async def batch_synthesize(self, text_list: List[str], output_dir: str,
                             voice_type: Optional[str] = None, encoding: str = "mp3",
                             filename_template: str = "tts_{index}_{timestamp}.{ext}",
                             max_concurrent: int = 3, **kwargs) -> List[Dict[str, Any]]:
        """
        Batch synthesize multiple texts
        
        Args:
            text_list: List of texts to synthesize
            output_dir: Output directory
            voice_type: Voice type (optional)
            encoding: Audio encoding format
            filename_template: Filename template (supports {index}, {timestamp}, {ext})
            max_concurrent: Maximum concurrent requests
            **kwargs: Additional parameters
            
        Returns:
            List of synthesis info dictionaries
        """
        if not text_list:
            return []
        
        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Prepare tasks
        semaphore = asyncio.Semaphore(max_concurrent)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        async def synthesize_single(index: int, text: str) -> Dict[str, Any]:
            async with semaphore:
                try:
                    # Generate filename
                    ext = encoding.lower()
                    if ext == 'pcm':
                        ext = 'wav'  # PCM is typically in WAV container
                    
                    filename = filename_template.format(
                        index=index + 1,
                        timestamp=timestamp,
                        ext=ext
                    )
                    output_path = os.path.join(output_dir, filename)
                    
                    # Synthesize
                    result = await self.synthesize_to_file(
                        text, output_path, voice_type, encoding, **kwargs
                    )
                    result['index'] = index
                    result['success'] = True
                    result['error'] = None
                    
                    return result
                    
                except Exception as e:
                    self.logger.error(f"Failed to synthesize text {index + 1}: {e}")
                    return {
                        'index': index,
                        'success': False,
                        'error': str(e),
                        'text_length': len(text),
                        'file_path': None
                    }
        
        # Execute batch synthesis
        self.logger.info(f"Starting batch synthesis of {len(text_list)} texts (max {max_concurrent} concurrent)")
        tasks = [synthesize_single(i, text) for i, text in enumerate(text_list)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle any exceptions
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Task {i + 1} failed with exception: {result}")
                final_results.append({
                    'index': i,
                    'success': False,
                    'error': str(result),
                    'text_length': len(text_list[i]) if i < len(text_list) else 0,
                    'file_path': None
                })
            else:
                final_results.append(result)
        
        # Summary
        successful = sum(1 for r in final_results if r.get('success', False))
        self.logger.info(f"Batch synthesis completed: {successful}/{len(text_list)} successful")
        
        return final_results