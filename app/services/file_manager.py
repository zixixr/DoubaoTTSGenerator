"""
File Management Service for TTS Tool

This module provides comprehensive file management functionality including:
- Template-based filename generation with variable substitution
- Output directory management and organization  
- File deduplication checking using MD5 hashes
- Batch filename mapping
- File organization by date/voice/language categories
"""

import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Union
import aiofiles
import aiofiles.os
from dataclasses import dataclass


@dataclass
class FileMetadata:
    """File metadata information"""
    file_path: str
    original_name: str
    generated_name: str
    size: int
    md5_hash: str
    created_at: datetime
    voice_type: Optional[str] = None
    encoding: str = "mp3"
    text_length: int = 0
    category: Optional[str] = None
    language: Optional[str] = None
    

class FilenameTemplate:
    """Filename template with variable substitution"""
    
    # Available template variables
    VARIABLES = {
        'date': 'Current date (YYYYMMDD)',
        'time': 'Current time (HHMMSS)', 
        'datetime': 'Current datetime (YYYYMMDD_HHMMSS)',
        'timestamp': 'Unix timestamp',
        'index': 'Item index (1-based)',
        'voice': 'Voice type identifier',
        'voice_name': 'Voice display name',
        'encoding': 'Audio encoding format',
        'language': 'Language code',
        'emotion': 'Emotion/style',
        'category': 'Voice category',
        'text_hash': 'MD5 hash of text (first 8 chars)',
        'text_length': 'Text length in characters',
        'uuid': 'Random UUID',
        'year': 'Current year (YYYY)',
        'month': 'Current month (MM)', 
        'day': 'Current day (DD)',
        'hour': 'Current hour (HH)',
        'minute': 'Current minute (MM)',
        'second': 'Current second (SS)'
    }
    
    def __init__(self, template: str = "tts_{index}_{datetime}.{ext}"):
        """
        Initialize filename template
        
        Args:
            template: Template string with variables in {variable} format
        """
        self.template = template
        self.logger = logging.getLogger(__name__)
        
        # Validate template
        self._validate_template()
    
    def _validate_template(self):
        """Validate template contains valid variables"""
        # Find all variables in template
        variables = re.findall(r'\{(\w+)\}', self.template)
        
        # Check for invalid variables
        invalid_vars = [var for var in variables if var not in self.VARIABLES and var != 'ext']
        if invalid_vars:
            self.logger.warning(f"Template contains unknown variables: {invalid_vars}")
    
    def render(self, context: Dict[str, Any], extension: str = "mp3") -> str:
        """
        Render template with provided context
        
        Args:
            context: Dictionary with variable values
            extension: File extension
            
        Returns:
            Rendered filename
        """
        now = datetime.now()
        
        # Build substitution context with defaults
        substitutions = {
            'date': now.strftime('%Y%m%d'),
            'time': now.strftime('%H%M%S'), 
            'datetime': now.strftime('%Y%m%d_%H%M%S'),
            'timestamp': str(int(now.timestamp())),
            'year': now.strftime('%Y'),
            'month': now.strftime('%m'),
            'day': now.strftime('%d'),
            'hour': now.strftime('%H'),
            'minute': now.strftime('%M'),
            'second': now.strftime('%S'),
            'uuid': str(__import__('uuid').uuid4()),
            'ext': extension.lower()
        }
        
        # Add provided context
        substitutions.update(context)
        
        # Handle special variables
        if 'text' in context:
            text_hash = hashlib.md5(context['text'].encode()).hexdigest()[:8]
            substitutions['text_hash'] = text_hash
            substitutions['text_length'] = len(context['text'])
        
        # Clean up None values
        substitutions = {k: str(v) if v is not None else '' for k, v in substitutions.items()}
        
        # Render template
        try:
            filename = self.template.format(**substitutions)
            # Clean filename for filesystem compatibility
            filename = self._sanitize_filename(filename)
            return filename
        except KeyError as e:
            self.logger.error(f"Missing variable in template: {e}")
            # Fallback to simple naming
            return f"tts_{substitutions.get('index', '1')}_{substitutions['datetime']}.{extension}"
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for filesystem compatibility"""
        # Remove/replace invalid characters
        invalid_chars = r'<>:"/\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Remove consecutive underscores
        filename = re.sub(r'_+', '_', filename)
        
        # Remove leading/trailing underscores and dots
        filename = filename.strip('_.')
        
        # Ensure filename is not empty
        if not filename or filename.isspace():
            filename = f"tts_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
        return filename


class DirectoryOrganizer:
    """Organizes output files into directory structures"""
    
    ORGANIZATION_TYPES = {
        'flat': 'All files in single directory',
        'date': 'Organize by date (YYYY/MM/DD)',
        'voice': 'Organize by voice type',
        'language': 'Organize by language',
        'category': 'Organize by voice category',
        'date_voice': 'Organize by date and voice (YYYY/MM/DD/voice)',
        'voice_date': 'Organize by voice and date (voice/YYYY/MM/DD)'
    }
    
    def __init__(self, base_dir: Union[str, Path], organization: str = "flat"):
        """
        Initialize directory organizer
        
        Args:
            base_dir: Base output directory
            organization: Organization type
        """
        self.base_dir = Path(base_dir)
        self.organization = organization
        self.logger = logging.getLogger(__name__)
        
        if organization not in self.ORGANIZATION_TYPES:
            self.logger.warning(f"Unknown organization type: {organization}, using 'flat'")
            self.organization = 'flat'
    
    def get_output_path(self, context: Dict[str, Any]) -> Path:
        """
        Get organized output path based on context
        
        Args:
            context: File context with metadata
            
        Returns:
            Organized directory path
        """
        if self.organization == 'flat':
            return self.base_dir
        
        now = datetime.now()
        voice_type = context.get('voice_type', 'default')
        language = context.get('language', 'unknown')
        category = context.get('category', 'general')
        
        if self.organization == 'date':
            return self.base_dir / now.strftime('%Y') / now.strftime('%m') / now.strftime('%d')
        
        elif self.organization == 'voice':
            return self.base_dir / self._sanitize_dirname(voice_type)
        
        elif self.organization == 'language':
            return self.base_dir / self._sanitize_dirname(language)
        
        elif self.organization == 'category':
            return self.base_dir / self._sanitize_dirname(category)
        
        elif self.organization == 'date_voice':
            return (self.base_dir / now.strftime('%Y') / now.strftime('%m') / 
                   now.strftime('%d') / self._sanitize_dirname(voice_type))
        
        elif self.organization == 'voice_date':
            return (self.base_dir / self._sanitize_dirname(voice_type) / 
                   now.strftime('%Y') / now.strftime('%m') / now.strftime('%d'))
        
        return self.base_dir
    
    def _sanitize_dirname(self, dirname: str) -> str:
        """Sanitize directory name for filesystem compatibility"""
        if not dirname:
            return 'unknown'
        
        # Replace invalid characters
        invalid_chars = r'<>:"/\|?*'
        for char in invalid_chars:
            dirname = dirname.replace(char, '_')
        
        # Clean up
        dirname = re.sub(r'_+', '_', dirname).strip('_.')
        
        if not dirname or dirname.isspace():
            return 'unknown'
            
        return dirname


class FileDeduplicator:
    """Handles file deduplication using MD5 hashes"""
    
    def __init__(self, metadata_file: Optional[str] = None):
        """
        Initialize file deduplicator
        
        Args:
            metadata_file: Path to metadata storage file
        """
        self.metadata_file = metadata_file or "file_metadata.json"
        self.metadata: Dict[str, FileMetadata] = {}
        self.logger = logging.getLogger(__name__)
        
        # Load existing metadata
        asyncio.create_task(self._load_metadata())
    
    async def _load_metadata(self):
        """Load metadata from storage file"""
        try:
            if await aiofiles.os.path.exists(self.metadata_file):
                async with aiofiles.open(self.metadata_file, 'r', encoding='utf-8') as f:
                    data = json.loads(await f.read())
                    for key, value in data.items():
                        # Convert back to FileMetadata
                        value['created_at'] = datetime.fromisoformat(value['created_at'])
                        self.metadata[key] = FileMetadata(**value)
        except Exception as e:
            self.logger.error(f"Failed to load file metadata: {e}")
    
    async def _save_metadata(self):
        """Save metadata to storage file"""
        try:
            # Convert to serializable format
            data = {}
            for key, metadata in self.metadata.items():
                data[key] = {
                    'file_path': metadata.file_path,
                    'original_name': metadata.original_name,
                    'generated_name': metadata.generated_name,
                    'size': metadata.size,
                    'md5_hash': metadata.md5_hash,
                    'created_at': metadata.created_at.isoformat(),
                    'voice_type': metadata.voice_type,
                    'encoding': metadata.encoding,
                    'text_length': metadata.text_length,
                    'category': metadata.category,
                    'language': metadata.language
                }
            
            async with aiofiles.open(self.metadata_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            self.logger.error(f"Failed to save file metadata: {e}")
    
    async def compute_file_hash(self, file_path: str) -> str:
        """Compute MD5 hash of a file"""
        hash_md5 = hashlib.md5()
        try:
            async with aiofiles.open(file_path, 'rb') as f:
                while chunk := await f.read(8192):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            self.logger.error(f"Failed to compute hash for {file_path}: {e}")
            return ""
    
    async def find_duplicate(self, file_path: str) -> Optional[FileMetadata]:
        """
        Find if file is a duplicate based on MD5 hash
        
        Args:
            file_path: Path to file to check
            
        Returns:
            FileMetadata of duplicate if found, None otherwise
        """
        file_hash = await self.compute_file_hash(file_path)
        if not file_hash:
            return None
        
        # Check if hash exists
        for metadata in self.metadata.values():
            if metadata.md5_hash == file_hash:
                # Verify original file still exists
                if await aiofiles.os.path.exists(metadata.file_path):
                    return metadata
                else:
                    # Remove stale metadata
                    await self.remove_metadata(metadata.file_path)
        
        return None
    
    async def add_file_metadata(self, file_path: str, **kwargs) -> FileMetadata:
        """
        Add file metadata to tracking
        
        Args:
            file_path: Path to file
            **kwargs: Additional metadata fields
            
        Returns:
            Created FileMetadata object
        """
        file_path = str(Path(file_path).resolve())
        
        # Get file stats
        stat = await aiofiles.os.stat(file_path)
        file_hash = await self.compute_file_hash(file_path)
        
        metadata = FileMetadata(
            file_path=file_path,
            original_name=kwargs.get('original_name', Path(file_path).name),
            generated_name=Path(file_path).name,
            size=stat.st_size,
            md5_hash=file_hash,
            created_at=datetime.now(),
            voice_type=kwargs.get('voice_type'),
            encoding=kwargs.get('encoding', 'mp3'),
            text_length=kwargs.get('text_length', 0),
            category=kwargs.get('category'),
            language=kwargs.get('language')
        )
        
        self.metadata[file_path] = metadata
        await self._save_metadata()
        
        return metadata
    
    async def remove_metadata(self, file_path: str):
        """Remove metadata for a file"""
        file_path = str(Path(file_path).resolve())
        if file_path in self.metadata:
            del self.metadata[file_path]
            await self._save_metadata()


class FileManager:
    """Main file management service"""
    
    def __init__(self, 
                 base_output_dir: str = "./output",
                 default_template: str = "tts_{index}_{datetime}.{ext}",
                 organization: str = "flat",
                 enable_deduplication: bool = True,
                 metadata_dir: str = "./file_metadata"):
        """
        Initialize file manager
        
        Args:
            base_output_dir: Base output directory
            default_template: Default filename template
            organization: Directory organization type
            enable_deduplication: Whether to enable file deduplication
            metadata_dir: Directory for metadata storage
        """
        self.base_output_dir = Path(base_output_dir)
        self.default_template = FilenameTemplate(default_template)
        self.organization = organization
        self.enable_deduplication = enable_deduplication
        self.metadata_dir = Path(metadata_dir)
        self.logger = logging.getLogger(__name__)
        
        # Initialize components
        self.organizer = DirectoryOrganizer(self.base_output_dir, organization)
        
        if enable_deduplication:
            self.metadata_dir.mkdir(parents=True, exist_ok=True)
            metadata_file = self.metadata_dir / "file_metadata.json"
            self.deduplicator = FileDeduplicator(str(metadata_file))
        else:
            self.deduplicator = None
    
    async def generate_filename(self, 
                              context: Dict[str, Any], 
                              template: Optional[str] = None,
                              extension: str = "mp3") -> str:
        """
        Generate filename using template and context
        
        Args:
            context: Context variables for template
            template: Custom template (optional)
            extension: File extension
            
        Returns:
            Generated filename
        """
        filename_template = FilenameTemplate(template) if template else self.default_template
        return filename_template.render(context, extension)
    
    async def get_output_path(self, 
                            context: Dict[str, Any],
                            filename: Optional[str] = None,
                            template: Optional[str] = None,
                            extension: str = "mp3") -> Path:
        """
        Get complete output path for a file
        
        Args:
            context: Context variables
            filename: Custom filename (optional)
            template: Custom template (optional)
            extension: File extension
            
        Returns:
            Complete output file path
        """
        # Generate filename if not provided
        if not filename:
            filename = await self.generate_filename(context, template, extension)
        
        # Get organized directory
        output_dir = self.organizer.get_output_path(context)
        
        # Ensure directory exists
        output_dir.mkdir(parents=True, exist_ok=True)
        
        return output_dir / filename
    
    async def resolve_file_conflicts(self, file_path: Path) -> Path:
        """
        Resolve file naming conflicts by appending numbers
        
        Args:
            file_path: Desired file path
            
        Returns:
            Available file path
        """
        if not await aiofiles.os.path.exists(file_path):
            return file_path
        
        # Get base name and extension
        stem = file_path.stem
        suffix = file_path.suffix
        parent = file_path.parent
        
        # Try incrementing numbers
        counter = 1
        while counter < 1000:  # Reasonable limit
            new_path = parent / f"{stem}_{counter}{suffix}"
            if not await aiofiles.os.path.exists(new_path):
                return new_path
            counter += 1
        
        # If we reach here, use timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        return parent / f"{stem}_{timestamp}{suffix}"
    
    async def save_file_with_management(self,
                                      audio_data: bytes,
                                      context: Dict[str, Any],
                                      custom_filename: Optional[str] = None,
                                      template: Optional[str] = None,
                                      check_duplicates: bool = None) -> Dict[str, Any]:
        """
        Save audio file with full file management
        
        Args:
            audio_data: Audio file data
            context: File context and metadata
            custom_filename: Custom filename (optional)
            template: Custom filename template (optional)
            check_duplicates: Override deduplication setting
            
        Returns:
            Dictionary with save results and metadata
        """
        try:
            encoding = context.get('encoding', 'mp3')
            
            # Get output path
            output_path = await self.get_output_path(
                context, custom_filename, template, encoding
            )
            
            # Resolve conflicts
            final_path = await self.resolve_file_conflicts(output_path)
            
            # Check for duplicates if enabled
            duplicate_info = None
            if (check_duplicates if check_duplicates is not None else self.enable_deduplication) and self.deduplicator:
                # Save temporarily to check hash
                temp_path = final_path.with_suffix(f'{final_path.suffix}.tmp')
                async with aiofiles.open(temp_path, 'wb') as f:
                    await f.write(audio_data)
                
                duplicate = await self.deduplicator.find_duplicate(str(temp_path))
                
                if duplicate:
                    # Remove temp file and return duplicate info
                    await aiofiles.os.remove(temp_path)
                    duplicate_info = {
                        'is_duplicate': True,
                        'existing_file': duplicate.file_path,
                        'existing_created': duplicate.created_at.isoformat(),
                        'size': duplicate.size
                    }
                    self.logger.info(f"Duplicate file found: {duplicate.file_path}")
                    
                    return {
                        'success': True,
                        'file_path': duplicate.file_path,
                        'new_file': False,
                        'size': duplicate.size,
                        'duplicate_info': duplicate_info
                    }
                else:
                    # Move temp file to final location
                    await aiofiles.os.rename(temp_path, final_path)
            else:
                # Save directly
                async with aiofiles.open(final_path, 'wb') as f:
                    await f.write(audio_data)
            
            # Add to metadata tracking
            metadata = None
            if self.deduplicator:
                metadata = await self.deduplicator.add_file_metadata(
                    str(final_path),
                    original_name=custom_filename or output_path.name,
                    voice_type=context.get('voice_type'),
                    encoding=encoding,
                    text_length=context.get('text_length', 0),
                    category=context.get('category'),
                    language=context.get('language')
                )
            
            self.logger.info(f"File saved successfully: {final_path}")
            
            return {
                'success': True,
                'file_path': str(final_path),
                'new_file': True,
                'size': len(audio_data),
                'metadata': metadata.file_path if metadata else None,
                'duplicate_info': duplicate_info
            }
            
        except Exception as e:
            self.logger.error(f"Failed to save file: {e}")
            return {
                'success': False,
                'error': str(e),
                'file_path': None
            }
    
    async def batch_filename_mapping(self, 
                                   items: List[Dict[str, Any]], 
                                   template: Optional[str] = None) -> List[Tuple[str, str]]:
        """
        Generate batch filename mapping for multiple items
        
        Args:
            items: List of item contexts
            template: Custom template (optional)
            
        Returns:
            List of (text_preview, filename) tuples
        """
        mappings = []
        
        for i, item in enumerate(items):
            # Add index to context
            context = item.copy()
            context['index'] = i + 1
            
            # Generate filename
            encoding = item.get('encoding', 'mp3')
            filename = await self.generate_filename(context, template, encoding)
            
            # Get text preview
            text = item.get('text', '')
            text_preview = text[:50] + ('...' if len(text) > 50 else '')
            
            mappings.append((text_preview, filename))
        
        return mappings
    
    async def get_file_statistics(self) -> Dict[str, Any]:
        """Get file management statistics"""
        stats = {
            'total_files': 0,
            'total_size': 0,
            'by_encoding': {},
            'by_voice': {},
            'by_language': {},
            'by_date': {},
            'duplicates_avoided': 0
        }
        
        if not self.deduplicator:
            return stats
        
        # Count by various categories
        for metadata in self.deduplicator.metadata.values():
            stats['total_files'] += 1
            stats['total_size'] += metadata.size
            
            # By encoding
            encoding = metadata.encoding or 'unknown'
            stats['by_encoding'][encoding] = stats['by_encoding'].get(encoding, 0) + 1
            
            # By voice
            voice = metadata.voice_type or 'unknown'
            stats['by_voice'][voice] = stats['by_voice'].get(voice, 0) + 1
            
            # By language
            language = metadata.language or 'unknown'
            stats['by_language'][language] = stats['by_language'].get(language, 0) + 1
            
            # By date
            date_str = metadata.created_at.strftime('%Y-%m-%d')
            stats['by_date'][date_str] = stats['by_date'].get(date_str, 0) + 1
        
        return stats
    
    async def cleanup_old_files(self, days: int = 30) -> Dict[str, int]:
        """
        Clean up old files and metadata
        
        Args:
            days: Age threshold in days
            
        Returns:
            Cleanup statistics
        """
        if not self.deduplicator:
            return {'files_removed': 0, 'metadata_cleaned': 0}
        
        cutoff_date = datetime.now() - __import__('timedelta')(days=days)
        files_removed = 0
        metadata_cleaned = 0
        
        # Find old files
        old_files = []
        for file_path, metadata in self.deduplicator.metadata.items():
            if metadata.created_at < cutoff_date:
                old_files.append(file_path)
        
        # Remove old files
        for file_path in old_files:
            try:
                if await aiofiles.os.path.exists(file_path):
                    await aiofiles.os.remove(file_path)
                    files_removed += 1
                
                # Remove from metadata
                del self.deduplicator.metadata[file_path]
                metadata_cleaned += 1
            except Exception as e:
                self.logger.error(f"Failed to remove old file {file_path}: {e}")
        
        # Save updated metadata
        if metadata_cleaned > 0:
            await self.deduplicator._save_metadata()
        
        self.logger.info(f"Cleanup completed: {files_removed} files, {metadata_cleaned} metadata entries")
        
        return {
            'files_removed': files_removed,
            'metadata_cleaned': metadata_cleaned
        }


# Import for async initialization
import asyncio