"""
Tests for file management service
"""

import pytest
import asyncio
import os
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from app.services.file_manager import (
    FileManager, FilenameTemplate, DirectoryOrganizer, FileDeduplicator,
    FileMetadata
)


class TestFilenameTemplate:
    """Test filename template functionality"""
    
    def test_init_and_validation(self):
        """Test template initialization and validation"""
        # Valid template
        template = FilenameTemplate("tts_{index}_{date}.{ext}")
        assert template.template == "tts_{index}_{date}.{ext}"
        
        # Invalid variables (should still work but warn)
        template = FilenameTemplate("tts_{invalid}_{date}.{ext}")
        assert template.template == "tts_{invalid}_{date}.{ext}"
    
    def test_basic_rendering(self):
        """Test basic template rendering"""
        template = FilenameTemplate("tts_{index}_{date}.{ext}")
        context = {'index': 1, 'voice': 'zh_female'}
        
        filename = template.render(context, 'mp3')
        
        # Should contain index and date
        assert '1' in filename
        assert datetime.now().strftime('%Y%m%d') in filename
        assert filename.endswith('.mp3')
    
    def test_variable_substitution(self):
        """Test all variable substitutions"""
        template = FilenameTemplate("{voice}_{language}_{index}_{text_hash}.{ext}")
        
        context = {
            'index': 5,
            'voice': 'zh_female_1',
            'language': 'zh-cn',
            'text': 'Hello world'
        }
        
        filename = template.render(context, 'wav')
        
        assert 'zh_female_1' in filename
        assert 'zh-cn' in filename
        assert '5' in filename
        assert filename.endswith('.wav')
        assert len(filename.split('_')[-1].split('.')[0]) == 8  # text_hash should be 8 chars
    
    def test_sanitization(self):
        """Test filename sanitization"""
        template = FilenameTemplate("{voice}.{ext}")
        
        # Test with invalid characters
        context = {'voice': 'test<>:"/\\|?*voice'}
        filename = template.render(context, 'mp3')
        
        # Should not contain invalid chars
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            assert char not in filename
    
    def test_edge_cases(self):
        """Test edge cases"""
        template = FilenameTemplate("{nonexistent}_{index}.{ext}")
        
        # Missing variable should trigger fallback behavior
        context = {'index': 1}
        filename = template.render(context, 'mp3')
        
        # Should fall back to default naming when template fails
        assert filename.startswith('tts_1_')  # Fallback format
        assert filename.endswith('.mp3')


class TestDirectoryOrganizer:
    """Test directory organization functionality"""
    
    def test_flat_organization(self):
        """Test flat organization"""
        organizer = DirectoryOrganizer("/test", "flat")
        path = organizer.get_output_path({})
        
        assert path == Path("/test")
    
    def test_date_organization(self):
        """Test date-based organization"""
        organizer = DirectoryOrganizer("/test", "date")
        path = organizer.get_output_path({})
        
        now = datetime.now()
        expected_path = Path("/test") / now.strftime('%Y') / now.strftime('%m') / now.strftime('%d')
        assert path == expected_path
    
    def test_voice_organization(self):
        """Test voice-based organization"""
        organizer = DirectoryOrganizer("/test", "voice")
        context = {'voice_type': 'zh_female_1'}
        path = organizer.get_output_path(context)
        
        expected_path = Path("/test") / "zh_female_1"
        assert path == expected_path
    
    def test_complex_organization(self):
        """Test complex organization patterns"""
        organizer = DirectoryOrganizer("/test", "date_voice")
        context = {'voice_type': 'zh_female_1'}
        path = organizer.get_output_path(context)
        
        now = datetime.now()
        expected_path = (Path("/test") / now.strftime('%Y') / now.strftime('%m') / 
                        now.strftime('%d') / "zh_female_1")
        assert path == expected_path
    
    def test_invalid_organization(self):
        """Test invalid organization type falls back to flat"""
        organizer = DirectoryOrganizer("/test", "invalid_type")
        assert organizer.organization == "flat"


class TestFileDeduplicator:
    """Test file deduplication functionality"""
    
    @pytest.fixture
    def temp_metadata_file(self):
        """Create temporary metadata file"""
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        yield path
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    
    @pytest.mark.asyncio
    async def test_hash_computation(self, temp_metadata_file):
        """Test MD5 hash computation"""
        deduplicator = FileDeduplicator(temp_metadata_file)
        
        # Create temp file with known content
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_file = f.name
        
        try:
            hash_value = await deduplicator.compute_file_hash(temp_file)
            
            # Known MD5 of "test content"
            expected_hash = "9a0364b9e99bb480dd25e1f0284c8555"
            assert hash_value == expected_hash
        finally:
            os.unlink(temp_file)
    
    @pytest.mark.asyncio
    async def test_metadata_operations(self, temp_metadata_file):
        """Test metadata add/remove operations"""
        deduplicator = FileDeduplicator(temp_metadata_file)
        
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_file = f.name
        
        try:
            # Add metadata
            metadata = await deduplicator.add_file_metadata(
                temp_file,
                voice_type='test_voice',
                encoding='mp3'
            )
            
            assert metadata.file_path == str(Path(temp_file).resolve())
            assert metadata.voice_type == 'test_voice'
            assert metadata.encoding == 'mp3'
            
            # Check if in memory
            assert temp_file in deduplicator.metadata or str(Path(temp_file).resolve()) in deduplicator.metadata
            
            # Remove metadata
            await deduplicator.remove_metadata(temp_file)
            assert str(Path(temp_file).resolve()) not in deduplicator.metadata
            
        finally:
            os.unlink(temp_file)


