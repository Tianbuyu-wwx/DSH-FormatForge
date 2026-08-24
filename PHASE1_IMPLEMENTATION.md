# 第一阶段实施记录与后续开发方案

更新时间：2026-07-22  
当前状态：第一阶段代码已落地，正在等待质量门禁和全量回归收口；尚未形成 2.1.1 发布提交。

## 0. 当前项目进度总览

从功能实现、测试结果和生产部署情况综合判断，项目已经是“功能型 Beta”，还不是可以直接对外发布的生产版本。以下完成度是工程评估值，用于排定工作优先级，不代表代码覆盖率百分比。

| 领域 | 当前进度 | 现状 |
|---|---:|---|
| 转换内核与 Pipeline | 约 85% | 多阶段 Pipeline、缓存、策略决策、OCR、质量报告、模板和 SSE 已存在 |
| 文件格式解析 | 约 80% | 已注册 21 类解析器，覆盖文档、表格、图片、数据、邮件、压缩包、字幕、音频等；部分解析器缺少独立测试 |
| v2 API | 约 80% | 转换、URL/文本输入、历史、导出、质量、Webhook、指标等接口已具备；认证边界刚完成第一阶段加固 |
| Web 前端 | 开发模式约 80% | Lit + TypeScript + Vite，上传、URL、文本、批量、历史、对比和 i18n 已实现 |
| 前端生产部署 | 约 65% | dist 静态托管和背景资源已修复，但仍需要在干净环境和 CI 中固化部署流程 |
| 测试体系 | 后端基础较强，前端基础覆盖 | 原基线为 640 个后端测试通过；本阶段新增鉴权/SSRF 和前端 API Key 测试，但全量回归仍需隔离临时目录和限流状态 |
| 工程质量 | 约 70% | Ruff check、Ruff format 已通过；mypy 仍有 65 个错误 |
| 生产运维 | 约 45% | 尚无完整 Docker/依赖锁定/多 worker 共享状态方案 |

### 当前可用性判断

- 本地开发：可用，核心转换和前端开发模式已具备。
- 受控内网试用：基本可行，但应设置 API Key，并先完成全量测试收口。
- 公开生产服务：暂不建议，原因是 mypy、全量 pytest、Provider 能力一致性、DNS rebinding 防护和部署自动化仍未完成。
- 当前版本定位：第一阶段候选工作区，不应标记为已经发布的 `2.1.1`。

## 1. 本阶段目标

第一阶段对应发布前止血和工程质量收口，范围包括：

- 敏感读取接口鉴权与 Webhook SSRF 防护；
- 前端 API Key 与生产静态资源链路；
- Ruff、格式检查、pre-commit、`.gitignore` 和配置模板修复；
- 为后续 2.1.1 发布准备可重复验证条件。

## 2. 已实施修改

### 2.1 API 与安全

涉及文件：[api/v2.py](api/v2.py)、[core/auth.py](core/auth.py)、[core/webhook_manager.py](core/webhook_manager.py)。

- v2 的历史列表、历史详情、历史统计、导出、质量报告、Webhook 状态和 Webhook 统计接口增加 `verify_api_key`。
- `health`、`templates`、`metrics` 等公共运维/元数据接口继续公开。
- Webhook 注册时调用现有 URL 安全校验。
- Webhook 每次实际重试投递前再次校验目标地址，避免注册后地址变化绕过 SSRF 检查。
- 保留现有 Bearer Token 和 HMAC 时序安全比较逻辑。
- 新增鉴权、危险地址和重试阶段重新校验的回归测试。

当前仍有一个窄风险：现有 `validate_url_domain` 尚未绑定 DNS 解析结果，理论上仍存在 DNS rebinding/TOCTOU 窗口，列入下一阶段安全任务。

### 2.2 前端与生产静态资源

涉及文件：[frontend/src/utils/api.ts](frontend/src/utils/api.ts)、[frontend/src/main.ts](frontend/src/main.ts)、[frontend/src/components/app-background.ts](frontend/src/components/app-background.ts)、[main.py](main.py)。

- 增加当前标签页级别的 API Key 配置，自动为 GET/POST/DELETE 请求添加 `Authorization: Bearer ...`。
- API Key 使用密码输入，不显示原文，不写入 URL、日志或构建产物，并拒绝 CRLF 请求头注入。
- 背景 MP4 改用 `import.meta.url` 纳入 Vite 依赖图，生产构建会生成带 hash 的资源文件。
- FastAPI 仅在 `frontend/dist/index.html` 存在时挂载构建产物。
- 未构建时不再暴露 TypeScript 源码，并输出明确的启动/回退提示。
- 新增 5 项前端 API Key 测试。

### 2.3 工具链、配置和可追踪性

涉及文件：[pyproject.toml](pyproject.toml)、[.pre-commit-config.yaml](.pre-commit-config.yaml)、[.gitignore](.gitignore)、[.env.example](.env.example) 及若干 Python 源文件。

