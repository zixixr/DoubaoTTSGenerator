@echo off
echo 启动TTS服务器...

REM 设置环境变量
set DOUBAO_ACCESS_TOKEN=1S1ytpziyHoBscoULan0qADv1bUhA5Ht
set VOLCENGINE_SPEECH_ACCESS_TOKEN=1S1ytpziyHoBscoULan0qADv1bUhA5Ht

echo 环境变量已设置:
echo DOUBAO_ACCESS_TOKEN=%DOUBAO_ACCESS_TOKEN%

REM 启动FastAPI服务
python -m uvicorn app.main:app --reload --port 8001 --host 127.0.0.1

pause