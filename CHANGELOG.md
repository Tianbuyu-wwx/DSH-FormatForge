# 更新日志 (Changelog)

本项目的所有重要变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.14.0] - 2026-08-31 — 窗 B 全收口（v1.0 stable 前最后一站）

> 基线：v0.13.0（538 测试）→ v0.14.0 stable（566 测试，+28）
> 主题：完成 v0.14.0 计划全部 7 项（2 项 P0 + 5 项 P1）。v1.0 stable 直接复用此代码 + 窗 C 协议冻结。

### Added

- **B-P0-1 `ff_formats` 能力元数据**：每个 format 自带 `capabilities` 列表（自动扫描 parser 代码真实方法名）
- **B-P0-2 `ff_diff` 增量模式**：`--against-dir <dir>` + `--since-mtime <ts>`，共享 `_compute_diff`
- **B-P1-3 retention 通知降噪**：retention 清理只 log 不广播，避免惊扰 live session
- **B-P1-4 TTL 删除前 `.ff.retired.log`**：sha256(path) + ts + size 审计轨迹
- **B-P1-5 质量评分按 file_type 动态调权重**：纯文本 table_accuracy 归零；表格 table_accuracy 提高
- **B-P1-6 OCR enhance 漏判修复**：OCR 后纯图片 PDF，OCR confidence < 0.6 触发 `ocr_low_confidence`
- **B-P1-7 多文件 markdown `---` 分隔符保护**：截断优先级提升到最强边界，JS+Python 双端同步
- 跨语言一致性测试 `test-truncate-consistency.mjs` 11 case（保证 JS/Python smartTruncate byte-equal）

### Changed

- `cli/formatforge diff` 顺序变更 `path_b path_a`（argparse 限制）
- `_resolve_paths` 容错旧顺序
- `QualityReport.analyze` 现在记 `file_type` → `overall_score` 按 file_type 调权

### Removed

- **MediaIndexStrategy 从策略注册表移除**（v1.0/C 清理 dead code）：无人调用、auto_detect 不选它、CLI conversion_type 枚举不引用；class 保留供 v2.0 删

### Notes

- v0.14.0 RC（v0.14.0-rc.1）已发布但不进 npm latest——本 stable 才进 npm latest
- 协议冻结（v1.0/C）由 PR #9 完成
- npm 上 `latest: 0.14.0` 发布后，旧 0.13.0 仍可访问但不再推荐

### Tests
- 538 → **566 passed**（+28：B-P0-1 11 + B-P0-2 6 + B-P1-3/4 各 1 + B-P1-5 4 + B-P1-6 5 + B-P1-7 4）
- ruff ✓ / format ✓ / mypy ✓
- Node `test-local.mjs` / `test-inbox.mjs` / `test-manifest.mjs` / `test-truncate-consistency.mjs` 全过

## [0.14.0-rc.1] - 2026-08-31 — RC 候选（v1.0 前第二批 P0）

> 基线：v0.13.0（538 测试） → v0.14.0-rc.1（555 测试，+17）
> 主题：**会话模型发现能力 + diff 增量模式**。为 P1 五项做铺垫，本 RC 仅含 2 项 P0；完整 v0.14.0 等下个工作窗合并 P1 后再发 stable。

### Added
- **B-P0-1 `ff_formats` 能力元数据**：每个 format 自带 `capabilities` 列表（机器可读），让会话模型按能力选择 format：
  - `pdf` → `[furniture_strip, ocr, table, two_column]`
  - `pptx` → `[animation_order, speaker_notes, table]`
  - `epub` → `[chapter_split]`
  - `xlsx` → `[multi_sheet]`
  - `odt/ods/odp` → `[table]`
  - 数据来源：自动扫描 `parsers/*.py` 类真实方法名（`_extract_animations`/`_parse_ncx`/`_extract_table`/...），不依赖静态字典——自动反映 parser 代码真实能力
  - 新模块 `core/format_capabilities.py`