- 修复生产源码中的 Ruff 问题，并将公共 API 的 camelCase 字段作为兼容契约处理。
- 修复 5 个 Python 源文件的格式问题。
- pre-commit 不再硬编码失效的 `E:/.venv-common/...` 路径，改为使用当前激活环境的 `python`。
- 不再忽略整个 `test/` 目录；同时 Ruff 明确排除测试目录，避免测试脚本风格问题阻塞生产源码门禁。
- `.env.example` 改用可被配置解析器直接识别的 CORS JSON 数组，修正缓存配置名并补充请求体限制、限流开关和磁盘缓存开关。
- 原先被 `.gitignore` 隐藏的一批测试文件现在会显示为未跟踪文件；这些文件在本阶段前已经存在，未删除，需后续由项目维护者决定是否纳入版本库。

## 3. 当前验证结果

所有 Python 验证均通过项目内部 `.venv\Scripts\python.exe` 执行。该 venv 原先引用了另一台机器的 Python 路径，已原地修正 `pyvenv.cfg`，未重建依赖环境。

| 检查项 | 结果 | 说明 |
|---|---|---|
| Ruff check | 通过 | `All checks passed!` |
| Ruff format | 通过 | 56 个文件已格式化 |
| 安全定向测试 | 通过 | 24 passed |
| 前端 TypeScript | 通过 | `tsc --noEmit` |
| 前端 Vitest | 通过 | 2 个文件、15 项测试 |
| Vite production build | 通过 | JS 约 81.78 kB，MP4 资源约 10.5 MB |
| 静态资源 smoke | 通过 | `index.html`、hash JS、hash MP4 均返回 200 |
| mypy | 未通过 | 当前仍有 65 个类型错误，分布在 core、parsers、api |
| 后端全量 pytest | 尚未收口 | 当前运行得到 503 passed、8 failed、146 errors；主要包含临时目录 ACL 问题和测试进程共享限流状态导致的 429 |

全量 pytest 的失败不能直接判定为业务回归：大量错误发生在 fixture 建立临时目录时，另有新增鉴权测试使 TestClient 共享的限流计数超过默认阈值。但在发布前必须通过测试 fixture 隔离、限流状态重置或测试专用配置把这两个问题彻底消除。

## 4. 当前发布判断

当前应标记为“第一阶段候选工作区”，不能标记为已经发布的 `2.1.1`：

- 安全和生产前端链路已经实现并有定向验证；
- Ruff 和格式门禁已经通过；
- mypy 尚未清零；
- 全量 pytest 尚未重新达到全绿；
- 版本号、README 和 CHANGELOG 尚未统一更新为 2.1.1；
- 尚未创建提交或发布标签。

## 5. 后续开发方案

### 5.1 P0：完成 2.1.1 质量收口

1. 按错误类别清零 65 个 mypy 错误：优先修复 Optional、返回值类型、解析器容器类型和 AI client 类型边界，不通过关闭检查掩盖问题。
2. 为测试设置项目内可写的临时目录，避免使用受限的系统临时目录。
3. 将限流中间件的计数隔离到测试 fixture，或在测试环境显式关闭限流，避免跨测试产生 429。
4. 重新运行内部 venv 下的完整 pytest、Ruff、format 和 mypy。
5. 更新 `__version__.py`、`pyproject.toml`、前端包版本、README badge 和 CHANGELOG，形成 2.1.1 发布记录。

验收标准：Python 3.10–3.12 CI 中 pytest、Ruff、format、mypy 全部通过；前端 tsc、Vitest、Vite build 全部通过。

### 5.2 P1：生产安全闭环

1. 在 `DEBUG=false` 且监听 `0.0.0.0` 时，API Key 为空应拒绝启动或明确阻止生产运行。
2. 为 Webhook 和 URL 输入增加 DNS 解析结果绑定，降低 rebinding/TOCTOU 风险。
3. 为历史、导出和质量数据增加数据保留、清理和访问范围策略。
4. 将生产部署、前端 API Key 注入方式和密钥轮换方式写入部署文档。

### 5.3 P1：功能一致性与覆盖率

1. 补齐 Anthropic、Qwen、DeepSeek 等 Provider 的配置字段、客户端实现和 mock contract tests；不能运行的 Provider 不应继续宣称“已支持”。
2. 为 Audio、DOCX、XLSX、LaTeX、SQL、Subtitle 解析器补充独立测试和 fixtures。
3. 将当前前端顺序批量循环升级为服务端批量任务：有限并发、进度、取消、重试和失败明细。
4. 对 API schema、camelCase 外部契约和前端类型增加契约测试。

### 5.4 P2：部署与架构升级

1. 增加 Dockerfile、生产启动命令、健康检查和干净 checkout 的一键启动说明。
2. 增加 Python 依赖锁定文件，并让 CI 使用锁定依赖。
3. 多 worker 部署时，将进程内缓存和指标迁移到共享存储或明确单 worker 约束。
4. 为 v1 API 增加 Sunset 日期，完成迁移后在 3.0 再删除，避免小版本破坏兼容性。
5. 替换或可选加载当前视频背景，降低素材授权和部署体积风险。

## 6. 推荐验证命令

```powershell
# 后端：只使用项目内部 venv
.venv\Scripts\python.exe -m pytest test --tb=short -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m mypy core api parsers --ignore-missing-imports

# 前端：在 frontend 目录执行
npm ci
npm run build
npm test -- --reporter=verbose
npx tsc --noEmit
```
