---
name: 做一个调用TTS生成音频的工具
status: completed
created: 2025-09-05T16:52:51Z
progress: 100%
prd: .claude/prds/做一个调用TTS生成音频的工具.md
github: https://github.com/zixixr/DoubaoTTSGenerator/issues/1
last_sync: 2025-09-06T03:50:06Z
---

# Epic: 做一个调用TTS生成音频的工具

## Overview

构建一个轻量级的TTS音频生成工具，采用Python FastAPI后端和简洁的HTML/JavaScript前端。利用现有的豆包TTS API和配置文件，通过最小化开发工作量实现核心功能。重点关注批量处理能力和用户友好的界面，避免过度工程化。

## Architecture Decisions

### 简化的技术选择
- **后端**: Python FastAPI（轻量、内置异步支持、自动API文档）
- **前端**: 纯HTML + JavaScript + Tailwind CSS（避免框架复杂性）
- **任务处理**: Python asyncio（避免引入Celery/Redis等额外依赖）
- **文件存储**: 本地文件系统（无需数据库）
- **配置管理**: 复用现有JSON配置文件

### 设计原则
- **最小依赖**: 尽量使用Python标准库和最少的第三方包
- **配置驱动**: 充分利用现有tts_config.json和voice_config.json
- **渐进增强**: 先实现核心功能，后续迭代改进
- **错误友好**: 清晰的错误提示和重试机制

## Technical Approach

### Frontend Components
- **单页应用**: index.html作为主界面
- **文本输入区**: 支持直接粘贴和文件上传（txt格式优先）
- **配置面板**: 基于voice_config.json动态生成音色选择器
- **批处理控制**: 简单的队列显示和进度条
- **文件命名**: 两列表格（文本|文件名）

### Backend Services
- **核心API端点**:
  - `POST /api/tts/generate` - 单个TTS请求
  - `POST /api/tts/batch` - 批量处理
  - `GET /api/voices` - 获取可用音色列表
  - `GET /api/config` - 获取当前配置
  - `POST /api/config` - 更新配置

- **TTS服务封装**:
  - 基于tts_http_demo.py改造
  - 添加重试逻辑和错误处理
  - 实现字数统计和限制

- **文件管理**:
  - 自动创建输出目录
  - 支持自定义命名模板
  - 文件去重检查

### Infrastructure
- **部署方式**: 本地运行，使用uvicorn服务器
- **配置热重载**: 监听配置文件变化
- **日志记录**: 使用Python logging模块
- **错误监控**: 简单的错误计数和告警

## Implementation Strategy

### 开发阶段
1. **Phase 1 - MVP（2天）**:
   - 基础API封装
   - 简单Web界面
   - 单文本TTS生成

2. **Phase 2 - 批处理（2天）**:
   - 批量处理逻辑
   - 进度显示
   - 文件命名系统

3. **Phase 3 - 优化（1天）**:
   - UI美化
   - 错误处理完善
   - 性能优化

### 风险缓解
- API密钥安全：使用环境变量，不硬编码
- 并发限制：使用asyncio信号量控制并发数
- 大文件处理：分块处理，避免内存溢出

### 测试方法
- 单元测试：核心TTS服务函数
- 集成测试：API端点测试
- 手动测试：UI交互和批处理流程

## Task Breakdown Preview

简化后的任务列表（共8个任务）：

- [ ] **Task 1**: 设置项目结构和依赖安装
- [ ] **Task 2**: 实现TTS API服务封装（基于现有demo）
- [ ] **Task 3**: 创建FastAPI后端核心端点
- [ ] **Task 4**: 开发基础Web界面（HTML/JS）
- [ ] **Task 5**: 实现批处理逻辑和队列管理
- [ ] **Task 6**: 添加文件管理和命名系统
- [ ] **Task 7**: 实现配置管理和成本控制
- [ ] **Task 8**: UI优化和错误处理完善

## Dependencies

### 外部依赖
- 豆包TTS API（已有demo和配置）
- Python 3.8+环境
- 网络连接

### Python包依赖（最小化）
- fastapi
- uvicorn
- python-multipart（文件上传）
- aiofiles（异步文件操作）
- python-dotenv（环境变量）

### 内部依赖
- tts_config.json（已存在）
- voice_config.json（已存在）
- .env文件（API密钥）

## Success Criteria (Technical)

### 性能指标
- 单个请求处理时间 < 3秒（1000字内）
- 批量处理支持至少3个并发请求
- 内存使用 < 500MB

### 质量标准
- 零配置启动（使用默认配置）
- API调用成功率 > 95%
- 错误恢复率 > 90%

### 可用性要求
- 一键启动脚本
- 清晰的使用说明
- 浏览器兼容性（Chrome/Edge/Firefox）

## Estimated Effort

### 时间估算
- **总工期**: 5个工作日
- **开发**: 4天
- **测试和优化**: 1天

### 资源需求
- 1名全栈开发人员
- 本地开发环境
- 豆包TTS API访问权限

### 关键路径
1. API服务封装（Day 1）
2. 后端实现（Day 2）
3. 前端开发（Day 3）
4. 批处理功能（Day 4）
5. 测试优化（Day 5）

## Simplification Notes

### 相比PRD的简化
1. **技术栈简化**: 不使用React/Celery/Redis，改用原生方案
2. **功能精简**: 暂不实现文档导入（docx/pdf）、主题切换、使用统计
3. **部署简化**: 本地运行，不考虑生产部署
4. **存储简化**: 不使用数据库，配置和日志均使用文件

### 利用现有资源
1. 直接改造tts_http_demo.py
2. 复用所有JSON配置结构
3. 使用现有的音色映射关系

### 后续可扩展
- 添加更多文件格式支持
- 实现用户认证
- 部署到云服务
- 添加使用统计仪表板

## Tasks Created
- [x] #2 - 设置项目结构和依赖安装 (parallel: false)
- [x] #3 - 实现TTS API服务封装 (parallel: true)
- [x] #4 - 创建FastAPI后端核心端点 (parallel: true)
- [x] #5 - 开发基础Web界面 (parallel: true)
- [x] #6 - 实现批处理逻辑和队列管理 (parallel: false)
- [x] #7 - 添加文件管理和命名系统 (parallel: true)
- [x] #8 - 实现配置管理和成本控制 (parallel: true)
- [x] #9 - UI优化和错误处理完善 (parallel: false)

Total tasks: 8
Parallel tasks: 5
Sequential tasks: 3
Estimated total effort: 47 hours (约6个工作日)