- **B-P0-2 `ff_diff` 增量模式**：
  - 新参数 `--against-dir <dir>`：与 dir 内同 stem 文件做 diff（path_a 可省，自动从 dir 找）
  - 新参数 `--since-mtime <ts>`：仅处理 path_b mtime >= 此 Unix timestamp 的文件
  - 抽出 `_compute_diff` 共享函数（单文件模式 + 增量模式都用）
- 新单测 `test/unit/test_format_capabilities.py` 11 项（probe 注册 + build_format_details + capability 检测）
- 新单测 `TestR14DiffIncremental` 6 项（against_dir stem 匹配 / 显式 path_a 优先 / 缺 stem 报错 / since-mtime 过滤 / 类型校验 / 0 等价不过滤）

### Changed
- **CLI 顺序变更**：`formatforge diff` 现在 `path_b path_a`（argparse 限制：optional+required positional+中间 option 会失败）
- `_resolve_paths` 容错：JS 端或测试传反顺序时自动检测并互换（path_a 是文件 path_b 不是 → 互换）
- CLI 注册注释解释 argparse 限制 + 共享 `_compute_diff` 抽出
- SKILL.md `ff_formats` 条目加 capabilities 字段说明

### Notes
- **本 RC 仅含 2 项 P0**，未含完整 v0.14.0 计划的所有 5 项 P1（retention 降噪 / TTL 预览 / 动态权重 / OCR 漏判 / markdown 分段优先）——下个工作窗继续
- npm 上**不发布 0.14.0-rc.1**（RC 标签会让 npm dist-tag 混乱）；只走 PR + GitHub Release，不打 npm。完整 v0.14.0 stable 才上 npm

### Tests
- 538 → **555 passed**（+17：B-P0-1 11 项 + B-P0-2 6 项）
- ruff ✓ · format ✓ · mypy ✓（49 source files 0 issues）
- Node `test-local.mjs` / `test-inbox.mjs` / `test-manifest.mjs` / `test-truncate-consistency.mjs` 全过

## [0.13.0] - 2026-08-31 — 封口批（v1.0 前 P0/P1 修复）

> 基线：v0.12.0（537 测试） → v0.13.0（538 测试）
> 主题：清理 v0.10-v0.12 累积的协议不一致 + 文档漂移，为 v1.0 协议冻结做准备

### Added
- **A1**：`packages/dsh-formatforge/tools/_truncate.mjs` 新模块——`renderTruncate(text, cap)` + `smartTruncate(text, maxChars, start)`，供 translate.mjs / result.mjs 共用
- **A3**：`formatforge batch` CLI + `ff_batch` 工具新增 `--quality` / `--encoding` / `--language` 三个 flag，与 `ff_translate` 对齐；批量锻造出的 markdown 现在带 enhance 提示与会话模型目标语 metadata
- **B3**：单测 `tests/test_pipeline_steps.py::TestBuildResultStep::test_builds_result_when_decision_noop`——覆盖 `conversion_needed=False` 路径走 `BuildResultStep` 不崩的回归保护
- **C1**：`renderTruncate` 抽出共用——render 层兜底截断走「段落 > 行 > 硬切」语义，避免切碎代码块/表格
- **D1**：`SKILL.md` frontmatter 补 `version: 0.13.0` + `updated: 2026-08-31`；底部版本号从 v0.9.0（4 个版本没改）→ v0.13.0；description 增 `ff_diff` 描述
- **G1**：`core/decision_engine.py::ConversionDecision` docstring 扩充——标明 `strategies` 字段是「候选策略列表」（按序考虑）而非「已执行的策略」，避免会话模型误解
- **跨语言一致性测试**：`packages/dsh-formatforge/test/test-truncate-consistency.mjs`——JS smartTruncate 与 Python `core/utils.py::smart_truncate` 在 9 组样例上 byte-equal 对比，未来任一侧改算法即漂移自动捕获

