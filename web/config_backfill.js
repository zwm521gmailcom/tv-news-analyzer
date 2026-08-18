// ── config_backfill.js ─────────────────────────────────
// TV News 正文回填配置页面 — 实时状态 + 日志
(function () {
  const $ = (id) => document.getElementById(id);
  const t = (k) => (window.I18N ? window.I18N.t(k) : k);

  function showToast(msg, type = '') {
    const el = $('toast');
    el.textContent = msg;
    el.className = `toast show ${type}`;
    setTimeout(() => el.classList.remove('show'), 3000);
  }

  function statusPill(status) {
    const labels = {
      idle:    t('back.status.idle'),
      running: t('back.status.running'),
      done:    t('back.status.done'),
      error:   t('back.status.error'),
      stopped: t('back.status.stopped'),
    };
    return `<span class="status-pill ${status}"><span class="status-dot ${status === 'running' ? 'pulse' : ''}"></span>${labels[status] || status}</span>`;
  }

  async function refresh() {
    try {
      const r = await fetch('/api/backfill/preview');
      const d = await r.json();
      $('pendingCount').textContent = d.pending.toLocaleString();
      const state = d.state || {};
      $('statusPill').innerHTML = statusPill(state.status || 'idle');
      $('startedAt').textContent = state.started_at ? state.started_at.replace('T', ' ').slice(0, 19) : '—';
      $('endedAt').textContent = state.ended_at ? state.ended_at.replace('T', ' ').slice(0, 19) : '—';
      // 运行中 → 隐藏 Run 按钮显示 Stop；否则反之
      if (state.status === 'running') {
        $('btnRun').style.display = 'none';
        $('btnStop').style.display = 'inline-flex';
        $('hint').textContent = `PID ${state.pid} · limit=${state.limit} delay=${state.delay}s`;
      } else {
        $('btnRun').style.display = 'inline-flex';
        $('btnStop').style.display = 'none';
        if (state.status === 'done') {
          const before = state.pending_before || 0;
          const after = state.pending_after || 0;
          const processed = before - after;
          $('hint').textContent = `本轮处理 ${processed} 条（${before} → ${after}）`;
        } else {
          $('hint').textContent = '';
        }
      }
    } catch (e) {
      console.error('preview failed', e);
    }
    try {
      const r2 = await fetch('/api/backfill/status');
      const s = await r2.json();
      const logLines = s.log_tail || [];
      const logBox = $('logBox');
      if (logLines.length === 0) {
        logBox.innerHTML = `<div class="log-empty">${t('back.log.empty')}</div>`;
      } else {
        logBox.textContent = logLines.join('');
      }
      $('logSize').textContent = `${logLines.length} / 30 行`;
    } catch (e) {
      console.error('status failed', e);
    }
  }

  async function doRun() {
    const limit = parseInt($('paramLimit').value, 10);
    const delay = parseFloat($('paramDelay').value);
    if (isNaN(limit) || limit < 1 || limit > 10000) {
      showToast(t('back.err.limit'), 'error');
      return;
    }
    if (isNaN(delay) || delay < 0.1 || delay > 10) {
      showToast(t('back.err.delay'), 'error');
      return;
    }
    if (!confirm(t('back.confirm.run').replace('{n}', limit).replace('{d}', delay.toFixed(1)))) {
      return;
    }
    try {
      const r = await fetch('/api/backfill/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit, delay }),
      });
      const d = await r.json();
      if (d.ok) {
        showToast(t('back.toast.started').replace('{pid}', d.pid), 'success');
        await refresh();
      } else {
        showToast(`❌ ${d.error}`, 'error');
      }
    } catch (e) {
      showToast(`❌ ${e}`, 'error');
    }
  }

  async function doStop() {
    if (!confirm(t('back.confirm.stop'))) return;
    try {
      const r = await fetch('/api/backfill/stop', { method: 'POST' });
      const d = await r.json();
      if (d.ok) showToast(t('back.toast.stopped'), 'success');
      else showToast(`❌ ${d.error}`, 'error');
      await refresh();
    } catch (e) {
      showToast(`❌ ${e}`, 'error');
    }
  }

  function bindEvents() {
    $('btnRun').addEventListener('click', doRun);
    $('btnStop').addEventListener('click', doStop);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { bindEvents(); refresh(); });
  } else {
    bindEvents();
    refresh();
  }
  setInterval(refresh, 3000);  // 3s 轮询
})();
