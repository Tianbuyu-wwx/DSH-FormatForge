# PLUGIN_PLAN.md — DSH-FormatForge 封装为 DeepSeek Harness 插件

> 状态：**Phase 0–6 全部完成**（2026-08-25）
> 交付：插件 v0.3.2（npm `@tianbuyu-wwx/dsh-formatforge`）· CI 7/7 绿 · tag `v0.3.2`
> 能力：拖拽直投 / 路径对话 / CLI 三通道 · inbox 自动锻造 · 会话轻量通知 · enhance 会话模型增强
> 项目新名：**DSH-FormatForge**（原名 Data-Format-Translator / AI 数据转换器）
> 起草：Hermes · 基线：main @ `6610ef1`（CI 全绿：7/7 jobs success）

---

## 0. 决策记录

| 决策点 | 结论 |
|---|---|
| 插件形态 | **A：薄壳 JS bundle + Python CLI**（one-shot spawn，无常驻服务） |
| AI 增强 | **不内置任何 AI 客户端**。需要增强时通过协议字段交给 **dsh 当前会话的默认模型** 完成 |
| 现有 Web 版 | **打 tag `v2.1.0-ci-green` 冻结于 `6610ef1`**，主分支瘦身；复活随时 checkout |
| 项目更名 | **DSH-FormatForge**（格式锻炉）。插件名与旧仓库名不同；语义锚点=README「让混乱的原始文件变成 AI 可直接消化的干净数据」 |

### 0.1 命名映射总表（全文档以此为准）

| 维度 | 旧 | 新 |
|---|---|---|
| 项目/仓库名 | Data-Format-Translator | **DSH-FormatForge** |
| npm 包名（scope 防撞名） | — | `@tianbuyu-wwx/dsh-formatforge` |
| bundle id / 插件目录 | ~~dsh-data-translator~~ | `dsh-formatforge` |
| Python 发行名（pyproject name） | data-format-translator | `dsh-formatforge`（上 PyPI 前再查重） |
| Python 包/CLI 模块 | ~~dft_core~~ | `formatforge`（`python -m formatforge`） |
| 工具名 | ~~dft_translate / dft_formats~~ | **`ff_translate` / `ff_formats`** |
| 环境变量 | DFT_PYTHON / DFT_TIMEOUT_S / DFT_MAX_BYTES | `FF_PYTHON` / `FF_TIMEOUT_S` / `FF_MAX_BYTES` |
| skill 目录 | — | `skills/dsh-formatforge/SKILL.md` |

> 工具名取 `ff_` 前缀的理由：dsh 全局工具表讲究简短（对照 `pwsh`/`read`）；FF=FormatForge 无歧义；
> 安装后用 `dispatch_probe` 校验无冲突即可。

---

## 1. 目标与非目标

**目标**
1. DSH agent 通过 `ff_translate` / `ff_formats` 两个原生工具，把本地文件/文本转为 AI 友好的结构化输出。
2. 主分支删除 Web 服务全套包袱（frontend 115MB、FastAPI 层、认证/限流/SSE/webhook/metrics），保留 17 个解析器核心资产。
3. 插件经 `dsh plugin add` 安装、重启 web 即生效，遵循 hermes-link 验证过的全部 bundle 契约。
4. 项目以 DSH-FormatForge 之名完成 git/文档/包名的整体迁移。

**非目标**
- 不做流式输出（SSE）、多用户并发、远程部署。
- 不在 Python 侧集成任何 LLM SDK。

---

## 2. 总体架构

```
DSH agent（当前会话模型 = DeepSeek）
   │ ① 调工具
   ▼
ff_translate (defineTool, dsh-formatforge bundle)
   │ ② spawn（args 数组，不过 shell；FF_PYTHON → 项目 venv → PATH 探测）
   ▼
python -m formatforge translate <path|--stdin-text> --format json [--quality]
   │ ③ 解析管线（parsers/* 全保留）
   │    策略选择（decision_engine 裁剪版）
   │    质量报告（可选）
   ▼
④ stdout 单行协议 JSON：
   { ok, code, data:{content, format, meta, enhance?} | error:{kind, message} }
   │
   ▼
⑤ 结果回传 agent；若 data.enhance.needed=true → 按 SKILL.md 用会话模型自行增强
```

