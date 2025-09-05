#!/usr/bin/env python3
"""
Simple test script to verify the TTS web interface functionality
"""

import requests
import json
import time

BASE_URL = "http://127.0.0.1:8001"

def test_endpoints():
    """Test all API endpoints"""
    print("Testing TTS Web Interface...")
    
    # Test 1: Health check
    print("\n1. Testing health endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Service Status: {data.get('service_status', 'unknown')}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Test 2: Web interface
    print("\n2. Testing web interface...")
    try:
        response = requests.get(BASE_URL)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            print(f"   Content-Type: {response.headers.get('content-type')}")
            print(f"   Page size: {len(response.text)} bytes")
            if "TTS音频生成工具" in response.text:
                print("   ✓ HTML template loaded correctly")
            else:
                print("   ✗ HTML template not found")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Test 3: Static files
    print("\n3. Testing static files...")
    static_files = [
        "/static/js/app.js",
        "/static/css/styles.css"
    ]
    
    for file_path in static_files:
        try:
            response = requests.head(f"{BASE_URL}{file_path}")
            print(f"   {file_path}: {response.status_code}")
        except Exception as e:
            print(f"   {file_path}: Error - {e}")
    
    # Test 4: API endpoints
    print("\n4. Testing API endpoints...")
    api_endpoints = [
        "/api/voices",
        "/api/config",
        "/api"
    ]
    
    for endpoint in api_endpoints:
        try:
            response = requests.get(f"{BASE_URL}{endpoint}")
            print(f"   {endpoint}: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                if endpoint == "/api/voices":
                    print(f"      Available voices: {data.get('total_count', 0)}")
                elif endpoint == "/api/config":
                    print(f"      Audio config: {data.get('audio', {}).get('encoding', 'unknown')}")
        except Exception as e:
            print(f"   {endpoint}: Error - {e}")
    
    # Test 5: TTS generation (small sample)
    print("\n5. Testing TTS generation...")
    try:
        tts_payload = {
            "text": "这是一个测试",
            "voice_type": "BV001_streaming",
            "encoding": "mp3",
            "speed_ratio": 1.0,
            "volume_ratio": 1.0,
            "pitch_ratio": 1.0
        }
        
        response = requests.post(
            f"{BASE_URL}/api/tts/generate",
            json=tts_payload,
            timeout=30
        )
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print(f"   ✓ TTS generation successful")
                print(f"   Audio size: {data.get('file_size', 0)} bytes")
                print(f"   Text length: {data.get('text_length', 0)} characters")
                if data.get('audio_data'):
                    print("   ✓ Audio data returned (base64)")
            else:
                print(f"   ✗ TTS generation failed: {data.get('message', 'unknown error')}")
        else:
            error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
            print(f"   ✗ Request failed: {error_data}")
            
    except requests.exceptions.Timeout:
        print("   ⏱ Request timed out (this may be normal for TTS generation)")
    except Exception as e:
        print(f"   Error: {e}")

def main():
    """Main test function"""
    print("=" * 60)
    print("TTS Web Interface Test")
    print("=" * 60)
    
    # Wait a moment for server to be ready
    time.sleep(1)
    
    test_endpoints()
    
    print("\n" + "=" * 60)
    print("Test completed!")
    print("Open http://127.0.0.1:8001 in your browser to test the web interface.")
    print("=" * 60)

if __name__ == "__main__":
    main()