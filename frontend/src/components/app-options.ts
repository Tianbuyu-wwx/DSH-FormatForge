// ============================================================
// <app-options> v4.0 — 紧凑行内选项
// ============================================================

import { LitElement, html, css } from 'lit';
import { customElement } from 'lit/decorators.js';
import { store } from '../state/store.js';

@customElement('app-options')
export class AppOptions extends LitElement {
  static styles = css`
    :host { display: block; margin-bottom: var(--space-3); }
    .row { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }

    .field {
      display: flex;
      align-items: center;
      gap: var(--space-1);
    }
    .field-label {
      font-size: var(--text-xs);
      color: var(--text-muted);
      white-space: nowrap;
      letter-spacing: 0.03em;
    }

    select {
      appearance: none;
      -webkit-appearance: none;
      padding: 5px 22px 5px 8px;
      font-family: var(--font-body);
      font-size: var(--text-xs);
      color: var(--text);
      background: rgba(0,0,0,0.2);
      border: 1px solid var(--border);
      border-radius: 6px;
      cursor: pointer;
      outline: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='%238a8884' stroke-width='3'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 6px center;
      transition: border-color var(--duration);
    }
    select:focus { border-color: var(--border-focus); }

    .custom-input {
      width: 100%;
      padding: 8px 12px;
      font-family: var(--font-body);
      font-size: var(--text-sm);
      color: var(--text);
      background: rgba(0,0,0,0.2);
      border: 1px solid var(--border);
      border-radius: 6px;
      outline: none;
      margin-top: var(--space-2);
      box-sizing: border-box;
    }
    .custom-input::placeholder { color: var(--text-muted); }
    .custom-input:focus { border-color: var(--border-focus); }

    /* ===== 响应式 ===== */
    @media (max-width: 479px) {
      .row { gap: var(--space-2); }
      .field-label { font-size: 11px; }
      select { padding: 4px 18px 4px 6px; font-size: 11px; }
    }
  `;

  render() {
    const { conversionType, outputFormat, customPrompt } = store.state;
    return html`
      <div class="row">
        <div class="field">
          <span class="field-label">转换类型</span>
          <select .value=${conversionType} @change=${this._onType}>
            <option value="auto">自动检测</option>
            <option value="text">纯文本提取</option>
            <option value="structured">结构化数据</option>
            <option value="table">表格提取</option>
            <option value="image_desc">图片描述</option>
            <option value="ocr">OCR 文字识别</option>
            <option value="encoding">编码修复</option>
          </select>
        </div>
        <div class="field">
          <span class="field-label">输出格式</span>
          <select .value=${outputFormat} @change=${this._onFormat}>
            <option value="json">JSON</option>
            <option value="markdown">Markdown</option>
            <option value="text">纯文本</option>
            <option value="html">HTML</option>
          </select>
        </div>
      </div>
      <input class="custom-input" type="text" .value=${customPrompt || ''}
        placeholder="自定义指令（可选）"
        @input=${(e: InputEvent) => store.setCustomPrompt((e.target as HTMLInputElement).value)}>
    `;
  }

  private _onType(e: Event) {
    store.setConversionType((e.target as HTMLSelectElement).value as any);
  }

  private _onFormat(e: Event) {
    store.setOutputFormat((e.target as HTMLSelectElement).value as any);
  }
}

declare global { interface HTMLElementTagNameMap { 'app-options': AppOptions; } }
