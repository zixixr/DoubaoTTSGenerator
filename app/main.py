"""
FastAPI main application for TTS Tool

This module creates the FastAPI application with all endpoints, middleware,
and configurations needed for the TTS service.
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from app.services.tts_service import TTSService, TTSServiceError, TTSAPIError, TTSConfigError
from app.services.queue_manager import QueueManager, BatchJob, JobStatus, JobPriority
from app.services.progress_broadcaster import get_progress_broadcaster
from app.core.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global service instances
tts_service: Optional[TTSService] = None
queue_manager: Optional[QueueManager] = None
progress_broadcaster = get_progress_broadcaster()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    global tts_service, queue_manager
    
    try:
        # Startup
        logger.info("Starting TTS Tool application...")
        
        # Initialize TTS service
        tts_service = TTSService()
        await tts_service.start()
        logger.info("TTS service initialized successfully")
        
        # Initialize Queue Manager
        queue_manager = QueueManager(
            storage_dir="./queue_data",
            max_concurrent_jobs=settings.concurrent_requests
        )
        await queue_manager.start()
        logger.info("Queue manager initialized successfully")
        
        yield
        
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        raise
    finally:
        # Shutdown
        if queue_manager:
            await queue_manager.stop()
        if tts_service:
            await tts_service.close()
        await progress_broadcaster.shutdown()
        logger.info("TTS Tool application shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="TTS Tool API",
    description="豆包TTS音频生成工具API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# Request/Response Models
class TTSRequest(BaseModel):
    """Single TTS generation request"""
    text: str = Field(..., description="要合成的文本", min_length=1, max_length=10000)
    voice_type: Optional[str] = Field(None, description="音色类型")
    encoding: str = Field("mp3", description="音频编码格式")
    speed_ratio: float = Field(1.0, ge=0.2, le=3.0, description="语速")
    volume_ratio: float = Field(1.0, ge=0.1, le=3.0, description="音量")
    pitch_ratio: float = Field(1.0, ge=0.1, le=3.0, description="音调")
    emotion: Optional[str] = Field(None, description="情感/风格")
    language: Optional[str] = Field(None, description="语言")
    
    @field_validator('text')
    @classmethod
    def validate_text(cls, v):
        if not v.strip():
            raise ValueError("Text cannot be empty")
        return v.strip()


class BatchTTSItem(BaseModel):
    """Batch TTS item"""
    text: str = Field(..., description="要合成的文本", min_length=1)
    filename: Optional[str] = Field(None, description="自定义文件名(不含扩展名)")
    voice_type: Optional[str] = Field(None, description="音色类型")
    encoding: str = Field("mp3", description="音频编码格式")
    speed_ratio: float = Field(1.0, ge=0.2, le=3.0, description="语速")
    volume_ratio: float = Field(1.0, ge=0.1, le=3.0, description="音量")
    pitch_ratio: float = Field(1.0, ge=0.1, le=3.0, description="音调")
    emotion: Optional[str] = Field(None, description="情感/风格")
    language: Optional[str] = Field(None, description="语言")


class BatchTTSRequest(BaseModel):
    """Batch TTS generation request"""
    items: List[BatchTTSItem] = Field(..., min_length=1, max_length=50, description="批量处理项目")
    output_dir: str = Field("./output", description="输出目录")
    max_concurrent: int = Field(3, ge=1, le=5, description="最大并发数")
    max_retries: int = Field(3, ge=0, le=5, description="最大重试次数")
    priority: str = Field("normal", description="任务优先级")
    filename_template: str = Field("tts_{index}_{timestamp}.{ext}", description="文件名模板")


class ConfigUpdateRequest(BaseModel):
    """Configuration update request"""
    voice_type: Optional[str] = Field(None, description="默认音色类型")
    encoding: Optional[str] = Field(None, description="默认音频编码格式")
    speed_ratio: Optional[float] = Field(None, ge=0.2, le=3.0, description="默认语速")
    volume_ratio: Optional[float] = Field(None, ge=0.1, le=3.0, description="默认音量")
    pitch_ratio: Optional[float] = Field(None, ge=0.1, le=3.0, description="默认音调")
    emotion: Optional[str] = Field(None, description="默认情感/风格")
    language: Optional[str] = Field(None, description="默认语言")
    max_text_length: Optional[int] = Field(None, ge=100, le=10000, description="最大文本长度")


class TTSResponse(BaseModel):
    """TTS generation response"""
    success: bool
    message: str
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    text_length: Optional[int] = None
    synthesis_time: Optional[float] = None
    voice_type: Optional[str] = None
    encoding: Optional[str] = None
    audio_data: Optional[str] = None  # Base64 encoded audio for direct response


class BatchTTSResponse(BaseModel):
    """Batch TTS response"""
    success: bool
    message: str
    job_id: str
    status: str
    submitted_at: str
    total_items: int


class VoiceInfo(BaseModel):
    """Voice information"""
    name: str
    voice_type: str
    emotions: List[str] = []
    languages: List[str] = []
    timestamp_support: bool = True


class VoicesResponse(BaseModel):
    """Available voices response"""
    categories: Dict[str, List[VoiceInfo]]
    total_count: int


class ConfigResponse(BaseModel):
    """Configuration response"""
    audio: Dict[str, Any]
    api: Dict[str, Any]
    limits: Dict[str, Any]


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: str
    version: str
    service_status: str
    queue_status: str
    

class JobControlRequest(BaseModel):
    """Job control request (pause/resume/cancel)"""
    action: str = Field(..., description="Action to perform: pause, resume, cancel, retry")
    

class JobListResponse(BaseModel):
    """Job list response"""
    jobs: List[Dict[str, Any]]
    total_count: int
    running_count: int
    completed_count: int
    failed_count: int
    

class QueueStatusResponse(BaseModel):
    """Queue status response"""
    running: bool
    queue_size: int
    running_jobs: int
    max_concurrent_jobs: int
    total_jobs: int
    stats: Dict[str, Any]
    jobs_by_status: Dict[str, int]


# Middleware for request logging and timing
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log requests with timing and add request ID"""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    
    start_time = time.time()
    logger.info(f"Request {request_id}: {request.method} {request.url}")
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.info(f"Request {request_id} completed in {process_time:.3f}s - Status: {response.status_code}")
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(round(process_time, 3))
        
        return response
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"Request {request_id} failed after {process_time:.3f}s - Error: {e}")
        raise