### Changed
- **A1**：translate.mjs 多文件分页字段从 `data.meta.next_offset` → `data.paging.next_offset`（与单文件路径统一）；render 分页提示也改读 `data.paging.next_offset`
- **A3**：`formatforge/__main__.py::cmd_translate_main` 返回签名从 `(content, meta)` → `(content, meta, enhance | None)`；quality/encoding/language/custom_prompt 参数透传到 Python CLI
- **B1**：`packages/dsh-formatforge/tools/diff.mjs` 在 `execute` 开头复用 `validateLocalFile` 对 `path_a`/`path_b` 做 size clamp（防 OOM 大文件）
- **B2**：`services/inbox-watcher.mjs` 与 `formatforge/batch.py` 的 `KNOWN_EXT` 同步移除 `.doc`（无 Python doc 解析器，移除假阳性）
- **C6**：`packages/dsh-formatforge/tools/result.mjs` 单文件查找删除 `names.find((n) => n.includes(rawId))` 兜底（id="abc" 误命中 xxxabcxxx.ff.json 的潜在 bug）；改为精确 `resultId` JSON 头匹配

### Fixed
- **测试健壮性**：`tests/unit/test_cli_protocol.py` 的 `TestR11XlsxSchema` / `TestR11DocxRevisions` / `TestR11PptxAnimations` 加 `pytest.importorskip`——venv 漂移（缺 openpyxl/docx/pptx）从「fail 成 ERROR」降级为「skip」

### Tests
- 537 → **538 passed**（+1：B3 回归测试）
- ruff ✓ · format ✓（54 files already formatted） · mypy ✓（48 files 0 issues）
- bandit：0 High（CI threshold `-ll` 允许 Medium/Low warning）
- Node `test-local.mjs` / `test-inbox.mjs` / `test-manifest.mjs` / `test-truncate-consistency.mjs`（新增）全过
- `scripts/dev.py --quick` 全套通过

## [0.12.0] - 2026-08-28 — 第三波战略工具（ff_diff 文件对比）

### Added
- **B10 `ff_diff` 工具**（`tools/diff.mjs` + CLI `diff` 子命令 `formatforge/diff.py`）：
  - 逐行 LCS diff（difflib.SequenceMatcher），输出 unified diff 格式
  - 参数：path_a（旧版）、path_b（新版）、format（中间格式）、context_lines、max_chars
  - 返回：additions / deletions / unchanged_count / similarity / diff_preview
  - 任意格式可对比（先走 translate 转 text，PDF/DOCX 也能 diff）
  - 文件不存在 → file_not_found；转换失败 → parse_failed
- SKILL.md 工具清单加 `ff_diff`
- 测试：TestR12Diff 4 项（简单版本 / 相同文件 / 缺文件 / PDF 自比）

### Changed
- `formatforge/__main__.py`：注册 diff 子命令
- `packages/dsh-formatforge/index.mjs`：注册 ff_diff（5 工具：ff_translate/ff_formats/ff_result/ff_batch/ff_diff）
- `test-local.mjs` 工具数断言 4→5

### Fixed
- `_read_text_lines` 处理 translate_file_data 返回 dict（协议 data 字段）而非字符串

### Tests
- 537/537 passed（533 → 537，+4）· ruff ✓ · format ✓ · mypy 48 文件 0 错

## [0.11.0] - 2026-08-28 — 第二波场景深耕（CSV/XLSX schema + DOCX 修订 + EPUB 章节 + PPTX 动画）

### Added
- **B1 CSV/XLSX/SQL schema 推断 + 前 N 行预览**（`core/conversion_strategies.py`）：
  - 类型判定：integer / float / date / boolean / string
  - 整数/浮点合并判定（混小数点整列 → float）
  - `structured_data.schema` 顶层汇总 + 每表 `tables[i].schema` + `preview_rows`（前 5 行）
  - CLI `--type type` 输出 `meta.schema` / `data.structured_data.schema`
- **B5 DOCX 修订追踪**（`parsers/docx_parser.py`）：w:ins / w:del 抽出到 `PageContent.metadata.revisions`，
  含 author/date/text。python-docx 默认忽略 w:ins/w:del 文本，B5 显式 iter 这两个 tag。
