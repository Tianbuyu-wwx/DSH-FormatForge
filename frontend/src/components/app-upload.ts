// ============================================================
// <app-upload> 文件上传组件
// ============================================================
// 功能：拖拽上传、点击选择、格式校验、大小限制、格式标签展示

import { LitElement, html, css } from 'lit';
import { customElement, state, property } from 'lit/decorators.js';
import type { FileInfo } from '../types/index.js';
import { store } from '../state/store.js';
import {
  getFileIcon, getFileCategory, formatFileSize,
  ALLOWED_EXTENSIONS, FORMAT_CATEGORIES,
  getMaxSize, getSizeLabel,
} from '../utils/format.js';

@customElement('app-upload')
export class AppUpload extends LitElement {
  /** 是否正在拖拽悬停 */
  @state() private _dragOver = false;

  /** 当前选中的文件信息 */
  @property({ type: Object, attribute: false }) file: FileInfo | null = null;

  private _input: HTMLInputElement | null = null;

  static styles = css`
    :host {
      display: block;
    }

    /* 上传区域 - 状态切换 */
    .upload-area {
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      padding: 60px 40px;
      border-radius: 16px;
      border: 2px dashed var(--color-border);
      cursor: pointer;
      transition: all 0.3s ease;
      background: var(--color-surface);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
    }

    .upload-area:hover {
      background: var(--color-surface-hover);
      border-color: rgba(255, 255, 255, 0.5);
    }

    .upload-area.drag-over {
      background: rgba(102, 126, 234, 0.15);
      border-color: var(--color-primary);
      transform: scale(1.02);
    }

    .upload-icon {
      font-size: 4rem;
      margin-bottom: 16px;
      transition: transform 0.3s ease;
    }

    .drag-over .upload-icon {
      transform: translateY(-8px);
    }

    .upload-title {
      font-size: 1.5rem;
      font-weight: 600;
      margin-bottom: 12px;
    }

    /* 格式标签 */
    .format-tags {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 6px 10px;
      max-width: 580px;
      margin-bottom: 12px;
    }

    .format-tag {
      display: inline-flex;
      align-items: baseline;
      gap: 3px;
      background: rgba(255, 255, 255, 0.06);
      padding: 2px 8px;
      border-radius: 4px;
      white-space: nowrap;
    }

    .tag-label {
      font-weight: 600;
      color: var(--color-info);
      font-size: 0.75rem;
    }

    .tag-formats {
      font-size: 0.75rem;
      color: rgba(255, 255, 255, 0.75);
    }

    .size-hint {
      font-size: 0.82rem;
      color: var(--color-text-muted);
      margin-bottom: 20px;
    }

    .size-hint strong {
      color: var(--color-success);
    }

    .upload-btn {
      background: linear-gradient(135deg, var(--color-primary) 0%, #764ba2 100%);
      color: white;
      border: none;
      padding: 14px 32px;
      font-size: 1rem;
      font-weight: 600;
      border-radius: 8px;
      cursor: pointer;
      transition: all 0.3s ease;
      box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
    }

    .upload-btn:hover {
      transform: translateY(-2px);
      box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
    }

    /* 已上传文件卡片 */
    .file-card {
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--color-surface);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border-radius: 12px;
      padding: 20px;
      animation: fadeIn 0.3s ease;
    }

    .file-info {
      display: flex;
      align-items: center;
      gap: 15px;
    }

    .file-icon {
      font-size: 2.5rem;
    }

    .file-details {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .file-name {
      font-size: 1.1rem;
      font-weight: 500;
    }

    .file-meta {
      display: flex;
      gap: 12px;
      font-size: 0.85rem;
      opacity: 0.8;
    }

    .file-meta .category-badge {
      display: inline-block;
      background: rgba(116, 185, 255, 0.2);
      color: var(--color-info);
      padding: 1px 8px;
      border-radius: 10px;
      font-size: 0.78rem;
    }

    .btn-delete {
      background: rgba(255, 255, 255, 0.2);
      border: none;
      padding: 10px 12px;
      border-radius: 8px;
      cursor: pointer;
      font-size: 1.2rem;
      transition: all 0.3s ease;
      color: white;
    }

    .btn-delete:hover {
      background: rgba(255, 100, 100, 0.5);
    }
  `;

