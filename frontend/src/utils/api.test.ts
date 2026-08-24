import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  clearHistory,
  configureApiKey,
  convertText,
  getHistory,
  isApiKeyConfigured,
} from './api.js';

function successfulResponse<T>(data: T) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ code: 200, msg: 'ok', data }),
  } as Response;
}

describe('API Key 请求认证', () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    sessionStorage.clear();
    configureApiKey('');
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  it('默认空配置不发送 Authorization 头', async () => {
    fetchMock.mockResolvedValue(successfulResponse({ items: [], total: 0 }));

    await getHistory();

    expect(isApiKeyConfigured()).toBe(false);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[1]?.headers).toBeUndefined();
  });

  it('为 GET 和 DELETE 请求添加 Bearer 头', async () => {
    configureApiKey('  phase-one-secret  ');
    fetchMock
      .mockResolvedValueOnce(successfulResponse({ items: [], total: 0 }))
      .mockResolvedValueOnce(successfulResponse(null));

    await getHistory();
    await clearHistory();

    expect(isApiKeyConfigured()).toBe(true);
    expect(fetchMock.mock.calls[0]?.[1]?.headers).toEqual({
      Authorization: 'Bearer phase-one-secret',
    });
    expect(fetchMock.mock.calls[1]?.[1]?.headers).toEqual({
      Authorization: 'Bearer phase-one-secret',
    });
  });

  it('为携带 FormData 的 POST 请求添加 Bearer 头且不覆盖 Content-Type', async () => {
    configureApiKey('phase-one-secret');
    fetchMock.mockResolvedValue(successfulResponse({
      resultId: 'result-1',
      fileName: 'text-input.txt',
      conversionType: 'text',
      outputFormat: 'text',
      confidence: 1,
      convertedContent: 'converted',
    }));

    await convertText('source', {
      conversionType: 'text',
      outputFormat: 'text',
      customPrompt: '',
    });

    const request = fetchMock.mock.calls[0]?.[1];
    expect(request?.method).toBe('POST');
    expect(request?.body).toBeInstanceOf(FormData);
    expect(request?.headers).toEqual({ Authorization: 'Bearer phase-one-secret' });
    expect((request?.headers as Record<string, string>)['Content-Type']).toBeUndefined();
  });

  it('空值会清除会话密钥', () => {
    configureApiKey('phase-one-secret');
    expect(sessionStorage.getItem('dft.apiKey')).toBe('phase-one-secret');

    configureApiKey('');

    expect(isApiKeyConfigured()).toBe(false);
    expect(sessionStorage.getItem('dft.apiKey')).toBeNull();
  });

  it('拒绝可能造成请求头注入的换行符', () => {
    expect(() => configureApiKey('valid\r\nInjected: true')).toThrow('不能包含换行符');
    expect(isApiKeyConfigured()).toBe(false);
  });
});
