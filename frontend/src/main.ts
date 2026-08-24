// ============================================================
// AI 数据转换器 — v4.0 Sacred Grove
// ============================================================
// 布局：左侧边栏（安全区）+ 右侧角色留白

import '../styles/main.css';
import './components/app-background';
import './components/app-upload';
import './components/app-options';
import './components/app-convert-btn';
import './components/app-status';
import './components/app-result';
import './components/app-history';
import './components/app-compare.js';
import './components/ui/icon.js';

import { LitElement, html, css } from 'lit';
import { customElement, query, state } from 'lit/decorators.js';
import { store } from './state/store.js';
import { getLang, toggleLang } from './i18n/index.js';
import {
  uploadAndConvert,
  convertUrl,
  convertText,
  batchConvert,
  ApiError,
  configureApiKey,
  isApiKeyConfigured,
} from './utils/api.js';
import { AppUpload } from './components/app-upload.js';

@customElement('app-root')
export class AppRoot extends LitElement {
  @query('app-upload') private _upload!: AppUpload;
  @state() private _sidebarOpen = false;
  @state() private _apiKeyEditorOpen = false;
  @state() private _apiKeyDraft = '';

  private _onConvertBound = this._onConvert.bind(this);
  private _onConvertUrlBound = this._onConvertUrl.bind(this);
  private _onConvertTextBound = this._onConvertText.bind(this);

  static styles = css`
    :host { display: block; position: fixed; inset: 0; }

    /* ===== 左侧边栏 ===== */
    .sidebar {
      position: fixed;
      top: 0; left: 0; bottom: 0;
      width: 420px;
      max-width: 45vw;
      z-index: 1;
      display: flex;
      flex-direction: column;
      background: rgba(15, 46, 46, 0.38);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border-right: 1px solid rgba(95, 179, 195, 0.08);
      box-shadow: 4px 0 40px rgba(0,0,0,0.35);
      animation: sidebarIn 0.9s var(--ease) both;
      overflow: hidden;
    }

    .sidebar::before {
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 1px;
      background: linear-gradient(90deg, rgba(255,248,231,0.2), transparent 80%);
    }

    .sidebar-scroll {
      flex: 1;
      overflow-y: auto;
      padding: 28px 28px 20px;
    }

    .sidebar-footer {
      padding: 10px 28px;
      border-top: 1px solid rgba(95, 179, 195, 0.06);
      display: flex;
      justify-content: space-between;
      font-size: var(--text-xs);
      color: var(--text-muted);
      letter-spacing: 0.03em;
    }

    /* ===== Logo ===== */
    .logo {
      font-family: var(--font-display);
      font-size: var(--text-lg);
      font-style: italic;
      font-weight: 400;
      color: var(--light-warm);
      letter-spacing: -0.01em;
      text-shadow: 0 2px 12px rgba(0,0,0,0.35);
      margin-bottom: 20px;
    }

    /* ===== 顶栏操作 ===== */
    .panel-header {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      margin-bottom: 20px;
    }

    .top-actions {
      display: flex;
      gap: 16px;
    }

    .top-actions button {
      font-family: var(--font-body);
      font-size: var(--text-xs);
      font-weight: 400;
      color: var(--text-secondary);
      background: none;
      border: none;
      cursor: pointer;
      letter-spacing: 0.04em;
      transition: color var(--duration) var(--ease);
      padding: 0;
    }

    .top-actions button:hover { color: var(--text); }

    .api-key-editor {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: var(--space-2);
      align-items: center;
      margin: -8px 0 16px;
      padding: var(--space-2);
      background: rgba(0,0,0,0.18);
      border: 1px solid var(--border);
      border-radius: 8px;
    }
    .api-key-editor input {
      min-width: 0;
      padding: 6px 8px;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      color: var(--text);
      background: rgba(0,0,0,0.2);
      border: 1px solid var(--border);
      border-radius: 6px;
      outline: none;
    }
    .api-key-editor input:focus { border-color: var(--border-focus); }
    .api-key-editor button {
      padding: 5px 8px;
      font-family: var(--font-body);
      font-size: var(--text-xs);
      color: var(--text-secondary);
      background: transparent;
      border: 1px solid var(--border);
      border-radius: 6px;
      cursor: pointer;
    }
    .api-key-editor button:hover { color: var(--text); border-color: var(--border-focus); }

    /* ===== 右侧角色区域 ===== */
    .character-area {
      position: fixed;
      top: 0; right: 0; bottom: 0;
      left: 420px;
      pointer-events: none;
      z-index: 0;
    }

    @keyframes sidebarIn {
      from { opacity: 0; transform: translateX(-30px); }
      to   { opacity: 1; transform: translateX(0); }
    }

    /* ===== 响应式 ===== */

    /* 平板横屏 / 小桌面：收窄边栏 */
    @media (max-width: 1023px) {
      .sidebar { width: 340px; }
      .sidebar-scroll { padding: 20px 20px 16px; }
      .character-area { left: 340px; }
      .logo { font-size: var(--text-base); margin-bottom: 14px; }
    }

    /* 平板竖屏：边栏变为可滑出的覆盖面板 */
    @media (max-width: 767px) {
      .sidebar {
        width: 85vw;
        max-width: 360px;
        transform: translateX(-100%);
        transition: transform 0.35s var(--ease);
      }
      .sidebar.open { transform: translateX(0); }
      .sidebar-scroll { padding: 16px 16px 12px; }
      .character-area { display: none; }
      .logo { font-size: var(--text-base); margin-bottom: 12px; }
    }

    /* 手机：全屏边栏 */
    @media (max-width: 479px) {
      .sidebar { width: 100vw; max-width: none; }
      .sidebar-scroll { padding: 12px 12px 8px; }
    }

    /* 汉堡菜单按钮（仅移动端显示） */
    .menu-toggle {
      display: none;
      position: fixed;
      top: 12px; left: 12px;
      z-index: 10;
      width: 40px; height: 40px;
      align-items: center;
      justify-content: center;
      background: rgba(15, 46, 46, 0.6);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(95, 179, 195, 0.12);
      border-radius: 10px;
      color: var(--text);
      cursor: pointer;
      transition: all var(--duration) var(--ease);
    }
    .menu-toggle:hover {
      background: rgba(15, 46, 46, 0.8);
      border-color: rgba(95, 179, 195, 0.25);
    }
    @media (max-width: 767px) {
      .menu-toggle { display: flex; }
    }

    /* 遮罩层（移动端边栏打开时） */
    .overlay {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.5);
      z-index: 0;
      opacity: 0;
      transition: opacity 0.35s var(--ease);
    }
    .overlay.show {
      display: block;
      opacity: 1;
    }
    @media (min-width: 768px) {
      .overlay { display: none !important; }
    }
  `;

