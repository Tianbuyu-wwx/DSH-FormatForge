// lib/panel.source.js — FormatForge 面板（v3.0.0，从零手写：零构建、零 npm 依赖）。
//
// 落点（用户拍板"只做面板"）：宿主右侧栏的**页签**——
//   1) 类型：ctx.sidebarRightTabs.register({ id, kind, priority:'extension', title, guide })
//   2) 主体：ctx.slots.register({ name:'sidebar.right.pane.tab', key: id }, Body)
//   3) 标题：ctx.slots.register({ name:'sidebar.right.pane.tab.title', key: id }, Title)
//   4) 入口：guide 条目（宿主内置 guide 页面里出现一张卡片）+ 侧栏底部动作按钮
//
// 依赖：宿主 Module Loader 提供的 `react`（本 bundle 的 factory 参数 require）。
// 降级（详见 UI_DB_PLAN.md §8-R1）：拿不到 react / 没有 sidebarRightTabs / 插槽未声明
//   → 只写日志，**绝不影响拖拽模块与工具**。
//
// 数据来源：`/formatforge/api/*`（同源请求，宿主鉴权围栏管不到我们的路由，
//   所以 API 侧做了同源判定 + 一次性 token，见 http/api.mjs）。

const FF_PANEL_KIND = 'formatforge-inbox'
const FF_PANEL_ID = '@tianbuyu-wwx/dsh-formatforge'
const FF_PANEL_NS = 'formatforge'
// 侧栏导航条目顺序：宿主的「插件」多为 0、「自动化任务」是 10 → 我们排 20，落在自动化任务下面
const FF_PANEL_ORDER = 20
const FF_API = '/formatforge/api'
const FF_PANEL_LIMIT = 50
const FF_PREVIEW_CHARS = 4000

const FF_DICT = {
  zh: {
    'panel.title': 'FormatForge',
    'panel.guide': 'FormatForge 收件箱',
    'panel.guideDesc': '搜索、预览、重新锻造已转换的产物',
    'panel.search': '搜索产物（支持中文子串）',
    'panel.refresh': '刷新',
    'panel.limit': '每页条数',
    'panel.loading': '加载中…',
    'panel.empty': '还没有产物：把文件拖进窗口即可自动锻造。',
    'panel.emptyQuery': '没有匹配的产物。',
    'panel.error': '读取失败',
    'panel.apiStale': '接口未就绪（HTTP 404）：插件已更新，但宿主还跑着旧的 Node 半 —— 请完全退出 DSH（含托盘）后重开一次。',
    'panel.apiRejected': '宿主拒绝了请求（HTTP 400，空响应）：插件 Node 半未随本次启动加载 —— 请完全退出 DSH（含托盘）后重开一次。',
    'panel.copyPath': '复制路径',
    'panel.retry': '重新锻造',
    'panel.delete': '从列表移除',
    'panel.copied': '已复制',
    'panel.retryQueued': '已排队重转（下一个扫描周期执行）',
    'panel.deleted': '已从列表移除（磁盘文件保留）',
    'panel.preview': '正文预览',
    'panel.more': '还有更多，用 ff_result 取全文',
    'panel.stats': '共 {total} 条 · 来源 {source}',
    'panel.close': '收起',
  },
  en: {
    'panel.title': 'FormatForge',
    'panel.guide': 'FormatForge inbox',
    'panel.guideDesc': 'Search, preview and re-forge converted artifacts',
    'panel.search': 'Search artifacts (substring, CJK friendly)',
    'panel.refresh': 'Refresh',
    'panel.limit': 'Page size',
    'panel.loading': 'Loading…',
    'panel.empty': 'No artifacts yet — drop a file onto the window.',
    'panel.emptyQuery': 'No artifact matches that query.',
    'panel.error': 'Request failed',
    'panel.apiStale': 'API not ready (HTTP 404): the plugin updated but the host still runs the old Node half — fully quit DSH (including the tray) and reopen.',
    'panel.apiRejected': 'Host rejected the request (HTTP 400, empty body): the plugin Node half did not load on this boot — fully quit DSH (including the tray) and reopen.',
    'panel.copyPath': 'Copy path',
    'panel.retry': 'Re-forge',
    'panel.delete': 'Hide',
    'panel.copied': 'Copied',
    'panel.retryQueued': 'Queued for re-forge (next scan tick)',
    'panel.deleted': 'Hidden (files kept on disk)',
    'panel.preview': 'Content preview',
    'panel.more': 'Truncated — use ff_result for the full text',
    'panel.stats': '{total} artifacts · source {source}',
    'panel.close': 'Collapse',
  },
}

