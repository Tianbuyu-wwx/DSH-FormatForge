# AI 数据转换器

> 自动将各种格式数据转换为 AI 可识别的标准化数据

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## 目录

- [项目简介](#项目简介)
- [核心功能](#核心功能)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 文档](#api-文档)
- [项目结构](#项目结构)
- [测试](#测试)
- [许可证](#许可证)

---

## 项目简介

AI 数据转换器是一个智能数据格式转换服务，支持将 **PPT、PDF、Word、Excel、CSV、图片、TXT、HTML、压缩包** 等多种文件格式转换为 AI 模型可识别的标准化数据（JSON / Markdown / HTML / 纯文本）。

项目采用 **FastAPI** 构建高性能后端，提供友好的 **Web 前端界面** 和完整的 **RESTful API**，同时支持 AI 增强转换（集成 MiniMax / OpenAI / 智谱等 AI 服务），可自动发现目标 AI 的能力并进行针对性转换。

## 核心功能

### 多格式文件解析（30+ 格式）
| 分类 | 格式 |
|------|------|
| 文档 | PDF, DOCX, PPTX, TXT, MD, RTF, ODT, ODP |
| 表格 | XLSX, CSV, ODS |
| 图片 | JPG/JPEG, PNG, GIF, WEBP, BMP, TIFF, SVG |
| 数据 | JSON, XML, YAML, TOML |
| 邮件 | EML, MSG |
| 电子书 | EPUB |
| 压缩包 | ZIP, 7z, RAR |
| 其他 | HTML |

### 智能数据转换
- 自动检测输入文件格式（魔数 + 扩展名 + 内容分析）
- 支持 7 种转换类型：自动检测、纯文本提取、结构化数据、表格提取、图片描述、OCR 文字识别、编码修复
- 4 种输出格式：JSON / Markdown / HTML / 纯文本
- AI 增强转换：自动发现目标 AI 能力（多模态、输入类型、上下文长度等），选择最优转换策略
- 自定义转换指令（Prompt）

### Web 前端界面（Lit + TypeScript + TailwindCSS）
- 拖拽上传文件（弹性缩放动画 + "松开上传"提示）
- 视频背景（渐变回退 + 暗角遮罩 + 光晕点缀）
- 格式分类标签（6 大分类、34 种格式）
- SVG 环形进度条 + 阶段文字提示
- 结果标签页展示（转换内容 / 结构化数据 / 处理日志）
- Toast 通知（右上角浮动，带滑入/滑出动画）
- 按类型差异化大小限制（图片 20MB / 其他 50MB）

### RESTful API
- **v1 接口**（兼容旧版）：文件上传解析、转换执行、结果查询与导出
- **v2 接口**（新架构）：统一转换入口，支持文件/URL/原始数据输入，支持目标 AI 能力发现
- **AI 能力发现接口**：探测目标 AI 端点能力

### 高级特性
- OCR 文字识别（支持中文、英文等多语言）
- 批量文件转换
- 内容缓存（TLD 过期 + LRU 淘汰 + 磁盘持久化）
- 敏感信息脱敏
- 请求频率限制与请求体积限制
- 结构化日志（JSON 格式 + TraceID 全链路追踪）
- 并发安全（线程锁保护的缓存与单例）

## 技术栈

| 类别 | 技术 |
|------|------|
| 后端框架 | FastAPI 0.109 |
| 运行时 | Python 3.10+, Uvicorn 0.27 |
| 数据模型 | Pydantic v2 |
| AI 服务 | OpenAI SDK（兼容 MiniMax、智谱等） |
| PDF 解析 | PyPDF2, pdfplumber |
| 图片处理 | Pillow |
| PPT 解析 | python-pptx |
| 文件上传 | python-multipart |
| 编码检测 | chardet（内置） |
| HTTP 客户端 | httpx, requests |
| 前端 | Lit Web Components + Vite + TailwindCSS |
| 测试 | pytest, ruff |

## 快速开始

### 环境要求

- Python 3.10+
- pip / poetry

### 安装

```bash
# 1. 克隆项目
git clone <your-repo-url>
cd 数据格式转换器

# 2. 创建虚拟环境（推荐）
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt
```

### 配置

创建 `.env` 文件（基于 `.env.example`）：

```ini
# AI 服务提供商: minimax / openai / zhipu
AI_PROVIDER=minimax

# MiniMax 配置
MINIMAX_API_KEY=your_minimax_api_key
MINIMAX_GROUP_ID=your_group_id

# 或 OpenAI 配置
# OPENAI_API_KEY=your_openai_api_key

# 应用配置
APP_HOST=0.0.0.0
APP_PORT=8000
DEBUG=true
```

> **注意**：若不配置 AI 密钥，项目仍可作为普通的文件格式转换器使用，只是无法使用 AI 增强功能。

### 运行

```bash
python main.py
```

服务启动后：
- 前端页面：http://localhost:8000/static/index.html
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

### 运行测试

```bash
# 运行所有测试
pytest test/

# 运行特定测试
pytest test/unit/test_txt_parser.py -v
pytest test/integration/test_api.py -v

# 带覆盖率报告
pytest --cov=. test/
```

## 配置说明

通过 `.env` 文件或环境变量配置，详见 [core/config.py](core/config.py)。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `APP_HOST` | `0.0.0.0` | 服务监听地址 |
| `APP_PORT` | `8000` | 服务端口 |
| `DEBUG` | `false` | 调试模式（开启热重载） |
| `AI_PROVIDER` | `minimax` | AI 服务提供商 |
| `MAX_FILE_SIZE` | `52428800` (50MB) | 单文件上传大小限制 |
| `MAX_REQUEST_SIZE` | `104857600` (100MB) | 请求体积限制 |
| `RATE_LIMIT_MAX` | `60` | 每分钟最大请求数 |
| `CACHE_TTL` | `3600` | 转换结果缓存过期时间（秒） |

## API 文档

### v1 接口（兼容旧版）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/convert/upload` | 上传文件并解析 |
| POST | `/api/v1/convert/run` | 执行数据转换 |
| POST | `/api/v1/convert/auto` | 上传文件直接转换 |
| GET | `/api/v1/convert/result/{result_id}` | 获取转换结果 |
| GET | `/api/v1/convert/status/{parse_id}` | 查询解析状态 |
| GET | `/api/v1/convert/export/{result_id}` | 导出转换结果 |
| POST | `/api/v1/ai/discover` | AI 能力发现 |
| GET | `/api/v1/ai/providers` | 列出支持的 AI 提供商 |

### v2 接口（新架构）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v2/convert` | 统一转换（支持文件/URL/原始数据） |

### 基础接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务信息 |
| GET | `/health` | 健康检查 |
| GET | `/debug/config` | 调试配置（非敏感信息） |

## 项目结构

```
数据格式转换器/
├── main.py                  # 应用入口：FastAPI 初始化、中间件、路由注册
├── requirements.txt         # Python 依赖
├── .env                     # 环境配置（不提交到版本库）
├── .gitignore
├── LICENSE                  # MIT 许可证
├── README.md
│
├── core/                    # 核心逻辑
│   ├── config.py            # 应用配置（Pydantic Settings）
│   ├── models.py            # 数据模型 & 枚举定义
│   ├── utils.py             # 工具函数
│   ├── security.py          # 安全：文件类型校验、敏感信息过滤
│   ├── middleware.py        # 中间件：频率限制、请求体积限制
│   ├── di.py                # 依赖注入（全局单例）
│   │
│   ├── converter_engine.py  # 核心转换引擎（智能决策、AI 增强）
│   ├── conversion_strategies.py  # 转换策略注册与选择
│   ├── decision_engine.py   # 转换决策引擎
│   ├── format_detector.py   # 格式自动检测
│   ├── input_adapters.py    # 多源输入适配器（文件/URL/原始数据）
│   ├── file_parser.py       # 文件解析器总入口
│   │
│   ├── ai_client.py         # AI 客户端封装
│   ├── ai_discovery.py      # AI 能力发现
│   ├── ai_presets.py        # AI 提供商预设
│   ├── ai_prompt_manager.py # AI 提示词管理
│   │
│   ├── content_cache.py     # 内容缓存（TTL + 持久化）
│   ├── ocr_engine.py        # OCR 识别引擎
│   ├── logging_config.py    # 日志配置（含敏感信息过滤）
│   │
├── parsers/                 # 各格式具体解析器（18 个）
│   ├── pdf_parser.py        # PDF 解析
│   ├── pptx_parser.py       # PPT/PPTX 解析
│   ├── docx_parser.py       # Word 文档解析
│   ├── xlsx_parser.py       # Excel 解析
│   ├── csv_parser.py        # CSV 解析
│   ├── txt_parser.py        # 纯文本解析（编码自动检测）
│   ├── image_parser.py      # 图片解析
│   ├── html_parser.py       # HTML 解析
│   ├── archive_parser.py    # 压缩包解析
│   ├── richtext_parser.py   # 富文本解析（RTF）
│   ├── data_parser.py       # 通用数据解析（JSON/YAML/XML）
│   ├── markdown_parser.py   # Markdown 解析（★ 新增）
│   ├── toml_parser.py       # TOML 解析（★ 新增）
│   ├── odf_parser.py        # ODF 解析 .odt/.ods/.odp（★ 新增）
│   ├── email_parser.py      # 邮件解析 .eml/.msg（★ 新增）
│   ├── epub_parser.py       # EPUB 电子书解析（★ 新增）
│   └── svg_parser.py        # SVG 矢量图解析（★ 新增）
│
├── api/                     # API 接口层
│   ├── v1.py                # v1 兼容接口
│   └── v2.py                # v2 新架构接口
│
├── frontend/                # Web 前端（TypeScript + Lit + TailwindCSS）
│   ├── index.html           # 入口页面（Lit 组件挂载点）
│   ├── package.json          # 前端依赖清单
│   ├── tsconfig.json         # TypeScript 配置
│   ├── vite.config.ts        # Vite 构建配置
│   ├── styles/
│   │   └── main.css          # TailwindCSS 主题 + 工具类
│   ├── src/
│   │   ├── main.ts           # 根组件 <app-root> + 转换流程编排
│   │   ├── state/
│   │   │   └── store.ts      # 发布-订阅全局状态管理
│   │   ├── types/
│   │   │   └── index.ts      # TypeScript 类型定义
│   │   ├── utils/
│   │   │   ├── api.ts        # API 客户端（上传 + 转换）
│   │   │   └── format.ts     # 格式工具函数（图标/分类/大小限制）
│   │   └── components/       # Lit Web Components（8 个）
│   │       ├── app-background.ts   # 视频背景组件
│   │       ├── app-upload.ts       # 拖拽上传组件
│   │       ├── app-options.ts      # 转换选项面板
│   │       ├── app-convert-btn.ts  # 转换按钮 + SVG 进度环
│   │       ├── app-status.ts       # Toast 通知组件
│   │       └── app-result.ts       # 结果展示（标签页 + 代码高亮）
│   └── background/
│       └── Genshin Impact - Kusanali in the forest - PC.mp4
│
├── test/                    # 测试套件
│   ├── conftest.py          # pytest 配置
│   ├── fixtures/            # 测试用的固定数据文件
│   ├── unit/                # 单元测试
│   └── integration/         # 集成测试
│
└── uploads/                 # 上传文件临时存储（自动创建）
```

## 测试

项目提供丰富的测试套件，覆盖各解析器、转换引擎、OCR 引擎、编码检测、API 接口等核心模块。

- **单元测试**：`test/unit/` 目录下 25+ 测试文件（含 7 个新格式解析器测试）
- **集成测试**：`test/integration/` API 接口端到端测试
- **测试数据**：`test/fixtures/` 提供各类编码、格式的测试文件

## 更新日志

### v1.2.0 (2026-06-12) — 7 种新格式 + 前端现代化重构

**测试体系修复**
- 修复 `conftest.py` 导入路径错误（`file_parser` → `core.file_parser`），从 452 错误降至 0
- 修复 3 个测试文件的 patch 路径和导入问题
- 补充 `pydantic-settings`、`requests`、`PyYAML` 缺失依赖

**并发安全修复**
- `MiniMaxClient` 单例模式添加 `threading.Lock()` 双重检查加锁
- `DataConverter` 缓存字典添加 `_cache_lock` 保护并发读写

**统一 OutputFormat 枚举**
- `ai_discovery.py` 中 `OutputFormat` 重命名为 `AiOutputFormat`，消除与 `models.py` 的命名冲突
- `models.py` 中补全 `OutputFormat.AUTO = "auto"`

**删除未使用文件**
- 删除 `core/extended_parsers.py`（未注册的扩展解析器）
- 删除 `core/chart_extraction.py`（未集成到策略系统）
- 删除对应测试文件

**基础设施**
- 创建 `pyproject.toml`（项目元数据 + ruff 规范 + pytest 配置）
- 创建 `.github/workflows/ci.yml`（Python 3.10/3.11/3.12 矩阵 CI）
- 创建 `.env.example`（完整环境变量示例含 AI/安全/缓存配置）

**安全加固**
- CORS 中间件改为使用 `settings.ALLOWED_ORIGINS` 配置项，替代硬编码 `allow_origins=["*"]`
- `/debug/config` 接口增加 `DEBUG` 模式保护，非调试模式返回 403
- 临时文件清理改为 `try/finally` 模式，确保异常路径下也被删除

**代码质量加固**
- 修复 16 处裸 `except:`（涉及 8 个文件），改为捕获具体异常类型

**结构化日志 + TraceID**
- 新增 `core/logging_config.py`：`JsonFormatter`（JSON 输出）+ `setup_logging()`
- 新增 `TraceIDMiddleware`：每个请求自动分配 Trace ID，响应头返回 `X-Trace-ID`
- `main.py` 接入结构化日志，DEBUG 模式用文本，生产用 JSON

**converter_engine 拆分**
- 新增 `core/decision_engine.py`：提取 `ConversionDecision` + `DecisionEngine` 类
- 新增 `core/ai_prompt_manager.py`：提取 `AIPromptManager` 类
- `DataConverter` 现通过组合持有子引擎，职责更单一

**ContentHashCache 集成**
- 将内存+磁盘两级内容哈希缓存集成到 `DataConverter.convert_with_ai_target()`
- 相同内容的文件可直接返回缓存结果，减少重复 AI 调用

**7 种新文件格式解析器**
| 格式 | 解析器 | 特性 |
|------|--------|------|
| Markdown (`.md`) | `markdown_parser.py` | 标题层级/代码块/表格/列表/前言元数据 |
| TOML (`.toml`) | `toml_parser.py` | 键值对/表/表数组/内联表，零依赖（Python 3.11+ `tomllib`） |
| ODF (`.odt/.ods/.odp`) | `odf_parser.py` | 文本文档/电子表格/演示文稿，零依赖（zipfile + xml） |
| EML/MSG (`.eml/.msg`) | `email_parser.py` | 邮箱头/正文/附件，MSG 支持可选 `extract-msg` 库 |
| EPUB (`.epub`) | `epub_parser.py` | 章节分页/OPF 元数据/HTML 净化，零依赖 |
| SVG (`.svg`) | `svg_parser.py` | 文本提取/图形统计/Title/Desc，零依赖 |

**前端现代化重构（TypeScript + Lit + TailwindCSS）**
- 技术栈从「原生 JS + CSS」升级为「TypeScript + Lit Web Components + TailwindCSS v4」
- 单体 `script.js`（700+ 行）拆分为 8 个独立 Web Components + 响应式 `store.ts`
- 消除 18 处 `style.display` 硬编码，统一用条件渲染 + CSS class 切换
- 构建产物：JS 59.83 kB (gzip 17.28 kB)，CSS 23.31 kB (gzip 6.50 kB)
- 删除旧版残留文件 `script.js`、`style.css`、`vite.config.js`

**新增测试用例**
- 新增 7 个解析器测试文件（markdown 19 个、TOML 14 个、ODF 18 个、email 15 个、EPUB 12 个、SVG 16 个）
- 总计新增 **~110 个**测试用例

### v1.1.0 (2026-06-12) — 架构精简

**阶段一：移除未使用模块**
- 删除 `core/quality_evaluator.py`（396 行）— 全局实例未在任何转换流程中调用
- 删除 `core/stream_parser.py`（301 行）— 流式解析能力未集成到转换流程
- 删除 `core/output_formatters.py`（410 行）— 格式化逻辑已在 `converter_engine.py` 内联实现
- 删除对应测试文件 `test/unit/test_quality_evaluator.py`、`test/unit/test_stream_parser.py`
- 将 `ResultExporter` 类内联为 `api/v1.py` 中的模块级导出函数

**阶段二：重构 converter_engine.py**
- 提取 `format_output()` 为 `core/utils.py` 独立工具函数，支持 JSON/Markdown/HTML/纯文本
- 移除 `DataConverter.export_result()`（与 `api/v1.py` 导出函数重复）
- 移除 3 个未使用的兼容转发方法（`_make_decision`、`_build_recommendation`、`_ai_enhance_convert`）
- 移除未使用的 `import json` 和 `ConversionDecision` 导入
- `converter_engine.py` 从 749 行降至 649 行（-13%）

**阶段三：日志合并与依赖清理**
- `SensitiveDataFilter` 注册逻辑从 `main.py` 移入 `logging_config.py` 的 `setup_logging()`
- 移除未使用依赖：`aiofiles`、`pdf2image`、`pywin32`、`pytest-asyncio`
- 移除 `pyproject.toml` dev 依赖中重复的 `httpx`
- 同步更新 `requirements.txt`
- 主依赖从 14 个降至 12 个，dev 依赖从 3 个降至 2 个

**净收益**
- 删除 ~1107 行未使用代码
- 核心模块从 22 个降至 19 个
- 测试套件 483 个用例全部通过，零回归

## 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。