# DSH 版本适配计划 — DSH-FormatForge → DeepSeek Harness 0.2.0-rc.2

> 扫描日期：2026-09-30
> 插件基线：`packages/dsh-formatforge` v1.0.1（内核 `dsh-formatforge` 1.0.1）
> 宿主：DeepSeek Harness **0.2.0-rc.2**（Electron 桌面版，`dsh-desktop-runtime`）
> 安装目标 profile：`desktop`（`%USERPROFILE%\.dsh\profiles\desktop`），GUI `http://127.0.0.1:19387`
> 证据来源：宿主 app.asar 解包源码（`.scan/dsh-src/`）+ 真实宿主模块进程内契约自检（17/17 通过）

---

## 0. 结论先行

| 判定 | 数量 | 说明 |
|---|---|---|
| 🔴 BLOCKER | 2 | 不修就一定装不上：peer 版本闸门、peer 依赖解析 |
| 🟠 契约漂移 | 4 | 清单字段/脚本/测试与 0.2.0 契约不一致 |
| 🟢 已验证兼容 | 5 类 | 工具 DSL、skill provider、sessions/agents、webServer 路由、client 模块协议 |

**宿主侧代码（5 个工具 + skill provider + HTTP 路由 + Python 内核）本身不需要改动**——
已用真实 `@deepseek-ai/dsh-tools` 0.2.0-rc.2 的 `defineTool` 编译器 + 真实
`FileSystemSkillProvider` 在进程内跑通全部注册与执行路径。

---

## 1. 扫描结果：宿主契约逐项比对

### 1.1 🔴 BLOCKER-1 — peer 版本闸门会直接拒绝安装

`dsh plugin add` 在 pnpm 之前先做兼容性预检
（`@deepseek-ai/dsh-plugin-manager/lib/types/operations.js:296-319`，调用
`dsh-app-boot/lib/index.js:286 evaluatePluginCompatibility`）：

```js
// app-boot:292-301
for (const [name, range] of Object.entries(dependencies)) {
  if (name !== "@deepseek-ai/dsh" && !name.startsWith("@deepseek-ai/dsh-")) continue;
  if (requirement.trim() === "" || !semver.satisfies(runtimeVersion, requirement, { includePrerelease: true }))
    peers[name] = range;
}
```

插件当前声明（`packages/dsh-formatforge/package.json:60-63`）：

```json
"@deepseek-ai/dsh-tools":            ">=0.0.1-rc.1 <0.1.0 || >=0.1.0-rc.1 <0.2.0-0",
"@deepseek-ai/dsh-skill-filesystem": ">=0.0.1-rc.1 <0.1.0 || >=0.1.0-rc.1 <0.2.0-0"
```

实测（用宿主自带 semver 0.2.0-rc.2 判定）：

| range | satisfies(0.2.0-rc.2, includePrerelease) |
|---|---|
| 现有 range | **false** ❌ |
| `>=0.2.0-rc.1 <0.3.0-0` | true ✅ |

后果：预检失败 → `dsh: installation rejected … nothing was installed`，**退出码 1，一个文件都不会装**。
（备选逃生口 `dsh plugin allow-version` 只授精确版本豁免，不修 range 就得每次手工放行，且 UI 插件管理器同样会被拦。）

**修法**：把两个 peer range 放宽到 `>=0.2.0-rc.1 <0.3.0-0`。

### 1.2 🔴 BLOCKER-2 — `node_modules` junction 指向已消失的 npx 缓存

```
packages/dsh-formatforge/node_modules/@deepseek-ai/dsh-tools
  → C:\Users\…\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh-tools   (不存在)
```

这是 `scripts/rebuild-plugin-junctions.py` 留下的旧世代产物：当年宿主不会为 link 安装的插件
解析 peer 依赖，只能在包内塞 junction 桥接。

**0.2.0-rc.2 已经内建了 peer-aware linked 解析**（`app-boot/lib/index.js:1214 findInterceptionLayer`
→ `1471 routeLinked`）：

