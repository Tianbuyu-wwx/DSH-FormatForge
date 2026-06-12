// ============================================================
// <app-convert-btn> 转换按钮 + 进度环
// ============================================================
// 根据 store 状态切换：禁用 → 可点击 → 加载中 → 完成

import { LitElement, html, css } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { store } from '../state/store.js';

const PHASE_LABELS: Record<string, string> = {
  upload: '上传中...',
  parse: '解析中...',
  convert: 'AI 转换中...',
  done: '完成',
};

@customElement('app-convert-btn')
export class AppConvertBtn extends LitElement {
  @state() private _hasFile = false;
  @state() private _loading = false;
  @state() private _phase = '';
  @state() private _percent = 0;

  static styles = css`
    :host {
      display: block;
      text-align: center;
      margin-bottom: 24px;
    }

    .btn-wrap {
      display: inline-flex;
      flex-direction: column;
      align-items: center;
      gap: 12px;
    }

    /* 圆形进度环 */
    .progress-ring {
      display: none;
      position: relative;
      width: 140px;
      height: 140px;
    }

    .progress-ring.visible {
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .ring-bg {
      fill: none;
      stroke: rgba(255, 255, 255, 0.1);
    }

    .ring-fg {
      fill: none;
      stroke: url(#ringGradient);
      stroke-linecap: round;
      transform: rotate(-90deg);
      transform-origin: center;
      transition: stroke-dashoffset 0.5s ease;
    }

    .ring-text {
      position: absolute;
      text-align: center;
    }

    .ring-percent {
      font-size: 1.8rem;
      font-weight: 700;
    }

    .ring-label {
      font-size: 0.78rem;
      color: var(--color-text-muted);
      margin-top: 2px;
    }

    /* 按钮 */
    .convert-btn {
      background: linear-gradient(135deg, var(--color-secondary) 0%, var(--color-accent) 100%);
      color: white;
      border: none;
      padding: 18px 48px;
      font-size: 1.2rem;
      font-weight: 600;
      border-radius: 12px;
      cursor: pointer;
      transition: all 0.3s ease;
      box-shadow: 0 4px 20px rgba(17, 153, 142, 0.4);
      font-family: inherit;
    }

    .convert-btn:hover:not(:disabled) {
      transform: translateY(-2px);
      box-shadow: 0 6px 25px rgba(17, 153, 142, 0.5);
    }

    .convert-btn:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    .convert-btn.hidden {
      display: none;
    }
  `;

  private _unsub?: () => void;

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe((s) => {
      this._hasFile = !!s.file;
      this._loading = s.loading;
      this._phase = s.progress.phase;
      this._percent = s.progress.percent;
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  render() {
    const radius = 58;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (this._percent / 100) * circumference;

    return html`
      <div class="btn-wrap">
        <!-- 圆形进度环 -->
        <div class="progress-ring ${this._loading ? 'visible' : ''}">
          <svg width="140" height="140" viewBox="0 0 140 140">
            <defs>
              <linearGradient id="ringGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" style="stop-color:var(--color-secondary)" />
                <stop offset="100%" style="stop-color:var(--color-accent)" />
              </linearGradient>
            </defs>
            <circle class="ring-bg" cx="70" cy="70" r=${radius} stroke-width="6" />
            <circle
              class="ring-fg"
              cx="70" cy="70" r=${radius}
              stroke-width="6"
              stroke-dasharray=${circumference}
              stroke-dashoffset=${offset}
            />
          </svg>
          <div class="ring-text">
            <div class="ring-percent">${this._percent}%</div>
            <div class="ring-label">${PHASE_LABELS[this._phase] ?? ''}</div>
          </div>
        </div>

        <!-- 按钮 -->
        <button
          class="convert-btn ${this._loading ? 'hidden' : ''}"
          ?disabled=${!this._hasFile}
          @click=${this._onClick}
        >
          ⚡ 开始转换
        </button>
      </div>
    `;
  }

  private _onClick() {
    this.dispatchEvent(new CustomEvent('convert', { bubbles: true, composed: true }));
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'app-convert-btn': AppConvertBtn;
  }
}