/* ═══════════════════════════════════════════════════════════════════════════
   WOWBOX - Client-Side Application
   ═══════════════════════════════════════════════════════════════════════════ */

// ─── State ──────────────────────────────────────────────────────────────────
let selectedFile = null;
let audioBlob = null;
let mediaRecorder = null;
let audioChunks = [];
let queuePollInterval = null;
const POLL_RATE = 3000; // 3 seconds

// ─── DOM Elements ───────────────────────────────────────────────────────────
const loginScreen = document.getElementById('login-screen');
const appScreen = document.getElementById('app-screen');
const loginForm = document.getElementById('login-form');
const passwordInput = document.getElementById('password-input');
const loginBtn = document.getElementById('login-btn');
const loginError = document.getElementById('login-error');
const logoutBtn = document.getElementById('logout-btn');

const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');
const previewSection = document.getElementById('preview-section');
const previewImage = document.getElementById('preview-image');
const previewFilename = document.getElementById('preview-filename');
const previewFilesize = document.getElementById('preview-filesize');
const previewClose = document.getElementById('preview-close');
const sendPrintBtn = document.getElementById('send-print-btn');

// Audio elements
const recordAudioBtn = document.getElementById('record-audio-btn');
const recordBtnText = document.getElementById('record-btn-text');
const audioPlaybackContainer = document.getElementById('audio-playback-container');
const audioPlayback = document.getElementById('audio-playback');
const removeAudioBtn = document.getElementById('remove-audio-btn');

const queueList = document.getElementById('queue-list');
const queueEmpty = document.getElementById('queue-empty');
const clearQueueBtn = document.getElementById('clear-queue-btn');
const agentStatus = document.getElementById('agent-status');

// ─── Init ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    setupEventListeners();
});

// ─── Auth ───────────────────────────────────────────────────────────────────
async function checkAuth() {
    try {
        const res = await fetch('/api/check-auth');
        const data = await res.json();
        if (data.authenticated) {
            showApp();
        } else {
            showLogin();
        }
    } catch (err) {
        showLogin();
    }
}

function showLogin() {
    loginScreen.classList.add('active');
    appScreen.classList.remove('active');
    stopQueuePolling();
    passwordInput.focus();
}

function showApp() {
    loginScreen.classList.remove('active');
    appScreen.classList.add('active');
    startQueuePolling();
    refreshQueue();
}

async function handleLogin(e) {
    e.preventDefault();
    const password = passwordInput.value.trim();
    if (!password) return;

    setButtonLoading(loginBtn, true);
    hideError();

    try {
        const res = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password })
        });
        const data = await res.json();

        if (res.ok && data.success) {
            showApp();
            passwordInput.value = '';
        } else {
            showError(data.error || 'Incorrect password');
        }
    } catch (err) {
        showError('Server connection error');
    } finally {
        setButtonLoading(loginBtn, false);
    }
}

async function handleLogout() {
    try {
        await fetch('/api/logout', { method: 'POST' });
    } catch (err) {
        // ignore
    }
    showLogin();
}

function showError(message) {
    loginError.textContent = message;
    loginError.classList.remove('hidden');
}

function hideError() {
    loginError.classList.add('hidden');
}

// ─── Event Listeners ────────────────────────────────────────────────────────
function setupEventListeners() {
    // Login
    loginForm.addEventListener('submit', handleLogin);
    logoutBtn.addEventListener('click', handleLogout);

    // Upload zone click
    uploadZone.addEventListener('click', () => fileInput.click());

    // File input change
    fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
            handleFileSelect(e.target.files[0]);
        }
    });

    // Drag & drop
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        uploadZone.classList.add('drag-over');
    });

    uploadZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        e.stopPropagation();
        uploadZone.classList.remove('drag-over');
    });

    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        uploadZone.classList.remove('drag-over');
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleFileSelect(e.dataTransfer.files[0]);
        }
    });

    // Preview controls
    previewClose.addEventListener('click', clearPreview);
    sendPrintBtn.addEventListener('click', handleUpload);

    // Audio controls
    setupAudioRecording();

    // Clear queue
    clearQueueBtn.addEventListener('click', handleClearQueue);
}

// ─── File Selection & Preview ───────────────────────────────────────────────
function handleFileSelect(file) {
    // Validate file type
    const allowed = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp', 'image/heic', 'image/heif'];
    if (!allowed.includes(file.type) && !file.name.match(/\.(jpg|jpeg|png|gif|webp|heic|heif)$/i)) {
        showToast('Unsupported file type', 'error');
        return;
    }

    // Validate file size (20MB)
    if (file.size > 20 * 1024 * 1024) {
        showToast('File too large (max 20MB)', 'error');
        return;
    }

    selectedFile = file;

    // Show preview
    const reader = new FileReader();
    reader.onload = (e) => {
        previewImage.src = e.target.result;
        previewFilename.textContent = file.name;
        previewFilesize.textContent = formatFileSize(file.size);
        previewSection.classList.remove('hidden');

        // Scroll to preview
        previewSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };
    reader.readAsDataURL(file);
}

