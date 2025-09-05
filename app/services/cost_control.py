"""
Cost Control Service

This service provides cost control functionality including character limits,
confirmation dialogs, usage quotas, and cost estimation.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple, Union
from dataclasses import dataclass, asdict
from enum import Enum


class LimitType(Enum):
    """Types of limits that can be applied"""
    SOFT_LIMIT = "soft"  # Warning/confirmation required
    HARD_LIMIT = "hard"  # Prevents execution
    QUOTA_LIMIT = "quota"  # Daily/monthly limits


@dataclass
class CostLimit:
    """Cost limit configuration"""
    limit_type: LimitType
    threshold: int  # Character count threshold
    message: str = ""
    cost_estimate: float = 0.0
    period: str = "request"  # request, daily, monthly
    enabled: bool = True


@dataclass
class UsageQuota:
    """Usage quota configuration"""
    max_characters_daily: int = 50000
    max_characters_monthly: int = 500000
    max_requests_daily: int = 1000
    max_requests_monthly: int = 10000
    max_cost_daily: float = 50.0
    max_cost_monthly: float = 500.0
    enabled: bool = True


@dataclass
class CostControlConfig:
    """Cost control configuration"""
    # Character limits
    soft_limit_1000: bool = True  # 1000 character confirmation
    hard_limit_5000: bool = True  # 5000 character hard limit
    
    # Custom limits
    custom_limits: List[CostLimit] = None
    
    # Usage quotas
    quotas: UsageQuota = None
    
    # Cost estimation
    base_cost_per_char: float = 0.001
    show_cost_estimates: bool = True
    
    # Confirmation settings
    require_confirmation_over: int = 1000
    confirmation_timeout: int = 300  # 5 minutes
    
    def __post_init__(self):
        if self.custom_limits is None:
            self.custom_limits = []
        if self.quotas is None:
            self.quotas = UsageQuota()


@dataclass
class CostEstimate:
    """Cost estimation result"""
    character_count: int
    utf8_bytes: int
    estimated_cost: float
    voice_multiplier: float = 1.0
    encoding_multiplier: float = 1.0
    language_multiplier: float = 1.0
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


@dataclass
class LimitCheckResult:
    """Result of limit checking"""
    allowed: bool
    limit_exceeded: Optional[CostLimit] = None
    requires_confirmation: bool = False
    confirmation_token: Optional[str] = None
    cost_estimate: Optional[CostEstimate] = None
    warnings: List[str] = None
    quota_info: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class CostController:
    """
    Cost Control Service
    
    Features:
    - Character count validation with soft/hard limits
    - 1000-character confirmation dialog
    - 5000-character hard limit enforcement
    - Usage quotas (daily/monthly)
    - Cost estimation
    - Confirmation token management
    """
    
    def __init__(self, config: CostControlConfig, usage_tracker=None):
        """
        Initialize cost controller
        
        Args:
            config: Cost control configuration
            usage_tracker: Usage tracker service for quota monitoring
        """
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.usage_tracker = usage_tracker
        
        # Confirmation tokens (session_id -> confirmation_data)
        self.pending_confirmations: Dict[str, Dict[str, Any]] = {}
        
        # Default limits based on requirements
        self._setup_default_limits()
    
    def _setup_default_limits(self):
        """Setup default limits based on requirements"""
        if not self.config.custom_limits:
            self.config.custom_limits = []
        
        # Add 1000-character soft limit if enabled
        if self.config.soft_limit_1000:
            self.config.custom_limits.append(CostLimit(
                limit_type=LimitType.SOFT_LIMIT,
                threshold=1000,
                message="Text length exceeds 1000 characters. This may result in higher costs. Do you want to continue?",
                period="request"
            ))
        
        # Add 5000-character hard limit if enabled
        if self.config.hard_limit_5000:
            self.config.custom_limits.append(CostLimit(
                limit_type=LimitType.HARD_LIMIT,
                threshold=5000,
                message="Text length exceeds the maximum limit of 5000 characters. Please reduce the text length.",
                period="request"
            ))
    
    def calculate_cost_estimate(self, text: str, voice_type: str = "", 
                              encoding: str = "mp3", language: str = "") -> CostEstimate:
        """
        Calculate cost estimate for given text and parameters
        
        Args:
            text: Input text
            voice_type: Voice type
            encoding: Audio encoding
            language: Language
            
        Returns:
            CostEstimate object
        """
        character_count = len(text)
        utf8_bytes = len(text.encode('utf-8'))
        
        # Base cost calculation
        base_cost = character_count * self.config.base_cost_per_char
        
        # Apply multipliers (simplified version - can be enhanced)
        voice_multiplier = 1.0
        if voice_type.startswith("BV7"):  # Premium voices
            voice_multiplier = 1.2
        elif voice_type.startswith("BR"):  # Special voices
            voice_multiplier = 1.5
        
        encoding_multiplier = {
            "mp3": 1.0,
            "wav": 1.2,
            "pcm": 1.3,
            "ogg_opus": 0.9
        }.get(encoding.lower(), 1.0)
        
        language_multiplier = {
            "cn": 1.0,
            "en": 1.1,
            "ja": 1.2,
            "": 1.0  # Default
        }.get(language.lower(), 1.0)
        
        estimated_cost = base_cost * voice_multiplier * encoding_multiplier * language_multiplier
        
        # Generate warnings
        warnings = []
        if character_count > 500:
            warnings.append(f"Long text ({character_count} characters) may take longer to process")
        if estimated_cost > 1.0:
            warnings.append(f"Estimated cost is ${estimated_cost:.3f}")
        if utf8_bytes > character_count * 2:
            warnings.append("Text contains many multi-byte characters")
        
        return CostEstimate(
            character_count=character_count,
            utf8_bytes=utf8_bytes,
            estimated_cost=round(estimated_cost, 4),
            voice_multiplier=voice_multiplier,
            encoding_multiplier=encoding_multiplier,
            language_multiplier=language_multiplier,
            warnings=warnings
        )
    
    async def check_limits(self, text: str, session_id: str, voice_type: str = "",
                          encoding: str = "mp3", language: str = "",
                          confirmation_token: Optional[str] = None) -> LimitCheckResult:
        """
        Check if text request is within limits
        
        Args:
            text: Input text
            session_id: Session identifier
            voice_type: Voice type
            encoding: Audio encoding
            language: Language
            confirmation_token: Token from previous confirmation
            
        Returns:
            LimitCheckResult object
        """
        try:
            # Calculate cost estimate
            cost_estimate = self.calculate_cost_estimate(text, voice_type, encoding, language)
            character_count = cost_estimate.character_count
            
            # Check if confirmation token is valid
            if confirmation_token and self._validate_confirmation_token(confirmation_token, session_id):
                # Clear the confirmation and allow request
                self._clear_confirmation(session_id)
                return LimitCheckResult(
                    allowed=True,
                    cost_estimate=cost_estimate,
                    warnings=["Request confirmed and proceeding"]
                )
            
            # Check custom limits
            for limit in self.config.custom_limits:
                if not limit.enabled:
                    continue
                
                if character_count >= limit.threshold:
                    if limit.limit_type == LimitType.HARD_LIMIT:
                        return LimitCheckResult(
                            allowed=False,
                            limit_exceeded=limit,
                            cost_estimate=cost_estimate,
                            warnings=[f"Hard limit exceeded: {limit.message}"]
                        )
                    
                    elif limit.limit_type == LimitType.SOFT_LIMIT:
                        # Generate confirmation token
                        confirmation_token = self._generate_confirmation_token(
                            session_id, text, cost_estimate
                        )
                        
                        return LimitCheckResult(
                            allowed=False,
                            limit_exceeded=limit,
                            requires_confirmation=True,
                            confirmation_token=confirmation_token,
                            cost_estimate=cost_estimate,
                            warnings=[f"Confirmation required: {limit.message}"]
                        )
            
            # Check quotas if usage tracker is available
            quota_info = None
            if self.usage_tracker and self.config.quotas.enabled:
                quota_info = await self._check_quotas(session_id, cost_estimate)
                if quota_info and not quota_info.get('allowed', True):
                    return LimitCheckResult(
                        allowed=False,
                        cost_estimate=cost_estimate,
                        quota_info=quota_info,
                        warnings=[f"Quota exceeded: {quota_info.get('message', 'Unknown quota limit')}"]
                    )
            
            # All checks passed
            return LimitCheckResult(
                allowed=True,
                cost_estimate=cost_estimate,
                quota_info=quota_info,
                warnings=cost_estimate.warnings
            )
            
        except Exception as e:
            self.logger.error(f"Error checking limits: {e}")
            # On error, be conservative and block
            return LimitCheckResult(
                allowed=False,
                warnings=[f"Error checking limits: {str(e)}"]
            )
    
    def _generate_confirmation_token(self, session_id: str, text: str, 
                                   cost_estimate: CostEstimate) -> str:
        """Generate confirmation token for pending request"""
        import uuid
        import hashlib
        
        token = str(uuid.uuid4())
        timestamp = time.time()
        
        # Store confirmation data
        self.pending_confirmations[session_id] = {
            'token': token,
            'text': text,
            'cost_estimate': asdict(cost_estimate),
            'timestamp': timestamp,
            'expires_at': timestamp + self.config.confirmation_timeout
        }
        
        # Clean up old confirmations
        self._cleanup_expired_confirmations()
        
        return token
    
    def _validate_confirmation_token(self, token: str, session_id: str) -> bool:
        """Validate confirmation token"""
        confirmation = self.pending_confirmations.get(session_id)
        if not confirmation:
            return False
        
        if confirmation['token'] != token:
            return False
        
        if time.time() > confirmation['expires_at']:
            self._clear_confirmation(session_id)
            return False
        
        return True
    
    def _clear_confirmation(self, session_id: str):
        """Clear confirmation data for session"""
        self.pending_confirmations.pop(session_id, None)
    
    def _cleanup_expired_confirmations(self):
        """Clean up expired confirmations"""
        current_time = time.time()
        expired_sessions = [
            session_id for session_id, data in self.pending_confirmations.items()
            if current_time > data['expires_at']
        ]
        
        for session_id in expired_sessions:
            self.pending_confirmations.pop(session_id, None)
    
    async def _check_quotas(self, session_id: str, cost_estimate: CostEstimate) -> Dict[str, Any]:
        """Check usage quotas"""
        try:
            # Get current usage
            current_usage = await self.usage_tracker.get_current_usage(session_id)
            today_stats = current_usage.get('today', {})
            
            characters_today = today_stats.get('characters', 0)
            requests_today = today_stats.get('requests', 0)
            cost_today = today_stats.get('cost', 0.0)
            
            # Check daily quotas
            quotas = self.config.quotas
            
            # Character quota
            if characters_today + cost_estimate.character_count > quotas.max_characters_daily:
                return {
                    'allowed': False,
                    'quota_type': 'daily_characters',
                    'current': characters_today,
                    'limit': quotas.max_characters_daily,
                    'requested': cost_estimate.character_count,
                    'message': f"Daily character limit exceeded. Current: {characters_today}, Limit: {quotas.max_characters_daily}"
                }
            
            # Request quota
            if requests_today + 1 > quotas.max_requests_daily:
                return {
                    'allowed': False,
                    'quota_type': 'daily_requests',
                    'current': requests_today,
                    'limit': quotas.max_requests_daily,
                    'message': f"Daily request limit exceeded. Current: {requests_today}, Limit: {quotas.max_requests_daily}"
                }
            
            # Cost quota
            if cost_today + cost_estimate.estimated_cost > quotas.max_cost_daily:
                return {
                    'allowed': False,
                    'quota_type': 'daily_cost',
                    'current': cost_today,
                    'limit': quotas.max_cost_daily,
                    'requested': cost_estimate.estimated_cost,
                    'message': f"Daily cost limit exceeded. Current: ${cost_today:.3f}, Limit: ${quotas.max_cost_daily:.3f}"
                }
            
            # Return quota info
            return {
                'allowed': True,
                'daily_usage': {
                    'characters': {
                        'used': characters_today,
                        'limit': quotas.max_characters_daily,
                        'remaining': quotas.max_characters_daily - characters_today
                    },
                    'requests': {
                        'used': requests_today,
                        'limit': quotas.max_requests_daily,
                        'remaining': quotas.max_requests_daily - requests_today
                    },
                    'cost': {
                        'used': round(cost_today, 3),
                        'limit': quotas.max_cost_daily,
                        'remaining': round(quotas.max_cost_daily - cost_today, 3)
                    }
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error checking quotas: {e}")
            return {'allowed': True, 'error': str(e)}
    
    def get_confirmation_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get pending confirmation information"""
        confirmation = self.pending_confirmations.get(session_id)
        if not confirmation:
            return None
        
        if time.time() > confirmation['expires_at']:
            self._clear_confirmation(session_id)
            return None
        
        return {
            'token': confirmation['token'],
            'text_preview': confirmation['text'][:100] + "..." if len(confirmation['text']) > 100 else confirmation['text'],
            'cost_estimate': confirmation['cost_estimate'],
            'expires_at': datetime.fromtimestamp(confirmation['expires_at']).isoformat(),
            'time_remaining': int(confirmation['expires_at'] - time.time())
        }
    
    def get_limits_info(self) -> Dict[str, Any]:
        """Get information about current limits and quotas"""
        return {
            'character_limits': [
                {
                    'type': limit.limit_type.value,
                    'threshold': limit.threshold,
                    'message': limit.message,
                    'enabled': limit.enabled
                }
                for limit in self.config.custom_limits
            ],
            'quotas': asdict(self.config.quotas),
            'cost_settings': {
                'base_cost_per_char': self.config.base_cost_per_char,
                'show_cost_estimates': self.config.show_cost_estimates,
                'confirmation_timeout': self.config.confirmation_timeout
            },
            'pending_confirmations': len(self.pending_confirmations)
        }
    
    def update_config(self, new_config: CostControlConfig):
        """Update cost control configuration"""
        old_config = self.config
        self.config = new_config
        
        # Re-setup default limits
        self._setup_default_limits()
        
        self.logger.info("Cost control configuration updated")
        
        # Clear pending confirmations if limits changed significantly
        if (old_config.require_confirmation_over != new_config.require_confirmation_over or
            old_config.hard_limit_5000 != new_config.hard_limit_5000):
            self.pending_confirmations.clear()
            self.logger.info("Cleared pending confirmations due to limit changes")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cost control statistics"""
        current_time = time.time()
        active_confirmations = sum(
            1 for data in self.pending_confirmations.values()
            if current_time <= data['expires_at']
        )
        
        return {
            'active_confirmations': active_confirmations,
            'expired_confirmations': len(self.pending_confirmations) - active_confirmations,
            'limits_configured': len(self.config.custom_limits),
            'quotas_enabled': self.config.quotas.enabled,
            'cost_estimation_enabled': self.config.show_cost_estimates
        }