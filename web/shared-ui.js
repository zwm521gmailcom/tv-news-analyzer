// ── 自适应加载 i18n.js（处理只引入 shared-ui.js 没引入 i18n.js 的页面）──
// 同步 XHR + Function 执行（同源，OK）。如果当前页面已经引入 i18n.js，此步跳过。
if (typeof window.I18N === 'undefined') {
  try {
    const xhr = new XMLHttpRequest();
    xhr.open('GET', '/static/i18n.js', false);  // 同步
    xhr.send();
    if (xhr.status === 200) {
      (new Function(xhr.responseText))();
    }
  } catch (e) {
    console.warn('[shared-ui] auto-load i18n.js failed:', e);
  }
}

(function () {
  // ── 依赖 I18N（自加载后 i18n.js 已就绪）──
  const i18n = {
    t: (path) => (window.I18N ? window.I18N.t(path) : ''),
  };

  function navLabel(key) {
    return i18n.t(`nav.${key}`);
  }

  const NAV_ITEMS = [
    { href: '/',       key: 'home' },
    { href: '/analytics', key: 'analytics' },
    { href: '/timeline',  key: 'timeline' },
    { href: '/graph',     key: 'graph' },
    { href: '/graph3d',   key: 'graph3d' },
    { href: '/system',  key: 'system' },
    { href: '/history', key: 'history' },
  ];

  const RUNTIME_ENDPOINT = '/api/runtime';

  function normalizePath(path) {
    if (!path) return '/';
    const clean = path.replace(/\/+$/, '');
    return clean || '/';
  }

  function isActive(href, currentPath) {
    const current = normalizePath(currentPath);
    const target = normalizePath(href);
    if (target === '/') {
      return current === '/';
    }
    return current === target || current.startsWith(`${target}/`);
  }

  function createNavLink(item, active) {
    const link = document.createElement('a');
    link.href = item.href;
    link.className = `nav-link${active ? ' active' : ''}`;
    link.textContent = navLabel(item.key);
    link.dataset.navKey = item.key;
    return link;
  }

  function refreshNavLabels() {
    document.querySelectorAll('.site-nav [data-nav-key]').forEach((link) => {
      const key = link.dataset.navKey;
      link.textContent = navLabel(key);
    });
  }

  function createLangSwitcher() {
    const wrap = document.createElement('div');
    wrap.className = 'lang-switcher';
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Language');

    const langs = [
      { code: 'zh-Hans', label: '中' },
      { code: 'en',      label: 'EN' },
    ];
    langs.forEach((l) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'lang-btn';
      btn.dataset.lang = l.code;
      btn.textContent = l.label;
      btn.setAttribute('aria-pressed', 'false');
      btn.addEventListener('click', () => {
        if (window.I18N) window.I18N.setLang(l.code);
      });
      wrap.appendChild(btn);
    });
    return wrap;
  }

  function refreshLangSwitcher() {
    const cur = window.I18N ? window.I18N.getLang() : 'zh-Hans';
    document.querySelectorAll('.lang-btn').forEach((btn) => {
      const active = btn.dataset.lang === cur;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function createRefreshModeSwitcher() {
    const wrap = document.createElement('div');
    wrap.className = 'mode-switcher';
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Refresh mode');

    const modes = [
      { code: 'auto',   i18nKey: 'refresh_mode.auto' },
      { code: 'manual', i18nKey: 'refresh_mode.manual' },
    ];
    modes.forEach((m) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'mode-btn';
      btn.dataset.mode = m.code;
      btn.textContent = i18n.t(m.i18nKey);  // 直接设 textContent（仿 createNavLink 模式）
      btn.setAttribute('aria-pressed', 'false');
      btn.addEventListener('click', () => {
        // 持久化 + 立即同步 active 状态 + 派发事件
        try { localStorage.setItem('tvnews.refresh', m.code); } catch (e) {}
        document.querySelectorAll('.mode-btn').forEach((b) => {
          const active = b.dataset.mode === m.code;
          b.classList.toggle('active', active);
          b.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        document.dispatchEvent(new CustomEvent('refresh:mode-changed', { detail: { mode: m.code } }));
      });
      wrap.appendChild(btn);
    });
    return wrap;
  }

  function refreshModeSwitcher() {
    const cur = (function () {
      try { return localStorage.getItem('tvnews.refresh') || 'auto'; } catch (e) { return 'auto'; }
    })();
    document.querySelectorAll('.mode-btn').forEach((btn) => {
      const active = btn.dataset.mode === cur;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function refreshModeLabels() {
    document.querySelectorAll('.mode-btn').forEach((btn) => {
      const code = btn.dataset.mode;
      if (code) btn.textContent = i18n.t(`refresh_mode.${code}`);
    });
  }

  function ensureNavStrip(activePath) {
    const topbar = document.querySelector('.topbar');
    if (!topbar) return null;

    const current = document.querySelector('.site-nav');
    if (current) current.remove();

    const nav = document.createElement('nav');
    nav.className = 'site-nav';
    nav.setAttribute('aria-label', '主导航');

    const left = document.createElement('div');
    left.className = 'site-nav-left';

    const links = document.createElement('div');
    links.className = 'nav-links shared-nav-links';
    NAV_ITEMS.forEach((item) => {
      links.appendChild(createNavLink(item, isActive(item.href, activePath)));
    });
    left.appendChild(links);

    const right = document.createElement('div');
    right.className = 'site-nav-right';

    const modeSwitcher = createRefreshModeSwitcher();
    right.appendChild(modeSwitcher);

    const langSwitcher = createLangSwitcher();
    right.appendChild(langSwitcher);

    const badge = document.createElement('div');
    badge.className = 'runtime-badge runtime-loading';
    badge.dataset.runtimeBadge = '1';
    badge.innerHTML = `<span class="runtime-dot"></span><span class="runtime-label">${i18n.t('runtime.loading')}</span>`;
    right.appendChild(badge);

    nav.appendChild(left);
    nav.appendChild(right);
    topbar.insertAdjacentElement('afterend', nav);

    refreshLangSwitcher();
    refreshModeSwitcher();
    // 触发首次 mode 应用（index.html 监听后启动/停止轮询）
    document.dispatchEvent(new CustomEvent('refresh:mode-changed', {
      detail: { mode: (function(){ try { return localStorage.getItem('tvnews.refresh') || 'auto'; } catch(e){ return 'auto'; } })() }
    }));
    return nav;
  }

  function updateRuntimeBadge(payload) {
    const badge = document.querySelector('[data-runtime-badge="1"]');
    if (!badge) return;

    const anonymous = !!payload?.anonymous_mode;
    badge.classList.toggle('anonymous', anonymous);
    badge.classList.toggle('cookie', !anonymous);
    badge.classList.remove('runtime-loading');

    const label = badge.querySelector('.runtime-label');
    if (label) {
      label.textContent = anonymous ? i18n.t('runtime.anon') : i18n.t('runtime.cookie');
    }

    badge.title = anonymous
      ? `匿名访问 · ${payload?.cookie_source || 'none'}`
      : `Cookie 访问 · ${payload?.cookie_source || 'file'} · ${payload?.cookie_count || 0} 项`;
  }

  async function loadRuntime() {
    try {
      const resp = await fetch(RUNTIME_ENDPOINT, { cache: 'no-store' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      updateRuntimeBadge(await resp.json());
    } catch (err) {
      const badge = document.querySelector('[data-runtime-badge="1"]');
      if (!badge) return;
      badge.classList.remove('runtime-loading', 'cookie');
      badge.classList.add('anonymous');
      badge.title = '运行态获取失败，默认显示匿名模式';
      const label = badge.querySelector('.runtime-label');
      if (label) {
        label.textContent = i18n.t('runtime.anon');
      }
    }
  }

  function initSharedUI() {
    document.body.classList.add('has-site-nav');
    ensureNavStrip(window.location.pathname);
    loadRuntime();

    // 监听 i18n 切换：刷新 nav 文案 + runtime badge 文案 + mode 切换器文案
    document.addEventListener('i18n:changed', () => {
      refreshNavLabels();
      refreshLangSwitcher();
      refreshModeLabels();
      refreshModeSwitcher();
      // runtime badge 已经在服务端拿到过 payload，重渲文字（保持状态）
      const badge = document.querySelector('[data-runtime-badge="1"]');
      if (badge && !badge.classList.contains('runtime-loading')) {
        const isAnon = badge.classList.contains('anonymous');
        const label = badge.querySelector('.runtime-label');
        if (label) label.textContent = isAnon ? i18n.t('runtime.anon') : i18n.t('runtime.cookie');
      }
    });

    // 兜底：监听 refresh:mode-changed 同步 active 状态
    document.addEventListener('refresh:mode-changed', () => {
      refreshModeSwitcher();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSharedUI);
  } else {
    initSharedUI();
  }
})();
