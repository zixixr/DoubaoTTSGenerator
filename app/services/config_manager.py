"""
Configuration Management Service with Hot-Reload

This service provides configuration hot-reload functionality, validation,
and change notification features for the TTS application.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Set
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent
import hashlib


class ConfigurationError(Exception):
    """Configuration-related errors"""
    pass


class ConfigChangeHandler(FileSystemEventHandler):
    """File system event handler for configuration changes"""
    
    def __init__(self, config_manager: 'ConfigManager'):
        self.config_manager = config_manager
        self.logger = logging.getLogger(__name__)
    
    def on_modified(self, event):
        """Handle file modification events"""
        if not isinstance(event, FileModifiedEvent):
            return
            
        file_path = Path(event.src_path)
        
        # Check if it's one of our monitored config files
        if file_path.name in self.config_manager.monitored_files:
            self.logger.info(f"Configuration file changed: {file_path}")
            # Schedule reload in the event loop
            asyncio.create_task(self.config_manager._handle_config_change(str(file_path)))


class ConfigManager:
    """
    Configuration Manager with Hot-Reload Support
    
    Features:
    - Hot-reload configuration files without restart
    - Configuration validation
    - Change notifications to subscribers
    - Rollback on invalid configuration
    - Configuration history tracking
    """
    
    def __init__(self, config_paths: Dict[str, str], validation_schema: Optional[Dict] = None):
        """
        Initialize configuration manager
        
        Args:
            config_paths: Dict mapping config names to file paths
            validation_schema: Optional schema for config validation
        """
        self.logger = logging.getLogger(__name__)
        
        # Configuration data
        self.config_paths = config_paths
        self.configs: Dict[str, Dict[str, Any]] = {}
        self.config_hashes: Dict[str, str] = {}
        self.config_history: List[Dict[str, Any]] = []
        self.validation_schema = validation_schema or {}
        
        # File monitoring
        self.observer = Observer()
        self.event_handler = ConfigChangeHandler(self)
        self.monitored_files: Set[str] = set()
        self.monitored_dirs: Set[str] = set()
        
        # Change notification
        self.change_callbacks: List[Callable[[str, Dict[str, Any]], None]] = []
        
        # Reload throttling
        self.last_reload_time: Dict[str, float] = {}
        self.reload_throttle = 1.0  # Minimum seconds between reloads
        
        # Initialize
        self._load_all_configurations()
        self._setup_file_monitoring()
    
    def _load_all_configurations(self):
        """Load all configuration files"""
        for config_name, config_path in self.config_paths.items():
            try:
                self._load_single_config(config_name, config_path)
                self.logger.info(f"Loaded configuration: {config_name}")
            except Exception as e:
                self.logger.error(f"Failed to load config {config_name}: {e}")
                raise ConfigurationError(f"Failed to load {config_name}: {e}")
    
    def _load_single_config(self, config_name: str, config_path: str):
        """Load a single configuration file"""
        if not os.path.exists(config_path):
            raise ConfigurationError(f"Configuration file not found: {config_path}")
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Validate configuration
            if config_name in self.validation_schema:
                self._validate_config(config_name, config_data)
            
            # Calculate hash for change detection
            config_hash = self._calculate_config_hash(config_data)
            
            # Store configuration
            old_config = self.configs.get(config_name)
            self.configs[config_name] = config_data
            self.config_hashes[config_name] = config_hash
            
            # Record history
            self.config_history.append({
                'config_name': config_name,
                'timestamp': datetime.now().isoformat(),
                'action': 'loaded',
                'hash': config_hash,
                'file_path': config_path
            })
            
            # Limit history size
            if len(self.config_history) > 100:
                self.config_history = self.config_history[-50:]
            
            # Notify changes if this is a reload
            if old_config is not None and old_config != config_data:
                self._notify_config_change(config_name, config_data)
            
        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON in {config_path}: {e}")
        except Exception as e:
            raise ConfigurationError(f"Error loading {config_path}: {e}")
    
    def _calculate_config_hash(self, config_data: Dict[str, Any]) -> str:
        """Calculate hash of configuration data"""
        config_str = json.dumps(config_data, sort_keys=True, separators=(',', ':'))
        return hashlib.md5(config_str.encode('utf-8')).hexdigest()
    
    def _validate_config(self, config_name: str, config_data: Dict[str, Any]):
        """Validate configuration against schema"""
        schema = self.validation_schema.get(config_name)
        if not schema:
            return
        
        # Basic validation - can be extended with jsonschema library
        required_fields = schema.get('required', [])
        for field in required_fields:
            if field not in config_data:
                raise ConfigurationError(f"Missing required field '{field}' in {config_name}")
        
        # Type validation
        field_types = schema.get('types', {})
        for field, expected_type in field_types.items():
            if field in config_data:
                value = config_data[field]
                if not isinstance(value, expected_type):
                    raise ConfigurationError(
                        f"Field '{field}' in {config_name} should be {expected_type.__name__}, "
                        f"got {type(value).__name__}"
                    )
    
    def _setup_file_monitoring(self):
        """Setup file system monitoring for configuration files"""
        monitored_dirs = set()
        
        for config_path in self.config_paths.values():
            file_path = Path(config_path).resolve()
            directory = file_path.parent
            
            # Add file to monitoring set
            self.monitored_files.add(file_path.name)
            
            # Add directory to monitoring if not already monitored
            if str(directory) not in monitored_dirs:
                self.observer.schedule(self.event_handler, str(directory), recursive=False)
                monitored_dirs.add(str(directory))
                self.monitored_dirs.add(str(directory))
        
        self.logger.info(f"Monitoring {len(monitored_dirs)} directories for config changes")
    
    async def start(self):
        """Start the configuration manager"""
        self.observer.start()
        self.logger.info("Configuration manager started with hot-reload enabled")
    
    async def stop(self):
        """Stop the configuration manager"""
        self.observer.stop()
        self.observer.join()
        self.logger.info("Configuration manager stopped")
    
    async def _handle_config_change(self, file_path: str):
        """Handle configuration file change"""
        file_name = Path(file_path).name
        
        # Find which config this file belongs to
        config_name = None
        for name, path in self.config_paths.items():
            if Path(path).name == file_name:
                config_name = name
                break
        
        if not config_name:
            return
        
        # Throttle reloads
        current_time = time.time()
        if config_name in self.last_reload_time:
            time_since_last = current_time - self.last_reload_time[config_name]
            if time_since_last < self.reload_throttle:
                return
        
        self.last_reload_time[config_name] = current_time
        
        try:
            # Small delay to ensure file write is complete
            await asyncio.sleep(0.1)
            
            # Calculate new hash to check if actually changed
            with open(file_path, 'r', encoding='utf-8') as f:
                new_config_data = json.load(f)
            
            new_hash = self._calculate_config_hash(new_config_data)
            
            # Check if configuration actually changed
            if new_hash == self.config_hashes.get(config_name):
                return
            
            self.logger.info(f"Reloading changed configuration: {config_name}")
            
            # Backup current config for rollback
            backup_config = self.configs.get(config_name, {}).copy()
            
            try:
                # Reload configuration
                self._load_single_config(config_name, file_path)
                self.logger.info(f"Successfully reloaded configuration: {config_name}")
                
            except Exception as e:
                # Rollback on error
                self.logger.error(f"Failed to reload {config_name}: {e}, rolling back")
                if backup_config:
                    self.configs[config_name] = backup_config
                raise
                
        except Exception as e:
            self.logger.error(f"Error handling config change for {file_path}: {e}")
    
    def get_config(self, config_name: str) -> Optional[Dict[str, Any]]:
        """Get configuration by name"""
        return self.configs.get(config_name)
    
    def get_all_configs(self) -> Dict[str, Dict[str, Any]]:
        """Get all configurations"""
        return self.configs.copy()
    
    def update_config(self, config_name: str, updates: Dict[str, Any], 
                     save_to_file: bool = True) -> bool:
        """
        Update configuration programmatically
        
        Args:
            config_name: Name of configuration to update
            updates: Dictionary of updates to apply
            save_to_file: Whether to persist changes to file
            
        Returns:
            True if update was successful
        """
        if config_name not in self.configs:
            raise ConfigurationError(f"Configuration '{config_name}' not found")
        
        try:
            # Create updated configuration
            updated_config = self.configs[config_name].copy()
            
            # Apply updates recursively
            self._deep_update(updated_config, updates)
            
            # Validate updated configuration
            if config_name in self.validation_schema:
                self._validate_config(config_name, updated_config)
            
            # Apply update
            old_config = self.configs[config_name].copy()
            self.configs[config_name] = updated_config
            
            # Update hash
            self.config_hashes[config_name] = self._calculate_config_hash(updated_config)
            
            # Record history
            self.config_history.append({
                'config_name': config_name,
                'timestamp': datetime.now().isoformat(),
                'action': 'updated_programmatically',
                'updates': updates,
                'hash': self.config_hashes[config_name]
            })
            
            # Save to file if requested
            if save_to_file and config_name in self.config_paths:
                config_path = self.config_paths[config_name]
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(updated_config, f, indent=2, ensure_ascii=False)
            
            # Notify change
            self._notify_config_change(config_name, updated_config)
            
            self.logger.info(f"Configuration '{config_name}' updated successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to update configuration '{config_name}': {e}")
            raise ConfigurationError(f"Failed to update configuration: {e}")
    
    def _deep_update(self, base_dict: Dict[str, Any], update_dict: Dict[str, Any]):
        """Recursively update nested dictionary"""
        for key, value in update_dict.items():
            if key in base_dict and isinstance(base_dict[key], dict) and isinstance(value, dict):
                self._deep_update(base_dict[key], value)
            else:
                base_dict[key] = value
    
    def add_change_callback(self, callback: Callable[[str, Dict[str, Any]], None]):
        """Add a callback to be notified of configuration changes"""
        self.change_callbacks.append(callback)
    
    def remove_change_callback(self, callback: Callable[[str, Dict[str, Any]], None]):
        """Remove a change callback"""
        if callback in self.change_callbacks:
            self.change_callbacks.remove(callback)
    
    def _notify_config_change(self, config_name: str, new_config: Dict[str, Any]):
        """Notify all subscribers of configuration change"""
        for callback in self.change_callbacks:
            try:
                callback(config_name, new_config)
            except Exception as e:
                self.logger.error(f"Error in config change callback: {e}")
    
    def get_config_history(self, config_name: Optional[str] = None, 
                          limit: int = 20) -> List[Dict[str, Any]]:
        """Get configuration change history"""
        history = self.config_history
        
        if config_name:
            history = [h for h in history if h.get('config_name') == config_name]
        
        # Return most recent entries first
        return sorted(history, key=lambda x: x['timestamp'], reverse=True)[:limit]
    
    def get_config_info(self) -> Dict[str, Any]:
        """Get information about all configurations"""
        return {
            'configs': {
                name: {
                    'path': self.config_paths.get(name, ''),
                    'hash': self.config_hashes.get(name, ''),
                    'size': len(json.dumps(config).encode('utf-8')),
                    'last_modified': os.path.getmtime(self.config_paths[name]) 
                                   if name in self.config_paths and os.path.exists(self.config_paths[name])
                                   else None
                }
                for name, config in self.configs.items()
            },
            'monitoring': {
                'monitored_files': len(self.monitored_files),
                'monitored_directories': len(self.monitored_dirs),
                'observer_running': self.observer.is_alive()
            },
            'history_entries': len(self.config_history)
        }
    
    def validate_all_configs(self) -> Dict[str, Any]:
        """Validate all configurations and return status"""
        results = {}
        
        for config_name, config_data in self.configs.items():
            try:
                if config_name in self.validation_schema:
                    self._validate_config(config_name, config_data)
                results[config_name] = {'valid': True, 'errors': []}
            except Exception as e:
                results[config_name] = {'valid': False, 'errors': [str(e)]}
        
        return results