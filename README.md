# AI 数据转换器

> 自动将各种格式数据转换为 AI 可识别的标准化数据

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green)](https://fastapi.tiangolo.com)
[![Frontend](https://img.shields.io/badge/frontend-Lit%20%2B%20Vite%20%2B%20TS-orange)]()
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-585%20passed-brightgreen)]()

## 目录

- [项目简介](#项目简介)
- [核心功能](#核心功能)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 文档](#api-文档)
- [项目结构](#项目结构)
- [测试](#测试)
- [更新日志](#更新日志)
- [许可证](#许可证)

---

## 项目简介

AI 数据转换器是一个智能数据格式转换服务，支持将 **PPT、PDF、Word、Excel、CSV、图片、TXT、HTML、压缩包、邮件、电子书、音视频元数据** 等 34+ 种文件格式转换为 AI 模型可识别的标准化数据（JSON / Markdown / HTML / CSV / XML / 纯文本）。

项目采用 **FastAPI** 构建高性能后端，提供友好的 **Web 前端界面**（Lit 3 + TypeScript + Vite）和完整的 **RESTful API**，专注于"数据 → AI"格式转换管道，让混乱的原始文件变成 AI 可直接消化的干净数据。

## 核心功能

### 多格式文件解析（34+ 格式）
| 分类 | 格式 |
|------|------|
| 文档 | PDF, DOCX, PPTX, TXT, MD, RTF, ODT, ODP |
| 表格 | XLSX, CSV, ODS |
| 图片 | JPG/JPEG, PNG, GIF, WEBP, BMP, TIFF, SVG |
| 数据 | JSON, XML, YAML, TOML |
| 邮件 | EML, MSG |
| 电子书 | EPUB |
| 压缩包 | ZIP, 7z, RAR |
| 字幕 | SRT, VTT |
| 文档 | LaTeX (.tex) |
| 数据库 | SQL Dump (.sql) |
| 音频 | WAV, MP3, FLAC, OGG, M4A, AIFF |
| 其他 | HTML |

### 智能数据转换
- 自动检测输入文件格式（魔数 + 扩展名 + 内容分析）
- 支持 7 种转换策略：自动检测、纯文本提取、结构化数据、表格提取、图片描述、OCR 文字识别、AI 增强
- 6 种输出格式：JSON / Markdown / HTML / CSV / XML / 纯文本
- 5 种输出模板：OpenAI Messages、RAG 文档切片、向量数据库导入、LangChain Document、智能摘要
- 自定义转换指令（Prompt）
- 可选 AI 增强转换（MiniMax / OpenAI / Anthropic / 智谱 / 通义千问 / DeepSeek）

### Web 前端界面（Lit 3 + TypeScript + Vite）
- **v4.0 Sacred Grove 视觉主题**：《原神》须弥森林视频背景，纳西妲角色画面完全不被遮挡
- God Rays 体积光束 + Canvas 萤火虫粒子系统 + 暗角遮罩
- 森林配色体系（深绿/青/暖琥珀强调色），衬线体标题 + Inter 正文
- 左侧边栏布局（420px 毛玻璃面板），响应式适配（桌面/平板/手机）
- 拖拽上传文件 / URL 输入 / 文本粘贴 三种输入方式
- 批量文件转换（多文件拖拽 + 进度展示）
- SVG 环形进度条 + 阶段文字提示
- 结果标签页展示（转换内容 / 结构化数据 / 处理日志）
- 多格式对比预览（Markdown / JSON / HTML / 纯文本 并排展示）
- 质量评分报告（5 维度 + A/B/C/D/F 等级）
- 转换历史记录面板（SQLite 持久化 + 搜索 + 重新下载）
- Toast 通知（顶部横幅，带滑入/滑出动画）
- 中/English 语言切换
- 按类型差异化大小限制（图片 20MB / 其他 50MB）

### RESTful API
- **v1 接口**（已弃用，将在下个版本移除）：文件上传解析、转换执行、结果查询与导出
- **v2 接口**（主力）：统一转换入口，支持文件/URL/原始数据输入，批量转换，SSE 流式输出
- **Webhook 回调**：转换完成后异步 POST 结果到指定 URL（HMAC 签名 + 重试机制）
- **质量分析**：转换结果质量评分 API
- **可观测性**：Prometheus 指标 + 健康检查端点

### 高级特性
- OCR 文字识别（Tesseract / PaddleOCR / EasyOCR 多后端，自动降级）
- 增强表格解析（合并单元格检测、分隔符自动识别、数值格式化）
- 批量文件转换（逐文件进度回调）
- 内容缓存（TTL 过期 + 磁盘持久化）
- 转换历史（SQLite 持久化，WAL 模式）
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
| 前端 | Lit Web Components + Vite + TailwindCSS v4 |
| 测试 | pytest, ruff, mypy |
| CI | GitHub Actions（Python 3.10/3.11/3.12 矩阵） |

## 快速开始

### 环境要求

- Python 3.10+
- pip / poetry
- Node.js 18+（前端构建）

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

# 4. 构建前端（可选）
cd frontend && npm install && npm run build && cd ..
```

### 配置

创建 `.env` 文件（基于 `.env.example`）：

```ini
# AI 服务提供商（可选，不配置则作为纯格式转换器使用）
AI_PROVIDER=minimax

# MiniMax 配置
MINIMAX_API_KEY=your_minimax_api_key
MINIMAX_GROUP_ID=your_group_id

# 应用配置
APP_HOST=0.0.0.0
APP_PORT=8000
DEBUG=true
```

> **注意**：不配置 AI 密钥也可作为完整的数据格式转换器使用，所有转换功能均不依赖 AI。

### 运行

```bash
python main.py
```

服务启动后：
- 前端页面：http://localhost:8000/static/index.html
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/v2/health
- Prometheus 指标：http://localhost:8000/api/v2/metrics

### 运行测试

```bash
# 运行所有测试
pytest test/

# 运行特定测试
pytest test/unit/test_txt_parser.py -v
pytest test/integration/test_api.py -v
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

### v2 接口（主力）

**转换**
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v2/convert` | 统一转换（JSON body） |
| POST | `/api/v2/convert/upload` | 文件上传转换 |
| POST | `/api/v2/convert/url` | URL 内容转换 |
| POST | `/api/v2/convert/text` | 文本内容转换 |
| POST | `/api/v2/convert/stream` | SSE 流式转换 |
| POST | `/api/v2/convert/template` | 应用输出模板转换 |

**历史记录**
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v2/history` | 历史记录列表（分页+筛选） |
| GET | `/api/v2/history/{id}` | 历史记录详情 |
| DELETE | `/api/v2/history/{id}` | 删除单条历史 |
| DELETE | `/api/v2/history` | 清空历史 |
| GET | `/api/v2/history/stats` | 历史统计 |

**导出**
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v2/export/{id}` | 导出结果文件（json/md/txt/html/csv/xml） |

**输出模板**
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v2/templates` | 获取模板列表 |

**质量报告**
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v2/quality/{id}` | 获取历史记录质量报告 |
| POST | `/api/v2/quality/analyze` | 上传文件分析质量 |

**Webhook 回调**
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v2/webhook/register` | 注册 Webhook 回调 |
| GET | `/api/v2/webhook/status/{task_id}` | 查询投递状态 |
| DELETE | `/api/v2/webhook/{task_id}` | 取消 Webhook |
| GET | `/api/v2/webhook/stats` | Webhook 统计 |

**监控与健康检查**
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v2/metrics` | Prometheus 格式指标 |
| GET | `/api/v2/health` | 健康检查 |

### v1 接口（已弃用，将在下版本移除）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/convert/upload` | 上传文件并解析 |
| POST | `/api/v1/convert/run` | 执行数据转换 |
| POST | `/api/v1/convert/auto` | 上传文件直接转换 |
| GET | `/api/v1/convert/result/{result_id}` | 获取转换结果 |
| GET | `/api/v1/convert/status/{parse_id}` | 查询解析状态 |
| GET | `/api/v1/convert/export/{result_id}` | 导出转换结果 |
| POST | `/api/v1/ai/discover` | AI 能力发现 |
| GET | `/api/v1/ai/providers` | 支持的 AI 提供商 |

### 基础接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务信息 |
| GET | `/health` | 健康检查 |
| GET | `/debug/config` | 调试配置（仅 DEBUG 模式） |

## 项目结构

```
数据格式转换器/
├── main.py                  # 应用入口：FastAPI 初始化、中间件、路由注册
├── requirements.txt         # Python 依赖
├── pyproject.toml           # 项目元数据 + ruff/mypy 配置
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
│   ├── pipeline.py          # Pipeline 编排引擎（步骤化转换流程）
│   ├── pipeline_steps.py    # Pipeline 步骤实现（含 OCR/Webhook 集成）
│   ├── converter_engine.py  # 核心转换引擎（智能决策）
│   ├── conversion_strategies.py  # 转换策略（含增强表格解析）
│   ├── decision_engine.py   # 转换决策引擎
│   ├── format_detector.py   # 格式自动检测
│   ├── input_adapters.py    # 多源输入适配器（文件/URL/原始数据）
│   ├── file_parser.py       # 文件解析器总入口
│   │
│   ├── provider_registry.py # AI Provider 统一注册中心
│   ├── ai_client.py         # AI 客户端封装
│   ├── ai_discovery.py      # AI 能力发现
│   ├── ai_prompt_manager.py # AI 提示词管理
│   │
│   ├── content_cache.py     # 内容缓存（TTL + 持久化）
│   ├── ocr_engine.py        # OCR 识别引擎（Tesseract/PaddleOCR/EasyOCR）
│   ├── logging_config.py    # 日志配置（JSON 格式 + TraceID）
│   ├── quality_report.py    # 解析质量评分（5 维度 + A/B/C/D/F）
│   ├── stream_handler.py    # SSE 流式输出处理器
│   ├── output_templates.py  # 输出模板引擎（5 种预设）
│   ├── metrics.py           # Prometheus 指标收集（8 个指标）
│   ├── webhook_manager.py   # Webhook 回调管理（注册/投递/重试/签名）
│   ├── history_store.py     # 转换历史 SQLite 存储
│   │
├── parsers/                 # 各格式解析器（21 个）
│   ├── __init__.py           # BaseParser 抽象基类
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
│   ├── markdown_parser.py   # Markdown 解析
│   ├── toml_parser.py       # TOML 解析
│   ├── odf_parser.py        # ODF 解析 .odt/.ods/.odp
│   ├── email_parser.py      # 邮件解析 .eml/.msg
│   ├── epub_parser.py       # EPUB 电子书解析
│   ├── svg_parser.py        # SVG 矢量图解析
│   ├── subtitle_parser.py   # 字幕解析 .srt/.vtt
│   ├── latex_parser.py      # LaTeX 解析 .tex
│   ├── sql_parser.py        # SQL Dump 解析
│   └── audio_parser.py      # 音频元数据解析 .wav/.mp3/.flac
│
├── api/                     # API 接口层
│   ├── v1.py                # v1 兼容接口（已弃用）
│   └── v2.py                # v2 新架构接口（20+ 端点）
│
├── frontend/                # Web 前端（Lit 3 + TypeScript + Vite）
│   ├── index.html           # 入口页面
│   ├── package.json         # 前端依赖清单
│   ├── tsconfig.json        # TypeScript 配置
│   ├── vite.config.ts       # Vite 构建配置
│   ├── vitest.config.ts     # Vitest 测试配置
│   ├── styles/
│   │   └── main.css         # 全局样式入口
│   ├── src/
│   │   ├── main.ts          # 根组件 <app-root> + 左侧边栏布局
│   │   ├── styles/
│   │   │   ├── tokens.css   # 设计 Token（oklch 色彩空间 + 双主题）
│   │   │   ├── shared.ts    # 共享 CSS 样式片段
│   │   │   └── animations.ts# 共享动画 keyframes + 工具类
│   │   ├── i18n/
│   │   │   ├── index.ts     # 中英文语言包（80+ 词条）
│   │   │   └── lit-i18n.ts  # Lit 响应式 T 指令
│   │   ├── state/
│   │   │   └── store.ts     # 发布-订阅全局状态管理
│   │   ├── types/
│   │   │   └── index.ts     # TypeScript 类型定义
│   │   ├── utils/
│   │   │   ├── api.ts       # API 客户端（20+ 端点）
│   │   │   └── format.ts    # 格式工具函数
│   │   └── components/      # Lit Web Components（9 个）
│   │       ├── ui/
│   │       │   └── icon.ts          # SVG 图标组件（35 个图标）
│   │       ├── app-background.ts    # 视频背景 + God Rays + 粒子系统
│   │       ├── app-upload.ts        # 多模式上传（文件/URL/文本）
│   │       ├── app-options.ts       # 转换选项面板
│   │       ├── app-convert-btn.ts   # 转换按钮 + SVG 进度环
│   │       ├── app-status.ts        # Toast 通知
│   │       ├── app-result.ts        # 结果展示（含单元测试）
│   │       ├── app-history.ts       # 历史记录面板
│   │       └── app-compare.ts       # 多格式对比预览
│   └── background/
│       └── Genshin Impact - Kusanali in the forest - PC.mp4
│
├── test/                    # 测试套件
│   ├── conftest.py          # pytest 配置
│   ├── fixtures/            # 测试用的固定数据文件
│   ├── unit/                # 单元测试（25+ 文件）
│   └── integration/         # 集成测试（API 端到端）
│
├── .github/
│   └── workflows/
│       └── ci.yml           # CI（python 3.10/3.11/3.12 + mypy + 前端构建）
│
└── uploads/                 # 上传文件临时存储（自动创建）
```

## 测试

项目提供丰富的测试套件，覆盖各解析器、转换引擎、OCR 引擎、编码检测、API 接口等核心模块。

- **单元测试**：`test/unit/` 目录下 25+ 测试文件
- **集成测试**：`test/integration/` API 接口端到端测试（含 Webhook、质量报告）
- **测试数据**：`test/fixtures/` 提供各类编码、格式的测试文件
- **CI**：GitHub Actions 自动运行 Python 3.10/3.11/3.12 矩阵测试 + ruff 格式检查 + mypy 类型检查 + 前端构建验证

## 更新日志

### v4.0 Sacred Grove (2026-06-14) — 视觉完全重构 + 去 AI 味

**视觉设计重构**
- 全新 "Sacred Grove" 视觉主题：以《原神》须弥森林纳西妲视频为核心背景
- 左侧边栏布局（420px），角色画面区域完全留白不被遮挡
- God Rays 体积光束（CSS 呼吸动画）+ Canvas 萤火虫粒子系统 + 暗角遮罩
- 森林配色体系：深绿 `#0a1f14` / 青 `#5fb3c3` / 暖琥珀 `#d4a574` 强调色
- 字体系统：`DM Serif Display` 衬线体标题 + `Inter` 正文 + `JetBrains Mono` 代码
- 毛玻璃边栏：`backdrop-filter: blur(24px)` + 24px 大圆角
- 药丸形渐变按钮 + 响应式适配（桌面/平板/手机）+ 移动端汉堡菜单

**架构升级**
- 设计 Token 体系：`src/styles/tokens.css` oklch 色彩空间
- 共享样式基类：`src/styles/shared.ts` 统一卡片、按钮、输入框、Badge
- 动画系统：`src/styles/animations.ts` 共享 keyframes + 工具类
- SVG 图标组件：`src/components/ui/icon.ts` 35 个粗线条手绘风格图标
- 空状态组件 + 骨架屏组件

**后端增强**
- 启动时自动检测前端（3000 端口），若未运行则自动唤起 `npm run dev`
- 自动打开浏览器访问前端页面
- 补全 6 个缺失的解析库：python-docx, openpyxl, chardet, py7zr, rarfile, striprtf

**测试**
- 新增 `src/components/app-result.test.ts`：10 个单元测试覆盖渲染逻辑
- vitest + jsdom 环境，串行执行 + store 重置隔离

**v4.0 技术栈**
- 前端：Lit 3 + TypeScript 5.6 + Vite 6
- 测试：vitest 4 + jsdom
- 构建产物：CSS 1.49 KB / JS 76.90 KB

### v1.4.0 (2026-06-13) — P0/P1/P2 三大梯队全面升级

**P0：强化解析能力**
- OCR 引擎集成：`core/pipeline_steps.py` 新增 `OcrStep`，ParseStep 后自动对图片文件执行 OCR（Tesseract → PaddleOCR → EasyOCR 优先级自动降级）
- 增强表格解析：`core/conversion_strategies.py` 重写 `TableExtractionStrategy`，支持分隔符自动检测、合并单元格识别（纵向/横向）、数值格式化、多 Sheet 标题
- 导出功能实现：`api/v2.py` 新增 `GET /export/{id}` 端点，支持 JSON/Markdown/HTML/CSV/XML/TXT 多格式导出

**P1：提升产品完整度**
- 新增 4 个文件格式解析器：字幕（SRT/VTT）、LaTeX（.tex）、SQL Dump（.sql）、音频元数据（WAV/MP3/FLAC/OGG/M4A/AIFF）
- 统一 Parser 接口：`parsers/__init__.py` 增强 `BaseParser` 抽象基类，添加 `name`/`description`/`supported_formats`/`parse_bytes()`
- 前端多模式输入：`app-upload.ts` 支持文件上传/URL 粘贴/文本粘贴三标签切换
- 批量转换前端：多文件拖拽 + 批量进度 + 批量结果汇总
- 转换历史记录：`core/history_store.py`（SQLite 持久化）+ 6 个历史 API + `app-history.ts` 历史面板
- 前端 API 客户端扩展：`api.ts` 新增 `convertUrl()`/`convertText()`/`batchConvert()` 等函数

**P2：增强与差异化**
- 多格式对比预览：`app-compare.ts` 模态弹窗，左右分栏对比原始内容 vs 各格式输出 + 质量评分条
- SSE 流式处理：`core/stream_handler.py` + `POST /convert/stream`，6 步骤实时进度推送
- 自定义输出模板：`core/output_templates.py`，5 种预设（OpenAI Messages / RAG 文档切片 / 向量数据库 / LangChain Document / 智能摘要）
- 解析质量报告：`core/quality_report.py`，5 维度评分（文本覆盖率/编码质量/结构保留/表格精度/内容完整性）+ A/B/C/D/F 等级
- 国际化 (i18n)：`frontend/src/i18n/` 中英文完整语言包（80+ 词条），Lit 响应式 `T` 指令，前端语言切换按钮
- Webhook 回调：`core/webhook_manager.py`，注册/投递/重试（3 次指数退避）/HMAC 签名/取消/统计，集成到 Pipeline 自动触发
- 可观测性：`core/metrics.py`（8 个 Prometheus 指标）+ `MetricsMiddleware` + `GET /metrics` + `GET /health`
- CI 增强：`ruff format --check` + `mypy` 类型检查 + 独立 `build-frontend` job（TypeScript 编译 + Vite 构建）

**v2 API 端点扩展**
- 新增 24 个端点：转换（url/text/stream/template）、历史（list/detail/delete/clear/stats）、导出、模板、质量报告、Webhook、监控指标
- v1 API 保持运行但标记弃用

**测试**
- 575 个测试用例全部通过，零回归

### v1.3.0 (2026-06-13) — 架构重构：Provider 注册中心 + 扩展名映射统一 + v1 API 弃用

**Provider 统一注册中心**
- 新增 `core/provider_registry.py`：统一 AI Provider 管理，合并 `ai_discovery.py`（能力预设）、`ai_client.py`（客户端工厂）、`config.py`（Provider 配置）三处分散逻辑
- 支持 6 大 Provider：MiniMax、OpenAI、Anthropic、智谱、通义千问、DeepSeek
- 提供 `ProviderRegistry` 全局单例，统一能力发现、客户端创建、Provider 查询接口
- `core/pipeline.py`、`core/converter_engine.py`、`core/conversion_strategies.py`、`core/decision_engine.py` 统一从 `provider_registry` 导入

**扩展名映射统一**
- `core/security.py` 不再维护独立的 `ALLOWED_EXTENSIONS`，改为从 `core/format_detector.py` 的 `EXTENSION_MAP` 自动推导
- 消除两处扩展名列表不同步的风险，单一数据源

**v1 API 弃用清理**
- `core/utils.py` 导出 URL 从 `/api/v1/convert/export/` 迁移至 `/api/v2/convert/export/`
- `frontend/src/utils/api.ts` 全面迁移至 v2 API：端点、字段名、响应结构均更新

**Bug 修复**
- `core/pipeline_steps.py` 补充缺失的 `import time`（修复 4 个测试失败）
- `test/unit/test_content_cache.py` 移除引用不存在 `SimilarityCache` 的无效测试类

**新增测试**
- `test/unit/test_provider_registry.py`：33 个测试用例
- `test/unit/test_security.py`：35 个测试用例
- `test/unit/test_utils.py`：25 个测试用例
- 合计新增 93 个测试用例，全部通过

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