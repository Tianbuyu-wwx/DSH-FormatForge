# v1.0 Protocol Freeze — FormatForge 协议快照

> **生效日期**：v1.0.0 stable（预计 2026-09）
> **冻结语义**：v1.0 起本目录快照锁版本。新增能力只能以**新增字段 / 新增文件**形式加入；已有字段语义、类型、值范围冻结。
> **兼容策略**：v1.x 内允许向后兼容新增字段；移除/改语义需走 v2.0 + 弃用周期。

## 目录

```
protocol/v1/
├── version.schema.json          # version 子命令响应
├── formats.schema.json          # formats 子命令响应（含 details[].capabilities v0.14 新增）
├── translate.schema.json        # translate 子命令成功响应
├── translate-error.schema.json   # translate 子命令失败响应
├── batch.schema.json            # batch 子命令响应
├── diff.schema.json             # diff 子命令响应
└── error-codes.json             # 错误码冻结清单 + 退出码 + 消息模板
```

## 协议通用规则

1. **协议 JSON 单行输出**（`sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")`）
2. **成功响应**：`{ok: true, code: 200, data: {...}}`
3. **失败响应**：`{ok: false, code: <int>, error: {kind: <code>, message: <str>}}`（code = 4000 + ErrorCode.exit_code）
4. **错误码枚举**：见 `error-codes.json`——9 个稳定值，新增只能 append
5. **退出码**：见 `error-codes.json.exit_codes`——CLI 进程退出码

## 输出格式（format 字段）

| 值 | 含义 | 稳定性 |
|---|---|---|
| `json` | 结构化 JSON | 稳定 |
| `markdown` | 语义保真 Markdown | 稳定 |
| `html` | HTML 渲染 | 稳定 |
| `text` | 纯文本 | 稳定 |

## 转换策略（conversion_type 字段）

| 值 | 含义 | 稳定性 |
|---|---|---|
| `auto` | 自动选择最佳策略 | 稳定 |
| `text` | 纯文本提取 | 稳定 |
| `structured` | JSON/Markdown 结构化 | 稳定 |
| `table` | 表格抽取 | 稳定 |
| `image_desc` | 图片描述（需会话模型补充） | 稳定 |
| `ocr` | OCR 文字识别 | 稳定 |

## format 分类（categories 字段）

`document / data / email / image / archive / audio` 六个分类稳定。

## capabilities 字段（v0.14.0 新增）

`formats.details[].capabilities` 是机器可读的能力列表，让会话模型按能力选择 format。
已识别的 capability 值：

- `furniture_strip` — header/footer 剔除
- `two_column` — 双栏阅读序重排
- `ocr` — OCR 引擎调用
- `table` — 表格抽取
- `multi_sheet` — 多 sheet 处理
- `schema_inference` — 列类型推断（CSV/XLSX）
- `animation_order` — PPTX 动画时序
- `speaker_notes` — PPTX 讲者备注
- `chapter_split` — EPUB 章节拆分
- `revision_track` — DOCX w:ins/w:del 修订追踪
- `metadata_only` — 仅元数据（音频）
- `encoding_override` — TXT 编码覆写
- `heading_hierarchy` — 字号/加粗 → h1-h4
- `toc_anchor` — 目录行 → 锚点

新增 capability 只能 append，已有的不能改语义。

## 环境变量冻结

| 变量 | 默认 | 说明 | 稳定性 |
|---|---|---|---|
| `FF_PYTHON` | (auto-detect) | Python 解释器路径 | 稳定 |
| `FF_HOME` | `~/.dsh/formatforge` | FF 主目录（inbox 等） | 稳定 |
| `FF_TIMEOUT_S` | 120 | 单次转换超时（秒） | 稳定 |
| `FF_MAX_BYTES` | 100MB | 单文件最大字节 | 稳定 |
| `FF_INBOX_NOTIFY` | true | inbox 完成后通知会话 | 稳定 |
| `FF_INBOX_TTL_DAYS` | 7 | inbox 清理 TTL（天） | 稳定 |
| `FF_INBOX_MAX_MB` | 500 | inbox 容量上限 | 稳定 |
| `FF_REPO_ROOT` | (cwd-detect) | 仓库根路径 | 稳定 |

## enhance 协议（v0.13.0 起稳定）

当 `data.enhance.needed = true` 时，会话模型按 `enhance.hint` 自助增强（不用调外部 API）。

`reason` 枚举（v0.14.0 起冻结）：

- `image_only` — 多数页无文字层（扫描件）
- `ocr_low_confidence` — OCR 文字层置信度 < 0.6（v0.14.0 新增）
- `low_confidence` — 转换置信度过低
- `table_sparse` — 检测到表格但未抽取到结构化单元格

## inbox 协议

- **入口**：`$FF_HOME/inbox/` 拖入文件 → 自动转换 → 产出 `<stem>.ff.json` + `<stem>.ff.md`
- **失败产物**：`<stem>.ff.error.txt` 含 `[kind] message`
- **预览机制**：`data.details[]` 在 formats 工具中暴露 capability
- **历史追溯**：retention 清理前写 `.ff.retired.log`（v0.14.0 起）

## 兼容性承诺

- v1.x 内：允许向后兼容的新增字段（不改既有字段类型/语义）
- v1 → v2.0：移除/改既有字段需走弃用周期（至少 1 个 minor 版本）
- 安全破坏性变更（如权限模型变化）可立即生效，需 CHANGELOG 注明

## 如何验证

```bash
# 验证 CLI 输出符合 snapshot
python -m formatforge version | python tools/_gen_proto_v1.py --validate

# 验证 npm bundle schema 一致
node packages/dsh-formatforge/test-manifest.mjs
```

## 更新协议

修改协议需要：
1. 在 `tools/_gen_proto_v1.py` 里更新 shape 定义
2. 在 `CHANGELOG.md` 记录变更
3. 更新本 README
4. CI 增加 schema 一致性检查（v1.0 后）
