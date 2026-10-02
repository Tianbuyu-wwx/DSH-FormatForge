# UI + 数据库实施计划（FormatForge v2.2 / v2.3）

> 状态：**已拍板并实施（v3.0.0）**
> 拍板结果：**只做面板**（不做 `main` 整窗口页、不做自托管页）· 持久化分层**由实现方定**（最终选择"偏好与索引同库"，理由见 §3.2）· **从零手写**（不复活冻结前端）· **一次性大版本**（3.0.0）
> 实现进度：**P-1 ✅（含实测确认的 `ff_result` 字段错配修复）· P0 ✅ · P1 ✅** · P2（整窗口页/自托管页）**按拍板未做** · P3 队列 / P4 打磨 未做
> 实测证据与取舍见 §1.4 / §3.2 与 [CHANGELOG.md](CHANGELOG.md) v3.0.0 节
> 起草：2026-10-02 · 基线：`main @ bd1eb73`（v2.0.2，CI 7/7 绿）
> 关系：**本文件细化并取代** [ROADMAP.md](ROADMAP.md) R6.2 的旧范围；R6.1/R6.3/R6.4/R6.5 不受影响。
> 前置阅读：`SELF_CHECK_v2.0.0.md` P2-1（用户提出的"数据库"就是指这里）

---

## 0. TL;DR

| 问题 | 结论 |
|---|---|
| 做什么 | ① 收件箱从「目录」升级为 **SQLite 库**（元数据 + 全文检索 + 溯源 + 去重）② 在此基础上做 **独立 UI**（DSH 右侧面板 + **`main` 整窗口页面**，同一份构建产物再挂一个自托管页） |
| 要推翻什么 | 现有三处**明示非目标**：`README.md:17`「无 Web 界面」、`ROADMAP.md:167`「❌ Web 服务复活」、`EVOLUTION_PLAN.md:162`。这是一次**产品策略变更**，必须显式记录，不能偷偷做 |
| 技术底色 | DB：**分层**——设置/小元数据走平台公开契约 `ctx.storageDomain`；产物索引与全文检索走 **SQLite**（Python stdlib 写 + Node 内置 `node:sqlite` 读）。UI：宿主插槽（`ctx.slots`，含 `main` 整窗口页）+ 可选自托管页（`webServer.register({kind:"prefix"})`） |
| 关键实测 | ① 宿主进程 = **Node 24.18.1 / Electron 44 / ABI 149**，`node:sqlite` **免 flag 可用**（平台自己就在用：`dsh-session-query-sqlite` + FTS5）；② FTS5 `trigram` 在 Python 3.45.3 与 Node 3.51.3 都可用，而 `unicode61` 对中文**命中为 0**（必须 trigram）；③ 平台确有插件级持久化 `ctx.storageDomain`（公开契约，**无迁移**、整域驻内存）；④ 71 个 shipped client bundle 共 **68 个可注入插槽**，注册到未声明插槽**加载期抛错** |
| 必须先修 | `ff_result` 读的字段（`data.convertedContent`/`data.resultId`/`data.fileInfo.*`）与 CLI 实际写出的字段（`data.content`/`data.meta.result_id`、无 `fileInfo`）**不一致** —— **已用真实产物实测确认**：`ff_result {id}` 取回的正文恒为空、`parser` 恒为 `?`。UI/DB 都建立在这层字段上，**P-1.1 必须先修**（约 5 行，可单独发 patch 版） |
| ⚠️ 安全前提 | 我们的 `/formatforge/*` 路由**不在宿主鉴权围栏内**（围栏只管 `GET /` 与 `/api`）→ 新增 API 必须自建 token 校验 + loopback 来源校验（§3.3、§8-R10） |
| 总量 | **4 个阶段 + 1 个先决阶段，约 25–35 人日**（单人 + AI 协作口径）；P0 结束即可用（CLI 侧检索/去重），UI 在 P1 起可见 |
| 硬约束 | 协议 v1 冻结（只能加字段/加文件）；`package.json` `dependencies` 必须保持 `{}`；产物必须人类可读（`.ff.md`/`.ff.json` 继续留在磁盘） |

---

## 1. 现状盘点（含证据）

### 1.1 数据链路（今天）

```
浏览器拖拽 ──POST /formatforge/upload──▶ inbox-watcher(2s 轮询) ──spawn──▶ python -m formatforge translate
   ▲                                          │                                   │
   │                                          ├─ 写 <stem>.ff.json（CLI 协议原文） ◀┘
   └── 会话通知(默认关) ◀── onDone ────────────┴─ 写 <stem>.ff.md（data.content）
                                              └─ 失败写 <stem>.ff.error.txt
`ff_result{list|ids}` ── 直接读目录（list 只读每个文件前 2048 B）
retention：TTL 7 天 / 上限 500 MB，清理前写入 .ff.retired.log
```

- 落盘位置：`FF_HOME || <DSH_HOME>/formatforge` → `inbox/`（`services/inbox-watcher.mjs:32-40`）
- 产物命名：`<stem>.ff.json` / `<stem>.ff.md` / `<stem>.ff.error.txt`（`inbox-watcher.mjs:152-155`）
- 元数据现状：`.ff.json` 里有 `parser/file_size/result_id/confidence/elapsed_ms/quality/enhance`，
  **没有** source_path、sha256、session_id（`formatforge/__main__.py:145-180,232-249`）
- 规模实测（ROADMAP.md:48-54）：`list` 100 条 4.5 ms / 0.2 MB；1000 条 33.8 ms / 2.4 MB；5000 条 241.9 ms / **12.0 MB**

**结论**：I/O 不是瓶颈；缺的是**全文检索、内容去重、来源溯源、结构化筛选**，
以及 `list` 会把全部条目塞进模型上下文的真实痛点。这与 ROADMAP.md:56 的判断一致。

### 1.2 已经写好的 DB 计划（本计划在其上扩展）

`ROADMAP.md:44-115` 已经给出方案骨架，本计划**采纳**：

- 落点 `<DSH_HOME>/formatforge/index.db`（与收件箱同级）
- Python 侧写、Node 侧不碰 SQLite（经 `formatforge inbox <subcmd>` CLI 边界）
- 迁移＝扫描现有 `*.ff.json` 回填，`INSERT OR IGNORE`，幂等、非破坏、可删库重建
- 已否决：JSON 索引文件（无 FTS/无并发保护）、`better-sqlite3`（破坏零依赖）、宿主 `dsh-storage`（会话级）

**本计划的三处修订**（基于本次实测）：

| 修订 | 依据 |
|---|---|
| Node 侧**可以**直接只读 SQLite（`node:sqlite` 内置，非 npm 依赖），API 层不必每次 spawn Python | 实测 Node 22.23.1 `require('node:sqlite')` 免 flag 成功；运行时 ships **Node 24.18.1**（`runtime/versions.json`） |
| 全文索引必须用 `tokenize='trigram'`，不是默认 `unicode61` | 实测：中文短语「付款条款」在 `unicode61` 下 **0 命中**，`trigram` 下命中 |
| schema 需要为 UI 扩展：tags、jobs、events、thumbnails、软删除 | 见 §4 |

