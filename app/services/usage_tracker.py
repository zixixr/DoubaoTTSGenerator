"""
Usage Tracking and Statistics Service

This service tracks TTS usage, character counts, cost calculations,
and provides comprehensive statistics and reporting functionality.
"""

import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, asdict
from threading import Lock
import aiosqlite


@dataclass
class UsageRecord:
    """Individual usage record"""
    id: Optional[int] = None
    timestamp: float = 0.0
    request_id: str = ""
    text: str = ""
    text_length: int = 0
    utf8_bytes: int = 0
    voice_type: str = ""
    encoding: str = ""
    language: str = ""
    emotion: str = ""
    success: bool = True
    error_message: str = ""
    processing_time: float = 0.0
    file_size: int = 0
    cost_estimate: float = 0.0
    session_id: str = ""
    user_id: str = "default"
    batch_id: Optional[str] = None
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class CostConfig:
    """Cost calculation configuration"""
    base_rate: float = 0.001  # Cost per character
    voice_multipliers: Dict[str, float] = None  # Voice-specific multipliers
    encoding_multipliers: Dict[str, float] = None  # Encoding-specific multipliers
    language_multipliers: Dict[str, float] = None  # Language-specific multipliers
    volume_discounts: Dict[int, float] = None  # Volume discount thresholds
    
    def __post_init__(self):
        if self.voice_multipliers is None:
            self.voice_multipliers = {}
        if self.encoding_multipliers is None:
            self.encoding_multipliers = {"mp3": 1.0, "wav": 1.2, "ogg_opus": 0.9, "pcm": 1.3}
        if self.language_multipliers is None:
            self.language_multipliers = {"cn": 1.0, "en": 1.1, "ja": 1.2}
        if self.volume_discounts is None:
            self.volume_discounts = {1000: 0.95, 5000: 0.90, 10000: 0.85, 50000: 0.80}