- **B8 EPUB 章节拆分 + NCX 标题**（`parsers/epub_parser.py`）：
  - `_parse_ncx` 解析 NCX toc.ncx → navPoint.title
  - 通过 manifest 反查把 spine itemref idref 映射回 NCX 章节标题
  - element metadata.chapter_title 填充章节名
- **B6 PPTX 动画顺序**（`parsers/pptx_parser.py`）：
  - `_extract_animations` 扫 p:timing/p:par 节点
  - 返回 [{index, shape_id, shape_name, effect_type, delay_ms}, ...] 按播放顺序
  - 讲者备注（notes_slide）早已支持，B6 加补动画（观望池 PPTX 深度达标）

### Changed
- `formatforge/__main__.py` cmd_translate：把 `result.structuredData` 透传到 `data.structured_data`（B1 CLI 暴露）
- `core/conversion_strategies.py` TableExtractionStrategy：`tables[].data` 不再含 header（挪到 `headers` 字段）

### Fixed
- parser 在 EPUB 缺 NCX 时不报错（_parse_ncx 异常被吞 + log.debug）

### Tests
- 533/533 passed（509 → 533，+24 增量：B1 CSV/XLSX 3 项、B5 DOCX 2 项、B8 EPUB 2 项、B6 PPTX 2 项 + 测试 fixture）
- ruff ✓ · format ✓ · mypy 47 文件 0 错

## [0.10.0] - 2026-08-28 — 第一波新功能（ff_batch / language / output-file / formats 过滤）

### Added
- **B3 ff_batch 工具**（`tools/batch.mjs`）：批量锻造，包装 Python CLI `batch` 子命令
  - 参数：source（目录/glob）、out、format、type、workers（1-8）、recursive、force、pages
  - 输出：每文件结果 + 汇总报告 `_batch_report.json`（总/成功/失败/跳过/平均置信度/总耗时）
  - 续跑：产物比源新 → 跳过；空目录 → 仍写报告（exit=1 提示无匹配）
- **B9 `--language` 目标语言 metadata**：ISO 639-1 代码（如 `zh` / `en` / `ja` / `zh-cn`）
  - CLI：写入 `meta.target_language` + `enhance.hint`（提示会话模型按此语种整理）
  - 工具：ff_translate 直接透传
- **A9 `--output-file` 路径**：content 另存到指定文件，stdout 协议 JSON 不变（meta.output_file 字段标记）
- **A10 `formats --category` 过滤**：6 类（document/data/email/image/archive/audio）
  - 输出加 `categories` 列表供会话模型发现可用分类
- `scripts/dev.py`：一键开发脚本（pytest+ruff+format+mypy+烟雾测）
- 8 个 CLI 协议护栏（TestR10LanguageFlag / TestR10OutputFile / TestR10FormatsCategory / TestR10Batch）

### Changed
- `formatforge/__main__.py` cmd_translate：`data` 类型推断加固（cast dict[str, Any] + type:ignore）
- `formatforge/batch.py` 空源返回 exit=1（旧契约）但仍写报告（契约级 _batch_report.json 必存在）

### Fixed
- mypy 在 cmd_translate 多个 dict[str, Any] union 操作时报类型冲突（已 cast 化解）

## [0.9.1] - 2026-08-28 — R3 协作面护栏补丁

### Added
- SKILL.md 同步 R3 用法：ff_result 三工具说明、`--encoding` 参数、retry_with 重调对照表、
  R3.1 auto 智能默认提示、R3.2 ids 批量取回、R3.4 schema -33.3% 标注
- CLI 协议护栏 `TestR3SmartDefault`：auto 模式自动开启 quality（无需 --quality）+ meta.quality_auto 契约字段
- CLI 协议护栏 `TestR3EncodingRetry`：`--encoding gbk` 透传解码 + retry_with 闭环
- CLI 协议护栏 `TestR3MarkdownStructureField`：meta.structured 字段守住
- test-inbox.mjs R3.2 断言：onDone payload.resultId 必须以 `cvt` 开头

### Changed
- `formatforge/__main__.py` cmd_translate 入口：R3.1 智能默认（auto 模式自动 want_quality=True）+
  meta.quality_auto 标记字段（让会话模型知道 quality 是自动开启的）
