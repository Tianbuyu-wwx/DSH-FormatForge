# DSH-FormatForge 全面自检报告

> 版本：v2.0.0（npm `@tianbuyu-wwx/dsh-formatforge@2.0.0`）
> 日期：2026-09-30
> 宿主：DeepSeek Harness 0.2.0-rc.2（Electron 桌面版，profile `desktop`）
> 方法：**对正在运行的插件做实测**，不是读代码猜结论。所有结论附可复现的命令与原始输出。

---

## 0. 结论摘要

**工程质量高，产品体验有系统性缺口。** 门禁全绿、协议稳定、主流格式解析准确；但一旦离开“文本类文件”这个舒适区，就会出现**静默错误、静默覆盖、静默劣化**——这三类问题最难被用户发现，也最伤信任。

| 级别 | 数量 | 一句话 |
|---|---|---|
| 🔴 P0 | 3 | 批量产物**静默互相覆盖**、`parser` 字段**名不副实**、收件箱通知**污染会话且跨会话失效**（已修） |
| 🟠 P1 | 3 | 图片转换 5–8 秒、可选依赖缺失时**静默降级成垃圾且报 confidence=1.0**、临时文件名泄漏进结果 |
| 🟡 P2 | 3 | 无历史/检索、CSV BOM 未剥离、不支持的拖入**静默忽略** |
| 🔵 P3 | 3 | 文档数字漂移、CHANGELOG 重复版本号、仓库缓存目录膨胀 |

**最该先修的是三件“静默错误”**——它们不报错，只是给出错误的答案或悄悄丢掉结果。

---

## 1. 自检范围与方法

| 手段 | 覆盖 |
|---|---|
| 自动化门禁 | pytest 564 · ruff check/format · mypy · 5 个 Node 自检 · 真实宿主模块契约 17 项 |
| **实机格式矩阵** | 自制 **30 个真实文件**（28 种格式，含 docx/xlsx/pptx/odt/ods/odp/epub/eml/zip/6 种图片/BOM CSV/GBK 文本），经**正在运行的插件** `ff_batch` 全量转换 |
| 对照实验 | 检测类型 vs 实际解析器、OCR 开关对照、`OCR_ENABLED=false` 对照、进程内微基准、`-X importtime` |
| 规模压测 | 复刻 `ff_result list` 的 I/O 模式，在 0/100/1000/5000 产物下计时 |
| 交互实测 | 拖入同一文件两次、同内容异名、`.exe` 拖入 |
| 现场反馈 | 用户在真实会话中报告的通知问题（P0-3） |

> 复现材料：`.scan/audit-live/`（fixtures + 生成脚本 + 基准脚本，已 gitignore）

---

## 2. 质量门禁：全绿

| 门禁 | 结果 |
|---|---|
| pytest（UTF-8 stdio，等同 CI 的 Linux runner） | **564 passed, 5 skipped, 0 failed** |
| ruff check / ruff format --check | All checks passed / 68 files already formatted |
| Node 自检（manifest / client-bundle / inbox / local / 截断一致性） | 5/5 OK |
| 真实宿主契约（用 app.asar 里解出的 `defineTool` 编译器实跑） | **17/17** |
| GitHub CI（推送后实跑） | **7/7 绿** |
| 宿主兼容闸门 `evaluatePluginCompatibility` | compatible |

**这一层没有问题。** 下面所有问题都不在这层门禁的覆盖范围内——这正是它们能活到今天的原因。

---

## 3. 实机格式矩阵：30 个文件

`ff_batch` 一次跑完，**29/29 报成功、0 失败、平均置信度 0.857**。但报告说成功，不代表结果对。

### 3.1 解析正确的（13 项）

| 输入 | 结果 | 评价 |
|---|---|---|
| `report.docx` | 标题 + 段落 + **Markdown 表格（数值列右对齐）** | ✅ 质量高 |
| `deck.pptx` | 每页标题/正文 + `[备注]` 讲者备注 | ✅ 备注被正确提取 |
| `book.xlsx` | 两个 Sheet 都转成表格 | ✅ |
| `doc.odt` / `slides.odp` | 结构 + 表格 | ✅ |
| `book.epub` | 章节标题 + 正文（内容正确） | ✅ 解析对了（但见 P0-2） |
| `note.txt` / `readme.md` | 保留 Markdown 结构 | ✅ |
| `config.yaml` / `query.sql` / `subtitle.srt` / `page.html` / `payload.json` | 各自结构化处理（YAML 重排、SQL 建表、字幕去时间轴、HTML 去标签） | ✅ |
| `gbk_note.txt` | **GBK 自动识别并正确解出中文** | ✅ 自愈链路有效 |
| `table.csv` | 转成 Markdown 表格 | ⚠️ 见 P2-2（BOM） |
| `chart.{png,jpg,webp}` | 图片元信息描述 | ⚠️ 见 P1-1（慢且无 OCR 文本） |

