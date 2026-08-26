# EVOLUTION_PLAN.md — DSH-FormatForge 功能演进方案

> 状态：**全部完成** ✅（2026-08-25，v0.4.0 / v0.5.0 / v0.6.0 / v0.7.0 四批全部交付；N2 拍板不做）
> 拍板：四批认可；N2 不做；每批结束 push GitHub（main + tag）
> 基线：v0.3.3 · 444 tests · CI 7/7 · npm `@tianbuyu-wwx/dsh-formatforge` · awesome-list PR #3113（gate 全绿）
> 现状盘点数据全部来自实机测量（2026-08-25），非估算。

---

## 0. 现状基线

| 维度 | 实测值 |
|---|---|
| 输入格式 | 34 种（pdf/docx/pptx/xlsx/csv/eml/msg/epub/toml/yaml/xml/sql/latex/rtf/srt/odt·ods·odp/图×7/压缩包×3/audio/binary…） |
| 输出格式 | json / markdown / html / text |
| 转换策略 | 7 个（auto_detect/text/structured/table/image_desc/ocr/media_index） |
| 入口通道 | ① 网页拖拽（client→POST /formatforge/upload→inbox watcher）② 对话工具 ff_translate（多文件/glob/分页）③ CLI |
| 质量体系 | 5 维评分 + grade + enhance 三触发（image_only/low_confidence/table_sparse） |
| OCR | tesseract / paddleocr / easyocr 本地可选 |
| 测试 | 444 passed / CI 7 job 全绿 |

### 结构性短板（本方案要修的根）

| # | 短板 | 证据 |
|---|---|---|
| S1 | enhance 判定在 CLI 层（`__main__.py:48 _build_enhance_hint`），Node 工具与 inbox 通道拿不到 enhance | 只有 `python -m formatforge` 直连才有；ff_translate 结果无此字段 |
| S2 | 无产物消费工具——inbox 锻造结果只能靠 agent 自己 read 文件 | notify 只给路径；子代理会话没有 ff_result 可调 |
| S3 | 分页按字符硬切——markdown 表格/代码块被拦腰截断 | translate.mjs max_chars 直接 slice |
| S4 | PDF header/footer 未剔除（models.py:237 TODO）；双栏 PDF 阅读序错乱 | 长期存在的解析质量问题 |
| S5 | 错误信息中英混杂、无稳定 error code | 协议契约里 error 形状未固化枚举 |
| S6 | inbox 无 TTL/容量管理——长期使用无限增长 | watcher 只写不删 |

---

## 1. 第一批 · 修正性工作（~1 天）

### M1 enhance 判定下沉管线层 ⭐ 根修复
- **现状**：`formatforge/__main__.py::_build_enhance_hint(parsed_file, confidence)` 只在 CLI 出口调用。
- **目标**：逻辑移入 `core/pipeline_steps.py::BuildResultStep`（管线唯一出口），结果写入 `ConvertResultData.enhance`。
- **改动面**：
  - 新增 `core/enhance.py`：`build_enhance_hint(parsed_file, confidence, quality=None) -> EnhanceHint | None`（三触发规则原样搬迁，含阈值常量化）
  - `core/models.py`：`ConvertResultData` 加 `enhance: EnhanceHint | None = None`
  - `BuildResultStep.process` 调用并挂载
  - CLI `_build_enhance_hint` 改为读 `result.enhance`（保留 `--no-enhance-hint`）
  - `tools/translate.mjs` render 层透传 `data.enhance`
  - inbox-watcher 的 `.ff.json` 自动携带
- **验收**：
  - 单测：image_only / low_confidence / table_sparse 三触发 + 不触发，四用例直测管线出口
  - e2e：`node test-local.mjs` 中 ff_translate 扫描件路径返回 `data.enhance.reason == 'image_only'`
- **风险**：低。纯搬迁，阈值不变。

### E1 分页按结构截断
- **现状**：`translate.mjs` 对 content 做 `slice(offset, offset+max_chars)`。
- **目标**：新增 `core/utils.py::smart_truncate(text, max_chars, start)` —— 优先级：段落边界(`\n\n`) > 行边界(`\n`) > 硬切；返回 `(chunk, next_offset)`。JS 侧同逻辑镜像实现（避免跨进程往返）。
- **验收**：单测覆盖「表格行中间不切、代码块围栏不切开、恰好 max_chars」；e2e 大 markdown 分页两次拼回全文无损。