  connectedCallback() {
    super.connectedCallback();
    // 订阅 store 以同步外部 reset
    this._unsub = store.subscribe((s) => {
      // 仅当外部清空了 file 而我们还有时才同步
      if (!s.file && this.file) {
        this.file = null;
        this.requestUpdate();
      }
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  private _unsub?: () => void;

  render() {
    if (this.file) {
      return this._renderFileCard();
    }
    return this._renderUploadArea();
  }

  /** 上传区域（未选择文件时） */
  private _renderUploadArea() {
    const dragClass = this._dragOver ? 'drag-over' : '';
    return html`
      <div
        class="upload-area ${dragClass}"
        @click=${this._onAreaClick}
        @dragover=${this._onDragOver}
        @dragleave=${this._onDragLeave}
        @drop=${this._onDrop}
      >
        <div class="upload-icon">${this._dragOver ? '📂' : '📁'}</div>
        <div class="upload-title">${this._dragOver ? '松开以上传文件' : '拖放文件到此处或点击上传'}</div>

        <div class="format-tags">
          ${FORMAT_CATEGORIES.map(cat => html`
            <span class="format-tag">
              <span class="tag-label">${cat.label}:</span>
              <span class="tag-formats">${cat.formats}</span>
            </span>
          `)}
        </div>

        <p class="size-hint">
          单个文件不超过 <strong>50MB</strong>（图片不超过 20MB）
        </p>

        <button class="upload-btn">选择文件</button>
        <input
          type="file"
          hidden
          accept="${ALLOWED_EXTENSIONS.join(',')}"
          @change=${this._onFileSelected}
        />
      </div>
    `;
  }

  /** 已上传文件卡片 */
  private _renderFileCard() {
    if (!this.file) return html``;
    const ext = this.file.extension;
    return html`
      <div class="file-card">
        <div class="file-info">
          <span class="file-icon">${getFileIcon(ext)}</span>
          <div class="file-details">
            <span class="file-name">${this.file.name}</span>
            <div class="file-meta">
              <span>${formatFileSize(this.file.size)}</span>
              <span class="category-badge">${ext}</span>
            </div>
          </div>
        </div>
        <button class="btn-delete" @click=${this._onDelete} title="删除文件">🗑</button>
      </div>
    `;
  }

  // ==================== 事件处理 ====================

  private _onAreaClick() {
    if (!this._input) {
      this._input = this.shadowRoot?.querySelector('input[type="file"]') ?? null;
    }
    this._input?.click();
  }

  private _onFileSelected(e: Event) {
    const input = e.target as HTMLInputElement;
    if (input.files?.length) {
      this._handleFile(input.files[0]);
    }
    // 重置 input 以允许重复选择同一文件
    input.value = '';
  }

  private _onDragOver(e: DragEvent) {
    e.preventDefault();
    this._dragOver = true;
  }

  private _onDragLeave() {
    this._dragOver = false;
  }

  private _onDrop(e: DragEvent) {
    e.preventDefault();
    this._dragOver = false;
    const files = e.dataTransfer?.files;
    if (files?.length) {
      this._handleFile(files[0]);
    }
  }

  private _onDelete() {
    this.file = null;
    store.clearFile();
    store.clearResult();
  }

  // ==================== 文件校验 ====================

  private _handleFile(rawFile: File) {
    const ext = '.' + rawFile.name.split('.').pop()!.toLowerCase();

    // 格式校验
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      store.showStatus(`不支持该文件格式：${ext}`, 'error');
      return;
    }

    // 大小校验
    const maxSize = getMaxSize(ext);
    if (rawFile.size > maxSize) {
      const label = getSizeLabel(ext);
      store.showStatus(
        `文件过大（${formatFileSize(rawFile.size)}），${ext} 格式文件不超过 ${label}`,
        'error'
      );
      return;
    }

    const fileInfo: FileInfo = {
      name: rawFile.name,
      size: rawFile.size,
      extension: ext,
      category: getFileCategory(ext),
    };

    this.file = fileInfo;
    store.setFile(fileInfo);

    // 保留原始 File 对象引用，用于后续上传
    (this.file as FileInfo & { _raw?: File })._raw = rawFile;
  }

  /** 获取当前文件的原始 File 对象（供 converter 使用） */
  getRawFile(): File | undefined {
    return (this.file as FileInfo & { _raw?: File })?._raw;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'app-upload': AppUpload;
  }
}