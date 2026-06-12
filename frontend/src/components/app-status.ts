// ============================================================
// <app-status> Toast 通知组件
// ============================================================
// 右上角浮动 Toast，3.5 秒自动消失，支持 info/success/error 三种类型

import { LitElement, html, css } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { store } from '../state/store.js';
import type { StatusMessage } from '../types/index.js';

const ICONS: Record<StatusMessage['type'], string> = {
  info:    'ℹ️',
  success: '✅',
  error:   '❌',
};

const COLORS: Record<StatusMessage['type'], string> = {
  info:    'var(--color-info)',
  success: 'var(--color-success)',
  error:   'var(--color-error)',
};

@customElement('app-status')
export class AppStatus extends LitElement {
  @state() private _status: StatusMessage | null = null;
  @state() private _visible = false;
  @state() private _exiting = false;

  private _timer: ReturnType<typeof setTimeout> | null = null;
  private _lastId = -1;

  static styles = css`
    :host {
      display: block;
      position: fixed;
      top: 24px;
      right: 24px;
      z-index: 1000;
      pointer-events: none;
    }

    .toast {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 14px 20px;
      border-radius: 10px;
      background: rgba(20, 20, 40, 0.92);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.15);
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
      opacity: 0;
      transform: translateX(120%);
      transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
      pointer-events: auto;
      max-width: 400px;
    }

    .toast.visible {
      opacity: 1;
      transform: translateX(0);
    }

    .toast.exiting {
      opacity: 0;
      transform: translateX(120%);
    }

    .toast-icon {
      font-size: 1.2rem;
      flex-shrink: 0;
    }

    .toast-message {
      font-size: 0.9rem;
      line-height: 1.4;
      color: var(--color-text-primary);
      word-break: break-word;
    }

    .toast-close {
      background: none;
      border: none;
      color: var(--color-text-muted);
      cursor: pointer;
      font-size: 1rem;
      padding: 2px;
      margin-left: 4px;
      flex-shrink: 0;
      transition: color 0.2s;
    }

    .toast-close:hover {
      color: white;
    }
  `;

  private _unsub?: () => void;

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe((s) => {
      if (s.status && s.status.id !== this._lastId) {
        this._show(s.status);
      }
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
    if (this._timer) clearTimeout(this._timer);
  }

  private _show(msg: StatusMessage) {
    if (this._timer) clearTimeout(this._timer);

    this._lastId = msg.id;
    this._status = msg;
    this._exiting = false;

    // 下一帧触发入场动画
    requestAnimationFrame(() => {
      this._visible = true;
    });

    // 自动消失
    this._timer = setTimeout(() => this._hide(), 3500);
  }

  private _hide() {
    this._exiting = true;
    this._visible = false;
    this._timer = setTimeout(() => {
      this._status = null;
    }, 350);
  }

  private _onDismiss() {
    if (this._timer) clearTimeout(this._timer);
    this._hide();
  }

  render() {
    if (!this._status) return html``;

    const cls = this._visible ? 'visible' : this._exiting ? 'exiting' : '';

    return html`
      <div class="toast ${cls}" style="border-left: 3px solid ${COLORS[this._status.type]}">
        <span class="toast-icon">${ICONS[this._status.type]}</span>
        <span class="toast-message">${this._status.message}</span>
        <button class="toast-close" @click=${this._onDismiss} title="关闭">✕</button>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'app-status': AppStatus;
  }
}