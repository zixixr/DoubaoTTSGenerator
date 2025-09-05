#!/usr/bin/env python3
"""
Test script for file manager functionality
"""

import asyncio
import sys
import os

# Add app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.services.file_manager import FileManager, FilenameTemplate, DirectoryOrganizer


async def test_filename_template():
    """Test filename template functionality"""
    print("Testing filename template...")
    
    template = FilenameTemplate("tts_{voice}_{date}_{index}.{ext}")
    
    context = {
        'voice': 'zh_female_1',
        'index': 1,
        'text': 'Hello world test'
    }
    
    filename = template.render(context, 'mp3')
    print(f"Generated filename: {filename}")
    
    # Test different templates
    templates = [
        "tts_{index}_{datetime}.{ext}",
        "{voice}_{date}_{time}.{ext}",
        "audio_{text_hash}_{voice}.{ext}",
        "{language}_{voice}_{index}.{ext}"
    ]
    
    for tmpl in templates:
        template = FilenameTemplate(tmpl)
        context_ext = context.copy()
        context_ext['language'] = 'zh-cn'
        
        filename = template.render(context_ext, 'mp3')
        print(f"Template: {tmpl} -> {filename}")


async def test_directory_organizer():
    """Test directory organizer functionality"""
    print("\nTesting directory organizer...")
    
    base_dir = "./test_output"
    
    organizers = ['flat', 'date', 'voice', 'language', 'date_voice', 'voice_date']
    
    for org_type in organizers:
        organizer = DirectoryOrganizer(base_dir, org_type)
        
        context = {
            'voice_type': 'zh_female_1',
            'language': 'zh-cn',
            'category': 'general'
        }
        
        path = organizer.get_output_path(context)
        print(f"Organization: {org_type} -> {path}")


async def test_file_manager():
    """Test file manager functionality"""
    print("\nTesting file manager...")
    
    # Create file manager
    file_manager = FileManager(
        base_output_dir="./test_output",
        default_template="test_{index}_{datetime}.{ext}",
        organization="date",
        enable_deduplication=False  # Disable for simple test
    )
    
    # Test filename generation
    context = {
        'index': 1,
        'voice_type': 'zh_female_1',
        'text': 'Test audio synthesis',
        'language': 'zh-cn'
    }
    
    filename = await file_manager.generate_filename(context, extension='mp3')
    print(f"Generated filename: {filename}")
    
    # Test output path
    output_path = await file_manager.get_output_path(context)
    print(f"Output path: {output_path}")
    
    # Test batch mapping
    items = [
        {'text': 'First test audio', 'voice_type': 'zh_female_1'},
        {'text': 'Second test audio', 'voice_type': 'zh_male_1'},
        {'text': 'Third test audio', 'voice_type': 'en_female_1'}
    ]
    
    mappings = await file_manager.batch_filename_mapping(items)
    print("Batch filename mappings:")
    for preview, filename in mappings:
        print(f"  {preview} -> {filename}")


async def main():
    """Main test function"""
    print("File Manager Test Suite")
    print("=" * 50)
    
    try:
        await test_filename_template()
        await test_directory_organizer()
        await test_file_manager()
        
        print("\n" + "=" * 50)
        print("All tests completed successfully!")
        
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())