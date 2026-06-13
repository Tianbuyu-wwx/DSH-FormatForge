// ============================================================
// <app-status> v4.0 — 顶部横幅 Toast
// ============================================================

import { LitElement, html, css } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { store } from '../state/store.js';

const TYPE_COLORS: Record<string, string> = {
  success: 'var(--success)',
  error: 'var(--error)',
  info: 'var(--info)',
};

@customElement('app-status')
export class AppStatus extends LitElement {
  @state() private _msg = '';
  @state() private _type: 'success' | 'error' | 'info' = 'info';
  @state() private _visible = false;
  private _timer?: ReturnType<typeof setTimeout>;

  static styles = css`
    :host {
      position: fixed;
      top: 0; left: 0; right: 0;
      z-index: 1000;
      pointer-events: none;
    }
    .bar {
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 10px var(--space-5);
      font-size: var(--text-sm);
      color: var(--text);
      background: rgba(15, 46, 46, 0.85);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--border);
      transform: translateY(-100%);
      transition: transform 0.25s var(--ease);
      pointer-events: auto;
    }
    .bar.visible {
      transform: translateY(0);
    }
    .bar::before {
      content: '';
      position: absolute;
      left: 0; top: 0; bottom: 0;
      width: 3px;
      background: var(--accent-color, var(--info));
    }

    /* ===== 响应式 ===== */
    @media (max-width: 479px) {
      .bar { padding: 8px 12px; font-size: var(--text-xs); }
    }
  `;

  private _unsub?: () => void;

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe((s) => {
      const st = s.status;
      if (!st) { this._visible = false; return; }
      clearTimeout(this._timer);
      this._msg = st.message;
      this._type = st.type;
      this._visible = true;
      this._timer = setTimeout(() => {
        this._visible = false;
        store.clearStatus();
      }, 3500);
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
    clearTimeout(this._timer);
  }

  render() {
    return html`
      <div class="bar ${this._visible ? 'visible' : ''}"
        style="--accent-color:${TYPE_COLORS[this._type] || TYPE_COLORS.info}">
        ${this._msg}
      </div>
    `;
  }
}

declare global { interface HTMLElementTagNameMap { 'app-status': AppStatus; } }
