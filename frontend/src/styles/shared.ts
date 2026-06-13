// ============================================================
// v4.0 共享样式 — 森林风格
// ============================================================

import { css } from 'lit';

export const sharedStyles = css`
  /* ===== 输入框 ===== */
  .input {
    width: 100%;
    padding: 10px 12px;
    font-family: var(--font-body);
    font-size: var(--text-sm);
    color: var(--text);
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 6px;
    outline: none;
    transition: border-color var(--duration) var(--ease);
  }
  .input:focus { border-color: var(--border-focus); }
  .input::placeholder { color: var(--text-muted); }

  .textarea {
    width: 100%;
    min-height: 140px;
    padding: 10px 12px;
    font-family: var(--font-body);
    font-size: var(--text-sm);
    line-height: 1.6;
    color: var(--text);
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 6px;
    resize: vertical;
    outline: none;
    transition: border-color var(--duration) var(--ease);
  }
  .textarea:focus { border-color: var(--border-focus); }
  .textarea::placeholder { color: var(--text-muted); }

  /* ===== 按钮 ===== */
  .btn-pill {
    display: inline-flex;
    align-items: center;
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
    transition: all 0.4s var(--ease);
    box-shadow: 0 4px 16px rgba(74,222,128,0.2);
    user-select: none;
  }
  .btn-pill:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 28px rgba(74,222,128,0.35);
  }
  .btn-pill:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }

  .btn-ghost {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: 5px 10px;
    font-family: var(--font-body);
    font-size: var(--text-xs);
    color: var(--text-secondary);
    background: transparent;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    transition: color var(--duration) var(--ease);
    user-select: none;
  }
  .btn-ghost:hover { color: var(--text); }
`;
