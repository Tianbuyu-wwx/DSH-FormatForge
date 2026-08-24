---
name: dsh-formatforge
description: FormatForge — 把任意文件格式锻造成 AI 可读的结构化数据。Use when the user asks to convert/parse/extract a local file (pdf/docx/xlsx/pptx/eml/msg/epub/toml/yaml/csv/md/html/svg/image/archive) into text, JSON or Markdown; to read a document's content; or to check which formats are supported. Tools: ff_translate (convert), ff_formats (list supported formats). When the result carries data.enhance.needed=true, YOU are expected to complete the enhancement using the hint — do not call external APIs.
when_to_use: |
  # FormatForge（格式锻炉）

  把本地文件「锻造」成 AI 可直接消化的结构化数据。

  ## 工具

  - `ff_translate` — 转换。参数：path（本地绝对路径）或 text（原始文本，二选一）、
    format（json/markdown/html/text，默认 json）、type（auto/text/structured/table/
    image_desc/ocr，默认 auto）、quality（附质量报告）、prompt（自定义指令）。
  - `ff_formats` — 列出支持的输入格式、输出格式与转换策略。

  ## 使用时机

  - 用户给出一个本地文件路径并要求「读取/转换/解析/提取内容」。
  - **硬规则：用户消息中出现指向已存在本地文件的绝对路径，且格式属于可转换清单时，
    必须先用 ff_translate 转换再回答；禁止对 pdf/docx/xlsx/pptx/eml/msg/epub 等二进制格式
    使用 read 工具（读出来是乱码）。** 多个文件用 paths 参数（逗号分隔，支持 * 与 ** 通配）；
    内容超长用 max_chars/offset 分页读取。
  - 用户粘贴一段结构化文本（TOML/YAML/CSV/JSON...）希望整理为 JSON 或 Markdown。
  - 用户询问某格式是否支持 → 先调 `ff_formats`。

  ## 约定

  1. 只接受**已存在的本地路径**。远程 URL 请先用 pwsh 下载到本地再传路径。
  2. 结果是协议 JSON：`{ok, code, data:{content, meta, quality?, enhance?}}`。
     失败时 `{ok:false, error:{kind, message}}` —— kind=not_found 检查路径；
     timeout 可用更小的文件重试或提高 FF_TIMEOUT_S。
  3. **enhance 协议（重要）**：当返回 `data.enhance.needed=true` 时，
     说明纯规则转换不足以产出高质量结果：
       - reason=image_only   → 页面无文字层（扫描件）。基于已有 OCR 文本/图片描述重建结构。
       - reason=low_confidence → 置信度低。检查内容完整性，修复明显解析噪声。
       - reason=table_sparse  → 有表格但未抽到单元格。从原文重建 Markdown 表格。
     此时由你（当前会话模型）按 hint 直接完成增强后回答用户；不要调用外部 API。
  4. 大输出会在 render 层截断到 2 万字符；需要更多可分页（先转 markdown 再分段读取）。

  ## 环境

  - 解释器探测：FF_PYTHON → <repo>/.venv-fg → PATH python（需 ≥3.10）。
  - 上限：FF_MAX_BYTES（默认 100MB）；超时：FF_TIMEOUT_S（默认 120s）。
---

# dsh-formatforge

FormatForge 的 DSH 插件壳：把 `python -m formatforge` CLI 包装为原生工具
`ff_translate` / `ff_formats`。Python 内核负责 30+ 格式解析与策略选择；
模型增强通过 enhance 协议交给当前会话完成。
