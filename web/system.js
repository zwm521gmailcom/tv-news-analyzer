// ── system.js ─────────────────────────────────────────
// TV News 系统总览页面 — 数据驱动渲染 + inline 配置 Modal
// ⚠️ 维护：系统逻辑变更时同步更新 SYSTEM_LOGIC 数组
(function () {
  // ── 数据源（唯一维护点） ──
  const SYSTEM_LOGIC = {
    lastUpdated: '2026-08-18',
    auto: [
      { id: 'news-poll', name: '新闻轮询', freq: '60s/轮',
        desc: '每 60 秒调 TradingView 列表接口拉中英双语新闻',
        source: 'pipeline/scheduler.py',
        status: 'active' },
      { id: 'dual-lang', name: '双语并发抓取', freq: '每轮 1 次',
        desc: 'en + zh-Hans 并发请求（asyncio.gather）',
        source: 'core/fetcher.py:280',
        status: 'active' },
      { id: 'body-fetch', name: '正文后台抓取', freq: '每条新新闻 0.5s',
        desc: '入库后 create_task 后台抓详情（不阻塞主流程）',
        source: 'pipeline/orchestrator.py:43',
        status: 'active' },
      { id: 'ai-global', name: 'AI 全局叙事', freq: '整点',
        desc: '调 MiniMax M2.7 生成过去 24h 全局叙事',
        source: 'pipeline/global_narrative.py',
        status: 'partial' },
      { id: 'ai-region', name: 'AI 区域叙事', freq: '整点',
        desc: 'Ollama qwen2.5:7b 按区域生成一句话叙事',
        source: 'pipeline/ai_narrator.py',
        status: 'partial' },
      { id: 'ai-causal', name: 'AI 因果链', freq: '整点',
        desc: 'Ollama 每小时末生成事件因果链',
        source: 'pipeline/ai_narrator.py',
        status: 'partial' },
      { id: 'db-migrate', name: 'DB 自动迁移', freq: 'News 启动时',
        desc: 'init_db() 检查 schema + 自动加列（sector/country/corp_activity）',
        source: 'db/database.py',
        status: 'active',
        config_page: null  // schema 改动需要改代码，无配置页
      },
      { id: 'db-backup', name: 'DB 定期备份', freq: '每日（默认 03:00）',
        desc: 'SQLite 在线热备 + gzip 压缩 + 自动清理过期（默认保留 7 天）',
        source: 'web/server.py (_backup_scheduler_loop)',
        status: 'active',
        config_page: '/backup'  // 点击 ⚙️ 跳转到 /backup 配置页
      },
      { id: 'boot-backfill', name: '启动自动回填', freq: 'News 启动时',
        desc: '未回填正文 ≥50 条时自动后台补齐（1.0s/条）',
        source: 'run.py:85',
        status: 'active' },
      { id: 'html-auto-refresh', name: 'HTML 自动增量刷新', freq: '30s',
        desc: '增量拉 since=latestTs 的新条目，顶部追加',
        source: 'web/index.html (pollForNewItems)',
        status: 'active' },
      { id: 'html-clock', name: '客户端时钟', freq: '1s',
        desc: '顶栏时钟每秒更新（按 i18n locale 切换）',
        source: 'web/index.html (updateClock)',
        status: 'active' },
      { id: 'i18n-storage', name: 'i18n localStorage 持久化', freq: '切换时',
        desc: '用户语言/刷新模式选择持久化到 localStorage',
        source: 'web/i18n.js',
        status: 'active' },
      { id: 'cookie-sync', name: 'Cookie 自动同步', freq: 'News 启动时',
        desc: 'cookies.txt 有内容时同步到 cookies.json',
        source: 'core/cookie_manager.py',
        status: 'active' },
    ],
    semi: [
      { id: 'html-incremental', name: 'HTML 增量轮询', freq: '30s',
        desc: '用户切到"自动"模式时启用（基于 pollForNewItems）',
        source: 'web/index.html + web/shared-ui.js',
        status: 'active' },
      { id: 'html-manual', name: 'HTML 手动刷新', freq: '用户点击',
        desc: '切到"手动"模式后只点 ↻ 刷新按钮才重载（loadNews(true)）',
        source: 'web/index.html',
        status: 'active' },
      { id: 'modal', name: '弹窗打开', freq: '点新闻卡片',
        desc: '拉 /api/news_detail?id=... 加载完整正文',
        source: 'web/index.html (openModal)',
        status: 'active' },
      { id: 'filter-change', name: '过滤切换', freq: '点 chip',
        desc: '语言/市场 chip 切换立即重拉新闻（reset=true）',
        source: 'web/index.html (filter handler)',
        status: 'active' },
      { id: 'auto-fallback', name: '24h→7d 自动降级', freq: '拉取时',
        desc: '24h 内 0 条新闻时自动切到近 7 天',
        source: 'web/index.html (loadNews fallback)',
        status: 'active' },
    ],
    manual: [
      { id: 'service-ctrl', name: '启停服务', freq: '—',
        desc: './tvnews.sh start/stop/restart/status',
        source: 'tvnews.sh',
        status: 'manual' },
      { id: 'manual-backup', name: '手动立即备份', freq: '—',
        desc: '打开 /backup 页面点"立即备份"按钮（或 POST /api/backup/create）',
        source: 'web/backup.html + /api/backup/create',
        status: 'manual' },
      { id: 'manual-restore', name: '手动恢复备份', freq: '—',
        desc: '打开 /backup 页面点备份行的 ↻ 按钮（POST /api/backup/restore）',
        source: 'web/backup.html + /api/backup/restore',
        status: 'manual' },
      { id: 'manual-backfill', name: '手动回填正文', freq: '—',
        desc: 'python3 scripts/backfill_story_body.py --limit 1000 --delay 0.5（已部分被 boot-backfill 替代）',
        source: 'scripts/backfill_story_body.py',
        status: 'manual',
        config_page: '/config/backfill' },
      { id: 'manual-fields', name: '回填 market/sector/country', freq: '—',
        desc: 'python3 scripts/backfill_raw_fields.py --dry-run / --overwrite',
        source: 'scripts/backfill_raw_fields.py',
        status: 'manual' },
      { id: 'db-cleanup', name: '清理 AI 残留', freq: '—',
        desc: 'python3 scripts/db_cleanup.py（删 news_analysis / market_summaries / enable_* KV）',
        source: 'scripts/db_cleanup.py',
        status: 'manual' },
      { id: 'obsidian-sync', name: '同步到 Obsidian', freq: '—',
        desc: 'python3 scripts/sync_raw_to_obsidian.py（按需）',
        source: 'scripts/sync_raw_to_obsidian.py',
        status: 'manual' },
      { id: 'terminal-query', name: '终端查询', freq: '—',
        desc: 'python3 run.py --query --hours 24 --limit 20',
        source: 'run.py (run_query)',
        status: 'manual' },
      { id: 'single-fetch', name: '一次性抓取测试', freq: '—',
        desc: 'python3 run.py --once（调试）',
        source: 'run.py (run_monitor once=True)',
        status: 'manual' },
    ],
    missing: [
      { id: 'db-cleanup-auto', name: '30 天清理', freq: '—',
        desc: 'scripts/db_cleanup.py 没有自动调度（应每小时或每天清）',
        source: 'scripts/db_cleanup.py（无 cron）',
        status: 'missing' },
      { id: 'health-endpoint', name: '/api/health 健康检查', freq: '—',
        desc: '外部监控（uptime robot 等）无法知道项目是否正常',
        source: 'web/server.py（无）',
        status: 'missing' },
      { id: 'cookie-expiry', name: 'Cookie 过期检测', freq: '—',
        desc: 'Cookie 静默失效 → 抓不到 Pro 内容无感知',
        source: 'core/cookie_manager.py（无）',
        status: 'missing' },
      { id: 'ai-cache', name: 'AI 叙事 hourly cache', freq: '—',
        desc: '每整点重新生成浪费 API 费用，应加 24h 缓存',
        source: 'pipeline/global_narrative.py（无）',
        status: 'missing' },
    ],
  };

  // ── 渲染 ──
  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function statusBadge(status) {
    const t = (window.I18N && window.I18N.t.bind(window.I18N)) || ((k) => k);
    const labels = {
      active:  t('system.status.active'),
      partial: t('system.status.partial'),
      missing: t('system.status.missing'),
      manual:  t('system.status.manual'),
    };
    return `<span class="logic-status ${status}"><span class="status-dot ${status === 'active' ? 'pulse' : ''}"></span>${escapeHtml(labels[status] || status)}</span>`;
  }

  function configBtn(item) {
    const hasPage = !!item.config_page;
    const t = (k) => (window.I18N ? window.I18N.t(k) : k);
    const title = hasPage ? t('system.config.open') : t('system.config.empty');
    return `<button class="logic-config-btn" data-action="config" data-page="${escapeHtml(item.config_page || '')}" data-id="${escapeHtml(item.id)}" title="${escapeHtml(title)}" ${hasPage ? '' : 'disabled'}>⚙</button>`;
  }

  function renderItem(item) {
    return `
      <div class="logic-item" data-id="${escapeHtml(item.id)}">
        <div class="logic-name">${escapeHtml(item.name)}</div>
        <div class="logic-desc">${escapeHtml(item.desc)}</div>
        <div class="logic-source-wrap"><span class="logic-source">${escapeHtml(item.source)}</span></div>
        <div class="logic-freq">${escapeHtml(item.freq)}</div>
        <div class="logic-status-wrap">${statusBadge(item.status)}</div>
        ${configBtn(item)}
      </div>`;
  }

  function renderSection(key, containerId, countId) {
    const items = SYSTEM_LOGIC[key];
    const container = document.getElementById(containerId);
    const countEl = document.getElementById(countId);
    countEl.textContent = items.length;
    if (items.length === 0) {
      const t = (window.I18N && window.I18N.t.bind(window.I18N)) || ((k) => k);
      container.innerHTML = `<div class="empty-msg">${escapeHtml(t('system.empty'))}</div>`;
      return;
    }
    container.innerHTML = items.map(renderItem).join('');
  }

  function renderSummary() {
    const summary = document.getElementById('systemSummary');
    const t = (k) => (window.I18N ? window.I18N.t(k) : k);
    const items = [
      { icon: '🟢', num: SYSTEM_LOGIC.auto.length,    color: 'green',  label: t('system.summary.auto') },
      { icon: '🟡', num: SYSTEM_LOGIC.semi.length,    color: 'yellow', label: t('system.summary.semi') },
      { icon: '🔴', num: SYSTEM_LOGIC.manual.length,  color: 'red',    label: t('system.summary.manual') },
      { icon: '⚠️', num: SYSTEM_LOGIC.missing.length, color: 'purple', label: t('system.summary.missing') },
    ];
    summary.innerHTML = items.map((it) => `
      <div class="summary-card">
        <div class="summary-icon">${it.icon}</div>
        <div class="summary-num ${it.color}">${it.num}</div>
        <div class="summary-label">${escapeHtml(it.label)}</div>
      </div>`).join('');
  }

  function render() {
    document.getElementById('lastUpdated').textContent = SYSTEM_LOGIC.lastUpdated;
    renderSummary();
    renderSection('auto',    'autoList',    'autoCount');
    renderSection('semi',    'semiList',    'semiCount');
    renderSection('manual',  'manualList',  'manualCount');
    renderSection('missing', 'missingList', 'missingCount');
  }

  // ── 事件委托：⚙️ 按钮点击 → 跳转到配置页 ──
  function bindEvents() {
    document.body.addEventListener('click', (e) => {
      const cfgBtn = e.target.closest('button[data-action="config"]');
      if (cfgBtn && !cfgBtn.disabled) {
        const page = cfgBtn.dataset.page;
        if (page) window.location.href = page;
        return;
      }
    });
  }

  // ── 启动 ──
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { bindEvents(); render(); });
  } else {
    bindEvents();
    render();
  }

  // i18n 切换时重渲染
  document.addEventListener('i18n:changed', render);
})();
