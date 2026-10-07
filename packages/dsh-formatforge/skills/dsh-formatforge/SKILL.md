---
name: dsh-formatforge
description: FormatForge — 把任意文件格式锻造成 AI 可读的结构化数据。Use when the user asks to convert/parse/extract a local file (pdf/docx/xlsx/pptx/eml/msg/epub/toml/yaml/csv/md/html/svg/image/archive) into text, JSON or Markdown; to read a document's content; to batch-fetch multiple FormatForge results; to bulk-forge a directory of files in one shot; to diff two files (合同/法规/脚本版本对照); or to check which formats are supported (optionally filtered by category). Tools: ff_translate (convert), ff_formats (list supported formats), ff_result (fetch past results from inbox by id or batch), ff_batch (bulk convert a directory), ff_diff (compare two files via unified diff). When the result carries data.enhance.needed=true, YOU are expected to complete the enhancement using the hint — do not call external APIs.
version: 1.0.1
updated: 2026-08-31
when_to_use: |
  # FormatForge（格式锻炉）

  把本地文件「锻造」成 AI 可直接消化的结构化数据。

  ## 工具

  - `ff_translate` — 转换。参数：path（本地绝对路径）或 text（原始文本，二选一）、
    format（json/markdown/html/text，默认 json）、type（auto/text/structured/table/
    image_desc/ocr，默认 auto，**R3.1：auto 模式下自动附带 quality + 返回头 200 字预览**）、
    quality（附质量报告）、prompt（自定义指令）、pages（PDF 页选择 `1-3,7`）、
    encoding（TXT 类编码覆写如 `gbk`/`latin-1`，**R3.3：自愈重试链路接通了**）、
    **v0.10.0**: language（ISO 639-1 目标语言 metadata，写入 enhance.hint）、
    **v0.10.0**: output_file（content 另存路径，stdout 协议 JSON 不变；**只对单个目标有效**，
    多文件落盘用 `ff_batch(out=…)`）。
  - `ff_formats` — 列出支持的输入格式。**v0.10.0**: category 过滤（document/data/email/image/archive/audio）。
    **v0.14.0**: 返回 `data.details[]` 含每个 format 的 capabilities 列表（如 `pdf` 有 `[furniture_strip, ocr, table, two_column]`），按能力选择 format。
  - `ff_result` — 收件箱取回。参数：id（单 id）/ ids（批量 `id1,id2,...`，**R3.2 ≤20**）/
    list（列全部）；max_chars（默认 12,000）、offset（仅单 id 生效）；**R3.4 schema -33.3%**。
  - `ff_batch` — **v0.10.0** 批量锻造。参数：source（目录/glob）、out（产物目录）、format、type、
    workers（1-8）、recursive、force（忽略已有产物）、pages。返回汇总报告 + 每文件结果。
  - `ff_diff` — **v0.12.0** 对比两份文件差异（合同/法规/版本对照）。参数：path_a、path_b、
    format（中间格式）、context_lines、max_chars。返回增/删/未变行数 + unified diff 预览。

  ## 质量自愈（E4 / R3.3）

  ff_translate 带 `quality: true`（**R3.1 auto 模式自动开**）时返回 `quality.actions[]`。
  若某条 action 带 `retry_with`（如 `{"encoding":"gbk"}` 或 `{"conversion_type":"ocr"}`），
  **直接把这些参数并入 ff_translate 的同名参数重调**再回答；不要把 actions 原文丢给用户。

  | retry_with key | 重调方式 |
  |---|---|
  | `encoding` | `ff_translate {path, encoding:"<value>"}`（TXT 类编码错误） |
  | `conversion_type` | `ff_translate {path, type:"<value>"}`（如 `ocr` 兜底扫描件） |
  | `prompt` | `ff_translate {path, prompt:"<value>"}`（结构化重建） |

  ## 收件箱产物消费（N1 / R3.2 / v2.0.1 改为拉取式）

  **收件箱是共享目录，任何会话、任何时刻都能读**——不依赖"当前对话收到过通知"。

  - 用户说「我刚拖了个文件 / 把文件放进去了 / 上传了 X」→ **先调 `ff_result {list:true}`**
    看有什么，再决定取哪份。
  - 要列全部产物 → `ff_result {list:true}`
  - 取某份内容 → `ff_result {id:"<list 里的 id>"}`
  - **批量取多份** → `ff_result {ids:"id1,id2,id3"}`（R3.2：一次拿多产物，≤20）
  - 内容被截断时按提示带 `offset` 翻页（仅单 id 生效）
  - 用户直接给了本地路径时，`ff_translate {path}` 更省事，不必先查收件箱。

  > v2.0.1：默认**不再**往会话里推送「已锻好」通知（`FF_INBOX_NOTIFY=true` 可开）。
  > 宿主没有临时通知通道，推送只能落成一条 `user/message`，会永久留在 transcript 里
  > 反复重发、被当成用户发言，而且只有当时正在运行的会话收得到。
  > 因此改为拉取式：产物躺在收件箱里，谁需要谁去 `ff_result` 取。

  ## 使用时机

  - 用户给出一个本地文件路径并要求「读取/转换/解析/提取内容」。
  - **硬规则：用户消息中出现指向已存在本地文件的绝对路径，且格式属于可转换清单时，
    必须先用 ff_translate 转换再回答；禁止对 pdf/docx/xlsx/pptx/eml/msg/epub 等二进制格式
    使用 read 工具（读出来是乱码）。** 多个文件用 paths 参数（逗号分隔，支持 * 与 ** 通配）；
    内容超长用 max_chars/offset 分页读取。
  - 用户粘贴一段结构化文本（TOML/YAML/CSV/JSON...）希望整理为 JSON 或 Markdown。
  - 用户询问某格式是否支持 → 先调 `ff_formats`。
  - 用户提到刚拖入/上传了文件（没有给路径）→ `ff_result {list:true}` 找最近的产物。

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
  5. **R3.1 头部预览**：长 markdown/json 输出附 `body.slice(0, 200)` 预览，
     帮助判断质量/相关性后再决定翻页。

  ## 环境

  - 解释器探测：FF_PYTHON → <repo>/.venv-fg → PATH python（需 ≥3.10）。
  - 上限：FF_MAX_BYTES（默认 100MB）；超时：FF_TIMEOUT_S（默认 120s）。
---

# dsh-formatforge

FormatForge 的 DSH 插件壳：把 `python -m formatforge` CLI 包装为原生工具
`ff_translate` / `ff_formats` / `ff_result`。Python 内核负责 30+ 格式解析与策略选择；
模型增强通过 enhance 协议交给当前会话完成。

**版本**：v3.0.0（2026-10-02）—— 收件箱升级为 SQLite 索引库（元数据 / 全文检索 trigram / 内容去重 / 溯源）
+ 宿主右侧栏面板（搜索、预览、重转）+ 只读 API/SSE；顺带修好 `ff_result` 的字段错配（此前取回正文恒为空、
`parser` 恒为 `?`）。`ff_result` 新增 `search` / `stats` / `limit` 三个参数。协议仍是 v1（`protocol/v1/` 未变）。
**变更点**：见 CHANGELOG v3.0.0 节（v2.0.x 见该节）。