**关键理念**：FormatForge 的职责边界 = 「把任意格式锻成模型可读的结构化文本」；「读懂并加工」是会话模型的活。AI 层从 Python 移除，改为协议级协作。

---

## 3. Phase 0 — 冻结与改名基线（~15 分钟）

```bash
# 3.1 Web 版终态冻结（精确钉在 CI 绿的提交上）
git tag -a v2.1.0-ci-green 6610ef1 -m "Web 版终态：CI 7/7 绿"
git push origin v2.1.0-ci-green

# 3.2 （可选，需用户点头）GitHub 仓库同步改名——git 自动重定向旧 URL
gh repo edit Tianbuyu-wwx/DSH-FormatForge --new-name DSH-FormatForge
```

## 3.5 Phase 0.5 — 本地目录迁移（⚠️ 需要用户协助）

**现状风险**：本地仓库在中文路径 `E:\项目\...`，而 pnpm junction 对中文路径的写坏复发率 100%。
**动作**：把整个克隆迁到纯 ASCII 路径，如 `E:\projects\DSH-FormatForge`：

1. 用户关闭占用该目录的程序/终端；
2. `robocopy "E:\项目\Data Format Translator" "E:\projects\DSH-FormatForge" /E /MOVE`（或资源管理器剪切）；
3. Hermes 会话工作区重新锚定到新路径（project_switch）；
4. 旧目录确认清空后删除。

此后插件开发全部在新路径进行，junction 问题釜底抽薪。

---

## 4. Phase 1 — Python 瘦身 + CLI（~半天）

### 4.1 删除清单

| 目标 | 理由 |
|---|---|
| `frontend/` | dsh web 自带 UI |
| `main.py`、`api/` | 不再暴露 HTTP 面 |
| `core/middleware.py` | 限流/请求体积/TraceID 是公网防御 |
| `core/auth.py` + API_KEY 配置 | 无 HTTP 无需认证 |
| `core/metrics.py` | 无 Prometheus 抓取方 |
| `core/stream_handler.py` | 同步 JSON 返回，不做 SSE |
| `core/webhook_manager.py` | 回调对 agent 无意义 |
| `core/history_store.py` | 会话历史归 dsh session 管 |
| `UrlInputAdapter` + `core/security.py` | 只收本地路径/raw 文本，SSRF 攻击面消除 |
| `core/ai_client.py`、`provider_registry.py`、`ai_discovery.py`、`ai_prompt_manager.py` | AI 增强移交会话模型 |
| `core/ocr_engine.py` 的 `ai` 后端分支 | 同上；tesseract 本地路径保留为可选依赖 |
| `uploads/ data/ cache/ __pycache__/ *.egg-info requirements.txt` | 运行产物与过期文件 |
| 对应测试 | 随模块删除 |

### 4.2 保留清单（一行不动）

`parsers/` 全部 17 个解析器；`core/` 的 `pipeline*.py`、`models.py`、`format_detector.py`、
`conversion_strategies.py`（裁剪 AI 策略）、`content_cache.py`、`quality_report.py`、
`decision_engine.py`（裁剪版）、`input_adapters.py`（File/Text）、`utils.py`、`config.py`（瘦身后）。

### 4.3 新增 `formatforge/__main__.py`

```
python -m formatforge translate <path> [--format json|markdown|text] [--quality] [--max-bytes N]
python -m formatforge translate --stdin-text
python -m formatforge formats
python -m formatforge version
```

**stdout 协议（唯一出口，日志全走 stderr）：**

