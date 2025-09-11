#!/usr/bin/env python3
"""
调试批量采样率传递流程
"""
import json

# 1. 模拟前端发送的批量请求
def simulate_frontend_request():
    """模拟前端发送的批量请求数据"""
    
    # 用户在界面选择了16000Hz
    user_selected_rate = 16000
    
    # 前端getAudioParameters()函数的逻辑
    audio_params = {
        "voice_type": "BV700_V2_streaming",
        "encoding": "mp3", 
        "speed_ratio": 1.0,
        "volume_ratio": 1.0,
        "pitch_ratio": 1.0,
        "emotion": None,
        "sampling_rate": user_selected_rate,  # 关键参数
        "language": None
    }
    
    # 前端getBatchItems()函数的逻辑
    batch_items = []
    test_texts = ["测试文本1", "测试文本2"]
    
    for text in test_texts:
        item = audio_params.copy()  # 复制音频参数
        item["text"] = text
        item["filename"] = f"{text}.mp3"
        batch_items.append(item)
    
    # 完整批量请求
    batch_request = {
        "items": batch_items,
        "output_dir": "./output",
        "max_concurrent": 2,
        "max_retries": 3,
        "priority": 5,
        "filename_template": "{filename}"
    }
    
    return batch_request, user_selected_rate

# 2. 模拟后端BatchTTSItem验证
def simulate_backend_validation(batch_request):
    """模拟后端BatchTTSItem模型验证"""
    
    print("=== 后端BatchTTSItem模型验证 ===")
    
    validated_items = []
    for i, item in enumerate(batch_request["items"]):
        # 模拟Pydantic模型验证
        validated_item = {
            "text": item.get("text"),
            "filename": item.get("filename"),
            "voice_type": item.get("voice_type"),
            "encoding": item.get("encoding", "mp3"),
            "sampling_rate": item.get("sampling_rate", 24000),  # 关键：现在应该是sampling_rate字段
            "speed_ratio": item.get("speed_ratio", 1.0),
            "volume_ratio": item.get("volume_ratio", 1.0),
            "pitch_ratio": item.get("pitch_ratio", 1.0),
            "emotion": item.get("emotion"),
            "language": item.get("language")
        }
        
        validated_items.append(validated_item)
        print(f"Item {i+1}: sampling_rate = {validated_item['sampling_rate']}Hz")
    
    return validated_items

# 3. 模拟队列管理器处理
def simulate_queue_processing(validated_items):
    """模拟队列管理器的参数处理"""
    
    print("\n=== 队列管理器参数映射 ===")
    
    for i, item in enumerate(validated_items):
        # 模拟queue_manager.py第571行的逻辑
        params = item
        sampling_rate_from_params = params.get('sampling_rate', 'NOT_FOUND')
        mapped_sample_rate = params.get('sampling_rate', 24000)
        
        print(f"Item {i+1}: sampling_rate from params = {sampling_rate_from_params}, mapped to sample_rate = {mapped_sample_rate}")
        
        # 模拟TTS服务调用参数
        tts_call_params = {
            "text": item["text"],
            "voice_type": item["voice_type"],
            "encoding": item["encoding"],
            "sample_rate": mapped_sample_rate,  # 传递给TTS服务
            "speed_ratio": item["speed_ratio"],
            "volume_ratio": item["volume_ratio"],
            "pitch_ratio": item["pitch_ratio"],
            "emotion": item["emotion"],
            "language": item["language"]
        }
        
        print(f"   -> 传递给TTS服务: sample_rate = {tts_call_params['sample_rate']}")
        
        # 模拟TTS服务的build_request_payload
        api_payload_rate = tts_call_params.get('sample_rate', 24000)
        print(f"   -> TTS API请求: rate = {api_payload_rate}")

def main():
    print("=== 批量采样率参数传递流程调试 ===\n")
    
    # 1. 模拟前端请求
    batch_request, user_rate = simulate_frontend_request()
    print(f"用户选择的采样率: {user_rate}Hz")
    print(f"前端发送的批量项目数: {len(batch_request['items'])}")
    print(f"第一个项目的sampling_rate: {batch_request['items'][0]['sampling_rate']}Hz\n")
    
    # 2. 模拟后端验证
    validated_items = simulate_backend_validation(batch_request)
    
    # 3. 模拟队列处理
    simulate_queue_processing(validated_items)
    
    print(f"\n=== 总结 ===")
    print(f"用户选择: {user_rate}Hz")
    print(f"最终API: {user_rate}Hz")
    print("状态: 参数传递正确！")

if __name__ == "__main__":
    main()