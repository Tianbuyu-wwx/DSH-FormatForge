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

### 多格式文件解析
| 格式 | 说明 |
|------|------|
| PDF | 文本提取、图片识别（OCR）、混合内容处理 |
| PPT/PPTX | 幻灯片文字、图表、图片提取 |
| DOCX | Word 文档内容提取 |
| XLSX/CSV | 表格数据提取与分析 |
| TXT | 纯文本（自动检测编码：UTF-8 / GBK / GB2312 / Big5） |
| 图片 | OCR 文字识别、图片描述生成 |
| HTML | 富文本内容提取 |
| ZIP/7z/RAR | 压缩包内文件解析 |

### 智能数据转换
- 自动检测输入文件格式
- 支持 7 种转换类型：自动检测、纯文本提取、结构化数据、表格提取、图片描述、OCR 文字识别、编码修复
- 4 种输出格式：JSON / Markdown / HTML / 纯文本
- AI 增强转换：自动发现目标 AI 能力（多模态、输入类型、上下文长度等），选择最优转换策略
- 自定义转换指令（Prompt）

### Web 前端界面
- 拖拽上传文件
- 实时转换进度展示
- 转换结果预览（内容 / 结构化数据 / 处理日志）
- 结果复制与下载（支持 JSON / Markdown / HTML / TXT 导出）

### RESTful API
- **v1 接口**（兼容旧版）：文件上传解析、转换执行、结果查询与导出
- **v2 接口**（新架构）：统一转换入口，支持文件/URL/原始数据输入，支持目标 AI 能力发现
- **AI 能力发现接口**：探测目标 AI 端点能力

### 高级特性
- OCR 文字识别（支持中文、英文等多语言）
- 图表提取与分析（饼图、柱状图、折线图、散点图等）
- 批量文件转换
- 内容缓存（TTL 过期、LRU 淘汰、持久化）
- 转换质量评估与置信度评分
- 敏感信息脱敏
- 请求频率限制与请求体积限制
- 流式数据解析

## 技术栈

| 类别 | 技术 |
|------|------|
| 后端框架 | FastAPI 0.109 |
| 运行时 | Python 3.10+, Uvicorn 0.27 |
| 数据模型 | Pydantic v2 |
| AI 服务 | OpenAI SDK（兼容 MiniMax、智谱等） |
| PDF 解析 | PyPDF2, pdfplumber, pdf2image |
| 图片处理 | Pillow |
| PPT 解析 | python-pptx |
| 文件上传 | python-multipart, aiofiles |
| 编码检测 | chardet（内置） |
| HTTP 客户端 | httpx |
| 前端 | HTML / CSS / JavaScript（原生） |
| 测试 | pytest |

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
│   ├── format_detector.py   # 格式自动检测
│   ├── input_adapters.py    # 多源输入适配器（文件/URL/原始数据）
│   ├── file_parser.py       # 文件解析器总入口
│   ├── extended_parsers.py  # 扩展解析器
│   ├── stream_parser.py     # 流式数据解析器
│   │
│   ├── ai_client.py         # AI 客户端封装
│   ├── ai_discovery.py      # AI 能力发现
│   ├── ai_presets.py        # AI 提供商预设
│   │
│   ├── output_formatters.py # 输出格式化器
│   ├── content_cache.py     # 内容缓存（TTL + 持久化）
│   ├── quality_evaluator.py # 转换质量评估
│   ├── ocr_engine.py        # OCR 识别引擎
│   ├── chart_extraction.py  # 图表提取与分析
│   │
├── parsers/                 # 各格式具体解析器
│   ├── pdf_parser.py        # PDF 解析
│   ├── pptx_parser.py       # PPT/PPTX 解析
│   ├── docx_parser.py       # Word 文档解析
│   ├── xlsx_parser.py       # Excel 解析
│   ├── csv_parser.py        # CSV 解析
│   ├── txt_parser.py        # 纯文本解析（编码自动检测）
│   ├── image_parser.py      # 图片解析
│   ├── html_parser.py       # HTML 解析
│   ├── archive_parser.py    # 压缩包解析
│   ├── richtext_parser.py   # 富文本解析
│   ├── data_parser.py       # 通用数据解析
│
├── api/                     # API 接口层
│   ├── v1.py                # v1 兼容接口
│   └── v2.py                # v2 新架构接口
│
├── frontend/                # Web 前端
│   ├── index.html           # 主页面
│   ├── style.css            # 样式
│   ├── script.js            # 交互逻辑
│   └── background/          # 背景资源
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

项目提供丰富的测试套件，覆盖各解析器、转换引擎、OCR 引擎、质量评估、编码检测等核心模块。

- **单元测试**：`test/unit/` 目录下 20+ 测试文件
- **集成测试**：`test/integration/` API 接口测试
- **测试数据**：`test/fixtures/` 提供各类编码、格式的测试文件

## 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。