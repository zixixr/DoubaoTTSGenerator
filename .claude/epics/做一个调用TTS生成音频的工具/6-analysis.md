---
issue: 6
analyzed: 2025-09-06T04:23:15Z
streams: 4
---

# Issue #6 Analysis: 实现批处理逻辑和队列管理

## Current State Analysis

**Backend**: Complete and robust async queue system exists with:
- Full job management (pause/resume/cancel)
- Progress tracking and persistence
- Retry logic and error handling
- Advanced file management with templates

**Frontend**: Integration gap causing user-facing issues:
- Batch processing returns "undefined" message
- Generated files not visible to users
- No real-time progress updates

## Root Cause Analysis

**Primary Bug**: Frontend expects synchronous response with `result.completed` and `result.failed` properties, but receives async job submission response. This causes:
1. `app.js:620-621` displays "批量生成完成undefined"
2. No mechanism to poll job status or show progress
3. Files generated asynchronously but frontend doesn't refresh file list

**Missing Integration**: Frontend lacks connection to existing backend progress tracking infrastructure (SSE/WebSocket endpoints exist but unused).

## Work Stream Decomposition

### Stream A: Frontend Bug Fix (Critical)
- **Agent Type**: general-purpose
- **Scope**: Fix immediate "undefined" display bug and file visibility
- **Files**: `static/js/app.js` (batch processing section)
- **Can Start**: immediately
- **Dependencies**: none

### Stream B: Progress Integration
- **Agent Type**: general-purpose  
- **Scope**: Connect frontend to existing SSE progress system
- **Files**: `static/js/app.js` (progress tracking), `templates/index.html` (progress UI)
- **Can Start**: immediately (parallel to A)
- **Dependencies**: none

### Stream C: Queue Control UI
- **Agent Type**: general-purpose
- **Scope**: Implement pause/resume/cancel buttons in frontend
- **Files**: `templates/index.html` (UI), `static/js/app.js` (controls)
- **Can Start**: after Stream B (needs progress system)
- **Dependencies**: progress integration

### Stream D: File Discovery Enhancement
- **Agent Type**: general-purpose
- **Scope**: Auto-refresh file list after batch completion
- **Files**: `static/js/app.js` (file list management)
- **Can Start**: immediately (parallel to A,B)
- **Dependencies**: none

## Coordination Notes

- **Stream A** (bug fix) has highest priority - should complete first
- **Streams B & D** can work in parallel with A
- **Stream C** depends on B's progress integration
- All streams modify `app.js` - coordinate via git commits and avoid merge conflicts
- Test each stream independently before integration

## Testing Strategy

**Stream A**: Verify batch generation shows proper completion message and files appear
**Stream B**: Confirm real-time progress updates during batch processing  
**Stream C**: Test pause/resume/cancel controls work correctly
**Stream D**: Ensure file list auto-refreshes after batch completion

**Integration Test**: Complete batch workflow from submission to file access