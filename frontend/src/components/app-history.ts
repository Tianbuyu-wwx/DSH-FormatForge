// ============================================================
// <app-history> v4.0 — 下拉覆盖层式历史面板
// ============================================================

import { LitElement, html, css } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { store } from '../state/store.js';
import { formatFileSize } from '../utils/format.js';
import { getHistory, deleteHistory } from '../utils/api.js';
import type { HistoryItem } from '../types/index.js';
import '../components/ui/icon.js';

@customElement('app-history')
export class AppHistory extends LitElement {
  @state() private _items: HistoryItem[] = [];
  @state() private _open = false;

  static styles = css`
    :host { position: relative; display: inline-block; }

    .overlay {
      position: fixed;
      inset: 0;
      z-index: 200;
      display: none;
    }
    .overlay.open { display: block; }

    .panel {
      position: absolute;
      top: calc(100% + 8px);
      right: 0;
      width: 340px;
      max-height: 420px;
      background: rgba(15, 46, 46, 0.85);
      backdrop-filter: blur(20px);
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow: hidden;
      display: none;
      flex-direction: column;
      z-index: 201;
      box-shadow: 0 16px 48px rgba(0,0,0,0.4);
    }
    .panel.open {
      display: flex;
      animation: fadeIn 0.15s var(--ease);
    }

    .panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--space-3) var(--space-4);
      border-bottom: 1px solid var(--border);
      font-size: var(--text-sm);
      font-weight: 500;
      color: var(--text);
    }

    .panel-body {
      overflow-y: auto;
      padding: var(--space-1) 0;
    }

    .item {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      padding: var(--space-2) var(--space-4);
      cursor: pointer;
      transition: background var(--duration);
    }
    .item:hover { background: var(--bg-hover); }

    .item-info { flex: 1; min-width: 0; }
    .item-name { font-size: var(--text-sm); color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .item-meta { font-size: var(--text-xs); color: var(--text-muted); }
    .item-del { color: var(--text-muted); cursor: pointer; background: none; border: none; padding: 0; transition: color var(--duration); }
    .item-del:hover { color: var(--error); }

    .empty {
      padding: var(--space-6);
      text-align: center;
      font-size: var(--text-sm);
      color: var(--text-muted);
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(-4px); }
      to { opacity: 1; transform: translateY(0); }
    }
  `;

  private _unsub?: () => void;

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe((s) => {
      if (s.showHistory !== this._open) {
        this._open = s.showHistory;
        if (this._open) this._load();
      }
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  render() {
    return html`
      <div class="overlay ${this._open ? 'open' : ''}" @click=${this._close}></div>
      <div class="panel ${this._open ? 'open' : ''}">
        <div class="panel-header">
          <span>历史记录</span>
          <span style="color:var(--text-muted);font-size:var(--text-xs);font-weight:400;">${this._items.length} 条</span>
        </div>
        <div class="panel-body">
          ${this._items.length === 0 ? html`<div class="empty">暂无历史记录</div>` : ''}
          ${this._items.map(item => html`
            <div class="item" @click=${() => this._view(item)}>
              <ui-icon name="file-text" size="16"></ui-icon>
              <div class="item-info">
                <div class="item-name">${item.file_name}</div>
                <div class="item-meta">${formatFileSize(item.file_size)} · ${item.output_format} · ${new Date(item.created_at).toLocaleDateString()}</div>
              </div>
              <button class="item-del" @click=${(e: Event) => { e.stopPropagation(); this._delete(item); }}>
                <ui-icon name="trash" size="14"></ui-icon>
              </button>
            </div>
          `)}
        </div>
      </div>
    `;
  }

  private async _load() {
    try { const res = await getHistory(); this._items = res.items; }
    catch { this._items = []; }
  }

  private _close() { store.toggleHistory(); }

  private _view(item: HistoryItem) {
    this._close();
    store.viewHistory(item.result_id);
  }

  private async _delete(item: HistoryItem) {
    try {
      await deleteHistory(item.result_id);
      this._items = this._items.filter(i => i.id !== item.id);
      store.showStatus('已删除', 'success');
    } catch {
      store.showStatus('删除失败', 'error');
    }
  }
}

declare global { interface HTMLElementTagNameMap { 'app-history': AppHistory; } }
