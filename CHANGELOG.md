# 更新日志 (Changelog)

本项目的所有重要变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [3.0.0] - 2026-10-02 — 收件箱升级为「库」+ 宿主右侧栏面板

> 用户拍板：**只做面板**（不做整窗口页/自托管页）· 持久化分层由实现方定 · **从零写**（不复活冻结前端）· **一次性大版本** · 先自检、等审查再发。
> 计划与取舍依据：[UI_DB_PLAN.md](UI_DB_PLAN.md)

### 新增

**① 收件箱索引库（SQLite，`<DSH_HOME>/formatforge/index.db`）** —— ROADMAP R6.2 的落地：

| 能力 | 实现 |
|---|---|
| 元数据索引 | `artifacts` 表 + schema 迁移（`schema_migrations`，幂等；失败自动重建） |
| 全文检索 | FTS5 **trigram**（中文子串可用）+ **短词 LIKE 兜底**（trigram 只索引 3 字序列，「付款」这类 2 字查询必须走 LIKE） |
| 内容去重 | `source_sha256`（≤8MB 全文哈希 / 更大取首 1MB+尺寸标记），拖入命中即秒回 |
| 会话溯源 | `session_id` 列（预留）+ `events` 事件表 |
| 回填 | `python -m formatforge inbox reindex`：扫 `.ff.json` 幂等回填，**可随时删库重建** |
| 保留对齐 | `inbox prune`：磁盘上已消失的产物标 `retired_at`（与 watcher 的 TTL/LRU 对齐） |
| 运维 | `inbox stats / vacuum / backup(VACUUM INTO) / find / delete(软删)` |

新 CLI：`python -m formatforge inbox {init,index,query,stats,reindex,delete,prune,digest,find,vacuum,backup,prefs}`
（沿用「stdout 唯一出口」单行协议 JSON）。

**② 宿主右侧栏面板 + 侧栏导航入口（从零手写，零构建、零 npm 依赖）**：

- **侧栏导航条目**（用户指定位置）：注册 `sidebar.panellist`（图标 + label，`order=20`）→ 落在
  「插件 / 自动化任务」下方的导航列表里；点击由宿主 `selectPanel(id)` 切到 `main` 插槽同 key 的**主区页面**
  （与官方 schedule 插件同一套公开写法）。
- **右侧栏页签**（保留）：`sidebar.right.pane.tab` + `.title`（keyed 插槽）+ 类型注册
  `ctx.sidebarRightTabs.register({kind:'formatforge-inbox', priority:'extension', guide:[…]})` + 侧栏底部按钮。
- 同一个面板组件两种落点：主区页面（`variant=page`，宽屏居中）与右栏页签（`variant=pane`，窄栏自适应）。
- 功能：搜索（中文子串）、产物列表（来源/解析器/体积/时间/失败标记）、详情预览（正文 + 元数据）、
  复制路径 / 重新锻造（删产物 + 通知 watcher 重跑）/ 从列表移除（软删）、**每页条数偏好**。
- 技术：宿主 Module Loader lane 的 `require('react')` + `React.createElement`；图标是内联 SVG（`currentColor`，跟随主题）。
- **降级**：拿不到 react / 没有 `sidebarRightTabs` / 插槽未声明（register 抛错）/ `slots` 注入失败
  → 只记日志，**绝不影响拖拽模块与工具**（有专门的降级测试）。
- **接口未就绪提示**：宿主若还跑着旧的 Node 半（API 404），面板直接提示"完全退出 DSH 后重开"，而不是干瞪眼。

**③ 只读 API + SSE（`/formatforge/api/*`）**：`health`·`stats`·`artifacts`(列表/检索)·`artifacts/:id`(元数据)·`artifacts/:id/content`(分页正文)·
`artifacts/:id/retry`·`DELETE artifacts/:id`·`events`(SSE)·`settings`(GET/PUT)。

**④ `ff_result` 能力升级**：新增 `search`（全文检索）、`stats`（库状态）、`limit`（列表条数）三个参数；
列表默认取最新 N 条（缓解 ROADMAP:56「list 把全部条目塞进模型上下文」）。

### 修复

**🔴 面板首屏 401「需要 token 或同源访问」——桌面端的 fetch 不带 `Sec-Fetch-Site` / `Origin`。**
面板跑在 DSH 桌面端里，它的 fetch 既不发送 `Sec-Fetch-Site: same-origin`，也没有 loopback `Origin`，
而原策略只认"同源浏览器请求" → 所有接口 401（`/formatforge/api/artifacts?limit=50` 首屏即挂）。
重定策略（威胁模型不变，只是把判定建在真正可判别的信号上）：
- Host 必须 loopback（挡局域网直连 / DNS rebinding）；
- token 正确 → 放行；**token 错误 → 立刻 401，不降级**；
- 同源页面（`Sec-Fetch-Site: same-origin` 或 loopback `Origin`）→ 放行；
- **无浏览器信号**（两个头都没有）或 opaque（`site=none` / `origin=null`）视为桌面端/主进程代理/脚本 → **读放行**；
- **写操作**（retry / delete / `PUT settings`）额外要求 `x-ff-client: panel`：跨站网页带自定义头会触发
  CORS 预检，而我们从不回 `Access-Control-Allow-*`，所以恶意页面发不出写请求（CSRF 挡住）；
- 带跨站信号（`cross-site`/`same-site` + 非 loopback Origin）的网页请求 → 401（浏览器另有 CORS 兜底读取）。
401 文案现在带上观察到的信号（`site=… origin=… client=…`），下次线上失败一眼可定位。
顺带修：token 文件改为**注册路由时生成**（原先挪进"带 token 才校验"的分支会让文件永不生成，脚本永远拿不到凭证）。

**🔴 大产物按 id 取回全链路 404 —— id 反查只扫产物前 64KB。**
`http/api.mjs::findArtifact` 用 `readFileSync(...).slice(0, 64*1024)` 后在头部找
`"result_id": "…"`，但 payload 的顺序是 `content` 在前、`meta.result_id` 在后，watcher 又以
`JSON.stringify(res, null, 2)` 落盘 —— **正文超过 ~64K 字符的产物，id 就落在窗口之外**：
详情、正文预览、重转、删除全部 404（接口本身正常，`/artifacts/<stem>` 还能取到，所以极难定位）。
实测：正文 120,034 字符 → `/artifacts/<id>` = 404 / `code 4002`；小产物 200。
修复：`findArtifact` 改成三层 —— ① `services/inbox-db.mjs::findArtifactById()` 查库拿 `json_path`
（O(1)，与正文大小无关，并支持 id 前缀）；② 文件名精确/前缀；③ 全文扫描兜底（正则容忍
`"k":"v"` 无空格写法，前缀语义保留，单文件 >64MB 跳过）——回滚开关 `FF_DB=off` 时同样可用。
`tools/result.mjs`（`ff_result`）的同一处 64KB 头部窗口一并修掉；顺带把大文件（>2MB）的元数据兜底
从「整文件读入再切头部 64KB」改成 **fd 分段读首尾窗口**（`meta` 排在 `content` 之后 → 尾部窗口才是关键），
既修掉 `parser='?'` 又不再把上百 MB 产物整个读进内存。

**🟡 IPv6 loopback Host 被误判。** `isLoopbackHostHeader` 先 `split(':')` 再去方括号，
`'[::1]:19387'.split(':')[0]` 是 `'['` → `[::1]` / `::1` 一律判成非 loopback（与 `isLoopbackOrigin` 语义不一致）。
现在按「方括号优先、单个冒号才算端口」解析，三种写法都放行，外域仍 403。

