// ============================================================
// <app-result> 单元测试 — 覆盖渲染逻辑
// ============================================================

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import './app-result.js';
import { store } from '../state/store.js';
import type { ConvertResult } from '../types/index.js';

describe.sequential('app-result 渲染逻辑', () => {
  let container: HTMLElement;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    store.reset();
  });

  afterEach(() => {
    container.remove();
    store.reset();
  });

  async function mountWithResult(result: ConvertResult | null): Promise<HTMLElement> {
    if (result) store.setResult(result);
    container.innerHTML = '<app-result></app-result>';
    const el = container.querySelector('app-result')!;
    await (el as any).updateComplete;
    await new Promise(r => setTimeout(r, 10));
    return el;
  }

  function makeResult(overrides: Partial<ConvertResult> = {}): ConvertResult {
    return {
      fileName: 'test.txt',
      fileSize: 1024,
      fileType: 'txt',
      confidence: 0.95,
      parsedContent: 'parsed',
      convertedContent: 'converted',
      ...overrides,
    };
  }

  // ===== 空状态测试 =====

  it('无结果时应显示"等待转换"占位', async () => {
    const el = await mountWithResult(null);
    const shadow = el.shadowRoot!;

    const tabs = shadow.querySelectorAll('.tab');
    expect(tabs.length).toBe(3);
    expect(tabs[0]!.textContent!.trim()).toBe('内容');
    expect(tabs[1]!.textContent!.trim()).toBe('结构化');
    expect(tabs[2]!.textContent!.trim()).toBe('日志');

    const emptyState = shadow.querySelector('.empty-state');
    expect(emptyState).not.toBeNull();
    expect(emptyState!.querySelector('.empty-title')!.textContent).toBe('等待转换');
    expect(emptyState!.querySelector('.empty-desc')!.textContent).toContain('上传文件');
  });

  it('空状态下标签栏始终可见', async () => {
    const el = await mountWithResult(null);
    const shadow = el.shadowRoot!;
    expect(shadow.querySelector('.result-wrap')).not.toBeNull();
    expect(shadow.querySelector('.tabs')).not.toBeNull();
  });

  // ===== 有结果状态测试 =====

  it('有结果时应显示元数据标签和转换内容', async () => {
    const mockResult = makeResult({
      convertedContent: '{"key": "value"}',
      outputFormat: 'json',
      conversionDecision: {
        detectedFormat: 'json',
        recommendedStrategy: 'structured',
        confidence: 0.95,
        fromCache: false,
      },
      structuredData: { key: 'value' },
      processingLogs: [{ level: 'info', step: 'parse', message: '解析完成' }],
    });

    const el = await mountWithResult(mockResult);
    const shadow = el.shadowRoot!;

    expect(shadow.querySelector('.empty-state')).toBeNull();

    const metaTags = shadow.querySelectorAll('.meta-tag');
    expect(metaTags.length).toBeGreaterThan(0);

    const tagTexts = Array.from(metaTags).map(t => t.textContent);
    expect(tagTexts.some(t => t!.includes('策略'))).toBe(true);
    expect(tagTexts.some(t => t!.includes('95%'))).toBe(true);
    expect(tagTexts.some(t => t!.includes('格式'))).toBe(true);

    const contentBox = shadow.querySelector('.content-box');
    expect(contentBox).not.toBeNull();
    expect(contentBox!.textContent).toContain('key');

    const actions = shadow.querySelectorAll('.actions .btn-icon');
    expect(actions.length).toBeGreaterThanOrEqual(2);
    expect(Array.from(actions).some(a => a.textContent!.includes('复制'))).toBe(true);
    expect(Array.from(actions).some(a => a.textContent!.includes('下载'))).toBe(true);
  });

  it('缓存命中时应显示缓存标签', async () => {
    const mockResult = makeResult({
      convertedContent: 'cached content',
      outputFormat: 'json',
      conversionDecision: {
        detectedFormat: 'txt',
        recommendedStrategy: 'text',
        confidence: 0.88,
        fromCache: true,
      },
    });

    const el = await mountWithResult(mockResult);
    const shadow = el.shadowRoot!;
    const metaTags = Array.from(shadow.querySelectorAll('.meta-tag'));
    expect(metaTags.some(t => t.textContent!.includes('缓存'))).toBe(true);
    expect(metaTags.some(t => t.classList.contains('accent'))).toBe(true);
  });

  // ===== 标签切换测试 =====

  it('点击"结构化"标签应切换到结构化视图', async () => {
    const mockResult = makeResult({
      convertedContent: '{"a":1}',
      outputFormat: 'json',
      structuredData: { a: 1, b: 2 },
    });

    const el = await mountWithResult(mockResult);
    const shadow = el.shadowRoot!;
    const structuredTab = Array.from(shadow.querySelectorAll('.tab')).find(
      t => t.textContent!.trim() === '结构化'
    ) as HTMLElement;

    structuredTab.click();
    await (el as any).updateComplete;

    expect(structuredTab.classList.contains('active')).toBe(true);
    const contentBox = shadow.querySelector('.content-box');
    expect(contentBox).not.toBeNull();
    expect(contentBox!.textContent).toContain('"a": 1');
  });

  it('点击"日志"标签应切换到日志视图', async () => {
    const mockResult = makeResult({
      convertedContent: 'test',
      outputFormat: 'json',
      processingLogs: [
        { level: 'info', step: 'upload', message: '上传成功' },
        { level: 'info', step: 'convert', message: '转换完成' },
      ],
    });

    const el = await mountWithResult(mockResult);
    const shadow = el.shadowRoot!;
    const logsTab = Array.from(shadow.querySelectorAll('.tab')).find(
      t => t.textContent!.trim() === '日志'
    ) as HTMLElement;

    logsTab.click();
    await (el as any).updateComplete;

    expect(logsTab.classList.contains('active')).toBe(true);
    const logItems = shadow.querySelectorAll('.log-item');
    expect(logItems.length).toBe(2);
    expect(logItems[0]!.textContent).toContain('upload');
    expect(logItems[1]!.textContent).toContain('convert');
  });

  // ===== 边界条件测试 =====

  it('转换内容为空时应显示"无内容"', async () => {
    const mockResult = makeResult({ convertedContent: '' });

    const el = await mountWithResult(mockResult);
    const shadow = el.shadowRoot!;
    const contentBox = shadow.querySelector('.content-box');
    expect(contentBox).not.toBeNull();
    expect(contentBox!.textContent).toContain('无内容');
  });

  it('无结构化数据时应显示空提示', async () => {
    const mockResult = makeResult({ convertedContent: 'text' });

    const el = await mountWithResult(mockResult);
    const shadow = el.shadowRoot!;
    const structuredTab = Array.from(shadow.querySelectorAll('.tab')).find(
      t => t.textContent!.trim() === '结构化'
    ) as HTMLElement;

    structuredTab.click();
    await (el as any).updateComplete;

    const empty = shadow.querySelector('.empty');
    expect(empty).not.toBeNull();
    expect(empty!.textContent).toContain('无结构化数据');
  });

  it('无处理日志时应显示空提示', async () => {
    const mockResult = makeResult({
      convertedContent: 'text',
      processingLogs: [],
    });

    const el = await mountWithResult(mockResult);
    const shadow = el.shadowRoot!;
    const logsTab = Array.from(shadow.querySelectorAll('.tab')).find(
      t => t.textContent!.trim() === '日志'
    ) as HTMLElement;

    logsTab.click();
    await (el as any).updateComplete;

    const empty = shadow.querySelector('.empty');
    expect(empty).not.toBeNull();
    expect(empty!.textContent).toContain('无处理日志');
  });

  // ===== 组件销毁测试 =====

  it('组件移除时应取消 store 订阅', async () => {
    const el = await mountWithResult(null);
    expect(() => el.remove()).not.toThrow();
  });
});