# Error handlers
@app.exception_handler(TTSServiceError)
async def tts_service_error_handler(request: Request, exc: TTSServiceError):
    """Handle TTS service errors"""
    request_id = getattr(request.state, 'request_id', 'unknown')
    logger.error(f"TTS Service Error in request {request_id}: {exc}")
    
    return JSONResponse(
        status_code=400,
        content={
            "error": "TTS Service Error",
            "message": str(exc),
            "request_id": request_id
        }
    )


@app.exception_handler(TTSAPIError)
async def tts_api_error_handler(request: Request, exc: TTSAPIError):
    """Handle TTS API errors"""
    request_id = getattr(request.state, 'request_id', 'unknown')
    logger.error(f"TTS API Error in request {request_id}: {exc}")
    
    return JSONResponse(
        status_code=502,
        content={
            "error": "TTS API Error",
            "message": str(exc),
            "request_id": request_id
        }
    )


@app.exception_handler(TTSConfigError)
async def tts_config_error_handler(request: Request, exc: TTSConfigError):
    """Handle TTS configuration errors"""
    request_id = getattr(request.state, 'request_id', 'unknown')
    logger.error(f"TTS Config Error in request {request_id}: {exc}")
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Configuration Error",
            "message": str(exc),
            "request_id": request_id
        }
    )


# API Endpoints
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    from datetime import datetime
    
    # Check service status
    service_status = "healthy" if tts_service else "unavailable"
    queue_status = "healthy" if queue_manager and queue_manager._running else "unavailable"
    
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        version="1.0.0",
        service_status=service_status,
        queue_status=queue_status
    )


@app.post("/api/tts/generate", response_model=TTSResponse)
async def generate_tts(request: TTSRequest):
    """Generate TTS audio for single text"""
    if not tts_service:
        raise HTTPException(status_code=503, detail="TTS service not available")
    
    try:
        logger.info(f"Generating TTS for text: {request.text[:50]}...")
        
        # Generate audio bytes
        audio_bytes = await tts_service.synthesize_speech(
            text=request.text,
            voice_type=request.voice_type,
            encoding=request.encoding,
            speed_ratio=request.speed_ratio,
            volume_ratio=request.volume_ratio,
            pitch_ratio=request.pitch_ratio,
            emotion=request.emotion,
            language=request.language
        )
        
        # Count characters
        char_info = tts_service.count_characters(request.text)
        
        # Return audio data as base64 for direct use
        import base64
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        
        return TTSResponse(
            success=True,
            message="TTS generation successful",
            file_size=len(audio_bytes),
            text_length=char_info['total_chars'],
            voice_type=request.voice_type or tts_service.config['audio']['voice_type'],
            encoding=request.encoding,
            audio_data=audio_b64
        )
        
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")


