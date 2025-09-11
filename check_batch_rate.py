#!/usr/bin/env python3
"""
直接测试批量采样率传递
"""
import requests
import json
import time

def test_batch_sampling_rate():
    """测试批量生成的采样率参数"""
    
    # API地址
    base_url = "http://localhost:8001"
    
    # 准备批量请求数据，选择16000Hz
    batch_request = {
        "items": [
            {
                "text": "测试文本一",
                "filename": "test1.mp3",
                "voice_type": "BV700_V2_streaming",
                "encoding": "mp3",
                "sampling_rate": 16000,  # 明确指定16000Hz
                "speed_ratio": 1.0,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
                "emotion": None,
                "language": None
            },
            {
                "text": "测试文本二",
                "filename": "test2.mp3",
                "voice_type": "BV700_V2_streaming",
                "encoding": "mp3",
                "sampling_rate": 8000,  # 明确指定8000Hz
                "speed_ratio": 1.0,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
                "emotion": None,
                "language": None
            }
        ],
        "output_dir": "./output",
        "max_concurrent": 2,
        "max_retries": 3,
        "priority": "normal",
        "filename_template": "{filename}"
    }
    
    print("=== 批量采样率测试 ===")
    print(f"发送批量请求，项目1: 16000Hz, 项目2: 8000Hz")
    print("请求内容:")
    print(json.dumps(batch_request, indent=2, ensure_ascii=False))
    
    # 发送请求
    try:
        response = requests.post(
            f"{base_url}/api/tts/batch",
            json=batch_request,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"\n请求成功！Job ID: {result.get('job_id')}")
            print("查看服务器日志确认采样率是否正确传递")
        else:
            print(f"\n请求失败: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"\n错误: {e}")

if __name__ == "__main__":
    test_batch_sampling_rate()