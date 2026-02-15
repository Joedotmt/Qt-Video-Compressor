// State management
let currentFile = null;
let videoInfo = null;
let currentJobId = null;

// DOM Elements
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const fileInfo = document.getElementById('fileInfo');
const compressBtn = document.getElementById('compressBtn');
const progressContainer = document.getElementById('progressContainer');
const progressFill = document.getElementById('progressFill');
const progressText = document.getElementById('progressText');
const statusBadge = document.getElementById('statusBadge');
const downloadSection = document.getElementById('downloadSection');
const downloadBtn = document.getElementById('downloadBtn');
const errorMessage = document.getElementById('errorMessage');

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        const tabName = tab.dataset.tab;
        
        // Update active tab
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        
        // Update active content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
        });
        document.getElementById(`${tabName}-tab`).classList.add('active');
    });
});

// Drag and drop handlers
dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        handleFileSelect(files[0]);
    }
});

fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        handleFileSelect(e.target.files[0]);
    }
});

// File handling
async function handleFileSelect(file) {
    if (!file.type.startsWith('video/')) {
        showError('Please select a valid video file');
        return;
    }
    
    currentFile = file;
    
    // Show loading state
    dropZone.innerHTML = '<div class="drop-text">Uploading...</div>';
    compressBtn.disabled = true;
    
    try {
        // Upload file
        const formData = new FormData();
        formData.append('file', file);
        
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Upload failed');
        }
        
        videoInfo = data.info;
        videoInfo.filepath = data.filepath;
        videoInfo.filename = data.filename;
        
        // Update UI
        displayFileInfo();
        compressBtn.disabled = false;
        
        // Auto-fill form fields
        loadSourceSettings();
        
    } catch (error) {
        showError(error.message);
        resetDropZone();
    }
}

function displayFileInfo() {
    const info = videoInfo;
    
    document.getElementById('fileName').textContent = info.filename;
    document.getElementById('fileDuration').textContent = formatDuration(info.duration);
    document.getElementById('fileResolution').textContent = `${info.width}x${info.height}`;
    document.getElementById('fileFps').textContent = `${info.fps} fps`;
    document.getElementById('fileSize').textContent = `${info.file_size_mb} MB`;
    
    fileInfo.classList.add('visible');
    dropZone.innerHTML = `
        <div class="drop-icon">✓</div>
        <div class="drop-text">${info.filename}</div>
        <div class="drop-subtext">Click to change file</div>
    `;
}

function resetDropZone() {
    dropZone.innerHTML = `
        <div class="drop-icon">📹</div>
        <div class="drop-text">Drag & Drop Video File</div>
        <div class="drop-subtext">or click to browse</div>
    `;
}

