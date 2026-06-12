// ============================================================
// <app-background> 视频背景组件
// ============================================================
// 功能：全屏视频背景 + CSS 渐变回退 + 渐变遮罩增强可读性
// 视频路径：background/Genshin Impact - Kusanali in the forest - PC.mp4

import { LitElement, html, css } from 'lit';
import { customElement, state } from 'lit/decorators.js';

// 视频资源路径（相对于 index.html）
const VIDEO_SRC = 'background/Genshin Impact -  Kusanali in the forest - PC.mp4';

@customElement('app-background')
export class AppBackground extends LitElement {
  /** 视频是否已开始播放 */
  @state() private _videoReady = false;

  /** 浏览器是否不支持视频 */
  @state() private _videoError = false;

  static styles = css`
    :host {
      display: block;
      position: fixed;
      inset: 0;
      z-index: -1;
    }

    /* ===== 渐变回退层 ===== */
    .bg-fallback {
      position: absolute;
      inset: 0;
      background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
      transition: opacity 1s ease;
    }

    .bg-fallback.hidden {
      opacity: 0;
    }

    /* ===== 视频层 ===== */
    .bg-video {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      opacity: 0;
      transition: opacity 1.5s ease;
    }

    .bg-video.ready {
      opacity: 1;
    }

    /* ===== 渐变遮罩 ===== */
    .bg-overlay {
      position: absolute;
      inset: 0;
      background:
        /* 顶部暗角 */
        linear-gradient(to bottom, rgba(15, 12, 41, 0.6) 0%, rgba(15, 12, 41, 0.2) 30%, transparent 50%),
        /* 底部暗角 */
        linear-gradient(to top, rgba(36, 36, 62, 0.7) 0%, transparent 40%),
        /* 左右暗角 */
        radial-gradient(ellipse at center, transparent 50%, rgba(15, 12, 41, 0.4) 100%),
        /* 色温统一层 */
        rgba(15, 12, 41, 0.25);
      pointer-events: none;
    }

    /* ===== 光晕点缀 ===== */
    .bg-glow {
      position: absolute;
      inset: 0;
      background:
        radial-gradient(ellipse at 15% 40%, rgba(72, 52, 212, 0.2) 0%, transparent 50%),
        radial-gradient(ellipse at 85% 25%, rgba(0, 201, 255, 0.1) 0%, transparent 50%),
        radial-gradient(ellipse at 50% 85%, rgba(146, 84, 222, 0.15) 0%, transparent 50%);
      pointer-events: none;
    }
  `;

  render() {
    return html`
      <!-- 渐变回退 -->
      <div class="bg-fallback ${this._videoReady && !this._videoError ? 'hidden' : ''}"></div>

      <!-- 视频 -->
      <video
        class="bg-video ${this._videoReady ? 'ready' : ''}"
        autoplay
        muted
        loop
        playsinline
        preload="metadata"
        @loadeddata=${this._onVideoLoaded}
        @playing=${this._onVideoPlaying}
        @error=${this._onVideoError}
        src=${VIDEO_SRC}
      ></video>

      <!-- 遮罩层 -->
      <div class="bg-overlay"></div>

      <!-- 光晕 -->
      <div class="bg-glow"></div>
    `;
  }

  private _onVideoLoaded() {
    this._videoReady = true;
  }

  private _onVideoPlaying() {
    this._videoReady = true;
  }

  private _onVideoError() {
    // 视频加载失败，回退到 CSS 渐变
    this._videoError = true;
    console.warn('[AppBackground] 视频加载失败，使用 CSS 渐变回退');
  }

  /** 公开方法：重新加载视频 */
  reload() {
    const video = this.shadowRoot?.querySelector('video');
    if (video) {
      video.load();
    }
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'app-background': AppBackground;
  }
}