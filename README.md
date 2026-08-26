# DSH-FormatForge

**把任意文件拖进 DeepSeek Harness，立刻变成 AI 能读懂的数据。**

[![Version](https://img.shields.io/npm/v/@tianbuyu-wwx/dsh-formatforge)](https://www.npmjs.com/package/@tianbuyu-wwx/dsh-formatforge)
[![CI](https://github.com/Tianbuyu-wwx/DSH-FormatForge/actions/workflows/ci.yml/badge.svg)](https://github.com/Tianbuyu-wwx/DSH-FormatForge/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![Node](https://img.shields.io/badge/Node-22%2B-green)](https://nodejs.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

DSH-FormatForge 是一个 [DeepSeek Harness](https://github.com/deepseek-ai) 插件：把 PDF、DOCX、PPTX、XLSX、EML、EPUB、TOML 等 **30+ 种格式**锻造成 AI 模型可直接消化的结构化文本——直接**拖进 dsh 网页**，或在对话里粘贴文件路径。

> 项目前身是「Data-Format-Translator / AI 数据转换器」（Web 服务形态，冻结于 `v2.1.0-ci-green`）。
> v3.0 起完全重构为 dsh 插件：无 Web 界面、无内置 AI 客户端，专注「格式 → 结构化数据」这一层。

## 它解决什么问题

dsh 的 `read` 工具读 PDF/DOCX 这类二进制是乱码；官方附件通道只认图片。
装上 FormatForge 后：

```
拖 report.pdf 进 dsh 网页
  → 右下角提示「正在锻造…」
  → 数秒后对话收到通知：report.pdf 已锻好 (parser=pdf, confidence=0.95)
  → 直接基于这份文件继续提问
```

也可以不走拖拽：在对话里粘贴本地路径（`E:\docs\report.docx`），agent 会按约定先调用 `ff_translate` 再回答。

## 安装

### 前置

| 依赖 | 说明 |
|---|---|
| Python ≥ 3.10 | 运行转换内核；解释器探测顺序 `FF_PYTHON` → `<repo>/.venv-fg` → PATH |
| Node ≥ 22 | dsh web 本身的要求 |

### 方式一：从 npm 安装（推荐）

```bash
npx @deepseek-ai/dsh plugin add --profile web @tianbuyu-wwx/dsh-formatforge
# 重启 dsh web 生效
npx @deepseek-ai/dsh web
```

npm 包是插件壳。还需要一份可运行的 Python 内核（本仓库），两种给法：

```bash
# 给法 A：clone 本仓库并安装内核（推荐，含全部解析器依赖）
git clone https://github.com/Tianbuyu-wwx/DSH-FormatForge.git DSH-FormatForge
cd DSH-FormatForge
pip install -e .
# 告诉插件内核在哪（或用 FF_PYTHON 指向任一已装依赖的解释器）
setx FF_REPO_ROOT "D:\DSH-FormatForge"

# 给法 B：已有环境？只要它 import 得到 core/parsers：
setx FF_PYTHON "C:\path\to\your\python.exe"
```

### 方式二：从源码安装（开发）

```bash
git clone https://github.com/Tianbuyu-wwx/DSH-FormatForge.git DSH-FormatForge
cd DSH-FormatForge
pip install -e .

# link 插件壳到 profile（路径含中文时装完跑一次 junction 修复脚本）
npx @deepseek-ai/dsh plugin add --profile web ./packages/dsh-formatforge
python scripts/rebuild-plugin-junctions.py   # 重建 peer 依赖 junction
# 重启 dsh web → 启动日志看到 "tools registered: ff_translate, ff_formats"
```

## 使用

### 1. 网页拖拽（零学习成本）

把任何支持的文件拖进 dsh 网页任意位置：

- 非图片文件 → 自动上传并锻造，右下角 toast 显示进度与结果
- 图片 → 走 dsh 原生图片附件通道（不受影响）
- 转换完成后活跃会话收到轻量通知，附产物路径

产物落在收件箱目录（默认 `~/.dsh/formatforge/inbox/`）：
`<名字>.ff.md`（可直接阅读）+ `<名字>.ff.json`(完整协议数据)。

### 2. 对话内工具

| 工具 | 用途 |
|---|---|
| `ff_translate` | 转换：`path`（单个）/ `paths`（多个，支持 `*` glob）/ `text` 三选一；`format` json·markdown·html·text；`max_chars`/`offset` 分页；`quality` 附质量报告 |
| `ff_formats` | 列出支持的输入格式矩阵 |

### 3. CLI（脱离 dsh 也能用）

```bash
pip install -e .   # 之后
python -m formatforge translate document.pdf --format markdown
python -m formatforge translate --stdin-text < notes.txt
python -m formatforge formats      # 支持格式矩阵
```

stdout 输出单行协议 JSON（`{ok, code, data:{content, meta, quality?, enhance?}}`），日志走 stderr，退出码 0/2/3/4。

## enhance 协议 —— 模型增强交给会话本身

插件**不带任何 AI 客户端**。当纯规则转换不足以产出高质量结果时，返回里会出现：

```jsonc
"enhance": {
  "needed": true,
  "reason": "image_only",   // image_only | low_confidence | table_sparse
  "hint": "4/4 页无文字层（疑似扫描件）..."
}
```

SKILL.md 会指导当前会话模型：**按 hint 直接用自己的能力完成增强**（如基于 OCR 文本重建表格），不调用任何外部 API。模型永远与 dsh 会话一致，零密钥配置。

## 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `FF_REPO_ROOT` | 自动探测 | 含 `formatforge/ core/ parsers/` 的仓库根 |
| `FF_PYTHON` | 探测链兜底 PATH | 指定解释器（≥3.10） |
| `FF_MAX_BYTES` | 104857600 | 单文件上限（100MB） |
| `FF_TIMEOUT_S` | 120 | 单次转换超时（秒） |
| `FF_INBOX_NOTIFY` | true | 锻造完成后是否向会话注入轻量通知 |
| `OCR_ENABLED` | true | 启用本地 OCR（tesseract/paddleocr/easyocr 任一） |

## 架构

```
浏览器拖拽 ──POST /formatforge/upload──┐
                                       ▼
                          ~/.dsh/formatforge/inbox/
                                       │ fs watcher（去重·稳定检测）
对话路径 ── ff_translate ──┐            ▼
CLI     ── python -m … ──► formatforge 内核（30+ 解析器 × 7 策略）
                           │            ▼
                           │    协议 JSON {content, meta, quality?, enhance?}
                           ▼            
                    会话轻量通知（仅元数据，不注全文）
```

- **Python 内核**（`core/` + `parsers/` + `formatforge/`）：格式检测、管线编排、策略选择、质量评分
- **Node bundle**（`packages/dsh-formatforge/`）：工具注册（cordis）、client 拖拽模块、inbox watcher、HTTP 上传路由

## 开发

```bash
pip install -e ".[dev]"
pytest test/                                   # 444 passed
ruff check . && ruff format --check .
mypy core/ parsers/ formatforge/
node packages/dsh-formatforge/test-manifest.mjs   # bundle 契约自检
node packages/dsh-formatforge/test-local.mjs      # stub 环境 e2e（需本机 Python）
node packages/dsh-formatforge/test-inbox.mjs      # inbox watcher e2e
```

设计文档：[PLUGIN_PLAN.md](PLUGIN_PLAN.md)（插件化实施）· [EVOLUTION_PLAN.md](EVOLUTION_PLAN.md)（v0.4–v0.7 演进）· [ROADMAP.md](ROADMAP.md)（后续计划）

## 已知限制

- 扫描件 PDF 无文字层时依赖本机 OCR 引擎；都没有则返回 `enhance=image_only` 提示由会话模型兜底
- Windows 下以 `link:` 方式安装的插件需要 `rebuild-plugin-junctions.py`（pnpm 重装后复发）
- 宿主升级可能改变 client 模块内部契约——本插件带特征检测，失败时静默降级为纯路径模式

## License

MIT