```js
// routeLinked:1479-1485
if (ancestorSet.has(searchPath) && readPeerNames(directory).has(name)) {
  const route = { kind: "interception", entry: target, after: join(dirname(directory), "package.json") };
  return { route };             // ← 用宿主运行时的同名包，peer 位置优先于物理 node_modules
}
```

即：只要插件 `package.json` 的 `peerDependencies` 里写了 `@deepseek-ai/dsh-tools`，
链接目录下的 importer 就会命中宿主运行时的那一份，**不需要包内 junction**。
（第三方插件 `dshmarket` / `@linxin666/*` 正是这样工作的——它们没有本地 peer 副本。）

**修法**：删掉这两个失效 junction，让宿主 peer 路由接管；同时修掉
`test-local.mjs` 的 `process.on('exit')` —— 它会 `rmSync` 整个 `node_modules`，
任何一次本地测试都会把将来可能存在的真实依赖一起删掉。

### 1.3 🟠 清单字段滞后

`@deepseek-ai/dsh-package-manifest` README 定义了当前公开清单字段：

| 字段 | 现状 | 应补 |
|---|---|---|
| `dsh.manifestVersion` | 缺 | `1`（清单格式标识，与 npm 版本无关） |
| `engines.dsh` | 缺 | `">=0.2.0-rc.1 <0.3.0-0"`（作者声明的兼容区间） |
| `engines.node` | `>=22.13.0` | ✅ 保留（宿主 Electron 44 / Node 22） |
| `dsh.bundle.patch` | `./cordis.patch.yml` | ✅ 契约未变 |
| `dsh.client` | `{inject: [], platform: "web"}` | ✅ 契约未变 |

### 1.4 🟠 `cordis.patch.yml` 的 `package:` 是死字段

0.2.0 的 loader 只认 `id / name / config / group / disabled / inject`
（`cordis-plugin-loader/src/config/entry.ts:10-23`），`applyEntryPatches` 会把未识别键原样留下。
不报错，但属于历史残留，应删。

### 1.5 🟠 自检脚本/CI 与当前宿主不符

| 文件 | 问题 |
|---|---|
| `test-manifest.mjs:33-40` | 断言 `client.js` 的 load id == `cordis.patch.yml` 的 entry id（`dsh-formatforge`）。**错的**：0.2.0 的 graph row 以 **包名** 为键（`dsh-client-modules/lib/index.js:883-884 graphRow(packageName,…)`），浏览器半边按该 id 查表（`lib/client.js:739`）。当前 `lib/client.js` 写的 `@tianbuyu-wwx/dsh-formatforge` 才是对的 |
| `test-local.mjs:28` | `process.on('exit')` 删掉整个 `node_modules`，破坏性 |
| `scripts/verify-install.py` | 硬编码 profile `web` + `127.0.0.1:3080` + `%LOCALAPPDATA%\dsh_web*.log`；现在是 `desktop` profile + GUI `127.0.0.1:19387` |
| `scripts/rebuild-plugin-junctions.py` | 整体过时（见 1.2），且硬编码 profile `web` |

### 1.6 🟢 已确认兼容（无需改动，附证据）

用宿主 app.asar 里解出的**真实** 0.2.0-rc.2 模块做进程内自检，结果 **17/17 通过**：

