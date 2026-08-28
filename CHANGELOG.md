# 更新日志 (Changelog)

本项目的所有重要变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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