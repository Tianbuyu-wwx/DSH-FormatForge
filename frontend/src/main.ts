// ============================================================
// AI 数据转换器 - 应用入口
// ============================================================

import '../styles/main.css';

// 组件将在后续步骤中逐步引入
import './components/app-background';
import './components/app-upload';
import './components/app-options';
import './components/app-convert-btn';
import './components/app-status';
import './components/app-result';

import { LitElement, html, css } from 'lit';
import { customElement, query } from 'lit/decorators.js';
import { store } from './state/store.js';
import { uploadAndConvert, ApiError } from './utils/api.js';
import { AppUpload } from './components/app-upload.js';

/**
 * 应用根组件
 * 后续步骤中会逐步替换为完整的组件树
 */
@customElement('app-root')
export class AppRoot extends LitElement {
  @query('app-upload') private _upload!: AppUpload;

  private _onConvertBound = this._onConvert.bind(this);
  static styles = css`
    :host {
      display: block;
      min-height: 100vh;
    }

    .container {
      max-width: 900px;
      margin: 0 auto;
      padding: 120px 20px 40px;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      position: relative;
      z-index: 1;
    }

    .header {
      text-align: center;
      margin-bottom: 50px;
    }

    .logo {
      font-size: 2.5rem;
      font-weight: 700;
      margin-bottom: 10px;
      text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
    }

    .subtitle {
      font-size: 1.1rem;
      opacity: 0.9;
      text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.3);
    }

    .footer {
      text-align: center;
      padding: 20px;
      opacity: 0.8;
      font-size: 0.9rem;
      margin-top: auto;
    }
  `;

  connectedCallback() {
    super.connectedCallback();
    this.addEventListener('convert', this._onConvertBound);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.removeEventListener('convert', this._onConvertBound);
  }

  render() {
    return html`
      <app-background></app-background>
      <app-status></app-status>
      <div class="container">
        <header class="header">
          <h1 class="logo">AI 数据转换器</h1>
          <p class="subtitle">自动将各种格式数据转换为AI可识别的标准化数据</p>
        </header>

        <main class="flex-1">
          <app-upload></app-upload>
          <app-options></app-options>
          <app-convert-btn></app-convert-btn>
          <app-result></app-result>
        </main>

        <footer class="footer">
          <p>&copy; 2026 AI 数据转换器 | 智能数据格式化工具</p>
        </footer>
      </div>
    `;
  }
private async _onConvert() {
    const rawFile = this._upload?.getRawFile();
    if (!rawFile) {
      store.showStatus('请先选择文件', 'error');
      return;
    }

    const { conversionType, outputFormat, customPrompt } = store.state;

    try {
      store.clearResult();
      store.setLoading(true);
      store.setProgress('upload', 0);

      const result = await uploadAndConvert(
        rawFile,
        { conversionType, outputFormat, customPrompt },
        (phase, percent) => store.setProgress(phase as Parameters<typeof store.setProgress>[0], percent),
      );

      store.setResult(result);
      store.showStatus('转换完成！', 'success');
    } catch (err) {
      const message = err instanceof ApiError
        ? err.message
        : '网络错误，请检查后端服务是否启动';
      store.showStatus(message, 'error');
    } finally {
      store.setLoading(false);
      store.setProgress('done', 100);
    }
  }
}

// 全局错误处理
window.addEventListener('error', (e) => {
  console.error('[App Error]', e.error);
});

// 未捕获的 Promise 错误
window.addEventListener('unhandledrejection', (e) => {
  console.error('[Unhandled Promise]', e.reason);
});