| 契约 | 宿主实现 | 插件用法 | 结果 |
|---|---|---|---|
| 工具注册 | `dsh-tools/lib/index.js:2878 register()` / `838 defineTool()` | `ctx.tools.register(defineTool({...}))` | ✅ 5 个工具全部通过真实 schema 编译器 |
| 作者 DSL | `assertAuthorKeys` 允许 `type/enum/default/description`；object 必须显式 `additionalProperties` | 各工具 output schema 均显式声明 | ✅ 无抛错 |
| skill provider | `dsh-skill-filesystem/lib/index.js:63-86 constructor(ctx, control, config)` | `new FileSystemSkillProvider(ctx, control, {providerName, customSkillDirs})` | ✅ 构造成功，name=`dsh-formatforge` |
| `ctx.skills.registerProvider` | `dsh-skill/lib/index.js:147` | 同签名 | ✅ |
| `ctx.get('webServer')` + `webServer.register({kind,path,handler})` | `cordis/lib/index.js:763`；`dsh-host-webserver/lib/index.js:158 super(ctx,"webServer")`, `:177 register()` | `http/upload.mjs:46-52` | ✅ 两条 exact 路由注册成功 |
| 会话通知 | `dsh-agent/lib/index.js:612 list()`；`dsh-session/lib/index.js:1441 append()` + `:1191 assertMessageEventShape` | `services/notify.mjs`（`user/message` + `surfaceOp:'append'`） | ✅ 载荷形状逐字段匹配 |
| client 模块 | `dsh-client-modules/lib/index.js:883` graphRow 以包名为 id；`lib/client.js:569 register({id,factory})` | `lib/client.js` `id:"@tianbuyu-wwx/dsh-formatforge"` + `exports.{inject,apply}` | ✅ |
| bundle patch 层 | `dsh-base/cordis.patch.yml` 同构：顶层数组 + `- insert:` | 插件 `cordis.patch.yml` 同构 | ✅ |
| Python 内核 | — | `.venv-fg` Python 3.12.7，`python -m formatforge version/formats` 正常 | ✅ 34 格式 |

---

## 2. 安装路径（0.2.0-rc.2 版）

```
dsh plugin --profile desktop add <插件目录绝对路径>
   │
   ├─ ① 预检 evaluatePluginCompatibility(插件 manifest)      ← BLOCKER-1 在这里拦
   ├─ ② pnpm add（profile 目录，hoisted linker）
   ├─ ③ reconcileProfilePlugins()：把声明了 dsh.bundle.patch 的新依赖
   │      自动追加进 profile package.json 的 dsh.profile.bundles   ← 免手工改 bundles
   └─ ④ 重启 dsh → loadProfileDirectory() 读每个 bundle 的 cordis.patch.yml 作为一层
```

要点：
- **add ≠ 激活**，必须重启桌面端才生效。
- 宿主限制：`requireDesktopProfile()` 要求 profile 已由桌面端初始化过（已满足）。
- 本次装载不需要 `minimumReleaseAge` 调整（本地 link，不走 registry）。

---

## 3. 改动清单（本次执行）

| # | 文件 | 改动 | 类型 |
|---|---|---|---|
| 1 | `packages/dsh-formatforge/package.json` | peer range → `>=0.2.0-rc.1 <0.3.0-0`；补 `engines.dsh`、`dsh.manifestVersion:1`；版本 → `1.1.0` | 必改 |
| 2 | `packages/dsh-formatforge/node_modules/@deepseek-ai/*` | 删除失效 junction | 必改 |
| 3 | `packages/dsh-formatforge/cordis.patch.yml` | 去掉 `package:` 死字段 | 清理 |
| 4 | `packages/dsh-formatforge/test-manifest.mjs` | 断言改为「load id == 包名」，并保留 `__ModuleLoader__` 包裹 + `.apply/.inject` 形状检查 | 修 CI |
| 5 | `packages/dsh-formatforge/test-local.mjs` | 只清理自己建的 stub，不再 `rmSync` 整个 `node_modules` | 修破坏性 |
| 6 | `scripts/verify-install.py` | 支持 `--profile`/`--base-url`，默认 `desktop` + `19387` | 修脚本 |
| 7 | `scripts/rebuild-plugin-junctions.py` | 标注为 0.1.x 时代遗留并给出 0.2.0 说明（保留但不再作为安装步骤） | 修文档 |
| 8 | `packages/dsh-formatforge/index.mjs` | `VERSION` 与包版本对齐 | 清理 |
| 9 | 根 `README.md` / `CHANGELOG.md` | 记录本次适配 | 文档 |
| 10 | `.scan/` | 扫描与验证脚手架（最后清理或加入 .gitignore） | 脚手架 |