### 1.3 前端资产（可直接复活）

冻结线 `v2.1.0-ci-green` = commit `6610ef1`（2026-08-24），含：

- `frontend/` **29 个文件**：Lit 3 + TypeScript + Vite + Tailwind 4，组件 `app-upload/app-result/app-history/app-compare/app-options/app-background/app-status`，i18n（zh/en）、设计 token（`styles/tokens.css`）
- `api/v1.py`(14 KB) + `api/v2.py`(24 KB) + `main.py`(10 KB)（FastAPI 层：认证、限流、SSE、webhook、metrics）
- `PLUGIN_PLAN.md:42` 记录当时"删除 115 MB 包袱，保留 17 个解析器核心资产"

**复活策略见 §3.1**：前端**复活并重构**，后端**不复活**（改用插件内 Node 路由 + CLI 边界）。

### 1.4 平台能力（实机核查，含出处）

> 核查方法：`.scan/dsh-src` 只有 27 个包，实机 asar 里有 **289** 个 `@deepseek-ai` 包。下表以**在内存中解析 asar**
> （pickle header → JSON → 按 offset 读文件）与**以 Node 模式启动 shipped exe 实测**为准。

| 能力 | 结论 | 证据 |
|---|---|---|
| 客户端插槽注册 | ✅ `ctx.slots.inject(name, () => ctx.slots.register({name,id?,order?,locale?,children?,slots?,store?,inject?}, Component))`；另有生成器写法与 `registerFactory`（可复用装配） | `dsh-client-ui-slots/README.md`；`dsh-client-ui-workspace/lib/client.js:4299-4361` |
| 插槽种类 / 作用域 | `single｜list｜keyed｜chain`；作用域 `root｜session｜session-maybe` | slots README「Use this package」；会话侧声明 `dsh-client-ui-conversation/lib/client.js:18154-18186` |
| ⚠️ 注册纪律 | **注册到"未声明"的插槽会在加载期抛错**；插槽名由**声明它的插件**拥有（`SlotMap` 靠 `declare module` 增补合并），**平台不保证稳定** | slots README internals |
| **整窗口页面** | ✅ **`main`** 插槽 = 全窗口页面（owner：`dsh-client-ui-conversation:18435`、`plugin-manager:3712`、`schedule:6793`）→ **"独立页面"有原生落点，不必只在浏览器另开标签** | asar 全量提取 |
| 右侧面板页签 | ✅ `rightbar`（seat owner `dsh-client-ui-sidebar-right:9138`）+ `sidebar.right.pane.tab` / `.title`（8 个既有注册者：plan / sidebar-browser / documentpreview / files / terminal / subagent / schedule / sidebar-right） | 同上 |
| 交付物面板（**已存在**） | ✅ `deliverables.file.actions` / `deliverables.review.file.actions`，owner `dsh-client-ui-deliverables` → 宿主**自带"交付物/产物"面板**，产物可以挂进去，而不是另起一套浏览体验 | 同上（消费方 `dsh-client-ui-open-in-app:878`） |
| 设置 | ✅ `settings.section`、`settings.general.item`（主题插件在用）、`settings.trigger/close/header/action`、`settings.plugins.tab` | 同上 |
| 其他客户端服务 | `ctx.shortcuts.register()`（快捷键命令）、`ctx.layout.selectPanel(id)` / `activePanelId`（切面板）、`ctx.configForms.get(ns)`（读设置值）、`ctx.remote`（browser→host RPC） | workspace:109/4292/162/969；theme:1581 |
| 插槽清单规模 | 71 个 shipped `lib/client.js` 共提取出 **68 个可注入插槽名**（关键项见 §3.1） | asar 全量提取 |
| 自定义路由 | ✅ `webServer.register({kind:"exact"｜"prefix", path, handler})`，重复 `(kind,path)` 抛错；`registerUpgrade({path,handler})`（WS，仅 exact）；`registerFallback`（**唯一席位，已被 SPA 占用**）；匹配顺序 exact → 最长 prefix → fallback；handler 抛错 → 400 | `dsh-host-webserver/lib/index.js:177-207,322-334`、README:45,49 |
| ⚠️ **鉴权围栏** | **自定义路由完全在鉴权之外**：webserver"无 TLS、无鉴权、无 origin 策略"；浏览器信任围栏只保护 `GET /` 的 token 换 cookie 与 `/api` 路由。因此 `/formatforge/*` 任何本机进程都能调用 | `dsh-host-webserver/README.md:39,113`；`dsh-client-connection/lib/index.js:587-588` |
| SSE / 流式 | ✅ 无 helper：自己写 `res` 并 flush；gzip 中间件**跳过 SSE**（不会被压坏）；长连接也可用 `registerUpgrade` 走 WS | webserver README:41 |
| 请求体大小 | 自定义路由**无平台上限** → `http/upload.mjs:27-43` 的 `FF_MAX_BYTES` 自限是**必需**（平台上限只作用于 `/api`） | `dsh-client-connection` 的 `maxRequestBodyBytes` |
| 插件级持久化 | ✅ **存在公开契约**：`ctx.storageDomain.open(defineDomain({name,version,tables}))`；读**同步**（域全量驻内存）、写走**单一 write chain**、记录经 zod 校验；JSON 后端落 `~/.dsh/storages/`；**没有迁移机制**（version 不匹配 → `version-mismatch` 拒绝） | `dsh-storage-domain/README.md`；`dsh-base/cordis.patch.yml:161-186` |
| 平台自带 SQLite 先例 | ✅ 宿主自带 `dsh-session-query-sqlite`（**SQLite FTS5** 检索），`await import("node:sqlite")` + `PRAGMA journal_mode`；默认关闭（`openAt: never`），且带"FTS5 外层谓词预算 14"的复杂度护栏 | `dsh-session-query-sqlite/lib/index.js:50,62,106,136,167`；`dsh-base/cordis.patch.yml:141-153` |
| 插件进程模型 | 宿主插件跑在**独立 Node 子进程**（Electron 以 `ELECTRON_RUN_AS_NODE=1` Node 模式启动，只传 `--expose-internals`），**不是 Electron 主进程、不是 worker** | `lib/main.js:3673-3691,3529-3534` |
| 实测运行时 | node **v24.18.1** / Electron **44.0.0** / chrome 152 / **`process.versions.modules = 149`**（Electron ABI，**≠** 原生 Node 24） | 以 Node 模式启动 shipped exe 实测 |
| `node:sqlite` | ✅ **完全免 flag**：在 shipped runtime 实测建 FTS5 虚表 + `MATCH` 查询成功 | 同上（宿主也只传 `--expose-internals`） |
| 原生插件（如 better-sqlite3） | ❌ 不建议：ABI 149 必须按 Electron 44 重编译；且插件安装是否允许 build script 未确认 | 同上 |
| `engines.node` 下限 | ⚠️ **`>=22.13.0` 不足以支撑 `node:sqlite`**（22.x 需 `--experimental-sqlite`，宿主不传）；本机宿主 24.18.1 可用 | 同上 |