### 3.2 解析可疑的（6 项）

| 输入 | 实际产出 | 问题 |
|---|---|---|
| `memo.rtf` | **原始 RTF 标记原样输出** | P1-2 |
| `paper.tex` | **原始 LaTeX 命令原样输出** | P1-2 |
| `data.xml` | 单行 XML 原样输出（未结构化） | 见 §4.2 |
| `mail.eml` | 原始 MIME 头，**Subject 仍是 base64** | 见 §4.2 |
| `sheet.ods` | `未检测到表格数据`（confidence 0.3） | 夹具受限，未定论 |
| `vector.svg` | `未检测到图片内容`（confidence 0.3，16 字符） | SVG 文本内容完全丢失 |

---

## 4. 发现明细

### 🔴 P0-1 `ff_batch` 产物名冲突 → 静默覆盖（数据丢失）

**现象**：一次 29 个文件的批量转换，**只产出 22 个文件**。报告写「29/29 完成，失败 0」，用户不会察觉少了 7 份。

```
COLLISION: book.md   <- ['book.epub', 'book.xlsx']
COLLISION: chart.md  <- ['chart.png', 'chart.jpg', 'chart.bmp', 'chart.gif', 'chart.tiff', 'chart.webp']
COLLISION: config.md <- ['config.toml', 'config.yaml']
```

**根因**：`formatforge/batch.py:126-129`

```python
# formatforge/batch.py:125-129
ext_map = {"markdown": ".md", "html": ".html", "json": ".json", "text": ".txt"}
out_ext = ext_map.get(to_format, f".{to_format}")
stem = path.stem if path.suffix.lower() == out_ext else path.stem
out_path = out_dir / f"{stem}{out_ext}"  # ← 只用 stem，扩展名被丢弃
```

**同类问题在收件箱**：`packages/dsh-formatforge/services/inbox-watcher.mjs:126-127,152-154` 同样用 `<stem>.ff.json`。所以 `report.docx` 与 `report.pdf` 先后拖入会互相覆盖。

**影响**：拖 6 张图 = 只剩 1 份结果；批量转换目录是不可信的。这是**静默数据丢失**，优先级最高。

**修法**：产物名带上原扩展名（`book.epub.md`）或在冲突时加序号；批量报告需显式列出被覆盖的条目。

---

### 🔴 P0-2 `meta.parser` 名不副实：报告的是「检测到的粗类型」，不是「实际用的解析器」

**证据（对照实验）**：

| 文件 | `meta.parser` 显示 | 实际跑的解析器 | 产出 |
|---|---|---|---|
| `book.epub` | `txt` | **`EPUBParser`** | 内容正确（`第一章 / 季度经营分析报告`） |
| `bundle.zip` | `unknown` | **`ArchiveParser`** | 压缩包内文件均被列出并提取 |

**根因链**：

1. `formatforge/__main__.py:132` 和 `:398`：
   ```python
   "parser": result.fileInfo.fileType.value if result.fileInfo else "unknown",
   ```
2. `FileType` 是个**只有 8 个值**的粗枚举（`core/models.py:93`）：
   `ppt / pdf / image / doc / txt / csv / xls / unknown`
3. `core/file_parser.py:267-323` 有一张显式映射表，把约 20 种格式**压扁**进这 8 个桶：
   ```python
   ".json": FileType.TXT, ".yaml": FileType.TXT, ".xml": FileType.TXT,
   ".html": FileType.TXT, ".rtf": FileType.TXT, ".sql": FileType.TXT,
   ".zip": FileType.UNKNOWN, ".7z": FileType.UNKNOWN, ".rar": FileType.UNKNOWN,
   ```

**真正的解析器名字其实已经拿到了**——`core/file_parser.py:345` 就在记日志：
```python
logger.info("解析完成: parser=%s, pages=%d", type(plugin_parser).__name__, len(pages))
```
只是没有往外传。

**影响**：
- 工具返回头写 `parser=txt`，模型会据此判断“这份文件被当纯文本处理了”——**结论是错的**；
- `ff_formats` 宣称的 34 种格式与 capabilities 无法被验证；
- 排查问题时被误导（本次自检就先被它误导了一轮）。

**修法**：`meta` 增加 `parser` = `type(plugin_parser).__name__`，保留旧字段为 `file_type`（做弃用过渡，符合 v1 协议兼容承诺）。

---

### 🔴 P0-3 收件箱通知污染会话，且跨会话失效（**已修复**）

**用户现场反馈**（原话）：