**🔴 单条产物接口全部 404 —— prefix 路由带尾斜杠，永远不会被命中。**
宿主 `match()` 的 prefix 规则是 `pathname === prefix || pathname.startsWith(prefix + '/')`
（`dsh-host-webserver/lib/index.js`），而 `/formatforge/api/artifacts/` 这种**带尾斜杠**的前缀
只有 `/artifacts//<id>` 能命中；真实的 `/artifacts/<id>`、`/<id>/content`、`/<id>/retry`、DELETE
全部落到 SPA fallback，变成 **404 且 body 为空**（不是我们自己的 JSON 404）。
现象：面板列表能出来（exact 路由正常），但**点任意一行都不行**。
修复：prefix 注册路径改成不带尾斜杠的 `/formatforge/api/artifacts`；基路径被 prefix 表命中时按列表语义处理。
**测试保真度修正（第二次同类教训）**：`test-api.mjs` 原先直接按 `(kind, path)` 找路由调 handler，
从不经过宿主的匹配规则；现在新增 `hostMatch()` 复刻宿主 `match()` 语义（exact → 最长 prefix），
`call()` 在调用前先断言「这个 URL 真的会路由到这条路由」，并新增 `1b` 节钉死 prefix 语义
（子路径命中、`/artifactsX` 不抢、尾斜杠禁令）；`test-plugin-boot.mjs` 同样加了尾斜杠不变量与匹配仿真。

**🔴 列表行字段对不上 —— 库列名 vs 面板读的客户端形状。**
SQLite 行是 `source_name` / `source_bytes` / `created_at`（unix 秒），而面板渲染读的是
`source` / `size_bytes` / `forged_at` → **列表会把产物 id 当文件名显示，大小与时间为空**
（`bytesLabel(undefined)`、`timeLabel(undefined)`），看起来就像"面板坏了"，但接口全是 200。
修复分三层：`services/inbox-db.mjs` 新增 `toClientRow()` 在 sqlite 与 CLI 两条路径上统一归一
（`source_name→source`、`source_bytes→size_bytes`、unix 秒→ISO `forged_at`，原始列名无损保留）；
面板 `rowOf()` 再做一层兜底（库列名/毫秒时间戳/ISO 都能渲染）；`bytesLabel`/`timeLabel` 对空值与秒级时间戳
健壮。**测试保真度修正（第三次同类教训）**：`test-api.mjs` 现在用**真实库行**断言列表契约
（`source` 等于真实文件名、`size_bytes` 是数字、`forged_at` 可被 `Date.parse`）；
`test-client-panel.mjs` 新增 `2c` 节，用库列名的退化行验证面板仍显示文件名与 `4KB`。

**🔴 面板全部接口 400（空 body）——宿主只以 `handler(req, res)` 调用处理器。**
`@deepseek-ai/dsh-host-webserver` 的分发是 `await route.handler(req, res)`（`lib/index.js`），
**不传第三个参数**；而 `http/api.mjs` 的包装器写成 `async (req, res, url)` 并把
`authorize(req, url)` 放在 `try` 之外 —— 线上 `url === undefined` → `TypeError: Cannot read
properties of undefined (reading 'searchParams')` 在 try 之外抛出 → 被宿主 `catch` 后
`res.writeHead(400); res.end()`，于是 `/formatforge/api/*` 全部 **400 + 空 body**；
老路由 `/formatforge/health`（`(req, res)` 签名）仍然 200，所以现象看起来像「只有面板坏了」。
修复：新增 `requestUrl(req, provided)` 从 `req.url` + Host 头自建 URL（不再依赖第三参），
鉴权与 handler 一起纳入 `try`（异常一律回 JSON 500，绝不交给宿主变 400 空 body），
`sendJson` 在头部已发出时不再二次写。
**测试保真度修正**：`test-api.mjs` 原先给 handler 传了第三个 `URL` 参数，正是这一「善意」掩盖了缺陷 ——
现在按宿主真实调用形态只传两参；`test-plugin-boot.mjs` 对全部 8 条路由（含上传/健康）做两参调用回归，
任何一条依赖第三参都会判失败。面板侧把「400 空 body」与「404」都识别为「Node 半未随本次启动加载」并提示完全退出 DSH 重开。

**🔴 `ff_result` 字段口径错配（P-1.1，实测确认）。** CLI 与 watcher 写出的是
`data.content` + `data.meta.{parser,result_id,confidence}`，而 `tools/result.mjs` 读的是
`data.convertedContent` / `data.resultId` / `data.fileInfo.*` —— **取回正文恒为空字符串、`parser` 恒为 `?`、
`confidence` 恒为 null**，而 SKILL.md 正把 `ff_result` 当作唯一产物消费入口。
实测方式：往运行中的宿主投真实文件 → 产出 `.ff.json`（键集合 `content/format/meta/…`）→ 对照读代码。
现在以实际契约为准，旧字段名仅作兜底（历史产物仍可读）；新增 `test-result-contract.mjs` 钉死口径。

**顺带修**：`runFormatForge` 在解释器解析失败时**抛异常**（会让调用方吃未捕获 rejection），
现在返回协议形状的 `{ok:false, kind:'python_missing'}`；元数据读取从「只读前 2048 字节」改为
「小文件整体解析 + 大文件 64KB 正则兜底」（长正文会把 `meta` 挤出窗口，导致列表 `parser='?'`）；
产物名不含 `result_id`，`id` 前缀匹配改为扫 64KB 头。

### 安全

**自定义路由在宿主鉴权围栏之外**（围栏只保护 `GET /` 与 `/api`；`ctx.webServer` 自身「无 TLS、无鉴权、无 origin 策略」）。
因此 `http/api.mjs` 自建两道门：**loopback Host 校验** + **同源判定**（`Sec-Fetch-Site: same-origin` 或 loopback Origin），
非浏览器访问需带 `<FF_HOME>/api-token`（首启生成，0600）。写操作同样受这两道门保护。

### 测试

| 套件 | 覆盖 |
|---|---|
| `test/unit/test_inbox_db.py`（新增 11 例） | 建库/迁移幂等、协议 JSON 回填、中文 FTS、短词 LIKE、去重键、筛选/游标、软删、reindex 幂等、backup/vacuum、`FF_DB=off` |
| `test-api.mjs`（新增） | 6 条路由注册（含重复路由防护）、**鉴权矩阵**（非 loopback Host→403 / 跨源无 token→401 / 同源→200 / token→200 / 错 token→401）、列表/检索/元数据/正文、retry/delete、偏好 GET/PUT、SSE 帧、**宿主两参调用形态回归**（`handler(req, res)`，URL 由 `req.url` 还原）、**宿主 prefix 匹配仿真**（exact→最长 prefix、尾斜杠禁令、`/artifactsX` 不抢、子路径命中） |
| `test-client-panel.mjs`（新增） | 侧栏导航条目（`sidebar.panellist` 的 id/order/label/图标）+ `main` 主区页面 + keyed 右栏插槽 + guide 入口 + zh/en 文案；假 React 渲染冒烟（搜索框/列表/详情/偏好）；**4 条降级路径**；**400 空 body / 后端错误文案 可诊断性**；**库列名行兜底渲染** |
| `test-plugin-boot.mjs`（新增） | 无宿主启动冒烟：`apply()` 不抛错、5 个工具、8 条路由（含 6 条 API）、**8 条路由逐个两参调用**（不抛错 = 线上不会 400 空 body）、prefix 尾斜杠不变量、disposer 可回收、`inject` 契约 |
| `test-host-http.mjs`（新增，84 断言） | **真实 `node:http` + 忠实复刻宿主语义的 mini-webServer**：6 条路由全走真实 HTTP；两参调用、exact→最长 prefix 匹配、未知 id 的 JSON 404（区别于宿主 fallback 的空 body 404）、鉴权矩阵、SSE 首帧、disposer/socket/定时器收尾；并含**注入突变自检**（故意把前缀写成带尾斜杠 → 必然复现线上 404，证明这套仿真真的能抓到该缺陷） |
| `test-result-contract.mjs`（新增） | `ff_result` 字段口径（P-1.1 回归点）+ 分页 + 错误码 + 列表/检索/统计 + 旧形状兜底 |
| `test-client-bundle.mjs`（扩充） | 双 effect（拖拽 + 面板）注册契约、面板失败不影响拖拽 |
| 既有套件 | `test-client-drag.mjs`(117)、`test-manifest.mjs`、`test-inbox.mjs`、`test-local.mjs`、分页一致性 全过 |

