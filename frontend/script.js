// AI 数据转换器 - 前端脚本
// 调用后端 API 进行数据转换

// 后端 API 地址配置
const API_BASE_URL = 'http://localhost:8000';

// DOM 元素
const uploadArea = document.getElementById('uploadArea');
const fileInput = document.getElementById('fileInput');
const btnUpload = document.querySelector('.btn-upload');
const uploadedFile = document.getElementById('uploadedFile');
const fileName = document.getElementById('fileName');
const fileSize = document.getElementById('fileSize');
const fileIcon = document.getElementById('fileIcon');
const deleteFile = document.getElementById('deleteFile');
const optionsSection = document.getElementById('optionsSection');
const convertBtn = document.getElementById('convertBtn');
const statusSection = document.getElementById('statusSection');
const statusMessage = document.getElementById('statusMessage');
const progressBar = document.getElementById('progressBar');
const progressFill = document.querySelector('.progress-fill');
const resultSection = document.getElementById('resultSection');
const resultContent = document.getElementById('resultContent');
const resultFileName = document.getElementById('resultFileName');
const resultConfidence = document.getElementById('resultConfidence');
const copyBtn = document.getElementById('copyBtn');
const downloadBtn = document.getElementById('downloadBtn');
const newBtn = document.getElementById('newBtn');
const conversionType = document.getElementById('conversionType');
const outputFormat = document.getElementById('outputFormat');
const customPrompt = document.getElementById('customPrompt');

// 当前上传的文件
let currentFile = null;
let convertedResult = '';
let currentResultData = null;

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    initUpload();
    initButtons();
    initTabs();
});

// 初始化上传功能
function initUpload() {
    btnUpload.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFile(e.target.files[0]);
        }
    });

    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('drag-over');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('drag-over');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('drag-over');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    });

    deleteFile.addEventListener('click', () => {
        resetUpload();
    });
}

// 处理文件
function handleFile(file) {
    const allowedTypes = ['.ppt', '.pptx', '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.txt', '.csv'];
    const fileExt = '.' + file.name.split('.').pop().toLowerCase();

    if (!allowedTypes.includes(fileExt)) {
        showStatus('不支持该文件格式', 'error');
        return;
    }

    const maxSize = 50 * 1024 * 1024;
    if (file.size > maxSize) {
        showStatus('文件过大，请上传不超过 50MB 的文件', 'error');
        return;
    }

    currentFile = file;
    fileName.textContent = file.name;
    fileSize.textContent = formatFileSize(file.size);
    fileIcon.textContent = getFileIcon(fileExt);

    uploadedFile.style.display = 'flex';
    uploadArea.style.display = 'none';
    optionsSection.style.display = 'grid';
    convertBtn.disabled = false;

    hideStatus();
}

// 重置上传
function resetUpload() {
    currentFile = null;
    fileInput.value = '';
    uploadedFile.style.display = 'none';
    uploadArea.style.display = 'flex';
    optionsSection.style.display = 'none';
    convertBtn.disabled = true;
    hideStatus();
    hideResult();
    currentResultData = null;
}

// 初始化按钮
function initButtons() {
    convertBtn.addEventListener('click', startConversion);
    copyBtn.addEventListener('click', copyResult);
    downloadBtn.addEventListener('click', downloadResult);
    newBtn.addEventListener('click', resetUpload);
}

// 初始化标签页
function initTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            displayTabContent(btn.dataset.tab);
        });
    });
}

// 开始转换
async function startConversion() {
    if (!currentFile) {
        showStatus('请先上传文件', 'error');
        return;
    }

    setLoading(true);
    showStatus('正在上传并转换文件...', 'info');
    showProgress();

    try {
        const formData = new FormData();
        formData.append('file', currentFile);
        formData.append('fileType', 'auto');
        formData.append('conversionType', conversionType.value);
        formData.append('outputFormat', outputFormat.value);
        if (customPrompt.value) {
            formData.append('customPrompt', customPrompt.value);
        }

        updateProgress(20);

        const response = await fetch(`${API_BASE_URL}/api/v1/convert/auto`, {
            method: 'POST',
            body: formData
        });

        updateProgress(60);

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.msg || `请求失败: ${response.status}`);
        }

        const data = await response.json();
        updateProgress(80);

        if (data.code !== 200) {
            throw new Error(data.msg || '转换失败');
        }

        currentResultData = data.data;
        displayResult(data.data);

        updateProgress(100);
        showStatus('转换成功！', 'success');

    } catch (error) {
        console.error('转换失败:', error);
        showStatus(`转换失败: ${error.message}`, 'error');
    } finally {
        setLoading(false);
        setTimeout(() => hideProgress(), 1000);
    }
}

