// ============================================================
// <app-upload> v4.0 — 森林风格三态输入区
// ============================================================

import { LitElement, html, css } from 'lit';
import { customElement, state, query } from 'lit/decorators.js';
import { store } from '../state/store.js';
import { t } from '../i18n/index.js';
import type { InputMode, FileInfo } from '../types/index.js';
import { getFileCategory, getFileIcon, formatFileSize, getMaxSize } from '../utils/format.js';
import '../components/ui/icon.js';

@customElement('app-upload')
export class AppUpload extends LitElement {
  @query('#fileInput') private _fileInput!: HTMLInputElement;
  @state() private _files: File[] = [];
  @state() private _dragOver = false;

  private _unsub?: () => void;

  static styles = css`
    :host { display: block; }

    /* ===== 模式切换 ===== */
    .mode-bar {
      display: flex;
      gap: var(--space-1);
      margin-bottom: var(--space-4);
    }
    .mode-btn {
      padding: 6px 12px;
      font-family: var(--font-body);
      font-size: var(--text-xs);
      font-weight: 400;
      color: var(--text-muted);
      background: transparent;
      border: 1px solid transparent;
      border-radius: 6px;
      cursor: pointer;
      transition: all var(--duration) var(--ease);
      letter-spacing: 0.02em;
    }
    .mode-btn:hover { color: var(--text-secondary); }
    .mode-btn.active {
      color: var(--text);
      background: var(--bg-hover);
      border-color: var(--border);
    }

    /* ===== 文件上传区 ===== */
    .dropzone {
      width: 100%;
      border: 1px dashed var(--border);
      border-radius: 12px;
      padding: var(--space-6) var(--space-4);
      text-align: center;
      cursor: pointer;
      transition: all 0.4s var(--ease);
      background: rgba(0,0,0,0.12);
      margin-bottom: var(--space-3);
      box-sizing: border-box;
    }
    .dropzone:hover, .dropzone.drag-over {
      border-color: var(--border-accent);
      background: rgba(253, 230, 138, 0.03);
    }
    .dropzone-icon {
      color: var(--text-secondary);
      margin-bottom: var(--space-2);
      transition: color 0.4s var(--ease);
    }
    .dropzone:hover .dropzone-icon, .dropzone.drag-over .dropzone-icon {
      color: var(--particle-gold);
    }
    .dropzone-text {
      font-size: var(--text-base);
      color: var(--text);
      margin-bottom: var(--space-1);
    }
    .dropzone-hint {
      font-size: var(--text-xs);
      color: var(--text-muted);
    }

    /* ===== 文件卡片 ===== */
    .file-card {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      padding: var(--space-2) var(--space-3);
      background: rgba(0,0,0,0.15);
      border: 1px solid var(--border);
      border-radius: 8px;
      margin-top: var(--space-2);
      animation: fadeIn 0.2s var(--ease);
    }
    .file-info { flex: 1; min-width: 0; }
    .file-name { font-size: var(--text-sm); color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .file-meta { font-size: var(--text-xs); color: var(--text-muted); }
    .file-remove { color: var(--text-muted); cursor: pointer; transition: color var(--duration); background: none; border: none; padding: 0; }
    .file-remove:hover { color: var(--error); }

    /* ===== URL / 文本 ===== */
    .url-input {
      width: 100%;
      padding: 10px 12px;
      font-family: var(--font-body);
      font-size: var(--text-sm);
      color: var(--text);
      background: var(--bg-input);
      border: 1px solid var(--border);
      border-radius: 6px;
      outline: none;
      transition: border-color var(--duration) var(--ease);
      margin-bottom: var(--space-3);
    }
    .url-input:focus { border-color: var(--border-focus); }
    .url-input::placeholder { color: var(--text-muted); }

    .text-input {
      width: 100%;
      min-height: 180px;
      padding: 10px 12px;
      font-family: var(--font-body);
      font-size: var(--text-sm);
      line-height: 1.6;
      color: var(--text);
      background: var(--bg-input);
      border: 1px solid var(--border);
      border-radius: 6px;
      resize: vertical;
      outline: none;
      transition: border-color var(--duration) var(--ease);
      margin-bottom: var(--space-3);
    }
    .text-input:focus { border-color: var(--border-focus); }
    .text-input::placeholder { color: var(--text-muted); }

    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }

    /* ===== 响应式 ===== */
    @media (max-width: 479px) {
      .mode-bar { flex-wrap: wrap; gap: 4px; }
      .mode-btn { padding: 5px 10px; font-size: 11px; }
      .dropzone { padding: 20px 12px; }
      .dropzone-text { font-size: var(--text-sm); }
      .file-card { padding: 6px 10px; gap: 8px; }
      .file-name { font-size: var(--text-xs); }
    }
  `;

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe(() => this.requestUpdate());
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  getRawFiles(): File[] { return this._files; }
  getRawFile(): File | null { return this._files[0] || null; }

