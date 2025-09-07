/**
 * TTS Tool Frontend Application
 * Handles all client-side functionality including API communication,
 * UI interactions, file handling, and audio playback.
 */

class TTSApp {
    constructor() {
        this.baseURL = window.location.origin;
        this.apiURL = `${this.baseURL}/api`;
        this.voices = {};
        this.currentAudio = null;
        this.progressWebSocket = null;
        this.sseConnection = null;
        this.currentJobId = null;
        this.templateInfo = null;
        this.fileStats = null;
        this.settings = {
            maxConcurrent: 3,
            autoPreview: false
        };
        
        this.init();
    }
    
    /**
     * Initialize the application
     */
    async init() {
        this.setupEventListeners();
        this.setupUI();
        await this.loadVoices();
        await this.loadConfig();
        await this.loadTemplateInfo();
        await this.loadFileStats();
        this.loadSettings();
        this.checkAPIStatus();
        this.setupSSEConnection();
        
        // Initialize tooltips and other UI enhancements
        this.initializeTooltips();
        
        console.log('TTS App initialized successfully');
    }
    
    /**
     * Setup all event listeners
     */
    setupEventListeners() {
        // Tab navigation
        document.querySelectorAll('.tab-button').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchTab(e.target.id));
        });
        
        // Text input
        const textInput = document.getElementById('text-input');
        textInput.addEventListener('input', () => this.updateCharCount());
        textInput.addEventListener('paste', () => {
            setTimeout(() => this.updateCharCount(), 10);
        });
        
        document.getElementById('clear-text').addEventListener('click', () => {
            textInput.value = '';
            this.updateCharCount();
        });
        
        
        // Batch processing
        document.getElementById('add-batch-item').addEventListener('click', () => this.addBatchItem());
        document.getElementById('clear-batch-items').addEventListener('click', () => this.clearBatchItems());
        
        // Audio parameters
        this.setupParameterControls();
        
        // Generate buttons
        document.getElementById('generate-single').addEventListener('click', () => this.generateSingle());
        document.getElementById('generate-batch').addEventListener('click', () => this.generateBatch());
        document.getElementById('preview-audio').addEventListener('click', () => this.previewAudio());
        
        // Settings
        document.getElementById('settings-btn').addEventListener('click', () => this.openSettings());
        document.getElementById('close-settings').addEventListener('click', () => this.closeSettings());
        document.getElementById('cancel-settings').addEventListener('click', () => this.closeSettings());
        document.getElementById('save-settings').addEventListener('click', () => this.saveSettings());
        
        
        // File upload for direct input
        document.getElementById('upload-file-btn').addEventListener('click', () => {
            document.getElementById('file-input').click();
        });
        document.getElementById('file-input').addEventListener('change', (e) => this.handleFileUpload(e));
        
        // Single result actions
        document.getElementById('play-single').addEventListener('click', () => this.playSingleAudio());
        document.getElementById('download-single').addEventListener('click', () => this.downloadSingleAudio());
        
        // Batch operations
        document.getElementById('download-completed').addEventListener('click', () => this.downloadCompletedBatchItems());
        document.getElementById('download-all-zip').addEventListener('click', () => this.downloadBatchAsZip());
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => this.handleKeyboardShortcuts(e));
    }
    
    /**
     * Setup UI components
     */
    setupUI() {
        this.updateCharCount();
        this.updateParameterDisplays();
    }
    
    
    /**
     * Setup parameter controls (sliders)
     */
    setupParameterControls() {
        const controls = ['speed', 'volume', 'pitch'];
        
        controls.forEach(control => {
            const slider = document.getElementById(`${control}-slider`);
            const valueDisplay = document.getElementById(`${control}-value`);
            
            slider.addEventListener('input', (e) => {
                const value = parseFloat(e.target.value);
                valueDisplay.textContent = `${value}x`;
            });
        });
        
        // Voice selection
        document.getElementById('voice-select').addEventListener('change', (e) => {
            this.updateEmotionOptions(e.target.value);
        });
        
        // Sampling rate selection
        document.getElementById('sample-rate-select').addEventListener('change', (e) => {
            const sampleRate = this.validateSampleRate(e.target.value);
            // Update the select value to ensure it's valid
            if (sampleRate !== parseInt(e.target.value)) {
                e.target.value = sampleRate.toString();
            }
        });
    }
    
    /**
     * Switch between tabs
     */
    switchTab(tabId) {
        // Update tab buttons
        document.querySelectorAll('.tab-button').forEach(btn => {
            btn.classList.remove('active');
            btn.classList.add('text-gray-500');
            btn.classList.remove('text-primary', 'border-primary');
            btn.style.borderBottomColor = 'transparent';
        });
        
        const activeBtn = document.getElementById(tabId);
        activeBtn.classList.add('active');
        activeBtn.classList.remove('text-gray-500');
        activeBtn.classList.add('text-primary');
        activeBtn.style.borderBottomColor = '#3b82f6';
        
        // Update tab content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.add('hidden');
        });
        
        const contentMap = {
            'tab-text': 'text-input-tab',
            'tab-batch': 'batch-input-tab'
        };
        
        const activeContent = document.getElementById(contentMap[tabId]);
        if (activeContent) {
            activeContent.classList.remove('hidden');
        }
    }
    
    /**
     * Update character count
     */
    updateCharCount() {
        const textInput = document.getElementById('text-input');
        const charCount = document.getElementById('char-count');
        const count = textInput.value.length;
        
        charCount.textContent = `${count} / 10000 字符`;
        
        if (count > 8000) {
            charCount.classList.add('text-warning');
            charCount.classList.remove('text-gray-500');
        } else if (count >= 10000) {
            charCount.classList.add('text-error');
            charCount.classList.remove('text-gray-500', 'text-warning');
        } else {
            charCount.classList.remove('text-warning', 'text-error');
            charCount.classList.add('text-gray-500');
        }
    }
    
    /**
     * Update parameter displays
     */
    updateParameterDisplays() {
        ['speed', 'volume', 'pitch'].forEach(param => {
            const slider = document.getElementById(`${param}-slider`);
            const display = document.getElementById(`${param}-value`);
            display.textContent = `${slider.value}x`;
        });
    }
    
    /**
     * Handle file upload for direct input
     */
    async handleFileUpload(event) {
        const file = event.target.files[0];
        if (!file) return;
        
        // Validate file
        const extension = file.name.toLowerCase().split('.').pop();
        if (!['txt', 'md'].includes(extension)) {
            this.showNotification('只支持 .txt 和 .md 格式文件', 'error');
            return;
        }
        
        if (file.size > 10 * 1024 * 1024) { // 10MB
            this.showNotification('文件大小不能超过 10MB', 'error');
            return;
        }
        
        try {
            const text = await this.readFileAsText(file);
            
            // Update text input
            document.getElementById('text-input').value = text;
            this.updateCharCount();
            
            this.showNotification(`已加载 ${file.name}`, 'success');
        } catch (error) {
            console.error('File read error:', error);
            this.showNotification('文件读取失败', 'error');
        }
        
        // Clear the input so the same file can be selected again
        event.target.value = '';
    }
    
    /**
     * Read file as text
     */
    readFileAsText(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = e => resolve(e.target.result);
            reader.onerror = reject;
            reader.readAsText(file, 'utf-8');
        });
    }
    
    /**
     * Show single generation result
     */
    showSingleResult(data) {
        // Store current result
        this.currentSingleResult = data;
        
        // Update UI
        document.getElementById('single-filename').textContent = data.filename;
        document.getElementById('single-audio').src = data.audioUrl;
        document.getElementById('single-result').classList.remove('hidden');
    }
    
    /**
     * Play single audio result
     */
    playSingleAudio() {
        const audio = document.getElementById('single-audio');
        if (audio.src) {
            if (audio.paused) {
                audio.play();
                document.getElementById('play-single').innerHTML = '<i class="fas fa-pause mr-1"></i>暂停';
            } else {
                audio.pause();
                document.getElementById('play-single').innerHTML = '<i class="fas fa-play mr-1"></i>播放';
            }
        }
    }
    
    /**
     * Download single audio result
     */
    downloadSingleAudio() {
        if (this.currentSingleResult && this.currentSingleResult.audioBlob) {
            const url = URL.createObjectURL(this.currentSingleResult.audioBlob);
            const a = document.createElement('a');
            a.href = url;
            a.download = this.currentSingleResult.filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }
    }
    
    /**
     * Add batch item
     */
    addBatchItem(text = '', filename = '', status = '待处理', errorMsg = '') {
        const tbody = document.getElementById('batch-items');
        const index = tbody.children.length + 1;
        
        // Hide empty state
        document.getElementById('batch-empty-state').style.display = 'none';
        document.getElementById('batch-table').parentElement.style.display = 'block';
        
        const row = document.createElement('tr');
        row.className = 'batch-item hover:bg-gray-50';
        
        // Determine status styling
        let statusClass = 'text-gray-600';
        let statusIcon = 'fas fa-clock';
        if (status === '完成') {
            statusClass = 'text-green-600';
            statusIcon = 'fas fa-check-circle';
        } else if (status === '错误' || errorMsg) {
            statusClass = 'text-red-600';
            statusIcon = 'fas fa-exclamation-circle';
            status = '错误';
        } else if (status === '处理中') {
            statusClass = 'text-blue-600';
            statusIcon = 'fas fa-spinner fa-spin';
        }
        
        // Download button content
        const downloadButton = status === '完成' ? 
            `<button class="download-batch-item text-green-600 hover:text-green-800 text-sm" title="下载">
                <i class="fas fa-download"></i>
            </button>` : 
            `<span class="text-gray-400 text-sm">-</span>`;
        
        row.innerHTML = `
            <td class="border border-gray-300 px-4 py-2 text-center text-sm font-medium text-gray-700">${index}</td>
            <td class="border border-gray-300 px-2 py-1">
                <textarea class="batch-text w-full p-2 border-0 resize-none text-sm bg-transparent" 
                          placeholder="输入文本内容..." maxlength="1000" rows="2" 
                          title="${errorMsg}">${text}</textarea>
            </td>
            <td class="border border-gray-300 px-2 py-1">
                <input type="text" class="batch-filename w-full p-2 border-0 text-sm bg-transparent" 
                       placeholder="自定义文件名" value="${filename}">
            </td>
            <td class="border border-gray-300 px-4 py-2 text-center">
                <span class="batch-status ${statusClass} text-sm">
                    <i class="${statusIcon}"></i>
                    <span class="ml-1">${status}</span>
                </span>
            </td>
            <td class="border border-gray-300 px-4 py-2 text-center">
                ${downloadButton}
            </td>
            <td class="border border-gray-300 px-4 py-2 text-center">
                <button class="remove-batch-item text-red-600 hover:text-red-800 text-sm" title="删除">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        `;
        
        // Add event listener for remove button
        row.querySelector('.remove-batch-item').addEventListener('click', () => {
            row.remove();
            this.updateBatchIndices();
            this.updateBatchOperationsVisibility();
        });
        
        // Add event listener for download button if it exists
        const downloadBtn = row.querySelector('.download-batch-item');
        if (downloadBtn) {
            downloadBtn.addEventListener('click', () => {
                this.downloadBatchItem(row);
            });
        }
        
        tbody.appendChild(row);
        this.updateBatchOperationsVisibility();
    }
    
    /**
     * Download individual batch item
     */
    downloadBatchItem(row) {
        const filename = row.querySelector('.batch-filename').value || 'audio.mp3';
        const fileData = row.fileData; // This will be set when item completes
        
        if (fileData) {
            const a = document.createElement('a');
            a.href = fileData.url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        } else {
            this.showNotification('文件数据不可用', 'error');
        }
    }
    
    /**
     * Update batch operations visibility and counts
     */
    updateBatchOperationsVisibility() {
        const rows = document.querySelectorAll('#batch-items .batch-item');
        const completedRows = Array.from(rows).filter(row => 
            row.querySelector('.batch-status').textContent.includes('完成')
        );
        
        document.getElementById('completed-count').textContent = completedRows.length;
        
        if (completedRows.length > 0) {
            document.getElementById('batch-operations').classList.remove('hidden');
        } else {
            document.getElementById('batch-operations').classList.add('hidden');
        }
    }
    
    /**
     * Download all completed batch items
     */
    downloadCompletedBatchItems() {
        const rows = document.querySelectorAll('#batch-items .batch-item');
        const completedRows = Array.from(rows).filter(row => 
            row.querySelector('.batch-status').textContent.includes('完成') && row.fileData
        );
        
        if (completedRows.length === 0) {
            this.showNotification('没有可下载的文件', 'warning');
            return;
        }
        
        completedRows.forEach(row => {
            this.downloadBatchItem(row);
        });
        
        this.showNotification(`开始下载 ${completedRows.length} 个文件`, 'success');
    }
    
    /**
     * Download batch items as ZIP
     */
    async downloadBatchAsZip() {
        const rows = document.querySelectorAll('#batch-items .batch-item');
        const completedRows = Array.from(rows).filter(row => 
            row.querySelector('.batch-status').textContent.includes('完成')
        );
        
        if (completedRows.length === 0) {
            this.showNotification('没有可下载的文件', 'warning');
            return;
        }
        
        try {
            this.showNotification('正在准备ZIP文件...', 'info');
            
            // Get current audio format
            const currentFormat = document.getElementById('format-select').value || 'mp3';
            
            // Collect file names from completed rows and ensure they have the correct extension
            const files = completedRows.map(row => {
                let filename = row.querySelector('.batch-filename').value || 'audio';
                
                // Remove any existing extension
                const lastDotIndex = filename.lastIndexOf('.');
                if (lastDotIndex > 0) {
                    filename = filename.substring(0, lastDotIndex);
                }
                
                // Add the correct extension based on current format
                return `${filename}.${currentFormat}`;
            });
            
            // Call backend API to create ZIP file
            const response = await fetch('/api/files/batch/download', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ files })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            // Download the ZIP file
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `tts_batch_${new Date().toISOString().slice(0, 10)}.zip`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            
            this.showNotification(`已下载ZIP文件，包含 ${files.length} 个音频文件`, 'success');
            
        } catch (error) {
            console.error('ZIP download failed:', error);
            this.showNotification('ZIP下载失败: ' + error.message, 'error');
        }
    }
    
    /**
     * Update batch item indices
     */
    /**
     * Clear all batch items
     */
    clearBatchItems() {
        const tbody = document.getElementById('batch-items');
        tbody.innerHTML = '';
        
        // Show empty state
        document.getElementById('batch-empty-state').style.display = 'block';
        document.getElementById('batch-table').parentElement.style.display = 'none';
        
        this.showNotification('已清空所有批量处理项目', 'info');
    }
    
    updateBatchIndices() {
        const batchRows = document.querySelectorAll('#batch-items .batch-item');
        batchRows.forEach((row, index) => {
            const indexCell = row.querySelector('td:first-child');
            if (indexCell) {
                indexCell.textContent = index + 1;
            }
        });
        
        // Show/hide empty state
        if (batchRows.length === 0) {
            document.getElementById('batch-empty-state').style.display = 'block';
            document.getElementById('batch-table').parentElement.style.display = 'none';
        }
    }
    
    /**
     * Update batch item status
     */
    updateBatchItemStatus(index, status, errorMsg = '', fileData = null) {
        const rows = document.querySelectorAll('#batch-items .batch-item');
        if (rows[index]) {
            const row = rows[index];
            const statusSpan = row.querySelector('.batch-status');
            const downloadCell = row.querySelectorAll('td')[4]; // Download column
            
            let statusClass = 'text-gray-600';
            let statusIcon = 'fas fa-clock';
            
            if (status === '完成') {
                statusClass = 'text-green-600';
                statusIcon = 'fas fa-check-circle';
                
                // Update download button
                downloadCell.innerHTML = `
                    <button class="download-batch-item text-green-600 hover:text-green-800 text-sm" title="下载">
                        <i class="fas fa-download"></i>
                    </button>
                `;
                
                // Add event listener for new download button
                const downloadBtn = downloadCell.querySelector('.download-batch-item');
                if (downloadBtn) {
                    downloadBtn.addEventListener('click', () => {
                        this.downloadBatchItem(row);
                    });
                }
                
                // Store file data in row
                if (fileData) {
                    row.fileData = fileData;
                }
                
            } else if (status === '错误') {
                statusClass = 'text-red-600';
                statusIcon = 'fas fa-exclamation-circle';
                downloadCell.innerHTML = '<span class="text-gray-400 text-sm">-</span>';
            } else if (status === '处理中') {
                statusClass = 'text-blue-600';
                statusIcon = 'fas fa-spinner fa-spin';
                downloadCell.innerHTML = '<span class="text-gray-400 text-sm">-</span>';
            } else {
                downloadCell.innerHTML = '<span class="text-gray-400 text-sm">-</span>';
            }
            
            statusSpan.className = `batch-status ${statusClass} text-sm`;
            statusSpan.innerHTML = `<i class="${statusIcon}"></i><span class="ml-1">${status}</span>`;
            
            if (errorMsg) {
                const textarea = row.querySelector('.batch-text');
                textarea.title = errorMsg;
            }
            
            // Update batch operations visibility
            this.updateBatchOperationsVisibility();
        }
    }
    
    /**
     * Load available voices from API
     */
    async loadVoices() {
        try {
            const response = await fetch(`${this.apiURL}/voices`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            
            const data = await response.json();
            this.voices = data.categories;
            
            this.updateVoiceSelect();
            this.updateVoicesCount(data.total_count);
            
        } catch (error) {
            console.error('Failed to load voices:', error);
            this.showNotification('加载音色列表失败', 'error');
        }
    }
    
    /**
     * Update voice selection dropdown
     */
    updateVoiceSelect() {
        const select = document.getElementById('voice-select');
        select.innerHTML = '<option value="">选择音色...</option>';
        
        Object.keys(this.voices).forEach(category => {
            const optgroup = document.createElement('optgroup');
            optgroup.label = category;
            
            this.voices[category].forEach(voice => {
                const option = document.createElement('option');
                option.value = voice.voice_type;
                option.textContent = voice.name;
                optgroup.appendChild(option);
            });
            
            select.appendChild(optgroup);
        });
    }
    
    /**
     * Update emotion options based on selected voice
     */
    updateEmotionOptions(voiceType) {
        const emotionSelect = document.getElementById('emotion-select');
        emotionSelect.innerHTML = '<option value="">默认</option>';
        
        if (!voiceType) return;
        
        // Find voice info
        let voiceInfo = null;
        Object.values(this.voices).forEach(category => {
            const voice = category.find(v => v.voice_type === voiceType);
            if (voice) voiceInfo = voice;
        });
        
        if (voiceInfo && voiceInfo.emotions && voiceInfo.emotions.length > 0) {
            voiceInfo.emotions.forEach(emotion => {
                const option = document.createElement('option');
                option.value = emotion;
                option.textContent = emotion;
                emotionSelect.appendChild(option);
            });
        }
    }
    
    /**
     * Load configuration from API
     */
    async loadConfig() {
        try {
            const response = await fetch(`${this.apiURL}/config`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            
            const config = await response.json();
            
            // Set default values from config
            if (config.audio) {
                const audio = config.audio;
                
                if (audio.voice_type) {
                    document.getElementById('voice-select').value = audio.voice_type;
                    this.updateEmotionOptions(audio.voice_type);
                }
                
                if (audio.encoding) {
                    document.getElementById('format-select').value = audio.encoding;
                }
                
                if (audio.speed_ratio) {
                    document.getElementById('speed-slider').value = audio.speed_ratio;
                    document.getElementById('speed-value').textContent = `${audio.speed_ratio}x`;
                }
                
                if (audio.volume_ratio) {
                    document.getElementById('volume-slider').value = audio.volume_ratio;
                    document.getElementById('volume-value').textContent = `${audio.volume_ratio}x`;
                }
                
                if (audio.pitch_ratio) {
                    document.getElementById('pitch-slider').value = audio.pitch_ratio;
                    document.getElementById('pitch-value').textContent = `${audio.pitch_ratio}x`;
                }
                
                if (audio.emotion) {
                    document.getElementById('emotion-select').value = audio.emotion;
                }
            }
            
        } catch (error) {
            console.error('Failed to load config:', error);
            this.showNotification('加载配置失败', 'error');
        }
    }
    
    /**
     * Check API status
     */
    async checkAPIStatus() {
        try {
            const response = await fetch(`${this.baseURL}/health`);
            const data = await response.json();
            
            const statusIndicator = document.getElementById('status-indicator');
            const apiStatus = document.getElementById('api-status');
            
            if (response.ok && data.status === 'healthy') {
                statusIndicator.innerHTML = `
                    <div class="w-3 h-3 bg-green-500 rounded-full mr-2"></div>
                    <span class="text-sm text-gray-600">服务正常</span>
                `;
                apiStatus.textContent = '正常';
                apiStatus.className = 'text-success font-medium';
            } else {
                throw new Error('Service unhealthy');
            }
            
        } catch (error) {
            console.error('API status check failed:', error);
            
            const statusIndicator = document.getElementById('status-indicator');
            const apiStatus = document.getElementById('api-status');
            
            statusIndicator.innerHTML = `
                <div class="w-3 h-3 bg-red-500 rounded-full mr-2"></div>
                <span class="text-sm text-gray-600">服务异常</span>
            `;
            apiStatus.textContent = '异常';
            apiStatus.className = 'text-error font-medium';
        }
    }
    
    /**
     * Generate single TTS audio
     */
    async generateSingle() {
        const text = document.getElementById('text-input').value.trim();
        
        if (!text) {
            this.showNotification('请输入要合成的文本', 'error');
            return;
        }
        
        const params = this.getAudioParameters();
        params.text = text;
        
        try {
            this.showProgress(true, '正在生成音频...', 0);
            this.disableControls(true);
            
            const response = await fetch(`${this.apiURL}/tts/generate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(params)
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || `HTTP ${response.status}`);
            }
            
            const result = await response.json();
            
            this.showProgress(true, '音频生成完成', 100);
            
            if (result.success && result.audio_data) {
                // Create audio blob from base64
                const audioBlob = this.base64ToBlob(result.audio_data, 'audio/mpeg');
                const audioUrl = URL.createObjectURL(audioBlob);
                
                // Show single result area
                this.showSingleResult({
                    filename: result.file_name || `audio_${Date.now()}.${params.encoding}`,
                    audioUrl: audioUrl,
                    audioBlob: audioBlob,
                    result: result
                });
                
                // Auto-play if enabled
                if (this.settings.autoPreview) {
                    this.playAudio(audioUrl);
                }
                
                this.showNotification('音频生成成功', 'success');
            } else {
                throw new Error(result.message || '生成失败');
            }
            
        } catch (error) {
            console.error('TTS generation failed:', error);
            this.showNotification(`生成失败: ${error.message}`, 'error');
            this.showProgress(false);
        } finally {
            this.disableControls(false);
            setTimeout(() => this.showProgress(false), 2000);
        }
    }
    
    /**
     * Generate batch TTS audio
     */
    async generateBatch() {
        const items = this.getBatchItems();
        
        if (items.length === 0) {
            this.showNotification('请添加批量处理项目', 'error');
            return;
        }
        
        const outputDir = './output'; // Fixed server-side output directory
        const filenameTemplate = document.getElementById('filename-template').value.trim();
        const maxConcurrent = this.settings.maxConcurrent;
        
        const request = {
            items: items,
            output_dir: outputDir,
            max_concurrent: maxConcurrent,
            filename_template: filenameTemplate,
            max_retries: 3,
            priority: "normal"
        };
        
        try {
            this.showProgress(true, '正在提交批量任务...', 0);
            this.disableControls(true);
            
            // Mark all items as processing
            items.forEach((_, index) => {
                this.updateBatchItemStatus(index, '等待中');
            });
            
            // Submit batch job
            const response = await fetch(`${this.apiURL}/tts/batch`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(request)
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || `HTTP ${response.status}`);
            }
            
            const result = await response.json();
            
            if (result.success && result.job_id) {
                this.showProgress(true, '任务已提交，正在处理...', 10);
                this.currentJobId = result.job_id;
                
                // Start SSE connection to monitor progress
                this.setupSSEConnection(result.job_id);
                
                // Show job submitted notification
                this.showNotification(`批量任务已提交 (${result.total_items}个项目)`, 'info');
            } else {
                throw new Error(result.message || '任务提交失败');
            }
            
        } catch (error) {
            console.error('Batch TTS generation failed:', error);
            this.showNotification(`批量生成失败: ${error.message}`, 'error');
            this.showProgress(false);
            this.disableControls(false);
        }
    }
    
    /**
     * Preview audio (generate short sample)
     */
    async previewAudio() {
        const text = document.getElementById('text-input').value.trim();
        
        if (!text) {
            this.showNotification('请输入要预览的文本', 'error');
            return;
        }
        
        // Limit preview text to first 100 characters
        const previewText = text.substring(0, 100) + (text.length > 100 ? '...' : '');
        
        const params = this.getAudioParameters();
        params.text = previewText;
        
        try {
            this.showProgress(true, '正在生成预览...', 0);
            
            const response = await fetch(`${this.apiURL}/tts/generate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(params)
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || `HTTP ${response.status}`);
            }
            
            const result = await response.json();
            
            this.showProgress(true, '预览生成完成', 100);
            
            if (result.success && result.audio_data) {
                const audioBlob = this.base64ToBlob(result.audio_data, 'audio/mpeg');
                const audioUrl = URL.createObjectURL(audioBlob);
                
                this.showAudioPreview(audioUrl, result);
                this.playAudio(audioUrl);
                
                this.showNotification('预览生成成功', 'success');
            } else {
                throw new Error(result.message || '预览生成失败');
            }
            
        } catch (error) {
            console.error('Preview generation failed:', error);
            this.showNotification(`预览失败: ${error.message}`, 'error');
            this.showProgress(false);
        } finally {
            setTimeout(() => this.showProgress(false), 2000);
        }
    }
    
    /**
     * Validate and get sampling rate value
     */
    validateSampleRate(value) {
        const validRates = [8000, 16000, 24000];
        const intValue = parseInt(value);
        
        if (validRates.includes(intValue)) {
            return intValue;
        }
        
        // Default to 24000 Hz if invalid value
        console.warn(`Invalid sample rate: ${value}, defaulting to 24000`);
        return 24000;
    }

    /**
     * Get current audio parameters
     */
    getAudioParameters() {
        const sampleRate = this.validateSampleRate(document.getElementById('sample-rate-select').value);
        return {
            voice_type: document.getElementById('voice-select').value || null,
            encoding: document.getElementById('format-select').value,
            speed_ratio: parseFloat(document.getElementById('speed-slider').value),
            volume_ratio: parseFloat(document.getElementById('volume-slider').value),
            pitch_ratio: parseFloat(document.getElementById('pitch-slider').value),
            emotion: document.getElementById('emotion-select').value || null,
            sampling_rate: sampleRate,
            language: null // Could add language selection later
        };
    }
    
    /**
     * Get batch items from UI
     */
    getBatchItems() {
        const items = [];
        const batchRows = document.querySelectorAll('#batch-items .batch-item');
        
        batchRows.forEach(row => {
            const text = row.querySelector('.batch-text').value.trim();
            const filename = row.querySelector('.batch-filename').value.trim();
            
            if (text) {
                const params = this.getAudioParameters();
                params.text = text;
                params.filename = filename || null;
                items.push(params);
            }
        });
        
        return items;
    }
    
    /**
     * Convert base64 to blob
     */
    base64ToBlob(base64, mimeType) {
        const byteCharacters = atob(base64);
        const byteNumbers = new Array(byteCharacters.length);
        
        for (let i = 0; i < byteCharacters.length; i++) {
            byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        
        const byteArray = new Uint8Array(byteNumbers);
        return new Blob([byteArray], { type: mimeType });
    }
    
    /**
     * Show/hide progress panel
     */
    showProgress(show, message = '', percentage = 0) {
        const panel = document.getElementById('progress-panel');
        const text = document.getElementById('progress-text');
        const percentageSpan = document.getElementById('progress-percentage');
        const bar = document.getElementById('progress-bar');
        
        if (show) {
            panel.classList.remove('hidden');
            text.textContent = message;
            percentageSpan.textContent = `${percentage}%`;
            bar.style.width = `${percentage}%`;
        } else {
            panel.classList.add('hidden');
        }
    }
    
    /**
     * Enable/disable controls during processing
     */
    disableControls(disable) {
        const buttons = ['generate-single', 'generate-batch', 'preview-audio'];
        buttons.forEach(id => {
            document.getElementById(id).disabled = disable;
        });
    }
    
    /**
     * Show audio preview
     */
    showAudioPreview(audioUrl, info) {
        const preview = document.getElementById('audio-preview');
        const player = document.getElementById('audio-player');
        const infoDiv = document.getElementById('audio-info');
        
        player.src = audioUrl;
        
        // Update info
        infoDiv.innerHTML = `
            <div class="grid grid-cols-2 gap-4 text-xs">
                <div>
                    <span class="font-medium">音色:</span> ${info.voice_type || '默认'}
                </div>
                <div>
                    <span class="font-medium">格式:</span> ${info.encoding || 'mp3'}
                </div>
                <div>
                    <span class="font-medium">文本长度:</span> ${info.text_length || 0} 字符
                </div>
                <div>
                    <span class="font-medium">文件大小:</span> ${this.formatFileSize(info.file_size || 0)}
                </div>
            </div>
        `;
        
        preview.classList.remove('hidden');
    }
    
    /**
     * Play audio
     */
    playAudio(audioUrl) {
        const player = document.getElementById('audio-player');
        if (player && audioUrl) {
            player.play().catch(error => {
                console.error('Audio play failed:', error);
                this.showNotification('音频播放失败', 'error');
            });
        }
    }
    
    /**
     * Add generated file to list
     */
    addGeneratedFile(fileInfo) {
        const filesList = document.getElementById('files-list');
        const container = document.getElementById('files-container');
        
        filesList.classList.remove('hidden');
        
        const fileItem = document.createElement('div');
        fileItem.className = 'flex items-center justify-between p-2 bg-gray-50 rounded text-sm';
        fileItem.innerHTML = `
            <div class="flex items-center">
                <i class="fas fa-file-audio mr-2 text-primary"></i>
                <div>
                    <div class="font-medium">${fileInfo.name}</div>
                    <div class="text-xs text-gray-500">${this.formatFileSize(fileInfo.size)}</div>
                </div>
            </div>
            <div class="flex space-x-2">
                ${fileInfo.url ? `<button class="play-file text-primary hover:text-primary-dark" title="播放">
                    <i class="fas fa-play"></i>
                </button>` : ''}
                ${fileInfo.url ? `<button class="download-file text-gray-500 hover:text-gray-700" title="下载">
                    <i class="fas fa-download"></i>
                </button>` : ''}
            </div>
        `;
        
        // Add event listeners
        const playBtn = fileItem.querySelector('.play-file');
        if (playBtn && fileInfo.url) {
            playBtn.addEventListener('click', () => this.playAudio(fileInfo.url));
        }
        
        const downloadBtn = fileItem.querySelector('.download-file');
        if (downloadBtn && fileInfo.url) {
            downloadBtn.addEventListener('click', () => this.downloadFile(fileInfo.url, fileInfo.name));
        }
        
        container.appendChild(fileItem);
        
        // Scroll to bottom
        container.scrollTop = container.scrollHeight;
    }
    
    /**
     * Download file
     */
    downloadFile(url, filename) {
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }
    
    /**
     * Format file size
     */
    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }
    
    /**
     * Show notification
     */
    showNotification(message, type = 'info', duration = 5000) {
        const container = document.getElementById('notifications');
        const notification = document.createElement('div');
        
        const typeClasses = {
            success: 'bg-green-500',
            error: 'bg-red-500',
            warning: 'bg-yellow-500',
            info: 'bg-blue-500'
        };
        
        const typeIcons = {
            success: 'fa-check-circle',
            error: 'fa-exclamation-circle',
            warning: 'fa-exclamation-triangle',
            info: 'fa-info-circle'
        };
        
        notification.className = `flex items-center p-4 rounded-lg shadow-lg text-white fade-in ${typeClasses[type]}`;
        notification.innerHTML = `
            <i class="fas ${typeIcons[type]} mr-3"></i>
            <span class="flex-1">${message}</span>
            <button class="ml-3 text-white hover:text-gray-200" onclick="this.parentElement.remove()">
                <i class="fas fa-times"></i>
            </button>
        `;
        
        container.appendChild(notification);
        
        // Auto remove after duration
        if (duration > 0) {
            setTimeout(() => {
                if (notification.parentElement) {
                    notification.remove();
                }
            }, duration);
        }
    }
    
    /**
     * Settings management
     */
    loadSettings() {
        const saved = localStorage.getItem('tts-settings');
        if (saved) {
            this.settings = { ...this.settings, ...JSON.parse(saved) };
        }
        
        document.getElementById('max-concurrent').value = this.settings.maxConcurrent;
        document.getElementById('auto-preview').checked = this.settings.autoPreview;
    }
    
    saveSettings() {
        this.settings.maxConcurrent = parseInt(document.getElementById('max-concurrent').value);
        this.settings.autoPreview = document.getElementById('auto-preview').checked;
        
        localStorage.setItem('tts-settings', JSON.stringify(this.settings));
        this.closeSettings();
        this.showNotification('设置已保存', 'success');
    }
    
    openSettings() {
        document.getElementById('settings-modal').classList.remove('hidden');
        document.getElementById('settings-modal').classList.add('flex');
    }
    
    closeSettings() {
        document.getElementById('settings-modal').classList.add('hidden');
        document.getElementById('settings-modal').classList.remove('flex');
    }
    
    
    
    /**
     * Load files from selected directory into batch processing
     */
    loadFilesToBatch(files) {
        // Clear existing batch items
        document.getElementById('batch-items').innerHTML = '';
        
        // Filter text files
        const textFiles = Array.from(files).filter(file => {
            const extension = file.name.toLowerCase().split('.').pop();
            return ['txt', 'md', 'text'].includes(extension);
        });
        
        if (textFiles.length === 0) {
            this.showNotification('所选目录中没有找到文本文件 (.txt, .md)', 'warning');
            return;
        }
        
        // Switch to batch processing tab
        document.querySelector('[data-tab="batch-input"]').click();
        
        // Process each text file
        textFiles.forEach(async (file, index) => {
            try {
                const text = await this.readFileAsText(file);
                const filename = file.name.replace(/\.[^/.]+$/, ""); // Remove extension
                this.addBatchItem(text, filename);
            } catch (error) {
                console.error(`Error reading file ${file.name}:`, error);
                this.addBatchItem('', file.name, '错误', `无法读取文件: ${error.message}`);
            }
        });
        
        this.showNotification(`已加载 ${textFiles.length} 个文本文件到批量处理`, 'success');
    }
    
    
    /**
     * Update voices count display
     */
    updateVoicesCount(count) {
        document.getElementById('voices-count').textContent = `${count} 种`;
    }
    
    /**
     * Handle keyboard shortcuts
     */
    handleKeyboardShortcuts(e) {
        if (e.ctrlKey || e.metaKey) {
            switch (e.key) {
                case 'Enter':
                    e.preventDefault();
                    this.generateSingle();
                    break;
                case 'p':
                    e.preventDefault();
                    this.previewAudio();
                    break;
                case 'b':
                    e.preventDefault();
                    this.generateBatch();
                    break;
                case ',':
                    e.preventDefault();
                    this.openSettings();
                    break;
            }
        }
        
        if (e.key === 'Escape') {
            this.closeSettings();
        }
    }
    
    /**
     * Initialize tooltips (if needed)
     */
    initializeTooltips() {
        // Add tooltip functionality if needed
        const tooltips = document.querySelectorAll('[title]');
        tooltips.forEach(element => {
            // Could add custom tooltip implementation here
        });
    }

    /**
     * Load template info
     */
    async loadTemplateInfo() {
        try {
            console.log('Loading template info...');
        } catch (error) {
            console.warn('Failed to load template info:', error);
        }
    }

    /**
     * Load file stats
     */
    async loadFileStats() {
        try {
            console.log('Loading file stats...');
        } catch (error) {
            console.warn('Failed to load file stats:', error);
        }
    }

    /**
     * Setup SSE connection for real-time updates
     */
    setupSSEConnection(jobId) {
        try {
            if (this.sseConnection) {
                this.sseConnection.close();
            }
            
            console.log('Setting up SSE connection for job:', jobId);
            this.sseConnection = new EventSource(`${this.apiURL}/progress/sse`);
            
            this.sseConnection.onopen = () => {
                console.log('SSE connection established');
            };
            
            this.sseConnection.onmessage = (event) => {
                try {
                    console.log('Raw SSE message:', event.data);
                    const data = JSON.parse(event.data);
                    console.log('Parsed SSE data:', data);
                    this.handleProgressUpdate(data);
                } catch (error) {
                    console.error('Failed to parse SSE message:', error, 'Raw data:', event.data);
                }
            };
            
            this.sseConnection.onerror = (error) => {
                console.error('SSE connection error:', error);
                // Try to reconnect after 5 seconds
                setTimeout(() => {
                    if (this.currentJobId && this.sseConnection.readyState === EventSource.CLOSED) {
                        this.setupSSEConnection(this.currentJobId);
                    }
                }, 5000);
            };
            
        } catch (error) {
            console.warn('Failed to setup SSE connection:', error);
        }
    }
    
    handleProgressUpdate(data) {
        console.log('Progress update:', data);
        
        // Handle different message types
        if (data.type === 'progress') {
            // Filter events for current job
            if (!this.currentJobId || data.data?.job_id !== this.currentJobId) {
                return;
            }
            
            // Check for specific actions
            if (data.data?.action === 'item_completed') {
                // Handle individual item completion
                const itemIndex = data.data?.item_index;
                console.log('Item completed:', itemIndex, data.data);
                
                if (itemIndex !== undefined) {
                    if (data.data?.success) {
                        // Create file download data
                        const fileData = {
                            url: `${this.apiURL}/files/${encodeURIComponent(data.data?.file_name)}`,
                            filename: data.data?.file_name,
                            size: data.data?.file_size
                        };
                        
                        console.log('Updating item status to completed:', itemIndex, fileData);
                        this.updateBatchItemStatus(itemIndex, '完成', '', fileData);
                    } else {
                        console.log('Updating item status to error:', itemIndex, data.data?.error);
                        this.updateBatchItemStatus(itemIndex, '错误', data.data?.error || '生成失败');
                    }
                }
            } else if (data.data?.action === 'item_started') {
                // Handle item start
                const itemIndex = data.data?.item_index;
                if (itemIndex !== undefined) {
                    console.log('Item started:', itemIndex);
                    this.updateBatchItemStatus(itemIndex, '处理中');
                }
            }
            
            // Handle progress update from queue manager
            const progress = data.data?.progress || 0;
            const completed = data.data?.completed_count || 0;
            const failed = data.data?.failed_count || 0;
            const total = data.data?.total_count || 0;
            
            // Update progress display
            const message = `正在处理... (${completed + failed}/${total})`;
            this.showProgress(true, message, progress);
            
            // Check if job is completed
            if (data.data?.status === 'completed') {
                this.handleBatchCompletion({
                    completed: completed,
                    failed: failed,
                    total: total
                });
            } else if (data.data?.status === 'failed') {
                this.handleBatchError('批量处理失败');
            }
            
        } else {
            // Handle other message types (job_status, system, etc.)
            switch (data.type) {
                case 'job_status':
                    if (data.data?.job_id === this.currentJobId) {
                        if (data.data?.status === 'completed') {
                            this.handleBatchCompletion(data.data);
                        } else if (data.data?.status === 'failed') {
                            this.handleBatchError(data.data?.error || '批量处理失败');
                        }
                    }
                    break;
                    
                case 'system':
                    console.log('System message:', data.data?.message);
                    break;
            }
        }
    }
    
    handleBatchCompletion(data) {
        const completed = data?.completed || 0;
        const failed = data?.failed || 0;
        const total = completed + failed;
        
        this.showProgress(true, '批量生成完成', 100);
        this.showNotification(`批量生成完成: 成功 ${completed} / 失败 ${failed}`, 
                             completed > 0 ? 'success' : 'warning');
        
        // Clean up
        this.currentJobId = null;
        this.disableControls(false);
        if (this.sseConnection) {
            this.sseConnection.close();
            this.sseConnection = null;
        }
        
        // File list refresh not needed in new design
        
        setTimeout(() => this.showProgress(false), 3000);
    }
    
    handleBatchError(error) {
        this.showNotification(`批量生成失败: ${error}`, 'error');
        this.showProgress(false);
        this.disableControls(false);
        
        // Clean up
        this.currentJobId = null;
        if (this.sseConnection) {
            this.sseConnection.close();
            this.sseConnection = null;
        }
    }
}

// Initialize app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.ttsApp = new TTSApp();
});

// Add some global utility functions
window.addEventListener('beforeunload', (e) => {
    // Clean up audio URLs to prevent memory leaks
    const audioElements = document.querySelectorAll('audio');
    audioElements.forEach(audio => {
        if (audio.src && audio.src.startsWith('blob:')) {
            URL.revokeObjectURL(audio.src);
        }
    });
});