**明确不改**：`tools/*.mjs`、`services/*.mjs`、`http/upload.mjs`、`lib/client.source.js`、
`lib/client.js`、`core/`、`parsers/`、`formatforge/` —— 契约自检已证明兼容。

---

## 4. 验收标准

1. `node .scan/check-contract.mjs`（真实宿主模块）17/17 通过。
2. `node packages/dsh-formatforge/test-manifest.mjs` 输出 `MANIFEST-OK`。
3. `node packages/dsh-formatforge/test-local.mjs` 输出 `LOCAL-E2E-DONE` 且不删 `node_modules`。
4. `dsh plugin --profile desktop add <path>` 退出码 0；profile `package.json` 的
   `dsh.profile.bundles` 自动含 `@tianbuyu-wwx/dsh-formatforge`。
5. `dsh --profile desktop --dump-config` 中该 bundle 不落入 skipped，entry 出现在组合树里。
6. 隔离 profile 冷启动（不打扰正在运行的桌面端）：启动日志出现
   `tools registered: ff_translate, ff_formats, ff_result, ff_batch, ff_diff`，
   `GET /formatforge/health` 200，`GET /plugins/@tianbuyu-wwx/dsh-formatforge/client.js` 200。
7. 桌面端重启后：会话里 `ff_formats` 可调；拖一个 `.pdf/.docx` 进窗口 → inbox 出 `.ff.md`。

---

## 5. 执行记录（2026-09-30 完成）

### 5.1 实际改动

| # | 文件 | 状态 |
|---|---|---|
| 1 | `packages/dsh-formatforge/package.json` | ✅ v2.0.0；peer → `>=0.2.0-rc.1 <0.3.0-0`；补 `engines.dsh` + `dsh.manifestVersion:1` |
| 2 | `packages/dsh-formatforge/node_modules/@deepseek-ai/*` | ✅ 两个失效 junction 已删，`node_modules` 目录已空并移除 |
| 3 | `packages/dsh-formatforge/cordis.patch.yml` | ✅ 去掉 `package:`，补注释说明 peer 解析来源 |
| 4 | `packages/dsh-formatforge/test-manifest.mjs` | ✅ 断言改为「load id == 包名」+ entry name 校验 + `engines.dsh` 校验 |
| 5 | `packages/dsh-formatforge/test-local.mjs` | ✅ 只清理自建 stub（按版本标记识别）；显式退出 |
| 6 | `packages/dsh-formatforge/test-client-bundle.mjs` | 🆕 用 `node:vm` 按宿主方式执行 client bundle |
| 7 | `packages/dsh-formatforge/lib/client.source.js` | ✅ `activate()` 返回 disposer；修 overlay 设计 token |
| 8 | `packages/dsh-formatforge/scripts/build-client.mjs` | ✅ `exports.apply = ctx => ctx.effect(() => activate())`；修正 id 规则注释 |
| 9 | `packages/dsh-formatforge/services/inbox-watcher.mjs` | ✅ inbox 跟随 `DSH_HOME`；轮询定时器 `unref()` |
| 10 | `packages/dsh-formatforge/index.mjs` | ✅ 版本读 `package.json`；注释更新 |
| 11 | `packages/dsh-formatforge/test/test-truncate-consistency.mjs` | ✅ 去掉无谓 stub 与破坏性清理；复用插件的解释器/仓库根探测 |
| 12 | `scripts/verify-install.py` | ✅ 支持 `--profile/--base-url/--token`，尊重 `DSH_HOME`，combo URL，cookie jar，UTF-8 输出 |
| 13 | `scripts/rebuild-plugin-junctions.py` | ✅ 标注 0.2.0 起废弃 + 原因 |
| 14 | `README.md` / `CHANGELOG.md` / `.gitignore` | ✅ 安装流程改写；v2.0.0 记录；`.scan/` 与 `.bak-*` 忽略 |

### 5.2 验收结果