class TestFileManager:
    """Test main file manager functionality"""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def file_manager(self, temp_dir):
        """Create file manager instance"""
        return FileManager(
            base_output_dir=temp_dir,
            default_template="test_{index}_{datetime}.{ext}",
            organization="flat",
            enable_deduplication=False  # Disabled for testing
        )
    
    @pytest.mark.asyncio
    async def test_filename_generation(self, file_manager):
        """Test filename generation"""
        context = {
            'index': 1,
            'voice_type': 'zh_female_1',
            'text': 'Test text'
        }
        
        filename = await file_manager.generate_filename(context, extension='mp3')
        
        assert 'test_1_' in filename
        assert filename.endswith('.mp3')
    
    @pytest.mark.asyncio
    async def test_output_path_generation(self, file_manager):
        """Test output path generation"""
        context = {
            'index': 1,
            'voice_type': 'zh_female_1'
        }
        
        path = await file_manager.get_output_path(context)
        
        # Should be in base directory (flat organization)
        assert path.parent == file_manager.base_output_dir
        assert path.name.startswith('test_1_')
        assert path.suffix == '.mp3'
    
    @pytest.mark.asyncio
    async def test_conflict_resolution(self, file_manager, temp_dir):
        """Test file conflict resolution"""
        # Create existing file
        existing_file = Path(temp_dir) / "test_file.mp3"
        existing_file.touch()
        
        # Try to resolve conflict
        resolved_path = await file_manager.resolve_file_conflicts(existing_file)
        
        # Should be different from original
        assert resolved_path != existing_file
        assert resolved_path.stem.endswith('_1')  # Should append _1
        assert resolved_path.suffix == '.mp3'
    
    @pytest.mark.asyncio
    async def test_batch_filename_mapping(self, file_manager):
        """Test batch filename mapping"""
        items = [
            {'text': 'First audio clip', 'voice_type': 'zh_female'},
            {'text': 'Second audio clip with longer text', 'voice_type': 'zh_male'},
            {'text': 'Third', 'voice_type': 'en_female'}
        ]
        
        mappings = await file_manager.batch_filename_mapping(items)
        
        assert len(mappings) == 3
        
        # Check mapping format
        for i, (preview, filename) in enumerate(mappings):
            assert isinstance(preview, str)
            assert isinstance(filename, str)
            assert f'test_{i+1}_' in filename
            
            # Preview should be truncated version of text
            expected_text = items[i]['text'][:50]
            if len(items[i]['text']) > 50:
                expected_text += '...'
            assert preview == expected_text
    
    @pytest.mark.asyncio
    async def test_file_save_with_management(self, file_manager, temp_dir):
        """Test file saving with full management"""
        audio_data = b"fake audio data for testing"
        context = {
            'text': 'Test audio',
            'voice_type': 'zh_female_1',
            'encoding': 'mp3',
            'language': 'zh-cn'
        }
        
        result = await file_manager.save_file_with_management(
            audio_data=audio_data,
            context=context,
            custom_filename="custom_test.mp3"
        )
        
        assert result['success'] is True
        assert result['new_file'] is True
        assert result['size'] == len(audio_data)
        
        # Check file exists
        file_path = result['file_path']
        assert Path(file_path).exists()
        
        # Check content
        with open(file_path, 'rb') as f:
            saved_data = f.read()
        assert saved_data == audio_data


@pytest.mark.asyncio
async def test_integration_workflow():
    """Test complete workflow integration"""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create file manager
        file_manager = FileManager(
            base_output_dir=temp_dir,
            default_template="integration_{voice}_{index}.{ext}",
            organization="voice",
            enable_deduplication=False
        )
        
        # Test complete workflow
        items = [
            {'text': 'Integration test 1', 'voice_type': 'zh_female'},
            {'text': 'Integration test 2', 'voice_type': 'zh_female'},
            {'text': 'Integration test 3', 'voice_type': 'en_male'}
        ]
        
        # Generate mappings
        mappings = await file_manager.batch_filename_mapping(items)
        assert len(mappings) == 3
        
        # Save files
        for i, item in enumerate(items):
            context = {
                'index': i + 1,
                'text': item['text'],
                'voice_type': item['voice_type'],
                'encoding': 'mp3'
            }
            
            audio_data = f"Audio data for item {i+1}".encode()
            
            result = await file_manager.save_file_with_management(
                audio_data=audio_data,
                context=context
            )
            
            assert result['success'] is True
            
            # File should be in voice-organized directory
            file_path = Path(result['file_path'])
            assert item['voice_type'] in str(file_path)
            assert file_path.exists()
        
        # Check directory structure
        created_dirs = [d for d in Path(temp_dir).iterdir() if d.is_dir()]
        expected_voices = {'zh_female', 'en_male'}
        created_voices = {d.name for d in created_dirs}
        assert created_voices == expected_voices


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])