> 这个插件的拖入文件的上下文只生效于当前的对话，别的对话不生效，也不用再显示一遍

**根因**：`services/notify.mjs:50-59` 往会话里 append 了一条 **`user/message`**：

```js
session.append('user/message',
  { id: `ff-inbox-…`, role: 'user', content: [{ type: 'text', text }], source: { kind: 'user' } },
  { surfaceOp: 'append' })
```

宿主**没有临时通知通道**——`KNOWN_SESSION_EVENT_TYPES` 里所有模型可见事件都是持久化的。所以这条消息必然：

1. **永久写进 transcript** → 之后每一轮都重发给模型、UI 里反复出现（“又显示一遍”）；
2. **被署名为用户**（`role/source = user`）→ 对话里出现了用户从没说过的话；
3. **只送达当时持有 live agent 的会话**（`ctx.agents.list()`）→ 用户在别的对话里工作时拖的文件，永远不会有任何提示。

**已实施的修复（v2.0.1）**：

| 改动 | 文件 |
|---|---|
| 推送**默认关闭**（改为 `FF_INBOX_NOTIFY=true` 才开） | `services/notify.mjs` |
| 按 `resultId` **去重**，同一产物每会话最多播报一次 | `services/notify.mjs` + `index.mjs` |
| 通知文案从 6 行压成 **1 行**（transcript 是永久成本） | `services/notify.mjs` |
| **拉取式**取代推送：`ff_result {list:true}` 任何会话任何时刻可读 | `skills/…/SKILL.md` |

**验证**：`test-inbox.mjs` 新增 3 项断言——单行 ✓、去重后 1 条 ✓、默认关闭且不写 transcript ✓；契约 17/17 仍绿。

**为什么这是对的**：收件箱本来就是**共享目录**，任意对话都能 `ff_result` 取到。真正缺的是“知道去看”，而不是“被推一条消息”——后者代价是永久上下文污染。

---

### 🟠 P1-1 图片转换 5–8 秒，且最终只给一行元信息

**实测**（640×260 的 4KB PNG）：

| 环节 | 耗时 |
|---|---|
| 裸解释器启动 | 79 ms |
| `python -m formatforge version`（含管线导入） | 140 ms |
| **`ImageParser.parse()` 本身** | **4.3 ms** |
| 完整 CLI 转换（默认） | **7898 ms** |
| 完整 CLI 转换（`OCR_ENABLED=false`） | **5320 ms** |
| `import rapidocr_onnxruntime` | 309 ms |
| `ff_batch` 内各图片 | 1227 / 1413 / 3694 / 4119 / 5105 / 5141 ms |

**解析只要 4 毫秒，整条链路却要 5–8 秒**——说明开销在解析器之外（管线步骤 / OCR 初始化 / 质量评分），且**关掉 OCR 仍有 5.3 秒**。最终产物是 `图片: tmpukd170ad.png, 格式=PNG, 尺寸=(640, 260), 模式=RGB` ——95 个字符。

**影响**：这是**体感最强的延迟**。拖一张截图等 7 秒，等到的还不是内容。

**下一步**：对管线做一次 `cProfile` 定位（本次 stderr 重定向被 PowerShell 编码干扰，未取到干净的 profile 表）。

---

### 🟠 P1-2 可选依赖缺失时静默降级成垃圾，却报 `confidence=1.0`

`memo.rtf`（`striprtf` 未安装）的实际输出：

```
{\rtf1\ansi\deff0{\fonttbl{\f0 Arial;}}\f0\fs24 \u23395?\u24230?\u32463?\u-31707?…}
```
`parser=unknown, confidence=1.0`

`paper.tex` 同理输出原始 LaTeX，`confidence=1.0`。

**影响**：用户拿到的是**标记语言原文**，工具却报告「完全可信的成功」。这比报错更糟——模型会把这堆控制序列当成正文去理解。

**修法**：解析器无法处理时应返回 `unsupported_format` 或触发 `enhance`（`low_confidence`），**绝不能给 1.0**。可选依赖缺失应在 `ff_formats` 里标注该格式「当前不可用」。

---

### 🟠 P1-3 临时文件名泄漏进结果

| 输入 | 产出中出现的名字 |
|---|---|
| `bundle.zip` | `"title": "tmp2su4zugj.zip"` |
| `chart.png` | `图片: tmpukd170ad.png` |

内部走临时文件拷贝，**原始文件名没有回填**。用户无法判断这份结果对应哪个文件——批量场景下直接失去对应关系。

---

### 🟡 P2-1 没有历史与检索（用户提出的「数据库」正是指这里）

**实测 `ff_result list` 的开销**（复刻工具的真实 I/O 模式：`readdirSync` → 逐文件读前 2048B → `JSON.parse`）：