### 兼容、迁移与回滚

- **文件仍是真相源**：`.ff.md`/`.ff.json` 语义与位置不变；库只是索引，删库可重建。
- **升级**：首次启动自动建库 + 按需 `reindex`；不动任何既有文件。
- **回滚**：`FF_DB=off` 一键回到纯文件路径（list/search 自动退回文件扫描与文件名匹配），代码双路径都有测试。
- 协议仍为 **v1**（新增环境变量与新增路由，不动既有字段语义）。

### 取舍说明（与计划的偏差）

- **面板专项**：按拍板只做面板，`main` 整窗口页与 `/formatforge/ui` 自托管页**未实现**（计划里它们是 P2 的可选项）。
- **持久化分层**：UI 偏好**没有**走平台 `ctx.storageDomain`，而是与索引同库（`settings` 表）——
  该域「整域驻内存 + 没有迁移机制」，而这里已有带迁移的 SQLite；单一可写存储、单一迁移故事更简单。
  触发重新评估的条件：偏好需要与宿主设置界面联动，或需要跨 profile 共享。
- **产物命名**（R6.1.1 `<name>.<ext>.ff.json`）**未改**：它是值不是 schema，库已存真实路径与源名，
  改名不阻塞本版；当前用「同 stem 反查源文件」补齐源名（Node/Python 各一份实现，逻辑一致）。

## [2.0.2] - 2026-10-02 — 拖拽文件夹不再卡死

> 用户现场反馈：*「当拖拽文件夹时也会激活这个插件，但是会卡死，请放行文件夹并在那个拖动到的界面上加入 × 来退出防止卡死」*

### 修复

**根因：客户端拖拽分流没认出「目录」。** Chrome 把目录交给页面的就是一个
**没有 MIME、没有扩展名、0 字节的 `File`**，与空文件无法区分，于是 v0.3 的 `partition()` 把它当普通文件：
`dragenter` 时 `preventDefault()/stopPropagation()` 抢下整个拖拽并弹出全屏遮罩，松手后还去 POST 一个
0 字节幽灵文件。而宿主的 `DropOverlay`（`@deepseek-ai/dsh-client-ui-attachment`）用**它自己的
`dragDepth` 计数器**显示，且只在**它自己的** drop/dragleave/dragend 里归零 —— 终止事件一旦被我们吞掉，
计数就停在 >0，全屏遮罩挂到刷新为止（用户说的「卡死」）。顺带，宿主本来就会把拖入的文件夹变成
`@路径` 引用，接管等于把这个能力也一起弄坏了。

| 改动 | 位置 |
|---|---|
| 一次拖拽里出现**目录**即整体放行：不接管、不显示遮罩、不上传，宿主自己的目录 intake 原样运行 | `lib/client.source.js` `directoryFiles()` / `classify()` / `onDrop()` |
| 目录判定用 `DataTransferItem.webkitGetAsEntry()`（与宿主 `droppedDirectories()` 同一判据），**逐个条目**判定；该 API 无应答的条目退化为「无 MIME + 0/4096 字节」特征（**不再要求"无扩展名"**：目录叫 `报告.pdf`、`archive.zip` 同样要放行） | `directoryFiles()` / `looksLikeDirectory()` |
| 遮罩加 **×**（`#ff-drop-close`）+ **Esc**；另有一枚 **× 逃生按钮**（`#ff-drop-escape`）随每次文件拖拽出现（含放行的文件夹），拖拽结束后再留 8 秒 | `showOverlay()` / `showEscape()` |
| 凡是我们吞掉的终止事件（drop、×、Esc、看门狗、卸载）都补发宿主自己的复位路径：合成 `window.dragend` + 指向 `body` 的视口边缘 `dragleave` | `releaseHostDrag()` |
| **只要 stopPropagation 掉一次 drop，就无条件补发宿主复位**（"首次 `dragenter` 读不到文件 → 松手时才分类"这条路径里宿主已经计过数，漏发就会留下卡住的全屏遮罩） | `onDrop()` |
| × / Esc 之后**这一段拖拽整体交回宿主**（含它的 drop），不再"表面退出、松手仍然偷偷接管"；只有**拖拽进行中**的逃逸才上锁，拖拽结束后点残留的 × 不会污染下一次拖拽 | `escapeDrag()` / `onDrop()` |
| 逃生按钮 8 秒后自动退场时**再补一次宿主复位**：连续 8 秒没有任何拖拽事件，说明宿主遮罩若还在就是陈旧的 | `retireEscape()` |
| 混合拖拽（文件夹 + 文件）整体交回宿主，不做半接管（合成 drop 无法携带目录的 entry，半接管必然出错） | `onDrop()` |
| 不再按形状二次过滤 `handleOthers()`：被我们吞下的 drop 必须有人接——0 字节/无类型文件照常锻造，绝不再"既不锻造也不交回" | `handleOthers()` |

### 新增测试

**`test-client-drag.mjs`**：用 `node:vm` + 迷你 DOM **按宿主方式**（含 `dragDepth` 计数器、
`dragover` 的 `preventDefault` 与 `droppedDirectories()` 语义）重放 16 组真实拖拽序列、117 条断言。
两种浏览器方言都跑：`spec`（MDN：`webkitGetAsEntry()` 只在 `dragstart`/`drop` 阶段可读）与
`chrome`（各阶段都能读）——两边的外部行为必须一致：

- 文件夹拖拽：entry API / 无 API 特征 / 带扩展名的目录名（`报告.pdf`）/ 首次 `dragenter` 不带 files
  四条路径 → 宿主全程收到事件、计数归零、零上传、无遮罩
- 真文件拖拽 → 遮罩 + ×、上传恰好一次（含文件名头与字节数）、宿主计数被复位
- **未定性即松手**（首次 `dragenter` 读不到文件）→ 仍然恰好锻造一次，且宿主计数归零（卡死回归点）
- **× / Esc / 看门狗**：遮罩与逃生按钮消失、宿主计数归零、**这一段拖拽的 drop 交回宿主且零上传**；
  1.5s 时间闸门两端都测（同段拖拽靠 `dragover` 保活 → 仍不上锁；新拖拽 → 照常接管）
- 松开后残留的 × 点掉 → 宿主计数归零，且**不**污染下一次拖拽
- 空文件 / 无类型文件 / 无类型空文件 → 三者都不再"静默消失"
- 混合拖拽（部分条目 entry 无应答）→ 整段放行、零上传；离开视口 / 真实 `dragend` → 遮罩与 × 退场
- 卸载后监听器与逃生元素全部清除（HMR 不叠加）

**变异自检**：对 `lib/client.js` 注入 8 个人为回归（去掉宿主复位、恢复"带扩展名不当目录"、
drop 忽略逃逸状态、复位改成条件触发、取消 `releasingHost` 守卫、去掉逐个条目兜底……），
套件 8/8 全部报错——这些断言不是摆设。

### 修复（全盘自检追加）

**① 协议 stdout 在中文 Windows 控制台下会把「编码崩了」伪装成 internal 错误。**