function panelLog(msg) {
  try {
    console.log('[ff-panel] ' + msg)
  } catch {
    /* noop */
  }
}

function pickText(lang, key, vars) {
  const dict = FF_DICT[lang] || FF_DICT.zh
  let text = dict[key] || FF_DICT.zh[key] || key
  if (vars) {
    for (const k of Object.keys(vars)) text = text.replace('{' + k + '}', String(vars[k]))
  }
  return text
}

/** 面板内部的小状态机：一次取一页，选中项再取正文。 */
function makeStore() {
  let state = {
    rows: [],
    total: 0,
    source: '-',
    searchMode: '-',
    loading: false,
    error: null,
    query: '',
    notice: '',
    prefs: { panelLimit: FF_PANEL_LIMIT, lang: 'zh' },
  }
  const listeners = new Set()
  const emit = () => {
    for (const fn of [...listeners]) {
      try {
        fn()
      } catch (e) {
        panelLog('listener failed: ' + e.message)
      }
    }
  }
  const set = (patch) => {
    state = { ...state, ...patch }
    emit()
  }
  const api = async (path, options) => {
    // x-ff-client 是写操作的门票：跨站网页带自定义头会触发 CORS 预检，而我们从不回
    // Access-Control-Allow-*，恶意页面因此发不出写请求；面板（同源页面或桌面端）可以随便带。
    const res = await fetch(FF_API + path, {
      ...options,
      credentials: 'same-origin',
      headers: { 'x-ff-client': 'panel', ...((options && options.headers) || {}) },
    })
    let payload = null
    try {
      payload = await res.json()
    } catch {
      payload = null
    }
    if (!res.ok || !payload || payload.ok !== true) {
      const lang = state.prefs && state.prefs.lang
      if (res.status === 404) throw new Error(pickText(lang, 'panel.apiStale'))
      // 宿主 webserver 在处理器抛错时回 400 空 body —— 说明 Node 半没跟着本次启动加载。
      if (res.status === 400 && !payload) throw new Error(pickText(lang, 'panel.apiRejected'))
      const detail = (payload && payload.error && payload.error.message) || `HTTP ${res.status}`
      throw new Error(`${detail}（${FF_API}${path}）`)
    }
    return payload.data || {}
  }
  return {
    getState: () => state,
    subscribe(fn) {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
    async load(query) {
      set({ loading: true, error: null, notice: '', query: query === undefined ? state.query : query })
      try {
        const q = state.query ? `&q=${encodeURIComponent(state.query)}` : ''
        const limit = Number(state.prefs.panelLimit) || FF_PANEL_LIMIT
        const data = await api(`/artifacts?limit=${limit}${q}`)
        set({ rows: data.rows || [], total: (data.rows || []).length, source: data.source || '?', searchMode: data.search_mode || '?', loading: false })
      } catch (e) {
        set({ loading: false, error: e.message, rows: [] })
      }
    },
    async loadPrefs() {
      try {
        const data = await api('/settings')
        if (data && data.prefs) set({ prefs: { ...state.prefs, ...data.prefs } })
      } catch {
        /* 偏好读不到就用默认值 */
      }
    },
    async setLimit(limit) {
      const next = { ...state.prefs, panelLimit: Number(limit) || FF_PANEL_LIMIT }
      set({ prefs: next, error: null })
      try {
        const data = await api('/settings', {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ panelLimit: next.panelLimit }),
        })
        if (data && data.prefs) set({ prefs: { ...next, ...data.prefs } })
      } catch (e) {
        set({ error: e.message })
      }
      try {
        const q = state.query ? `&q=${encodeURIComponent(state.query)}` : ''
        const data = await api(`/artifacts?limit=${next.panelLimit}${q}`)
        set({ rows: data.rows || [], total: (data.rows || []).length, source: data.source || '?', searchMode: data.search_mode || '?' })
      } catch (e) {
        set({ error: e.message })
      }
    },
    async refreshStats() {
      try {
        const data = await api('/stats')
        const s = (data && data.stats) || {}
        set({ total: s.total ?? state.total, source: s.available ? s.source || 'sqlite' : 'files' })
      } catch {
        /* stats 失败不影响列表 */
      }
    },
    async detail(id) {
      set({ loading: true, error: null })
      try {
        const meta = await api(`/artifacts/${encodeURIComponent(id)}`)
        let content = ''
        try {
          const body = await api(`/artifacts/${encodeURIComponent(id)}/content?max_chars=${FF_PREVIEW_CHARS}`)
          content = body.content || ''
        } catch (e) {
          content = `（正文读取失败：${e.message}）`
        }
        set({ loading: false, selected: { ...meta, content } })
      } catch (e) {
        set({ loading: false, error: e.message })
      }
    },
    async retry(id, t) {
      try {
        await api(`/artifacts/${encodeURIComponent(id)}/retry`, { method: 'POST' })
        set({ notice: t('panel.retryQueued'), selected: null })
      } catch (e) {
        set({ error: e.message })
      }
    },
    async remove(id, t) {
      try {
        await api(`/artifacts/${encodeURIComponent(id)}`, { method: 'DELETE' })
        set({ notice: t('panel.deleted'), selected: null })
        await api.load(state.query)
      } catch (e) {
        set({ error: e.message })
      }
    },
    clearSelection() {
      set({ selected: null })
    },
  }
}