```jsonc
// 成功
{ "ok": true, "code": 200,
  "data": {
    "content": "<转换结果>",
    "format": "json|markdown|text",
    "meta": { "parser": "docx", "file_size": 182044, "elapsed_ms": 812 },
    "quality": { },                    // --quality 时才有
    "enhance": {                       // 触发条件满足时才有
      "needed": true,
      "reason": "image_only|low_confidence|table_sparse",
      "hint": "页面为扫描件，请基于 OCR 文本重建结构并补齐表格"
    }
  } }

// 失败
{ "ok": false, "code": 4001,
  "error": { "kind": "unsupported_format|too_large|not_found|parse_failed|internal", "message": "..." } }
```

退出码：`0` 成功 / `2` 参数错 / `3` 解析失败 / `4` 超限。

### 4.4 配置与包名

- `config.py` 删 CORS/API_KEY/RATE_LIMIT/URL_DOMAIN_VALIDATION/Webhook 字段；
  加 `FF_MAX_BYTES`（默认 100MB）、`FF_TIMEOUT_S`（默认 120s）。
- `pyproject.toml`：`name = "dsh-formatforge"`，`description` 更新，
  `[project.scripts]` 加 `formatforge = "formatforge.__main__:main"`。

### 4.5 测试迁移

保留 parsers/pipeline/quality 单测；删 api/middleware/auth/webhook/metrics/stream 相关；
新增 `test/test_cli_protocol.py`（样本矩阵断言协议 JSON 与退出码）。conftest 的限流 hack 随 middleware 删除。

### 4.6 文档

README 重写为「FormatForge —— 把任意格式锻造成 AI 可读数据」三用法（库/CLI/dsh 插件）；全仓 grep 替换旧名。

---

## 5. Phase 2 — Node bundle（~半天）

### 5.1 目录结构（模板 = `dsh-hermes-link`）

```
packages/dsh-formatforge/
├── index.mjs                 # export const name/inject; export function apply(ctx)
├── tools/
│   ├── translate.mjs         # defineTool → ff_translate
│   └── formats.mjs           # defineTool → ff_formats
├── services/
│   └── python-runner.mjs     # 解释器探测 + spawn + 超时杀树 + JSON 校验
├── skills/dsh-formatforge/SKILL.md
├── cordis.patch.yml
└── package.json              # name=@tianbuyu-wwx/dsh-formatforge; keywords 含 dsh-bundle
```

### 5.2 工具面（只有两个）

```js
defineTool({
  name: 'ff_translate',
  description: 'FormatForge：把本地文件或原始文本(pdf/docx/xlsx/pptx/eml/msg/toml/yaml/md/csv/json/html/svg/epub/zip…) '
             + '解析为 AI 友好的结构化 JSON/Markdown/text。只接受存在的本地路径；'
             + '返回 data.enhance.needed=true 时应按提示用当前会话模型增强。',
  parameters: {
    path:    { type: 'string', description: '本地文件绝对路径（与 text 二选一）' },
    text:    { type: 'string', description: '原始文本内容（与 path 二选一）' },
    format:  { type: 'string', enum: ['json','markdown','text'], default: 'json' },
    quality: { type: 'boolean', default: false },
  },
})
```

`ff_formats()` 返回格式支持矩阵。

### 5.3 python-runner.mjs 要点

探测链 `FF_PYTHON` → `<repo>/.venv-fg/Scripts/python.exe` → PATH `python`（启动校验 ≥3.10 并缓存）；
spawn 一律 args 数组；超时杀进程树（Windows `/T`）；stdout 单 JSON 解析失败→internal 错误附 stderr 摘要；
stat clamp 存在/是文件/≤100MB；拒绝 URL 与目录。

### 5.4 DSL 契约四坑（bootfix #2 实录）

minimum/maximum 不支持→handler 内 clamp；嵌套 object 显式 additionalProperties；
output.required 逐字段标注；用了哪个 ctx 服务就必须进 `export const inject`（本插件预计只需 `['workspaceRegistry']`）。

