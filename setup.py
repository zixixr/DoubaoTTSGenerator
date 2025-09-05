#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTS Tool Setup Script
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def check_python_version():
    """Check Python version compatibility"""
    if sys.version_info < (3, 8):
        print("[ERROR] Python 3.8 or higher is required")
        print(f"   Current version: {sys.version}")
        return False
    print(f"[OK] Python version: {sys.version.split()[0]}")
    return True

def create_virtual_environment():
    """Create virtual environment if it doesn't exist"""
    venv_path = Path("venv")
    if venv_path.exists():
        print("[OK] Virtual environment already exists")
        return True
    
    try:
        print("[INFO] Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", "venv"], check=True)
        print("[OK] Virtual environment created successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to create virtual environment: {e}")
        return False

def get_pip_command():
    """Get the correct pip command for the platform"""
    if sys.platform == "win32":
        return os.path.join("venv", "Scripts", "pip.exe")
    else:
        return os.path.join("venv", "bin", "pip")

def install_dependencies():
    """Install Python dependencies"""
    pip_cmd = get_pip_command()
    
    if not os.path.exists(pip_cmd):
        print("[ERROR] Virtual environment pip not found")
        return False
    
    try:
        print("[INFO] Installing dependencies...")
        # Try to upgrade pip, but don't fail if it doesn't work
        try:
            subprocess.run([pip_cmd, "install", "--upgrade", "pip"], check=True)
            print("[OK] Pip upgraded successfully")
        except subprocess.CalledProcessError:
            print("[WARN] Pip upgrade failed, continuing with existing version")
        
        # Install requirements
        subprocess.run([pip_cmd, "install", "-r", "requirements.txt"], check=True)
        print("[OK] Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to install dependencies: {e}")
        return False

def setup_environment_file():
    """Setup environment configuration"""
    env_file = Path(".env")
    env_example = Path(".env.example")
    
    if env_file.exists():
        print("[OK] .env file already exists")
        return True
    
    if env_example.exists():
        try:
            shutil.copy(env_example, env_file)
            print("[OK] Created .env from template")
            print("[WARN] Please edit .env file with your actual API credentials")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to create .env file: {e}")
            return False
    else:
        print("[ERROR] .env.example template not found")
        return False

def create_directories():
    """Create necessary directories"""
    dirs = ["output", "logs"]
    for dir_name in dirs:
        dir_path = Path(dir_name)
        if not dir_path.exists():
            try:
                dir_path.mkdir(parents=True)
                print(f"[OK] Created directory: {dir_name}")
            except Exception as e:
                print(f"[ERROR] Failed to create directory {dir_name}: {e}")
                return False
        else:
            print(f"[OK] Directory already exists: {dir_name}")
    return True

def display_next_steps():
    """Display next steps to user"""
    print("\n" + "="*50)
    print("Setup completed successfully!")
    print("="*50)
    print("\nNext steps:")
    print("1. Edit .env file with your TTS API credentials")
    print("2. Activate virtual environment:")
    
    if sys.platform == "win32":
        print("   .\\venv\\Scripts\\activate")
    else:
        print("   source venv/bin/activate")
    
    print("3. Run the application:")
    print("   python main.py")
    print("\n4. Open browser to: http://127.0.0.1:8000")
    print("\nFor more information, see README.md")

def main():
    """Main setup function"""
    print("TTS Tool Setup")
    print("="*30)
    
    # Check Python version
    if not check_python_version():
        sys.exit(1)
    
    # Create virtual environment
    if not create_virtual_environment():
        sys.exit(1)
    
    # Install dependencies
    if not install_dependencies():
        sys.exit(1)
    
    # Setup environment file
    if not setup_environment_file():
        sys.exit(1)
    
    # Create directories
    if not create_directories():
        sys.exit(1)
    
    # Display next steps
    display_next_steps()

if __name__ == "__main__":
    main()