`python -m formatforge translate <含 ¥/emoji 的文件>`（README 里写明的直接用法）在 cp936 控制台返回
`{"ok": false, "code": 4070, "error": {"kind": "internal", "message": "'gbk' codec can't encode ..."}}`
——内容没问题，是**字节流**撞了控制台代码页。宿主插件侧 spawn 时本来就设了
`PYTHONIOENCODING=utf-8`/`PYTHONUTF8=1`（`services/python-runner.mjs`），所以只有直接跑 CLI 会踩；
本地 `pytest` 也因此红了 2 个协议用例（父进程按 GBK 解码 → reader 线程 UnicodeDecodeError → `stdout=None`）。
CI 是 UTF-8 locale，所以一直是绿的。

| 改动 | 文件 |
|---|---|
| CLI 入口把协议 stdout 固定成 UTF-8（不再随控制台代码页漂移） | `formatforge/__main__.py` `_ensure_utf8_stdout()` |
| 测试侧显式按 UTF-8 解码子进程 stdout / stderr | `test/unit/test_cli_protocol.py`（2 处 `subprocess.run`） |
| Python 内核版本 2.0.1 → **2.0.2**（`__version__.py` 是单一版本来源，与 npm 侧两处必须同值；CLI `version` 也读这里） | `formatforge/__version__.py` · `packages/dsh-formatforge/package.json` |

**② 版本对齐**：CLI `version` 现在与 npm 包一致报 `2.0.2`。

### 全盘自检（2026-10-02）

| 门禁 | 命令 | 结果 |
|---|---|---|
| Python 单测 | `pytest test/ -q` | **564 passed / 5 skipped / 0 failed**（修编码前是 562 passed + 2 failed） |
| Lint / 格式 | `ruff check .` · `ruff format --check .` | All checks passed · 69 files already formatted |
| 类型检查 | `mypy core/ parsers/ formatforge/ --ignore-missing-imports` | ⚠️ 本机不可复现 CI（见下）；**CI 门禁在上一次推送为绿** |
| 安全扫描 | `bandit -r core/ parsers/ formatforge/ -ll` | 10 medium / 0 high（全是既有的 pickle 缓存与 `xml.etree` 解析，非本次改动文件；CI 该步 warning-only） |
| Bundle 语法 | `node --check`（index + lib + tools + services + http） | 全过 |
| Client 契约 | `test-client-bundle.mjs` | `CLIENT-BUNDLE-OK`（+8 监听器，disposer 后归零） |
| Client 拖拽行为 | `test-client-drag.mjs` | **117 断言全过** + 8/8 变异全被抓 |
| Bundle 清单 | `test-manifest.mjs` | `MANIFEST-OK` |
| 插件 e2e | `test-local.mjs` · `test-inbox.mjs` · `test/test-truncate-consistency.mjs` | `LOCAL-E2E-DONE` · `INBOX-E2E-DONE` · 13 cases consistent |
| 实机宿主 | `GET /plugins/??@tianbuyu-wwx/dsh-formatforge/client.js&rev=…` | 200，rev 与新 mtime/size 匹配，含 `ff-drop-escape`/`retireEscape`/`wasEscaped` |
| npm 包内容 | `npm pack --dry-run` | 17 files / 40.5 kB，含修好的 `lib/client.js` |

> **mypy 的本机差异**：`python_version = "3.10"` 配置下，本机 venv 能看到全局 Python 3.12 的
> 可选包（numpy 2.5.2 的 `.pyi` 需要 3.12 语法；`tomllib` 可被解析），mypy 因此在
> `site-packages/numpy/__init__.pyi` 与 `parsers/toml_parser.py`（既有文件，本次未改动）上报错；
> **同一份改动 `git stash` 到干净树后报同样的错**，而 CI（同 mypy 2.3.1、同配置、未装这些可选包）
> 上一次推送 7/7 全绿。其余门禁均为本机实跑。

## [2.0.1] - 2026-09-30 — 修掉「通知污染会话 + 跨会话失效」

> 用户现场反馈：*「拖入文件的上下文只生效于当前的对话，别的对话不生效，也不用再显示一遍」*
> 完整自检报告：[SELF_CHECK_v2.0.0.md](SELF_CHECK_v2.0.0.md) · 后续计划：[ROADMAP.md](ROADMAP.md) R6

### 修复

**收件箱通知不再是 `user/message`（推送默认关闭）。**

根因：宿主**没有临时通知通道**——`KNOWN_SESSION_EVENT_TYPES` 里所有模型可见事件都会持久化。
所以 `services/notify.mjs` 原来 append 的那条 `user/message` 必然带来三个后果：

1. **永久写进 transcript** —— 之后每一轮都重新发给模型、UI 里反复出现（用户说的「又显示一遍」），
   并且成为永久的上下文成本；
2. **被署名为用户** —— `role: 'user'` + `source.kind: 'user'`，对话里出现了用户从没说过的话；
3. **只送达当时持有 live agent 的会话** —— `ctx.agents.list()` 只包含正在运行的会话，
   用户在别的对话里工作时拖的文件永远不会有任何提示（用户说的「别的对话不生效」）。

改动：

| 改动 | 文件 |
|---|---|
| 推送**默认关闭**（`FF_INBOX_NOTIFY=true` 才开） | `services/notify.mjs` |
| 按 `resultId` **去重**，同一产物每会话最多播报一次 | `services/notify.mjs` + `index.mjs` |
| 通知文案 6 行 → **1 行**（transcript 是永久成本） | `services/notify.mjs` |
| **拉取式**取代推送：`ff_result {list:true}` 任何会话任何时候都能读 | `skills/dsh-formatforge/SKILL.md` |
| 启动日志 `notify=` → `push-notify=`（语义更准） | `index.mjs` |

**为什么拉取式是对的**：收件箱本来就是**共享目录**，任意对话都能用 `ff_result` 取到产物。
缺的是「知道去看」，而不是「被推一条消息」——后者的代价是永久上下文污染加错误署名。

### 新增测试

`test-inbox.mjs` 增加 3 项断言：

- 通知必须是单行（`notice is a single line`）
- 同一 `resultId` 重复播报被抑制（3 次调用只出 1 条）
- **默认关闭**且不向 transcript 写任何消息

### 文档

- 新增 **`SELF_CHECK_v2.0.0.md`** —— 30 个真实文件 × 实机插件的全面自检报告
- **`ROADMAP.md` 重写** —— R1–R5 归档，新增 R6「用户体验优先」（含收件箱数据库方案）
- README：`FF_INBOX_NOTIFY` 默认值与原因；测试数 `444` → `564`

## [2.0.0] - 2026-09-30 — 适配 DeepSeek Harness 0.2.0-rc.2

> 主题：宿主从「npx 拉的 dsh web」换成 **Electron 桌面版 dsh-desktop-runtime 0.2.0-rc.2**，
> 安装目标 profile 从 `web` 变为 `desktop`。插件契约几乎未变，但**版本闸门**会让不修就装不上。
> 详见 [ADAPTATION_PLAN.md](ADAPTATION_PLAN.md)。

### 为什么是 major（2.0.0）而不是 1.1.0

- **宿主要求被收紧**：peer 区间从「0.0.x / 0.1.x」改为「0.2.x」，pre-0.2.0 宿主不再受支持。
  这不是白收的——0.2.0 的 launcher 才内建 peer-aware linked 解析，
  正是它让包内 junction 桥接可以删除；而保留 junction 的旧宿主，本来就是靠它解析 peer 的。
- **编号冲突**：`v1.1.0` 这个 git tag 已被 2026-06-12 的旧 Web 版占用
  （`4dcab67 chore: v1.1.0 架构精简…`），CHANGELOG 里也已有 `## [1.1.0] - 2026-06-12`
  与 `## [1.2.0] - 2026-06-12` 两条历史条目。2.0.0 在 npm、git tag、CHANGELOG 三处都不冲突。