const FF_STYLE = {
  root: { display: 'flex', flexDirection: 'column', gap: '8px', padding: '10px 12px', fontSize: '12px', color: 'var(--dsw-alias-label-primary, #111)', height: '100%', boxSizing: 'border-box', overflow: 'auto' },
  rootPage: { maxWidth: '960px', width: '100%', margin: '0 auto', padding: '18px 22px', gap: '12px', fontSize: '13px' },
  row: { display: 'flex', gap: '6px', alignItems: 'center' },
  input: { flex: '1 1 auto', minWidth: '0', padding: '5px 8px', fontSize: '12px', borderRadius: '6px', border: '1px solid var(--dsw-alias-border-l2, #d0d0d0)', background: 'var(--dsw-alias-bg-base, #fff)', color: 'inherit' },
  button: { padding: '5px 9px', fontSize: '12px', borderRadius: '6px', border: '1px solid var(--dsw-alias-border-l2, #d0d0d0)', background: 'var(--dsw-alias-interactive-bg-hover, rgba(127,127,127,.12))', color: 'inherit', cursor: 'pointer', whiteSpace: 'nowrap' },
  list: { display: 'flex', flexDirection: 'column', gap: '4px' },
  item: { textAlign: 'left', display: 'flex', flexDirection: 'column', gap: '2px', padding: '6px 8px', borderRadius: '6px', border: '1px solid transparent', background: 'var(--dsw-alias-interactive-bg-hover, rgba(127,127,127,.08))', color: 'inherit', cursor: 'pointer' },
  itemTitle: { fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  meta: { opacity: 0.65, fontSize: '11px' },
  detail: { border: '1px solid var(--dsw-alias-border-l2, #d0d0d0)', borderRadius: '8px', padding: '8px', display: 'flex', flexDirection: 'column', gap: '6px' },
  pre: { margin: 0, padding: '8px', maxHeight: '240px', overflow: 'auto', fontSize: '11px', lineHeight: 1.45, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'var(--dsw-alias-bg-base, #fff)', borderRadius: '6px' },
  badge: { fontSize: '10px', padding: '1px 5px', borderRadius: '999px', background: 'var(--dsw-alias-interactive-bg-hover, rgba(127,127,127,.18))' },
  notice: { color: 'var(--dsw-alias-label-secondary, #666)', fontSize: '11px' },
  error: { color: '#b3261e', fontSize: '11px' },
}

function bytesLabel(n) {
  if (n === null || n === undefined || n === '') return ''
  const v = Number(n) || 0
  if (v < 1024) return `${v}B`
  if (v < 1024 * 1024) return `${Math.round(v / 1024)}KB`
  return `${(v / 1024 / 1024).toFixed(1)}MB`
}

// 兼容 ISO 字符串、unix 秒与毫秒时间戳（库里存的是秒，接口归一后是 ISO，两种都不能崩）
function timeLabel(value) {
  try {
    if (value === null || value === undefined || value === '') return ''
    if (typeof value === 'number' && Number.isFinite(value)) {
      const d = new Date(value < 1e12 ? value * 1000 : value)
      return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString()
    }
    const d = new Date(value)
    if (Number.isNaN(d.getTime())) return String(value)
    return d.toLocaleString()
  } catch {
    return String(value)
  }
}

// 兜底归一：接口正常时已经是客户端形状，但库列名（source_name/source_bytes/created_at）
// 若因任何原因透出来，列表也不能显示成 id 或空白。
function rowOf(r) {
  if (!r || typeof r !== 'object') return {}
  const created = r.forged_at ?? r.created_at
  return {
    ...r,
    source: r.source || r.source_name || null,
    size_bytes: r.size_bytes ?? r.source_bytes ?? null,
    forged_at: created === undefined ? null : created,
  }
}

/** 组装面板组件；返回 React 组件函数。 */
function makePanel(React, store, t) {
  const h = React.createElement
  const useSync = (selector) => {
    const [, force] = React.useReducer((x) => x + 1, 0)
    React.useEffect(() => store.subscribe(force), [])
    return selector(store.getState())
  }

  return function FormatForgePanel(props) {
    const state = useSync((s) => s)
    const [draft, setDraft] = React.useState('')
    const isPage = Boolean(props && props.variant === 'page')
    const rootStyle = isPage ? { ...FF_STYLE.root, ...FF_STYLE.rootPage } : FF_STYLE.root

    React.useEffect(() => {
      void store.loadPrefs().then(() => store.load(''))
      void store.refreshStats()
    }, [])

    const submit = () => {
      void store.load(draft)
    }

    const rows = state.rows || []
    const head = h(
      'div',
      { style: FF_STYLE.row },
      h('input', {
        style: FF_STYLE.input,
        placeholder: t('panel.search'),
        value: draft,
        onChange: (e) => setDraft(e.target.value),
        onKeyDown: (e) => {
          if (e.key === 'Enter') submit()
        },
        'aria-label': t('panel.search'),
      }),
      h('button', { style: FF_STYLE.button, onClick: submit, type: 'button' }, t('panel.refresh')),
      h(
        'select',
        {
          style: FF_STYLE.button,
          value: String((state.prefs && state.prefs.panelLimit) || FF_PANEL_LIMIT),
          title: t('panel.limit'),
          'aria-label': t('panel.limit'),
          onChange: (e) => void store.setLimit(e.target.value),
        },
        [20, 50, 100, 200].map((n) => h('option', { key: n, value: String(n) }, String(n))),
      ),
    )

    const status = state.error
      ? h('div', { style: FF_STYLE.error }, `${t('panel.error')}: ${state.error}`)
      : state.notice
        ? h('div', { style: FF_STYLE.notice }, state.notice)
        : h('div', { style: FF_STYLE.notice }, t('panel.stats', { total: state.total, source: state.source }))

    const list = state.loading && rows.length === 0
      ? h('div', { style: FF_STYLE.notice }, t('panel.loading'))
      : rows.length === 0
        ? h('div', { style: FF_STYLE.notice }, state.query ? t('panel.emptyQuery') : t('panel.empty'))
        : h(
            'div',
            { style: FF_STYLE.list, role: 'list' },
            rows.map((rawRow) => {
              const r = rowOf(rawRow)
              return h(
                'button',
                {
                  key: r.id,
                  type: 'button',
                  role: 'listitem',
                  style: FF_STYLE.item,
                  onClick: () => void store.detail(r.id),
                },
                h('span', { style: FF_STYLE.itemTitle }, r.source || r.id),
                h(
                  'span',
                  { style: FF_STYLE.meta },
                  `${r.parser || '?'} · ${bytesLabel(r.size_bytes)} · ${timeLabel(r.forged_at)}` +
                    (r.status === 'failed' ? ' · ⚠failed' : '') +
                    (r.session_id ? ` · ${String(r.session_id).slice(0, 8)}` : ''),
                ),
              )
            }),
          )

    const sel = state.selected ? rowOf(state.selected) : null
    const detail = sel
      ? h(
          'div',
          { style: FF_STYLE.detail },
          h('div', { style: FF_STYLE.row }, h('strong', null, sel.source || sel.id), h('span', { style: FF_STYLE.badge }, sel.parser || '?')),
          h(
            'div',
            { style: FF_STYLE.meta },
            `${sel.id} · ${bytesLabel(sel.size_bytes)}` +
              (sel.confidence !== null && sel.confidence !== undefined ? ` · conf=${sel.confidence}` : ''),
          ),
          h('div', { style: FF_STYLE.row },
            h('button', {
              type: 'button',
              style: FF_STYLE.button,
              onClick: () => {
                const p = sel.md_path || sel.json_path || ''
                try {
                  void navigator.clipboard.writeText(p)
                } catch {
                  /* clipboard 不可用时忽略 */
                }
              },
            }, t('panel.copyPath')),
            h('button', { type: 'button', style: FF_STYLE.button, onClick: () => void store.retry(sel.id, t) }, t('panel.retry')),
            h('button', { type: 'button', style: FF_STYLE.button, onClick: () => void store.remove(sel.id, t) }, t('panel.delete')),
            h('button', { type: 'button', style: FF_STYLE.button, onClick: () => store.clearSelection() }, t('panel.close')),
          ),
          h('div', { style: FF_STYLE.meta }, t('panel.preview')),
          h('pre', { style: FF_STYLE.pre }, sel.content || ''),
        )
      : null

    return h('div', { style: rootStyle }, head, status, list, detail)
  }
}

/** 侧栏导航条目要的是**图标**（宿主 PanelRow 传 { size, active }）。内联 SVG，零依赖、跟随主题。 */
function makePanelIcon(React) {
  return function FormatForgeIcon(props) {
    const size = (props && props.size) || 18
    return React.createElement(
      'svg',
      {
        width: size,
        height: size,
        viewBox: '0 0 24 24',
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.7,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        'aria-hidden': 'true',
        focusable: 'false',
      },
      // 一个"收件箱 + 锻造火花"的极简字形：箱子 + 上方三点
      React.createElement('path', { d: 'M3 12.5 5 6h14l2 6.5V18a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 3 18z' }),
      React.createElement('path', { d: 'M3 12.5h5l1.2 2.2h5.6L16 12.5h5' }),
      React.createElement('path', { d: 'M12 3.2v2.4M8.6 4.4v1.2M15.4 4.4v1.2' }),
    )
  }
}

/**
 * 把面板挂到宿主右侧栏。由 client bundle 的 apply() 调用。
 * @param {object} ctx cordis 客户端根 ctx
 */
function activatePanel(ctx) {
  if (!ctx || typeof ctx.inject !== 'function') {
    panelLog('ctx.inject unavailable; panel disabled')
    return
  }
  ctx.inject(['slots'], (scope) => {
    let React = null
    try {
      React = require('react')
    } catch (e) {
      panelLog('react unavailable, panel stays off: ' + (e && e.message))
      return
    }
    if (!React || typeof React.createElement !== 'function') {
      panelLog('react shape unexpected; panel stays off')
      return
    }
    const get = (name) => {
      try {
        return scope && typeof scope.get === 'function' ? scope.get(name) : scope && scope[name]
      } catch {
        return null
      }
    }
    const slots = get('slots') || (scope && scope.slots)
    if (!slots || typeof slots.register !== 'function') {
      panelLog('slots service unavailable; panel stays off')
      return
    }
    const locale = get('locale')
    const tabs = get('sidebarRightTabs')
    const sidebar = get('sidebarRight')

    let lang = 'zh'
    try {
      if (locale && typeof locale.register === 'function') {
        ctx.effect(() => locale.register(FF_PANEL_NS, FF_DICT), 'ff-panel: dictionaries')
      }
      if (locale && typeof locale.get === 'function' && typeof locale.get() === 'string') lang = locale.get()
    } catch {
      /* locale 不可用就用默认 zh */
    }
    const t = (key, vars) => pickText(lang, key, vars)

    const store = makeStore()
    const Panel = makePanel(React, store, t)
    const PanelIcon = makePanelIcon(React)

    const Title = function FormatForgeTitle() {
      return React.createElement('span', { title: t('panel.title'), style: { fontWeight: 600 } }, t('panel.title'))
    }

    // 1) 侧栏导航条目（用户要的位置：`sidebar.panellist`，排在「自动化任务」下面）
    //    宿主 PanelRow 会把条目渲染成「图标 + 标题」，点击时调 selectPanel(id) 切到 main 插槽同 key 的页面。
    const iconSpec = { name: 'sidebar.panellist', id: FF_PANEL_ID, order: FF_PANEL_ORDER, label: () => t('panel.title') }
    const mainSpec = { name: 'main', key: FF_PANEL_ID }
    if (locale) {
      iconSpec.locale = FF_PANEL_NS
      mainSpec.locale = FF_PANEL_NS
    }
    try {
      ctx.effect(
        () =>
          slots.inject('sidebar.panellist', () =>
            slots.register(iconSpec, function FormatForgeNavIcon(props) {
              return PanelIcon(props)
            }),
          ),
        'ff-panel: sidebar entry',
      )
      ctx.effect(
        () => slots.inject('main', () => slots.register({ ...mainSpec, inject: () => ({ variant: 'page' }) }, Panel)),
        'ff-panel: main page',
      )
      panelLog(`registered sidebar.panellist entry (order=${FF_PANEL_ORDER}) + main page`)
    } catch (e) {
      panelLog('sidebar entry / main page registration failed: ' + (e && e.message))
    }

    // 2) 页签类型 + guide 入口（没有 sidebarRightTabs 时跳过：body 仍注册，等宿主自己开）
    if (tabs && typeof tabs.register === 'function') {
      try {
        ctx.effect(
          () =>
            tabs.register({
              id: FF_PANEL_ID,
              kind: FF_PANEL_KIND,
              priority: 'extension',
              title: () => t('panel.title'),
              guide: [{ id: 'inbox', kind: FF_PANEL_KIND, title: t('panel.guide'), description: t('panel.guideDesc') }],
            }),
          'ff-panel: tab type',
        )
      } catch (e) {
        panelLog('tab type registration failed: ' + (e && e.message))
      }
    } else {
      panelLog('sidebarRightTabs unavailable — guide entry skipped')
    }

    // 3) 右侧栏页签主体 + 标题（keyed 插槽：key 必须等于类型注册的 id）
    const bodySpec = { name: 'sidebar.right.pane.tab', key: FF_PANEL_ID }
    const titleSpec = { name: 'sidebar.right.pane.tab.title', key: FF_PANEL_ID }
    if (locale) {
      bodySpec.locale = FF_PANEL_NS
      titleSpec.locale = FF_PANEL_NS
    }
    try {
      ctx.effect(
        () => slots.inject('sidebar.right.pane.tab', () => slots.register({ ...bodySpec, inject: () => ({ variant: 'pane' }) }, Panel)),
        'ff-panel: body',
      )
      ctx.effect(
        () => slots.inject('sidebar.right.pane.tab.title', () => slots.register(titleSpec, Title)),
        'ff-panel: title',
      )
      panelLog('registered into sidebar.right.pane.tab (kind=' + FF_PANEL_KIND + ')')
    } catch (e) {
      // 插槽未声明/结构变化：静默降级，绝不影响拖拽模块
      panelLog('slot registration failed (host contract changed?): ' + (e && e.message))
    }

    // 4) 侧栏底部保留一个入口：右侧栏页签不是每个人都会展开
    if (sidebar && typeof sidebar.openTab === 'function') {
      try {
        ctx.effect(
          () =>
            slots.inject('sidebar.footer.action', () =>
              slots.register({ name: 'sidebar.footer.action', id: 'ff-panel-open' }, function FormatForgeOpen() {
                return React.createElement(
                  'button',
                  {
                    type: 'button',
                    title: t('panel.guideDesc'),
                    style: { ...FF_STYLE.button, width: '100%' },
                    onClick: () => sidebar.openTab(FF_PANEL_KIND),
                  },
                  t('panel.guide'),
                )
              }),
            ),
          'ff-panel: footer action',
        )
      } catch (e) {
        panelLog('footer action skipped: ' + (e && e.message))
      }
    }
  })
}