function formatDuration(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    
    if (hours > 0) {
        return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
}

// Load source settings
function loadSourceSettings() {
    if (!videoInfo) return;
    
    document.getElementById('width').value = videoInfo.width;
    document.getElementById('height').value = videoInfo.height;
    document.getElementById('fps').value = videoInfo.fps;
    document.getElementById('audioBitrate').value = videoInfo.audio_bitrate;
    document.getElementById('targetSize').value = videoInfo.file_size_mb.toFixed(2);
    
    updateVideoPreview();
    updateEstimatedBitrate();
}

document.getElementById('useSourceSettings').addEventListener('click', loadSourceSettings);

document.getElementById('matchSourceSize').addEventListener('click', () => {
    if (videoInfo) {
        document.getElementById('targetSize').value = videoInfo.file_size_mb.toFixed(2);
        updateEstimatedBitrate();
    }
});

document.getElementById('matchSourceAudio').addEventListener('click', () => {
    if (videoInfo) {
        document.getElementById('audioBitrate').value = videoInfo.audio_bitrate;
        updateEstimatedBitrate();
    }
});

// Update video preview
function updateVideoPreview() {
    const width = document.getElementById('width').value;
    const height = document.getElementById('height').value;
    const fps = document.getElementById('fps').value;
    
    let preview = '';
    if (width && height) {
        const evenWidth = Math.floor(width / 2) * 2;
        const evenHeight = Math.floor(height / 2) * 2;
        preview += `${evenWidth}x${evenHeight}`;
    }
    if (fps) {
        const fpsNum = parseFloat(fps);
        const fpsStr = Number.isInteger(fpsNum) ? fpsNum.toString() : fpsNum.toFixed(2).replace(/\.?0+$/, '');
        preview += ` @ ${fpsStr} fps`;
    }
    
    document.getElementById('videoPreview').textContent = preview;
}

document.getElementById('width').addEventListener('input', updateVideoPreview);
document.getElementById('height').addEventListener('input', updateVideoPreview);
document.getElementById('fps').addEventListener('input', updateVideoPreview);

// Update estimated bitrate
function updateEstimatedBitrate() {
    if (!videoInfo) return;
    
    const targetSize = parseFloat(document.getElementById('targetSize').value);
    const audioBitrate = parseFloat(document.getElementById('audioBitrate').value) || videoInfo.audio_bitrate;
    const muted = document.getElementById('muteAudio').checked;
    
    if (!targetSize || targetSize <= 0) {
        document.getElementById('estimatedBitrate').value = '';
        return;
    }
    
    const duration = videoInfo.duration;
    const audioBps = muted ? 0 : audioBitrate * 1000;
    const targetBits = targetSize * 1024 * 1024 * 8;
    const videoBps = (targetBits / duration) - audioBps;
    const adjustedVideoBps = videoBps * 0.97; // Safety margin
    
    if (adjustedVideoBps <= 0) {
        document.getElementById('estimatedBitrate').value = '0';
        return;
    }
    
    const videoKbps = Math.floor(adjustedVideoBps / 1000);
    document.getElementById('estimatedBitrate').value = videoKbps.toString();
}

document.getElementById('targetSize').addEventListener('input', updateEstimatedBitrate);
document.getElementById('audioBitrate').addEventListener('input', updateEstimatedBitrate);
document.getElementById('muteAudio').addEventListener('change', updateEstimatedBitrate);

// Compression
compressBtn.addEventListener('click', startCompression);

async function startCompression() {
    if (!videoInfo) {
        showError('Please select a video file first');
        return;
    }
    
    hideError();
    
    // Validate inputs
    const width = document.getElementById('width').value;
    const height = document.getElementById('height').value;
    const fps = document.getElementById('fps').value;
    const targetSize = document.getElementById('targetSize').value;
    const crf = document.getElementById('crf').value;
    
    if (!width || !height || !fps) {
        showError('Please fill in width, height, and FPS');
        return;
    }
    
    if (!crf && !targetSize) {
        showError('Please enter either a target size or CRF value');
        return;
    }
    
    // Prepare compression settings
    const settings = {
        input_file: videoInfo.filepath,
        width: width,
        height: height,
        fps: fps,
        target_size: targetSize,
        preset: document.getElementById('preset').value,
        mute_audio: document.getElementById('muteAudio').checked,
        audio_bitrate: document.getElementById('audioBitrate').value || videoInfo.audio_bitrate,
        duration: videoInfo.duration,
        crf: crf || null,
        tune: document.getElementById('tune').value
    };
    
    try {
        // Start compression
        const response = await fetch('/compress', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(settings)
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Compression failed');
        }
        
        currentJobId = data.job_id;
        
        // Show progress
        compressBtn.disabled = true;
        progressContainer.classList.add('visible');
        downloadSection.classList.remove('visible');
        
        // Poll for status
        pollCompressionStatus();
        
    } catch (error) {
        showError(error.message);
    }
}

async function pollCompressionStatus() {
    try {
        const response = await fetch(`/status/${currentJobId}`);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to get status');
        }
        
        // Update progress
        progressFill.style.width = `${data.progress}%`;
        progressText.textContent = `${data.progress}%`;
        
        if (data.status === 'completed') {
            statusBadge.textContent = 'Completed';
            statusBadge.className = 'status-badge status-completed';
            compressBtn.disabled = false;
            
            // Show download section
            const compressionRatio = ((1 - (data.output_size_mb / videoInfo.file_size_mb)) * 100).toFixed(1);
            document.getElementById('outputSize').textContent = `${data.output_size_mb} MB`;
            document.getElementById('compressionRatio').textContent = `${compressionRatio}%`;
            downloadSection.classList.add('visible');
            
        } else if (data.status === 'failed') {
            statusBadge.textContent = 'Failed';
            statusBadge.className = 'status-badge status-failed';
            showError(data.error || 'Compression failed');
            compressBtn.disabled = false;
            
        } else {
            // Continue polling
            setTimeout(pollCompressionStatus, 500);
        }
        
    } catch (error) {
        showError(error.message);
        compressBtn.disabled = false;
    }
}

// Download
downloadBtn.addEventListener('click', () => {
    if (currentJobId) {
        window.location.href = `/download/${currentJobId}`;
    }
});

// Error handling
function showError(message) {
    errorMessage.textContent = message;
    errorMessage.classList.add('visible');
}

function hideError() {
    errorMessage.classList.remove('visible');
}

// Check FFmpeg on load
async function checkFFmpeg() {
    try {
        const response = await fetch('/check_ffmpeg');
        const data = await response.json();
        
        if (!data.installed) {
            showError('FFmpeg is not installed. Please install FFmpeg to use this application.');
            compressBtn.disabled = true;
        }
    } catch (error) {
        console.error('Failed to check FFmpeg:', error);
    }
}

checkFFmpeg();