// 显示结果
function displayResult(data) {
    convertedResult = data.convertedContent || '';

    resultFileName.textContent = `文件: ${data.fileName}`;
    resultConfidence.textContent = `置信度: ${(data.confidence * 100).toFixed(1)}%`;

    // 默认显示转换内容标签
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('.tab-btn[data-tab="content"]').classList.add('active');
    displayTabContent('content');

    resultSection.style.display = 'block';
    resultSection.scrollIntoView({ behavior: 'smooth' });
}

// 显示标签页内容
function displayTabContent(tab) {
    if (!currentResultData) return;

    let content = '';

    switch (tab) {
        case 'content':
            content = formatContent(currentResultData.convertedContent);
            break;
        case 'structured':
            if (currentResultData.structuredData) {
                content = `<pre class="json-content">${JSON.stringify(currentResultData.structuredData, null, 2)}</pre>`;
            } else {
                content = '<p class="no-data">无结构化数据</p>';
            }
            break;
        case 'logs':
            if (currentResultData.processingLogs && currentResultData.processingLogs.length > 0) {
                content = '<div class="logs-list">';
                currentResultData.processingLogs.forEach(log => {
                    const levelClass = log.level === 'error' ? 'log-error' : log.level === 'warning' ? 'log-warning' : 'log-info';
                    content += `
                        <div class="log-item ${levelClass}">
                            <span class="log-step">[${log.step}]</span>
                            <span class="log-message">${log.message}</span>
                        </div>
                    `;
                });
                content += '</div>';
            } else {
                content = '<p class="no-data">无处理日志</p>';
            }
            break;
    }

    resultContent.innerHTML = content;
}

// 格式化内容
function formatContent(content) {
    if (!content) return '';

    // 检测是否为JSON
    try {
        const parsed = JSON.parse(content);
        return `<pre class="json-content">${JSON.stringify(parsed, null, 2)}</pre>`;
    } catch {
        // 不是JSON，按文本处理
    }

    return content
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>');
}

// 复制结果
async function copyResult() {
    try {
        await navigator.clipboard.writeText(convertedResult);
        showStatus('结果已复制到剪贴板', 'success');
    } catch (err) {
        showStatus('复制失败，请手动复制', 'error');
    }
}

// 下载结果
function downloadResult() {
    const format = outputFormat.value;
    let mimeType = 'text/plain';
    let ext = 'txt';

    if (format === 'json') {
        mimeType = 'application/json';
        ext = 'json';
    } else if (format === 'markdown') {
        mimeType = 'text/markdown';
        ext = 'md';
    } else if (format === 'html') {
        mimeType = 'text/html';
        ext = 'html';
    }

    const blob = new Blob([convertedResult], { type: mimeType + ';charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${currentFile ? currentFile.name.split('.')[0] : 'converted'}_converted.${ext}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showStatus('结果已下载', 'success');
}

// 隐藏结果
function hideResult() {
    resultSection.style.display = 'none';
    resultContent.innerHTML = '';
    convertedResult = '';
}

// 设置加载状态
function setLoading(loading) {
    const btnText = convertBtn.querySelector('.btn-text');
    const btnLoading = convertBtn.querySelector('.btn-loading');

    if (loading) {
        convertBtn.disabled = true;
        btnText.style.display = 'none';
        btnLoading.style.display = 'inline-flex';
    } else {
        convertBtn.disabled = false;
        btnText.style.display = 'inline';
        btnLoading.style.display = 'none';
    }
}

// 显示状态消息
function showStatus(message, type = 'info') {
    statusSection.style.display = 'block';
    statusMessage.textContent = message;
    statusMessage.className = 'status-message ' + type;
}

// 隐藏状态
function hideStatus() {
    statusSection.style.display = 'none';
    statusMessage.textContent = '';
}

// 显示进度条
function showProgress() {
    progressBar.style.display = 'block';
    updateProgress(0);
}

// 隐藏进度条
function hideProgress() {
    progressBar.style.display = 'none';
}

// 更新进度
function updateProgress(percent) {
    progressFill.style.width = percent + '%';
}

// 格式化文件大小
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 获取文件图标
function getFileIcon(ext) {
    const icons = {
        '.ppt': '&#128202;',
        '.pptx': '&#128202;',
        '.pdf': '&#128196;',
        '.jpg': '&#127748;',
        '.jpeg': '&#127748;',
        '.png': '&#127748;',
        '.gif': '&#127748;',
        '.txt': '&#128221;',
        '.csv': '&#128207;'
    };
    return icons[ext] || '&#128196;';
}
