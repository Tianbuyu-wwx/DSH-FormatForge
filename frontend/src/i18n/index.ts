// ============================================================
// i18n 语言包系统
// ============================================================

// 支持的语言
export type Lang = 'zh' | 'en';

// 翻译映射表类型
export type TranslationMap = Record<string, string>;

// 中文翻译
const zh: TranslationMap = {
  // 导航
  'nav.title': 'AI 数据转换器',
  'nav.history': '历史',
  'nav.compare': '对比预览',

  // 上传
  'upload.tab.file': '文件上传',
  'upload.tab.url': 'URL 输入',
  'upload.tab.text': '文本输入',
  'upload.dropzone': '拖拽文件到此处，或点击选择',
  'upload.supported': '支持格式',
  'upload.maxSize': '最大',
  'upload.fileCount': '已选择 {count} 个文件',
  'upload.addMore': '添加更多文件',
  'upload.urlPlaceholder': '输入网页 URL 或文件链接...',
  'upload.urlFetch': '获取并转换',
  'upload.textPlaceholder': '粘贴文本内容...',
  'upload.textChars': '已输入 {count} 字符',
  'upload.textConvert': '粘贴并转换',

  // 选项
  'options.title': '转换选项',
  'options.type': '转换类型',
  'options.format': '输出格式',
  'options.prompt': '自定义提示词',
  'options.promptPlaceholder': '输入自定义提示词（可选）...',
  'options.template': '输出模板',
  'options.noTemplate': '无模板',

  // 转换
  'convert.start': '开始转换',
  'convert.batch': '批量转换',
  'convert.retry': '重试',
  'convert.new': '新的转换',
  'convert.download': '下载结果',

  // 进度
  'progress.upload': '上传中...',
  'progress.parse': '解析中...',
  'progress.ocr': 'OCR 识别中...',
  'progress.convert': '转换中...',
  'progress.done': '完成',
  'progress.batch': '批量转换 {current}/{total}',

  // 结果
  'result.title': '转换结果',
  'result.confidence': '置信度',
  'result.strategy': '策略',
  'result.raw': '原始内容',
  'result.converted': '转换结果',
  'result.structured': '结构化数据',
  'result.logs': '处理日志',
  'result.export': '导出',
  'result.copy': '复制',
  'result.copied': '已复制',

  // 历史
  'history.title': '转换历史',
  'history.empty': '暂无历史记录',
  'history.loading': '加载中...',
  'history.clear': '清空历史',
  'history.clearConfirm': '确定要清空所有历史记录吗？',
  'history.delete': '删除',
  'history.justNow': '刚刚',
  'history.minutesAgo': '{n} 分钟前',
  'history.hoursAgo': '{n} 小时前',
  'history.daysAgo': '{n} 天前',

  // 对比
  'compare.title': '对比预览',
  'compare.source': '原始内容',
  'compare.markdown': 'Markdown',
  'compare.json': 'JSON',
  'compare.text': '纯文本',
  'compare.html': 'HTML',
  'compare.quality': '质量评分',

  // 质量
  'quality.grade.A': '优秀',
  'quality.grade.B': '良好',
  'quality.grade.C': '一般',
  'quality.grade.D': '较差',
  'quality.grade.F': '很差',
  'quality.textCoverage': '文本覆盖率',
  'quality.encoding': '编码质量',
  'quality.structure': '结构保留',
  'quality.table': '表格精度',
  'quality.completeness': '内容完整性',

  // 状态
  'status.success': '转换成功',
  'status.error': '转换失败',
  'status.warning': '警告',

  // 模板
  'template.openai': 'OpenAI Messages 格式',
  'template.rag': 'RAG 文档切片',
  'template.vector': '向量数据库导入',
  'template.langchain': 'LangChain Document',
  'template.summary': '智能摘要',
};

