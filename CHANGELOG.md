# 更新日志 (Changelog)

本项目的所有重要变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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