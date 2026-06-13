// ============================================================
// v4.0 动画 — 森林呼吸感
// ============================================================

import { css } from 'lit';

export const animationKeyframes = css`
  @keyframes fadeIn {
    from { opacity: 0; }
    to   { opacity: 1; }
  }

  @keyframes sidebarIn {
    from { opacity: 0; transform: translateX(-30px); }
    to   { opacity: 1; transform: translateX(0); }
  }

  @keyframes panelRise {
    from { opacity: 0; transform: translateY(20px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  @keyframes godrayPulse {
    0%, 100% { opacity: 0.7; transform: scale(1); }
    50%      { opacity: 1;   transform: scale(1.06); }
  }
`;

export const animationClasses = css`
  .anim-fade  { animation: fadeIn 0.5s var(--ease) both; }
  .anim-rise  { animation: panelRise 0.6s var(--ease) both; }
  .anim-slide { animation: sidebarIn 0.9s var(--ease) both; }
`;
