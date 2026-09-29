# ROADMAP.md — DSH-FormatForge 后续开发计划

> 重写：2026-09-30 · 基线：**v2.0.0**（npm `@tianbuyu-wwx/dsh-formatforge@2.0.0`）
> 依据：[SELF_CHECK_v2.0.0.md](SELF_CHECK_v2.0.0.md)（实机自检，非推测）
> 主题转向：**从「能转」到「可信」，再到「好用」**

---

## 0. 现状快照（v2.0.0）

| 维度 | 状态 |
|---|---|
| 宿主 | DeepSeek Harness **0.2.0-rc.2**（peer 区间 `>=0.2.0-rc.1 <0.3.0-0`） |
| 输入格式 | 34 种 · 6 大分类 |
| 入口 | 拖拽（浏览器上传 + 收件箱 watcher）· 5 工具（translate/formats/result/batch/diff）· CLI |
| 解析质量 | docx/pptx/xlsx/pdf/epub/odt 质量高；PDF `confidence=0.92`（含表格与双栏） |
| 质量体系 | 5 维评分 + enhance 三触发（实测在低置信样本上正确触发） |
| 工程 | **564 tests** · CI **7/7** · 契约自检 **17/17** · mypy/ruff 全绿 |
| 协议 | `protocol/v1` 冻结未变 |
| 历史任务 | R1 收录 · R2 解析纵深 · R3 协作面 · R4 观望池 · R5 巡检 —— **全部完成**（见文末归档） |

**自检结论**：门禁层无问题；缺口全部在**产品体验层**，且以「静默错误」为主。

---

## 1. R6 · 用户体验优先（本轮主计划）

排序原则：**先消灭静默错误（信任）→ 再补历史与检索（好用）→ 再谈速度（爽）**。
理由：静默错误会让用户在不自知的情况下拿到错答案，伤害远大于慢。

### R6.1 可信度：消灭三个静默错误

| # | 项 | 现状 | 目标 | 预估 |
|---|---|---|---|---|
| R6.1.1 | **产物名冲突** | `ff_batch` 29 入 → 22 出，报告仍称「29/29 成功」；收件箱同病 | 产物名保留原扩展名（`book.epub.md`）；报告显式列出被覆盖项；收件箱改 `<name>.<ext>.ff.json` | 2h |
| R6.1.2 | **`parser` 字段语义** | 报的是 8 值粗枚举 `FileType`，`book.epub` 显示 `parser=txt` | `meta.parser` = 真实解析器类名；旧值降级为 `meta.file_type` 并走弃用期 | 3h |
| R6.1.3 | **假 confidence** | `striprtf` 缺失时输出原始 RTF，却报 `confidence=1.0` | 解析器无法处理 → `unsupported_format` 或 `enhance.low_confidence`；`ff_formats` 标注「可选依赖缺失，当前不可用」 | 3h |
| R6.1.4 | **临时名泄漏** | 结果里出现 `tmp2su4zugj.zip` / `tmpukd170ad.png` | 回填原始文件名（与 R6.2 的 `source_name` 同源） | 1h |
| R6.1.5 | **不支持拖入无反馈** | `.exe` 丢进收件箱：无产物、无 `.error.txt` | 写 `<name>.ff.error.txt`，并在 `ff_result {list:true}` 里可见失败项 | 1h |
| R6.1.6 | **CSV BOM** | `utf-8-sig` 文件表头残留 U+FEFF | 读取时剥离 BOM | 30m |

**验收**：构造一份「必须失败」的样本集（无依赖 RTF、无文字层 SVG、错扩展名），断言**没有任何一项返回 `ok:true` + `confidence≥0.9`**。

### R6.2 历史与检索：收件箱从「目录」升级为「库」

> 用户提出的「搞个数据库存放已上传的文件」——**方向对，但要连对地方**。

**先看实测**（复刻 `ff_result list` 的真实 I/O 路径）：

| 产物数 | `list()` | 体积 |
|---:|---:|---:|
| 100 | 4.5 ms | 0.2 MB |
| 1 000 | 33.8 ms | 2.4 MB |
| 5 000 | 241.9 ms | 12.0 MB |

