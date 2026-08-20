// ── history.js ──────────────────────────────────────────
// TV News 历史洞察页：时间线 + 连续性 diff
(function () {
  const $ = (id) => document.getElementById(id);
  const t = (k) => (window.I18N ? window.I18N.t(k) : k);

  let currentPeriod = '';  // '' = all
  let comparePeriod = 'daily';
  let historyCache = [];   // 当前过滤后的历史

  // ── 工具 ──
  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function timeAgo(unixSec) {
    if (!unixSec) return '—';
    const lang = (window.I18N && window.I18N.getLang) ? window.I18N.getLang() : 'zh-Hans';
    const s = Math.max(0, Math.floor(Date.now() / 1000 - unixSec));
    if (s < 60) return lang === 'en' ? `${s}s ago` : `${s} 秒前`;
    const m = Math.floor(s / 60);
    if (m < 60) return lang === 'en' ? `${m}m ago` : `${m} 分钟前`;
    const h = Math.floor(m / 60);
    if (h < 24) return lang === 'en' ? `${h}h ago` : `${h} 小时前`;
    const d = Math.floor(h / 24);
    return lang === 'en' ? `${d}d ago` : `${d} 天前`;
  }

  function fmtDate(unixSec) {
    if (!unixSec) return '—';
    const d = new Date(unixSec * 1000);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
  }

  function showToast(msg) {
    const el = $('toast');
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 3000);
  }

  // ── 拉数据 ──
  async function loadHistory() {
    const url = currentPeriod
      ? `/api/insights/history?period=${currentPeriod}&limit=50`
      : `/api/insights/history?limit=50`;
    try {
      const r = await fetch(url);
      const d = await r.json();
      if (d.ok) {
        historyCache = d.history;
        renderTimeline();
        $('filterStats').textContent = `共 ${d.count} 条`;
      } else {
        $('timeline').innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-text">${escapeHtml(d.error || '加载失败')}</div></div>`;
      }
    } catch (e) {
      $('timeline').innerHTML = `<div class="empty-state"><div class="empty-icon">❌</div><div class="empty-text">网络错误: ${escapeHtml(e.message)}</div></div>`;
    }
  }

  async function loadCompare() {
    try {
      const r = await fetch(`/api/insights/compare?period=${comparePeriod}`);
      const d = await r.json();
      const card = $('compareCard');
      if (d.ok && d.prior) {
        card.style.display = 'block';
        $('compareTitle').textContent = `🔄 连续性对比：${comparePeriod}`;
        const deltas = d.deltas;
        $('compareDeltas').innerHTML = `
          <span>📊 趋势变化：<strong>${escapeHtml(deltas.trend_change)}</strong></span>
          <span>📈 新闻数：<strong>${deltas.news_count_delta >= 0 ? '+' : ''}${deltas.news_count_delta}</strong></span>
          <span>🆕 新增主题：<strong>${deltas.new_count}</strong></span>
          <span>🔁 延续主题：<strong>${deltas.continued_count}</strong></span>
          <span>✅ 已解决：<strong>${deltas.resolved_count}</strong></span>
          <span>⏱️ 上期距今：<strong>${timeAgo(d.prior.generated_at)}</strong></span>
        `;
      } else {
        // 至少 1 条历史，但没法对比
        card.style.display = 'block';
        $('compareTitle').textContent = `🔄 连续性对比：${comparePeriod}`;
        $('compareDeltas').innerHTML = `<span style="color:var(--text-muted);">📌 当前只有 1 条历史。等下次 04:00 自动跑（或到洞察页手动生成）后即可对比。</span>`;
      }
    } catch (e) {
      $('compareCard').style.display = 'none';
    }
  }

  // ── 渲染时间线 ──
  function renderTimeline() {
    const tl = $('timeline');
    if (!historyCache.length) {
      tl.innerHTML = `<div class="empty-state"><div class="empty-icon">📜</div><div class="empty-text">还没有历史记录。等 04:00 调度器跑一次，或在 <a href="/timeline" style="color:var(--purple);">洞察页</a> 手动生成。</div></div>`;
      return;
    }

    const periodLabel = {daily: '每日', '3day': '3 日', weekly: '每周', monthly: '每月'};
    const trendIcon = {up: '📈', down: '📉', stable: '➡️', mixed: '〰️'};

    let html = '';
    for (const item of historyCache) {
      const newCount = (item.new_themes || []).length;
      const contCount = (item.continued_themes || []).length;
      const resCount = (item.resolved_themes || []).length;
      const trend = item.trend || 'stable';

      html += `<div class="timeline-item ${item.period}" data-id="${item.id}">`;
      html += `  <div class="timeline-dot"></div>`;
      html += `  <div class="timeline-card" data-action="toggle">`;
      // header
      html += `    <div class="timeline-header">`;
      html += `      <span class="timeline-period ${item.period}">${periodLabel[item.period] || item.period}</span>`;
      html += `      <span class="timeline-date">${fmtDate(item.generated_at)}</span>`;
      html += `      <span class="timeline-count">📰 ${item.news_count} 条</span>`;
      html += `      <span class="timeline-trend ${trend}" title="整体趋势">${trendIcon[trend] || '•'} ${trend}</span>`;
      // deltas
      if (newCount + contCount + resCount > 0) {
        html += `      <div class="timeline-deltas">`;
        if (newCount)     html += `        <span class="delta-chip new">🆕${newCount}</span>`;
        if (contCount)    html += `        <span class="delta-chip continued">🔁${contCount}</span>`;
        if (resCount)     html += `        <span class="delta-chip resolved">✓${resCount}</span>`;
        html += `      </div>`;
      }
      html += `    </div>`;
      // summary
      html += `    <div class="timeline-summary collapsed">${escapeHtml(item.summary || '（无总结）')}</div>`;
      // detail (loaded on demand via /api/insights/period or via direct query)
      html += `    <div class="timeline-detail" data-detail-for="${item.id}"><div class="loading">加载详情…</div></div>`;
      html += `  </div>`;
      html += `</div>`;
    }
    tl.innerHTML = html;
  }

  // ── 点击展开详情 ──
  async function toggleDetail(card) {
    const item = card.closest('.timeline-item');
    const id = item.dataset.id;
    const detail = item.querySelector('.timeline-detail');
    const isExpanded = item.classList.contains('expanded');

    if (isExpanded) {
      item.classList.remove('expanded');
      return;
    }

    // 已加载过就不重拉
    if (detail.dataset.loaded === '1') {
      item.classList.add('expanded');
      return;
    }

    detail.innerHTML = '<div class="loading">加载详情…</div>';
    item.classList.add('expanded');

    try {
      // 拉完整行
      const r = await fetch(`/api/insights/history?period=${item.classList.contains('daily') ? 'daily' : ''}&limit=50`);
      const d = await r.json();
      const full = (d.history || []).find(x => x.id == id);
      if (!full) {
        detail.innerHTML = '<div class="loading">未找到详情</div>';
        return;
      }
      // 还需要 ai_themes / sectors 完整数据，从 /api/insights/period 拉
      const period = Array.from(item.classList).find(c => ['daily','3day','weekly','monthly'].includes(c));
      const r2 = await fetch(`/api/insights/period?period=${period}`);
      const latest = await r2.json();
      const aiThemes = (latest.ai_themes || []);
      const bull = (latest.bullish_sectors || []);
      const bear = (latest.bearish_sectors || []);

      // 这条 history 行的 details 也得用同 period 的 AI 输出
      // 因为 history 行只存了 new/continued/resolved 列表，没存完整 themes
      // 这里用 latest 的 themes 列表 + history 的 status 分类
      // （如果这条不是 latest，会不准确，但能展示大致结构）
      const newSet = new Set(full.new_themes || []);
      const contSet = new Set(full.continued_themes || []);
      const resSet = new Set(full.resolved_themes || []);

      const themesHtml = aiThemes.map(t => {
        const title = t.title || '';
        let status = t.status || '';
        if (!status) {
          if (newSet.has(title)) status = 'new';
          else if (contSet.has(title)) status = 'continued';
          else if (resSet.has(title)) status = 'resolved';
        }
        const tag = {new: '🆕', continued: '🔁', resolved: '✓'}[status] || '•';
        return `<div class="detail-item">${tag} <strong>${escapeHtml(title)}</strong>${t.detail ? ' — ' + escapeHtml(t.detail) : ''}</div>`;
      }).join('') || '<div class="detail-item">（无主题）</div>';

      const renderSectors = (list, kind) => list.map(s => `
        <div class="sector-row">
          <span class="sector-name">${escapeHtml(s.sector || '?')}</span>
          <div class="sector-bar"><div class="sector-bar-fill ${kind}" style="width:${Math.min(100, s.confidence || 0)}%"></div></div>
          <span class="sector-conf">${s.confidence ?? 0}</span>
        </div>
      `).join('') || '<div class="detail-item">（无）</div>';

      detail.innerHTML = `
        <div class="detail-grid">
          <div class="detail-block">
            <div class="detail-label">核心主题 (${aiThemes.length})</div>
            ${themesHtml}
          </div>
          <div class="detail-block">
            <div class="detail-label">看多板块 (${bull.length})</div>
            <div class="detail-sectors">${renderSectors(bull, 'bullish')}</div>
          </div>
          <div class="detail-block">
            <div class="detail-label">看空板块 (${bear.length})</div>
            <div class="detail-sectors">${renderSectors(bear, 'bearish')}</div>
          </div>
          <div class="detail-block">
            <div class="detail-label">摘要</div>
            <div class="detail-item" style="white-space:pre-wrap;line-height:1.7;">${escapeHtml(full.summary || '（无）')}</div>
          </div>
        </div>
      `;
      detail.dataset.loaded = '1';
    } catch (e) {
      detail.innerHTML = `<div class="loading">❌ ${escapeHtml(e.message)}</div>`;
    }
  }

  // ── 事件 ──
  function bindEvents() {
    // 周期 filter
    $('periodFilter').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-period]');
      if (!btn) return;
      document.querySelectorAll('#periodFilter .chip').forEach(c => c.classList.toggle('active', c === btn));
      currentPeriod = btn.dataset.period;
      loadHistory();
    });

    // 对比 period tabs
    $('comparePeriodTabs').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-cmp-period]');
      if (!btn) return;
      document.querySelectorAll('#comparePeriodTabs .chip').forEach(c => c.classList.toggle('active', c === btn));
      comparePeriod = btn.dataset.cmpPeriod;
      loadCompare();
    });

    // 时间线点击展开
    $('timeline').addEventListener('click', (e) => {
      const card = e.target.closest('[data-action="toggle"]');
      if (card) toggleDetail(card);
    });
  }

  // ── 时钟 ──
  function updateClock() {
    $('clock').textContent = new Date().toLocaleTimeString('zh-CN', {hour12: false});
  }

  // ── 启动 ──
  function init() {
    bindEvents();
    updateClock();
    setInterval(updateClock, 1000);
    loadHistory();
    loadCompare();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // i18n 切换时重渲染（时间轴标签要换语言）
  document.addEventListener('i18n:changed', () => {
    loadHistory();
    loadCompare();
  });
})();
