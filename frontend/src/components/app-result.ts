// ============================================================
// <app-result> v4.0 — 边栏内结果面板
// ============================================================

import { LitElement, html, css } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { store } from '../state/store.js';
import type { ConvertResult } from '../types/index.js';
import '../components/ui/icon.js';

@customElement('app-result')
export class AppResult extends LitElement {
  @state() private _result: ConvertResult | null = null;
  @state() private _tab: 'content' | 'structured' | 'logs' = 'content';

  static styles = css`
    :host { display: block; margin-top: var(--space-4); }

    .result-wrap {
      padding-top: var(--space-3);
      border-top: 1px solid var(--border);
      animation: fadeIn 0.5s var(--ease) both;
    }

    .tabs {
      display: flex;
      gap: var(--space-1);
      margin-bottom: var(--space-3);
    }
    .tab {
      padding: 4px 10px;
      font-family: var(--font-body);
      font-size: var(--text-xs);
      font-weight: 400;
      color: var(--text-muted);
      background: none;
      border: none;
      border-bottom: 2px solid transparent;
      cursor: pointer;
      margin-bottom: -1px;
      transition: all var(--duration) var(--ease);
      letter-spacing: 0.03em;
    }
    .tab:hover { color: var(--text-secondary); }
    .tab.active {
      color: var(--light-warm);
      border-bottom-color: var(--particle-gold);
      text-shadow: 0 0 8px rgba(253,230,138,0.25);
    }

    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-1);
      margin-bottom: var(--space-3);
      padding-bottom: var(--space-2);
      border-bottom: 1px solid var(--border);
    }
    .meta-tag {
      font-size: var(--text-xs);
      color: var(--text-muted);
      padding: 1px 6px;
      border: 1px solid var(--border);
      border-radius: 4px;
    }
    .meta-tag.accent {
      color: var(--particle-gold);
      border-color: var(--border-accent);
    }

    .content-box {
      background: rgba(0,0,0,0.2);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: var(--space-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      line-height: 1.7;
      color: rgba(224,242,241,0.7);
      white-space: pre-wrap;
      word-break: break-word;
      overflow: auto;
      max-height: 140px;
    }

    .actions {
      display: flex;
      gap: var(--space-2);
      margin-top: var(--space-3);
    }
    .btn-icon {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px 10px;
      font-size: var(--text-xs);
      color: var(--text-secondary);
      background: rgba(0,0,0,0.15);
      border: 1px solid var(--border);
      border-radius: 6px;
      cursor: pointer;
      transition: all var(--duration);
    }
    .btn-icon:hover {
      color: var(--text);
      border-color: var(--border-focus);
    }

    .log-item {
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      color: var(--text-muted);
      padding: 2px 0;
      border-bottom: 1px solid var(--border);
    }
    .log-item:last-child { border-bottom: none; }

    .empty {
      text-align: center;
      padding: var(--space-5);
      color: var(--text-muted);
      font-size: var(--text-sm);
    }

    .empty-state {
      text-align: center;
      padding: var(--space-5) var(--space-3);
      border: 1px dashed var(--border);
      border-radius: 10px;
      animation: fadeIn 0.4s var(--ease);
    }
    .empty-icon {
      color: var(--text-muted);
      margin-bottom: var(--space-2);
    }
    .empty-title {
      font-size: var(--text-sm);
      color: var(--text-secondary);
      margin-bottom: var(--space-1);
    }
    .empty-desc {
      font-size: var(--text-xs);
      color: var(--text-muted);
      line-height: 1.5;
    }

    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }

    /* ===== 响应式 ===== */
    @media (max-width: 479px) {
      .content-box { padding: 10px; font-size: 11px; max-height: 200px; }
      .meta { gap: 4px; }
      .meta-tag { font-size: 10px; padding: 1px 4px; }
      .actions { gap: 6px; }
      .btn-icon { padding: 3px 8px; font-size: 11px; }
      .tab { padding: 3px 8px; font-size: 11px; }
      .empty-state { padding: 16px 12px; }
    }
  `;

  private _unsub?: () => void;

  connectedCallback() {
    super.connectedCallback();
    const r = store.state.result;
    if (r) { this._result = r; this._tab = 'content'; }
    this._unsub = store.subscribe((s) => {
      if (s.result) {
        this._result = s.result;
        this._tab = 'content';
      } else {
        this._result = null;
      }
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  render() {
    const r = this._result;

    return html`
      <div class="result-wrap">
        <div class="tabs">
          <button class="tab ${this._tab === 'content' ? 'active' : ''}" @click=${() => this._tab = 'content'}>内容</button>
          <button class="tab ${this._tab === 'structured' ? 'active' : ''}" @click=${() => this._tab = 'structured'}>结构化</button>
          <button class="tab ${this._tab === 'logs' ? 'active' : ''}" @click=${() => this._tab = 'logs'}>日志</button>
        </div>
        ${r
          ? html`${this._tab === 'content' ? this._renderContent(r) : ''}${this._tab === 'structured' ? this._renderStructured(r) : ''}${this._tab === 'logs' ? this._renderLogs(r) : ''}`
          : this._renderEmpty()
        }
      </div>
    `;
  }

  private _renderEmpty() {
    return html`
      <div class="empty-state">
        <div class="empty-icon"><ui-icon name="file-text" size="24"></ui-icon></div>
        <div class="empty-title">等待转换</div>
        <div class="empty-desc">上传文件或输入内容后，转换结果将显示在此处</div>
      </div>
    `;
  }

  private _renderContent(r: ConvertResult) {
    return html`
      <div class="meta">
        ${r.conversionDecision ? html`
          <span class="meta-tag">策略: ${r.conversionDecision.recommendedStrategy}</span>
          <span class="meta-tag accent">置信度: ${(r.conversionDecision.confidence * 100).toFixed(0)}%</span>
          ${r.conversionDecision.fromCache ? html`<span class="meta-tag accent">缓存</span>` : ''}
        ` : ''}
        <span class="meta-tag">格式: ${r.outputFormat || r.fileType}</span>
      </div>
      <div class="content-box">${r.convertedContent || '无内容'}</div>
      <div class="actions">
        <button class="btn-icon" @click=${() => this._copy(r.convertedContent)}><ui-icon name="copy" size="12"></ui-icon> 复制</button>
        <button class="btn-icon" @click=${() => this._download(r)}><ui-icon name="file" size="12"></ui-icon> 下载</button>
      </div>
    `;
  }

  private _renderStructured(r: ConvertResult) {
    const json = r.structuredData ? JSON.stringify(r.structuredData, null, 2) : '';
    if (!json) return html`<div class="empty">无结构化数据</div>`;
    return html`
      <div class="content-box">${json}</div>
      <div class="actions">
        <button class="btn-icon" @click=${() => this._copy(json)}><ui-icon name="copy" size="12"></ui-icon> 复制 JSON</button>
      </div>
    `;
  }

  private _renderLogs(r: ConvertResult) {
    const logs = r.processingLogs || [];
    if (!logs.length) return html`<div class="empty">无处理日志</div>`;
    return html`
      <div class="content-box">
        ${logs.map(l => html`<div class="log-item">[${l.step}] ${l.message}</div>`)}
      </div>
    `;
  }

  private _copy(text: string) {
    navigator.clipboard.writeText(text).then(() => store.showStatus('已复制', 'success'));
  }

  private _download(r: ConvertResult) {
    const blob = new Blob([r.convertedContent || ''], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `converted.${r.outputFormat || 'txt'}`;
    a.click();
    URL.revokeObjectURL(url);
  }
}

declare global { interface HTMLElementTagNameMap { 'app-result': AppResult; } }
