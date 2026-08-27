# ROADMAP.md — DSH-FormatForge 后续开发计划

> 起草：2026-08-26 · 基线：v0.7.0（EVOLUTION_PLAN 四批全部交付）· R2 已完成：v0.8.0（2026-08-27）
> 定位延续：dsh 插件 · 「文件 → AI 可读数据」锻造层 · 无内置 AI 客户端 · 模型增强永远属于会话模型

---

## 0. 现状快照（v0.8.0）

| 维度 | 状态 |
|---|---|
| 输入格式 | 34 种；输出 json/markdown/html/text |
| 入口通道 | 网页拖拽（upload→inbox→watcher）/ 对话工具 ×3（ff_translate/ff_formats/ff_result）/ CLI（translate/formats/version/batch） |
| 质量体系 | 5 维评分 + grade + enhance 三触发 + actions（retry_with 可自愈）；R2.1 起 OCR 管线贯通（RapidOCR 真置信度） |
| PDF 深度 | pages 选择 / furniture 剔除 / 双栏阅读序 / **R2.3 标题层级+列表嵌套+目录锚点** / **R2.2 表格语义（合并/跨页/对齐）** |
| 工程面 | 509 tests · CI 7/7 · mypy 47 文件 0 错 · golden fixture 机制 · dependabot 三生态 · verify-install 自检 |
| 分发 | npm `@tianbuyu-wwx/dsh-formatforge`（v0.8.0） · awesome-list 已收录 · storefront 截图已声明 |

---

## 1. R1 · 收录落地与生态反馈（被动响应为主，~随缘）

**目标**：PR #3113 合并后，把「上榜」转化为可用性反馈与第一批真实用户。

| 项 | 内容 | 触发/工作量 |
|---|---|---|
| R1.1 合并跟进 ✅ | 已合并（2026-08-26）；后续仅剩维护者意见响应 | 随缘 · <1h/轮 |
| R1.2 README 截图 ✅ | 已完成（v0.7.1）：assets/ 三张 dsh web 实拍（拖拽 toast / 收件箱 / 通知）+ 按新约定在包内 screenshots.json 声明 + README 嵌图 | — |
| R1.3 issue 模板 ✅ | 已完成（v0.7.1）：bug report 强制附 verify-install 输出栏 + feature request | — |
| R1.4 首批用户支持 | 观察安装类 issue → 反哺 verify-install 的修法提示库 | 持续 |

**验收**：上榜 + storefront 有截图 + issue 模板就位。

## 2. R2 · 解析质量纵深（✅ 已完成 → v0.8.0，2026-08-27）

**目标**：把「能转」推进到「转得准」，聚焦真实使用中失败率最高的场景。

| 项 | 内容 | 状态 |
|---|---|---|
| R2.1 扫描件 OCR 管线强化 ✅ | OCR 引擎实际接线（原 pipeline 断线）；RapidOCR 后端（真实逐行置信度）；调色板 PNG 自愈；文字层合并去重 | v0.8.0 |
| R2.2 表格语义还原 ✅ | 跨页表格续接合并；数值列右对齐；None=合并覆盖 vs ''=真空单元格语义区分 | v0.8.0 |
| R2.3 长文档结构保真 ✅ | 字号/加粗 → h1-h4；x0 几何聚类 → 列表嵌套；目录页 → 锚点；OCR 行不误判 | v0.8.0 |

**验收结果**：golden 语料 enhance 触发率 20% → 0%（目标 ≥30% 下降，实际 100%）；golden fixture 机制随批引入（16 项新测试）。

## 3. R3 · Agent 协作面增强（~2 天）

**目标**：让会话模型更省力地用好 FormatForge——减少往返、提高一次成功率。

| 项 | 内容 | 工作量 |
|---|---|---|
| R3.1 ff_translate 智能默认 | 按检测格式自动带 quality（低置信格式自动开）；返回头 200 字预览帮模型先判断再决定翻页 | ~半天 |
| R3.2 ff_result 批量取回 | `ids` 数组参数一次取多产物（各带 max_chars）；inbox 通知直接附 id | ~半天 |
| R3.3 SKILL.md 自愈闭环实测 | 构造劣化样本集，验证「actions→retry_with→重调」链路在真实 dsh 会话中的成功率，按结果修提示词 | ~1 天 |
| R3.4 工具描述 token 瘦身 | 三工具 description 精简（当前 ff_translate 描述较长），省会话上下文 | ~2h |

**验收**：劣化样本集一次成功率 ≥80%；三工具 schema 体积减 30%。

## 4. R4 · 观望池升级评估（数据驱动，不预设）

按 EVOLUTION_PLAN §5 观望池逐项评估，**有信号才立项**：

| 项 | 升级信号 | 预估 |
|---|---|---|
| N2 URL 抓取 | ≥3 个用户明确要网页转 markdown（需重新过安全评审） | 1-2 天 |
| N4 截图/剪贴板直投 | Windows 截图取字需求 ≥2 次 | 1 天 |
| E6 本地遥测 | 「哪个格式支持最好」类问题出现 | 半天 |
| Office/云盘连接器 | OneDrive/GDrive 直转需求 | 2 天+ |
| PPTX 深度解析（讲者备注/动画顺序） | 用户拿 PPT 做知识库场景出现 | 1 天 |
| 多语言界面 | 英文用户反馈看不懂日志 | 半天 |

## 5. R5 · 工程持续健康（低频巡检，不占开发窗口）

| 项 | 节奏 |
|---|---|
| dependabot PR 处理 | 月度（已配置，合并前跑全门禁） |
| dsh 宿主升级回归 | 每次宿主发版跑 `scripts/verify-install.py` + dispatch 探针（~10 分钟） |
| golden fixture 库扩充 | 每修一个真实 bug 沉淀一个 fixture（持续） |
| 性能基线 | batch 50 文件耗时记录，防解析层退化（每批测一次） |

---

## 排期建议

| 阶段 | 内容 | 前置 |
|---|---|---|
| 即刻 | R1.1 合并跟进（PR #3113） | 维护者 review |
| 合并后一周 | R1.2 + R1.3 + R3.4（轻量快赢） | 上榜 |
| 首个开发窗口 | R2 解析质量纵深（R2.1 → R2.3 → R2.2） | — |
| 第二窗口 | R3 协作面增强（R3.1 → R3.3 → R3.2） | R2 的 fixture 库 |
| 持续 | R4 观望池评估 + R5 巡检 | 用户信号 |

## Non-goals（不变，延续 EVOLUTION_PLAN §7）

- ❌ 云端 AI 增强 · ❌ Web 服务复活 · ❌ GUI 桌面端 · ❌ 出站网络（N2 除非重新拍板）

## 版本号规划

- R1/R3/R5 → v0.7.x patch/minor
- R2 解析质量纵深 → **v0.8.0**（golden fixture 机制随批引入）
- R3 全落地 → **v0.9.0**
- 若 R2+R3 稳定且生态反馈良好 → 评估 **1.0.0**（API 承诺：协议 JSON 形状冻结 + 弃用周期）