> **契约分级**（决定 UI 的失败策略）：`ctx.slots.*`、`ctx.webServer.register`、`ctx.storageDomain` 都是**公开契约**（README 的 "Use this package" 一节）；
> 但**具体插槽名**（`main`、`sidebar.right.pane.tab`…）是**对等插件私有**的，且注册到未声明插槽会**在加载期抛错** →
> UI 必须"探测声明 + try/catch + 降级"，见 §8-R1。
> 平台整体处于 `0.2.0-rc.x`（peer 区间 `>=0.2.0-rc.1 <0.3.0-0`）→ **跨 0.3 要预期破坏性变更**。

### 1.5 必须遵守的约束

| 约束 | 出处 |
|---|---|
| 协议 v1 冻结：只能**新增字段/新增文件**，不得改既有字段语义；新增 API 属于"新增" | `protocol/v1/README.md:3-5,105-109` |
| `package.json` `dependencies` 保持 `{}`（硬不变量） | `packages/dsh-formatforge/package.json:41`、ROADMAP.md:62 |
| 新目录必须进 `files` 白名单，否则不会被打包 | `package.json:12-20`（当前 17 files / 40.5 kB） |
| 产物继续人类可读，DB 只做元数据 + 索引 | ROADMAP.md:63 |
| `engines.node >= 22.13.0`、`engines.dsh >= 0.2.0-rc.1 < 0.3.0-0` | `package.json:32-35`；⚠️ 这个 Node 下限**不足以支撑 `node:sqlite`**（22.x 需 flag，宿主不传）→ 见 §8-R3 |
| 客户端 bundle 的注册 id = npm 包名（改版本不影响） | `scripts/build-client.mjs:1-14` |

---

## 2. P-1 先决阶段：**8–12 小时**（必须先做完，否则后面全部建立在坏地基上）

### P-1.1 修 `ff_result` 字段错配 🔴 阻塞级（**已实测确认，非推断**）

**实测方式**：往正在运行的宿主收件箱投一个真实文件（`ff-plan-probe-20261002.txt`），让 watcher 走完整链路产出
`ff-plan-probe-20261002.ff.json`（1133 B），再对读代码：

```
产物 data 字段   : content, format, meta, structured_data, quality
meta 字段        : parser, file_size, result_id, confidence, elapsed_ms, quality_auto
convertedContent : ✗ 不存在      fileInfo: ✗ 不存在      resultId: ✗ 不存在
meta.result_id   = cvt202610020216178c771b        （真实 id）
```

**工具读的是另一套字段名**：

| 读代码 | 期望字段 | 实际字段 | 真实后果 |
|---|---|---|---|
| `tools/result.mjs:202` | `data.convertedContent` | `data.content` | **fetch 取回的正文恒为空字符串** |
| `:212`（fetch）/:43（list） | `data.resultId` | `data.meta.result_id` | id 退化成文件名 stem，`cvt…` 前缀匹配失效 |
| `:214`/:45 | `data.fileInfo.fileName` | 无（需新增 `meta.source_name`） | `source` 只剩文件名兜底 |
| `:215`/:46 | `data.fileInfo.fileType` | `data.meta.parser` | **`parser` 永远显示 `?`** |
| `:47` | `fileInfo.pageCount` | 无 | `pages` 永远 0 |
| `:216`/:48 | `data.confidence` | `data.meta.confidence` | `confidence` 永远 `null` |
| `:217`/:49 | `data.enhance` ✅ | `data.enhance` | 唯一正确的字段 |

**影响面**：模型侧"取回收件箱产物"这条能力实际上是坏的——`ff_result {list:true}` 只能看到文件名/时间/体积，
`ff_result {id}` **拿不到任何正文**。而 SKILL.md 正把 `ff_result` 作为唯一的产物消费入口（v2.0.1 的设计）。
**这与 UI/DB 计划无关，可立即作为 patch 发布。**

**补丁草案（P-1.1，约 5 行）**：

```js
// tools/result.mjs —— 以 CLI 实际契约（content + meta.*）为准，旧字段留作兼容兜底
const d = doc.data || {}
const meta = d.meta || {}
const content = typeof d.content === 'string' ? d.content
              : (typeof d.convertedContent === 'string' ? d.convertedContent : '')   // 旧产物兜底
// id      : meta.result_id || d.resultId || stem
// source  : meta.source_name || d.fileInfo?.fileName || stem
// parser  : meta.parser    || d.fileInfo?.fileType || '?'
// confidence: meta.confidence ?? d.confidence ?? null
// pages   : meta.page_count ?? d.fileInfo?.pageCount ?? 0
```

**配套**：`test/test-result-contract.mjs`（造一份真实产物 → 断言 `content` 非空、`parser != '?'`、
`confidence` 为数字、`id` 以 `cvt` 开头）+ CI 挂钩；顺手核对 `list` 路径同一批字段。

### P-1.2 定死产物命名（DB 列要写路径，必须先定）

- 现状：`<stem>.ff.json`（`inbox-watcher.mjs:152-155`），`report.docx` 与 `report.pdf` **会互相覆盖**（ROADMAP:35 / SELF_CHECK:109）
- 目标（R6.1.1）：`<name>.<ext>.ff.json`（如 `book.epub.ff.json`）
- **过渡策略（推荐）**：**新写新名、读旧名兜底**——写入端立刻切新名；`ff_result` 与 DB 迁移器同时识别两种命名；一个月后（下个 minor）移除旧名支持
- 产出：命名常量收敛到一处（`services/inbox-watcher.mjs` 与 `http/upload.mjs` 共用），补迁移期测试

### P-1.3 版本号与冻结表的两处决定

| 问题 | 现状 | 建议 |
|---|---|---|
| 版本号冲突 | tag `v2.1.0` 已被**旧 Web 线**占用（`8aa01207`），而 `ROADMAP.md:161` 把 DB 版本也规划成 v2.1.0 | 新线用 **v2.2.0（DB）/ v2.3.0（UI）**，避开 `v2.1.x`；在 CHANGELOG 写明历史同号情况 |
| 冻结表漂移 | `protocol/v1/README.md:82` 写 `FF_INBOX_NOTIFY` 默认 `true`，实现是 `=== 'true'`（默认 **false**，v2.0.1 起） | 只**修文档 + CHANGELOG 注明**（安全修正，不改实现语义）；新增 `FF_DB`、`FF_DB_PATH` 两个环境变量**走"新增"路线**并登记进冻结表 |

---

## 3. 技术选型

### 3.1 UI 形态：四选一 → **推荐 D（原生双落点 + 同构建自托管）**

