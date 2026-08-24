# DSH-FormatForge

> 把任意文件格式锻造成 AI 可读的结构化数据 —— DeepSeek Harness (dsh) 插件内核

[![Version](https://img.shields.io/badge/version-3.0.0-blue)](pyproject.toml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-443%20passed-brightgreen)](test/)

**FormatForge**（前身 *Data-Format-Translator / AI 数据转换器*）将 **PDF、DOCX、PPTX、XLSX、CSV、图片、邮件（EML/MSG）、电子书、压缩包、TOML/YAML/JSON、SVG** 等 30+ 种格式解析为 AI 模型可直接消化的标准化数据。

v3.0 起项目转型为 **DeepSeek Harness 插件**：剥离 Web 服务与内置 AI 客户端，专注「格式 → 结构化文本」这一层；需要模型增强时通过 `enhance` 协议字段交给 dsh 当前会话模型完成。详见 [PLUGIN_PLAN.md](PLUGIN_PLAN.md)。

## 三种用法

### 1. CLI

```bash
pip install -e .

python -m formatforge translate document.pdf --format markdown
python -m formatforge translate --stdin-text < notes.txt
python -m formatforge formats    # 支持格式矩阵
python -m formatforge version
```

stdout 输出单行协议 JSON：

```jsonc
{"ok": true, "code": 200, "data": {
  "content": "...",            // 转换结果
  "format": "markdown",
  "meta": {"parser": "pdf", "file_size": 182044, "confidence": 0.95, "elapsed_ms": 812},
  "enhance": {                  // 触发条件满足时出现
    "needed": true,
    "reason": "image_only",     // image_only | low_confidence | table_sparse
    "hint": "4/4 页无文字层（疑似扫描件）..."
  }
}}
```

退出码：`0` 成功 / `2` 参数错 / `3` 解析失败 / `4` 超限。日志全部走 stderr。

### 2. Python 库

```python
from core.pipeline import ConversionPipeline, PipelineContext
from core.models import ConversionType, OutputFormat

pipeline = ConversionPipeline(enable_content_cache=False)
ctx = PipelineContext(
    source="report.docx",
    conversion_type=ConversionType.AUTO,
    output_format=OutputFormat.MARKDOWN,
)
response = pipeline.run(ctx)
print(response["result"].convertedContent)
```

### 3. dsh 插件（Phase 2 开发中）

Node bundle `packages/dsh-formatforge` 提供 `ff_translate` / `ff_formats` 两个工具，
spawn 本 CLI 并回传协议 JSON。安装方式见 PLUGIN_PLAN.md §7。

## 配置（环境变量 / .env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `FF_MAX_BYTES` | 104857600 | 单文件上限（100MB） |
| `FF_TIMEOUT_S` | 120 | 转换超时秒数（执行方在 JS 侧） |
| `OCR_ENABLED` | true | 启用本地 OCR（tesseract/paddleocr/easyocr 任一即可） |
| `LOG_LEVEL` | INFO | 日志级别 |

## 开发

```bash
pip install -e ".[dev]"
pytest test/          # 443 passed
ruff check .
mypy core/ parsers/ formatforge/
```

## 许可证

MIT