### M4 错误协议固化
- **目标**：`core/errors.py` 定义错误码枚举：`file_not_found / is_directory / too_large / unsupported_format / parse_failed / timeout / permission_denied / internal`。CLI 与 Node runner 双侧映射统一；message 保持中英双语一行。
- **验收**：test_cli_protocol 增加「每类错误 → code 断言」；PLUGIN_PLAN §4.3 协议契约同步更新。

### E5 inbox TTL 与容量管理
- **设计**：watcher 每轮扫描顺带清理——`FF_INBOX_TTL_DAYS=7`、`FF_INBOX_MAX_MB=500`（可关）；LRU 按 mtime 删 `.ff.*` 及对应源文件；删除前写一条会话通知（批量合并为一条）。
- **验收**：单测伪造过期文件验证清理顺序与通知内容；默认配置下现有测试目录不受影响。

---

## 2. 第二批 · 闭环补全（~2 天）

### N1 ff_result 工具 ⭐ 闭环最后一环
- **设计**：
  - `ff_result` 参数：`id?`（result_id 或 inbox 文件名）、`list?`(bool)、`max_chars?`、`offset?`。
  - list 模式：扫描 inbox 返回 `[{id, file, forged_at, parser, confidence, size}]`（读 `.ff.json` 头部元数据，不载全文）。
  - 取模式：按 id 定位 `.ff.json`，返回 content（复用 E1 分页）。
  - 安全：仅读 inbox 目录白名单内文件；路径穿越拒绝。
- **验收**：本地 stub e2e（拖入→list 可见→取回正文与 ff.md 一致）；schema 过 DSL 四坑自检。
- **依赖**：E1（分页）、M1（.ff.json 带 enhance）。

### E4 质量报告可操作化
- **设计**：`QualityReport.warnings[]` 每条升级为 `{code, message, suggestion, retry_with?}`；
  - 例：编码疑似 GBK → `retry_with: {"encoding": "gbk"}`；
  - 表格稀疏 → `retry_with: {"conversion_type": "table"}`；
  - 页缺失 → 建议 `--pages` 参数（若引入，见 E2）。
- **消费方**：SKILL.md 增补一段「看到 retry_with 时直接带参重调 ff_translate」的指导。
- **验收**：构造三种劣化输入，断言 suggestion/retry_with 正确；SKILL.md 更新随 PR 提交。

### E3 表格抽取升级
- **范围**：xlsx 多 sheet（每 sheet 一个二级标题+表格，sheet 名入锚点）；合并单元格值填充到每个覆盖格；数字/日期类型保真（`001` 保持字符串）。
- **改动面**：`parsers/data_parser.py`（xlsx 分支）+ TableExtractionStrategy；openpyxl 已是依赖，零新增。
- **验收**：三 sheet 含合并单元格与 `001` 样本的 fixture；table_sparse 触发率对比记录进 PR 描述。

---

## 3. 第三批 · PDF 深度增强（~2 天，独立成批）

### E2 PDF 深度增强
1. **header/footer 剔除**（补 models.py:237 TODO）：跨页重复且位于页首/尾 ≤3 行的文本行识别为 furniture，默认剔除，`quality.warnings` 记录剔除统计；`keep_furniture=true` 可关。
2. **双栏阅读序**：基于词框 x 坐标聚类分栏（左半/右半阈值可配），按栏序拼接；仅当页宽>高且检测到两列分布时启用。
3. **页选择参数**：CLI 与 ff_translate 加 `pages="1-3,7"`（解析器层过滤，省时省 token）。
- **改动面**：`parsers/pdf_parser.py`、`core/models.py`（PageContent.furniture 移除）、策略层透传。
- **验收**：
  - fixture：双栏论文页、带页眉页脚的报表各一；
  - 指标：furniture 剔除准确率（人工标注 10 页样本 ≥90%）；双栏文本序与原稿一致；
  - 回归：现有 pdf 测试全绿，`complex_test.pdf` 输出 diff 人工审阅。
