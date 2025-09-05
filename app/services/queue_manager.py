"""
Advanced Job Queue Manager for TTS Batch Processing

This module provides a comprehensive job queue system with:
- Job status tracking and persistence
- Pause/resume/cancel functionality  
- Progress reporting and real-time updates
- Configurable concurrency control
- Retry logic with exponential backoff
- Job history and statistics
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Union
import aiofiles
import aiofiles.os


class JobStatus(str, Enum):
    """Job status enumeration"""
    PENDING = "pending"
    QUEUED = "queued" 
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class JobPriority(str, Enum):
    """Job priority enumeration"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class JobItem:
    """Individual job item within a batch job"""
    
    def __init__(self, index: int, text: str, filename: Optional[str] = None, **params):
        self.index = index
        self.text = text
        self.filename = filename
        self.params = params
        self.status = JobStatus.PENDING
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.retry_count = 0
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert job item to dictionary"""
        return {
            'index': self.index,
            'text': self.text,
            'filename': self.filename,
            'params': self.params,
            'status': self.status,
            'result': self.result,
            'error': self.error,
            'retry_count': self.retry_count,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration': self.get_duration()
        }
    
    def get_duration(self) -> Optional[float]:
        """Get job item duration in seconds"""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None
    
    def mark_started(self):
        """Mark job item as started"""
        self.status = JobStatus.RUNNING
        self.start_time = time.time()
        
    def mark_completed(self, result: Dict[str, Any]):
        """Mark job item as completed"""
        self.status = JobStatus.COMPLETED
        self.result = result
        self.end_time = time.time()
        
    def mark_failed(self, error: str):
        """Mark job item as failed"""
        self.status = JobStatus.FAILED
        self.error = error
        self.end_time = time.time()


class BatchJob:
    """Batch TTS processing job"""
    
    def __init__(self, job_id: str, items: List[JobItem], output_dir: str, 
                 max_concurrent: int = 3, priority: JobPriority = JobPriority.NORMAL,
                 max_retries: int = 3, **kwargs):
        self.job_id = job_id
        self.items = items
        self.output_dir = output_dir
        self.max_concurrent = max_concurrent
        self.priority = priority
        self.max_retries = max_retries
        self.params = kwargs
        
        # Job state
        self.status = JobStatus.QUEUED
        self.created_time = time.time()
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.paused_time: Optional[float] = None
        self.total_paused_duration = 0.0
        
        # Progress tracking
        self.progress = 0.0
        self.completed_count = 0
        self.failed_count = 0
        self.current_concurrent = 0
        
        # Control flags
        self._cancel_requested = False
        self._pause_requested = False
        
        # Progress callback
        self.progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        
    @classmethod
    def from_request(cls, job_id: str, request_data: Dict[str, Any]) -> 'BatchJob':
        """Create BatchJob from request data"""
        items = []
        for i, item_data in enumerate(request_data.get('items', [])):
            item = JobItem(
                index=i,
                text=item_data['text'],
                filename=item_data.get('filename'),
                voice_type=item_data.get('voice_type'),
                encoding=item_data.get('encoding', 'mp3'),
                speed_ratio=item_data.get('speed_ratio', 1.0),
                volume_ratio=item_data.get('volume_ratio', 1.0),
                pitch_ratio=item_data.get('pitch_ratio', 1.0),
                emotion=item_data.get('emotion'),
                language=item_data.get('language')
            )
            items.append(item)
        
        return cls(
            job_id=job_id,
            items=items,
            output_dir=request_data.get('output_dir', './output'),
            max_concurrent=request_data.get('max_concurrent', 3),
            priority=JobPriority(request_data.get('priority', 'normal')),
            max_retries=request_data.get('max_retries', 3),
            filename_template=request_data.get('filename_template', 'tts_{index}_{timestamp}.{ext}')
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert batch job to dictionary"""
        return {
            'job_id': self.job_id,
            'status': self.status,
            'priority': self.priority,
            'created_time': self.created_time,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'total_paused_duration': self.total_paused_duration,
            'progress': self.progress,
            'completed_count': self.completed_count,
            'failed_count': self.failed_count,
            'total_count': len(self.items),
            'current_concurrent': self.current_concurrent,
            'max_concurrent': self.max_concurrent,
            'max_retries': self.max_retries,
            'output_dir': self.output_dir,
            'params': self.params,
            'items': [item.to_dict() for item in self.items],
            'duration': self.get_duration(),
            'estimated_remaining': self.get_estimated_remaining()
        }
    
    def get_duration(self) -> Optional[float]:
        """Get job duration excluding paused time"""
        if not self.start_time:
            return None
        
        end_time = self.end_time or time.time()
        total_time = end_time - self.start_time
        return max(0, total_time - self.total_paused_duration)
    
    def get_estimated_remaining(self) -> Optional[float]:
        """Estimate remaining time based on completed items"""
        if self.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            return 0.0
            
        if self.completed_count == 0 or not self.start_time:
            return None
            
        duration = self.get_duration()
        if not duration:
            return None
            
        avg_time_per_item = duration / self.completed_count
        remaining_items = len(self.items) - self.completed_count - self.failed_count
        return avg_time_per_item * remaining_items
    
    def update_progress(self):
        """Update job progress and notify callback"""
        total_items = len(self.items)
        completed_items = self.completed_count + self.failed_count
        self.progress = (completed_items / total_items * 100) if total_items > 0 else 0.0
        
        if self.progress_callback:
            self.progress_callback(self.get_progress_data())
    
    def get_progress_data(self) -> Dict[str, Any]:
        """Get current progress data"""
        return {
            'job_id': self.job_id,
            'status': self.status,
            'progress': self.progress,
            'completed_count': self.completed_count,
            'failed_count': self.failed_count,
            'total_count': len(self.items),
            'current_concurrent': self.current_concurrent,
            'estimated_remaining': self.get_estimated_remaining(),
            'timestamp': time.time()
        }
    
    def pause(self):
        """Request job pause"""
        if self.status == JobStatus.RUNNING:
            self._pause_requested = True
            self.paused_time = time.time()
    
    def resume(self):
        """Resume paused job"""
        if self.status == JobStatus.PAUSED:
            if self.paused_time:
                self.total_paused_duration += time.time() - self.paused_time
                self.paused_time = None
            self._pause_requested = False
            self.status = JobStatus.RUNNING
    
    def cancel(self):
        """Request job cancellation"""
        self._cancel_requested = True
        if self.status in [JobStatus.QUEUED, JobStatus.PAUSED]:
            self.status = JobStatus.CANCELLED
            self.end_time = time.time()


