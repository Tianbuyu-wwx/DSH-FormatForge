// ============================================================
// <app-compare> v4.0 — 对比弹窗
// ============================================================

import { LitElement, html, css } from 'lit';
import { customElement } from 'lit/decorators.js';
import { store } from '../state/store.js';
import type { ConvertResult } from '../types/index.js';
import '../components/ui/icon.js';

@customElement('app-compare')
export class AppCompare extends LitElement {
  static styles = css`
    :host { position: fixed; inset: 0; z-index: 900; display: none; }
    :host(.open) { display: block; }

    .backdrop {
      position: absolute; inset: 0;
      background: rgba(0,0,0,0.6);
      animation: fadeIn 0.2s var(--ease);
    }

    .modal {
      position: absolute;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%);
      width: 90vw; max-width: 960px; height: 80vh;
      background: rgba(15, 46, 46, 0.9);
      backdrop-filter: blur(24px);
      border: 1px solid var(--border);
      border-radius: 16px;
      display: flex; flex-direction: column;
      animation: fadeIn 0.2s var(--ease);
      box-shadow: 0 24px 80px rgba(0,0,0,0.5);
    }

    .modal-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: var(--space-3) var(--space-4);
      border-bottom: 1px solid var(--border);
    }
    .modal-title { font-size: var(--text-sm); font-weight: 500; color: var(--text); }
    .close-btn {
      color: var(--text-muted); background: none; border: none; cursor: pointer;
      transition: color var(--duration);
    }
    .close-btn:hover { color: var(--text); }

    .modal-body {
      flex: 1; display: flex; overflow: hidden;
    }
    .pane {
      flex: 1; padding: var(--space-4); overflow: auto;
      font-family: var(--font-mono); font-size: var(--text-sm); line-height: 1.6;
      color: var(--text); white-space: pre-wrap;
    }
    .pane:first-child { border-right: 1px solid var(--border); }
    .pane-label {
      font-family: var(--font-body); font-size: var(--text-xs);
      color: var(--text-muted); margin-bottom: var(--space-2);
      text-transform: uppercase; letter-spacing: 0.05em;
    }

    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }
  `;

  private _unsub?: () => void;
  private _result: ConvertResult | null = null;

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe((s) => {
      this._result = s.result;
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  show() { this.classList.add('open'); }
  hide() { this.classList.remove('open'); }

  render() {
    const r = this._result;
    if (!r) return html``;
    return html`
      <div class="backdrop" @click=${() => this.hide()}></div>
      <div class="modal">
        <div class="modal-header">
          <span class="modal-title">对比预览</span>
          <button class="close-btn" @click=${() => this.hide()}><ui-icon name="close" size="18"></ui-icon></button>
        </div>
        <div class="modal-body">
          <div class="pane">
            <div class="pane-label">原始内容</div>
            ${r.parsedContent || '无原始内容'}
          </div>
          <div class="pane">
            <div class="pane-label">转换后</div>
            ${r.convertedContent || '无转换内容'}
          </div>
        </div>
      </div>
    `;
  }
}

declare global { interface HTMLElementTagNameMap { 'app-compare': AppCompare; } }