- **协议没有变**：`packages/dsh-formatforge/protocol/v1/` 保持 v1，工具签名与协议 JSON 逐字段兼容。
  变的只是「跑在哪个宿主上」。

### 破坏性阻塞（不修则 `dsh plugin add` 直接拒绝）

1. **peer 版本区间未覆盖 0.2.x**
   - 文件：`packages/dsh-formatforge/package.json`
   - 现象：宿主的 `evaluatePluginCompatibility()`
     （`dsh-app-boot`）对每个 `@deepseek-ai/dsh*` peer 做
     `semver.satisfies(runtime, range, {includePrerelease:true})`；旧区间
     `>=0.0.1-rc.1 <0.1.0 || >=0.1.0-rc.1 <0.2.0-0` 对 `0.2.0-rc.2` 判 false，
     `dsh plugin add` 在 pnpm 之前就 `installation rejected … nothing was installed`（exit 1）。
   - 修法：两个 peer 区间改为 `>=0.2.0-rc.1 <0.3.0-0`。

2. **包内 `node_modules` junction 指向已消失的 npx 缓存**
   - 现象：`node_modules/@deepseek-ai/{dsh-tools,dsh-skill-filesystem}` 是
     `scripts/rebuild-plugin-junctions.py` 留下的 junction，目标
     `%LOCALAPPDATA%\npm-cache\_npx\<hash>\…` 已被宿主重装清掉。
   - 根因已消失：0.2.0 的 launcher 为 linked profile 包内建 **peer-aware 解析**
     （`dsh-app-boot::routeLinked()`），peer 位置优先于物理 `node_modules`，
     因此包内 bridge 不再需要，且残留会遮蔽宿主副本。
   - 修法：删除两个失效 junction；`rebuild-plugin-junctions.py` 标注为 0.1.x 时代遗留。

### 变更

1. **清单补齐当前公开字段**：`dsh.manifestVersion: 1`、`engines.dsh: ">=0.2.0-rc.1 <0.3.0-0"`。
2. **`cordis.patch.yml`**：删掉 0.2.0 loader 不认的 `package:` 死字段（只保留 `id` + `name`）。
3. **inbox 跟随 `DSH_HOME`**：`services/inbox-watcher.mjs::ffHome()` 优先级变为
   `FF_HOME` → `$DSH_HOME/formatforge` → `~/.dsh/formatforge`，
   与宿主 `@deepseek-ai/dsh-home-paths::resolveDshHome()` 一致（自定义 home 不再往 `~/.dsh` 写）。
4. **inbox 轮询定时器 `unref()`**：插件不该成为宿主进程存活的原因。
5. **`index.mjs` 版本号改为读 `package.json`**（原先硬编码 `0.12.0`，与包版本漂移）。

### 修复（浏览器侧）

6. **client 模块监听器泄漏（HMR 下重复上传）**——`lib/client.source.js`
   - 现象：`apply(ctx)` 忽略 `ctx`，`activate()` 注册 7 个监听器且无清理；
     宿主每次 HMR reload（`client-hmr` → `tearDownEntryFiber` → `entry.refresh()`）
     都会再注册一套，一次拖拽触发 N 次上传（`stopPropagation` 不拦同节点兄弟监听器）。
   - 修法：`activate()` 返回 disposer（移除全部 7 个监听器 + 收起 overlay）；
     `scripts/build-client.mjs` 生成 `exports.apply = ctx => ctx.effect(() => activate())`，
     无 `ctx.effect` 时退化为直接激活。
7. **overlay 设计 token 失效**：`--dsw-alias-bg-primary` / `--dsw-alias-text-primary`
   在宿主里根本不存在 → 改为 `--dsw-alias-bg-base` / `--dsw-alias-label-primary`（深色主题生效）。

### 工具与脚本

8. **`test-manifest.mjs` 断言纠正**：原断言要求 client bundle 的 load id == `cordis.patch.yml`
   的 entry id；实际 0.2.0 的 graph row 以**包名**为键
   （`dsh-client-modules::graphRow(packageName, …)`），浏览器半边按该 id 查表。
   现断言 id == 包名 + entry `name` == 包名 + entry id 保持短 id，并校验 `engines.dsh`。
9. **`test-local.mjs` 不再破坏性删目录**：原 `process.on('exit')` 会 `rmSync` 整个
   `node_modules`；现在只清理自己创建的 stub（按 `0.0.0-local-stub` 版本标记识别），
   真实依赖存在时不动。
10. **新增 `test-client-bundle.mjs`**：用 `node:vm` + 假 DOM 按宿主方式执行 `lib/client.js`，
    断言 load id、factory exports 形状、以及「apply → ctx.effect → disposer 清空监听器」
    与二次 apply 不叠加。
11. **`test/test-truncate-consistency.mjs`**：去掉无用的宿主 stub 与破坏性清理；
    解释器与仓库根改用插件自身的 `resolvePython`/`findRepoRoot`
    （原先用 PATH 上的 `python`，在只有 Windows Store 别名的机器上必然失败，
    且 `repoRoot` 层数算错）。
12. **`scripts/verify-install.py` 适配 0.2.0**：支持 `--profile`/`--base-url`/`--token`，
    默认 `desktop` + `19387`；bundle 检查读 `dsh.profile.bundles`；
    尊重 `$DSH_HOME`；artifact 路径改为宿主发布的 combo URL；
    URL token 走 cookie jar（token 交换是 303 + Set-Cookie）；输出强制 UTF-8。
13. **`scripts/rebuild-plugin-junctions.py`**：顶部标注 0.2.0 起废弃及其原因，profile 可配。

### 验证

- 真实宿主模块进程内契约自检 **17/17 通过**（`dsh-tools` 0.2.0-rc.2 的 `defineTool` 编译器 +
  `FileSystemSkillProvider` + `webServer` 路由 + Python 内核 e2e）。
- 宿主自带 `evaluatePluginCompatibility()` 判定 **compatible**。
- 隔离 `DSH_HOME` 冷启动真实 `dsh web`：启动日志出现
  `tools registered: ff_translate, ff_formats, ff_result, ff_batch, ff_diff`；
  `GET /formatforge/health` 200；boot graph 收录并成功取到 client bundle；
  `POST /formatforge/upload` → inbox → 产出 `.ff.md/.ff.json`（`.exe` 被 415 拒绝）。
- `scripts/verify-install.py` 对隔离实例 **ALL GREEN**。

## [1.0.1] - 2026-08-31 — Hotfix（description + argparse JSON 化）

> 基线：v1.0.0（567 测试）→ v1.0.1（569 测试，+2）

### 修复

1. **description 修正**：v1.0.0 npm 包 description 字段仍含 'v0.14.0'（被遗漏）
   - 文件：`packages/dsh-formatforge/package.json`
   - 修法：description 字符串 v0.14.0 → v1.0.0
2. **argparse 错误 JSON 化**（v0.14.1 候选 #1）
   - 文件：`formatforge/__main__.py`
   - 修法：`main()` 临时 `sys.stderr = _SilentStream()` 让 argparse usage 静默，
     `SystemExit` 时走 `_fail("internal", ...)` 输出协议 JSON 到 stdout
   - 之前 argparse 错误走 stderr + exit 2，破坏 stdout 唯一出口约定
3. **测试 `test_category_invalid` 修正**：旧断言依赖 argparse stderr 文本输出

### 新增测试

- `test/unit/test_cli_protocol.py::TestArgparseJsonOutput`（2 测试）

## [1.0.0] - 2026-08-31 — 首个 production-ready stable

