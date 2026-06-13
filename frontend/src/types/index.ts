// ============================================================
// AI 数据转换器 - 类型定义
// ============================================================

/** 文件格式分类 */
export type FileCategory =
  | 'document'
  | 'spreadsheet'
  | 'image'
  | 'data'
  | 'email'
  | 'archive'
  | 'ebook'
  | 'vector';

/** 文件信息 */
export interface FileInfo {
  name: string;
  size: number;
  extension: string;
  category: FileCategory;
}

/** 转换类型 */
export type ConversionType =
  | 'auto'
  | 'text'
  | 'structured'
  | 'table'
  | 'image_desc'
  | 'ocr'
  | 'encoding';

/** 输出格式 */
export type OutputFormat = 'json' | 'markdown' | 'text' | 'html';

/** 转换阶段 */
export type ConvertPhase =
  | 'upload'
  | 'parse'
  | 'convert'
  | 'done';

/** 状态消息 */
export interface StatusMessage {
  id: number;
  message: string;
  type: 'info' | 'success' | 'error';
  timestamp: number;
}

/** 转换进度 */
export interface ProgressState {
  phase: ConvertPhase;
  percent: number;
}

/** 处理日志 */
export interface LogEntry {
  level: 'info' | 'warning' | 'error';
  step: string;
  message: string;
}

/** AI 能力和限制 */
export interface AICapabilities {
  provider: string;
  maxTokens: number;
  supportedFormats: string[];
}

/** AI 转换决策 */
export interface ConversionDecision {
  detectedFormat: string;
  recommendedStrategy: string;
  confidence: number;
  fromCache: boolean;
}

/** 转换结果 */
export interface ConvertResult {
  fileName: string;
  fileSize: number;
  fileType: string;
  outputFormat?: string;
  confidence: number;
  parsedContent: string;
  convertedContent: string;
  originalContent?: string;
  structuredData?: Record<string, unknown>;
  processingLogs?: LogEntry[];
  aiCapabilities?: AICapabilities;
  conversionDecision?: ConversionDecision;
}

/** API 响应 */
export interface ApiResponse<T = unknown> {
  code: number;
  msg: string;
  data: T;
}

/** 应用全局状态 */
export interface AppState {
  file: FileInfo | null;
  files: FileInfo[];                       // v2.3: 批量文件列表
  inputMode: InputMode;                    // v2.3: 输入模式
  urlInput: string;                        // v2.3: URL 输入
  textInput: string;                       // v2.3: 文本输入
  result: ConvertResult | null;
  results: ConvertResult[];                // v2.3: 批量结果
  status: StatusMessage | null;
  loading: boolean;
  progress: ProgressState;
  conversionType: ConversionType;
  outputFormat: OutputFormat;
  customPrompt: string;
  history: HistoryItem[];                  // v2.3: 历史记录
  historyLoading: boolean;                 // v2.3: 历史加载中
  showHistory: boolean;                    // v2.3: 是否显示历史面板
}

/** v2.3: 输入模式 */
export type InputMode = 'file' | 'url' | 'text';

/** v2.3: 历史记录项 */
export interface HistoryItem {
  id: number;
  result_id: string;
  file_name: string;
  file_size: number;
  file_type: string;
  conversion_type: string;
  output_format: string;
  confidence: number;
  strategy: string;
  from_cache: number;
  created_at: string;
}

