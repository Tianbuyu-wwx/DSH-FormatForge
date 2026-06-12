// ============================================================
// 响应式全局状态管理
// ============================================================
// 基于发布-订阅模式的轻量级状态管理，与 Lit 原生集成

import type { AppState, ConvertResult, FileInfo, StatusMessage, ProgressState, ConversionType, OutputFormat } from '../types/index.js';

type StateListener = (state: AppState) => void;

/** 创建初始状态快照 */
function createInitialState(): AppState {
  return {
    file: null,
    result: null,
    status: null,
    loading: false,
    progress: { phase: 'upload', percent: 0 },
    conversionType: 'auto',
    outputFormat: 'json',
    customPrompt: '',
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

  // ==================== 重置 ====================

  reset() {
    this._state = createInitialState();
    this._notify();
  }
}

/** 全局唯一 Store 实例 */
export const store = new Store();