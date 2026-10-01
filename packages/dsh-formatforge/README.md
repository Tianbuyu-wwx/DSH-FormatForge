# @tianbuyu-wwx/dsh-formatforge

**把任意文件拖进 DeepSeek Harness，立刻变成 AI 能读懂的数据。**

这是 [DSH-FormatForge](https://github.com/Tianbuyu-wwx/DSH-FormatForge) 的 **DSH 插件壳**：
一个薄 bundle，把本地 Python 内核（`python -m formatforge`）包装成宿主原生工具。
支持 PDF、DOCX、XLSX、PPTX、EML、EPUB、TOML 等 **30+ 种格式**。

> ⚠️ **本包不含解析器。** 它是壳，还需要一份可运行的 Python 内核，见下方「安装」。

## 兼容性

| | |
|---|---|
| DSH | `>=0.2.0-rc.1 <0.3.0-0`（`peerDependencies` 会被宿主 `evaluatePluginCompatibility()` 检查） |
| Node | `>=22.13.0` |
| Python | `>=3.10`（内核需要） |
| 协议 | `protocol/v1`（工具签名与返回 JSON 向后兼容） |

## 安装

```bash
# 1) 装插件壳
dsh plugin --profile desktop add @tianbuyu-wwx/dsh-formatforge

# 2) 准备 Python 内核（本包不自带）
git clone https://github.com/Tianbuyu-wwx/DSH-FormatForge.git
cd DSH-FormatForge && pip install -e .
setx FF_REPO_ROOT "D:\DSH-FormatForge"

# 3) 重启 DeepSeek Harness —— 0.2.0 起 add ≠ 激活
```

启动日志出现这一行即生效：

```
[dsh-formatforge v2.0.0] tools registered: ff_translate, ff_formats, ff_result, ff_batch, ff_diff
```

## 工具

| 工具 | 用途 |
|---|---|
| `ff_translate` | 转换：`path` / `paths`（逗号分隔，支持 `*` `**`）/ `text` 三选一；`format` json·markdown·html·text；`max_chars`/`offset` 分页；`quality` 附质量报告 |
| `ff_formats` | 列出支持的输入格式矩阵（可按 category 过滤） |
| `ff_result` | 取回收件箱产物（`list` / `id` / `ids` 批量） |
| `ff_batch` | 批量锻造目录或 glob（并发 workers、失败不中断） |
| `ff_diff` | 两份文件 unified diff（合同/法规/版本对照） |

## 使用方式

- **拖拽**：把**非图片文件**拖进窗口 → 自动上传锻造 → 收件箱产出 `<名字>.ff.md`（可读）+ `<名字>.ff.json`（完整协议），并向会话注入一条轻量通知。**图片与文件夹一律放行**：图片走宿主原生附件通道，文件夹由宿主自己变成 `@路径` 引用——插件不接管（v2.0.2 起，拖文件夹不再卡死）。拖动期间右上角常驻 **× 退出拖拽**，遮罩右上角也有 ×，按 **Esc** 等效：点一下就能清掉卡住的遮罩并复位宿主状态，不必刷新页面；× / Esc 之后**这一段**拖拽整体交回宿主（松手不会再被接管），下一次拖拽照常锻造。
- **路径**：在对话里给本地路径，agent 会先 `ff_translate` 再回答。
- **CLI**：`python -m formatforge translate doc.pdf --format markdown`（stdout 单行协议 JSON，退出码 0/2/3/4）。

## enhance 协议

插件**不带任何 AI 客户端**。纯规则转换不足以产出高质量结果时返回：

```jsonc
"enhance": { "needed": true, "reason": "image_only", "hint": "4/4 页无文字层（疑似扫描件）…" }
```

此时由**当前会话模型**按 hint 自行完成增强，零密钥配置。

## 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `FF_REPO_ROOT` | 自动探测 | 含 `formatforge/ core/ parsers/` 的仓库根 |
| `FF_PYTHON` | 探测链兜底 PATH | 指定解释器（探测顺序 `FF_PYTHON` → `<repo>/.venv-fg` → PATH） |
| `FF_MAX_BYTES` | 104857600 | 单文件上限（100MB） |
| `FF_TIMEOUT_S` | 120 | 单次转换超时（秒） |
| `FF_INBOX_NOTIFY` | true | 锻造完成后是否向会话注入轻量通知 |
| `FF_HOME` | `$DSH_HOME/formatforge` → `~/.dsh/formatforge` | 收件箱根目录 |
| `OCR_ENABLED` | true | 启用本地 OCR（tesseract/paddleocr/easyocr 任一） |

## 链接

- 仓库 / 完整文档：<https://github.com/Tianbuyu-wwx/DSH-FormatForge>
- 适配说明（DSH 0.2.0-rc.2）：[ADAPTATION_PLAN.md](https://github.com/Tianbuyu-wwx/DSH-FormatForge/blob/main/ADAPTATION_PLAN.md)
- 更新日志：<https://github.com/Tianbuyu-wwx/DSH-FormatForge/blob/main/CHANGELOG.md>

## License

MIT