> 关键新事实（本轮实机核查）：宿主有 **`main` 全窗口页面插槽**，所以"独立页面"**不必**只在浏览器另开标签；
> 而自托管页可以**复用同一份前端构建产物**——两个 lane 渲染同一套组件，成本远低于"维护两套视图"。

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 只做右侧面板页签（`sidebar.right.pane.tab`） | 轻、随主题、与对话同屏；已有 8 个内置同类（文件/终端/计划/文档预览…） | 空间小，只适合"最近产物 + 搜索 + 打开" | **P1 入口层** |
| B. 只做 `main` 整窗口页面 | 在 DSH 内拿到全窗口，可做表格/虚拟滚动/多视图；无需自建鉴权与静态托管 | 会占满/切换主区域，与对话互斥；插槽名对等私有 | **P2 重界面（首选落点）** |
| C. 只做自托管 `/formatforge/ui` | 完全自由、可分享 URL、可大屏；不依赖插槽契约 | 等于"离开 DSH"；要自建鉴权（我们自己的路由**不在**宿主鉴权围栏内，见 §1.4）与主题/i18n | **降级/可选**（同一产物多挂一个 lane） |
| **D. A + B + (C 可选) 混合** ✅ | 轻任务不离场、重任务有整窗口页、**同一份 Lit 构建两边复用**；宿主的 `deliverables.*` 面板还能作为"自动出现"的第三入口 | 需要维护插槽适配层（薄）；受插槽契约变动影响 | **推荐** |

**推荐的信息架构**（实现细节见 §5）：

```
DSH GUI
├─ 右侧面板页签 sidebar.right.pane.tab：「FormatForge」
│   ├─ 搜索框（FTS trigram）· 最近 20 条 · 状态徽标
│   ├─ 行操作：在整窗口页打开 / 复制路径 / 投递到当前会话 / 重新锻造
│   └─ 空态：拖入即用（复用现有拖拽模块）
├─ 整窗口页面 main：「FormatForge 库」  ← 与面板共用同一套组件
│   ├─ 列表（虚拟滚动）+ FTS 搜索 + 结构化筛选（格式/解析器/状态/时间/会话）
│   ├─ 详情预览（Markdown + 结构化数据 + quality/enhance）
│   ├─ 批量：多选重转 / 导出 zip / 删除；任务队列与进度（SSE）
│   └─ 历史时间线 + 标签/收藏
├─ 旁路入口（自动出现，不用额外开发视图）
│   ├─ 交付物面板 deliverables.file.actions：产物行动作（打开/重转/复制）
│   ├─ 拖拽投递后 conversation.composer.dock：本次产物的会话内卡片
│   └─ 设置 settings.section：库路径、TTL/上限、重建索引、导出备份
└─ 可选自托管页 /formatforge/ui（同一份构建产物；给"不打开 DSH 面板"或大屏场景）
```

**插槽映射表（P1/P2/P4 落地用）**：

| 用途 | 插槽名（**对等私有，需探测**） | 阶段 |
|---|---|---|
| 右侧面板主体 | `sidebar.right.pane.tab` + `sidebar.right.pane.tab.title` | P1 |
| 整窗口库页面 | `main` | P2 |
| 新产物计数徽标 | `sidebar.toggle.badge` | P1 |
| 面板底部动作（打开整窗口页 / 到设置） | `sidebar.footer.action` | P1 |
| 拖拽投递后的会话内卡片 | `conversation.input.dock` / `conversation.composer.dock` | P1 |
| 产物行动作挂到宿主"交付物"面板 | `deliverables.file.actions` / `deliverables.review.file.actions` | P2 |
| 设置分区 | `settings.section`（或 `settings.general.item`） | P4 |
| 工具卡美化（`ff_translate` 结果摘要 + 打开按钮） | `tool.call.toolview` | P2 |
| 快捷键（`/` 搜索、`k` 打开库） | `ctx.shortcuts.register()`（服务，非插槽） | P1 |
| 从面板跳到整窗口页 | `ctx.layout.selectPanel(id)`（服务，非插槽） | P2 |

> **三条落地纪律**（来自平台核查）：
> 1. **注册到未声明的插槽会在加载期抛错** → 每个注册点用 `ctx.slots.entries(name)` 探测声明 + `try/catch`，失败只记日志并继续（**绝不能让 UI 失败拖垮拖拽模块**）。
> 2. `dsh.client.inject` 是**外部模块请求列表**，不是 cordis 服务；cordis 服务写在 `client.js` 内的 `inject` 常量里。
> 3. 具体插槽的 **props 与生命周期**以宿主**生成的 Client Slot catalog** 为准（本计划只核实了名字、owner 与用途）。

### 3.2 数据库：**SQLite，Python 写 + Node 读**

| 方案 | 评价 |
|---|---|
| **SQLite：Python stdlib 写（真相源）+ Node `node:sqlite` 只读** ✅ | 零新增依赖（Python 标准库 + Node 内置）；WAL 支持多进程读写；UI 查询走 Node，**不必为每次查询 spawn Python**；写侧单点（watcher 进程）天然避免写冲突 |
| SQLite：Node 写、Python 只产文件 | 也零依赖，但转换状态与库有双写窗口；写侧并发（多会话）更难控 |
| SQLite：Python 写、Node 一律走 CLI 读（ROADMAP 原案） | 最保守，但每次 UI 查询 +0.5s（Python 冷启动地板，ROADMAP:123），面板交互会顿 |
| `better-sqlite3` | ❌ 破坏零依赖 + 原生编译 + Electron ABI 风险 |
| 宿主 `dsh-storage` | ❌ 会话级生命周期，产物要跨会话/跨 profile 存活（**但**：其插件侧 API `ctx.storageDomain` 是公开契约，适合放"插件设置/小元数据"，见下） |
| JSON 索引文件 | ❌ 无 FTS、无并发写保护（ROADMAP:111 已否，仅可作过渡） |

**分层持久化（本轮修订的核心）**：平台**确实**提供了面向插件的存储服务，按数据形态分两层用才是正解：

| 层 | 存什么 | 用什么 | 理由 |
|---|---|---|---|
| **A. 插件设置 / 小元数据** | UI 偏好（视图、每页条数、主题）、标签字典、上次索引版本、面板状态 | ✅ **`ctx.storageDomain`**（`defineDomain({name,version,tables})` → `open()` → `table().get/put/update/delete`） | 平台**公开契约**；读写简单（读同步）、写有单一 write chain、记录经 zod 校验；JSON 落 `~/.dsh/storages/`，跟着 DSH_HOME 走 |
| **B. 产物索引 / 全文检索** | artifacts / jobs / events / FTS5 | ✅ **SQLite（`node:sqlite` 只读 + Python stdlib 写）** | FTS5 是 A 层做不到的（A 层整域驻内存、无 FTS）；平台自己就这么干（`dsh-session-query-sqlite` 用 `node:sqlite` + FTS5） |
| C. 产物本体 | `.ff.md` / `.ff.json` | ✅ 继续留文件（人类可读） | 冻结约束（ROADMAP:63） |