// 英文翻译
const en: TranslationMap = {
  'nav.title': 'AI Data Translator',
  'nav.history': 'History',
  'nav.compare': 'Compare',

  'upload.tab.file': 'File Upload',
  'upload.tab.url': 'URL Input',
  'upload.tab.text': 'Text Input',
  'upload.dropzone': 'Drag & drop files here, or click to select',
  'upload.supported': 'Supported formats',
  'upload.maxSize': 'Max',
  'upload.fileCount': '{count} files selected',
  'upload.addMore': 'Add more files',
  'upload.urlPlaceholder': 'Enter URL or file link...',
  'upload.urlFetch': 'Fetch & Convert',
  'upload.textPlaceholder': 'Paste text content...',
  'upload.textChars': '{count} characters',
  'upload.textConvert': 'Paste & Convert',

  'options.title': 'Conversion Options',
  'options.type': 'Conversion Type',
  'options.format': 'Output Format',
  'options.prompt': 'Custom Prompt',
  'options.promptPlaceholder': 'Enter custom prompt (optional)...',
  'options.template': 'Output Template',
  'options.noTemplate': 'No Template',

  'convert.start': 'Start Convert',
  'convert.batch': 'Batch Convert',
  'convert.retry': 'Retry',
  'convert.new': 'New Convert',
  'convert.download': 'Download Result',

  'progress.upload': 'Uploading...',
  'progress.parse': 'Parsing...',
  'progress.ocr': 'OCR processing...',
  'progress.convert': 'Converting...',
  'progress.done': 'Done',
  'progress.batch': 'Batch {current}/{total}',

  'result.title': 'Conversion Result',
  'result.confidence': 'Confidence',
  'result.strategy': 'Strategy',
  'result.raw': 'Raw Content',
  'result.converted': 'Converted',
  'result.structured': 'Structured Data',
  'result.logs': 'Processing Logs',
  'result.export': 'Export',
  'result.copy': 'Copy',
  'result.copied': 'Copied',

  'history.title': 'History',
  'history.empty': 'No history',
  'history.loading': 'Loading...',
  'history.clear': 'Clear History',
  'history.clearConfirm': 'Are you sure you want to clear all history?',
  'history.delete': 'Delete',
  'history.justNow': 'Just now',
  'history.minutesAgo': '{n} minutes ago',
  'history.hoursAgo': '{n} hours ago',
  'history.daysAgo': '{n} days ago',

  'compare.title': 'Compare Preview',
  'compare.source': 'Source',
  'compare.markdown': 'Markdown',
  'compare.json': 'JSON',
  'compare.text': 'Plain Text',
  'compare.html': 'HTML',
  'compare.quality': 'Quality Score',

  'quality.grade.A': 'Excellent',
  'quality.grade.B': 'Good',
  'quality.grade.C': 'Fair',
  'quality.grade.D': 'Poor',
  'quality.grade.F': 'Very Poor',
  'quality.textCoverage': 'Text Coverage',
  'quality.encoding': 'Encoding Quality',
  'quality.structure': 'Structure',
  'quality.table': 'Table Accuracy',
  'quality.completeness': 'Completeness',

  'status.success': 'Conversion successful',
  'status.error': 'Conversion failed',
  'status.warning': 'Warning',

  'template.openai': 'OpenAI Messages',
  'template.rag': 'RAG Chunks',
  'template.vector': 'Vector DB Import',
  'template.langchain': 'LangChain Document',
  'template.summary': 'Smart Summary',
};

// 所有语言包
const translations: Record<Lang, TranslationMap> = { zh, en };

// 当前语言（默认为中文）
let currentLang: Lang = 'zh';

// 检测浏览器语言
function detectLang(): Lang {
  if (typeof navigator !== 'undefined') {
    const navLang = navigator.language?.toLowerCase() || '';
    if (navLang.startsWith('zh')) return 'zh';
    if (navLang.startsWith('en')) return 'en';
  }
  return 'zh';
}

// 初始化
currentLang = detectLang();

// 翻译函数
export function t(key: string, params?: Record<string, string | number>): string {
  const map = translations[currentLang];
  let text = map[key] || key;
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      text = text.replace(`{${k}}`, String(v));
    });
  }
  return text;
}

// 获取/设置当前语言
export function getLang(): Lang {
  return currentLang;
}

export function setLang(lang: Lang): void {
  currentLang = lang;
  // 触发自定义事件以便组件重新渲染
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('langchange', { detail: { lang } }));
  }
}

export function toggleLang(): Lang {
  const next = currentLang === 'zh' ? 'en' : 'zh';
  setLang(next);
  return next;
}