class UsageTracker:
    """
    Usage Tracking Service
    
    Features:
    - Track all TTS requests with detailed metrics
    - Character count and cost calculation
    - SQLite database for persistent storage
    - Real-time statistics and reporting
    - Usage limits and quotas
    - Export capabilities
    """
    
    def __init__(self, db_path: str = "./usage_data.db", cost_config: Optional[CostConfig] = None):
        """
        Initialize usage tracker
        
        Args:
            db_path: Path to SQLite database file
            cost_config: Cost calculation configuration
        """
        self.logger = logging.getLogger(__name__)
        self.db_path = db_path
        self.cost_config = cost_config or CostConfig()
        
        # Thread safety
        self._lock = Lock()
        
        # In-memory cache for quick access
        self._daily_stats: Dict[str, Dict[str, Any]] = {}
        self._cache_date = datetime.now().strftime('%Y-%m-%d')
        
        # Initialize database
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database"""
        try:
            # Create directory if needed
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Create database and tables
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Main usage records table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS usage_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        request_id TEXT NOT NULL,
                        text TEXT NOT NULL,
                        text_length INTEGER NOT NULL,
                        utf8_bytes INTEGER NOT NULL,
                        voice_type TEXT NOT NULL,
                        encoding TEXT NOT NULL,
                        language TEXT DEFAULT '',
                        emotion TEXT DEFAULT '',
                        success BOOLEAN NOT NULL,
                        error_message TEXT DEFAULT '',
                        processing_time REAL DEFAULT 0.0,
                        file_size INTEGER DEFAULT 0,
                        cost_estimate REAL DEFAULT 0.0,
                        session_id TEXT DEFAULT '',
                        user_id TEXT DEFAULT 'default',
                        batch_id TEXT DEFAULT NULL,
                        created_date TEXT NOT NULL
                    )
                ''')
                
                # Daily aggregation table for quick stats
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS daily_stats (
                        date TEXT PRIMARY KEY,
                        total_requests INTEGER DEFAULT 0,
                        successful_requests INTEGER DEFAULT 0,
                        failed_requests INTEGER DEFAULT 0,
                        total_characters INTEGER DEFAULT 0,
                        total_utf8_bytes INTEGER DEFAULT 0,
                        total_cost REAL DEFAULT 0.0,
                        total_file_size INTEGER DEFAULT 0,
                        avg_processing_time REAL DEFAULT 0.0,
                        unique_sessions INTEGER DEFAULT 0,
                        voice_usage TEXT DEFAULT '{}',
                        language_usage TEXT DEFAULT '{}',
                        encoding_usage TEXT DEFAULT '{}'
                    )
                ''')
                
                # Create indexes for performance
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_usage_timestamp 
                    ON usage_records(timestamp)
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_usage_date 
                    ON usage_records(created_date)
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_usage_session 
                    ON usage_records(session_id)
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_usage_batch 
                    ON usage_records(batch_id)
                ''')
                
                conn.commit()
                
            self.logger.info(f"Usage tracking database initialized: {self.db_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize usage database: {e}")
            raise
    
    async def track_usage(self, record: UsageRecord) -> int:
        """
        Track a usage record
        
        Args:
            record: UsageRecord instance
            
        Returns:
            Record ID in database
        """
        try:
            # Calculate cost
            record.cost_estimate = self._calculate_cost(record)
            
            # Set created date
            created_date = datetime.fromtimestamp(record.timestamp).strftime('%Y-%m-%d')
            
            # Insert into database
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.cursor()
                
                await cursor.execute('''
                    INSERT INTO usage_records (
                        timestamp, request_id, text, text_length, utf8_bytes,
                        voice_type, encoding, language, emotion, success,
                        error_message, processing_time, file_size, cost_estimate,
                        session_id, user_id, batch_id, created_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    record.timestamp, record.request_id, record.text, record.text_length,
                    record.utf8_bytes, record.voice_type, record.encoding, record.language,
                    record.emotion, record.success, record.error_message, record.processing_time,
                    record.file_size, record.cost_estimate, record.session_id, record.user_id,
                    record.batch_id, created_date
                ))
                
                record.id = cursor.lastrowid
                await db.commit()
            
            # Update daily stats
            await self._update_daily_stats(record, created_date)
            
            self.logger.debug(f"Tracked usage record: {record.request_id}")
            return record.id
            
        except Exception as e:
            self.logger.error(f"Failed to track usage record: {e}")
            raise
    
    def _calculate_cost(self, record: UsageRecord) -> float:
        """Calculate cost for a usage record"""
        try:
            if not record.success:
                return 0.0
            
            base_cost = record.text_length * self.cost_config.base_rate
            
            # Apply voice multiplier
            voice_multiplier = self.cost_config.voice_multipliers.get(record.voice_type, 1.0)
            
            # Apply encoding multiplier
            encoding_multiplier = self.cost_config.encoding_multipliers.get(record.encoding, 1.0)
            
            # Apply language multiplier
            language_multiplier = self.cost_config.language_multipliers.get(record.language, 1.0)
            
            total_cost = base_cost * voice_multiplier * encoding_multiplier * language_multiplier
            
            return round(total_cost, 4)
            
        except Exception as e:
            self.logger.error(f"Error calculating cost: {e}")
            return 0.0
    
    async def _update_daily_stats(self, record: UsageRecord, date: str):
        """Update daily aggregated statistics"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.cursor()
                
                # Get current stats
                await cursor.execute('SELECT * FROM daily_stats WHERE date = ?', (date,))
                existing = await cursor.fetchone()
                
                if existing:
                    # Update existing record
                    (_, total_requests, successful_requests, failed_requests,
                     total_characters, total_utf8_bytes, total_cost, total_file_size,
                     avg_processing_time, unique_sessions, voice_usage_str,
                     language_usage_str, encoding_usage_str) = existing
                    
                    # Parse JSON strings
                    voice_usage = json.loads(voice_usage_str or '{}')
                    language_usage = json.loads(language_usage_str or '{}')
                    encoding_usage = json.loads(encoding_usage_str or '{}')
                    
                    # Update counters
                    total_requests += 1
                    if record.success:
                        successful_requests += 1
                        total_characters += record.text_length
                        total_utf8_bytes += record.utf8_bytes
                        total_cost += record.cost_estimate
                        total_file_size += record.file_size
                    else:
                        failed_requests += 1
                    
                    # Update average processing time
                    if record.processing_time > 0:
                        total_processing_time = avg_processing_time * (total_requests - 1) + record.processing_time
                        avg_processing_time = total_processing_time / total_requests
                    
                    # Update usage counts
                    voice_usage[record.voice_type] = voice_usage.get(record.voice_type, 0) + 1
                    if record.language:
                        language_usage[record.language] = language_usage.get(record.language, 0) + 1
                    encoding_usage[record.encoding] = encoding_usage.get(record.encoding, 0) + 1
                    
                    # Update record
                    await cursor.execute('''
                        UPDATE daily_stats SET 
                            total_requests = ?, successful_requests = ?, failed_requests = ?,
                            total_characters = ?, total_utf8_bytes = ?, total_cost = ?,
                            total_file_size = ?, avg_processing_time = ?,
                            voice_usage = ?, language_usage = ?, encoding_usage = ?
                        WHERE date = ?
                    ''', (
                        total_requests, successful_requests, failed_requests,
                        total_characters, total_utf8_bytes, total_cost, total_file_size,
                        avg_processing_time, json.dumps(voice_usage), json.dumps(language_usage),
                        json.dumps(encoding_usage), date
                    ))
                    
                else:
                    # Create new record
                    voice_usage = {record.voice_type: 1}
                    language_usage = {record.language: 1} if record.language else {}
                    encoding_usage = {record.encoding: 1}
                    
                    await cursor.execute('''
                        INSERT INTO daily_stats (
                            date, total_requests, successful_requests, failed_requests,
                            total_characters, total_utf8_bytes, total_cost, total_file_size,
                            avg_processing_time, unique_sessions, voice_usage, language_usage, encoding_usage
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        date, 1, 1 if record.success else 0, 0 if record.success else 1,
                        record.text_length if record.success else 0,
                        record.utf8_bytes if record.success else 0,
                        record.cost_estimate, record.file_size if record.success else 0,
                        record.processing_time, 0, json.dumps(voice_usage),
                        json.dumps(language_usage), json.dumps(encoding_usage)
                    ))
                
                await db.commit()
                
        except Exception as e:
            self.logger.error(f"Failed to update daily stats: {e}")
    
    async def get_usage_stats(self, start_date: Optional[str] = None,
                            end_date: Optional[str] = None,
                            session_id: Optional[str] = None,
                            user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get usage statistics
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            session_id: Filter by session ID
            user_id: Filter by user ID
            
        Returns:
            Dictionary with comprehensive statistics
        """
        try:
            # Default to last 7 days if no dates provided
            if not start_date:
                start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            if not end_date:
                end_date = datetime.now().strftime('%Y-%m-%d')
            
            async with aiosqlite.connect(self.db_path) as db:
                # Build query conditions
                conditions = ["created_date >= ? AND created_date <= ?"]
                params = [start_date, end_date]
                
                if session_id:
                    conditions.append("session_id = ?")
                    params.append(session_id)
                
                if user_id:
                    conditions.append("user_id = ?")
                    params.append(user_id)
                
                where_clause = " AND ".join(conditions)
                
                # Get basic statistics
                cursor = await db.execute(f'''
                    SELECT 
                        COUNT(*) as total_requests,
                        SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_requests,
                        SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed_requests,
                        SUM(CASE WHEN success = 1 THEN text_length ELSE 0 END) as total_characters,
                        SUM(CASE WHEN success = 1 THEN utf8_bytes ELSE 0 END) as total_utf8_bytes,
                        SUM(cost_estimate) as total_cost,
                        SUM(CASE WHEN success = 1 THEN file_size ELSE 0 END) as total_file_size,
                        AVG(CASE WHEN processing_time > 0 THEN processing_time END) as avg_processing_time,
                        COUNT(DISTINCT session_id) as unique_sessions,
                        COUNT(DISTINCT batch_id) as unique_batches
                    FROM usage_records 
                    WHERE {where_clause}
                ''', params)
                
                basic_stats = await cursor.fetchone()
                
                # Get daily breakdown
                cursor = await db.execute(f'''
                    SELECT created_date, COUNT(*) as requests,
                           SUM(CASE WHEN success = 1 THEN text_length ELSE 0 END) as characters,
                           SUM(cost_estimate) as cost
                    FROM usage_records 
                    WHERE {where_clause}
                    GROUP BY created_date
                    ORDER BY created_date
                ''', params)
                
                daily_breakdown = await cursor.fetchall()
                
                # Get voice type breakdown
                cursor = await db.execute(f'''
                    SELECT voice_type, COUNT(*) as count,
                           SUM(CASE WHEN success = 1 THEN text_length ELSE 0 END) as characters,
                           SUM(cost_estimate) as cost
                    FROM usage_records 
                    WHERE {where_clause}
                    GROUP BY voice_type
                    ORDER BY count DESC
                ''', params)
                
                voice_breakdown = await cursor.fetchall()
                
                # Get language breakdown
                cursor = await db.execute(f'''
                    SELECT language, COUNT(*) as count,
                           SUM(CASE WHEN success = 1 THEN text_length ELSE 0 END) as characters
                    FROM usage_records 
                    WHERE {where_clause} AND language != ''
                    GROUP BY language
                    ORDER BY count DESC
                ''', params)
                
                language_breakdown = await cursor.fetchall()
                
                # Get encoding breakdown
                cursor = await db.execute(f'''
                    SELECT encoding, COUNT(*) as count,
                           SUM(CASE WHEN success = 1 THEN file_size ELSE 0 END) as total_size
                    FROM usage_records 
                    WHERE {where_clause}
                    GROUP BY encoding
                    ORDER BY count DESC
                ''', params)
                
                encoding_breakdown = await cursor.fetchall()
                
                # Get recent errors
                cursor = await db.execute(f'''
                    SELECT timestamp, request_id, error_message, voice_type, text_length
                    FROM usage_records 
                    WHERE {where_clause} AND success = 0
                    ORDER BY timestamp DESC
                    LIMIT 10
                ''', params)
                
                recent_errors = await cursor.fetchall()
                
                # Calculate success rate
                total_requests = basic_stats[0] or 0
                successful_requests = basic_stats[1] or 0
                success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0
                
                # Calculate average cost per character
                total_cost = basic_stats[5] or 0
                total_characters = basic_stats[3] or 0
                avg_cost_per_char = (total_cost / total_characters) if total_characters > 0 else 0
                
                return {
                    'period': {
                        'start_date': start_date,
                        'end_date': end_date,
                        'days': (datetime.strptime(end_date, '%Y-%m-%d') - 
                                datetime.strptime(start_date, '%Y-%m-%d')).days + 1
                    },
                    'summary': {
                        'total_requests': total_requests,
                        'successful_requests': successful_requests,
                        'failed_requests': basic_stats[2] or 0,
                        'success_rate': round(success_rate, 2),
                        'total_characters': total_characters,
                        'total_utf8_bytes': basic_stats[4] or 0,
                        'total_cost': round(total_cost, 4),
                        'avg_cost_per_char': round(avg_cost_per_char, 6),
                        'total_file_size': basic_stats[6] or 0,
                        'avg_processing_time': round(basic_stats[7] or 0, 3),
                        'unique_sessions': basic_stats[8] or 0,
                        'unique_batches': basic_stats[9] or 0
                    },
                    'daily_breakdown': [
                        {
                            'date': row[0],
                            'requests': row[1],
                            'characters': row[2],
                            'cost': round(row[3], 4)
                        }
                        for row in daily_breakdown
                    ],
                    'voice_breakdown': [
                        {
                            'voice_type': row[0],
                            'requests': row[1],
                            'characters': row[2],
                            'cost': round(row[3], 4)
                        }
                        for row in voice_breakdown
                    ],
                    'language_breakdown': [
                        {
                            'language': row[0],
                            'requests': row[1],
                            'characters': row[2]
                        }
                        for row in language_breakdown
                    ],
                    'encoding_breakdown': [
                        {
                            'encoding': row[0],
                            'requests': row[1],
                            'total_size': row[2]
                        }
                        for row in encoding_breakdown
                    ],
                    'recent_errors': [
                        {
                            'timestamp': datetime.fromtimestamp(row[0]).isoformat(),
                            'request_id': row[1],
                            'error_message': row[2],
                            'voice_type': row[3],
                            'text_length': row[4]
                        }
                        for row in recent_errors
                    ]
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get usage stats: {e}")
            raise
    
    async def get_usage_records(self, limit: int = 100, offset: int = 0,
                              start_date: Optional[str] = None,
                              end_date: Optional[str] = None,
                              session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get paginated usage records"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Build query conditions
                conditions = []
                params = []
                
                if start_date:
                    conditions.append("created_date >= ?")
                    params.append(start_date)
                
                if end_date:
                    conditions.append("created_date <= ?")
                    params.append(end_date)
                
                if session_id:
                    conditions.append("session_id = ?")
                    params.append(session_id)
                
                where_clause = " AND ".join(conditions) if conditions else "1=1"
                
                cursor = await db.execute(f'''
                    SELECT * FROM usage_records 
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                ''', params + [limit, offset])
                
                columns = [description[0] for description in cursor.description]
                rows = await cursor.fetchall()
                
                return [dict(zip(columns, row)) for row in rows]
                
        except Exception as e:
            self.logger.error(f"Failed to get usage records: {e}")
            raise
    
    async def get_current_usage(self, session_id: str) -> Dict[str, Any]:
        """Get current session usage statistics"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute('''
                    SELECT 
                        COUNT(*) as requests_today,
                        SUM(CASE WHEN success = 1 THEN text_length ELSE 0 END) as chars_today,
                        SUM(cost_estimate) as cost_today,
                        MAX(timestamp) as last_request_time
                    FROM usage_records 
                    WHERE session_id = ? AND created_date = ?
                ''', (session_id, today))
                
                result = await cursor.fetchone()
                
                return {
                    'session_id': session_id,
                    'today': {
                        'requests': result[0] or 0,
                        'characters': result[1] or 0,
                        'cost': round(result[2] or 0, 4),
                        'last_request': datetime.fromtimestamp(result[3]).isoformat() if result[3] else None
                    }
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get current usage: {e}")
            return {'session_id': session_id, 'today': {'requests': 0, 'characters': 0, 'cost': 0.0}}
    
    async def cleanup_old_records(self, days_to_keep: int = 90) -> Dict[str, int]:
        """Clean up old usage records"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).strftime('%Y-%m-%d')
            
            async with aiosqlite.connect(self.db_path) as db:
                # Count records to be deleted
                cursor = await db.execute('SELECT COUNT(*) FROM usage_records WHERE created_date < ?', (cutoff_date,))
                records_to_delete = (await cursor.fetchone())[0]
                
                # Delete old records
                await db.execute('DELETE FROM usage_records WHERE created_date < ?', (cutoff_date,))
                
                # Delete old daily stats
                cursor = await db.execute('SELECT COUNT(*) FROM daily_stats WHERE date < ?', (cutoff_date,))
                stats_to_delete = (await cursor.fetchone())[0]
                
                await db.execute('DELETE FROM daily_stats WHERE date < ?', (cutoff_date,))
                
                await db.commit()
                
                # Vacuum database to reclaim space
                await db.execute('VACUUM')
                
                self.logger.info(f"Cleaned up {records_to_delete} usage records and {stats_to_delete} daily stats older than {days_to_keep} days")
                
                return {
                    'records_deleted': records_to_delete,
                    'stats_deleted': stats_to_delete,
                    'cutoff_date': cutoff_date
                }
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup old records: {e}")
            raise
    
    def update_cost_config(self, cost_config: CostConfig):
        """Update cost calculation configuration"""
        self.cost_config = cost_config
        self.logger.info("Cost configuration updated")