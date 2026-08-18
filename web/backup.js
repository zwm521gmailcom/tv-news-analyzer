// ── backup.js ─────────────────────────────────────────
// TV News 数据备份页面 — 列表 / 创建 / 恢复 / 删除 / 调度
(function () {
  const $ = (id) => document.getElementById(id);

  function t(path) {
    if (window.I18N) return window.I18N.t(path);
    return path;
  }

  function showToast(msg, type = '') {
    const el = $('toast');
    el.textContent = msg;
    el.className = `toast show ${type}`;
    setTimeout(() => el.classList.remove('show'), 3000);
  }

  // ── 加载 paths & 状态 ──
  async function loadInfo() {
    try {
      const r = await fetch('/api/backup/info');
      const d = await r.json();
      $('infoDbPath').textContent = d.db_path;
      if (d.db_exists) {
        $('infoDbSize').textContent = `${d.db_size_mb} MB · ${d.db_row_count.toLocaleString()} ${t('backup.unit.rows')}`;
      } else {
        $('infoDbSize').textContent = '⚠ ' + t('backup.status.not_found');
      }
      $('infoBackupDir').textContent = d.backup_dir;
      if (d.last_backup) {
        $('infoLastBackup').textContent = `${d.last_backup.file} (${d.last_backup.size_mb} MB · ${d.last_backup.created_at.replace('T', ' ').slice(0, 19)})`;
      } else {
        $('infoLastBackup').textContent = '— ' + t('backup.status.no_backup');
      }
      const sched = d.schedule;
      $('infoSchedule').textContent = `${sched.enabled ? '✅' : '⏸'} ${String(sched.hour).padStart(2, '0')}:00 · ${sched.last_run ? sched.last_run.replace('T', ' ').slice(0, 19) : '—'}`;
    } catch (e) {
      showToast('加载失败: ' + e, 'error');
    }
  }

  // ── 加载 schedule ──
  async function loadSchedule() {
    try {
      const r = await fetch('/api/backup/schedule');
      const d = await r.json();
      $('scheduleEnabled').textContent = d.enabled ? '✅ ' + t('backup.status.on') : '⏸ ' + t('backup.status.off');
      $('scheduleHour').textContent = `${String(d.hour).padStart(2, '0')}:00`;
      $('scheduleLastRun').textContent = d.last_run ? d.last_run.replace('T', ' ').slice(0, 19) : '—';
      $('scheduleNextRun').textContent = d.next_run ? d.next_run.replace('T', ' ').slice(0, 19) : '—';
      $('scheduleStatus').textContent = `${d.backup_dir}`;
      // 同步 form
      $('formEnabled').checked = d.enabled;
      $('formHour').value = d.hour;
    } catch (e) {
      showToast('加载失败: ' + e, 'error');
    }
  }

  // ── 加载备份历史 ──
  async function loadHistory() {
    try {
      const r = await fetch('/api/backup/list');
      const d = await r.json();
      renderHistory(d.backups);
      $('historyMeta').textContent = `${d.count} 个 · ${d.total_size_mb} MB · ${d.backup_dir}`;
    } catch (e) {
      showToast('加载失败: ' + e, 'error');
    }
  }

  function renderHistory(backups) {
    const list = $('backupList');
    if (!backups || backups.length === 0) {
      list.innerHTML = `<div class="empty-msg">${t('backup.empty')}</div>`;
      return;
    }
    list.innerHTML = backups.map((b) => {
      const ageClass = b.age_days < 1 ? 'fresh' : b.age_days < 7 ? 'fresh' : b.age_days < 30 ? 'warn' : 'old';
      const ageLabel = b.age_days < 1 ? t('backup.age.today') : `${b.age_days} ${t('backup.unit.days')}`;
      return `
        <div class="backup-item" data-name="${b.name}">
          <div class="backup-name">${b.name}</div>
          <div class="backup-size">${b.size_mb} MB</div>
          <div class="backup-time">${b.created_at.replace('T', ' ').slice(0, 19)}</div>
          <div class="backup-age ${ageClass}">${ageLabel}</div>
          <div class="btn-row">
            <button class="btn secondary" data-action="restore" data-name="${b.name}">↻</button>
            <button class="btn danger" data-action="delete" data-name="${b.name}">✕</button>
          </div>
        </div>`;
    }).join('');
  }

  // ── 立即备份 ──
  async function doBackup() {
    const btn = $('btnBackupNow');
    btn.disabled = true;
    btn.textContent = '⏳ ...';
    try {
      const r = await fetch('/api/backup/create', { method: 'POST' });
      const d = await r.json();
      if (d.ok) {
        showToast(`✅ ${d.file} (${d.size_mb} MB)`, 'success');
        $('manualMeta').textContent = `最后: ${d.created_at.replace('T', ' ').slice(0, 19)} · ${d.size_mb} MB`;
        await loadHistory();
        await loadSchedule();
      } else {
        showToast('❌ ' + d.error, 'error');
      }
    } catch (e) {
      showToast('❌ ' + e, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = t('backup.btn.backup_now');
    }
  }

  // ── 保存 schedule ──
  async function saveSchedule() {
    const data = {
      enabled: $('formEnabled').checked,
      hour: parseInt($('formHour').value, 10),
    };
    if (isNaN(data.hour) || data.hour < 0 || data.hour > 23) {
      showToast('小时必须是 0-23', 'error');
      return;
    }
    try {
      const r = await fetch('/api/backup/schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const d = await r.json();
      if (d.ok) {
        showToast('✅ 已保存', 'success');
        await loadSchedule();
      } else {
        showToast('❌ ' + d.error, 'error');
      }
    } catch (e) {
      showToast('❌ ' + e, 'error');
    }
  }

  // ── 确认对话框 ──
  let pendingAction = null;
  function showConfirm(action) {
    pendingAction = action;
    $('confirmOverlay').classList.add('open');
  }
  function hideConfirm() {
    pendingAction = null;
    $('confirmOverlay').classList.remove('open');
  }

  async function doRestore(filename) {
    try {
      const r = await fetch('/api/backup/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      });
      const d = await r.json();
      if (d.ok) {
        showToast(`✅ 已恢复 ${d.restored_from}`, 'success');
        $('manualMeta').textContent = `已恢复，pre_restore: ${d.pre_restore_backup}`;
        await loadHistory();
      } else {
        showToast('❌ ' + d.error, 'error');
      }
    } catch (e) {
      showToast('❌ ' + e, 'error');
    }
  }

  async function doDelete(filename) {
    try {
      const r = await fetch(`/api/backup/${encodeURIComponent(filename)}`, { method: 'DELETE' });
      const d = await r.json();
      if (d.ok) {
        showToast(`✅ ${filename} 已删除`, 'success');
        await loadHistory();
        await loadSchedule();
      } else {
        showToast('❌ ' + d.error, 'error');
      }
    } catch (e) {
      showToast('❌ ' + e, 'error');
    }
  }

  // ── 事件绑定 ──
  function bindEvents() {
    $('btnBackupNow').addEventListener('click', doBackup);
    $('btnSaveSchedule').addEventListener('click', saveSchedule);
    $('btnRefresh').addEventListener('click', loadHistory);
    $('btnCancel').addEventListener('click', hideConfirm);
    $('btnConfirm').addEventListener('click', async () => {
      if (pendingAction) {
        const { action, filename } = pendingAction;
        hideConfirm();
        if (action === 'restore') await doRestore(filename);
        else if (action === 'delete') await doDelete(filename);
      }
    });
    // 事件代理：restore / delete 按钮
    $('backupList').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-action]');
      if (!btn) return;
      const action = btn.dataset.action;
      const filename = btn.dataset.name;
      if (action === 'restore') showConfirm({ action, filename });
      else if (action === 'delete') showConfirm({ action, filename });
    });
  }

  // ── 启动 ──
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { bindEvents(); loadInfo(); loadSchedule(); loadHistory(); });
  } else {
    bindEvents();
    loadInfo();
    loadSchedule();
    loadHistory();
  }

  // i18n 切换后重渲染
  document.addEventListener('i18n:changed', () => {
    loadInfo();
    loadSchedule();
    loadHistory();
  });

  // 30s 自动刷新历史（让用户看到自动备份新增的）
  setInterval(() => {
    loadHistory();
    loadSchedule();
    loadInfo();
  }, 30000);
})();