  private _unsubStore?: () => void;

  connectedCallback() {
    super.connectedCallback();
    this.addEventListener('convert', this._onConvertBound);
    this.addEventListener('convert-url', this._onConvertUrlBound);
    this.addEventListener('convert-text', this._onConvertTextBound);
    this._unsubStore = store.subscribe(() => this.requestUpdate());
    // v2.1.0: 监听语言切换事件，触发全组件 re-render
    this._onLangChange = () => this.requestUpdate();
    window.addEventListener('langchange', this._onLangChange);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.removeEventListener('convert', this._onConvertBound);
    this.removeEventListener('convert-url', this._onConvertUrlBound);
    this.removeEventListener('convert-text', this._onConvertTextBound);
    this._unsubStore?.();
    // v2.1.0: 清理 langchange 监听
    if (this._onLangChange) {
      window.removeEventListener('langchange', this._onLangChange);
    }
  }

  private _onLangChange?: () => void;

  render() {
    return html`
      <app-background></app-background>
      <app-status></app-status>
      <app-history></app-history>
      <app-compare></app-compare>

      <button class="menu-toggle" @click=${this._toggleSidebar} aria-label="菜单">
        <ui-icon name="file-text" size="20"></ui-icon>
      </button>

      <div class="overlay ${this._sidebarOpen ? 'show' : ''}" @click=${this._closeSidebar}></div>

      <div class="sidebar ${this._sidebarOpen ? 'open' : ''}">
        <div class="sidebar-scroll">
          <div class="panel-header">
            <span class="logo">AI 数据转换器</span>
            <div class="top-actions">
              <button @click=${this._toggleHistory}>历史</button>
              <button @click=${this._toggleApiKeyEditor}>密钥${isApiKeyConfigured() ? ' ✓' : ''}</button>
              <button @click=${() => toggleLang()}>${getLang() === 'zh' ? 'EN' : '中'}</button>
            </div>
          </div>

          ${this._apiKeyEditorOpen ? html`
            <div class="api-key-editor">
              <input
                type="password"
                autocomplete="off"
                spellcheck="false"
                aria-label="API Key"
                placeholder=${isApiKeyConfigured() ? '输入新密钥以替换' : '输入 API Key'}
                .value=${this._apiKeyDraft}
                @input=${(e: InputEvent) => this._apiKeyDraft = (e.target as HTMLInputElement).value}
                @keydown=${this._onApiKeyKeydown}
              >
              <button @click=${this._saveApiKey}>保存</button>
              <button @click=${this._clearApiKey}>清除</button>
            </div>
          ` : ''}

          <app-upload></app-upload>
          <app-options></app-options>
          <app-convert-btn></app-convert-btn>
          <app-result></app-result>
        </div>

        <div class="sidebar-footer">
          <span>${this._statusText()}</span>
          <span>v4.0 Sacred Grove</span>
        </div>
      </div>

      <div class="character-area"></div>
    `;
  }

  private _statusText(): string {
    const { files, loading } = store.state;
    if (loading) return '转换中...';
    if (files.length) return `${files.length} 个文件 · 就绪`;
    return '就绪 · 0 文件';
  }

  private _toggleHistory() {
    store.toggleHistory();
  }

  private _toggleApiKeyEditor() {
    this._apiKeyDraft = '';
    this._apiKeyEditorOpen = !this._apiKeyEditorOpen;
  }