**A 层的两条硬限制（必须写进实现约束）**：
- **没有迁移机制**：`version` 不匹配直接 `version-mismatch` 拒绝 → 我们的做法：`version` 只在**破坏性**变更时 +1，并同时把 `name` 换成新域（`formatforge.ui.v2`），旧域只读不写，代码里写一次性搬迁函数。
- **整域驻内存**：不适合放产物条目（几千条可以，几万条会长胖）→ 严格限制为"设置 + 小字典"。

**关键实现约束（实测得出）**：

1. **FTS5 分词必须用 `trigram`**：`unicode61` 对中文短语 0 命中；`trigram` 需 SQLite ≥ 3.34（Python 3.45.3 / Node 3.51.3 均满足）。
2. **写侧单点 + WAL**：只由 Python（`formatforge inbox ...`）写；Node 侧 `PRAGMA query_only=ON` 只读。
3. **FTS5 谓词预算**：平台实现里有"外层谓词预算 14"的护栏（`dsh-session-query-sqlite/lib/index.js:167`）——我们的查询构造器要避免把复杂过滤全塞进 `MATCH`，过滤走普通列 + 索引。
4. **`node:sqlite` 的版本前置**：宿主实测 Node 24.18.1（免 flag）✅；但 `engines.node >=22.13.0` 的**下限不成立**（22.x 需 `--experimental-sqlite`，宿主不传）→ 启动特征检测 + 降级：不可用时 Node 侧一律走 `python -m formatforge inbox query --json`（ROADMAP 原案），单测两条路径都测（见 §8-R3）。
5. **原生插件一律不用**：宿主进程 `process.versions.modules = 149`（Electron 44 的 ABI，非原生 Node 24）→ better-sqlite3 需要 electron-rebuild；用内置 `node:sqlite` 完全绕开。

### 3.3 服务端 API（REST + SSE）

统一前缀 `/formatforge/api/`（`kind:"prefix"`）。**先纠正一个安全前提**：

> ⚠️ 本轮核查确认：**宿主的鉴权围栏只保护 `GET /`（token 换 cookie）与 `/api` 路由**
> （`dsh-client-connection/lib/index.js:587-588`）；`ctx.webServer` 自己"无 TLS、无鉴权、无 origin 策略"
> （`dsh-host-webserver/README.md:39,113`）。也就是说**我们现有的 `/formatforge/upload`、`/formatforge/health`，
> 以及将来所有 `/formatforge/api/*` 都不在围栏内**——本机任何进程都能调用，绑定到 `0.0.0.0` 时局域网也能。
>
> 因此本计划新增两条**安全要求**（见 §8-R10）：
> 1. **自建鉴权**：插件首次启动生成一次性 UI token（存 `ctx.storageDomain` 的 A 层），`/formatforge/ui` 与 `/formatforge/api/*` 校验 `?token=` 或 `X-FF-Token`；`/formatforge/upload` 保留现状（浏览器拖拽直投，已有限流与白名单）。
> 2. **绑定与来源**：继续只依赖宿主 `127.0.0.1` 绑定；同时在 API 层校验 `Host`/`Origin` 属于 loopback（防御 DNS rebinding 类场景）。

```
GET    /formatforge/api/artifacts?q=&format=&parser=&status=&tag=&since=&cursor=&limit=
GET    /formatforge/api/artifacts/:id            # 元数据 + 预览片段
GET    /formatforge/api/artifacts/:id/content    # md/json 正文（分页）
POST   /formatforge/api/artifacts/:id/retry      # 重新锻造
DELETE /formatforge/api/artifacts/:id            # 软删除
GET    /formatforge/api/jobs                     # 队列
GET    /formatforge/api/events                   # SSE：job/artifact 事件流（gzip 会跳过，安全）
GET    /formatforge/api/stats                    # 计数、体积、TTL 状态
POST   /formatforge/upload                       # 复用现有（拖拽直投）
GET    /formatforge/ui/*                         # 自托管前端静态资源（prefix；同一份构建产物）
```

**其他路由事实**：重复 `(kind,path)` 会抛错 → 路由名集中登记，避免重复注册；`registerFallback` 唯一席位已被 SPA 占用（不要用）；
WebSocket 可用 `registerUpgrade`（仅 exact 路径）。**SSE 需要自己写 `res` 并 flush**（没有 helper），且 `ctx.effect()` 里返回 disposer 以便 HMR/禁用时清理。

**协议兼容**：全部是**新增路由**，不动 `protocol/v1` 既有形状；工具侧 `ff_result` 仍按冻结契约返回（新增可选参数 `search`/`stats`/`limit` 走"新增字段"）。

---

## 4. 数据模型（schema v1）

```sql
PRAGMA journal_mode = WAL;      -- 多进程读写
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at INTEGER NOT NULL,
  checksum TEXT NOT NULL
);

CREATE TABLE artifacts (
  id             TEXT PRIMARY KEY,        -- 已有 resultId：cvtYYYYMMDDHHMMSS+6hex
  source_name    TEXT NOT NULL,           -- 原始文件名（R6.1.4 回填）
  source_ext     TEXT,
  source_path    TEXT,                    -- 绝对路径（若来自磁盘）
  source_sha256  TEXT,                    -- 内容去重键（首 64KB→全文，分级）
  source_bytes   INTEGER,
  source_mtime   INTEGER,
  format         TEXT,                    -- 输出格式：json/markdown/html/text
  parser         TEXT,                    -- R6.1.2：真实解析器类名
  file_type      TEXT,                    -- 旧的粗枚举（降级保留）
  confidence     REAL,
  enhance_reason TEXT,
  quality_json   TEXT,
  chars          INTEGER,
  elapsed_ms     INTEGER,
  md_path        TEXT, json_path TEXT,    -- 命名方案定稿后写入（P-1.2）
  session_id     TEXT,                    -- 溯源：哪个会话触发的
  status         TEXT NOT NULL DEFAULT 'ok',   -- ok|failed|retired
  error_kind     TEXT, error_message TEXT,
  starred        INTEGER NOT NULL DEFAULT 0,
  created_at     INTEGER NOT NULL,
  updated_at     INTEGER NOT NULL,
  retired_at     INTEGER,
  deleted_at     INTEGER                  -- 软删除
);
CREATE INDEX idx_artifacts_created ON artifacts(created_at DESC);
CREATE INDEX idx_artifacts_sha     ON artifacts(source_sha256);
CREATE INDEX idx_artifacts_status  ON artifacts(status, created_at DESC);

-- 全文检索：trigram 才认中文（实测 unicode61 对「付款条款」0 命中）
CREATE VIRTUAL TABLE artifacts_fts USING fts5(
  id UNINDEXED, source_name, content,
  tokenize = 'trigram'
);

CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, color TEXT);
CREATE TABLE artifact_tags (artifact_id TEXT REFERENCES artifacts(id), tag_id INTEGER, PRIMARY KEY(artifact_id, tag_id));

CREATE TABLE jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL,          -- translate|batch|diff|reindex
  artifact_id TEXT, argv_json TEXT,
  status TEXT NOT NULL,                             -- queued|running|ok|failed|canceled
  queued_at INTEGER, started_at INTEGER, ended_at INTEGER,
  exit_code INTEGER, error_kind TEXT, error_message TEXT, pid INTEGER
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, kind TEXT NOT NULL,
  artifact_id TEXT, job_id TEXT, payload_json TEXT
);

CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT, updated_at INTEGER);
-- 注意：这里只放"索引层"设置（如 content_index_chars、schema 版本相关开关）。
-- UI 偏好（视图模式/每页条数/主题/标签字典）走平台契约 ctx.storageDomain（§3.2 A 层），不重复存。
```

