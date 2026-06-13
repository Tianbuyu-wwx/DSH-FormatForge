// ============================================================
// <app-background> v4.0 — 视频+God Rays+暗角+Canvas粒子
// ============================================================

import { LitElement, html, css } from 'lit';
import { customElement } from 'lit/decorators.js';

const VIDEO_SRC = 'background/Genshin Impact -  Kusanali in the forest - PC.mp4';

@customElement('app-background')
export class AppBackground extends LitElement {
  private _canvas?: HTMLCanvasElement;
  private _ctx?: CanvasRenderingContext2D;
  private _animId = 0;
  private _particles: Array<{
    x: number; y: number; size: number;
    speedX: number; speedY: number;
    opacity: number; targetOpacity: number;
    life: number; maxLife: number; hue: number;
  }> = [];

  static styles = css`
    :host { display: block; position: fixed; inset: 0; z-index: -3; }

    video {
      position: absolute; inset: 0;
      width: 100%; height: 100%;
      object-fit: cover;
    }

    .godrays {
      position: absolute;
      top: -15%; left: 20%;
      width: 60%; height: 85%;
      background: radial-gradient(ellipse at 50% 0%, rgba(255,248,231,0.16) 0%, transparent 60%);
      filter: blur(50px);
      mix-blend-mode: screen;
      pointer-events: none;
      animation: godrayPulse 8s ease-in-out infinite;
    }

    .vignette {
      position: absolute; inset: 0;
      background: radial-gradient(ellipse at 50% 55%, transparent 25%, rgba(10,31,20,0.4) 70%, rgba(10,31,20,0.85) 100%);
      pointer-events: none;
    }

    canvas {
      position: absolute; inset: 0;
      pointer-events: none;
    }

    @keyframes godrayPulse {
      0%, 100% { opacity: 0.7; transform: scale(1); }
      50%      { opacity: 1;   transform: scale(1.06); }
    }
  `;

  firstUpdated() {
    this._initParticles();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    cancelAnimationFrame(this._animId);
  }

  private _initParticles() {
    const canvas = this.shadowRoot?.querySelector('canvas') as HTMLCanvasElement;
    if (!canvas) return;
    this._canvas = canvas;
    this._ctx = canvas.getContext('2d')!;

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    window.addEventListener('resize', resize);
    resize();

    const COUNT = 40;
    for (let i = 0; i < COUNT; i++) {
      this._particles.push(this._createParticle(true));
    }

    const animate = () => {
      const ctx = this._ctx!;
      const W = canvas.width;
      const H = canvas.height;
      ctx.clearRect(0, 0, W, H);

      for (const p of this._particles) {
        p.life++;
        p.x += p.speedX + Math.sin(p.life * 0.01) * 0.3;
        p.y += p.speedY;

        if (p.life < 60) {
          p.opacity = (p.life / 60) * p.targetOpacity;
        } else if (p.life > p.maxLife - 60) {
          p.opacity = ((p.maxLife - p.life) / 60) * p.targetOpacity;
        }

        if (p.life >= p.maxLife || p.y < 0) {
          Object.assign(p, this._createParticle(false));
        }

        ctx.save();
        ctx.globalAlpha = p.opacity;
        const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.size * 4);
        g.addColorStop(0, `hsla(${p.hue}, 90%, 75%, 1)`);
        g.addColorStop(0.3, `hsla(${p.hue}, 80%, 60%, 0.4)`);
        g.addColorStop(1, `hsla(${p.hue}, 70%, 50%, 0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size * 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = `hsla(${p.hue}, 100%, 90%, ${p.opacity})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size * 0.6, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      this._animId = requestAnimationFrame(animate);
    };
    animate();
  }

  private _createParticle(randomLife: boolean) {
    const W = this._canvas?.width || window.innerWidth;
    const H = this._canvas?.height || window.innerHeight;
    const p = {
      x: Math.random() * W,
      y: H - Math.random() * (H * 0.3),
      size: Math.random() * 2.5 + 1,
      speedX: (Math.random() - 0.5) * 0.4,
      speedY: -(Math.random() * 0.6 + 0.2),
      opacity: 0,
      targetOpacity: Math.random() * 0.6 + 0.2,
      life: 0,
      maxLife: Math.random() * 400 + 300,
      hue: Math.random() > 0.7 ? 45 : 50,
    };
    if (randomLife) p.life = Math.random() * p.maxLife;
    return p;
  }

  render() {
    return html`
      <video autoplay muted loop playsinline preload="metadata">
        <source src=${VIDEO_SRC} type="video/mp4">
      </video>
      <div class="godrays"></div>
      <div class="vignette"></div>
      <canvas></canvas>
    `;
  }
}

declare global { interface HTMLElementTagNameMap { 'app-background': AppBackground; } }
