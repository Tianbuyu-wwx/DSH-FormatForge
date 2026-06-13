// ============================================================
// Lit 响应式 i18n 指令
// ============================================================

import { directive, Directive, DirectiveParameters, Part } from 'lit/directive.js';
import { t } from './index.js';

class TDirective extends Directive {
  override update(_part: Part, [key, params]: DirectiveParameters<this>) {
    return this.render(key, params);
  }

  render(key: string, params?: Record<string, string | number>) {
    return t(key, params);
  }
}

export const T = directive(TDirective);