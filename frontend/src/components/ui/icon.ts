// ============================================================
// v3.0 图标 — 粗线条手绘风格，去 Lucide 感
// ============================================================
// stroke-width: 2.5px，圆角连接，更粗更有个性

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';

export type IconName =
  | 'upload' | 'file' | 'file-text' | 'file-spreadsheet' | 'file-image' | 'file-code'
  | 'link' | 'text-input' | 'history' | 'trash' | 'convert' | 'check' | 'close'
  | 'folder' | 'folder-open' | 'copy' | 'chevron-down' | 'settings' | 'info'
  | 'empty' | 'no-data';

@customElement('ui-icon')
export class UiIcon extends LitElement {
  @property({ type: String }) name: IconName = 'file';
  @property({ type: Number }) size = 20;

  static styles = css`
    :host { display: inline-flex; align-items: center; justify-content: center;
      flex-shrink: 0; line-height: 0; vertical-align: middle; }
    svg { display: block; width: 100%; height: 100%; }
  `;

  render() {
    return html`<svg xmlns="http://www.w3.org/2000/svg" width=${this.size} height=${this.size}
      viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
      stroke-linecap="round" stroke-linejoin="round">${this._path()}</svg>`;
  }

  private _path() {
    const p: Record<IconName, ReturnType<typeof html>> = {
      upload: html`<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>`,
      file: html`<path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/>`,
      'file-text': html`<path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/>`,
      'file-spreadsheet': html`<path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><rect x="8" y="12" width="8" height="6" rx="1"/><line x1="8" y1="15" x2="16" y2="15"/>`,
      'file-image': html`<path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><circle cx="10" cy="13" r="2"/><path d="M20 18l-4-4-2 2-3-3-3 5"/>`,
      'file-code': html`<path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><polyline points="10 13 8 15 10 17"/><polyline points="14 13 16 15 14 17"/>`,
      link: html`<path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/>`,
      'text-input': html`<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/>`,
      history: html`<path d="M3 12a9 9 0 119 9"/><polyline points="3 3 3 9 9 9"/><polyline points="12 7 12 12 16 14"/>`,
      trash: html`<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>`,
      convert: html`<polyline points="13 2 13 8 19 8"/><path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-7-6z"/><polyline points="11 18 9 16 11 14"/><polyline points="15 12 17 14 15 16"/>`,
      check: html`<polyline points="20 6 9 17 4 12"/>`,
      close: html`<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>`,
      folder: html`<path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>`,
      'folder-open': html`<path d="M6 14l1.5-2.9A2 2 0 019.2 10H20a2 2 0 012 2v7a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2v1"/>`,
      copy: html`<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>`,
      'chevron-down': html`<polyline points="6 9 12 15 18 9"/>`,
      settings: html`<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>`,
      info: html`<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>`,
      empty: html`<circle cx="12" cy="12" r="10"/><line x1="8" y1="15" x2="16" y2="15"/>`,
      'no-data': html`<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/>`,
    };
    return p[this.name] || p.file;
  }
}

declare global {
  interface HTMLElementTagNameMap { 'ui-icon': UiIcon; }
}
