# DSH-FormatForge

**把任意文件拖进 DeepSeek Harness，立刻变成 AI 能读懂的数据。**

[![Version](https://img.shields.io/npm/v/@tianbuyu-wwx/dsh-formatforge)](https://www.npmjs.com/package/@tianbuyu-wwx/dsh-formatforge)
[![Status](https://img.shields.io/badge/status-production--ready-brightgreen)](https://github.com/Tianbuyu-wwx/DSH-FormatForge/releases)
[![CI](https://github.com/Tianbuyu-wwx/DSH-FormatForge/actions/workflows/ci.yml/badge.svg)](https://github.com/Tianbuyu-wwx/DSH-FormatForge/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![Node](https://img.shields.io/badge/Node-22%2B-green)](https://nodejs.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

> **v1.0 production-ready**（2026-09）：协议冻结（`packages/dsh-formatforge/protocol/v1/`），向后兼容承诺启用。

DSH-FormatForge 是一个 [DeepSeek Harness](https://github.com/deepseek-ai) 插件：把 PDF、DOCX、PPTX、XLSX、EML、EPUB、TOML 等 **30+ 种格式**锻造成 AI 模型可直接消化的结构化文本——直接**拖进 dsh 网页**，或在对话里粘贴文件路径。

> 项目前身是「Data-Format-Translator / AI 数据转换器」（Web 服务形态，冻结于 `v2.1.0-ci-green`）。
> v3.0 起完全重构为 dsh 插件：无 Web 界面、无内置 AI 客户端，专注「格式 → 结构化数据」这一层。

## 它解决什么问题

dsh 的 `read` 工具读 PDF/DOCX 这类二进制是乱码；官方附件通道只认图片。
装上 FormatForge 后：

```
拖 report.pdf 进 dsh 网页
  → 右下角提示「正在锻造…」
  → 数秒后对话收到通知：report.pdf 已锻好 (parser=pdf, confidence=0.95)
  → 直接基于这份文件继续提问
```

也可以不走拖拽：在对话里粘贴本地路径（`E:\docs\report.docx`），agent 会按约定先调用 `ff_translate` 再回答。

![拖拽锻造 toast](assets/screenshot-drop.png)
![FormatForge 收件箱产物](assets/screenshot-inbox.png)
![会话锻造完成通知](assets/screenshot-notice.png)

## 安装

> **适配目标：DeepSeek Harness 0.2.0-rc.2**（Electron 桌面版）。
> 0.2.0 起 profile 由应用托管：桌面端用 `desktop` profile，普通 web/tui 用各自 profile。
> 兼容性与安装拒绝规则见 [ADAPTATION_PLAN.md](ADAPTATION_PLAN.md)。

### 前置

| 依赖 | 说明 |
|---|---|
| Python ≥ 3.10 | 运行转换内核；解释器探测顺序 `FF_PYTHON` → `<repo>/.venv-fg` → PATH |
| Node ≥ 22 | dsh 本身的要求 |

### 方式一：从源码安装（本地开发，推荐用于本仓库）

```bash
git clone https://github.com/Tianbuyu-wwx/DSH-FormatForge.git DSH-FormatForge
cd DSH-FormatForge
pip install -e .                 # 或 python -m venv .venv-fg && .venv-fg/Scripts/pip install -e .

# 装进桌面端 profile（0.2.0：add ≠ 激活，重启桌面端才生效）
dsh plugin --profile desktop add "$(pwd)/packages/dsh-formatforge"

# 检查
dsh plugin --profile desktop ls          # 依赖里应出现 @tianbuyu-wwx/dsh-formatforge
python scripts/verify-install.py --skip-inbox   # 重启之后跑，应 ALL GREEN
```

`add` 成功后宿主会把本包**自动追加**进 profile `package.json` 的
`dsh.profile.bundles`（`reconcileProfilePlugins`），无需手工编辑。

**不需要**再跑 junction 修复脚本：0.2.0 的 launcher 为 linked profile 包内建了
peer-aware 解析（`dsh-app-boot::routeLinked()`），`@deepseek-ai/dsh-tools` 等 peer
直接命中宿主运行时那一份。`scripts/rebuild-plugin-junctions.py` 只对 0.1.x 宿主有意义。

### 方式二：从 npm 安装

```bash
npx @deepseek-ai/dsh plugin --profile desktop add @tianbuyu-wwx/dsh-formatforge
# 重启 DeepSeek Harness 生效
```

npm 包只是插件壳，仍需一份可运行的 Python 内核（本仓库）并告知位置：

```bash
# 给法 A：clone 本仓库并安装内核（推荐，含全部解析器依赖）
git clone https://github.com/Tianbuyu-wwx/DSH-FormatForge.git DSH-FormatForge
cd DSH-FormatForge && pip install -e .
setx FF_REPO_ROOT "D:\DSH-FormatForge"

# 给法 B：已有环境？只要它 import 得到 core/parsers：
setx FF_PYTHON "C:\path\to\your\python.exe"
```

### 生效验证

重启后在启动日志里找这一行：

```
[dsh-formatforge v2.0.0] tools registered: ff_translate, ff_formats, ff_result, ff_batch, ff_diff
```

再跑 `python scripts/verify-install.py`（桌面端需 `--token`，见脚本 `--help`）。

## 使用

### 1. 网页拖拽（零学习成本）

把任何支持的文件拖进 dsh 网页任意位置：

- 非图片文件 → 自动上传并锻造，右下角 toast 显示进度与结果
- 图片 → 走 dsh 原生图片附件通道（不受影响）
- 转换完成后活跃会话收到轻量通知，附产物路径

产物落在收件箱目录（默认 `~/.dsh/formatforge/inbox/`）：
`<名字>.ff.md`（可直接阅读）+ `<名字>.ff.json`(完整协议数据)。

### 1.5 面板（v3.0.0）

**入口在左侧栏导航里**（「插件 / 自动化任务」下面的 **FormatForge**，点击后主区域打开库页面）；
同时也注册了宿主右侧栏页签（同一套组件，窄栏自适应）与侧栏底部按钮，随手可用。

- 搜索产物（**中文子串可用**：FTS5 trigram，短词自动走 LIKE 兜底）
- 列表显示来源 / 解析器 / 体积 / 时间 / 失败标记，点开看正文预览与元数据
- 行内动作：复制路径 · **重新锻造**（删产物并让 watcher 重跑）· 从列表移除（软删，磁盘文件保留）
- 每页条数偏好持久化（与索引库同库：`settings` 表）

面板是**增强项**：宿主契约变化（插槽未声明、拿不到 react、没有 `sidebarRightTabs`）时只记日志，
拖拽与工具完全不受影响。数据来自 `/formatforge/api/*`（同源请求；非浏览器访问需 `~/.dsh/formatforge/api-token`）。

### 1.6 收件箱索引库（v3.0.0）

`.ff.md` / `.ff.json` **仍是真相源**；`index.db`（SQLite，与收件箱同级）只存元数据 + 全文索引，删库可重建：

```bash
python -m formatforge inbox stats            # 库状态（条数/体积/格式分布/分词器）
python -m formatforge inbox query --q 付款条款 --limit 20
python -m formatforge inbox reindex          # 从 .ff.json 幂等回填（首次升级用）
python -m formatforge inbox backup --out ~/ff-backup.db
```

工具侧新增 `ff_result {search:"付款条款"}`、`ff_result {stats:true}`、`ff_result {list:true, limit:20}`。

### 2. 对话内工具

| 工具 | 用途 |
|---|---|
| `ff_translate` | 转换：`path`（单个）/ `paths`（多个，支持 `*` glob）/ `text` 三选一；`format` json·markdown·html·text；`max_chars`/`offset` 分页；`quality` 附质量报告 |
| `ff_formats` | 列出支持的输入格式矩阵 |

### 3. CLI（脱离 dsh 也能用）

```bash
pip install -e .   # 之后
python -m formatforge translate document.pdf --format markdown
python -m formatforge translate --stdin-text < notes.txt
python -m formatforge formats      # 支持格式矩阵
```

stdout 输出单行协议 JSON（`{ok, code, data:{content, meta, quality?, enhance?}}`），日志走 stderr，退出码 0/2/3/4。

## enhance 协议 —— 模型增强交给会话本身

插件**不带任何 AI 客户端**。当纯规则转换不足以产出高质量结果时，返回里会出现：

```jsonc
"enhance": {
  "needed": true,
  "reason": "image_only",   // image_only | low_confidence | table_sparse
  "hint": "4/4 页无文字层（疑似扫描件）..."
}
```

SKILL.md 会指导当前会话模型：**按 hint 直接用自己的能力完成增强**（如基于 OCR 文本重建表格），不调用任何外部 API。模型永远与 dsh 会话一致，零密钥配置。

## 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `FF_REPO_ROOT` | 自动探测 | 含 `formatforge/ core/ parsers/` 的仓库根 |
| `FF_PYTHON` | 探测链兜底 PATH | 指定解释器（≥3.10） |
| `FF_MAX_BYTES` | 104857600 | 单文件上限（100MB） |
| `FF_TIMEOUT_S` | 120 | 单次转换超时（秒） |
| `FF_INBOX_NOTIFY` | **false** | 是否把「已锻好」推进会话 transcript。v2.0.1 起默认关：宿主没有临时通知通道，推送只能落成 `user/message`，会被当成用户发言、永久留在上下文里、且只有运行中的会话收得到。收件箱是共享目录，改用 `ff_result {list:true}` 拉取 |
| `FF_HOME` | `$DSH_HOME/formatforge` → `~/.dsh/formatforge` | 收件箱根目录（优先于 `DSH_HOME`） |
| `FF_DB` | 不设置（=开） | **v3.0.0**：`off` 时整体停用索引库，回到纯文件路径（list/search 自动退回文件扫描） |
| `FF_DB_PATH` | `$FF_HOME/index.db` | **v3.0.0**：索引库文件位置（设置/偏好同库） |
| `OCR_ENABLED` | true | 启用本地 OCR（tesseract/paddleocr/easyocr 任一） |

## 架构

```
浏览器拖拽 ──POST /formatforge/upload──┐
                                       ▼
                          ~/.dsh/formatforge/inbox/
                                       │ fs watcher（去重·稳定检测）
对话路径 ── ff_translate ──┐            ▼
CLI     ── python -m … ──► formatforge 内核（30+ 解析器 × 7 策略）
                           │            ▼
                           │    协议 JSON {content, meta, quality?, enhance?}
                           ▼            
                    会话轻量通知（仅元数据，不注全文）
```

- **Python 内核**（`core/` + `parsers/` + `formatforge/`）：格式检测、管线编排、策略选择、质量评分
- **Node bundle**（`packages/dsh-formatforge/`）：工具注册（cordis）、client 拖拽模块、inbox watcher、HTTP 上传路由

## 开发

```bash
pip install -e ".[dev]"
pytest test/                                   # 本地 575 passed（CI 为权威门禁）
ruff check . && ruff format --check .
mypy core/ parsers/ formatforge/
node packages/dsh-formatforge/test-manifest.mjs        # bundle 清单/契约自检
node packages/dsh-formatforge/test-client-bundle.mjs   # client bundle 按宿主方式执行自检
node packages/dsh-formatforge/test-client-drag.mjs     # 拖拽行为回放（文件夹放行 / × 逃生 / 宿主计数复位）
node packages/dsh-formatforge/test-client-panel.mjs    # 右侧栏面板：注册/渲染/降级路径/400 可诊断性（v3.0.0）
node packages/dsh-formatforge/test-plugin-boot.mjs     # 无宿主启动冒烟 + 8 条路由两参调用（v3.0.0）
node packages/dsh-formatforge/test-api.mjs             # /formatforge/api/*：路由 + 宿主 prefix 匹配仿真 + 鉴权 + 读写 + SSE（v3.0.0）
node packages/dsh-formatforge/test-host-http.mjs       # 真实 node:http + 宿主语义复刻（两参调用 / prefix 匹配 / 注入突变自检）
node packages/dsh-formatforge/scripts/verify-live.mjs  # 对**运行中的**宿主做端到端校验（改完 Node 侧代码、重启后先跑这个）
node packages/dsh-formatforge/test-result-contract.mjs # ff_result 字段口径 + search/stats/limit（v3.0.0）
node packages/dsh-formatforge/test-local.mjs           # stub 环境 e2e（需本机 Python）
node packages/dsh-formatforge/test-inbox.mjs           # inbox watcher e2e
node packages/dsh-formatforge/test/test-truncate-consistency.mjs  # JS↔Python 分页一致性
```

设计文档：[PLUGIN_PLAN.md](PLUGIN_PLAN.md)（插件化实施）· [EVOLUTION_PLAN.md](EVOLUTION_PLAN.md)（v0.4–v0.7 演进）· [ROADMAP.md](ROADMAP.md)（后续计划）· [UI_DB_PLAN.md](UI_DB_PLAN.md)（v3.0.0 的库 + 面板，含取舍与实测证据）

## 已知限制

- 扫描件 PDF 无文字层时依赖本机 OCR 引擎；都没有则返回 `enhance=image_only` 提示由会话模型兜底
- 拖拽模块挂在宿主**未导出**的内部实现上（`dsh-client-ui-attachment` 的 document 冒泡期
  drop 监听）：插件用捕获期先手 `stopPropagation` 完成分流。宿主若改到捕获期或 window 级，
  分流会静默失效（插件不会报错，只是拖拽不再被接管）——已用特征检测思路保守实现，但无公开契约。
  宿主的 `DropOverlay` 同样只用它自己的 `dragDepth` 计数复位，所以插件在吞掉终止事件时会补发
  一次宿主复位（合成 `dragend` + 视口边缘 `dragleave`），并常驻 ×/Esc 逃生入口。
- 文件夹不参与锻造（v2.0.2 起整条拖拽放行给宿主）：一个拖拽里只要出现目录，同批文件也不会被接管——
  要么单独拖文件，要么先打包成 zip。目录判定以 `webkitGetAsEntry()` 为准（与宿主同一判据），
  该 API 在 `dragenter` 阶段可能无应答（MDN：只在 `dragstart`/`drop` 可读），此时按「无 MIME + 0/4096 字节」
  特征**保守放行**：目录名带扩展名（`报告.pdf`）也算目录；代价是一个 0 字节且无 MIME 的真实文件
  在拖动中会被当成疑似目录，松手时再以 entry API 复核并照常锻造。
- ×/Esc 逃生入口只管**当前这一段**拖拽（清遮罩 + 补发宿主复位 + 把剩余事件交回宿主），
  不影响下一次拖拽；拖拽结束后残留的 × 再点一次也只是清场。
- 混合粘贴（剪贴板同时含文件与文本）只取文件，文本不会进入输入框——与宿主自身分支的差异是有意为之。
- **面板插槽是对等插件私有契约**（v3.0.0）：`sidebar.right.pane.tab` 等插槽名由声明它的插件拥有，
  注册到未声明的插槽会在加载期抛错。面板已做探测 + try/catch + 降级（失败只记日志），
  但宿主大版本升级后可能需要对插槽名做适配。
- **面板与 API 的路由不在宿主鉴权围栏内**（围栏只保护 `GET /` 与 `/api`）：`/formatforge/api/*` 自建
  loopback Host 校验 + 同源判定，非浏览器访问需 `~/.dsh/formatforge/api-token`；请勿把宿主绑定到 `0.0.0.0`。
- **索引库需要 `node:sqlite`**（Node ≥22.5；实测宿主 Node 24.18.1 免 flag 可用）：拿不到时 API/面板自动降级为
  "Node 走 CLI 查询"，功能仍可用但每次查询多一次 Python 冷启动（约 0.5s）。
- 检索分词：FTS5 **trigram** 只索引 3 字序列，1–2 字的查询（中文里很常见）走 LIKE 兜底，
  库很大时会退化为扫描（几千条无感；上万条建议用 ≥3 字的检索词）。
- 上传地址用根绝对路径 `/formatforge/upload`，与宿主注册的 exact 路由一致；若将来宿主支持子路径
  托管，客户端与服务端需要同时改。
- Windows 下以中文路径 `link:` 安装时，profile 里的 `package.json`/`pnpm-lock.yaml` 均为正确 UTF-8，
  但用 PowerShell `Get-Content` 查看可能显示为乱码（控制台编码问题，非文件问题）。

## License

MIT