- `packages/dsh-formatforge/test-inbox.mjs` 关掉 TTL（`FF_INBOX_TTL_DAYS=999`）—— fixture mtime
  古老会被 retention 误判过期；测试只验 R3.2 行为不测 retention

### Fixed
- v0.9.0 时 SKILL.md 描述仅列两工具（缺 ff_result）；R3.2 ids 数组用法无文档

## [0.9.0] - 2026-08-28 — R3 协作面

### Added
- R3.1 ff_translate 智能默认：`--type auto` 自动附带 `--quality`（低置信自动产出 actions），render 加 200 字头部预览
- R3.2 ff_result 批量取回：新增 `ids` 数组参数一次多产物 + 通知附 `resultId`（inbox 消息末尾 `- 结果 id：xxx`）
- R3.3 自愈闭环实测：CLI `--encoding` 透传（gbk/latin-1）+ ConvertStep 优先 conversion_needed 兜底 + raw 文本透传以让 quality 扫 FFFD/mojibake
- R3.4 工具描述瘦身：schema 体积 2951 → 1969 chars（削减 33.3%，目标 ≥30%）
- `scripts/measure_r3_selfheal.py` — 自愈闭环实测脚本（3 劣化样本集）
- `test/fixtures/golden/r3_selfheal.json` — R3.3 验收快照（self-heal 3/3 = 100%）

### Changed
- 协议：`ff_result` 批量响应 `data.batch=true / count / ok_count / results[]`
- 通知：FormatForge inbox watcher 携带 `resultId` 给 result.mjs 直接取回
- `core/pipeline_steps.ConvertStep.process()` 重构：优先级 decision→parsed→data→fallback
- `parsers/txt_parser.TXTParser.parse()` 支持 `encoding` 覆写（自愈重试路径）
- `formatforge/__main__.py`：新增 `--encoding` 参数透传 + CLI `quality` 默认在 auto 模式自动开启
- 测试：test_ocr_engine 三处跟随新默认引擎；test_pipeline_steps 增加 raw 透传覆盖

## [0.8.0] - 2026-08-27 — R2 解析质量纵深

### Added
- **R2.1 OCR 管线贯通**：修复「use_ocr 参数透传但引擎从未挂载」的主干断线（PDFParser 注册时 ocr_engine 恒为 None）；新增 RapidOCR (ONNX Runtime) 后端（Windows CPU 首选、真实逐行置信度、兼容新旧两代 API），默认引擎优先级 rapidocr > paddleocr > tesseract > easyocr；修复 pdfplumber 调色板 PNG（mode=P）导致 RapidOCR 返回空的问题（自动转 RGB 重试）；OCR 文字层合并去重（相似行不重复）
- **R2.2 表格语义**：新模块 core/table_semantics.py——None=合并覆盖（继承宿主值）vs ''=真空单元格的语义区分；数值列自动右对齐（markdown `---:`）；跨页表格续接合并（无表头续表整表并入 / 重复表头自动跳过）；原始 grid 随 metadata 携带
- **R2.3 结构保真**：新模块 core/structure_fidelity.py——字号/加粗 → h1-h4 标题层级（全书正文字号中位数基准）；行首 x0 几何聚类 → 列表嵌套层级（最多 4 级）；目录行识别 → `[标题](#锚点)`；markdown 输出时自动按层级渲染，OCR 行永不误判标题
- golden fixture 机制：test/fixtures/golden/ 确定性语料（5 份 PDF：扫描件/水印混排/跨页表格/合并单元格/结构层级）+ 期望快照 + FF_UPDATE_GOLDEN=1 显式刷新；测量脚本 scripts/measure_r2_baseline.py 持续跟踪 enhance 触发率
- 新增 16 项 R2 测试（OCR 4 + 结构 7 + 表格 4 + 触发率 2），总测试 488 → 509

