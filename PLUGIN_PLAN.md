# PLUGIN_PLAN.md — DFT 封装为 DeepSeek Harness 插件

> 状态：**待 review**（本文档确认后才动代码）
> 决策人：@Tianbuyu-wwx · 起草：Hermes · 2026-08-24
> 基线：main @ `6610ef1`（CI 全绿：7/7 jobs success）

---

## 0. 决策记录

| 决策点 | 结论 |
|---|---|
| 插件形态 | **A：薄壳 JS bundle + Python CLI**（one-shot spawn，无常驻服务） |
| AI 增强 | **不内置任何 AI 客户端**。需要增强时通过协议字段交给 **dsh 当前会话的默认模型**（即调用工具的 agent 本尊）完成 |
| 现有 Web 版 | **打 tag `v2.1.0-ci-green` 冻结**，主分支瘦身；复活随时 checkout |
| 本轮范围 | 仅本计划文档，review 后按 Phase 开工 |

---

## 1. 目标与非目标

**目标**
1. DSH agent 能通过 `dft_translate` / `dft_formats` 两个原生工具，把本地文件/文本转为 AI 友好的结构化输出。
2. 主分支删除 Web 服务全套包袱（frontend 115MB、FastAPI 层、认证/限流/SSE/webhook/metrics），保留 17 个解析器这一核心资产。
3. 插件可经 `dsh plugin add` 安装、重启 web 即生效，遵循 hermes-link 验证过的全部 bundle 契约。

**非目标**
- 不做流式输出（SSE）、不做多用户并发、不做远程部署。
- 不在 Python 侧集成任何 LLM SDK。

---

## 2. 总体架构

```
DSH agent（当前会话模型 = DeepSeek）
   │ ① 调工具
   ▼
dft_translate (defineTool, index.mjs bundle)
   │ ② spawn（args 数组，不过 shell；DFT_PYTHON → 项目 venv → PATH 探测）
   ▼
python -m dft_core translate <path|--stdin> --format json [--quality]
   │ ③ 解析管线（parsers/* 全保留）
   │    策略选择（decision_engine 裁剪版）
   │    质量报告（可选）
   ▼
④ stdout 单行协议 JSON：
   { ok, code, data:{content, format, meta, enhance?} | error:{kind, message} }
   │
   ▼
⑤ 工具结果原样回传 agent；
   若 data.enhance.needed=true → SKILL.md 指导 agent 用自身模型完成增强
   （转换/摘要/表格修复/图片描述……），必要时再跑一次 dft_translate 校验
```

**关键理念**：DFT 的职责边界 = 「把任意格式变成模型可读的结构化文本」；「读懂并加工」本来就是会话模型的活。因此 AI 层整体从 Python 中移除，改为协议级协作。

---

## 3. Phase 0 — 冻结与分支策略（~15 分钟）

```bash
git tag -a v2.1.0-ci-green -m "Web 版终态：CI 7/7 绿（test/lint/frontend/security/smoke 全过）"
git push origin v2.1.0-ci-green
```

之后所有瘦身在 main 上进行。回滚 = `git checkout v2.1.0-ci-green`。

---

## 4. Phase 1 — Python 瘦身 + CLI（~半天）

### 4.1 删除清单

| 目标 | 理由 |
|---|---|
| `frontend/` | dsh web 自带 UI，无第二前端必要（115MB 大头） |
| `main.py`、`api/`（v1/v2/OpenAPI） | 不再暴露 HTTP 面 |
| `core/middleware.py` | 限流/请求体积/TraceID 是公网防御，本地 spawn 用不上 |
| `core/auth.py` + API_KEY 配置 | 无 HTTP 无需认证 |
| `core/metrics.py` | 无 Prometheus 抓取方 |
| `core/stream_handler.py` | 工具调用是同步 JSON 返回 |
| `core/webhook_manager.py` | 回调对 agent 无意义，结果直接回传 |
| `core/history_store.py` | 会话历史归 dsh session 管 |
| `UrlInputAdapter` + `core/security.py` | 只收本地路径/raw 文本，SSRF 攻击面直接消除；远程内容由 agent 先用 pwsh 下载 |
| `core/ai_client.py`、`core/provider_registry.py`、`core/ai_discovery.py`、`core/ai_prompt_manager.py` | AI 增强移交会话模型（决策 2） |
| `core/ocr_engine.py` 的 `ai` 后端分支 | 同上；本地 tesseract 路径保留为可选依赖 |
| `uploads/ data/ cache/ __pycache__/ *.egg-info requirements.txt` | 运行产物与过期文件 |
| 对应测试：`test/integration/*`、middleware/auth/metrics 相关单测 | 随模块删除 |