**维护规则**

| 事项 | 规则 |
|---|---|
| 迁移 | `schema_migrations` 单调版本；每个迁移一个函数 + 幂等；启动时自动跑；失败回滚并保留 `.db.bak` |
| 回填 | `formatforge inbox reindex`：扫描 `*.ff.json` → `INSERT OR IGNORE` → 重建 FTS；**可随时删库重建** |
| 保留 | 与文件侧 TTL/上限**同一策略**（`FF_INBOX_TTL_DAYS`/`FF_INBOX_MAX_MB`）；清理时先标 `retired_at` 再删文件，`.ff.retired.log` 继续写 |
| 去重 | 拖入时按 `source_sha256` 命中 → 立即返回"已存在，id=…（N 天前）"，不重复锻造 |
| 备份 | `formatforge inbox backup --out <path>`（`VACUUM INTO`）；UI 设置页一键导出 |
| 体积 | `PRAGMA page_size=4096`；每 1000 条 `ANALYZE`；`inbox vacuum` 手动/月度 |

---

## 5. 界面设计要点（避免"又一个文件列表"）

| 维度 | 决策 |
|---|---|
| 首屏 | 面板：搜索框 + 最近 20 条（时间倒序）+ 状态徽标；全屏页：同上但带筛选侧栏与批量操作 |
| 搜索 | FTS trigram 前缀/子串匹配；高亮命中片段；`q` 为空时退回时间序（**永远不走 `list` 全量**） |
| 详情 | Markdown 渲染（复用 `.ff.md`）+ 结构化数据折叠 + `quality`/`enhance` 徽标 + 源码文件路径复制 |
| 空态 | "把文件拖进来"（指向现有拖拽模块）+ 一键在文件管理器中打开收件箱 |
| 错误态 | `status=failed` 的行显示 `error_kind` + "重新锻造"；`.ff.error.txt` 内容内联 |
| 主题 | 用宿主 CSS 变量（`--dsw-alias-*`，现有 client.js 已在用）为主；全屏页用 `tokens.css` 并支持跟随系统 |
| i18n | zh/en 两份字典（面板与全屏页共用 JSON）；宿主 `ctx.locale.register` 注册 |
| 快捷键 | `/` 聚焦搜索、`j/k` 上下、`Enter` 打开、`Esc` 关闭、`Cmd/Ctrl+K` 命令面板（P4） |
| 可访问性 | 每个插槽组件带 `aria-label`；列表用 `role="list"/"listitem"`；对比度 ≥ 4.5:1 |
| 性能 | 列表虚拟滚动（>200 行）；正文分页（复用 `max_chars/offset` 约定）；SSE 增量更新而非轮询 |

---

## 6. 路线图（分阶段，每阶段可独立交付）

| 阶段 | 范围 | 交付物 | 验收标准 | 工时 |
|---|---|---|---|---|
| **P-1 先决** | 修 `ff_result` 字段错配；定产物命名（新名写、旧名读）；定版本号/冻结表 | 修复 + `test-result-contract.mjs` + CHANGELOG | golden 测试绿；`ff_result {id}` 能取回正文；命名常量单点 | **8–12 h** |
| **P0 数据底座** | `formatforge/inbox.py`（`init/index/query/search/stats/reindex/retire/vacuum/backup`）；schema v1 + 迁移器；watcher 落盘后索引；`ff_result` 新增 `search/stats/limit` | DB + CLI 子命令 + Node 只读查询层 + 回填工具 | 1000 条 fixture 索引 <2 s；中文检索命中；重复拖入秒回；删库可重建；`pytest` 新增 ≥20 用例 | **3–4 d** |
| **P1 原生入口** | `http/api.mjs`（REST 只读 + SSE + **自建 token 校验**）；client 模块注册 `sidebar.right.pane.tab` 面板（**插槽探测 + 降级**）；设置/偏好落 `ctx.storageDomain` | 面板 UI（Lit 或 `React.createElement`，视 lane）+ API + 权限层 | 面板可搜索/打开产物；**未声明插槽时静默降级且不影响拖拽模块**；未带 token 的 API 请求 401；`test-client-panel.mjs` 覆盖注册/降级/卸载 | **3–4 d** |
| **P2 重界面** | 复活冻结前端并重构对接新 API（列表/搜索/详情/批量）；**首选挂 `main` 整窗口页**，同一份产物再挂 `/formatforge/ui`（prefix 路由） | `ui/` 源码 + `ui/dist` 产物 + 构建脚本 + 两个挂载点 | 首屏 <1 s（本地）；包体积增量 <1 MB；`files` 白名单与 npm pack 核对；真机 CDP 截图（两个 lane 各一张） | **8–12 d** |
| **P3 队列/作业** | `jobs` 状态机 + worker（复用 `python-runner`）+ SSE 进度 + 取消/重试；与 watcher 共用限流 | 队列 API + UI 任务视图 | 100 文件批量可见进度、可取消；宿主重启后状态可恢复（未完成→`failed`）；并发上限可配 | **4–6 d** |
| **P4 打磨** | 标签/收藏、设置页、i18n 补全、a11y、命令面板、GC/vacuum、备份恢复、截图回归 | 文档 + 截图 + `verify-install.py` 新检查 | `ruff/mypy/pytest/bandit` 全绿；截图进 `screenshots.json`；`verify-install.py` 5→7 项 | **5–8 d** |

**时间表（单人 + AI 协作，含验证与文档）**

| 周 | 内容 | 出口 |
|---|---|---|
| W1 | P-1 + P0 | v2.2.0：库可用（CLI 侧检索/去重/溯源） |
| W2–W3 | P1 + P2 | v2.3.0：面板可见 + 全屏页可用 |
| W4 | P3 | v2.3.x：批量/队列/进度 |
| W5 | P4 + 全盘自检 + 发布 | v2.3.0 正式版 |

> 每个阶段结束都走一遍现有发布流程（自检 → CHANGELOG → tag → GitHub Release → npm publish），保持"每步可交付、可回滚"。

---

## 7. 测试与 CI 扩展