| 产物数 | list() 耗时 | 收件箱体积 |
|---:|---:|---:|
| 100 | 4.5 ms | 0.2 MB |
| 1 000 | 33.8 ms | 2.4 MB |
| 5 000 | **241.9 ms** | 12.0 MB |

**I/O 不是瓶颈**——242 ms 可以接受。真正的问题是**它一次把 5000 行塞进模型上下文**，以及下面这些压根没有的能力：

- ❌ 全文检索（“上个月那份合同里付款条款怎么写的？”）
- ❌ 内容哈希去重（同内容改名再拖 = 又转一遍）
- ❌ 来源溯源（哪个会话/哪次任务要的这份）
- ❌ 结构化筛选（按格式/时间/置信度）
- ⚠️ 保留策略存在但用户不可见（`.ff.retired.log` 只有运维看得到）

详见配套的 [ROADMAP.md](ROADMAP.md) R6.2 节（含 schema 与迁移方案）。

---

### 🟡 P2-2 CSV BOM 未剥离

`table.csv` 用 `utf-8-sig` 保存，转换后表头第一格仍是 `| ﻿指标 |`——**U+FEFF 留在单元格里**。会影响下游按键名取值。

---

### 🟡 P2-3 不支持的拖入被静默忽略

实测把 `.exe` 放进收件箱：**不产生任何产物，也不产生 `.ff.error.txt`**，用户毫无反馈。

这与设计文档冲突——`PLUGIN_PLAN.md §11.2` 明确写「转换失败写 `<name>.ff.error.txt`」。（浏览器上传通道行为正确：HTTP 415 拒绝。）

---

### 🔵 P3 文档与仓库卫生

| 项 | 现状 |
|---|---|
| README 测试数 | 写 `444 passed`，实际 **564**（漂移 120 项） |
| ROADMAP 基线 | 停在 `v0.10.0`，项目已是 v2.0.0；R1–R5 全部完成未标记 |
| CHANGELOG | 旧 Web 产品线的 `[1.1.0]`/`[1.2.0]` 条目与新线同号并列，易误读 |
| `.mypy_cache` | 75.9 MB |
| 根 `node_modules` | 指向 `.scan/node_modules` 的 junction（本次自检脚手架残留，需清理并加 ignore） |

---

## 5. 没发现问题的部分（同样重要）

- **协议与契约**：`{ok, code, data|error}` 形状、退出码 0/2/3/4、`enhance` 三触发在低置信样本上**都正确触发**（`sheet.ods`/`vector.svg`/`slides.odp` 均返回 `low_confidence` 且带可执行 hint）。
- **编码自愈**：GBK 文件 862 ms 正确解出，无乱码。
- **Office / PDF 主干**：docx（含表格右对齐）、pptx（含讲者备注）、xlsx（多 Sheet）、pdf（`confidence=0.92`、表格与双栏正确）质量高。
- **上传端点安全**：扩展名白名单 415 拒绝 `.exe`、100MB 上限、文件名消毒、同名自动加序号——之前已实测。
- **幂等与缓存**：同一实例第二次解析同一图片 **0.3 ms**（首次 4.3 ms）。
- **宿主集成**：工具注册、skill provider、HTTP 路由、client 模块契约全部 17/17。
- **协议冻结承诺**：`protocol/v1/` 未变，v2.0.0 只动了宿主要求。

---

## 6. 优先级建议

| 顺序 | 项 | 理由 | 预估 |
|---|---|---|---|
| 1 | **P0-1 批量/收件箱产物名冲突** | 静默丢数据，批量功能不可信 | 2h |
| 2 | **P0-2 `parser` 字段语义** | 静默误导模型与用户，且挡住后续所有排查 | 3h（含协议兼容过渡） |
| 3 | **P1-2 静默劣化 + 假 confidence** | 垃圾被当成正确答案喂给模型 | 3h |
| 4 | **P1-1 图片 5–8s** | 体感最强；先 profile 再优化 | 半天 |
| 5 | **P1-3 临时名泄漏** | 批量场景失去文件对应关系 | 1h |
| 6 | **P2-3 不支持拖入无反馈** | 用户以为坏了 | 1h |
| 7 | **R6.2 历史/检索/去重** | 体验跃迁（用户已提出） | 1–2 天 |

> P0-3（通知）**已完成**，见 §4 P0-3。

---

## 7. 一句话结论

**这个插件的“能转”已经很扎实——门禁全绿、主流格式准确、协议稳定、自愈链路有效；问题集中在“转得对不对、说不说清楚、快不快”。** 三个静默错误（覆盖 / 误标 / 假置信度）修掉之后，它会从「能用」变成「可信」；再补上历史与检索，才会从「可信」变成「好用」。
