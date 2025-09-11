---
issue: 5
title: 开发基础Web界面
analyzed: 2025-09-06T12:29:04Z
estimated_hours: 3
parallelization_factor: 2.5
---

# Parallel Work Analysis: Issue #5

## Overview
Fix the critical sampling rate bug where audio is always generated at 24000Hz regardless of user selection. The frontend has the UI but the parameter isn't being properly passed to and used by the backend TTS service.

## Parallel Streams

### Stream A: Backend Sampling Rate Fix
**Scope**: Fix TTS service to properly receive and use the sampling_rate parameter
**Files**:
- `app/services/tts_service.py` - Add sampling_rate to TTS API payload
- `app/main.py` - Ensure endpoint accepts sampling_rate parameter
- `tts_config.json` - Verify configuration supports rate changes
**Agent Type**: backend-specialist
**Can Start**: immediately
**Estimated Hours**: 1
**Dependencies**: none

### Stream B: Frontend Parameter Passing
**Scope**: Ensure frontend properly sends sampling_rate in API requests
**Files**:
- `static/js/app.js` - Add sampling_rate to formData/request payload
- `templates/index.html` - Verify sampling rate selector has correct ID/name
**Agent Type**: frontend-specialist
**Can Start**: immediately
**Estimated Hours**: 0.5
**Dependencies**: none

### Stream C: File Upload Feature Implementation
**Scope**: Complete the file upload/drag-drop functionality
**Files**:
- `static/js/app.js` - Add drag-drop event handlers and file reading
- `templates/index.html` - Add drop zone UI if missing
- `static/css/style.css` - Style the upload area
**Agent Type**: frontend-specialist
**Can Start**: immediately
**Estimated Hours**: 1
**Dependencies**: none

### Stream D: Comprehensive Testing
**Scope**: Test all sampling rates and verify audio output
**Files**:
- Create test scripts for 8000Hz, 16000Hz, 24000Hz
- Verify audio file headers match selected rate
- Test file upload functionality
**Agent Type**: fullstack-specialist
**Can Start**: after Streams A & B complete
**Estimated Hours**: 0.5
**Dependencies**: Streams A & B

## Coordination Points

### Shared Files
Files that multiple streams modify:
- `static/js/app.js` - Streams B & C (B: form data, C: file handling)
- `templates/index.html` - Streams B & C (minimal overlap)

### Sequential Requirements
1. Backend must properly accept sampling_rate before testing
2. Frontend must send parameter before testing
3. Both fixes required before audio validation

## Conflict Risk Assessment
- **Low-Medium Risk**: Frontend streams work on different JavaScript functions
- **Mitigation**: Stream B focuses on generateAudio(), Stream C on file upload handlers

## Parallelization Strategy

**Recommended Approach**: hybrid

Launch Streams A, B, and C simultaneously. They work on separate concerns with minimal overlap. Stream D starts after A & B complete to verify the bug fix.

## Expected Timeline

With parallel execution:
- Wall time: 1.5 hours (max duration + testing)
- Total work: 3 hours
- Efficiency gain: 50%

Without parallel execution:
- Wall time: 3 hours

## Notes
- **Critical Bug**: Sampling rate always 24000Hz must be fixed first
- Frontend already has UI elements, issue is parameter passing/processing
- Backend needs to include sampling_rate in TTS API request payload
- Test with actual audio generation to verify different Hz outputs
- File upload is separate feature, can proceed independently