// ── i18n ────────────────────────────────────────────────
// 双 UI 字典（zh-Hans / en）+ 切换 + 持久化 + 应用到 DOM
// 依赖：必须在 shared-ui.js 之前加载
(function () {
  const DICT = {
    'zh-Hans': {
      nav:    { home: '看板', analytics: '分析', timeline: '洞察', map: '地图', graph: '关系图', graph3d: '3D 图谱', system: '系统', backup: '备份', history: '历史' },
      live:   'LIVE',
      refresh: '↻ 刷新',
      refresh_mode: { auto: '自动', manual: '手动', switch_to: '切换为', mode_label: '刷新模式' },
      runtime: { loading: '状态加载中', anon: '匿名模式', cookie: 'Cookie模式' },
      stats:  { total: '全部', db_total: 'DB总数', market_24h_total: '24h合计', en: '英文', zh: '中文', crypto: '加密', stock: '股票', forex: '外汇', futures: '期货', index: '指数', economic: '宏观', unknown: '未分类' },
      filter: {
        lang: '语言', market: '市场', all: '全部',
        en_label: '英文 EN', zh_label: '中文 ZH',
        crypto: '₿ 加密', stock: '📈 股票', forex: '💱 外汇', futures: '🛢 期货', index: '📊 指数',
        search_ph: '搜索新闻...',
        hours: { '1': '近1小时', '3': '近3小时', '6': '近6小时', '24': '近24小时', '48': '近48小时', '168': '近7天' }
      },
      section: { latest: '最新资讯', loading: '加载中...', load_more: '加载更多' },
      card:    { flash: '⚡ 快讯', zh: '中文', en: 'EN', source: '来源', empty: '暂无符合条件的新闻',
                 time: { sec: '秒前', min: '分钟前' } },
      modal:   { loading: '加载中...', loading_body: '正在加载正文...', error: '加载失败，请稍后重试',
                 empty: '暂无正文内容（源站未返回正文或摘要）',
                 open_source: '打开原文', open_page: '打开新闻页' },
      toast:   { new: '🔥 有新消息，已自动更新', fallback: '最近24小时没有数据，已自动切换到近7天' },
      total:   '共 {n} 条，显示 {shown} 条',
      page_title: 'TV News — Crypto Dashboard',
      system: {
        title: '系统总览',
        subtitle: 'TV News 自动化 & 手动逻辑清单',
        last_updated: '最后更新于',
        maintain_tip: '系统更新时请同步修改',
        empty: '（暂无）',
        section: { auto: '🟢 后台自动运行', semi: '🟡 半自动 / 触发式', manual: '🔴 需要手动运行', missing: '⚠️ 缺失的自动化' },
        summary: { auto: '自动', semi: '半自动', manual: '手动', missing: '缺失' },
        status:  { active: '运行中', partial: '部分', missing: '缺失', manual: '手动' },
        footer:  {
          note: '📝 维护说明：每条逻辑带 source 字段指向代码位置。系统改动时，请同步更新 web/system.js 里的 SYSTEM_LOGIC 数组。',
          tip:  '💡 提示：本页数据由 system.js 单一数据源驱动，新增/修改/删除逻辑只需改该数组。',
        },
        config: {
          title:    '参数配置',
          empty:    '暂无可配置',
          loading:  '加载中…',
          load_failed: '加载失败',
          save:     '保存',
          cancel:   '取消',
          saved:    '已保存',
          save_failed: '保存失败',
          open:     '打开配置页',
        },
      },
      // 顶层 ai.* 命名空间 — system 页和 config/backfill 页共用
      ai: {
        section_title:    '🤖 AI 洞察管理',
        section_subtitle: '模型 / Key / 4 周期洞察运行状态',
        loading:          '加载中…',
        load_failed:      '加载失败',
        field: {
          provider:     'Provider',
          model:        '当前模型',
          base_url:     'API 地址',
          api_key:      'API Key',
          api_key_set:  '✅ 已配置',
          api_key_missing: '❌ 未配置',
          api_key_source: '配置位置',
        },
        period: {
          title:     '多周期洞察',
          daily:     '每日',
          '3day':    '3 日',
          weekly:    '每周',
          monthly:   '每月',
          last_run:  '上次生成',
          never:     '从未生成',
          count:     '条新闻',
        },
        last_global: '最近全局叙事',
        never_global: '从未生成',
        note_title:  '⚠️ 修改提示',
        note_text:   'API Key 配置在 .env 文件（变量名 MINIMAX_API_KEY），修改后必须重启 News/Web 服务才能生效。',
      },
      backup: {
        title: '数据备份 & 恢复',
        subtitle: 'SQLite 在线热备 + gzip 压缩 + 定期任务 + 一键恢复',
        section: { schedule: '定期任务', manual: '立即备份', history: '备份历史' },
        field:   { enabled: '启用', hour: '运行时间', last_run: '上次运行', next_run: '下次运行', db_path: '数据库路径', db_size: 'DB 大小 / 行数', backup_dir: '备份目录', last_backup: '最近一次备份', schedule: '定期任务', retention: '备份保留策略' },
        form:    { enable_schedule: '启用定期备份', hour: '每日运行时间（0-23）' },
        unit:    { rows: '条' },
        status:  { on: '已启用', off: '已停用', not_found: 'DB 不存在', no_backup: '暂无备份' },
        retention: { never_delete: '永不自动删除（手动管理）' },
        paths:   { note: '所有路径与策略只读显示' },
        btn:     { backup_now: '立即备份', save_schedule: '保存设置', refresh: '刷新列表', cancel: '取消', confirm: '确认恢复' },
        manual:  { desc: '点下方按钮立即创建一个压缩备份（约几秒）。在线热备不锁表，不影响 News 抓取。' },
        status:  { on: '已启用', off: '已停用' },
        unit:    { days: '天' },
        age:     { today: '今天' },
        empty:   '暂无备份',
        back_to_system: '← 返回系统',
        confirm: {
          title: '⚠️ 确认恢复',
          text:  '恢复将 覆盖当前数据库。恢复前系统会自动备份当前 DB（命名为 pre_restore_*）以防出错。确认要恢复吗？',
        },
      },
      back: {
        title:    '正文回填设置',
        subtitle: '批量回填 story_body：对已入库但无正文的新闻补抓详情接口',
        section:  { status: '当前状态', params: '运行参数', log: '实时日志' },
        field:    {
          pending:  '未回填条数',
          status:   '任务状态',
          started:  '开始时间',
          ended:    '结束时间',
          limit:    '最多回填条数',
          limit_help: '默认 500，最大 10000',
          delay:    '每条间隔秒数',
          delay_help: '建议 0.5-1.0 防 API 限速',
        },
        status:   { idle: '空闲', running: '运行中', done: '完成', error: '错误', stopped: '已停止' },
        btn:      { run: '▶ 开始回填', stop: '■ 停止' },
        log:      { empty: '暂无日志' },
        toast:    { started: '✅ 已启动 PID {pid}', stopped: '✅ 已停止' },
        confirm:  {
          run:   '确定要启动回填吗？\n\n最多 {n} 条，每条间隔 {d} 秒。',
          stop:  '确定要停止当前回填任务吗？\n已处理的会保留，未处理的不变。',
        },
        err:      {
          limit: 'limit 必须在 1-10000',
          delay: 'delay 必须在 0.1-10 秒',
        },
        back_to_system: '← 返回系统',
      }
    },
    'en': {
      nav:    { home: 'Dashboard', analytics: 'Analytics', timeline: 'Insights', map: 'Map', graph: 'Graph', graph3d: '3D Graph', system: 'System', backup: 'Backup', history: 'History' },
      live:   'LIVE',
      refresh: '↻ Refresh',
      refresh_mode: { auto: 'Auto', manual: 'Manual', switch_to: 'Switch to', mode_label: 'Refresh mode' },
      runtime: { loading: 'Loading…', anon: 'Anonymous', cookie: 'Cookie' },
      stats:  { total: 'Total', db_total: 'DB Total', market_24h_total: '24h sum', en: 'EN', zh: 'CN', crypto: 'Crypto', stock: 'Stocks', forex: 'Forex', futures: 'Futures', index: 'Index', economic: 'Econ', unknown: 'Unknown' },
      filter: {
        lang: 'Lang', market: 'Market', all: 'All',
        en_label: 'English EN', zh_label: '中文 ZH',
        crypto: '₿ Crypto', stock: '📈 Stocks', forex: '💱 Forex', futures: '🛢 Futures', index: '📊 Index',
        search_ph: 'Search news…',
        hours: { '1': 'Last 1h', '3': 'Last 3h', '6': 'Last 6h', '24': 'Last 24h', '48': 'Last 48h', '168': 'Last 7d' }
      },
      section: { latest: 'Latest News', loading: 'Loading…', load_more: 'Load more' },
      card:    { flash: '⚡ Flash', zh: 'CN', en: 'EN', source: 'Source', empty: 'No matching news',
                 time: { sec: 's ago', min: 'm ago' } },
      modal:   { loading: 'Loading…', loading_body: 'Loading article…', error: 'Failed, please retry',
                 empty: 'No body content',
                 open_source: 'Open source', open_page: 'Open page' },
      toast:   { new: '🔥 New updates', fallback: 'No data in 24h, expanded to 7d' },
      total:   '{shown} of {n} shown',
      page_title: 'TV News — Crypto Dashboard',
      system: {
        title: 'System Overview',
        subtitle: 'TV News automation & manual logic inventory',
        last_updated: 'Last updated',
        maintain_tip: 'Sync this file when system changes',
        empty: '(none)',
        section: { auto: '🟢 Background automation', semi: '🟡 Semi-automatic / triggered', manual: '🔴 Manual', missing: '⚠️ Missing automation' },
        summary: { auto: 'Auto', semi: 'Semi', manual: 'Manual', missing: 'Missing' },
        status:  { active: 'Running', partial: 'Partial', missing: 'Missing', manual: 'Manual' },
        footer:  {
          note: '📝 Maintenance: each entry has a `source` field pointing to the code location. When system logic changes, update SYSTEM_LOGIC in web/system.js accordingly.',
          tip:  '💡 Tip: this page is data-driven by web/system.js — add/change/remove logic by editing the single data source.',
        },
        config: {
          title:    'Configure',
          empty:    'Not configurable',
          loading:  'Loading…',
          load_failed: 'Load failed',
          save:     'Save',
          cancel:   'Cancel',
          saved:    'Saved',
          save_failed: 'Save failed',
          open:     'Open config page',
        },
      },
      // 顶层 ai.* 命名空间 — system 页和 config/backfill 页共用
      ai: {
        section_title:    '🤖 AI Insights Management',
        section_subtitle: 'Model / Key / 4-period insight runtime status',
        loading:          'Loading…',
        load_failed:      'Load failed',
        field: {
          provider:     'Provider',
          model:        'Active model',
          base_url:     'API endpoint',
          api_key:      'API Key',
          api_key_set:  '✅ Configured',
          api_key_missing: '❌ Missing',
          api_key_source: 'Storage location',
        },
        period: {
          title:     'Multi-period insights',
          daily:     'Daily',
          '3day':    '3-day',
          weekly:    'Weekly',
          monthly:   'Monthly',
          last_run:  'Last generated',
          never:     'Never generated',
          count:     'news',
        },
        last_global: 'Latest global narrative',
        never_global: 'Never generated',
        note_title:  '⚠️ Modification note',
        note_text:   'API Key is stored in .env (MINIMAX_API_KEY). After editing, you must restart the News/Web service to apply.',
      },
      backup: {
        title: 'Backup & Restore',
        subtitle: 'SQLite hot backup + gzip compression + scheduled tasks + one-click restore',
        section: { schedule: 'Schedule', manual: 'Backup now', history: 'Backup history' },
        field:   { enabled: 'Enabled', hour: 'Run hour', last_run: 'Last run', next_run: 'Next run', db_path: 'DB path', db_size: 'DB size / rows', backup_dir: 'Backup dir', last_backup: 'Latest backup', schedule: 'Schedule', retention: 'Retention' },
        form:    { enable_schedule: 'Enable scheduled backup', hour: 'Daily run hour (0-23)' },
        unit:    { rows: 'rows' },
        status:  { on: 'on', off: 'off', not_found: 'DB not found', no_backup: 'no backup yet' },
        retention: { never_delete: 'Never auto-delete (manual only)' },
        paths:   { note: 'All paths & policy are read-only here' },
        btn:     { backup_now: 'Backup now', save_schedule: 'Save settings', refresh: 'Refresh', cancel: 'Cancel', confirm: 'Confirm restore' },
        manual:  { desc: 'Click below to create a compressed backup now (a few seconds). Online hot backup doesn\'t lock the table.' },
        status:  { on: 'Enabled', off: 'Disabled' },
        unit:    { days: 'days' },
        age:     { today: 'today' },
        empty:   'No backups yet',
        back_to_system: '← Back to System',
        confirm: {
          title: '⚠️ Confirm restore',
          text:  'Restore will overwrite the current database. The system will auto-backup the current DB (named pre_restore_*) first. Confirm restore?',
        },
      },
      back: {
        title:    'Backfill Settings',
        subtitle: 'Bulk backfill story_body: fetch article body for news that already in DB',
        section:  { status: 'Status', params: 'Parameters', log: 'Live log' },
        field:    {
          pending:  'Pending count',
          status:   'Task status',
          started:  'Started at',
          ended:    'Ended at',
          limit:    'Max backfill count',
          limit_help: 'Default 500, max 10000',
          delay:    'Delay per item (s)',
          delay_help: '0.5-1.0 recommended to avoid rate limit',
        },
        status:   { idle: 'Idle', running: 'Running', done: 'Done', error: 'Error', stopped: 'Stopped' },
        btn:      { run: '▶ Run', stop: '■ Stop' },
        log:      { empty: 'No logs yet' },
        toast:    { started: '✅ Started PID {pid}', stopped: '✅ Stopped' },
        confirm:  {
          run:   'Start backfill?\n\nMax {n} items, {d}s delay.',
          stop:  'Stop current backfill task?\nProcessed items stay, others remain pending.',
        },
        err:      {
          limit: 'limit must be 1-10000',
          delay: 'delay must be 0.1-10 s',
        },
        back_to_system: '← Back to System',
      }
    }
  };

  const STORAGE_KEY = 'tvnews.lang';
  let current = (function () {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved && DICT[saved]) return saved;
    } catch (e) {}
    return 'zh-Hans';
  })();

  function t(path) {
    const parts = path.split('.');
    let v = DICT[current];
    for (const p of parts) v = v?.[p];
    return v != null ? v : path;
  }

  function setLang(lang) {
    if (!DICT[lang]) return;
    current = lang;
    try { localStorage.setItem(STORAGE_KEY, lang); } catch (e) {}
    document.documentElement.lang = lang;
    document.title = t('page_title');
    applyAll();
  }

  function getLang() { return current; }

  function applyAll() {
    // data-i18n="nav.home"  → element.textContent
    document.querySelectorAll('[data-i18n]').forEach((el) => {
      const key = el.getAttribute('data-i18n');
      const val = t(key);
      if (val != null) el.textContent = val;
    });
    // data-i18n-placeholder="filter.search_ph"
    document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
      el.setAttribute('placeholder', t(el.getAttribute('data-i18n-placeholder')));
    });
    // data-i18n-title="..."  → element.title
    document.querySelectorAll('[data-i18n-title]').forEach((el) => {
      el.setAttribute('title', t(el.getAttribute('data-i18n-title')));
    });
    // 触发自定义事件，让 index.html 重新渲染动态内容
    document.dispatchEvent(new CustomEvent('i18n:changed', { detail: { lang: current } }));
  }

  // 首次设置 <html lang>
  try { document.documentElement.lang = current; } catch (e) {}

  window.I18N = { t, setLang, getLang, applyAll, DICT };
})();
