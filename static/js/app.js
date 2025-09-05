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
        this.loadSettings();
        this.checkAPIStatus();
        
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
        
        // File upload
        this.setupFileUpload();
        
        // Batch processing
        document.getElementById('add-batch-item').addEventListener('click', () => this.addBatchItem());
        
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
        
        // Directory browsing
        document.getElementById('browse-dir').addEventListener('click', () => this.browseDirectory());
        
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
     * Setup file upload functionality
     */
    setupFileUpload() {
        const dropZone = document.getElementById('drop-zone');
        const fileInput = document.getElementById('file-input');
        const selectBtn = document.getElementById('select-file-btn');
        const removeBtn = document.getElementById('remove-file');
        
        // Drag and drop
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });
        
        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover');
        });
        
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                this.handleFileSelect(files[0]);
            }
        });
        
        // File input
        selectBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                this.handleFileSelect(e.target.files[0]);
            }
        });
        
        // Remove file
        removeBtn.addEventListener('click', () => this.removeFile());
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
            'tab-file': 'file-input-tab',
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
     * Handle file selection
     */
    async handleFileSelect(file) {
        if (!file) return;
        
        // Validate file
        if (!file.name.endsWith('.txt')) {
            this.showNotification('只支持 .txt 格式文件', 'error');
            return;
        }
        
        if (file.size > 10 * 1024 * 1024) { // 10MB
            this.showNotification('文件大小不能超过 10MB', 'error');
            return;
        }
        
        try {
            const text = await this.readFileAsText(file);
            
            // Show file info
            document.getElementById('file-name').textContent = file.name;
            document.getElementById('file-info').classList.remove('hidden');
            
            // Update text input
            document.getElementById('text-input').value = text;
            this.updateCharCount();
            
            this.showNotification('文件上传成功', 'success');
        } catch (error) {
            console.error('File read error:', error);
            this.showNotification('文件读取失败', 'error');
        }
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
     * Remove uploaded file
     */
    removeFile() {
        document.getElementById('file-info').classList.add('hidden');
        document.getElementById('file-input').value = '';
        document.getElementById('text-input').value = '';
        this.updateCharCount();
    }
    
    /**
     * Add batch item
     */
    addBatchItem(text = '', filename = '') {
        const container = document.getElementById('batch-items');
        const index = container.children.length + 1;
        
        const itemDiv = document.createElement('div');
        itemDiv.className = 'batch-item bg-gray-50 p-4 rounded-lg border';
        itemDiv.innerHTML = `
            <div class="flex items-start space-x-3">
                <div class="flex-1 grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">文本 #${index}</label>
                        <textarea class="batch-text w-full p-2 border border-gray-300 rounded text-sm" 
                                  placeholder="输入文本..." maxlength="1000" rows="2">${text}</textarea>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">文件名 (可选)</label>
                        <input type="text" class="batch-filename w-full p-2 border border-gray-300 rounded text-sm" 
                               placeholder="自定义文件名..." value="${filename}">
                    </div>
                </div>
                <button class="remove-batch-item text-error hover:text-red-700 p-1" title="删除">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `;
        
        // Add event listener for remove button
        itemDiv.querySelector('.remove-batch-item').addEventListener('click', () => {
            itemDiv.remove();
            this.updateBatchIndices();
        });
        
        container.appendChild(itemDiv);
    }
    
    /**
     * Update batch item indices
     */
    updateBatchIndices() {
        const items = document.querySelectorAll('.batch-item');
        items.forEach((item, index) => {
            const label = item.querySelector('label');
            label.textContent = `文本 #${index + 1}`;
        });
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
                
                // Show preview
                this.showAudioPreview(audioUrl, result);
                
                // Auto-play if enabled
                if (this.settings.autoPreview) {
                    this.playAudio(audioUrl);
                }
                
                // Add to files list
                this.addGeneratedFile({
                    name: `audio_${Date.now()}.${params.encoding}`,
                    size: result.file_size,
                    url: audioUrl,
                    info: result
                });
                
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
        
        const outputDir = document.getElementById('output-dir').value.trim() || './output';
        const filenameTemplate = document.getElementById('filename-template').value.trim();
        const maxConcurrent = this.settings.maxConcurrent;
        
        const request = {
            items: items,
            output_dir: outputDir,
            max_concurrent: maxConcurrent,
            filename_template: filenameTemplate
        };
        
        try {
            this.showProgress(true, '正在批量生成音频...', 0);
            this.disableControls(true);
            
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
            
            this.showProgress(true, '批量生成完成', 100);
            
            // Process results
            if (result.results && result.results.length > 0) {
                result.results.forEach((item, index) => {
                    if (item.success && item.file_path) {
                        this.addGeneratedFile({
                            name: item.file_name || `batch_${index + 1}.mp3`,
                            size: item.file_size || 0,
                            path: item.file_path,
                            info: item
                        });
                    }
                });
            }
            
            const message = `批量生成完成: 成功 ${result.completed} / 失败 ${result.failed}`;
            this.showNotification(message, result.completed > 0 ? 'success' : 'warning');
            
        } catch (error) {
            console.error('Batch TTS generation failed:', error);
            this.showNotification(`批量生成失败: ${error.message}`, 'error');
            this.showProgress(false);
        } finally {
            this.disableControls(false);
            setTimeout(() => this.showProgress(false), 2000);
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
     * Get current audio parameters
     */
    getAudioParameters() {
        return {
            voice_type: document.getElementById('voice-select').value || null,
            encoding: document.getElementById('format-select').value,
            speed_ratio: parseFloat(document.getElementById('speed-slider').value),
            volume_ratio: parseFloat(document.getElementById('volume-slider').value),
            pitch_ratio: parseFloat(document.getElementById('pitch-slider').value),
            emotion: document.getElementById('emotion-select').value || null,
            language: null // Could add language selection later
        };
    }
    
    /**
     * Get batch items from UI
     */
    getBatchItems() {
        const items = [];
        const batchItems = document.querySelectorAll('.batch-item');
        
        batchItems.forEach(item => {
            const text = item.querySelector('.batch-text').value.trim();
            const filename = item.querySelector('.batch-filename').value.trim();
            
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
     * Directory browsing (placeholder - would need backend support)
     */
    browseDirectory() {
        this.showNotification('目录浏览功能需要后端支持', 'info');
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