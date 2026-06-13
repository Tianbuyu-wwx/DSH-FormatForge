// ============================================================
// API 客户端 - 封装后端接口调用 (v2.3)
// ============================================================

import type { ApiResponse, ConvertResult, ConversionType, OutputFormat, HistoryItem } from '../types/index.js';

const API_BASE = '/api/v2';

/** 通用 API 错误 */
export class ApiError extends Error {
  code: number;
  constructor(msg: string, code: number) {
    super(msg);
    this.code = code;
    this.name = 'ApiError';
  }
}

/** 通用 POST 请求 */
async function post<T>(path: string, body: FormData, signal?: AbortSignal): Promise<ApiResponse<T>> {
  const timeout = AbortSignal.timeout?.(120000) ?? undefined;
  const sig = signal ? (timeout ? AbortSignal.any([signal, timeout]) : signal) : timeout;

  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    body,
    signal: sig,
  });

  const json: ApiResponse<T> = await res.json();

  if (!res.ok || json.code !== 200) {
    throw new ApiError(json.msg || '请求失败', json.code || res.status);
  }

  return json;
}

/** 通用 GET 请求 */
async function get<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'GET',
    signal: AbortSignal.timeout?.(30000),
  });

  const json: ApiResponse<T> = await res.json();

  if (!res.ok || json.code !== 200) {
    throw new ApiError(json.msg || '请求失败', json.code || res.status);
  }

  return json;
}

/** 通用 DELETE 请求 */
async function del<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'DELETE',
    signal: AbortSignal.timeout?.(30000),
  });

  const json: ApiResponse<T> = await res.json();

  if (!res.ok || json.code !== 200) {
    throw new ApiError(json.msg || '请求失败', json.code || res.status);
  }

  return json;
}

// ==================== 类型定义 ====================

interface RawConvertData {
  resultId: string;
  fileName: string;
  conversionType: string;
  outputFormat: string;
  confidence: number;
  convertedContent: string;
  structuredData?: Record<string, unknown> | null;
  processingLogs?: Array<{ step: string; level: string; message: string }> | null;
  exportUrl?: string;
  decision?: Record<string, unknown> | null;
  aiCapabilities?: Record<string, unknown> | null;
  recommendation?: string;
}

function mapToConvertResult(raw: RawConvertData): ConvertResult {
  return {
    fileName: raw.fileName,
    fileSize: 0,
    fileType: raw.conversionType,
    outputFormat: raw.outputFormat,
    confidence: raw.confidence,
    parsedContent: '',
    convertedContent: raw.convertedContent || '',
    structuredData: raw.structuredData ?? undefined,
    processingLogs: (raw.processingLogs || []).map(log => ({
      level: (log.level as 'info' | 'warning' | 'error') || 'info',
      step: log.step || '',
      message: log.message || '',
    })),
    conversionDecision: {
      detectedFormat: raw.conversionType,
      recommendedStrategy: raw.conversionType,
      confidence: raw.confidence,
      fromCache: false,
    },
  };
}

// ==================== 转换 API ====================

/** 上传文件并转换 */
export async function uploadAndConvert(
  file: File,
  options: {
    conversionType: ConversionType;
    outputFormat: OutputFormat;
    customPrompt: string;
  },
  onProgress?: (phase: string, percent: number) => void,
  signal?: AbortSignal,
): Promise<ConvertResult> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('conversion_type', options.conversionType);
  formData.append('output_format', options.outputFormat);
  if (options.customPrompt) {
    formData.append('custom_prompt', options.customPrompt);
  }

  onProgress?.('upload', 10);
  await delay(200);
  onProgress?.('upload', 30);
  onProgress?.('parse', 50);

  const res = await post<RawConvertData>('/convert/upload', formData, signal);

  onProgress?.('convert', 80);
  await delay(300);
  onProgress?.('done', 100);

  return mapToConvertResult(res.data!);
}

// v2.3: URL 转换
export async function convertUrl(
  url: string,
  options: {
    conversionType: ConversionType;
    outputFormat: OutputFormat;
    customPrompt: string;
  },
  onProgress?: (phase: string, percent: number) => void,
): Promise<ConvertResult> {
  const formData = new FormData();
  formData.append('url', url);
  formData.append('conversion_type', options.conversionType);
  formData.append('output_format', options.outputFormat);
  if (options.customPrompt) formData.append('custom_prompt', options.customPrompt);

  onProgress?.('upload', 20);
  onProgress?.('parse', 50);
  const res = await post<RawConvertData>('/convert/url', formData);
  onProgress?.('convert', 80);
  await delay(200);
  onProgress?.('done', 100);
  return mapToConvertResult(res.data!);
}

// v2.3: 文本转换
export async function convertText(
  text: string,
  options: {
    conversionType: ConversionType;
    outputFormat: OutputFormat;
    customPrompt: string;
  },
  onProgress?: (phase: string, percent: number) => void,
): Promise<ConvertResult> {
  const formData = new FormData();
  formData.append('text', text);
  formData.append('conversion_type', options.conversionType);
  formData.append('output_format', options.outputFormat);
  if (options.customPrompt) formData.append('custom_prompt', options.customPrompt);

  onProgress?.('upload', 10);
  onProgress?.('parse', 50);
  const res = await post<RawConvertData>('/convert/text', formData);
  onProgress?.('convert', 80);
  await delay(200);
  onProgress?.('done', 100);
  return mapToConvertResult(res.data!);
}

// v2.3: 批量转换
export async function batchConvert(
  files: File[],
  options: {
    conversionType: ConversionType;
    outputFormat: OutputFormat;
  },
  onProgress?: (current: number, total: number, fileName: string) => void,
): Promise<ConvertResult[]> {
  const results: ConvertResult[] = [];

  for (let i = 0; i < files.length; i++) {
    onProgress?.(i + 1, files.length, files[i].name);
    try {
      const result = await uploadAndConvert(files[i], {
        ...options,
        customPrompt: '',
      });
      results.push(result);
    } catch (e) {
      results.push({
        fileName: files[i].name,
        fileSize: files[i].size,
        fileType: 'error',
        confidence: 0,
        parsedContent: '',
        convertedContent: '',
        processingLogs: [{ level: 'error', step: 'batch', message: String(e) }],
      });
    }
  }

  return results;
}

// ==================== 历史记录 API ====================

export async function getHistory(
  limit = 50,
  offset = 0,
  fileType?: string,
): Promise<{ items: HistoryItem[]; total: number }> {
  let path = `/history?limit=${limit}&offset=${offset}`;
  if (fileType) path += `&file_type=${encodeURIComponent(fileType)}`;
  const res = await get<{ items: HistoryItem[]; total: number }>(path);
  return res.data!;
}

export async function getHistoryDetail(resultId: string): Promise<ConvertResult> {
  const res = await get<RawConvertData>(`/history/${encodeURIComponent(resultId)}`);
  return mapToConvertResult(res.data!);
}

export async function deleteHistory(resultId: string): Promise<void> {
  await del(`/history/${encodeURIComponent(resultId)}`);
}

export async function clearHistory(): Promise<void> {
  await del('/history');
}

// ==================== 导出 ====================

export function getExportUrl(resultId: string, format = 'markdown'): string {
  return `${API_BASE}/export/${encodeURIComponent(resultId)}?format=${format}`;
}

// ==================== 工具函数 ====================

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}