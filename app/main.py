"""
FastAPI main application for TTS Tool

This module creates the FastAPI application with all endpoints, middleware,
and configurations needed for the TTS service. 
"""

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from app.services.tts_service import TTSService, TTSServiceError, TTSAPIError, TTSConfigError
from app.services.queue_manager import QueueManager, BatchJob, JobStatus, JobPriority
from app.services.progress_broadcaster import get_progress_broadcaster
from app.services.file_manager import FileManager
from app.services.config_manager import ConfigManager, ConfigurationError
from app.services.usage_tracker import UsageTracker, UsageRecord, CostConfig
from app.services.cost_control import CostController, CostControlConfig, LimitCheckResult
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
file_manager: Optional[FileManager] = None
config_manager: Optional[ConfigManager] = None
usage_tracker: Optional[UsageTracker] = None
cost_controller: Optional[CostController] = None
progress_broadcaster = get_progress_broadcaster()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    global tts_service, queue_manager, file_manager, config_manager, usage_tracker, cost_controller
    
    try:
        # Startup
        logger.info("Starting TTS Tool application...")
        
        # Initialize Configuration Manager
        config_paths = {
            "tts_config": "tts_config.json",
            "voice_config": "voice_config.json"
        }
        
        # Define validation schema for configurations
        validation_schema = {
            "tts_config": {
                "required": ["app", "audio", "request"],
                "types": {
                    "app": dict,
                    "audio": dict,
                    "request": dict
                }
            }
        }
        
        config_manager = ConfigManager(config_paths, validation_schema)
        await config_manager.start()
        logger.info("Configuration manager initialized with hot-reload")
        
        # Initialize Usage Tracker
        usage_tracker = UsageTracker(
            db_path="./usage_data.db",
            cost_config=CostConfig()
        )
        logger.info("Usage tracker initialized successfully")
        
        # Initialize Cost Controller
        cost_control_config = CostControlConfig(
            soft_limit_1000=True,
            hard_limit_5000=True,
            base_cost_per_char=0.001,
            show_cost_estimates=True
        )
        cost_controller = CostController(cost_control_config, usage_tracker)
        logger.info("Cost controller initialized successfully")
        
        # Initialize File Manager
        file_manager = FileManager(
            base_output_dir="./output",
            default_template="tts_{index}_{datetime}.{ext}",
            organization="date",  # Organize by date
            enable_deduplication=True,
            metadata_dir="./file_metadata"
        )
        logger.info("File manager initialized successfully")
        
        # Initialize TTS service with file manager
        tts_service = TTSService(file_manager=file_manager)
        await tts_service.start()
        logger.info("TTS service initialized successfully")
        
        # Setup configuration change callback
        def on_config_change(config_name: str, new_config: Dict[str, Any]):
            logger.info(f"Configuration '{config_name}' changed, reloading TTS service...")
            if config_name in ["tts_config", "voice_config"] and tts_service:
                try:
                    tts_service.reload_config()
                    logger.info("TTS service configuration reloaded successfully")
                except Exception as e:
                    logger.error(f"Failed to reload TTS service config: {e}")
        
        config_manager.add_change_callback(on_config_change)
        
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
        if config_manager:
            await config_manager.stop()
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
    sampling_rate: int = Field(24000, description="音频采样率")
    speed_ratio: float = Field(1.0, ge=0.2, le=3.0, description="语速")
    volume_ratio: float = Field(1.0, ge=0.1, le=3.0, description="音量")
    pitch_ratio: float = Field(1.0, ge=0.1, le=3.0, description="音调")
    emotion: Optional[str] = Field(None, description="情感/风格")
    language: Optional[str] = Field(None, description="语言")
    session_id: Optional[str] = Field(None, description="会话ID")
    confirmation_token: Optional[str] = Field(None, description="确认令牌")
    
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
    sampling_rate: int = Field(24000, description="音频采样率")


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
    confirmation_token: Optional[str] = None  # For confirmation requirements
    cost_estimate: Optional[float] = None  # Estimated cost


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
    """Generate TTS audio for single text with cost control"""
    if not tts_service or not cost_controller or not usage_tracker:
        raise HTTPException(status_code=503, detail="Services not available")
    
    try:
        # Generate session ID if not provided
        session_id = request.session_id or str(uuid.uuid4())
        
        logger.info(f"Generating TTS for text: {request.text[:50]}... (Session: {session_id})")
        
        # Check cost limits and character constraints
        limit_check = await cost_controller.check_limits(
            text=request.text,
            session_id=session_id,
            voice_type=request.voice_type or "",
            encoding=request.encoding,
            language=request.language or "",
            confirmation_token=request.confirmation_token
        )
        
        # Handle limit violations
        if not limit_check.allowed:
            if limit_check.requires_confirmation:
                # Return confirmation requirement
                return TTSResponse(
                    success=False,
                    message=f"Confirmation required: {limit_check.limit_exceeded.message if limit_check.limit_exceeded else 'Unknown limit'}",
                    confirmation_token=limit_check.confirmation_token,
                    cost_estimate=limit_check.cost_estimate.estimated_cost if limit_check.cost_estimate else None,
                    text_length=limit_check.cost_estimate.character_count if limit_check.cost_estimate else len(request.text)
                )
            else:
                # Hard limit or quota exceeded
                error_msg = "Request blocked"
                if limit_check.limit_exceeded:
                    error_msg = limit_check.limit_exceeded.message
                elif limit_check.quota_info:
                    error_msg = limit_check.quota_info.get('message', 'Quota exceeded')
                
                raise HTTPException(status_code=400, detail=error_msg)
        
        # Generate request ID for tracking
        request_id = str(uuid.uuid4())
        start_time = time.time()
        
        try:
            # Generate audio bytes with session_id for file isolation
            audio_bytes = await tts_service.synthesize_speech(
                text=request.text,
                voice_type=request.voice_type,
                encoding=request.encoding,
                sample_rate=request.sampling_rate,
                speed_ratio=request.speed_ratio,
                volume_ratio=request.volume_ratio,
                pitch_ratio=request.pitch_ratio,
                emotion=request.emotion,
                language=request.language,
                session_id=session_id  # Pass session_id for directory isolation
            )
            
            processing_time = time.time() - start_time
            
            # Count characters
            char_info = tts_service.count_characters(request.text)
            
            # Track usage
            usage_record = UsageRecord(
                request_id=request_id,
                text=request.text,
                text_length=char_info['total_chars'],
                utf8_bytes=char_info['utf8_bytes'],
                voice_type=request.voice_type or tts_service.config['audio']['voice_type'],
                encoding=request.encoding,
                language=request.language or "",
                emotion=request.emotion or "",
                success=True,
                processing_time=processing_time,
                file_size=len(audio_bytes),
                session_id=session_id,
                user_id="default"
            )
            
            await usage_tracker.track_usage(usage_record)
            
            # Return audio data as base64 for direct use
            import base64
            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            return TTSResponse(
                success=True,
                message="TTS generation successful",
                file_size=len(audio_bytes),
                text_length=char_info['total_chars'],
                synthesis_time=processing_time,
                voice_type=request.voice_type or tts_service.config['audio']['voice_type'],
                encoding=request.encoding,
                audio_data=audio_b64
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            
            # Track failed usage
            char_info = tts_service.count_characters(request.text)
            usage_record = UsageRecord(
                request_id=request_id,
                text=request.text,
                text_length=char_info['total_chars'],
                utf8_bytes=char_info['utf8_bytes'],
                voice_type=request.voice_type or "",
                encoding=request.encoding,
                language=request.language or "",
                emotion=request.emotion or "",
                success=False,
                error_message=str(e),
                processing_time=processing_time,
                session_id=session_id,
                user_id="default"
            )
            
            await usage_tracker.track_usage(usage_record)
            raise
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")


@app.post("/api/tts/batch", response_model=BatchTTSResponse)
async def batch_generate_tts(request: BatchTTSRequest, raw_request: Request):
    """Submit batch TTS generation job to queue"""
    if not tts_service or not queue_manager:
        raise HTTPException(status_code=503, detail="Services not available")
    
    try:
        # Debug: Log raw request to see what's being received
        import json
        body = await raw_request.body()
        if body:
            try:
                parsed_body = json.loads(body)
                logger.info(f"RAW REQUEST BODY (first item): {json.dumps(parsed_body.get('items', [{}])[0], ensure_ascii=False)[:500]}")
            except:
                logger.info(f"RAW REQUEST BODY: {body[:500]}")
        
        logger.info(f"Submitting batch TTS job with {len(request.items)} items - RELOAD TEST V3")
        # Debug: Log sampling rates and voice types of all items - trigger reload
        for i, item in enumerate(request.items):
            voice_type_debug = item.voice_type if item.voice_type else "None/Missing"
            logger.info(f"Item {i+1} sampling_rate: {item.sampling_rate}Hz, voice_type: {voice_type_debug}")
        
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


# File Management Endpoints

class FileManagementRequest(BaseModel):
    """File management configuration request"""
    organization_type: Optional[str] = Field(None, description="Directory organization type")
    filename_template: Optional[str] = Field(None, description="Default filename template")
    enable_deduplication: Optional[bool] = Field(None, description="Enable file deduplication")


class BatchFilenameRequest(BaseModel):
    """Batch filename mapping request"""
    items: List[Dict[str, Any]] = Field(..., description="Items for filename mapping")
    template: Optional[str] = Field(None, description="Custom filename template")


class FileStatsResponse(BaseModel):
    """File statistics response"""
    total_files: int
    total_size: int
    by_encoding: Dict[str, int]
    by_voice: Dict[str, int]
    by_language: Dict[str, int]
    by_date: Dict[str, int]
    duplicates_avoided: int


@app.get("/api/files/stats", response_model=FileStatsResponse)
async def get_file_statistics():
    """Get file management statistics"""
    if not file_manager:
        raise HTTPException(status_code=503, detail="File manager not available")
    
    try:
        stats = await file_manager.get_file_statistics()
        return FileStatsResponse(**stats)
    except Exception as e:
        logger.error(f"Failed to get file statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get file statistics: {str(e)}")


@app.post("/api/files/batch-mapping")
async def get_batch_filename_mapping(request: BatchFilenameRequest):
    """Get batch filename mapping preview"""
    if not file_manager:
        raise HTTPException(status_code=503, detail="File manager not available")
    
    try:
        mappings = await file_manager.batch_filename_mapping(request.items, request.template)
        return {
            "success": True,
            "mappings": [{"text_preview": preview, "filename": filename} for preview, filename in mappings],
            "template": request.template or file_manager.default_template.template,
            "total_count": len(mappings)
        }
    except Exception as e:
        logger.error(f"Failed to generate batch mappings: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate batch mappings: {str(e)}")


@app.get("/api/files/templates")
async def get_filename_templates():
    """Get available filename template variables and examples"""
    from app.services.file_manager import FilenameTemplate, DirectoryOrganizer
    
    return {
        "variables": FilenameTemplate.VARIABLES,
        "organization_types": DirectoryOrganizer.ORGANIZATION_TYPES,
        "example_templates": [
            "tts_{index}_{datetime}.{ext}",
            "{voice}_{date}_{time}.{ext}",
            "{language}_{voice}_{index}.{ext}",
            "audio_{text_hash}_{voice}.{ext}",
            "{category}/{voice}/{date}/{index}.{ext}"
        ],
        "default_template": file_manager.default_template.template if file_manager else "tts_{index}_{datetime}.{ext}"
    }


@app.post("/api/files/cleanup")
async def cleanup_old_files(days: int = Query(30, description="Number of days to keep")):
    """Clean up old files and metadata"""
    if not file_manager:
        raise HTTPException(status_code=503, detail="File manager not available")
    
    try:
        result = await file_manager.cleanup_old_files(days)
        return {
            "success": True,
            "message": f"Cleanup completed for files older than {days} days",
            "files_removed": result['files_removed'],
            "metadata_cleaned": result['metadata_cleaned']
        }
    except Exception as e:
        logger.error(f"Failed to cleanup files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cleanup files: {str(e)}")


@app.put("/api/files/config")
async def update_file_management_config(request: FileManagementRequest):
    """Update file management configuration"""
    if not file_manager:
        raise HTTPException(status_code=503, detail="File manager not available")
    
    try:
        updated_fields = []
        
        if request.organization_type is not None:
            file_manager.organizer.organization = request.organization_type
            updated_fields.append('organization_type')
        
        if request.filename_template is not None:
            from app.services.file_manager import FilenameTemplate
            file_manager.default_template = FilenameTemplate(request.filename_template)
            updated_fields.append('filename_template')
        
        if request.enable_deduplication is not None:
            file_manager.enable_deduplication = request.enable_deduplication
            updated_fields.append('enable_deduplication')
        
        return {
            "success": True,
            "message": f"File management configuration updated",
            "updated_fields": updated_fields
        }
    except Exception as e:
        logger.error(f"Failed to update file management config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update config: {str(e)}")


@app.get("/api/files/config")
async def get_file_management_config():
    """Get current file management configuration"""
    if not file_manager:
        raise HTTPException(status_code=503, detail="File manager not available")
    
    try:
        return {
            "base_output_dir": str(file_manager.base_output_dir),
            "default_template": file_manager.default_template.template,
            "organization": file_manager.organization,
            "enable_deduplication": file_manager.enable_deduplication,
            "metadata_dir": str(file_manager.metadata_dir) if file_manager.metadata_dir else None,
            "available_organizations": list(file_manager.organizer.ORGANIZATION_TYPES.keys()),
            "template_variables": list(file_manager.default_template.VARIABLES.keys())
        }
    except Exception as e:
        logger.error(f"Failed to get file management config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get config: {str(e)}")


@app.get("/api/files/{file_path:path}")
async def download_file(file_path: str, batch_id: str = None):
    """Download generated audio file"""
    if not file_manager:
        raise HTTPException(status_code=503, detail="File manager not available")
    
    try:
        # Construct full file path based on file manager's output directory
        import os
        from pathlib import Path
        
        # Clean the file path to prevent directory traversal
        file_path = file_path.strip('/')
        if '..' in file_path or file_path.startswith('/'):
            raise HTTPException(status_code=400, detail="Invalid file path")
        
        # Search for the file using multiple strategies
        actual_file_path = None
        
        # Strategy 1: Direct search using glob pattern
        search_patterns = []
        
        # If batch_id is provided, search within the batch directory first
        if batch_id:
            logger.info(f"Batch ID provided: {batch_id}")
            search_patterns.extend([
                f"batch_{batch_id}/{file_path}",      # Direct batch directory
                f"**/batch_{batch_id}/{file_path}",   # Batch directory anywhere
                f"batch_{batch_id}/**/{file_path}",   # File anywhere in batch directory
            ])
        
        # Fallback to general search patterns (newest file prioritization)
        search_patterns.extend([
            f"**/{file_path}",  # Search everywhere recursively
            f"*/{file_path}",   # Search one level deep
            f"*/*/{file_path}"  # Search two levels deep
        ])
        
        logger.info(f"Searching for file: {file_path}")
        for pattern in search_patterns:
            logger.info(f"Using search pattern: {pattern}")
            matches = list(file_manager.base_output_dir.glob(pattern))
            logger.info(f"Found {len(matches)} matches for pattern {pattern}")
            if matches:
                # Sort matches by modification time, newest first
                matches_with_time = [(match, match.stat().st_mtime) for match in matches]
                matches_with_time.sort(key=lambda x: x[1], reverse=True)
                actual_file_path = matches_with_time[0][0]
                logger.info(f"Available files: {[str(match) for match, _ in matches_with_time]}")
                logger.info(f"Selected newest file: {actual_file_path} (modified: {matches_with_time[0][1]})")
                break
        
        if not actual_file_path or not actual_file_path.exists():
            logger.warning(f"File '{file_path}' not found using any search pattern")
            raise HTTPException(status_code=404, detail=f"File '{file_path}' not found")
        
        # Determine media type based on file extension
        file_ext = actual_file_path.suffix.lower()
        media_type_map = {
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.pcm': 'audio/pcm',
            '.flac': 'audio/flac'
        }
        media_type = media_type_map.get(file_ext, 'application/octet-stream')
        
        # Return the file
        return FileResponse(
            path=str(actual_file_path),
            media_type=media_type,
            filename=actual_file_path.name
        )
        
    except Exception as e:
        logger.error(f"Failed to download file {file_path}: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        logger.error(f"Exception traceback:", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to download file: {str(e)}")


@app.post("/api/files/batch/download")
async def download_batch_files(request: Request):
    """Download multiple files as a ZIP archive"""
    if not file_manager:
        raise HTTPException(status_code=503, detail="File manager not available")
    
    try:
        # Get raw request body first for debugging
        raw_body = await request.body()
        logger.info(f"Raw request body: {raw_body.decode('utf-8') if raw_body else 'Empty'}")
        
        # Parse JSON from raw body
        import json
        body = json.loads(raw_body) if raw_body else {}
        file_list = body.get('files', [])
        batch_id = body.get('batch_id')
        logger.info(f"Batch download request for files: {file_list}")
        if batch_id:
            logger.info(f"Batch ID provided: {batch_id}")
        
        if not file_list:
            raise HTTPException(status_code=400, detail="No files specified")
        
        import zipfile
        import io
        import os
        from pathlib import Path
        from datetime import datetime
        
        # Create in-memory ZIP file
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            files_added = 0
            
            for file_name in file_list:
                # Clean the file path to prevent directory traversal
                file_name = file_name.strip('/')
                if '..' in file_name or file_name.startswith('/'):
                    continue  # Skip invalid files instead of failing entire batch
                
                # Use the same search strategy as the single file download
                possible_paths = []
                
                # If batch_id is provided, search within the batch directory first
                if batch_id:
                    batch_specific_patterns = [
                        f"batch_{batch_id}/{file_name}",      # Direct batch directory
                        f"**/batch_{batch_id}/{file_name}",   # Batch directory anywhere
                        f"batch_{batch_id}/**/{file_name}",   # File anywhere in batch directory
                    ]
                    
                    for pattern in batch_specific_patterns:
                        matches = list(file_manager.base_output_dir.glob(pattern))
                        if matches:
                            # Sort matches by modification time, newest first
                            matches_with_time = [(match, match.stat().st_mtime) for match in matches]
                            matches_with_time.sort(key=lambda x: x[1], reverse=True)
                            possible_paths.append(matches_with_time[0][0])
                            break
                
                # Fallback to general search if batch-specific search didn't find the file
                if not possible_paths:
                    general_patterns = [
                        f"**/{file_name}",  # Search everywhere recursively
                        f"*/{file_name}",   # Search one level deep
                        f"*/*/{file_name}"  # Search two levels deep
                    ]
                    
                    for pattern in general_patterns:
                        matches = list(file_manager.base_output_dir.glob(pattern))
                        if matches:
                            # Sort matches by modification time, newest first
                            matches_with_time = [(match, match.stat().st_mtime) for match in matches]
                            matches_with_time.sort(key=lambda x: x[1], reverse=True)
                            possible_paths.append(matches_with_time[0][0])
                            break
                
                actual_file_path = None
                for path in possible_paths:
                    if path.exists():
                        actual_file_path = path
                        break
                
                if actual_file_path and actual_file_path.exists():
                    # Add file to ZIP with its original name
                    zip_file.write(str(actual_file_path), file_name)
                    files_added += 1
                    logger.info(f"Added {file_name} to batch download")
                else:
                    logger.warning(f"File {file_name} not found in any of the expected locations: {[str(p) for p in possible_paths]}")
            
            if files_added == 0:
                raise HTTPException(status_code=404, detail="No files found")
        
        # Reset buffer position to start
        zip_buffer.seek(0)
        
        # Generate ZIP filename with timestamp
        zip_filename = f"tts_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        
        return StreamingResponse(
            io.BytesIO(zip_buffer.read()),
            media_type='application/zip',
            headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
        )
        
    except Exception as e:
        logger.error(f"Failed to create batch download: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create batch download: {str(e)}")


# Configuration Management Endpoints

class ConfigReloadRequest(BaseModel):
    """Configuration reload request"""
    config_name: Optional[str] = Field(None, description="Specific config to reload (optional)")

class ConfigUpdateRequest(BaseModel):
    """Configuration update request"""
    config_name: str = Field(..., description="Configuration name")
    updates: Dict[str, Any] = Field(..., description="Configuration updates")
    save_to_file: bool = Field(True, description="Save changes to file")

class UsageStatsRequest(BaseModel):
    """Usage statistics request"""
    start_date: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    session_id: Optional[str] = Field(None, description="Filter by session ID")
    user_id: Optional[str] = Field(None, description="Filter by user ID")

class CostEstimateRequest(BaseModel):
    """Cost estimation request"""
    text: str = Field(..., description="Text to estimate cost for")
    voice_type: str = Field("", description="Voice type")
    encoding: str = Field("mp3", description="Audio encoding")
    language: str = Field("", description="Language")

class ConfirmationRequest(BaseModel):
    """Confirmation request"""
    confirmation_token: str = Field(..., description="Confirmation token")
    session_id: str = Field(..., description="Session ID")

@app.get("/api/config/info")
async def get_config_info():
    """Get configuration information and status"""
    if not config_manager:
        raise HTTPException(status_code=503, detail="Configuration manager not available")
    
    try:
        return config_manager.get_config_info()
    except Exception as e:
        logger.error(f"Failed to get config info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config/history")
async def get_config_history(config_name: Optional[str] = None, limit: int = 20):
    """Get configuration change history"""
    if not config_manager:
        raise HTTPException(status_code=503, detail="Configuration manager not available")
    
    try:
        return config_manager.get_config_history(config_name, limit)
    except Exception as e:
        logger.error(f"Failed to get config history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/config/reload")
async def reload_config(request: ConfigReloadRequest):
    """Reload configuration files"""
    if not config_manager:
        raise HTTPException(status_code=503, detail="Configuration manager not available")
    
    try:
        if request.config_name:
            # Reload specific config (would need to implement this in ConfigManager)
            config_manager.reload_config()
            message = f"Configuration '{request.config_name}' reloaded successfully"
        else:
            config_manager.reload_config()
            message = "All configurations reloaded successfully"
        
        return {"success": True, "message": message}
    except Exception as e:
        logger.error(f"Failed to reload config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/config/update")
async def update_configuration(request: ConfigUpdateRequest):
    """Update configuration programmatically"""
    if not config_manager:
        raise HTTPException(status_code=503, detail="Configuration manager not available")
    
    try:
        success = config_manager.update_config(
            request.config_name, 
            request.updates, 
            request.save_to_file
        )
        
        if success:
            return {
                "success": True,
                "message": f"Configuration '{request.config_name}' updated successfully",
                "updates": request.updates
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to update configuration")
            
    except Exception as e:
        logger.error(f"Failed to update configuration: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config/validate")
async def validate_configurations():
    """Validate all configurations"""
    if not config_manager:
        raise HTTPException(status_code=503, detail="Configuration manager not available")
    
    try:
        results = config_manager.validate_all_configs()
        all_valid = all(result['valid'] for result in results.values())
        
        return {
            "all_valid": all_valid,
            "results": results,
            "total_configs": len(results),
            "valid_configs": sum(1 for r in results.values() if r['valid'])
        }
    except Exception as e:
        logger.error(f"Failed to validate configurations: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Usage Statistics Endpoints

@app.get("/api/usage/stats")
async def get_usage_statistics(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None
):
    """Get usage statistics"""
    if not usage_tracker:
        raise HTTPException(status_code=503, detail="Usage tracker not available")
    
    try:
        stats = await usage_tracker.get_usage_stats(start_date, end_date, session_id, user_id)
        return stats
    except Exception as e:
        logger.error(f"Failed to get usage stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/usage/current")
async def get_current_usage(session_id: str):
    """Get current session usage"""
    if not usage_tracker:
        raise HTTPException(status_code=503, detail="Usage tracker not available")
    
    try:
        usage = await usage_tracker.get_current_usage(session_id)
        return usage
    except Exception as e:
        logger.error(f"Failed to get current usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/usage/records")
async def get_usage_records(
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session_id: Optional[str] = None
):
    """Get paginated usage records"""
    if not usage_tracker:
        raise HTTPException(status_code=503, detail="Usage tracker not available")
    
    try:
        records = await usage_tracker.get_usage_records(limit, offset, start_date, end_date, session_id)
        return {
            "records": records,
            "limit": limit,
            "offset": offset,
            "count": len(records)
        }
    except Exception as e:
        logger.error(f"Failed to get usage records: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/usage/cleanup")
async def cleanup_usage_data(days_to_keep: int = Query(90, description="Days to keep usage data")):
    """Clean up old usage records"""
    if not usage_tracker:
        raise HTTPException(status_code=503, detail="Usage tracker not available")
    
    try:
        result = await usage_tracker.cleanup_old_records(days_to_keep)
        return result
    except Exception as e:
        logger.error(f"Failed to cleanup usage data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Cost Control Endpoints

@app.post("/api/cost/estimate")
async def estimate_cost(request: CostEstimateRequest):
    """Estimate cost for text synthesis"""
    if not cost_controller:
        raise HTTPException(status_code=503, detail="Cost controller not available")
    
    try:
        estimate = cost_controller.calculate_cost_estimate(
            request.text, request.voice_type, request.encoding, request.language
        )
        
        return {
            "character_count": estimate.character_count,
            "utf8_bytes": estimate.utf8_bytes,
            "estimated_cost": estimate.estimated_cost,
            "voice_multiplier": estimate.voice_multiplier,
            "encoding_multiplier": estimate.encoding_multiplier,
            "language_multiplier": estimate.language_multiplier,
            "warnings": estimate.warnings
        }
    except Exception as e:
        logger.error(f"Failed to estimate cost: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cost/limits")
async def get_cost_limits():
    """Get current cost limits and quotas"""
    if not cost_controller:
        raise HTTPException(status_code=503, detail="Cost controller not available")
    
    try:
        return cost_controller.get_limits_info()
    except Exception as e:
        logger.error(f"Failed to get cost limits: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cost/confirmation/{session_id}")
async def get_confirmation_info(session_id: str):
    """Get pending confirmation information"""
    if not cost_controller:
        raise HTTPException(status_code=503, detail="Cost controller not available")
    
    try:
        info = cost_controller.get_confirmation_info(session_id)
        if not info:
            raise HTTPException(status_code=404, detail="No pending confirmation found")
        
        return info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get confirmation info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/cost/confirm")
async def confirm_request(request: ConfirmationRequest):
    """Confirm a pending request"""
    if not cost_controller:
        raise HTTPException(status_code=503, detail="Cost controller not available")
    
    try:
        # Validate the confirmation token
        confirmation_info = cost_controller.get_confirmation_info(request.session_id)
        if not confirmation_info:
            raise HTTPException(status_code=404, detail="No pending confirmation found")
        
        if confirmation_info['token'] != request.confirmation_token:
            raise HTTPException(status_code=400, detail="Invalid confirmation token")
        
        return {
            "success": True,
            "message": "Request confirmed successfully",
            "confirmation_token": request.confirmation_token
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to confirm request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cost/stats")
async def get_cost_stats():
    """Get cost control statistics"""
    if not cost_controller:
        raise HTTPException(status_code=503, detail="Cost controller not available")
    
    try:
        return cost_controller.get_stats()
    except Exception as e:
        logger.error(f"Failed to get cost stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api")
async def api_info():
    """API information endpoint"""
    return {
        "name": "TTS Tool API",
        "version": "1.0.0",
        "description": "豆包TTS音频生成工具API - Enhanced with Configuration Management, Cost Control, and Usage Tracking",
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
            "sse_progress": "/api/progress/sse",
            "file_stats": "/api/files/stats",
            "batch_mapping": "/api/files/batch-mapping",
            "filename_templates": "/api/files/templates",
            "file_cleanup": "/api/files/cleanup",
            "file_config": "/api/files/config",
            "config_info": "/api/config/info",
            "config_history": "/api/config/history",
            "config_reload": "/api/config/reload",
            "config_update": "/api/config/update",
            "config_validate": "/api/config/validate",
            "usage_stats": "/api/usage/stats",
            "current_usage": "/api/usage/current",
            "usage_records": "/api/usage/records",
            "usage_cleanup": "/api/usage/cleanup",
            "cost_estimate": "/api/cost/estimate",
            "cost_limits": "/api/cost/limits",
            "cost_confirmation": "/api/cost/confirmation/{session_id}",
            "cost_confirm": "/api/cost/confirm",
            "cost_stats": "/api/cost/stats"
        },
        "features": [
            "Advanced job queue management",
            "Real-time progress updates via WebSocket/SSE",
            "Job pause/resume/cancel functionality",
            "Configurable concurrency control (1-5)",
            "Automatic retry with exponential backoff",
            "Job history and status tracking",
            "Persistent job state across restarts",
            "Advanced file management with template-based naming",
            "File deduplication using MD5 hashes",
            "Directory organization by date/voice/language",
            "Batch filename mapping and preview",
            "File cleanup and maintenance tools",
            "Configuration hot-reload without restart",
            "Usage tracking with SQLite database",
            "Character count and cost estimation",
            "1000-character confirmation dialog",
            "5000-character hard limit enforcement",
            "Daily/monthly usage quotas",
            "Comprehensive usage statistics and reporting",
            "Configuration validation and error handling",
            "Real-time cost control and limits"
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