### 4.2 保留清单（核心资产，一行不动）

`parsers/` 全部 17 个解析器；`core/` 的 `pipeline*.py`、`models.py`、`format_detector.py`、
`conversion_strategies.py`（裁剪 AI 策略后保留主干）、`content_cache.py`、`quality_report.py`、
`decision_engine.py`（裁剪版）、`input_adapters.py`（仅 File/Text 适配器）、`utils.py`、`config.py`（瘦身后）。

### 4.3 新增 `dft_core/__main__.py`（CLI 入口）

```
python -m dft_core translate <path> [--format json|markdown|text] [--quality] [--max-bytes N]
python -m dft_core translate --stdin-text          # raw 文本走 stdin
python -m dft_core formats                          # 支持格式表（供 dft_formats 工具）
python -m dft_core version
```

**stdout 协议（唯一出口，日志全走 stderr）：**

```jsonc
// 成功
{ "ok": true, "code": 200,
  "data": {
    "content": "<转换结果字符串或内嵌 JSON>",
    "format": "json|markdown|text",
    "meta": { "parser": "docx", "file_size": 182044, "elapsed_ms": 812 },
    "quality": { ... },              // --quality 时才有
    "enhance": {                      // 触发条件满足时才有
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

### 4.4 配置瘦身

`config.py` 删除 CORS/API_KEY/RATE_LIMIT/URL_DOMAIN_VALIDATION/Webhook 字段；
新增 `DFT_MAX_BYTES`（默认 100MB）、`DFT_TIMEOUT_S`（默认 120s，实际执行方在 JS 侧）。

### 4.5 测试迁移

- 保留并继续绿：parsers 单测、pipeline 单测、quality 单测。
- 删除：api/middleware/auth/webhook/metrics/stream 相关测试。
- 新增：`test/test_cli_protocol.py` —— 样本文件矩阵（pdf/docx/xlsx/pptx/eml/toml/md/csv/json/html/svg…）
  断言协议 JSON 形状与退出码。
- 附带收益：`conftest.py` 的限流 hack 可随 middleware 一起删掉。

### 4.6 文档

README 重写为「Python 库 + CLI + dsh 插件」三用法；删除 Web 截图与部署章节。

---

## 5. Phase 2 — Node bundle（~半天）

### 5.1 目录结构（模板 = 用户自己的 `dsh-hermes-link`）

```
packages/dsh-data-translator/
├── index.mjs                 # export const name/inject; export function apply(ctx)
├── tools/
│   ├── translate.mjs         # defineTool → dft_translate
│   └── formats.mjs           # defineTool → dft_formats
├── services/
│   └── python-runner.mjs     # 解释器探测 + spawn + 超时杀树 + JSON 校验
├── skills/dsh-data-translator/SKILL.md
├── cordis.patch.yml          # loader insert 条目（照抄 hermes-link 格式）
└── package.json              # keywords 含 "dsh-bundle"；engines node>=22
```

### 5.2 工具面（刻意只有两个）

```js
defineTool({
  name: 'dft_translate',
  description: '把本地文件或原始文本(pdf/docx/xlsx/pptx/eml/msg/toml/yaml/md/csv/json/html/svg/epub/zip…) '
             + '解析为 AI 友好的结构化 JSON/Markdown/text。只接受存在的本地路径；'
             + '返回 data.enhance.needed=true 时应按提示自行用当前会话模型增强。',
  parameters: {
    path:    { type: 'string', description: '本地文件绝对路径（与 text 二选一）' },
    text:    { type: 'string', description: '原始文本内容（与 path 二选一）' },
    format:  { type: 'string', enum: ['json','markdown','text'], default: 'json' },
    quality: { type: 'boolean', default: false },
  },
  // output.schema 注意：嵌套 object 必须显式 additionalProperties；required 逐字段标注
})
```

`dft_formats()` 返回格式支持矩阵，供 agent 在不确定扩展名时自查。

### 5.3 python-runner.mjs 要点

1. 探测顺序：`DFT_PYTHON` env → `<repo>/.venv-dft/Scripts/python.exe` → PATH `python`；
   启动时跑一次 `--version` 校验 `>=3.10` 并缓存。
2. `spawn(python, args)` 数组形式——绕开 shell 转义与中文路径两大坑。
3. 超时（默认 `DFT_TIMEOUT_S`=120s）→ 杀整棵进程树（Windows 用 `/T`）→ 返回 `timeout` 错误。
4. stdout 严格单 JSON 解析失败 → 包装成 `internal` 错误并附 stderr 摘要。
5. 安全 clamp：`stat` 检查存在/是文件/≤100MB；拒绝 URL 与目录；工作区外路径交由 dsh 自身审批弹窗。

### 5.4 DSL 契约四坑（bootfix #2 实录，写码前必查）

| 坑 | 规则 |
|---|---|
| minimum/maximum | value-schema **不支持**，handler 内 clamp |
| 嵌套 object | 必须显式 `additionalProperties: true\|false` |
| output.required | 逐字段 `required: true`，不是数组 |
| ctx 服务 | 用了哪个 `ctx.<svc>` 就必须出现在 `export const inject`（本插件预计只需 `['workspaceRegistry']`） |

---

## 6. AI 增强协议（决策 2 的落地细节）

**触发条件**（Python 侧判定）：`image_only`（无文字层页占比高）、`low_confidence`（质量分 < 阈值）、
`table_sparse`（检测到表格但抽取稀疏）。

**执行方式**：工具结果带 `enhance` 字段返回 → SKILL.md 明确指导 agent：

> 当 `enhance.needed=true`：你（当前会话模型）基于 `data.content` 里的原始材料，
> 按 `enhance.hint` 直接产出增强后的最终答案；不要尝试再次调用外部 API。

**备选升级（Phase 4 可选）**：重增强场景（整册扫描 PDF 的逐页描述）改由 bundle 通过
`ctx.subagents` spawn 子代理处理（自动继承会话模型/tier），避免撑爆主上下文。
hermes-link 已验证 `inject` 列表含 `subagents`，可行性有据。

---

## 7. Phase 3 — 安装与实测 SOP（~1 小时）

```bash
# 插件包放无中文路径！如 E:/projects/dsh-data-translator（junction 中文路径复发率 100%）
cd ~/.dsh/profiles/web && grep -q minimumReleaseAge pnpm-workspace.yaml || echo "minimumReleaseAge: 0" >> pnpm-workspace.yaml
npx @deepseek-ai/dsh plugin add --profile web ./packages/dsh-data-translator
# 两阶段规则：add ≠ 激活，必须重启 web
# ⚠️ add 后必做：diff bundles 快照，确认 hermes-link 未被挤掉；cat junction/package.json 验活
powershell 重启 web → 看启动日志的工具注册行 → curl /mcp/collab/health
dispatch_probe {"skill":"dft_translate"} → e2e: dispatch_task 转一份真实 pdf
```

---

## 8. Phase 4 — CI 与发布（可选）

- `ci.yml`：删 frontend job；smoke 改为 CLI 样本矩阵 e2e；新增 `node --test` job（无 python 环境时 runner 测试显式 skip）。
- 预计全量测试 657 → ~400，速度显著提升。
- 发布选项：GitHub repo / npm 包 / 仅本机 link。到时再定。

---

## 9. 风险与回滚

| 风险 | 对策 |
|---|---|
| pnpm 24h 冷却拒装 | workspace yaml `minimumReleaseAge: 0` |
| 中文路径 junction 写坏 | 包放纯 ASCII 路径；每次 add 后验活，坏则 `_winapi.CreateJunction` 重建 |
| bundles 被挤掉 hermes-link | add 前后 diff package.json |
| spawn 到错误 Python | 探测链 + 版本断言 + 失败即报 kind=internal 带诊断信息 |
| 大文件超时 | JS 侧杀树 + 明确 timeout 错误；上限 clamp |
| Web 版反悔 | checkout tag `v2.1.0-ci-green`（git 历史仍含全部前端代码） |

## 10. 验收标准

1. `pip install -e .` 后 `python -m dft_core translate samples/demo.docx --format markdown` 输出合法协议 JSON。
2. dsh web 带 bundle 启动无 ERR；`dispatch_probe` 认得 `dft_translate/dft_formats`。
3. 端到端：dispatch 一个真实 PDF 转换任务，agent 拿到结构化内容并正确处理 `enhance` 提示。
4. slim main：pytest/ruff/mypy 三绿；仓库工作区不含 frontend/api/main.py。
5. `git checkout v2.1.0-ci-green` 可完整回到 Web 版。