### Changed
- OCR 引擎默认从「恒 tesseract」改为按可用性优先级自动选择；test_ocr_engine 初始化用例跟随新语义
- enhance 触发率（golden 语料）：OCR 接线前 20%（扫描件 image_only）→ 接线后 0%；误判水印文档为 image_only 的问题已修复

> 验收对比 ROADMAP §2：image_only/table_sparse enhance 触发率下降 ≥30% 达成（样本集 20% → 0%）。

## [0.7.1] - 2026-08-27 — 上榜落地（R1 快赢）

### Added
- storefront 截图：assets/ 三张 dsh web 实拍（拖拽 toast / 收件箱产物 / 会话通知），按新约定在 `packages/dsh-formatforge/screenshots.json` 声明，README 嵌图
- GitHub issue 模板：bug report（强制附 verify-install.py 输出栏）+ feature request

### Changed
- 版本号统一：单一来源 `formatforge/__version__.py`（0.7.1），pyproject 动态读取，CLI `version` 命令同步（清除 3.0.0 历史漂移）；npm 包 0.7.0 → 0.7.1
- `scripts/rebuild-plugin-junctions.py`：候选源加入 npx cache 自动发现（宿主重装清缓存后可自愈）
- `scripts/take-screenshots.py`：修复 WS 握手空 query 尾巴（500 拒握手）与 8 字节掩码两处 bug；CDP 改用 Chrome For Testing daemon(:9222)——Edge 新配 profile 会强装扩展+首启弹窗，不可用

> 注：v0.3–v0.7 的插件化演进未记入本文件（见 EVOLUTION_PLAN.md / git log），自本版恢复维护。

## [2.1.0] - 2026-07-13 — DFT 1.5 安全硬化

### Added
- `__version__.py` 单一版本号来源
- `core/auth.py` API_KEY 认证模块（HMAC 时序安全比对）
- `core/security.py` 加固：NUL/UNC/NTFS 流/8.3 短文件名拦截
- `core/security.py` SSRF 用 `ipaddress` 模块替换字符串前缀比对
- `core/content_cache.py` JSON 序列化磁盘缓存（取代 pickle）
- `pyproject.toml` optional-dependencies groups: `[ocr]` / `[archive]` / `[richtext]` / `[all]`
- README「安全」章节 + 详细认证说明

### Changed
- 版本号统一为 `2.1.0`（`pyproject.toml` / `main.py` / `api/v2.py` / `__version__.py`）
- `ALLOWED_ORIGINS` 默认值改为 `["http://localhost:3000"]`；`["*"]` 自动 `allow_credentials=False`
- `validate_mime_type(None)` 改为 False
- 错误响应在生产模式不泄漏堆栈
- 11 个写接口加 `Depends(verify_api_key)`

### Fixed
- `build-backend` 错误值 `setuptools.backends._legacy:_Backend` → `setuptools.build_meta`
- `core/input_adapters.py` `List` 导入缺失
- PDF mock 路径：新增 `_PdfplumberStub` 模块级占位符

### Security
- SSRF 防护：拦截 `127.1` / `2130706433` / `0x7f000001` / `[::1]` / `file:///etc/passwd`
- CORS：`allow_origins=["*"]` + `allow_credentials=True` 同时存在 → 自动改为 `False`
- 路径遍历：NUL 字节、UNC 路径、NTFS 备用数据流、8.3 短文件名
- 磁盘缓存 `pickle.load` → `json.loads`，消除反序列化任意代码漏洞

### Tests
- 全量 pytest：**`635 passed, 5 skipped, 0 failed`**（v1.4: 17 failed / 618 passed）
- `TestPDFParserMock` 7 个 mock 测试从全失败恢复
- 新增 prod 模式回归测试（API_KEY 启用场景）

## [1.4.0] - 2026-06-13

详见 README §更新日志

## [1.3.0] - 2026-06-13

详见 README §更新日志

## [1.2.0] - 2026-06-12

详见 README §更新日志

## [1.1.0] - 2026-06-12

详见 README §更新日志

[Unreleased]: https://github.com/Tianbuyu/data-format-translator/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/Tianbuyu/data-format-translator/releases/tag/v2.1.0