---

## 6. AI 增强协议（决策 2 落地）

触发条件：`image_only` / `low_confidence` / `table_sparse`。
SKILL.md 指导语：「当 `enhance.needed=true`：你基于 `data.content` 按 `enhance.hint` 直接产出最终答案，不要调用外部 API。」
备选升级：整册扫描 PDF 等重活由 bundle 经 `ctx.subagents` spawn 子代理处理（Phase 4 可选）。

---

## 7. Phase 3 — 安装与实测 SOP（~1 小时）

```bash
cd ~/.dsh/profiles/web && grep -q minimumReleaseAge pnpm-workspace.yaml || echo "minimumReleaseAge: 0" >> pnpm-workspace.yaml
npx @deepseek-ai/dsh plugin add --profile web E:/projects/DSH-FormatForge/packages/dsh-formatforge
# 两阶段规则：add ≠ 激活；重启 web 才生效
# ⚠️ add 后必做：diff bundles 快照护住 hermes-link；cat junction/package.json 验活
powershell 重启 web → 启动日志看工具注册行 → curl /mcp/collab/health
dispatch_probe {"skill":"ff_translate"} → e2e: dispatch_task 转真实 pdf
```

---

## 8. Phase 4 — CI 与发布（可选）

- ci.yml：删 frontend job；smoke 改 CLI 样本矩阵 e2e；新增 node --test job。
- 发布选项：GitHub 改名后的 repo / npm `@tianbuyu-wwx/dsh-formatforge` / 仅本机 link。

---

## 11. Phase 5 — 文件投递：让 dsh 对话「吃」文件（2026-08-24 立项）

**问题**：dsh 对话无法直接附加 PDF/DOCX/PPTX 等二进制文件（`read` 只能读文本，读二进制全是乱码）。
**决策**：层 1 + 层 2 本轮实现；层 3 仅留占位。
已拍板：会话通知默认**开**；inbox 位置**固定** `~/.dsh/formatforge/inbox/`；层 3 占位不实现。

### 11.1 层 1 · 路径约定强化（零新代码）

- SKILL.md 增加硬规则：「用户消息中出现指向存在的本地文件的绝对路径时，
  若格式可转换，必须先 `ff_translate` 再回答；禁止用 read 读二进制格式」。
- `ff_translate` 增强：支持 `paths` 数组（多文件）与简单 glob（如 `*.pdf`）、
  新增 `max_chars` 参数做内容分页（配合 render 截断提示）。

### 11.2 层 2 · Inbox 投递箱 + 自动转换（主交付）

```
~/.dsh/formatforge/inbox/
  └── report.pdf            ← 用户拖入（资源管理器/cp/另存为均可）
      → fs watcher 触发自动转换
      ├── report.ff.json    ← 完整协议 JSON
      └── report.ff.md      ← 纯内容版（可直接阅读）
```

组件：
1. `services/inbox-watcher.mjs` —— chokidar/fs.watch 轮询 inbox；
   文件稳定（size 两次采样不变）后触发转换；复用 ContentHashCache 语义去重
   （同内容文件跳过，产物已存在且 mtime 较新也跳过）；转换后原文件保留不删。
2. **会话通知（默认开，吸取 hermes-link v0.2.1 教训只注轻量摘要）**：
   转换完成 → 向每个活跃 dsh 会话 append 一条通知事件：
   `[FormatForge] report.pdf 已锻好 (parser=pdf, confidence=0.95, 4 页)。
    结果: .../report.ff.md 。输入"继续"即可基于该文件提问。`
   只含文件名+元数据+结果路径，**不含全文**（防跨项目上下文污染）；
   `FF_INBOX_NOTIFY=false` 可关。surfaceOp 用字符串 `'append'`（bootfix #2 契约）。
