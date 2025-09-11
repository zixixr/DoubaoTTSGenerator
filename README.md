# 豆包 TTS Web 工具

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104.1-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

一个基于豆包（字节跳动）TTS API的现代化Web文本转语音工具，提供直观的Web界面和强大的批量处理功能。

![TTS Tool Screenshot](screenshot.png)

## ✨ 主要特性

### 🎯 核心功能
- **单文本转换**: 实时文本转语音，支持预览和下载
- **批量处理**: 高效批量转换，支持并发处理和进度跟踪  
- **数据粘贴**: 支持Tab分隔格式的批量数据导入
- **实时进度**: 基于SSE的实时进度更新和状态跟踪

### 🎵 音频配置
- **多种音色**: 支持豆包平台所有可用音色
- **灵活参数**: 语速、音量、音调精确控制（0.1-3.0倍）
- **多种格式**: 支持MP3、WAV、PCM、OGG Opus格式
- **采样率选择**: 8kHz、16kHz、24kHz可选

### 🚀 高级功能
- **智能队列**: 异步任务队列，支持优先级管理
- **成本控制**: 内置使用量统计和成本监控
- **文件管理**: 自动文件组织和批量下载
- **错误恢复**: 智能重试机制和错误处理

## 🚀 快速开始

### 环境要求

- Python 3.8+
- 豆包 TTS API访问令牌

### 1. 安装依赖

```bash
# 克隆项目
git clone <your-repository-url>
cd DoubaoTTSTest

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境

创建 `.env` 文件：

```env
# 豆包 TTS API 配置
DOUBAO_ACCESS_TOKEN=your_access_token_here
VOLCENGINE_SPEECH_ACCESS_TOKEN=your_access_token_here

# 应用配置（可选）
PORT=8001
HOST=127.0.0.1
DEBUG=False
```

### 3. 配置TTS参数

编辑 `tts_config.json` 和 `voice_config.json` 文件，配置默认的TTS参数和可用音色。

### 4. 启动应用

```bash
# 开发模式
python -m uvicorn app.main:app --reload --port 8001

# 生产模式
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### 5. 访问应用

打开浏览器访问 `http://localhost:8001`

## 📖 使用说明

### 单文本转换

1. 在"直接输入"标签页输入文本
2. 选择音色和调整音频参数
3. 点击"生成音频"或"预览"
4. 播放试听或下载音频文件

### 批量处理

1. 切换到"批量处理"标签页
2. 点击"🗂️ 粘贴数据"导入批量数据，或手动添加项目
3. 配置音频参数（应用于所有项目）
4. 点击"批量生成"开始处理
5. 查看实时进度，下载完成的文件

#### 批量数据格式

支持Tab分隔格式，如：

```
当前设备未授权	auth_fail
进入配网模式,请使用小程序配置网络	wificonfig
当前设备电量低，请充电	bat_low
```

每行格式：`文本内容[Tab]文件名`

## 📁 项目结构

```
DoubaoTTSTest/
├── app/                    # 应用核心代码
│   ├── main.py            # FastAPI主应用
│   ├── core/              # 核心配置
│   ├── services/          # 业务逻辑服务
│   │   ├── tts_service.py     # TTS API服务
│   │   ├── queue_manager.py   # 队列管理
│   │   ├── file_manager.py    # 文件管理
│   │   ├── usage_tracker.py   # 使用统计
│   │   └── ...
│   └── api/               # API路由
├── templates/             # HTML模板
│   └── index.html        # 主页面
├── static/               # 静态资源
│   ├── css/              # 样式文件
│   └── js/               # JavaScript文件
├── output/               # 生成的音频文件
├── tts_config.json       # TTS配置
├── voice_config.json     # 音色配置
├── requirements.txt      # Python依赖
└── README.md            # 项目说明
```

## ⚙️ API文档

启动应用后，访问以下地址查看API文档：

- Swagger UI: `http://localhost:8001/docs`
- ReDoc: `http://localhost:8001/redoc`

### 主要API端点

- `POST /api/tts/generate` - 单个文本转语音
- `POST /api/tts/batch` - 批量处理任务
- `GET /api/voices` - 获取可用音色列表
- `GET /api/progress/sse` - 实时进度推送（SSE）
- `GET /api/files/{filename}` - 下载音频文件

## 🛠️ 开发说明

### 技术栈

- **后端**: FastAPI + Python 3.8+
- **前端**: HTML5 + JavaScript + Tailwind CSS
- **API**: 豆包 TTS (字节跳动火山引擎)
- **异步**: asyncio + aiohttp
- **实时通信**: Server-Sent Events (SSE)

### 开发模式启动

```bash
# 启动开发服务器（自动重载）
python -m uvicorn app.main:app --reload --port 8001

# 运行测试
python -m pytest

# 代码格式化
black app/
```

### 配置说明

#### tts_config.json
主要配置豆包TTS API的连接参数和默认音频设置

#### voice_config.json  
配置可用的音色列表和对应的情感/风格选项

## 📋 功能特色

### 🎛️ 智能批量处理
- 支持Tab分隔数据粘贴导入
- 并发处理提升效率
- 实时进度跟踪和状态更新
- 智能错误重试和恢复

### 🎨 现代化界面
- 响应式设计，支持移动端
- 直观的参数调节界面
- 实时音频预览和播放
- 清晰的进度指示和状态反馈

### 🔧 企业级功能
- 文件自动管理和归档
- 使用量统计和成本监控
- 完整的错误日志和调试信息
- 支持批量下载和ZIP打包

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个项目！

### 开发流程

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启Pull Request

## 📄 许可证

本项目基于 MIT 许可证开源 - 查看 [LICENSE](LICENSE) 文件了解详情

## 🙏 致谢

- [豆包TTS](https://www.volcengine.com/products/tts) - 提供高质量的文本转语音服务
- [FastAPI](https://fastapi.tiangolo.com/) - 现代化的Python Web框架
- [Tailwind CSS](https://tailwindcss.com/) - 实用优先的CSS框架

## 📞 支持

如果您遇到问题或有建议，请：

1. 查看 [Issues](../../issues) 中的已知问题
2. 创建新的 [Issue](../../issues/new) 描述您的问题
3. 参考API文档和配置说明

---

**享受文本转语音的便利！** 🎵