**I/O 不是瓶颈。** 引入数据库的理由不是「快」，而是现在**根本没有**的四件事：全文检索、内容去重、来源溯源、结构化筛选；以及一个真实痛点——`list` 会把全部条目塞进模型上下文。

#### 推荐方案：SQLite（Python 侧写，Node 侧通过 CLI 读）

| 约束 | 结论 |
|---|---|
| 插件 npm 依赖必须保持 `{}` | ✅ 不引入任何 Node 依赖 |
| Python ≥3.10 已是硬需求 | ✅ `sqlite3` 是标准库，零新增依赖 |
| 产物必须人类可读 | ✅ `.ff.md` / `.ff.json` **继续留在磁盘上**，DB 只存元数据 + 索引 |
| Node 侧怎么读？ | ✅ 插件**本来就通过 spawn 调 Python CLI**；新增 `formatforge inbox <subcmd>` 即可，Node 侧不碰 SQLite |
| 需要全文检索 | ✅ FTS5（stdlib 自带；实现前先断言本机 `sqlite3` 编译含 FTS5） |

**Schema 草案**

```sql
CREATE TABLE results (
  id            TEXT PRIMARY KEY,   -- cvt20260930…（已有）
  source_name   TEXT NOT NULL,      -- 原始文件名  ← 修 R6.1.4
  source_path   TEXT,
  source_size   INTEGER,
  source_sha256 TEXT,               -- 内容去重    ← 修「同内容改名再转一遍」
  format        TEXT,               -- epub / xlsx …
  parser        TEXT,               -- 真实解析器  ← 修 R6.1.2
  confidence    REAL,
  enhance_reason TEXT,
  chars         INTEGER,
  elapsed_ms    INTEGER,
  json_path     TEXT, md_path TEXT, -- 产物仍在磁盘
  session_id    TEXT,               -- 溯源：哪个会话要的
  created_at    INTEGER NOT NULL,
  retired_at    INTEGER
);
CREATE INDEX idx_results_created ON results(created_at DESC);
CREATE INDEX idx_results_sha     ON results(source_sha256);
CREATE VIRTUAL TABLE results_fts USING fts5(id UNINDEXED, source_name, content);
```

**落点**：`<DSH_HOME>/formatforge/index.db`（与收件箱同级）。

**迁移**：首次启动扫描现有 `*.ff.json`，`INSERT OR IGNORE` 逐条回填——**幂等、非破坏、可随时删库重建**。

**解锁的体验**

| 能力 | 之前 | 之后 |
|---|---|---|
| 找一份旧结果 | 只能 `list` 全部翻 | `ff_result {search:"付款条款"}` |
| 列最近产物 | 全量返回，5000 行进上下文 | `ff_result {list:true, limit:20}` |
| 同内容重复拖入 | 再转一遍（实测确实重转） | 「已存在，id=…（3 天前）」秒回 |
| 知道这份是谁要的 | 无 | `session_id` 溯源 |
| 保留策略 | 只有 `.ff.retired.log` | `ff_result {stats:true}` 可见 |

**被否决的方案**

| 方案 | 否决理由 |
|---|---|
| 只加一个 JSON 索引文件 | 1 天可做、能解 `limit`，但没有 FTS、没有并发写保护；可作过渡，不建议终态 |
| Node 侧 `better-sqlite3` | 破坏「零 npm 依赖」，需原生编译，profile 安装变重 |
| 宿主 `dsh-storage` 服务 | 那是**会话存储**，随会话生命周期；插件产物要跨会话、跨 profile 存活，且必须人类可读可拷走 |

**分两步走**：先 `limit` + 内容哈希去重（半天，无 DB 也能做），再上 DB（1–2 天）。**每步都能独立交付体验提升**，不搞大爆炸。

### R6.3 速度：图片路径 5–8 秒

实测：`ImageParser.parse()` = **4.3 ms**，完整 CLI = **5300 ms**（关 OCR）/ **7898 ms**（开 OCR）。开销**不在解析器**。