> 基线：v0.14.0-rc.1（538 测试）→ v1.0.0（567 测试，+29）
> 主题：**v1.0 production-ready 里程碑**——v0.14.0 stable 代码 + 协议冻结 + 5 项 audit 修复。

### 升级指南

- npm 上 v0.14.0 缺 audit 修复（4 bug + 1 性能）——已在 npm 上 deprecate，提示升级 v1.0.0
- GitHub Release v0.14.0 加注 "升级到 v1.0.0"
- v1.0.0 是首个 production-ready stable，**v1.x 内 API 向后兼容**（不破坏性改动）

### v1.0.0 增量（5 项 audit 修复）

1. **Bug：translate.mjs 多文件分页用 inline 旧逻辑（v0.13.0 遗留）**
   - 文件：`packages/dsh-formatforge/tools/translate.mjs` line 152-160
   - 修法：改用 `_truncate.mjs::smartTruncate` 替代 inline 截断
2. **Bug：多文件分隔符 `---` 与 markdown 水平线冲突**
   - translate 多文件拼接改用 `<!-- ff-file-sep -->`（HTML 注释——markdown 不解析、对模型可读）
   - 之前 `--- 第 1 页 ---` 水平线被 smartTruncate 误识别为多文件分隔符，**实测 cap=40/70 时单文件内容被切断**
3. **Bug：`smartTruncate` JS / Python 算法不一致（6 case 不一致）**
   - 修法：sep_len 跟踪避免 nxt 算法漂移（Python 与 JS 完全对齐 13/13）
4. **Bug：`--against-dir` 触发 self-diff**
   - 文件：`formatforge/diff.py::cmd_diff_against_dir`
   - 修法：`candidates` 加 `if p != path_b and p.exists()` 排除自身
5. **性能优化：inbox-watcher retention sha256 全量读**
   - 文件：`packages/dsh-formatforge/services/inbox-watcher.mjs`
   - 修法：`openSync + readSync(64KB) + closeSync` 替代 `readFileSync().slice()`

### 测试

- 567 passed / 0 fail
- 跨语言 truncate 一致性：13/13
- ruff ✓ / format ✓ / mypy ✓

### 未修的 7 项（v0.14.1 / v1.0.1 hotfix 候选）

| # | 问题 | 严重度 | 处置 |
|---|---|---|---|
| 2 | argparse 错误未走 JSON 输出 | UX | v0.14.1 修 |
| 5 | retention 通知完全静默化 | UX | v0.14.1 改 Plan B |
| 6 | 跨进程 `.ff.retired.log` append race | 性能 | 极低风险 |
| 1 | 无扩展名文件 fallback `parser=unknown` | 已知边界 | v0.14.1 重构 |
| 7 | 同内容不同扩展名评分不同 | 已知行为 | 接受 |
| 8 | ocr_low_confidence 阈值严格边界 | 已知行为 | 接受 |
| 10 | capabilities `hasattr` 探针可能误报 | 已知 | 已文档化 |

## [0.14.0] - 2026-08-31 — 窗 B 全收口（v1.0 stable 前最后一站）

> 基线：v0.13.0（538 测试）→ v0.14.0 stable（566 测试，+28）
> 主题：完成 v0.14.0 计划全部 7 项（2 项 P0 + 5 项 P1）。v1.0 stable 直接复用此代码 + 窗 C 协议冻结。

### Added

- **B-P0-1 `ff_formats` 能力元数据**：每个 format 自带 `capabilities` 列表（自动扫描 parser 代码真实方法名）
- **B-P0-2 `ff_diff` 增量模式**：`--against-dir <dir>` + `--since-mtime <ts>`，共享 `_compute_diff`
- **B-P1-3 retention 通知降噪**：retention 清理只 log 不广播，避免惊扰 live session
- **B-P1-4 TTL 删除前 `.ff.retired.log`**：sha256(path) + ts + size 审计轨迹
- **B-P1-5 质量评分按 file_type 动态调权重**：纯文本 table_accuracy 归零；表格 table_accuracy 提高
- **B-P1-6 OCR enhance 漏判修复**：OCR 后纯图片 PDF，OCR confidence < 0.6 触发 `ocr_low_confidence`
- **B-P1-7 多文件 markdown `---` 分隔符保护**：截断优先级提升到最强边界，JS+Python 双端同步
- 跨语言一致性测试 `test-truncate-consistency.mjs` 11 case（保证 JS/Python smartTruncate byte-equal）

### Changed

- `cli/formatforge diff` 顺序变更 `path_b path_a`（argparse 限制）
- `_resolve_paths` 容错旧顺序
- `QualityReport.analyze` 现在记 `file_type` → `overall_score` 按 file_type 调权

### Removed

- **MediaIndexStrategy 从策略注册表移除**（v1.0/C 清理 dead code）：无人调用、auto_detect 不选它、CLI conversion_type 枚举不引用；class 保留供 v2.0 删

### Notes

- v0.14.0 RC（v0.14.0-rc.1）已发布但不进 npm latest——本 stable 才进 npm latest
- 协议冻结（v1.0/C）由 PR #9 完成
- npm 上 `latest: 0.14.0` 发布后，旧 0.13.0 仍可访问但不再推荐

### Tests
- 538 → **566 passed**（+28：B-P0-1 11 + B-P0-2 6 + B-P1-3/4 各 1 + B-P1-5 4 + B-P1-6 5 + B-P1-7 4）
- ruff ✓ / format ✓ / mypy ✓
- Node `test-local.mjs` / `test-inbox.mjs` / `test-manifest.mjs` / `test-truncate-consistency.mjs` 全过

## [0.14.0-rc.1] - 2026-08-31 — RC 候选（v1.0 前第二批 P0）

> 基线：v0.13.0（538 测试） → v0.14.0-rc.1（555 测试，+17）
> 主题：**会话模型发现能力 + diff 增量模式**。为 P1 五项做铺垫，本 RC 仅含 2 项 P0；完整 v0.14.0 等下个工作窗合并 P1 后再发 stable。

### Added
- **B-P0-1 `ff_formats` 能力元数据**：每个 format 自带 `capabilities` 列表（机器可读），让会话模型按能力选择 format：
  - `pdf` → `[furniture_strip, ocr, table, two_column]`
  - `pptx` → `[animation_order, speaker_notes, table]`
  - `epub` → `[chapter_split]`
  - `xlsx` → `[multi_sheet]`
  - `odt/ods/odp` → `[table]`
  - 数据来源：自动扫描 `parsers/*.py` 类真实方法名（`_extract_animations`/`_parse_ncx`/`_extract_table`/...），不依赖静态字典——自动反映 parser 代码真实能力
  - 新模块 `core/format_capabilities.py`
- **B-P0-2 `ff_diff` 增量模式**：
  - 新参数 `--against-dir <dir>`：与 dir 内同 stem 文件做 diff（path_a 可省，自动从 dir 找）
  - 新参数 `--since-mtime <ts>`：仅处理 path_b mtime >= 此 Unix timestamp 的文件
  - 抽出 `_compute_diff` 共享函数（单文件模式 + 增量模式都用）
- 新单测 `test/unit/test_format_capabilities.py` 11 项（probe 注册 + build_format_details + capability 检测）
- 新单测 `TestR14DiffIncremental` 6 项（against_dir stem 匹配 / 显式 path_a 优先 / 缺 stem 报错 / since-mtime 过滤 / 类型校验 / 0 等价不过滤）

### Changed
- **CLI 顺序变更**：`formatforge diff` 现在 `path_b path_a`（argparse 限制：optional+required positional+中间 option 会失败）
- `_resolve_paths` 容错：JS 端或测试传反顺序时自动检测并互换（path_a 是文件 path_b 不是 → 互换）
- CLI 注册注释解释 argparse 限制 + 共享 `_compute_diff` 抽出
- SKILL.md `ff_formats` 条目加 capabilities 字段说明

