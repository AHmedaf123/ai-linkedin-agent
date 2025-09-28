#!/usr/bin/env python3
"""
Health check script for AI LinkedIn Agent
Validates environment setup and dependencies
"""

import os
import sys
import importlib
import json
from pathlib import Path

def check_python_version():
    """Check Python version compatibility"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        return False, f"Python {version.major}.{version.minor} is too old. Requires Python 3.8+"
    return True, f"Python {version.major}.{version.minor}.{version.micro}"

def check_required_packages():
    """Check if required packages are installed"""
    required = [
        'requests', 'yaml', 'playwright', 'dotenv'
    ]
    
    missing = []
    for package in required:
        try:
            if package == 'yaml':
                importlib.import_module('yaml')
            elif package == 'dotenv':
                importlib.import_module('dotenv')
            else:
                importlib.import_module(package)
        except ImportError:
            missing.append(package)
    
    if missing:
        return False, f"Missing packages: {', '.join(missing)}"
    return True, "All required packages installed"

def check_environment_variables():
    """Check critical environment variables"""
    required_vars = ['OPENROUTER_API_KEY']
    optional_vars = ['LINKEDIN_EMAIL', 'LINKEDIN_PASSWORD', 'GITHUB_TOKEN']
    
    missing_required = []
    missing_optional = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_required.append(var)
    
    for var in optional_vars:
        if not os.getenv(var):
            missing_optional.append(var)
    
    if missing_required:
        return False, f"Missing required env vars: {', '.join(missing_required)}"
    
    warnings = []
    if missing_optional:
        warnings.append(f"Missing optional env vars: {', '.join(missing_optional)}")
    
    return True, "Environment variables OK" + (f" (Warnings: {'; '.join(warnings)})" if warnings else "")

def check_config_files():
    """Check if required config files exist"""
    required_files = [
        'agent/config.yaml',
        'agent/calendar.yaml',
        'agent/repo_queue.json'
    ]
    
    missing = []
    for file_path in required_files:
        if not Path(file_path).exists():
            missing.append(file_path)
    
    if missing:
        return False, f"Missing config files: {', '.join(missing)}"
    return True, "All config files present"

def check_playwright_installation():
    """Check if Playwright browsers are installed"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            # Try to get browser executable path
            browser_path = p.chromium.executable_path
            if browser_path and Path(browser_path).exists():
                return True, "Playwright browsers installed"
            else:
                return False, "Playwright browsers not installed"
    except Exception as e:
        return False, f"Playwright check failed: {str(e)}"

def main():
    """Run all health checks"""
    print("🔍 AI LinkedIn Agent Health Check")
    print("=" * 40)
    
    checks = [
        ("Python Version", check_python_version),
        ("Required Packages", check_required_packages),
        ("Environment Variables", check_environment_variables),
        ("Config Files", check_config_files),
        ("Playwright Installation", check_playwright_installation),
    ]
    
    all_passed = True
    results = {}
    
    for name, check_func in checks:
        try:
            passed, message = check_func()
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{name:<25} {status} - {message}")
            results[name] = {"passed": passed, "message": message}
            if not passed:
                all_passed = False
        except Exception as e:
            print(f"{name:<25} ❌ ERROR - {str(e)}")
            results[name] = {"passed": False, "message": f"Error: {str(e)}"}
            all_passed = False
    
    print("=" * 40)
    if all_passed:
        print("🎉 All health checks passed!")
        sys.exit(0)
    else:
        print("⚠️  Some health checks failed. Please fix the issues above.")
        sys.exit(1)

if __name__ == "__main__":
    main()