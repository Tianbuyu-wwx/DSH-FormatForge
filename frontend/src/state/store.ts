// ============================================================
// 响应式全局状态管理
// ============================================================
// 基于发布-订阅模式的轻量级状态管理，与 Lit 原生集成

import type { AppState, ConvertResult, FileInfo, StatusMessage, ProgressState, ConversionType, OutputFormat, InputMode, HistoryItem } from '../types/index.js';

type StateListener = (state: AppState) => void;

/** 创建初始状态快照 */
function createInitialState(): AppState {
  return {
    file: null,
    files: [],
    inputMode: 'file',
    urlInput: '',
    textInput: '',
    result: null,
    results: [],
    status: null,
    loading: false,
    progress: { phase: 'upload', percent: 0 },
    conversionType: 'auto',
    outputFormat: 'json',
    customPrompt: '',
    history: [],
    historyLoading: false,
    showHistory: false,
  };
}

class Store {
  private _state: AppState;
  private _listeners: Set<StateListener> = new Set();
  private _statusId = 0;

  constructor() {
    this._state = createInitialState();
  }

  /** 获取当前状态的只读快照 */
  get state(): Readonly<AppState> {
    return this._state;
  }

  /** 订阅状态变更 */
  subscribe(listener: StateListener): () => void {
    this._listeners.add(listener);
    return () => this._listeners.delete(listener);
  }

  /** 发放变更通知 */
  private _notify() {
    this._listeners.forEach(fn => fn(this._state));
  }

  // ==================== 文件状态 ====================

  setFile(file: FileInfo | null) {
    this._state = { ...this._state, file };
    this._notify();
  }

  clearFile() {
    this.setFile(null);
  }

  // v2.3: 批量文件
  addFiles(newFiles: FileInfo[]) {
    this._state = { ...this._state, files: [...this._state.files, ...newFiles] };
    if (newFiles.length > 0) this._state = { ...this._state, file: newFiles[0] };
    this._notify();
  }

  setFiles(files: FileInfo[]) {
    this._state = { ...this._state, files };
    this._notify();
  }

  setBatchFiles(files: FileInfo[] | undefined) {
    this._state = { ...this._state, files: files || [] };
    this._notify();
  }

  removeFile(index: number) {
    const updated = this._state.files.filter((_, i) => i !== index);
    this._state = { ...this._state, files: updated, file: updated[0] || null };
    this._notify();
  }

  clearFiles() {
    this._state = { ...this._state, files: [], file: null };
    this._notify();
  }

  // v2.3: 输入模式
  setInputMode(mode: InputMode) {
    this._state = { ...this._state, inputMode: mode };
    this._notify();
  }

  setUrlInput(url: string) {
    this._state = { ...this._state, urlInput: url };
    this._notify();
  }

  setTextInput(text: string) {
    this._state = { ...this._state, textInput: text };
    this._notify();
  }

  // ==================== 转换选项 ====================

  setConversionType(type: ConversionType) {
    this._state = { ...this._state, conversionType: type };
    this._notify();
  }

  setOutputFormat(format: OutputFormat) {
    this._state = { ...this._state, outputFormat: format };
    this._notify();
  }

  setCustomPrompt(prompt: string) {
    this._state = { ...this._state, customPrompt: prompt };
    this._notify();
  }

  // ==================== 加载与进度 ====================

  setLoading(loading: boolean) {
    this._state = { ...this._state, loading };
    this._notify();
  }

  setProgress(phase: ProgressState['phase'], percent: number) {
    this._state = { ...this._state, progress: { phase, percent } };
    this._notify();
  }

  // ==================== 结果 ====================

  setResult(result: ConvertResult | null) {
    this._state = { ...this._state, result };
    this._notify();
  }

  clearResult() {
    this.setResult(null);
  }

  // v2.3: 批量结果
  setResults(results: ConvertResult[]) {
    this._state = { ...this._state, results };
    this._notify();
  }

  appendResult(result: ConvertResult) {
    this._state = { ...this._state, results: [...this._state.results, result] };
    this._notify();
  }

  clearResults() {
    this._state = { ...this._state, results: [] };
    this._notify();
  }

  // ==================== Toast 通知 ====================

  showStatus(message: string, type: StatusMessage['type'] = 'info') {
    this._statusId++;
    const status: StatusMessage = {
      id: this._statusId,
      message,
      type,
      timestamp: Date.now(),
    };
    this._state = { ...this._state, status };
    this._notify();
  }

  clearStatus() {
    this._state = { ...this._state, status: null };
    this._notify();
  }

  // ==================== v2.3: 历史记录 ====================

  setHistory(history: HistoryItem[]) {
    this._state = { ...this._state, history };
    this._notify();
  }

  setHistoryLoading(loading: boolean) {
    this._state = { ...this._state, historyLoading: loading };
    this._notify();
  }

  toggleHistory(show?: boolean) {
    this._state = {
      ...this._state,
      showHistory: show !== undefined ? show : !this._state.showHistory
    };
    this._notify();
  }

  async viewHistory(resultId: string) {
    const { getHistoryDetail } = await import('../utils/api.js');
    try {
      const result = await getHistoryDetail(resultId);
      this.setResult(result);
    } catch {
      this.showStatus('加载历史记录失败', 'error');
    }
  }

  // ==================== 重置 ====================

  reset() {
    this._state = createInitialState();
    this._notify();
  }
}

/** 全局唯一 Store 实例 */
export const store = new Store();