### Notes
- **本 RC 仅含 2 项 P0**，未含完整 v0.14.0 计划的所有 5 项 P1（retention 降噪 / TTL 预览 / 动态权重 / OCR 漏判 / markdown 分段优先）——下个工作窗继续
- npm 上**不发布 0.14.0-rc.1**（RC 标签会让 npm dist-tag 混乱）；只走 PR + GitHub Release，不打 npm。完整 v0.14.0 stable 才上 npm

### Tests
- 538 → **555 passed**（+17：B-P0-1 11 项 + B-P0-2 6 项）
- ruff ✓ · format ✓ · mypy ✓（49 source files 0 issues）
- Node `test-local.mjs` / `test-inbox.mjs` / `test-manifest.mjs` / `test-truncate-consistency.mjs` 全过

## [0.13.0] - 2026-08-31 — 封口批（v1.0 前 P0/P1 修复）

> 基线：v0.12.0（537 测试） → v0.13.0（538 测试）
> 主题：清理 v0.10-v0.12 累积的协议不一致 + 文档漂移，为 v1.0 协议冻结做准备

### Added
- **A1**：`packages/dsh-formatforge/tools/_truncate.mjs` 新模块——`renderTruncate(text, cap)` + `smartTruncate(text, maxChars, start)`，供 translate.mjs / result.mjs 共用
- **A3**：`formatforge batch` CLI + `ff_batch` 工具新增 `--quality` / `--encoding` / `--language` 三个 flag，与 `ff_translate` 对齐；批量锻造出的 markdown 现在带 enhance 提示与会话模型目标语 metadata
- **B3**：单测 `tests/test_pipeline_steps.py::TestBuildResultStep::test_builds_result_when_decision_noop`——覆盖 `conversion_needed=False` 路径走 `BuildResultStep` 不崩的回归保护
- **C1**：`renderTruncate` 抽出共用——render 层兜底截断走「段落 > 行 > 硬切」语义，避免切碎代码块/表格
- **D1**：`SKILL.md` frontmatter 补 `version: 0.13.0` + `updated: 2026-08-31`；底部版本号从 v0.9.0（4 个版本没改）→ v0.13.0；description 增 `ff_diff` 描述
- **G1**：`core/decision_engine.py::ConversionDecision` docstring 扩充——标明 `strategies` 字段是「候选策略列表」（按序考虑）而非「已执行的策略」，避免会话模型误解
- **跨语言一致性测试**：`packages/dsh-formatforge/test/test-truncate-consistency.mjs`——JS smartTruncate 与 Python `core/utils.py::smart_truncate` 在 9 组样例上 byte-equal 对比，未来任一侧改算法即漂移自动捕获

### Changed
- **A1**：translate.mjs 多文件分页字段从 `data.meta.next_offset` → `data.paging.next_offset`（与单文件路径统一）；render 分页提示也改读 `data.paging.next_offset`
- **A3**：`formatforge/__main__.py::cmd_translate_main` 返回签名从 `(content, meta)` → `(content, meta, enhance | None)`；quality/encoding/language/custom_prompt 参数透传到 Python CLI
- **B1**：`packages/dsh-formatforge/tools/diff.mjs` 在 `execute` 开头复用 `validateLocalFile` 对 `path_a`/`path_b` 做 size clamp（防 OOM 大文件）
- **B2**：`services/inbox-watcher.mjs` 与 `formatforge/batch.py` 的 `KNOWN_EXT` 同步移除 `.doc`（无 Python doc 解析器，移除假阳性）
- **C6**：`packages/dsh-formatforge/tools/result.mjs` 单文件查找删除 `names.find((n) => n.includes(rawId))` 兜底（id="abc" 误命中 xxxabcxxx.ff.json 的潜在 bug）；改为精确 `resultId` JSON 头匹配

### Fixed
- **测试健壮性**：`tests/unit/test_cli_protocol.py` 的 `TestR11XlsxSchema` / `TestR11DocxRevisions` / `TestR11PptxAnimations` 加 `pytest.importorskip`——venv 漂移（缺 openpyxl/docx/pptx）从「fail 成 ERROR」降级为「skip」

### Tests
- 537 → **538 passed**（+1：B3 回归测试）
- ruff ✓ · format ✓（54 files already formatted） · mypy ✓（48 files 0 issues）
- bandit：0 High（CI threshold `-ll` 允许 Medium/Low warning）
- Node `test-local.mjs` / `test-inbox.mjs` / `test-manifest.mjs` / `test-truncate-consistency.mjs`（新增）全过
- `scripts/dev.py --quick` 全套通过

## [0.12.0] - 2026-08-28 — 第三波战略工具（ff_diff 文件对比）

### Added
- **B10 `ff_diff` 工具**（`tools/diff.mjs` + CLI `diff` 子命令 `formatforge/diff.py`）：
  - 逐行 LCS diff（difflib.SequenceMatcher），输出 unified diff 格式
  - 参数：path_a（旧版）、path_b（新版）、format（中间格式）、context_lines、max_chars
  - 返回：additions / deletions / unchanged_count / similarity / diff_preview
  - 任意格式可对比（先走 translate 转 text，PDF/DOCX 也能 diff）
  - 文件不存在 → file_not_found；转换失败 → parse_failed
- SKILL.md 工具清单加 `ff_diff`
- 测试：TestR12Diff 4 项（简单版本 / 相同文件 / 缺文件 / PDF 自比）

### Changed
- `formatforge/__main__.py`：注册 diff 子命令
- `packages/dsh-formatforge/index.mjs`：注册 ff_diff（5 工具：ff_translate/ff_formats/ff_result/ff_batch/ff_diff）
- `test-local.mjs` 工具数断言 4→5

### Fixed
- `_read_text_lines` 处理 translate_file_data 返回 dict（协议 data 字段）而非字符串

### Tests
- 537/537 passed（533 → 537，+4）· ruff ✓ · format ✓ · mypy 48 文件 0 错

## [0.11.0] - 2026-08-28 — 第二波场景深耕（CSV/XLSX schema + DOCX 修订 + EPUB 章节 + PPTX 动画）

### Added
- **B1 CSV/XLSX/SQL schema 推断 + 前 N 行预览**（`core/conversion_strategies.py`）：
  - 类型判定：integer / float / date / boolean / string
  - 整数/浮点合并判定（混小数点整列 → float）
  - `structured_data.schema` 顶层汇总 + 每表 `tables[i].schema` + `preview_rows`（前 5 行）
  - CLI `--type type` 输出 `meta.schema` / `data.structured_data.schema`
- **B5 DOCX 修订追踪**（`parsers/docx_parser.py`）：w:ins / w:del 抽出到 `PageContent.metadata.revisions`，
  含 author/date/text。python-docx 默认忽略 w:ins/w:del 文本，B5 显式 iter 这两个 tag。
- **B8 EPUB 章节拆分 + NCX 标题**（`parsers/epub_parser.py`）：
  - `_parse_ncx` 解析 NCX toc.ncx → navPoint.title
  - 通过 manifest 反查把 spine itemref idref 映射回 NCX 章节标题
  - element metadata.chapter_title 填充章节名
- **B6 PPTX 动画顺序**（`parsers/pptx_parser.py`）：
  - `_extract_animations` 扫 p:timing/p:par 节点
  - 返回 [{index, shape_id, shape_name, effect_type, delay_ms}, ...] 按播放顺序
  - 讲者备注（notes_slide）早已支持，B6 加补动画（观望池 PPTX 深度达标）