  private _saveApiKey() {
    if (!this._apiKeyDraft.trim()) {
      store.showStatus('请输入 API Key；如需移除请点击“清除”', 'error');
      return;
    }

    try {
      configureApiKey(this._apiKeyDraft);
      this._apiKeyDraft = '';
      this._apiKeyEditorOpen = false;
      store.showStatus('API Key 已为当前标签页配置', 'success');
    } catch (err) {
      store.showStatus(err instanceof Error ? err.message : 'API Key 配置失败', 'error');
    }
  }

  private _clearApiKey() {
    configureApiKey('');
    this._apiKeyDraft = '';
    this._apiKeyEditorOpen = false;
    store.showStatus('API Key 已清除', 'success');
  }

  private _onApiKeyKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') this._saveApiKey();
    if (e.key === 'Escape') this._toggleApiKeyEditor();
  }

  private _toggleSidebar() {
    this._sidebarOpen = !this._sidebarOpen;
  }

  private _closeSidebar() {
    this._sidebarOpen = false;
  }

  /* ===== 转换逻辑 ===== */
  private async _onConvert() {
    const { inputMode, conversionType, outputFormat, customPrompt } = store.state;

    if (inputMode === 'url') {
      const url = store.state.urlInput;
      if (!url) { store.showStatus('请输入 URL', 'error'); return; }
      await this._doConvertUrl(url, { conversionType, outputFormat, customPrompt });
      return;
    }

    if (inputMode === 'text') {
      const text = store.state.textInput;
      if (!text) { store.showStatus('请输入文本内容', 'error'); return; }
      await this._doConvertText(text, { conversionType, outputFormat, customPrompt });
      return;
    }

    const rawFiles = this._upload?.getRawFiles();
    const rawFile = this._upload?.getRawFile();

    if (rawFiles && rawFiles.length > 1) {
      try {
        store.clearResult(); store.clearResults(); store.setLoading(true);
        store.setProgress('upload', 0);
        const results = await batchConvert(rawFiles, { conversionType, outputFormat },
          (current, total, fileName) => {
            store.setProgress('convert', Math.round((current / total) * 100));
            store.showStatus(`正在转换 ${current}/${total}: ${fileName}`, 'info');
          });
        store.setResults(results); store.setResult(results[0] || null);
        store.showStatus(`批量转换完成！共 ${results.length} 个文件`, 'success');
      } catch (err) {
        store.showStatus(err instanceof ApiError ? err.message : '批量转换失败', 'error');
      } finally { store.setLoading(false); store.setProgress('done', 100); }
      return;
    }

    if (!rawFile) { store.showStatus('请先选择文件', 'error'); return; }

    try {
      store.clearResult(); store.setLoading(true); store.setProgress('upload', 0);
      const result = await uploadAndConvert(rawFile, { conversionType, outputFormat, customPrompt },
        (phase, percent) => store.setProgress(phase as 'upload' | 'parse' | 'convert' | 'done', percent));
      store.setResult(result); store.showStatus('转换完成！', 'success');
    } catch (err) {
      store.showStatus(err instanceof ApiError ? err.message : '网络错误', 'error');
    } finally { store.setLoading(false); store.setProgress('done', 100); }
  }

  private async _onConvertUrl(e: Event) {
    const detail = (e as CustomEvent).detail as { url: string };
    if (!detail?.url) return;
    const { conversionType, outputFormat, customPrompt } = store.state;
    await this._doConvertUrl(detail.url, { conversionType, outputFormat, customPrompt });
  }

  private async _doConvertUrl(url: string, opts: any) {
    try {
      store.clearResult(); store.setLoading(true); store.setProgress('upload', 0);
      const result = await convertUrl(url, opts, (phase, percent) =>
        store.setProgress(phase as 'upload' | 'parse' | 'convert' | 'done', percent));
      store.setResult(result); store.showStatus('转换完成！', 'success');
    } catch (err) {
      store.showStatus(err instanceof ApiError ? err.message : 'URL 转换失败', 'error');
    } finally { store.setLoading(false); store.setProgress('done', 100); }
  }

  private async _onConvertText(e: Event) {
    const detail = (e as CustomEvent).detail as { text: string };
    if (!detail?.text) return;
    const { conversionType, outputFormat, customPrompt } = store.state;
    await this._doConvertText(detail.text, { conversionType, outputFormat, customPrompt });
  }

  private async _doConvertText(text: string, opts: any) {
    try {
      store.clearResult(); store.setLoading(true); store.setProgress('upload', 0);
      const result = await convertText(text, opts, (phase, percent) =>
        store.setProgress(phase as 'upload' | 'parse' | 'convert' | 'done', percent));
      store.setResult(result); store.showStatus('转换完成！', 'success');
    } catch (err) {
      store.showStatus(err instanceof ApiError ? err.message : '文本转换失败', 'error');
    } finally { store.setLoading(false); store.setProgress('done', 100); }
  }
}

window.addEventListener('error', (e) => console.error('[App Error]', e.error));
window.addEventListener('unhandledrejection', (e) => console.error('[Unhandled Promise]', e.reason));