@app.post("/api/tts/batch", response_model=BatchTTSResponse)
async def batch_generate_tts(request: BatchTTSRequest):
    """Submit batch TTS generation job to queue"""
    if not tts_service or not queue_manager:
        raise HTTPException(status_code=503, detail="Services not available")
    
    try:
        logger.info(f"Submitting batch TTS job with {len(request.items)} items")
        
        # Generate job ID
        job_id = str(uuid.uuid4())
        
        # Create batch job
        job = BatchJob.from_request(job_id, {
            "items": [item.model_dump() for item in request.items],
            "output_dir": request.output_dir,
            "max_concurrent": request.max_concurrent,
            "max_retries": request.max_retries,
            "priority": request.priority,
            "filename_template": request.filename_template
        })
        
        # Set up progress callback
        def progress_callback(progress_data):
            # Use asyncio to schedule the coroutine
            asyncio.create_task(progress_broadcaster.broadcast_progress(progress_data))
        
        job.progress_callback = progress_callback
        
        # Submit to queue
        await queue_manager.submit_job(job, tts_service)
        
        # Broadcast job submission
        await progress_broadcaster.broadcast_job_status(
            job_id, "submitted", 
            {"total_items": len(request.items), "priority": request.priority}
        )
        
        return BatchTTSResponse(
            success=True,
            message=f"Batch job submitted successfully",
            job_id=job_id,
            status="queued",
            submitted_at=datetime.now().isoformat(),
            total_items=len(request.items)
        )
        
    except Exception as e:
        logger.error(f"Failed to submit batch job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to submit batch job: {str(e)}")


@app.get("/api/voices", response_model=VoicesResponse)
async def get_voices():
    """Get available voices"""
    if not tts_service:
        raise HTTPException(status_code=503, detail="TTS service not available")
    
    try:
        voices_data = tts_service.get_available_voices()
        
        # Convert to response format
        categories = {}
        total_count = 0
        
        for category, voices in voices_data.items():
            category_voices = []
            for voice in voices:
                category_voices.append(VoiceInfo(
                    name=voice.get('name', ''),
                    voice_type=voice.get('voice_type', ''),
                    emotions=voice.get('emotions', []),
                    languages=voice.get('languages', []),
                    timestamp_support=voice.get('timestamp_support', True)
                ))
            categories[category] = category_voices
            total_count += len(category_voices)
        
        return VoicesResponse(
            categories=categories,
            total_count=total_count
        )
        
    except Exception as e:
        logger.error(f"Failed to get voices: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get voices: {str(e)}")