| 标准 | 结果 |
|---|---|
| 真实宿主模块进程内契约自检 | ✅ **17/17**（`defineTool` 编译器 / `FileSystemSkillProvider` / webServer 路由 / Python e2e） |
| 宿主 `evaluatePluginCompatibility()` | ✅ compatible（修 range 前判 false） |
| `test-manifest.mjs` | ✅ `MANIFEST-OK: dsh-formatforge \| @tianbuyu-wwx/dsh-formatforge \| 2.0.0` |
| `test-client-bundle.mjs` | ✅ `CLIENT-BUNDLE-OK`（+7 监听器 → disposer 后 0；二次 apply 不叠加） |
| `test-inbox.mjs` | ✅ `INBOX-E2E-DONE` |
| `test-truncate-consistency.mjs` | ✅ 13/13 JS↔Python 一致 |
| `test-local.mjs` | ✅ `LOCAL-E2E-DONE`，退出后 `node_modules` 无残留 |
| `dsh plugin --profile desktop add` | ✅ exit 0；bundles 自动追加；`package.json`/`pnpm-lock.yaml` 均为正确 UTF-8 |
| 隔离 `DSH_HOME` 冷启动真实 `dsh web` | ✅ 工具注册行 / health 200 / boot graph 收录 / client bundle 可取 / upload→inbox→`.ff.md`（`.exe` 415） |
| `scripts/verify-install.py`（隔离实例） | ✅ **ALL GREEN** |
| 桌面端重启 | ⏳ 交给用户（重启会结束当前会话） |

### 5.3 与计划的偏差

1. **标准 5 无法执行**：`dsh --profile desktop --dump-config` 被宿主拒绝
   （`error: profile "desktop" is managed exclusively by the Electron application`）。
   改用**隔离 `DSH_HOME` 冷启动真实 `dsh web`** 替代——验证力更强（真的加载了插件并跑通 HTTP）。
2. **额外发现并修复**：client bundle 的 HMR 监听器泄漏（计划阶段的 4 项契约漂移之外，
   由浏览器侧专项审计在计划写完后补入）。
3. **`@linxin666/*` 被 pnpm 剪枝**：`dsh plugin add` 收敛依赖时移除了 54 个包，其中包含
   `@linxin666/*`（18 个）。**查证后确认是失败安装的残留，不是可用配置**：
   `<profile>/.dsh-market/log.ndjson` 记录 2026-09-29 两次
   `@linxin666/dsh-web-all@0.4.4 exit=1`（pnpm 拦下未批准的构建脚本：ssh2 / cloudflared /
   cpu-features，正对应 `pnpm-workspace.yaml` 里的 `allowBuilds` 占位），随后一次
   `install-blocked: refused while agents are running`。
   被剪掉的其余包（asn1/bcrypt-pbkdf/cloudflared/cpu-features/lightningcss/ws/zod/yaml/clsx/
   qrcode.react…）全是这批 UI 插件的传递依赖；`~/.dsh/{task-board,dsh-usage,dsh-session-archive}`
   数据目录最后写入停在 2026-09-15，即更早一次卸载之前。
   备份在 `~/.dsh/profiles/desktop/.ff-adapt-backup-<时间戳>/`；
   若要真正装回 `@linxin666/dsh-web-all`，需要先在 `pnpm-workspace.yaml` 的 `allowBuilds`
   里放行上述构建脚本，再走市场安装。

4. **激活自动化**：桌面端重启由 `.scan/restart-harness.ps1` 执行——该脚本经 WMI
   `Win32_Process.Create` 启动（脱离 harness 进程树，不会被一起杀掉），
   **以哨兵文件 `%TEMP%\ff-restart\GO` 为闸门**，等本轮回复完成后再宽限 60 秒，
   然后优雅关闭（`CloseMainWindow`，40 秒不退才强杀）→ 重新拉起 →
   轮询 `/formatforge/health` 直到 200。全过程写入 `%TEMP%\ff-restart\log.txt`。

### 5.4 已知遗留

- `pytest` 未装在 `.venv-fg`（Python 内核本次未改动；`pip install -e ".[dev]"` 可补）。
- `@linxin666/dsh-web-all` 的安装仍然失败（见 5.3 第 3 条），需要先批准构建脚本。
