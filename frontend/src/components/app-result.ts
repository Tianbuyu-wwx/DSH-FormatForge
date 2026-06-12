// ============================================================
// <app-result> 转换结果展示组件
// ============================================================
// 标签页切换（转换内容 / 结构化数据 / 处理日志）、
// 平滑过渡动画、复制到剪贴板、折叠长内容

import { LitElement, html, css } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { store } from '../state/store.js';
import type { ConvertResult } from '../types/index.js';

const TABS = [
  { key: 'content', label: '转换内容' },
  { key: 'structured', label: '结构化数据' },
  { key: 'logs', label: '处理日志' },
] as const;

type TabKey = (typeof TABS)[number]['key'];

@customElement('app-result')
export class AppResult extends LitElement {
  @state() private _result: ConvertResult | null = null;
  @state() private _activeTab: TabKey = 'content';
  @state() private _slideDir: 'left' | 'right' = 'right';
  @state() private _copied = false;
  @state() private _logsExpanded = false;

  private _tabOrder: TabKey[] = ['content', 'structured', 'logs'];

  static styles = css`
    :host {
      display: none;
      margin-top: 8px;
    }

    :host(.visible) {
      display: block;
    }

    .result-wrapper {
      animation: fadeIn 0.5s ease;
    }

    /* 头部信息 */
    .result-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 10px;
      padding: 16px 20px;
      background: var(--color-surface);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border-radius: 12px 12px 0 0;
      border: 1px solid var(--color-border);
      border-bottom: none;
    }

    .result-file-info {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .result-file-icon {
      font-size: 1.8rem;
    }

    .result-file-name {
      font-weight: 600;
      font-size: 1rem;
    }

    .result-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    .meta-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 10px;
      border-radius: 10px;
      font-size: 0.78rem;
      font-weight: 500;
    }

    .badge-cache {
      background: rgba(255, 193, 7, 0.2);
      color: var(--color-warning);
    }

    .badge-confidence {
      background: rgba(56, 239, 125, 0.15);
      color: var(--color-success);
    }

    .badge-type {
      background: rgba(116, 185, 255, 0.2);
      color: var(--color-info);
    }

    .btn-copy {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 6px 14px;
      border-radius: 6px;
      border: 1px solid var(--color-border);
      background: rgba(255, 255, 255, 0.06);
      color: var(--color-text-secondary);
      font-size: 0.85rem;
      cursor: pointer;
      transition: all 0.2s ease;
      font-family: inherit;
    }

    .btn-copy:hover {
      background: rgba(255, 255, 255, 0.12);
      border-color: var(--color-primary);
    }

    .btn-copy.copied {
      background: rgba(56, 239, 125, 0.15);
      border-color: var(--color-success);
      color: var(--color-success);
    }

    /* 标签页 */
    .tab-bar {
      display: flex;
      border-bottom: 1px solid var(--color-border);
      background: var(--color-surface);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border-left: 1px solid var(--color-border);
      border-right: 1px solid var(--color-border);
    }

    .tab-btn {
      flex: 1;
      padding: 12px 16px;
      background: none;
      border: none;
      border-bottom: 2px solid transparent;
      color: var(--color-text-muted);
      font-size: 0.9rem;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s ease;
      font-family: inherit;
      position: relative;
    }

    .tab-btn:hover {
      color: var(--color-text-secondary);
    }

    .tab-btn.active {
      color: var(--color-primary);
      border-bottom-color: var(--color-primary);
    }

    .tab-btn:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }

    .tab-badge {
      display: inline-block;
      margin-left: 6px;
      background: rgba(255, 255, 255, 0.1);
      padding: 0 6px;
      border-radius: 8px;
      font-size: 0.72rem;
      vertical-align: 1px;
    }

    /* 内容区 */
    .tab-content {
      position: relative;
      overflow: hidden;
      min-height: 200px;
      max-height: 600px;
      background: rgba(0, 0, 0, 0.3);
      border: 1px solid var(--color-border);
      border-top: none;
      border-radius: 0 0 12px 12px;
    }

    .tab-panel {
      padding: 20px;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
      font-size: 0.88rem;
      line-height: 1.6;
      color: var(--color-text-secondary);
      overflow-y: auto;
      max-height: 600px;
      position: absolute;
      inset: 0;
      transition: transform 0.3s ease, opacity 0.3s ease;
    }

    .tab-panel.enter-right {
      transform: translateX(30px);
      opacity: 0;
    }

    .tab-panel.enter-left {
      transform: translateX(-30px);
      opacity: 0;
    }

    .tab-panel.active {
      transform: translateX(0);
      opacity: 1;
      position: relative;
    }

    .tab-panel:not(.active) {
      pointer-events: none;
    }

    /* 空状态 */
    .empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 40px;
      color: var(--color-text-muted);
      text-align: center;
      font-family: var(--font-sans);
    }

    .empty-state .empty-icon {
      font-size: 2.5rem;
      margin-bottom: 12px;
      opacity: 0.5;
    }

    /* 日志列表 */
    .log-list {
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-family: var(--font-sans);
    }

    .log-entry {
      display: flex;
      gap: 10px;
      padding: 6px 10px;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.04);
      font-size: 0.85rem;
    }

    .log-level {
      flex-shrink: 0;
      font-weight: 600;
      font-size: 0.75rem;
      width: 50px;
      text-align: center;
      padding: 1px 6px;
      border-radius: 4px;
    }

    .log-level.info {
      background: rgba(116, 185, 255, 0.2);
      color: var(--color-info);
    }

    .log-level.warning {
      background: rgba(255, 193, 7, 0.2);
      color: var(--color-warning);
    }

    .log-level.error {
      background: rgba(255, 107, 107, 0.2);
      color: var(--color-error);
    }

    .log-step {
      flex-shrink: 0;
      color: var(--color-text-muted);
      font-size: 0.82rem;
    }

    .log-msg {
      color: var(--color-text-secondary);
    }

    /* 折叠按钮 */
    .collapse-toggle {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      padding: 8px;
      background: rgba(255, 255, 255, 0.04);
      border: none;
      border-top: 1px solid var(--color-border);
      color: var(--color-text-muted);
      font-size: 0.82rem;
      cursor: pointer;
      font-family: inherit;
      transition: background 0.2s;
    }

    .collapse-toggle:hover {
      background: rgba(255, 255, 255, 0.08);
    }

    .collapse-arrow {
      display: inline-block;
      margin-left: 4px;
      transition: transform 0.3s ease;
    }

    .collapse-arrow.expanded {
      transform: rotate(180deg);
    }
  `;