| # | 项 | 做法 |
|---|---|---|
| R6.3.1 | 定位 | 对管线做一次干净的 `cProfile`（本次因 PowerShell 编码未取到） |
| R6.3.2 | OCR 判定前置 | 无 OCR 引擎时直接跳过 OCR 分支，别走一遍初始化再放弃 |
| R6.3.3 | 进程常驻（可选） | 每次工具调用约 0.5s 是 Python 冷启动地板；若 R6.3.1 显示仍是大头，再评估常驻 worker |
| R6.3.4 | 图片默认快路径 | 长宽/格式元信息 <100ms 返回；OCR 文本作为 `enhance` 按需触发 |

**验收**：4KB PNG 端到端 **< 1s**（含进程启动）。

### R6.4 交互细节

| # | 项 | 说明 |
|---|---|---|
| R6.4.1 | 批量报告可读性 | 现在 29 条平铺；改为「成功 N / 失败 M / 覆盖 K」+ 失败置顶 |
| R6.4.2 | 拖拽失败反馈 | 上传 415 已有 toast；补齐收件箱直投路径（与 R6.1.5 联动） |
| R6.4.3 | `enhance` 提示可执行性 | 现在 hint 是自然语言；补 `retry_with`（延续 R3.3 自愈闭环） |
| R6.4.4 | 进度可见 | 大文件/批量跑 100s 时用户只看到转圈 |

### R6.5 文档与工程健康

| # | 项 |
|---|---|
| R6.5.1 | README 测试数 `444` → 实际 `564`，改为一处引用 CI |
| R6.5.2 | ROADMAP 快照停在 v0.10.0 —— 本次已重写 |
| R6.5.3 | CHANGELOG 新旧产品线同号条目（`1.1.0`/`1.2.0`）加分隔说明 |
| R6.5.4 | 清理 `.mypy_cache`（75.9 MB）与根 `node_modules` junction；后者补进 `.gitignore` |
| R6.5.5 | 把本次 30 个 fixture 收进 `test/fixtures/matrix/` 作为回归语料（每修一个 bug 沉淀一个） |

---

## 2. 排期建议

| 阶段 | 内容 | 交付标准 |
|---|---|---|
| **第 1 天** | R6.1.1 + R6.1.2 + R6.1.6 | 批量不再覆盖；`parser` 可信；BOM 修复 |
| **第 2 天** | R6.1.3 + R6.1.4 + R6.1.5 | 「必须失败」样本集全绿：无一返回假置信度 |
| **第 3–4 天** | R6.3.1 → R6.3.2 → R6.3.4 | 图片端到端 < 1s |
| **第 2 周** | R6.2（先 `limit`+去重，后 SQLite） | `ff_result {search}` 可用；重复拖入秒回 |
| 持续 | R6.4 / R6.5 | 随每次发版带上 |

**版本号**：R6.1 → **v2.0.1**（信任修复；P0-3 通知修复已在线上）· R6.2 → **v2.1.0**（新能力，协议向后兼容）· R6.3 → **v2.1.x 或 v2.2.0**（视是否引入常驻 worker）

---

## 3. Non-goals（延续，不变）

- ❌ 云端 AI 增强 · ❌ Web 服务复活 · ❌ GUI 桌面端 · ❌ 出站网络 · ❌ 引入 Node 运行时依赖

---

## 附录：历史任务归档（R1–R5）

| 阶段 | 内容 | 结果 |
|---|---|---|
| R1 | 收录落地与生态反馈 | ✅ 上榜 · 截图 · issue 模板 |
| R2 | 解析质量纵深（OCR 管线 / 表格语义 / 长文档结构） | ✅ v0.8.0；golden 语料 enhance 触发率 20% → 0% |
| R3 | Agent 协作面（智能默认 / 批量取回 / 自愈闭环 / schema 瘦身） | ✅ v0.9.0；一次成功率 100%，schema −33.3% |
| R4 | 观望池评估（URL 抓取 / 截图直投 / 遥测 / 连接器） | 未触发立项信号 |
| R5 | 工程巡检（dependabot / 宿主升级回归 / fixture 扩充 / 性能基线） | 持续；本自检报告即一次巡检 |

> 原 ROADMAP 的 R1–R5 明细已并入本节。`PLUGIN_PLAN.md`（插件化实施）与 `EVOLUTION_PLAN.md`（v0.4–v0.7 演进）作为历史文档保留。
