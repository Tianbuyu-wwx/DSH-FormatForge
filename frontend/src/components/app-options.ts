// ============================================================
// <app-options> 转换选项面板
// ============================================================
// 文件选中后展开显示，包含转换类型、输出格式和自定义指令

import { LitElement, html, css } from 'lit';
import { customElement } from 'lit/decorators.js';
import { store } from '../state/store.js';

const CONVERSION_TYPES = [
  { value: 'auto', label: '自动检测' },
  { value: 'text', label: '纯文本提取' },
  { value: 'structured', label: '结构化数据' },
  { value: 'table', label: '表格提取' },
  { value: 'image_desc', label: '图片描述' },
  { value: 'ocr', label: 'OCR 文字识别' },
  { value: 'encoding', label: '编码修复' },
] as const;

const OUTPUT_FORMATS = [
  { value: 'json', label: 'JSON' },
  { value: 'markdown', label: 'Markdown' },
  { value: 'text', label: '纯文本' },
  { value: 'html', label: 'HTML' },
] as const;

@customElement('app-options')
export class AppOptions extends LitElement {
  static styles = css`
    :host {
      display: none;
      margin-bottom: 24px;
    }

    :host(.visible) {
      display: block;
    }

    .options-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }

    @media (max-width: 640px) {
      .options-grid {
        grid-template-columns: 1fr;
      }
    }

    /* 单个选项组 */
    .option-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .option-group.full {
      grid-column: 1 / -1;
    }

    .option-label {
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--color-text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    /* 下拉框 */
    .select-wrapper {
      position: relative;
    }

    select {
      width: 100%;
      padding: 10px 14px;
      padding-right: 36px;
      border-radius: 8px;
      border: 1px solid var(--color-border);
      background: var(--color-surface);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      color: var(--color-text-primary);
      font-size: 0.95rem;
      font-family: inherit;
      cursor: pointer;
      appearance: none;
      -webkit-appearance: none;
      transition: border-color 0.3s ease;
      outline: none;
    }

    select:focus {
      border-color: var(--color-primary);
    }

    select option {
      background: #1a1a2e;
      color: white;
    }

    .select-arrow {
      position: absolute;
      right: 14px;
      top: 50%;
      transform: translateY(-50%);
      pointer-events: none;
      color: var(--color-text-muted);
      font-size: 0.75rem;
    }

    /* 输入框 */
    input {
      width: 100%;
      padding: 10px 14px;
      border-radius: 8px;
      border: 1px solid var(--color-border);
      background: var(--color-surface);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      color: var(--color-text-primary);
      font-size: 0.95rem;
      font-family: inherit;
      outline: none;
      transition: border-color 0.3s ease;
    }

    input:focus {
      border-color: var(--color-primary);
    }

    input::placeholder {
      color: var(--color-text-muted);
    }
  `;

  private _unsub?: () => void;

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe((s) => {
      if (s.file) {
        this.classList.add('visible');
      } else {
        this.classList.remove('visible');
      }
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  render() {
    return html`
      <div class="options-grid">
        <div class="option-group">
          <label class="option-label" for="convType">转换类型</label>
          <div class="select-wrapper">
            <select id="convType" @change=${this._onTypeChange}>
              ${CONVERSION_TYPES.map(t => html`
                <option value=${t.value} ?selected=${store.state.conversionType === t.value}>
                  ${t.label}
                </option>
              `)}
            </select>
            <span class="select-arrow">▼</span>
          </div>
        </div>

        <div class="option-group">
          <label class="option-label" for="outFormat">输出格式</label>
          <div class="select-wrapper">
            <select id="outFormat" @change=${this._onFormatChange}>
              ${OUTPUT_FORMATS.map(f => html`
                <option value=${f.value} ?selected=${store.state.outputFormat === f.value}>
                  ${f.label}
                </option>
              `)}
            </select>
            <span class="select-arrow">▼</span>
          </div>
        </div>

        <div class="option-group full">
          <label class="option-label" for="customPrompt">自定义指令（可选）</label>
          <input
            type="text"
            id="customPrompt"
            placeholder="输入自定义转换要求，例如：提取所有表格并转换为JSON格式"
            @input=${this._onPromptChange}
            .value=${store.state.customPrompt}
          />
        </div>
      </div>
    `;
  }

  private _onTypeChange(e: Event) {
    const val = (e.target as HTMLSelectElement).value;
    store.setConversionType(val as typeof store.state.conversionType);
  }

  private _onFormatChange(e: Event) {
    const val = (e.target as HTMLSelectElement).value;
    store.setOutputFormat(val as typeof store.state.outputFormat);
  }

  private _onPromptChange(e: Event) {
    const val = (e.target as HTMLInputElement).value;
    store.setCustomPrompt(val);
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'app-options': AppOptions;
  }
}