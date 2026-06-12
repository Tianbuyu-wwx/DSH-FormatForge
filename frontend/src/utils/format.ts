// ============================================================
// 工具函数：文件大小格式化、图标映射、格式分类
// ============================================================

import type { FileCategory } from '../types/index.js';

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

const ICON_MAP: Record<string, string> = {
  '.ppt': '📊', '.pptx': '📊',
  '.pdf': '📄',
  '.doc': '📝', '.docx': '📝',
  '.txt': '📝', '.rtf': '📝',
  '.xls': '📈', '.xlsx': '📈', '.csv': '📈',
  '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️',
  '.webp': '🖼️', '.bmp': '🖼️', '.tiff': '🖼️',
  '.json': '📋', '.xml': '📋', '.yaml': '📋', '.yml': '📋', '.toml': '📋',
  '.html': '🌐', '.htm': '🌐',
  '.md': '📖', '.markdown': '📖',
  '.zip': '📦', '.7z': '📦', '.rar': '📦',
  '.odt': '📄', '.ods': '📊', '.odp': '📊',
  '.eml': '✉️', '.msg': '✉️',
  '.epub': '📚',
  '.svg': '🎨',
};

export function getFileIcon(ext: string): string {
  return ICON_MAP[ext.toLowerCase()] ?? '📄';
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
];

// ========== 大小限制 ==========

/** 图片/矢量图格式扩展名 */
const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.svg']);

export const SIZE_LIMITS = {
  image: 20 * 1024 * 1024,   // 20MB
  default: 50 * 1024 * 1024, // 50MB
} as const;

export function getMaxSize(ext: string): number {
  return IMAGE_EXTS.has(ext.toLowerCase()) ? SIZE_LIMITS.image : SIZE_LIMITS.default;
}

export function getSizeLabel(ext: string): string {
  return IMAGE_EXTS.has(ext.toLowerCase()) ? '20MB' : '50MB';
}

// ========== 格式分类汇总 ==========

export interface FormatCategoryGroup {
  label: string;
  formats: string;
}

export const FORMAT_CATEGORIES: FormatCategoryGroup[] = [
  { label: '文档', formats: 'PDF, PPTX, DOCX, TXT, MD, RTF, ODT, ODP' },
  { label: '表格', formats: 'XLSX, CSV, ODS' },
  { label: '图片', formats: 'JPG, PNG, GIF, WEBP, BMP, TIFF, SVG' },
  { label: '数据', formats: 'JSON, XML, YAML, TOML' },
  { label: '邮件', formats: 'EML, MSG' },
  { label: '其他', formats: 'EPUB, ZIP, 7Z, RAR, HTML' },
];