function clearPreview() {
    selectedFile = null;
    audioBlob = null;
    if (audioPlayback) audioPlayback.src = '';
    if (audioPlaybackContainer) audioPlaybackContainer.classList.add('hidden');
    if (recordAudioBtn) recordAudioBtn.classList.remove('hidden');
    
    previewSection.classList.add('hidden');
    previewImage.src = '';
    fileInput.value = '';
}

function setupAudioRecording() {
    let isRecording = false;

    const startRecording = async (e) => {
        if (e && e.cancelable) e.preventDefault();
        if (isRecording) return;
        
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ 
                audio: {
                    autoGainControl: false,
                    echoCancellation: false,
                    noiseSuppression: false
                } 
            });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];
            
            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };
            
            mediaRecorder.onstop = () => {
                audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                const audioUrl = URL.createObjectURL(audioBlob);
                audioPlayback.src = audioUrl;
                
                recordAudioBtn.classList.add('hidden');
                audioPlaybackContainer.classList.remove('hidden');
                
                stream.getTracks().forEach(track => track.stop());
            };
            
            mediaRecorder.start();
            isRecording = true;
            recordAudioBtn.style.background = 'var(--accent-light)';
            recordBtnText.textContent = 'Recording... (Release to stop)';
            recordAudioBtn.classList.add('recording-pulse');
            
        } catch (err) {
            console.error("Mic access error", err);
            showToast('Microphone access denied', 'error');
        }
    };

    const stopRecording = (e) => {
        if (!isRecording) return;
        if (e && e.cancelable) e.preventDefault();
        if (!mediaRecorder || mediaRecorder.state === 'inactive') return;
        
        mediaRecorder.stop();
        isRecording = false;
        recordAudioBtn.style.background = 'var(--accent)';
        recordBtnText.textContent = 'Hold to Record Voice Message';
        recordAudioBtn.classList.remove('recording-pulse');
    };

    if (recordAudioBtn) {
        recordAudioBtn.addEventListener('mousedown', startRecording);
        recordAudioBtn.addEventListener('touchstart', startRecording, {passive: false});
        
        window.addEventListener('mouseup', stopRecording);
        window.addEventListener('touchend', stopRecording);
    }
    
    if (removeAudioBtn) {
        removeAudioBtn.addEventListener('click', (e) => {
            e.preventDefault();
            audioBlob = null;
            audioPlayback.src = '';
            audioPlaybackContainer.classList.add('hidden');
            recordAudioBtn.classList.remove('hidden');
        });
    }
}

// ─── Upload ─────────────────────────────────────────────────────────────────
async function handleUpload() {
    if (!selectedFile) return;

    setButtonLoading(sendPrintBtn, true);

    const formData = new FormData();
    formData.append('image', selectedFile);

    if (audioBlob) {
        formData.append('audio', audioBlob, 'audio.webm');
    }

    try {
        const res = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        const data = await res.json();

        if (res.ok && data.success) {
            const overlay = document.getElementById('success-overlay');
            if (overlay) {
                overlay.classList.add('active');
                setTimeout(() => {
                    overlay.classList.remove('active');
                    clearPreview();
                    refreshQueue();
                }, 3000); // 3 second emotional delay
            } else {
                showToast('Sent with Love! 💖', 'success');
                clearPreview();
                refreshQueue();
            }
        } else if (res.status === 401) {
            showToast('Please login again', 'error');
            showLogin();
        } else {
            showToast(data.error || 'Error uploading photo', 'error');
        }
    } catch (err) {
        showToast('Server connection error', 'error');
    } finally {
        setButtonLoading(sendPrintBtn, false);
    }
}

// ─── Queue ──────────────────────────────────────────────────────────────────
function startQueuePolling() {
    if (queuePollInterval) return;
    queuePollInterval = setInterval(refreshQueue, POLL_RATE);
}

function stopQueuePolling() {
    if (queuePollInterval) {
        clearInterval(queuePollInterval);
        queuePollInterval = null;
    }
}

async function refreshQueue() {
    try {
        const res = await fetch('/api/queue');
        if (res.status === 401) {
            showLogin();
            return;
        }

        const data = await res.json();
        renderQueue(data.queue || []);
    } catch (err) {
        // Silent fail for polling
    }
}

function renderQueue(queue) {
    // 🟢 Filter out cancelled items so they are permanently hidden from the UI
    queue = queue.filter(item => item.status !== 'cancelled');

    if (queue.length === 0) {
        queueList.innerHTML = '';
        queueEmpty.classList.remove('hidden');
        clearQueueBtn.classList.add('hidden');
        return;
    }

    queueEmpty.classList.add('hidden');

    // Show clear button if any completed/failed items
    const hasCompleted = queue.some(item => item.status === 'completed' || item.status === 'failed');
    clearQueueBtn.classList.toggle('hidden', !hasCompleted);

    // Build queue HTML
    const existingIds = new Set();
    const html = queue.map(item => {
        existingIds.add(item.id);
        return createQueueItemHTML(item);
    }).join('');

    // Only update if content changed
    const newContent = html;
    if (queueList.dataset.lastContent !== newContent) {
        queueList.innerHTML = newContent;
        queueList.dataset.lastContent = newContent;

        // Attach event listeners to cancel buttons
        queueList.querySelectorAll('.queue-cancel-btn').forEach(btn => {
            btn.addEventListener('click', () => handleCancelItem(btn.dataset.id));
        });
    }
}