- **风险**：pypdf 版本行为差异——锁定已验证版本区间；双栏误判兜底=关闭该特性开关。

---

## 4. 第四批 · 新通道与工程健康（~2 天）

### N2 URL 抓取转换（需拍板：涉及网络请求边界）
- **形态**：`ff_fetch(url, format?, max_chars?, offset?)` 新工具；readability 类正文抽取（纯 Python 实现 trafilatura 或自写启发式，禁 headless）。
- **安全边界（对齐 v2.x 时代教训）**：仅 http/https；私网/环回/link-local IP 黑名单（DNS 解析后二次校验防 rebinding）；30s 超时；5MB 上限；Content-Type 白名单（text/html）。
- **验收**：SSRF 用例表（127.0.0.1/169.254.169.254/内网域名解析后拦截）；正常文章抽取正文完整率抽查。
- **默认不做，除非明确批准**——这是唯一引入出站网络请求的功能。

### N3 批量转换命令
- `formatforge batch <dir|glob> --to markdown --out out/ [--workers 4] [--recursive]`
- 汇总报告：成功/失败/耗时/平均置信度；失败清单附 error code。
- 并发用 ThreadPoolExecutor（解析是 CPU-bound，进程池留给未来）。
- **验收**：50 文件混合目录端到端；中断续跑（跳过已有同名产物）。

### M2 安装验证自动化
- `scripts/verify-install.py`：boot 日志 grep formatforge 注册行 → dispatch_probe ff_formats → client.js rev 存在性 → inbox 写入冒烟。
- CI 增加一个 optional job（手动触发 workflow_dispatch），在 ubuntu 起 dsh web 完整跑一遍。
- **动机**：宿主每次升级手工验收必漏；这次把 Phase 6 三道闸的经验固化。

### M3 依赖健康
- 启用 dependabot（pip + npm + actions 三生态，月频）；
- pypdf/python-docx/openpyxl 上限约束复核（pyproject 加 `<上限>` 防大版本破坏）。

---

## 5. 观望池（有信号再做）

| 项 | 触发条件 |
|---|---|
| N2 URL 抓取转换 | **已拍板不做**（2026-08-25）；若未来用户强需求再重新评审安全边界 |
| N4 截图/剪贴板直投 | 用户提出 Windows 截图取字需求 ≥2 次 |
| E6 本地遥测 stats | 收录后 issue 里出现「哪个格式支持最好」类问题 |
| Office/云盘源连接器 | 有用户要求从 OneDrive/GDrive 直转 |
| 多语言界面 | 英文用户反馈看不懂中文日志 |

---

## 6. 排期总览

| 批次 | 内容 | 预估 | 交付物 |
|---|---|---|---|
| 一 | M1 + E1 + M4 + E5 | ~1 天 | v0.4.0（enhance 全通道 + 结构化分页 + 错误码 + inbox 管理） |
| 二 | N1 + E4 + E3 | ~2 天 | v0.5.0（ff_result + 可操作质量报告 + 表格升级） |
| 三 | E2 | ~2 天 | v0.6.0（PDF 深度增强） |
| 四 | N3 + M2 + M3 | ~2 天 | v0.7.0（batch + 安装自检 + 依赖健康） |

> **拍板记录（2026-08-25）**：四批范围/顺序认可；**N2（URL 抓取）不做**，从第四批移除并转入 §5 观望池。
> **流程约定**：每批结束时除发版外，**必须 push 到 GitHub**（main 分支 + 对应 tag），保证仓库与 npm 版本始终同步。

每批次固定节奏：TDD → 三门禁全绿 → dsh web 实机验收 → npm 发布 → awesome-list 条目描述如涉及能力变化则同步更新。

## 7. 明确不做（Non-goals）

- ❌ 云端 AI 增强（决策 2 既定：模型增强永远属于会话模型）
- ❌ Web 服务形态复活（冻结于 v2.1.0-ci-green）
- ❌ GUI 桌面端
- ❌ 除 N2 外的任何出站网络能力（N2 本身也默认搁置）
