// ============================================================
// 工具函数：文件大小格式化、图标映射、格式分类
// ============================================================

import type { FileCategory } from '../types/index.js';
import type { IconName } from '../components/ui/icon.js';

// ========== 文件大小 ==========

/** 格式化文件大小为人类可读字符串 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// ========== 文件图标 ==========

const ICON_MAP: Record<string, IconName> = {
  '.ppt': 'file-spreadsheet', '.pptx': 'file-spreadsheet',
  '.pdf': 'file',
  '.doc': 'file-text', '.docx': 'file-text',
  '.txt': 'file-text', '.rtf': 'file-text',
  '.xls': 'file-spreadsheet', '.xlsx': 'file-spreadsheet', '.csv': 'file-spreadsheet',
  '.jpg': 'file-image', '.jpeg': 'file-image', '.png': 'file-image', '.gif': 'file-image',
  '.webp': 'file-image', '.bmp': 'file-image', '.tiff': 'file-image',
  '.json': 'file-code', '.xml': 'file-code', '.yaml': 'file-code', '.yml': 'file-code', '.toml': 'file-code',
  '.html': 'file-code', '.htm': 'file-code',
  '.md': 'file-text', '.markdown': 'file-text',
  '.zip': 'file', '.7z': 'file', '.rar': 'file',
  '.odt': 'file', '.ods': 'file-spreadsheet', '.odp': 'file-spreadsheet',
  '.eml': 'file', '.msg': 'file',
  '.epub': 'file',
  '.svg': 'file-image',
  '.srt': 'file-text', '.vtt': 'file-text',
  '.sql': 'file-code',
  '.tex': 'file-text', '.latex': 'file-text', '.ltx': 'file-text',
  '.wav': 'file', '.mp3': 'file', '.flac': 'file', '.ogg': 'file', '.m4a': 'file', '.aiff': 'file', '.aif': 'file',
};

export function getFileIcon(ext: string): IconName {
  return ICON_MAP[ext.toLowerCase()] ?? 'file';
}

// ========== 格式分类 ==========

const CATEGORY_MAP: Record<string, FileCategory> = {
  '.pdf': 'document', '.doc': 'document', '.docx': 'document',
  '.txt': 'document', '.rtf': 'document', '.md': 'document', '.markdown': 'document',
  '.odt': 'document', '.odp': 'document',
  '.xls': 'spreadsheet', '.xlsx': 'spreadsheet', '.csv': 'spreadsheet', '.ods': 'spreadsheet',
  '.jpg': 'image', '.jpeg': 'image', '.png': 'image', '.gif': 'image',
  '.webp': 'image', '.bmp': 'image', '.tiff': 'image',
  '.svg': 'vector',
  '.json': 'data', '.xml': 'data', '.yaml': 'data', '.yml': 'data', '.toml': 'data',
  '.html': 'data', '.htm': 'data',
  '.eml': 'email', '.msg': 'email',
  '.epub': 'ebook',
  '.zip': 'archive', '.7z': 'archive', '.rar': 'archive',
};

export function getFileCategory(ext: string): FileCategory {
  return CATEGORY_MAP[ext.toLowerCase()] ?? 'document';
}

// ========== 允许的格式列表 ==========

export const ALLOWED_EXTENSIONS = [
  '.ppt', '.pptx', '.pdf', '.doc', '.docx',
  '.txt', '.rtf', '.md', '.markdown',
  '.xls', '.xlsx', '.csv',
  '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.svg',
  '.json', '.xml', '.yaml', '.yml', '.toml', '.html', '.htm',
  '.odt', '.ods', '.odp',
  '.eml', '.msg', '.epub',
  '.zip', '.7z', '.rar',
  '.srt', '.vtt', '.tex', '.latex', '.ltx', '.sql',
  '.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aiff', '.aif',
];

// ========== 大小限制 ==========

const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.svg']);
const AUDIO_EXTS = new Set(['.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aiff', '.aif']);

export const SIZE_LIMITS = {
  image: 20 * 1024 * 1024,   // 20MB
  audio: 100 * 1024 * 1024,  // 100MB
  default: 50 * 1024 * 1024, // 50MB
} as const;

export function getMaxSize(ext: string): number {
  if (IMAGE_EXTS.has(ext.toLowerCase())) return SIZE_LIMITS.image;
  if (AUDIO_EXTS.has(ext.toLowerCase())) return SIZE_LIMITS.audio;
  return SIZE_LIMITS.default;
}

export function getSizeLabel(ext: string): string {
  if (IMAGE_EXTS.has(ext.toLowerCase())) return '20MB';
  if (AUDIO_EXTS.has(ext.toLowerCase())) return '100MB';
  return '50MB';
}

// ========== 格式分类汇总 ==========

export interface FormatCategoryGroup {
  label: string;
  formats: string;
}

export const FORMAT_CATEGORIES: FormatCategoryGroup[] = [
  { label: '文档', formats: 'PDF, PPTX, DOCX, TXT, MD, RTF, ODT, ODP, LaTeX' },
  { label: '表格', formats: 'XLSX, CSV, ODS, SQL' },
  { label: '图片', formats: 'JPG, PNG, GIF, WEBP, BMP, TIFF, SVG' },
  { label: '数据', formats: 'JSON, XML, YAML, TOML' },
  { label: '字幕', formats: 'SRT, VTT' },
  { label: '音频', formats: 'WAV, MP3, FLAC, OGG, M4A, AIFF' },
  { label: '其他', formats: 'EML, MSG, EPUB, ZIP, 7Z, RAR, HTML' },
];