  private _unsub?: () => void;

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe((s) => {
      if (s.result) {
        this._result = s.result;
        this._activeTab = 'content';
        this._slideDir = 'right';
        this.classList.add('visible');
      } else {
        this._result = null;
        this.classList.remove('visible');
      }
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  render() {
    if (!this._result) return html``;

    const r = this._result;
    const hasStructured = !!r.structuredData && Object.keys(r.structuredData).length > 0;
    const hasLogs = !!r.processingLogs && r.processingLogs.length > 0;

    return html`
      <div class="result-wrapper">
        <!-- 头部 -->
        <div class="result-header">
          <div class="result-file-info">
            <span class="result-file-icon">📄</span>
            <span class="result-file-name">${r.fileName}</span>
          </div>
          <div class="result-meta">
            ${r.conversionDecision?.fromCache
              ? html`<span class="meta-badge badge-cache">⚡ 缓存</span>`
              : ''}
            <span class="meta-badge badge-confidence">
              置信度 ${(r.confidence * 100).toFixed(0)}%
            </span>
            <span class="meta-badge badge-type">${r.fileType}</span>
          </div>
          <button class="btn-copy ${this._copied ? 'copied' : ''}" @click=${this._onCopy}>
            ${this._copied ? '已复制' : '复制'}
          </button>
        </div>

        <!-- 标签页 -->
        <div class="tab-bar">
          ${TABS.map((tab, i) => html`
            <button
              class="tab-btn ${this._activeTab === tab.key ? 'active' : ''}"
              ?disabled=${(tab.key === 'structured' && !hasStructured) || (tab.key === 'logs' && !hasLogs)}
              @click=${() => this._switchTab(tab.key, i)}
            >
              ${tab.label}
              ${tab.key === 'logs' && hasLogs
                ? html`<span class="tab-badge">${r.processingLogs!.length}</span>`
                : ''}
            </button>
          `)}
        </div>

        <!-- 内容区 -->
        <div class="tab-content">
          ${this._renderContentPanel(r)}
          ${this._renderStructuredPanel(r, hasStructured)}
          ${this._renderLogsPanel(r, hasLogs)}
        </div>
      </div>
    `;
  }

  private _renderContentPanel(r: ConvertResult) {
    const active = this._activeTab === 'content';
    const dir = this._slideDir === 'right' ? 'enter-right' : 'enter-left';
    return html`
      <div class="tab-panel ${active ? 'active' : dir}">
        ${r.convertedContent || html`
          <div class="empty-state">
            <div class="empty-icon">📭</div>
            <span>暂无转换内容</span>
          </div>
        `}
      </div>
    `;
  }

  private _renderStructuredPanel(r: ConvertResult, has: boolean) {
    const active = this._activeTab === 'structured';
    const dir = this._slideDir === 'right' ? 'enter-right' : 'enter-left';
    const json = has ? JSON.stringify(r.structuredData, null, 2) : '';

    return html`
      <div class="tab-panel ${active ? 'active' : dir}">
        ${has ? json : html`
          <div class="empty-state">
            <div class="empty-icon">🧩</div>
            <span>无结构化数据</span>
          </div>
        `}
      </div>
    `;
  }

  private _renderLogsPanel(r: ConvertResult, has: boolean) {
    const active = this._activeTab === 'logs';
    const dir = this._slideDir === 'right' ? 'enter-right' : 'enter-left';
    if (!has) {
      return html`
        <div class="tab-panel ${active ? 'active' : dir}">
          <div class="empty-state">
            <div class="empty-icon">📋</div>
            <span>无处理日志</span>
          </div>
        </div>
      `;
    }
    const logs = r.processingLogs!;
    const limit = this._logsExpanded ? logs.length : 10;
    return html`
      <div class="tab-panel ${active ? 'active' : dir}">
        <div class="log-list">
          ${logs.slice(0, limit).map(l => html`
            <div class="log-entry">
              <span class="log-level ${l.level}">${l.level.toUpperCase()}</span>
              <span class="log-step">${l.step}</span>
              <span class="log-msg">${l.message}</span>
            </div>
          `)}
        </div>
        ${logs.length > 10 ? html`
          <button class="collapse-toggle" @click=${this._toggleLogs}>
            ${this._logsExpanded ? '收起' : `展开剩余 ${logs.length - 10} 条日志`}
            <span class="collapse-arrow ${this._logsExpanded ? 'expanded' : ''}">▼</span>
          </button>
        ` : ''}
      </div>
    `;
  }

  // ==================== 交互 ====================

  private _switchTab(key: TabKey, idx: number) {
    const oldIdx = this._tabOrder.indexOf(this._activeTab);
    this._slideDir = idx > oldIdx ? 'right' : 'left';
    this._activeTab = key;
  }

  private async _onCopy() {
    if (!this._result) return;
    const text = this._result.convertedContent || '';
    try {
      await navigator.clipboard.writeText(text);
      this._copied = true;
      setTimeout(() => { this._copied = false; }, 2000);
    } catch {
      store.showStatus('复制失败，请手动复制', 'error');
    }
  }

  private _toggleLogs() {
    this._logsExpanded = !this._logsExpanded;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'app-result': AppResult;
  }
}