### Changed
- `formatforge/__main__.py` cmd_translate：把 `result.structuredData` 透传到 `data.structured_data`（B1 CLI 暴露）
- `core/conversion_strategies.py` TableExtractionStrategy：`tables[].data` 不再含 header（挪到 `headers` 字段）

### Fixed
- parser 在 EPUB 缺 NCX 时不报错（_parse_ncx 异常被吞 + log.debug）

### Tests
- 533/533 passed（509 → 533，+24 增量：B1 CSV/XLSX 3 项、B5 DOCX 2 项、B8 EPUB 2 项、B6 PPTX 2 项 + 测试 fixture）
- ruff ✓ · format ✓ · mypy 47 文件 0 错

## [0.10.0] - 2026-08-28 — 第一波新功能（ff_batch / language / output-file / formats 过滤）

### Added
- **B3 ff_batch 工具**（`tools/batch.mjs`）：批量锻造，包装 Python CLI `batch` 子命令
  - 参数：source（目录/glob）、out、format、type、workers（1-8）、recursive、force、pages
  - 输出：每文件结果 + 汇总报告 `_batch_report.json`（总/成功/失败/跳过/平均置信度/总耗时）
  - 续跑：产物比源新 → 跳过；空目录 → 仍写报告（exit=1 提示无匹配）
- **B9 `--language` 目标语言 metadata**：ISO 639-1 代码（如 `zh` / `en` / `ja` / `zh-cn`）
  - CLI：写入 `meta.target_language` + `enhance.hint`（提示会话模型按此语种整理）
  - 工具：ff_translate 直接透传
- **A9 `--output-file` 路径**：content 另存到指定文件，stdout 协议 JSON 不变（meta.output_file 字段标记）
- **A10 `formats --category` 过滤**：6 类（document/data/email/image/archive/audio）
  - 输出加 `categories` 列表供会话模型发现可用分类
- `scripts/dev.py`：一键开发脚本（pytest+ruff+format+mypy+烟雾测）
- 8 个 CLI 协议护栏（TestR10LanguageFlag / TestR10OutputFile / TestR10FormatsCategory / TestR10Batch）

### Changed
- `formatforge/__main__.py` cmd_translate：`data` 类型推断加固（cast dict[str, Any] + type:ignore）
- `formatforge/batch.py` 空源返回 exit=1（旧契约）但仍写报告（契约级 _batch_report.json 必存在）

### Fixed
- mypy 在 cmd_translate 多个 dict[str, Any] union 操作时报类型冲突（已 cast 化解）

## [0.9.1] - 2026-08-28 — R3 协作面护栏补丁

### Added
- SKILL.md 同步 R3 用法：ff_result 三工具说明、`--encoding` 参数、retry_with 重调对照表、
  R3.1 auto 智能默认提示、R3.2 ids 批量取回、R3.4 schema -33.3% 标注
- CLI 协议护栏 `TestR3SmartDefault`：auto 模式自动开启 quality（无需 --quality）+ meta.quality_auto 契约字段
- CLI 协议护栏 `TestR3EncodingRetry`：`--encoding gbk` 透传解码 + retry_with 闭环
- CLI 协议护栏 `TestR3MarkdownStructureField`：meta.structured 字段守住
- test-inbox.mjs R3.2 断言：onDone payload.resultId 必须以 `cvt` 开头

### Changed
- `formatforge/__main__.py` cmd_translate 入口：R3.1 智能默认（auto 模式自动 want_quality=True）+
  meta.quality_auto 标记字段（让会话模型知道 quality 是自动开启的）
- `packages/dsh-formatforge/test-inbox.mjs` 关掉 TTL（`FF_INBOX_TTL_DAYS=999`）—— fixture mtime
  古老会被 retention 误判过期；测试只验 R3.2 行为不测 retention

### Fixed
- v0.9.0 时 SKILL.md 描述仅列两工具（缺 ff_result）；R3.2 ids 数组用法无文档

## [0.9.0] - 2026-08-28 — R3 协作面

### Added
- R3.1 ff_translate 智能默认：`--type auto` 自动附带 `--quality`（低置信自动产出 actions），render 加 200 字头部预览
- R3.2 ff_result 批量取回：新增 `ids` 数组参数一次多产物 + 通知附 `resultId`（inbox 消息末尾 `- 结果 id：xxx`）
- R3.3 自愈闭环实测：CLI `--encoding` 透传（gbk/latin-1）+ ConvertStep 优先 conversion_needed 兜底 + raw 文本透传以让 quality 扫 FFFD/mojibake
- R3.4 工具描述瘦身：schema 体积 2951 → 1969 chars（削减 33.3%，目标 ≥30%）
- `scripts/measure_r3_selfheal.py` — 自愈闭环实测脚本（3 劣化样本集）
- `test/fixtures/golden/r3_selfheal.json` — R3.3 验收快照（self-heal 3/3 = 100%）

### Changed
- 协议：`ff_result` 批量响应 `data.batch=true / count / ok_count / results[]`
- 通知：FormatForge inbox watcher 携带 `resultId` 给 result.mjs 直接取回
- `core/pipeline_steps.ConvertStep.process()` 重构：优先级 decision→parsed→data→fallback
- `parsers/txt_parser.TXTParser.parse()` 支持 `encoding` 覆写（自愈重试路径）
- `formatforge/__main__.py`：新增 `--encoding` 参数透传 + CLI `quality` 默认在 auto 模式自动开启
- 测试：test_ocr_engine 三处跟随新默认引擎；test_pipeline_steps 增加 raw 透传覆盖

## [0.8.0] - 2026-08-27 — R2 解析质量纵深

### Added
- **R2.1 OCR 管线贯通**：修复「use_ocr 参数透传但引擎从未挂载」的主干断线（PDFParser 注册时 ocr_engine 恒为 None）；新增 RapidOCR (ONNX Runtime) 后端（Windows CPU 首选、真实逐行置信度、兼容新旧两代 API），默认引擎优先级 rapidocr > paddleocr > tesseract > easyocr；修复 pdfplumber 调色板 PNG（mode=P）导致 RapidOCR 返回空的问题（自动转 RGB 重试）；OCR 文字层合并去重（相似行不重复）
- **R2.2 表格语义**：新模块 core/table_semantics.py——None=合并覆盖（继承宿主值）vs ''=真空单元格的语义区分；数值列自动右对齐（markdown `---:`）；跨页表格续接合并（无表头续表整表并入 / 重复表头自动跳过）；原始 grid 随 metadata 携带
- **R2.3 结构保真**：新模块 core/structure_fidelity.py——字号/加粗 → h1-h4 标题层级（全书正文字号中位数基准）；行首 x0 几何聚类 → 列表嵌套层级（最多 4 级）；目录行识别 → `[标题](#锚点)`；markdown 输出时自动按层级渲染，OCR 行永不误判标题
- golden fixture 机制：test/fixtures/golden/ 确定性语料（5 份 PDF：扫描件/水印混排/跨页表格/合并单元格/结构层级）+ 期望快照 + FF_UPDATE_GOLDEN=1 显式刷新；测量脚本 scripts/measure_r2_baseline.py 持续跟踪 enhance 触发率
- 新增 16 项 R2 测试（OCR 4 + 结构 7 + 表格 4 + 触发率 2），总测试 488 → 509

### Changed
- OCR 引擎默认从「恒 tesseract」改为按可用性优先级自动选择；test_ocr_engine 初始化用例跟随新语义
- enhance 触发率（golden 语料）：OCR 接线前 20%（扫描件 image_only）→ 接线后 0%；误判水印文档为 image_only 的问题已修复

> 验收对比 ROADMAP §2：image_only/table_sparse enhance 触发率下降 ≥30% 达成（样本集 20% → 0%）。

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