#!/usr/bin/env python3
"""
Simple test script for the FastAPI application
"""

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app.main import app
    print("+ FastAPI app imported successfully")
    
    # Test basic imports
    from app.services.tts_service import TTSService
    print("+ TTS service imported successfully")
    
    from app.core.config import settings
    print("+ Config imported successfully")
    
    print("\nApplication is ready!")
    print(f"Server will run on: http://{settings.host}:{settings.port}")
    
except ImportError as e:
    print(f"X Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"X Error: {e}")
    sys.exit(1)