3. 失败处理：转换失败写 `<name>.ff.error.txt`（含 kind/message），同样发轻量通知；
   不重试（用户重新拖入即手动重试）。
4. 大小/类型 clamp 与 ff_translate 一致（FF_MAX_BYTES；不支持格式直接报 unsupported_format）。

### 11.5 Phase 6 — 网页端拖拽直投（2026-08-25 实装，v0.3.0）

**6A 侦察结论**（函数级证据）：
- 官方附件 MIME 白名单硬拦非图片：`dsh-client-ui-conversation` 的 `imageMediaType()`
  只认 png/jpeg/webp/gif，其余 throw `UnsupportedImageMediaTypeError`
- 图片 = base64 内嵌 prompt content（`serializeImages` → `{type:'image',mediaType,data,name}`），
  无独立上传端点——协议层没有文档附件概念 → **路线乙确认**
- 宿主 client 模块系统（正门）：包内 `lib/client.js` + package.json 声明
  `"dsh": {"client": {...}}` 且 exports 提供 `"./client"` 子路径 →
  宿主自动挂 `/plugins/<pkg>/client.js?rev=` 并注册进 boot manifest

**实装**：
- `http/upload.mjs`：POST /formatforge/upload —— raw body 流式落盘 inbox，
  x-ff-filename 头传名（免 multipart 解析），扩展名白名单+FF_MAX_BYTES+文件名消毒，
  同名自动加序号；GET /formatforge/health
- `lib/client.js`：`window.__ModuleLoader__.load({id, factory})` 包裹形态；
  捕获阶段拦 drop/paste，partition 分流——图片放行原生管线，
  非图片 fetch 上传（右下 toast 进度），混合拖拽时图片经合成 DataTransfer 归还原生流
- index.mjs v0.3.0：inject 加 webServer

**踩坑**：只声明 `dsh.client` 不够——宿主要求 exports 必须有 `"./client"`
子路径映射到 client.js，否则 boot 崩 `declares dsh.client but exports no "./client" bundle`。

**验证**：manifest 收录 ✓ / client.js 200 ✓ / upload→watcher 锻造 ✓ /
415 拒绝 exe ✓ / hermes-link 与既有 e2e 无回归 ✓

### 11.4 验收

1. 拖一个 DOCX 进 inbox → ≤10s 出现 `.ff.json/.ff.md`，活跃会话收到一条通知。
2. 同一文件重复拖入 → 跳过（去重生效），不发重复通知。
3. 拖入 `.exe` → `.ff.error.txt` 写 unsupported_format，通知带错误 kind。
4. `FF_INBOX_NOTIFY=false` 时一切照常但不注入会话。
5. 既有 e2e（ff_translate 直连路径）不回归。

---

## 9. 风险与回滚

| 风险 | 对策 |
|---|---|
| 中文路径 junction 写坏 | Phase 0.5 整体迁 ASCII 路径；add 后验活 |
| bundles 挤掉 hermes-link | add 前后 diff package.json |
| spawn 错误 Python | 探测链 + 版本断言 + kind=internal 诊断 |
| 大文件超时 | JS 杀树 + timeout 错误 + 上限 clamp |
| PyPI/npm 撞名 | scope `@tianbuyu-wwx/` 兜底；PyPI 名 Phase 1 查重后再定 |
| Web 版反悔 | checkout tag `v2.1.0-ci-green` |

## 10. 验收标准

1. `pip install -e .` 后 `python -m formatforge translate samples/demo.docx --format markdown` 输出合法协议 JSON。
2. dsh web 带 `dsh-formatforge` 启动无 ERR；`dispatch_probe` 认得 `ff_translate/ff_formats`。
3. 端到端：dispatch 真实 PDF 任务，agent 正确处理 `enhance` 提示。
4. slim main：pytest/ruff/mypy 三绿；不含 frontend/api/main.py。
5. `git checkout v2.1.0-ci-green` 完整回到 Web 版。
