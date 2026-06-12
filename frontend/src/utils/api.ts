// ============================================================
// API 客户端 - 封装后端接口调用
// ============================================================

import type { ApiResponse, ConvertResult, ConversionType, OutputFormat } from '../types/index.js';

const API_BASE = '/api/v1';

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
async function post<T>(path: string, body: FormData): Promise<ApiResponse<T>> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    body,
  });

  const json: ApiResponse<T> = await res.json();

  if (!res.ok || json.code !== 200) {
    throw new ApiError(json.msg || '请求失败', json.code || res.status);
  }

  return json;
}

/** 后端返回的原始转换结果数据 */
interface RawConvertData {
  resultId: string;
  fileName: string;
  conversionType: string;
  outputFormat: string;
  confidence: number;
  convertedContent: string;
  structuredData?: Record<string, unknown> | null;
  processingLogs?: Array<{
    step: string;
    level: string;
    message: string;
  }> | null;
  exportUrl?: string;
}

/** 将后端原始数据映射为前端 ConvertResult 类型 */
function mapToConvertResult(raw: RawConvertData): ConvertResult {
  return {
    fileName: raw.fileName,
    fileSize: 0,
    fileType: raw.conversionType,
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

/**
 * 上传文件并执行自动转换
 * POST /api/v1/convert/auto
 */
export async function uploadAndConvert(
  file: File,
  options: {
    conversionType: ConversionType;
    outputFormat: OutputFormat;
    customPrompt: string;
  },
  onProgress?: (phase: string, percent: number) => void,
): Promise<ConvertResult> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('fileType', 'auto');
  formData.append('conversionType', options.conversionType);
  formData.append('outputFormat', options.outputFormat);
  if (options.customPrompt) {
    formData.append('customPrompt', options.customPrompt);
  }

  // 模拟上传进度
  onProgress?.('upload', 10);
  await delay(200);
  onProgress?.('upload', 30);

  // 实际请求
  onProgress?.('parse', 50);
  const res = await post<RawConvertData>('/convert/auto', formData);

  onProgress?.('convert', 80);
  await delay(300);
  onProgress?.('done', 100);

  return mapToConvertResult(res.data!);
}

/** 延迟工具函数 */
function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}