class QueueManager:
    """Advanced queue manager for batch TTS jobs"""
    
    def __init__(self, storage_dir: str = "./queue_data", max_concurrent_jobs: int = 3):
        self.logger = logging.getLogger(__name__)
        self.storage_dir = Path(storage_dir)
        self.max_concurrent_jobs = max_concurrent_jobs
        
        # Job storage
        self.jobs: Dict[str, BatchJob] = {}
        self.job_queue: asyncio.Queue = asyncio.Queue()
        self.running_jobs: Dict[str, asyncio.Task] = {}
        
        # Queue control
        self._running = False
        self._queue_task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = {
            'total_jobs': 0,
            'completed_jobs': 0,
            'failed_jobs': 0,
            'cancelled_jobs': 0,
            'total_items_processed': 0,
            'total_processing_time': 0.0
        }
        
        # Initialize storage
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    async def start(self):
        """Start the queue manager"""
        if self._running:
            return
            
        self._running = True
        self._queue_task = asyncio.create_task(self._process_queue())
        await self._load_persistent_jobs()
        self.logger.info("Queue manager started")
    
    async def stop(self):
        """Stop the queue manager"""
        if not self._running:
            return
            
        self._running = False
        
        # Cancel queue processing
        if self._queue_task:
            self._queue_task.cancel()
            try:
                await self._queue_task
            except asyncio.CancelledError:
                pass
        
        # Cancel running jobs
        for job_id, task in list(self.running_jobs.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Save state
        await self._save_persistent_jobs()
        self.logger.info("Queue manager stopped")
    
    async def submit_job(self, job: BatchJob, tts_service) -> str:
        """Submit a batch job to the queue"""
        self.jobs[job.job_id] = job
        self.stats['total_jobs'] += 1
        
        # Set up TTS service reference
        job.tts_service = tts_service
        
        # Add to queue
        await self.job_queue.put(job)
        await self._save_job_state(job)
        
        self.logger.info(f"Job {job.job_id} submitted to queue (priority: {job.priority})")
        return job.job_id
    
    def get_job(self, job_id: str) -> Optional[BatchJob]:
        """Get job by ID"""
        return self.jobs.get(job_id)
    
    def get_all_jobs(self) -> List[BatchJob]:
        """Get all jobs"""
        return list(self.jobs.values())
    
    def get_jobs_by_status(self, status: JobStatus) -> List[BatchJob]:
        """Get jobs by status"""
        return [job for job in self.jobs.values() if job.status == status]
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get queue status"""
        return {
            'running': self._running,
            'queue_size': self.job_queue.qsize(),
            'running_jobs': len(self.running_jobs),
            'max_concurrent_jobs': self.max_concurrent_jobs,
            'total_jobs': len(self.jobs),
            'stats': self.stats,
            'jobs_by_status': {
                status.value: len(self.get_jobs_by_status(status)) 
                for status in JobStatus
            }
        }
    
    async def pause_job(self, job_id: str) -> bool:
        """Pause a running job"""
        job = self.get_job(job_id)
        if not job:
            return False
            
        if job.status == JobStatus.RUNNING:
            job.pause()
            await self._save_job_state(job)
            self.logger.info(f"Job {job_id} paused")
            return True
        return False
    
    async def resume_job(self, job_id: str) -> bool:
        """Resume a paused job"""
        job = self.get_job(job_id)
        if not job:
            return False
            
        if job.status == JobStatus.PAUSED:
            job.resume()
            await self.job_queue.put(job)
            await self._save_job_state(job)
            self.logger.info(f"Job {job_id} resumed")
            return True
        return False
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a job"""
        job = self.get_job(job_id)
        if not job:
            return False
            
        job.cancel()
        
        # Cancel running task if exists
        if job_id in self.running_jobs:
            task = self.running_jobs[job_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self.running_jobs[job_id]
        
        # Update stats
        if job.status == JobStatus.CANCELLED:
            self.stats['cancelled_jobs'] += 1
            
        await self._save_job_state(job)
        self.logger.info(f"Job {job_id} cancelled")
        return True
    
    async def retry_job(self, job_id: str) -> bool:
        """Retry a failed job"""
        job = self.get_job(job_id)
        if not job or job.status != JobStatus.FAILED:
            return False
        
        # Reset failed items that haven't exceeded retry limit
        for item in job.items:
            if item.status == JobStatus.FAILED and item.retry_count < job.max_retries:
                item.status = JobStatus.PENDING
                item.error = None
                item.end_time = None
        
        # Reset job state
        job.status = JobStatus.QUEUED
        job.completed_count = sum(1 for item in job.items if item.status == JobStatus.COMPLETED)
        job.failed_count = sum(1 for item in job.items if item.status == JobStatus.FAILED)
        job.progress = 0.0
        
        # Re-queue
        await self.job_queue.put(job)
        await self._save_job_state(job)
        
        self.logger.info(f"Job {job_id} requeued for retry")
        return True
    
    async def _process_queue(self):
        """Main queue processing loop"""
        while self._running:
            try:
                # Wait for job or timeout
                try:
                    job = await asyncio.wait_for(self.job_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # Check if we can start more jobs
                if len(self.running_jobs) >= self.max_concurrent_jobs:
                    # Put job back and wait
                    await self.job_queue.put(job)
                    await asyncio.sleep(0.1)
                    continue
                
                # Start job processing
                task = asyncio.create_task(self._process_job(job))
                self.running_jobs[job.job_id] = task
                
            except Exception as e:
                self.logger.error(f"Error in queue processing: {e}")
                await asyncio.sleep(1.0)
    
    async def _process_job(self, job: BatchJob):
        """Process a single batch job"""
        try:
            job.status = JobStatus.RUNNING
            job.start_time = time.time()
            
            self.logger.info(f"Starting job {job.job_id} with {len(job.items)} items")
            
            # Create semaphore for concurrency control
            semaphore = asyncio.Semaphore(job.max_concurrent)
            
            # Process all items
            tasks = []
            for item in job.items:
                if item.status == JobStatus.PENDING:
                    task = asyncio.create_task(self._process_job_item(job, item, semaphore))
                    tasks.append(task)
            
            # Wait for completion or cancellation
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            
            # Final status update
            if job._cancel_requested:
                job.status = JobStatus.CANCELLED
                self.stats['cancelled_jobs'] += 1
            elif job.failed_count == len(job.items):
                job.status = JobStatus.FAILED
                self.stats['failed_jobs'] += 1
            elif job.completed_count + job.failed_count == len(job.items):
                job.status = JobStatus.COMPLETED
                self.stats['completed_jobs'] += 1
            
            job.end_time = time.time()
            self.stats['total_items_processed'] += len(job.items)
            
            duration = job.get_duration()
            if duration:
                self.stats['total_processing_time'] += duration
            
            # Final progress update
            job.update_progress()
            
            await self._save_job_state(job)
            self.logger.info(f"Job {job.job_id} completed with status: {job.status}")
            
        except Exception as e:
            job.status = JobStatus.FAILED
            job.end_time = time.time()
            self.stats['failed_jobs'] += 1
            
            self.logger.error(f"Job {job.job_id} failed with error: {e}")
            await self._save_job_state(job)
            
        finally:
            # Remove from running jobs
            if job.job_id in self.running_jobs:
                del self.running_jobs[job.job_id]
    
    async def _process_job_item(self, job: BatchJob, item: JobItem, semaphore: asyncio.Semaphore):
        """Process a single job item"""
        async with semaphore:
            if job._cancel_requested:
                return
            
            # Check for pause
            while job._pause_requested and not job._cancel_requested:
                job.status = JobStatus.PAUSED
                await asyncio.sleep(0.1)
            
            if job._cancel_requested:
                return
            
            job.current_concurrent += 1
            item.mark_started()
            
            try:
                # Check if TTS service has file manager
                use_file_manager = hasattr(job.tts_service, 'file_manager') and job.tts_service.file_manager is not None
                
                if use_file_manager:
                    # Use file manager for advanced file handling
                    result = await job.tts_service.synthesize_to_file(
                        text=item.text,
                        output_path=job.output_dir,  # Base directory when using file manager
                        voice_type=item.params.get('voice_type'),
                        encoding=item.params.get('encoding', 'mp3'),
                        use_file_manager=True,
                        custom_filename=item.filename,
                        filename_template=job.params.get('filename_template'),
                        speed_ratio=item.params.get('speed_ratio', 1.0),
                        volume_ratio=item.params.get('volume_ratio', 1.0),
                        pitch_ratio=item.params.get('pitch_ratio', 1.0),
                        emotion=item.params.get('emotion'),
                        language=item.params.get('language')
                    )
                else:
                    # Legacy filename generation (fallback)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    ext = item.params.get('encoding', 'mp3').lower()
                    if ext == 'pcm':
                        ext = 'wav'
                    
                    filename_template = job.params.get('filename_template', 'tts_{index}_{timestamp}.{ext}')
                    filename = item.filename or filename_template.format(
                        index=item.index + 1,
                        timestamp=timestamp,
                        ext=ext
                    )
                    
                    if not filename.endswith(f'.{ext}'):
                        filename = f"{filename}.{ext}"
                    
                    output_path = Path(job.output_dir) / filename
                    
                    # Use legacy file saving
                    result = await job.tts_service.synthesize_to_file(
                        text=item.text,
                        output_path=str(output_path),
                        voice_type=item.params.get('voice_type'),
                        encoding=item.params.get('encoding', 'mp3'),
                        use_file_manager=False,
                        speed_ratio=item.params.get('speed_ratio', 1.0),
                        volume_ratio=item.params.get('volume_ratio', 1.0),
                        pitch_ratio=item.params.get('pitch_ratio', 1.0),
                        emotion=item.params.get('emotion'),
                        language=item.params.get('language')
                    )
                
                item.mark_completed(result)
                job.completed_count += 1
                
            except Exception as e:
                item.retry_count += 1
                
                if item.retry_count < job.max_retries:
                    item.status = JobStatus.RETRYING
                    self.logger.warning(f"Job {job.job_id} item {item.index} failed, retrying ({item.retry_count}/{job.max_retries}): {e}")
                    
                    # Exponential backoff
                    delay = min(2 ** item.retry_count, 30)
                    await asyncio.sleep(delay)
                    
                    # Retry
                    return await self._process_job_item(job, item, semaphore)
                else:
                    item.mark_failed(str(e))
                    job.failed_count += 1
                    self.logger.error(f"Job {job.job_id} item {item.index} failed permanently: {e}")
            
            finally:
                job.current_concurrent -= 1
                job.update_progress()
                await self._save_job_state(job)
    
    async def _save_job_state(self, job: BatchJob):
        """Save job state to persistent storage"""
        job_file = self.storage_dir / f"job_{job.job_id}.json"
        try:
            async with aiofiles.open(job_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(job.to_dict(), indent=2, ensure_ascii=False))
        except Exception as e:
            self.logger.error(f"Failed to save job state {job.job_id}: {e}")
    
    async def _load_persistent_jobs(self):
        """Load persistent job states"""
        try:
            job_files = [f for f in self.storage_dir.glob("job_*.json")]
            
            for job_file in job_files:
                try:
                    async with aiofiles.open(job_file, 'r', encoding='utf-8') as f:
                        job_data = json.loads(await f.read())
                    
                    # Only reload unfinished jobs
                    status = JobStatus(job_data['status'])
                    if status in [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED]:
                        # Convert back to BatchJob (simplified)
                        job_id = job_data['job_id']
                        # Note: This is a simplified reload - in production you'd want full reconstruction
                        self.logger.info(f"Found persistent job {job_id} with status {status} - manual intervention may be needed")
                        
                except Exception as e:
                    self.logger.error(f"Failed to load job from {job_file}: {e}")
                    
        except Exception as e:
            self.logger.error(f"Failed to load persistent jobs: {e}")
    
    async def _save_persistent_jobs(self):
        """Save all job states"""
        for job in self.jobs.values():
            await self._save_job_state(job)
    
    async def cleanup_old_jobs(self, max_age_days: int = 7):
        """Clean up old completed jobs"""
        cutoff_time = time.time() - (max_age_days * 24 * 3600)
        jobs_to_remove = []
        
        for job_id, job in self.jobs.items():
            if (job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED] 
                and job.end_time and job.end_time < cutoff_time):
                jobs_to_remove.append(job_id)
        
        for job_id in jobs_to_remove:
            del self.jobs[job_id]
            job_file = self.storage_dir / f"job_{job_id}.json"
            try:
                await aiofiles.os.remove(job_file)
            except:
                pass
        
        if jobs_to_remove:
            self.logger.info(f"Cleaned up {len(jobs_to_remove)} old jobs")