@app.get("/api/config", response_model=ConfigResponse)
async def get_config():
    """Get current configuration"""
    if not tts_service:
        raise HTTPException(status_code=503, detail="TTS service not available")
    
    try:
        return ConfigResponse(
            audio=tts_service.config.get('audio', {}),
            api=tts_service.config.get('api', {}),
            limits={
                'max_text_length': tts_service.max_text_length,
                'max_concurrent': 10,
                'supported_encodings': ['mp3', 'wav', 'pcm', 'ogg_opus']
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to get config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get config: {str(e)}")


@app.post("/api/config", response_model=Dict[str, str])
async def update_config(request: ConfigUpdateRequest):
    """Update configuration"""
    if not tts_service:
        raise HTTPException(status_code=503, detail="TTS service not available")
    
    try:
        updated_fields = []
        
        # Update audio configuration
        if request.voice_type is not None:
            tts_service.config['audio']['voice_type'] = request.voice_type
            updated_fields.append('voice_type')
            
        if request.encoding is not None:
            tts_service.config['audio']['encoding'] = request.encoding
            updated_fields.append('encoding')
            
        if request.speed_ratio is not None:
            tts_service.config['audio']['speed_ratio'] = request.speed_ratio
            updated_fields.append('speed_ratio')
            
        if request.volume_ratio is not None:
            tts_service.config['audio']['volume_ratio'] = request.volume_ratio
            updated_fields.append('volume_ratio')
            
        if request.pitch_ratio is not None:
            tts_service.config['audio']['pitch_ratio'] = request.pitch_ratio
            updated_fields.append('pitch_ratio')
            
        if request.emotion is not None:
            tts_service.config['audio']['emotion'] = request.emotion
            updated_fields.append('emotion')
            
        if request.language is not None:
            tts_service.config['audio']['language'] = request.language
            updated_fields.append('language')
            
        if request.max_text_length is not None:
            tts_service.max_text_length = request.max_text_length
            updated_fields.append('max_text_length')
        
        logger.info(f"Configuration updated: {', '.join(updated_fields)}")
        
        # Broadcast configuration change
        await progress_broadcaster.broadcast_system_message(
            "config_update", 
            f"Configuration updated: {', '.join(updated_fields)}"
        )
        
        return {
            "message": f"Configuration updated successfully",
            "updated_fields": ", ".join(updated_fields)
        }
        
    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update config: {str(e)}")


# Root endpoint - serve the web interface
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the main web interface"""
    return templates.TemplateResponse("index.html", {"request": request})


# API info endpoint
# Queue Management Endpoints

@app.get("/api/queue/status", response_model=QueueStatusResponse)
async def get_queue_status():
    """Get queue status and statistics"""
    if not queue_manager:
        raise HTTPException(status_code=503, detail="Queue manager not available")
    
    status = queue_manager.get_queue_status()
    return QueueStatusResponse(**status)


@app.get("/api/queue/jobs", response_model=JobListResponse)
async def get_jobs(status: Optional[str] = None, limit: int = 50, offset: int = 0):
    """Get list of jobs with optional status filter"""
    if not queue_manager:
        raise HTTPException(status_code=503, detail="Queue manager not available")
    
    all_jobs = queue_manager.get_all_jobs()
    
    # Filter by status if provided
    if status:
        try:
            job_status = JobStatus(status)
            all_jobs = [job for job in all_jobs if job.status == job_status]
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    # Apply pagination
    total_count = len(all_jobs)
    jobs = all_jobs[offset:offset+limit]
    
    # Count by status
    running_count = len([job for job in all_jobs if job.status == JobStatus.RUNNING])
    completed_count = len([job for job in all_jobs if job.status == JobStatus.COMPLETED])
    failed_count = len([job for job in all_jobs if job.status == JobStatus.FAILED])
    
    return JobListResponse(
        jobs=[job.to_dict() for job in jobs],
        total_count=total_count,
        running_count=running_count,
        completed_count=completed_count,
        failed_count=failed_count
    )


@app.get("/api/queue/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get detailed status of a specific job"""
    if not queue_manager:
        raise HTTPException(status_code=503, detail="Queue manager not available")
    
    job = queue_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job.to_dict()


@app.post("/api/queue/jobs/{job_id}/control")
async def control_job(job_id: str, request: JobControlRequest):
    """Control job execution (pause/resume/cancel/retry)"""
    if not queue_manager:
        raise HTTPException(status_code=503, detail="Queue manager not available")
    
    action = request.action.lower()
    success = False
    message = ""
    
    if action == "pause":
        success = await queue_manager.pause_job(job_id)
        message = "Job paused" if success else "Failed to pause job"
    elif action == "resume":
        success = await queue_manager.resume_job(job_id)
        message = "Job resumed" if success else "Failed to resume job"
    elif action == "cancel":
        success = await queue_manager.cancel_job(job_id)
        message = "Job cancelled" if success else "Failed to cancel job"
    elif action == "retry":
        success = await queue_manager.retry_job(job_id)
        message = "Job requeued for retry" if success else "Failed to retry job"
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
    
    if success:
        # Broadcast status change
        await progress_broadcaster.broadcast_job_status(job_id, action, {"message": message})
    
    return {
        "success": success,
        "message": message,
        "job_id": job_id,
        "action": action
    }


# Real-time Progress Endpoints

@app.websocket("/api/progress/ws")
async def websocket_progress(websocket: WebSocket):
    """WebSocket endpoint for real-time progress updates"""
    await progress_broadcaster.handle_websocket_connection(websocket)


@app.get("/api/progress/sse")
async def sse_progress(request: Request):
    """Server-Sent Events endpoint for real-time progress updates"""
    
    def check_client_disconnection():
        return request.is_disconnected()
    
    # Create SSE connection
    queue = progress_broadcaster.connect_sse()
    
    async def generate():
        try:
            async for message in progress_broadcaster.generate_sse_stream(queue):
                if await check_client_disconnection():
                    break
                yield message
        except Exception as e:
            logger.error(f"SSE stream error: {e}")
        finally:
            progress_broadcaster.disconnect_sse(queue)
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )


@app.get("/api/progress/stats")
async def get_progress_stats():
    """Get progress broadcasting statistics"""
    return progress_broadcaster.get_connection_stats()


@app.get("/api")
async def api_info():
    """API information endpoint"""
    return {
        "name": "TTS Tool API",
        "version": "1.0.0",
        "description": "豆包TTS音频生成工具API - Enhanced with Queue Management",
        "docs_url": "/docs",
        "health_url": "/health",
        "endpoints": {
            "generate": "/api/tts/generate",
            "batch": "/api/tts/batch", 
            "voices": "/api/voices",
            "config": "/api/config",
            "queue_status": "/api/queue/status",
            "jobs": "/api/queue/jobs",
            "job_control": "/api/queue/jobs/{job_id}/control",
            "websocket_progress": "/api/progress/ws",
            "sse_progress": "/api/progress/sse"
        },
        "features": [
            "Advanced job queue management",
            "Real-time progress updates via WebSocket/SSE",
            "Job pause/resume/cancel functionality",
            "Configurable concurrency control (1-5)",
            "Automatic retry with exponential backoff",
            "Job history and status tracking",
            "Persistent job state across restarts"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    )