| 层 | 新增内容 |
|---|---|
| DB 单测（pytest） | 迁移幂等、回填正确性、FTS 中文命中、去重键、TTL 与软删除、并发写（两进程） |
| CLI 契约 | `formatforge inbox query --json` 单行协议（沿用 `stdout 唯一出口` 规则）；`ff_result` 新参数 golden |
| Node 侧 | `test-inbox-db.mjs`（索引→查询→去重端到端）、`test-api.mjs`（路由/鉴权/SSE 帧） |
| 客户端 | 扩 `test-client-drag.mjs` 同风格为 `test-client-panel.mjs`（插槽注册/降级/卸载泄漏） |
| UI | `vitest` 组件测试（已有 vitest 依赖在冻结前端）+ **CDP 真实截图**（修 `take-screenshots.py` 的 3080→19387 并改抓真界面） |
| CI | `ci.yml` 增加：DB 用例（矩阵 3.10/3.11/3.12）、`node --check` 覆盖 `ui/dist`、npm pack 体积门禁（>1.5 MB 失败）、API 契约用例 |
| 性能 | `scripts/measure_inbox.py`：索引 1k/5k/20k 条耗时、检索 P95、面板首屏 |

---

## 8. 风险登记册

| ID | 风险 | 影响 | 对策 |
|---|---|---|---|
| R1 | **具体插槽名是对等插件私有**，且**注册到未声明的插槽会在加载期抛错**（`SlotMap` 靠 `declare module` 增补） | 插件加载失败 / 面板消失 | 每个插槽注册点：`ctx.slots.entries(name)` 探测 + `try/catch`，失败只 `log()`；**UI 全部是可失败增强**，拖拽/工具/CLI 零依赖；`engines.dsh` 锁区间 + CI 冒烟（注册器在 fake ctx 下跑一遍） |
| R2 | 双写不一致（文件写了、库没写 / 反之） | 列表缺项 | **文件为真相源**：库只做索引；`inbox reindex` 随时重建；watcher 落盘成功后同步索引（失败重试队列） |
| R3 | `node:sqlite` 在目标宿主不可用（**`engines.node` 下限 22.13 不满足**：22.x 需 `--experimental-sqlite`，宿主只传 `--expose-internals`；未来 API 变动） | API/面板不可用 | 启动**特征检测**（`await import('node:sqlite')` try/catch）+ 降级到"Node 走 `python -m formatforge inbox query --json`"（ROADMAP 原案）；两条路径共享 SQL，单测都跑；文档写明实测宿主为 Node 24.18.1 |
| R4 | 前端产物体积（Lit + Tailwind + 虚拟滚动） | npm 包变大、安装变慢 | 构建目标：gzip <300 KB、解包 <1 MB；`files` 白名单 + `npm pack` 体积门禁；必要时用原生 Web Components 去掉框架 |
| R5 | 协议 v1 冻结被误伤 | 破坏兼容 | 只加字段/加路由；`protocol/v1/README.md` 增补新环境变量与新 API 小节；CI 跑既有 schema 校验 |
| R6 | Windows 中文路径/编码（v2.0.2 刚踩过） | 文件名乱码、SQL 报错 | 路径统一 `path.resolve` + UTF-8；DB `PRAGMA encoding='UTF-8'`；文件名入库前 `basename` 规范化；测试含中文名 fixture |
| R7 | 大库性能（20k+ 条、含长正文） | 面板卡顿 | FTS 只索引 `source_name + content 摘要`（正文按需读文件，不入库）；分页游标；列表虚拟滚动；避开 FTS5"外层谓词预算 14"（过滤走普通列） |
| R8 | 版本号/文档漂移（旧 Web 线 v2.1.0、冻结表 `FF_INBOX_NOTIFY`） | 用户困惑 | P-1.3 一次性结清；`CHANGELOG` 写清同号历史 |
| R9 | 隐私：产物正文入库 | 用户敏感内容被索引 | 只索引元数据 + 摘要（默认 4 KB，可配）；提供"不建内容索引"开关；DB 与 storageDomain 都在 `DSH_HOME` 内，权限沿用宿主 |
| **R10** | **自定义路由无鉴权**（`/formatforge/*` 在宿主鉴权围栏之外；`0.0.0.0` 绑定时局域网可达） | 本机/局域网任意进程可读产物、触发锻造 | ① 新增 API 自建一次性 token（存 A 层 storageDomain）+ 校验 `?token=`/`X-FF-Token`；② 校验 `Host`/`Origin` 为 loopback；③ 依赖宿主默认 `127.0.0.1` 绑定并在文档中明确；④ `upload` 保持白名单 + 体积上限；⑤ 删除/重转等写操作额外要求 token |
| **R11** | **`ctx.storageDomain` 没有迁移机制**（version 不匹配直接拒绝），且整域驻内存 | 升级后设置读不出、内存膨胀 | `version` 仅在破坏性变更时 +1 并**同时换域名**（`formatforge.ui.v2`），旧域只读 + 一次性搬迁；A 层只放设置与小字典，产物条目一律不进去 |
| **R12** | **宿主契约只在真机上成立，测试的"善意仿真"会掩盖它**（v3.0.0 实施期连踩四次：① 处理器只以 `handler(req, res)` 两参调用 → 依赖第三参 `url` 时线上全 400 空 body；② prefix 命中条件是 `pathname === prefix \|\| pathname.startsWith(prefix + '/')` → 带尾斜杠的前缀永不命中，单条接口全 404 且落到 SPA fallback；③ 列表行是库列名 `source_name/source_bytes/created_at` 而面板读 `source/size_bytes/forged_at` → 显示 id、大小时间空白；④ **鉴权只认同源浏览器信号，而桌面端 fetch 不带 `Sec-Fetch-Site`/`Origin`** → 面板首屏全 401） | 面板"点哪都不行"，且接口 200/404/401 混着，极难从现象定位 | **测试必须复刻宿主与真实客户端的语义**：`hostMatch()` 仿真 `match()`、`call()` 先断言"这个 URL 真会路由到这条路由"、所有 handler 两参调用、断言用**真实库行/真实产物**而不是手写假行、鉴权矩阵必须含"**无浏览器信号（桌面端）**"与"opaque"两行；再加一层**真实 `node:http` + 忠实 mini-webServer** 的端到端测试（`test-host-http.mjs`）；401/404 文案带上观察到的信号（`site/origin/client`）便于定位；文档记录四条规则的出处 |

---

## 9. 兼容、迁移与回滚