  render() {
    const { inputMode } = store.state;
    return html`
      <div class="mode-bar">
        ${this._modeBtn('file', '文件上传')}
        ${this._modeBtn('url', 'URL')}
        ${this._modeBtn('text', '文本')}
      </div>
      ${inputMode === 'file' ? this._renderFile() : ''}
      ${inputMode === 'url' ? this._renderUrl() : ''}
      ${inputMode === 'text' ? this._renderText() : ''}
    `;
  }

  private _modeBtn(mode: InputMode, label: string) {
    const active = store.state.inputMode === mode;
    return html`<button class="mode-btn ${active ? 'active' : ''}" @click=${() => store.setInputMode(mode)}>${label}</button>`;
  }

  private _renderFile() {
    return html`
      <div class="dropzone ${this._dragOver ? 'drag-over' : ''}"
        @click=${() => this._fileInput?.click()}
        @dragover=${this._onDragOver} @dragleave=${this._onDragLeave}
        @drop=${this._onDrop}>
        <div class="dropzone-icon"><ui-icon name="file" size="40"></ui-icon></div>
        <div class="dropzone-text">${t('upload.dropzone')}</div>
        <div class="dropzone-hint">${t('upload.supported')}</div>
      </div>
      <input id="fileInput" type="file" style="display:none" @change=${this._onFileSelect} multiple>
      ${this._files.map((f, i) => html`
        <div class="file-card">
          <ui-icon name=${getFileIcon(f.name)} size="18"></ui-icon>
          <div class="file-info">
            <div class="file-name">${f.name}</div>
            <div class="file-meta">${formatFileSize(f.size)} · ${getFileCategory(f.name)}</div>
          </div>
          <button class="file-remove" @click=${(e: Event) => { e.stopPropagation(); this._removeFile(i); }}>
            <ui-icon name="close" size="14"></ui-icon>
          </button>
        </div>
      `)}
    `;
  }

  private _renderUrl() {
    return html`
      <input class="url-input" type="url" .value=${store.state.urlInput}
        placeholder="https://example.com/file.pdf"
        @input=${(e: InputEvent) => store.setUrlInput((e.target as HTMLInputElement).value)}>
    `;
  }

  private _renderText() {
    return html`
      <textarea class="text-input" .value=${store.state.textInput}
        placeholder="在此粘贴或输入文本内容..."
        @input=${(e: InputEvent) => store.setTextInput((e.target as HTMLTextAreaElement).value)}></textarea>
    `;
  }

  private _onDragOver(e: DragEvent) { e.preventDefault(); this._dragOver = true; }
  private _onDragLeave() { this._dragOver = false; }

  private _onDrop(e: DragEvent) {
    e.preventDefault();
    this._dragOver = false;
    const dropped = Array.from(e.dataTransfer?.files || []);
    if (dropped.length) { this._addFiles(dropped); }
  }

  private _onFileSelect(e: Event) {
    const selected = Array.from((e.target as HTMLInputElement).files || []);
    if (selected.length) { this._addFiles(selected); }
  }

  private _addFiles(files: File[]) {
    const errs: string[] = [];
    const valid: File[] = [];
    for (const f of files) {
      const ext = '.' + f.name.split('.').pop();
      const max = getMaxSize(ext);
      if (f.size > max) {
        errs.push(`${f.name}: 超过大小限制 ${formatFileSize(max)}`);
        continue;
      }
      valid.push(f);
    }
    if (errs.length) store.showStatus(errs.join('；'), 'error');
    this._files = valid;
    if (valid.length) {
      const infos: FileInfo[] = valid.map(f => ({
        name: f.name, size: f.size, extension: '.' + f.name.split('.').pop() || '', type: f.type, category: getFileCategory(f.name)
      }));
      if (infos.length === 1) store.setFile(infos[0]);
      else store.setBatchFiles(infos);
    }
  }

  private _removeFile(idx: number) {
    this._files = this._files.filter((_, i) => i !== idx);
    if (!this._files.length) { store.clearFiles(); store.clearResult(); }
  }
}

declare global { interface HTMLElementTagNameMap { 'app-upload': AppUpload; } }
