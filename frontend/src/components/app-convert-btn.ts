// ============================================================
// <app-convert-btn> v4.0 — 药丸渐变按钮
// ============================================================

import { LitElement, html, css } from 'lit';
import { customElement } from 'lit/decorators.js';
import { store } from '../state/store.js';
import '../components/ui/icon.js';

@customElement('app-convert-btn')
export class AppConvertBtn extends LitElement {
  static styles = css`
    :host { display: block; margin-bottom: var(--space-2); }

    .wrap {
      display: flex;
      justify-content: flex-end;
    }

    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: var(--space-2);
      padding: 10px 24px;
      font-family: var(--font-body);
      font-size: var(--text-sm);
      font-weight: 500;
      color: var(--forest-deep);
      background: linear-gradient(135deg, var(--accent-green) 0%, var(--forest-light) 100%);
      border: none;
      border-radius: 999px;
      cursor: pointer;
      letter-spacing: 0.02em;
      transition: all 0.4s var(--ease);
      box-shadow: 0 4px 16px rgba(74,222,128,0.2);
      white-space: nowrap;
      user-select: none;
    }

    .btn:hover {
      transform: translateY(-2px);
      box-shadow: 0 8px 28px rgba(74,222,128,0.35);
    }

    .btn:disabled {
      opacity: 0.4;
      cursor: not-allowed;
      transform: none;
    }

    .progress {
      position: relative;
      overflow: hidden;
    }
    .progress::after {
      content: '';
      position: absolute;
      left: 0; top: 0; bottom: 0;
      background: rgba(0,0,0,0.15);
      width: var(--progress, 0%);
      transition: width 0.3s var(--ease);
    }
    .btn-label { position: relative; z-index: 1; }

    /* ===== 响应式 ===== */
    @media (max-width: 479px) {
      .wrap { justify-content: stretch; }
      .btn { width: 100%; justify-content: center; padding: 10px 16px; font-size: var(--text-xs); }
    }
  `;

  private _unsub?: () => void;

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe(() => this.requestUpdate());
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  render() {
    const { loading, progress } = store.state;
    const pct = progress?.percent || 0;

    if (loading) {
      return html`
        <div class="wrap">
          <button class="btn progress" disabled style="--progress:${pct}%">
            <span class="btn-label">${pct}%</span>
          </button>
        </div>
      `;
    }

    return html`
      <div class="wrap">
        <button class="btn" @click=${this._onClick}>
          <span>开始转换</span>
          <ui-icon name="convert" size="14"></ui-icon>
        </button>
      </div>
    `;
  }

  private _onClick() {
    this.dispatchEvent(new CustomEvent('convert', { bubbles: true, composed: true }));
  }
}

declare global { interface HTMLElementTagNameMap { 'app-convert-btn': AppConvertBtn; } }