| 场景 | 做法 |
|---|---|
| 老用户升级 | 首次启动自动 `init` + `reindex`（幂等，只读 `.ff.json`）；不动任何既有文件 |
| 不想用 DB | `FF_DB=off` → 完全回到今天的文件路径（代码保留双路径，CI 都测） |
| 库损坏 | `formatforge inbox reindex --force`（删库重建）；文件永不被 DB 操作删除 |
| 回滚版本 | npm 侧可退回 2.0.2；DB 文件向后兼容（schema 只增表/增列，多出的列旧代码忽略） |
| 旧命名产物 | 读取兼容 `<stem>.ff.json`；写入切新命名；下个 minor 移除旧读路径 |
| 多 profile / 多机 | 库在 `DSH_HOME`，天然按用户隔离；不做同步（沿用"不做远程/多用户"决策） |
| A 层（storageDomain）升级 | `version` 只在破坏性变更时 +1，**同时换域名**（`formatforge.ui.v2`），旧域只读 + 一次性搬迁函数；纯新增字段不改 version |
| A 层数据丢失 | 设置类数据可重建（缺省值兜底）；产物真相源永远在文件 + SQLite，A 层坏了不影响产物 |

---

## 10. 明确不做（沿用既有决策，避免范围蔓延）

- ❌ 云端 AI 增强、出站网络（ROADMAP:167）
- ❌ 多用户 / 远程部署 / 认证体系（PLUGIN_PLAN:47）
- ❌ 引入任何 npm 运行时依赖（`dependencies` 保持 `{}`）
- ❌ 把正文全量入库（只索引元数据 + 摘要）
- ❌ 复活 FastAPI/`main.py` 那套 Web 后端（只复活前端，后端用插件内 Node 路由）
- ❌ 改写 `protocol/v1` 既有字段语义

---

## 11. 需要你拍板的 4 件事

| # | 决策 | 选项 | 我的推荐 |
|---|---|---|---|
| 1 | **UI 形态** | A 只做右侧面板 / B 只做 `main` 整窗口页 / C 只做自托管页 / **D 组合** | **D**：P1 上右侧面板（轻入口），P2 上 **`main` 整窗口页**（重界面），同一份构建产物再挂一个 `/formatforge/ui`（不依赖插槽的降级/大屏通道）；宿主的 `deliverables.*` 面板作为"自动出现"的第三入口 |
| 2 | **持久化分工** | ① 全放 SQLite / ② **分层**（设置走 `ctx.storageDomain`，产物索引走 SQLite）/ ③ 全走 `ctx.storageDomain` | **②分层**：设置用平台公开契约（省事、跟 DSH_HOME 走），产物索引必须 SQLite（storageDomain 无 FTS、整域驻内存） |
| 3 | **前端策略** | 复活冻结 `frontend/`（Lit 3 + Vite）重构 / 从零新写 | **复活 + 重构**（组件、i18n、token 都现成，省 3–5 天）；两个 lane 复用同一构建产物 |
| 4 | **版本与节奏** | v2.2.0(DB)→v2.3.0(UI) 分两次发 / 一次大版本 v3.0 | **分两次**：P0 出口先发 v2.2.0（纯 DB，向后兼容），UI 完成再发 v2.3.0 |

> 另有两项**不需要你决策、但会被写进实现**的事：① `engines.node` 保持 `>=22.13.0` 不动（不因 `node:sqlite` 抬高门槛），改用**运行时特征检测 + CLI 降级**；② 新增 API 一律**自建 token 校验**（§8-R10）。

拍板后我会先做 **P-1（半天到一天）**：修 `ff_result` 字段错配 + 定命名 + 定版本号，然后按 P0 → P1 → P2 推进；每个阶段结束照旧走"全盘自检 → CHANGELOG → tag → Release → npm publish"。

---

## 附：本计划用到的实测证据

| 结论 | 验证方式 |
|---|---|
| `node:sqlite` 免 flag 可用 | ① 本机 Node v22.23.1 `require('node:sqlite')` → OK；② **shipped runtime（Node 24.18.1）实测**：建 FTS5 虚表 + `MATCH` 查询成功，导出 `DatabaseSync/StatementSync/Session/constants/backup` |
| 宿主进程模型与 ABI | `lib/main.js:3673-3691` 以 `spawn(node, ["--expose-internals", …])` 拉起独立 Node 子进程；`ELECTRON_RUN_AS_NODE=1`（`:3529-3534`）。实测该进程 `node v24.18.1 / electron 44.0.0 / chrome 152 / modules 149` |
| 宿主运行时版本 | `resources/runtime/versions.json` → node 24.18.1 / pnpm 11.7.0；`resources/version` → Electron 44.0.0 |
| Python SQLite 能力 | venv 实测：sqlite 3.45.3、FTS5 ✓、trigram ✓、json1 ✓、WAL ✓ |
| 中文分词选择 | FTS5 `unicode61`：`match '付款'` → **0 行**；`trigram`：`match '付款条款'` → 1 行 |
| 插槽清单与用途 | 71 个 shipped `lib/client.js` 提取出 **68 个可注入插槽**；`main`（整窗口页，owner plugin-manager/schedule/conversation）、`sidebar.right.pane.tab`（8 个注册者）、`deliverables.*`（owner `dsh-client-ui-deliverables`）、`settings.section` 等 |
| 插槽纪律 | `SlotMap` 空表 + `declare module` 增补；注册到未声明插槽**加载期抛错**（`dsh-client-ui-slots/README.md` internals） |
| 前缀路由 | `dsh-client-modules/lib/index.js:546-550` 用 `kind:"prefix"` 托管 `/plugins`；路由匹配 exact → 最长 prefix → fallback（`dsh-host-webserver/lib/index.js:322-334`） |
| 鉴权围栏边界 | `dsh-host-webserver/README.md:39,113`「无 TLS/鉴权/origin 策略」；`dsh-client-connection/lib/index.js:587-588` 只守 `/api`（403/401）→ 我们的路由在围栏外 |
| 插件级持久化 | `ctx.storageDomain`（`dsh-storage-domain/README.md`）：`defineDomain/open/table.get(同步)/put/update/delete`、单 write chain、zod 校验、**无迁移**；挂载点 `dsh-base/cordis.patch.yml:161-186`；`~/.dsh/storages/*.json` + `.bak-<ts>` |
| 平台自带 FTS5 先例 | `dsh-session-query-sqlite/lib/index.js:50,106,136,167`（`await import('node:sqlite')` + FTS5 + 谓词预算 14），默认 `openAt: never` |
| 插槽使用范式 | `dsh-client-ui-workspace/README.md:147-163`（`inject → register({name,id,order,locale,inject}, Component)`）；`ctx.shortcuts.register`（workspace:109）、`ctx.layout.selectPanel`（workspace:969） |
| `ff_result` 字段错配（**已实测**） | 向运行中的宿主收件箱投真实文件 → 产出 `ff-plan-probe-20261002.ff.json`，检查键集合：`data` = content/format/meta/structured_data/quality；`has convertedContent=false, fileInfo=false, resultId=false`；`meta.result_id=cvt202610020216178c771b` —— 对照 `tools/result.mjs:202,212,214-216` |
| 真实产物链路可用 | 同上：投递后 ~12 s 内产出 `.ff.json` + `.ff.md`（v2.0.2 实机 watcher）；探针文件已清理 |