function createQueueItemHTML(item) {
    const statusBadge = getStatusBadge(item.status);
    const timeAgo = getTimeAgo(item.created_at);
    const showCancel = item.status === 'pending' || item.status === 'printing';
    const thumbUrl = `/api/thumbnail/${item.id}`;

    return `
        <div class="queue-item" data-id="${item.id}">
            <div class="queue-item-thumb">
                <img src="${thumbUrl}" alt="" loading="lazy" onerror="this.style.display='none'">
            </div>
            <div class="queue-item-info">
                <div class="queue-item-name">${escapeHTML(item.original_name)}</div>
                <div class="queue-item-time">${timeAgo}${item.error ? ' • ' + escapeHTML(item.error) : ''}</div>
            </div>
            <div class="queue-item-actions">
                ${statusBadge}
                ${showCancel ? `
                    <button class="queue-cancel-btn" data-id="${item.id}" title="Cancel">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                ` : ''}
            </div>
        </div>
    `;
}

function getStatusBadge(status) {
    switch (status) {
        case 'pending':
            return `<span class="status-badge status-pending">
                <span class="status-dots"><span></span><span></span><span></span></span>
                Waiting
            </span>`;
        case 'printing':
            return `<span class="status-badge status-printing">
                <span class="status-spinner"></span>
                Printing
            </span>`;
        case 'completed':
            return `<span class="status-badge status-completed">
                <svg class="status-check" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                Printed
            </span>`;
        case 'failed':
            return `<span class="status-badge status-failed">
                <svg class="status-x" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
                Failed
            </span>`;
        default:
            return `<span class="status-badge">${status}</span>`;
    }
}

async function handleCancelItem(itemId) {
    try {
        const res = await fetch(`/api/queue/${itemId}`, { method: 'DELETE' });
        const data = await res.json();

        if (res.ok) {
            showToast('Printing cancelled', 'info');
            refreshQueue();
        } else {
            showToast(data.error || 'Cancellation error', 'error');
        }
    } catch (err) {
        showToast('Connection error', 'error');
    }
}

async function handleClearQueue() {
    try {
        const res = await fetch('/api/queue/clear', { method: 'POST' });
        if (res.ok) {
            showToast('History cleared', 'info');
            refreshQueue();
        }
    } catch (err) {
        showToast('Connection error', 'error');
    }
}

// ─── Toast Notifications ────────────────────────────────────────────────────
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        ${getToastIcon(type)}
        <span>${message}</span>
    `;

    container.appendChild(toast);

    // Auto dismiss
    setTimeout(() => {
        toast.classList.add('toast-out');
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

function getToastIcon(type) {
    switch (type) {
        case 'success':
            return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                <polyline points="22 4 12 14.01 9 11.01"></polyline>
            </svg>`;
        case 'error':
            return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="15" y1="9" x2="9" y2="15"></line>
                <line x1="9" y1="9" x2="15" y2="15"></line>
            </svg>`;
        default:
            return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="16" x2="12" y2="12"></line>
                <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>`;
    }
}

// ─── Utility ────────────────────────────────────────────────────────────────
function setButtonLoading(btn, loading) {
    const text = btn.querySelector('.btn-text');
    const loader = btn.querySelector('.btn-loader');
    if (loading) {
        text.classList.add('hidden');
        loader.classList.remove('hidden');
        btn.disabled = true;
    } else {
        text.classList.remove('hidden');
        loader.classList.add('hidden');
        btn.disabled = false;
    }
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function getTimeAgo(isoString) {
    const now = new Date();
    const date = new Date(isoString + 'Z'); // UTC
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);

    if (diffSec < 30) return 'Just now';
    if (diffSec < 60) return `${diffSec}s ago`;
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHour < 24) return `${diffHour}h ago`;
    return `${diffDay}d ago`;
}

function escapeHTML(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ─── Gentle Guidelines Rotation ───────────────────────────────────────────
function setupGuidelinesRotation() {
    const guidelineEl = document.getElementById('gentle-guideline');
    if (!guidelineEl) return;
    
    const guidelines = [
        '"Share the story behind this photo..."',
        '"Tell them a memory that makes you smile..."',
        '"Sing a few lines of a favorite song..."',
        '"Record the sounds of your surroundings..."',
        '"Just say hello and that you love them..."'
    ];
    
    let currentIndex = 0;
    
    setInterval(() => {
        guidelineEl.style.opacity = '0';
        setTimeout(() => {
            currentIndex = (currentIndex + 1) % guidelines.length;
            guidelineEl.textContent = guidelines[currentIndex];
            guidelineEl.style.opacity = '1';
        }, 1000); // Wait for fade out to complete
    }, 8000); // Rotate every 8 seconds
}

// Initialize guidelines when DOM is loaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupGuidelinesRotation);
} else {
    setupGuidelinesRotation();
}
