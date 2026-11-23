// 行李带停用改送：值班页面（试算 / 重算 / 确认 / 各带峰值与积压）
let rerouteData = null;

async function rerouteApi(path, options = {}) {
  const r = await fetch('/api/reroute' + path, {
    ...options,
    headers: {'Content-Type': 'application/json', Authorization: state.token ? `Bearer ${state.token}` : ''},
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || '请求失败');
  return d;
}

const planStatus = {
  trial: ['试算中', 'needs-confirmation'],
  superseded: ['已作废', 'failed'],
  confirmed: ['已确认', 'ready'],
};

function slotTime(iso) {
  return new Date(iso).toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'});
}

function miniBars(slots) {
  const max = Math.max(...slots.map(s => s.bags), 1);
  const peakVal = Math.max(...slots.map(s => s.bags));
  return `<div class="mini-bars">${slots.map(s =>
    `<i class="${s.bags === peakVal ? 'peak' : ''}" style="height:${Math.max(6, s.bags / max * 100)}%" title="${slotTime(s.at)} · ${s.bags} 件"></i>`).join('')}</div>`;
}

function beltCards() {
  return `<div class="reroute-belt-grid">${rerouteData.overview.belts.map(belt => {
    const over = belt.baseline_peak != null && belt.baseline_peak > belt.capacity_bags;
    const backlog = belt.active_reroute ? '见改送方案明细' : '—';
    return `<div class="reroute-belt ${belt.is_backup ? 'backup' : ''} ${belt.active ? '' : 'disabled'}">
      <h4><span class="mono">${belt.belt_code}</span>
        ${belt.is_backup ? '<span class="reroute-tag backup-flag">备带</span>' : '<span class="reroute-tag">主带</span>'}
        ${belt.active_reroute ? '<span class="reroute-tag live">改送生效中</span>' : ''}
      </h4>
      <div class="belt-meta">${belt.belt_name} · ${belt.terminal}</div>
      <div class="belt-peak">
        <div><strong>${belt.baseline_peak ?? '—'}</strong><small>基线预测峰值 件 / 档</small></div>
        <span class="cap-pill ${over ? 'over' : ''}">容量 ${belt.capacity_bags}${over ? ' · 超容量' : ''}</span>
      </div>
      ${state.user.role === 'supervisor' ? `<form class="belt-cap-form" data-belt="${belt.belt_code}">
        <input name="capacity_bags" type="number" min="1" step="0.5" value="${belt.capacity_bags}" aria-label="${belt.belt_code} 容量">
        <button class="small-btn dark" type="submit">调整容量</button>
      </form>` : ''}
      ${belt.baseline_slots.length ? `<details class="baseline-detail">
        <summary>逐波次按带预测（${belt.baseline_slots.length} 个波次）· 积压：${backlog}</summary>
        ${belt.baseline_slots.map(w => `<div class="wave-label">${w.wave_code} · 峰值 ${w.peak} 件</div>${miniBars(w.slots)}`).join('')}
      </details>` : '<div class="belt-meta" style="margin-top:12px">计数点不足，暂无法按带预测</div>'}
    </div>`;
  }).join('')}</div>`;
}

function trialForm() {
  if (state.user.role === 'viewer') return '';
  const belts = rerouteData.overview.belts;
  const mainBelts = belts.filter(b => !b.is_backup).map(b => `<option value="${b.belt_code}">${b.belt_code} · ${b.belt_name}</option>`).join('');
  const backupBelts = belts.filter(b => b.is_backup).map(b => `<option value="${b.belt_code}">${b.belt_code} · 容量 ${b.capacity_bags}</option>`).join('');
  const defaultStop = new Date(Date.now() + 30 * 60000);
  const local = new Date(defaultStop.getTime() - defaultStop.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  return `<form id="reroute-trial-form" class="trial-form">
    <label>停用行李带<select name="disabled_belt_code" required>${mainBelts}</select></label>
    <label>改送备带<select name="backup_belt_code" required>${backupBelts}</select></label>
    <label>停带时刻<input name="stop_at" type="datetime-local" value="${local}" required></label>
    <label>回归窗口（点）<input name="window_size" type="number" min="4" max="24" value="8" required></label>
    <div style="grid-column:1/-1"></div>
    <button class="primary" type="submit">开始试算</button>
  </form>`;
}

function backupSlotTable(plan) {
  const slots = plan.trial_result.backup_slots || [];
  if (!slots.length) return '';
  return `<div class="plan-section-title">备带 ${plan.backup_belt_code} 逐档峰值与排队积压（原有负荷 + 转入量）</div>
  <div class="slot-scroll"><table class="slot-table"><thead><tr>
    <th>时间档</th><th>原有负荷</th><th>转入件数</th><th>上档积压</th><th>本档峰值负荷</th><th>容量</th><th>本档消化</th><th>结转到下档</th>
  </tr></thead><tbody>${slots.map(s => `<tr>
    <td>${slotTime(s.at)}</td>
    <td class="num">${s.own_inflow}</td>
    <td class="num">${s.transfer_inflow}</td>
    <td class="num queue-num">${s.carried_queue}</td>
    <td class="num ${s.peak_load > s.capacity ? 'over-num' : ''}">${s.peak_load}</td>
    <td class="num">${s.capacity}</td>
    <td class="num">${s.processed}</td>
    <td class="num queue-num">${s.backlog}</td>
  </tr>`).join('')}</tbody></table></div>`;
}

function disabledSlotTable(plan) {
  const groups = plan.trial_result.disabled_slots || [];
  const rows = groups.flatMap(g => g.slots.map(s => ({...s, code: g.code})));
  if (!rows.length) return '';
  return `<div class="plan-section-title">停用带 ${plan.disabled_belt_code} 停带前保留档（停带时刻起的件数已全部改投）</div>
  <div class="slot-scroll"><table class="slot-table"><thead><tr>
    <th>波次</th><th>时间档</th><th>本档件数</th><th>容量</th><th>峰值负荷</th><th>积压</th>
  </tr></thead><tbody>${rows.map(s => `<tr>
    <td><span class="mono">${s.code}</span></td><td>${slotTime(s.at)}</td>
    <td class="num">${s.inflow}</td><td class="num">${s.capacity}</td>
    <td class="num ${s.peak_load > s.capacity ? 'over-num' : ''}">${s.peak_load}</td>
    <td class="num queue-num">${s.backlog}</td>
  </tr>`).join('')}</tbody></table></div>`;
}

function planCard(plan) {
  const [label, cls] = planStatus[plan.status] || [plan.status, 'draft'];
  const trial = plan.trial_result || {};
  const waves = trial.affected_waves || [];
  const canWrite = state.user.role !== 'viewer';
  const isManager = state.user.role === 'supervisor';
  return `<div class="reroute-plan ${plan.status}">
    <div class="plan-head">
      <div><b class="mono">#${plan.id} · ${plan.disabled_belt_code} → ${plan.backup_belt_code}</b>
        <div class="plan-sub">停带时刻 ${slotTime(plan.stop_at)} · 窗口 ${plan.window_size} 点 ·
          转入合计 <b>${trial.transfer_total_bags ?? '—'}</b> 件 ·
          备带峰值 <b>${trial.backup_peak_load ?? '—'}</b> 件 ·
          末次积压 <b>${trial.backup_final_backlog ?? '—'}</b> 件</div></div>
      <div class="plan-actions">
        <span class="badge ${cls}">${label}</span>
        ${plan.status === 'trial' && canWrite ? `<button class="small-btn" data-reroute-recalc="${plan.id}">重新试算</button>` : ''}
        ${plan.status === 'trial' && isManager ? `<button class="small-btn dark" data-reroute-confirm="${plan.id}">确认改送</button>` : ''}
      </div>
    </div>
    ${plan.status === 'superseded' ? `<div class="stale-banner">旧试算已作废：${plan.stale_reason || '基础数据变化'}。请重新试算后再确认。</div>` : ''}
    ${plan.stale && plan.status === 'trial' ? '<div class="stale-banner">试算依据已变化（补报计数 / 容量调整 / 其他方案确认），当前试算等待重算。</div>' : ''}
    <div class="wave-chip-row">${waves.map(w =>
      `<span class="wave-chip">${w.code} · 改投 <span class="moved">${w.transferred_slots.reduce((a, s) => a + s.bags, 0)}</span> 件 / 保留 ${w.kept_slots.reduce((a, s) => a + s.bags, 0)} 件</span>`).join('')}</div>
    ${backupSlotTable(plan)}
    ${disabledSlotTable(plan)}
    ${plan.status === 'confirmed' ? `<div class="plan-section-title">已于 ${slotTime(plan.confirmed_at)} 确认，受影响波次已全部换用新预测（forecast: ${(plan.confirmed_forecast_ids || []).join(', ')}）</div>` : ''}
  </div>`;
}

export function renderReroutePage(host) {
  if (!rerouteData) {
    host.innerHTML = '<div class="empty">正在加载行李带与试算数据…</div>';
    return;
  }
  host.innerHTML = `
    <div class="toolbar"><div><small class="eyebrow">BELT REROUTE / DUTY DESK</small>
      <p class="toolbar-note">行李带临时停用后，按带预测停带时刻起的件数并改投备带；多波次共用备带时合并原有负荷，超容量余量排队到下一档。补报计数、调容量或确认其他方案会使旧试算作废。</p></div></div>
    ${trialForm()}
    <small class="eyebrow">BELT PEAKS</small><h3 style="margin:6px 0 14px">各行李带峰值与积压</h3>
    ${beltCards()}
    <small class="eyebrow">REROUTE PLANS</small><h3 style="margin:6px 0 14px">改送试算与确认</h3>
    ${rerouteData.plans.length ? rerouteData.plans.map(planCard).join('') : '<div class="empty">暂无改送试算，先在上方发起一次试算。</div>'}`;
  bindReroutePage(host);
}

function bindReroutePage(host) {
  host.querySelector('#reroute-trial-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const o = Object.fromEntries(new FormData(event.target));
    o.window_size = +o.window_size;
    try {
      await rerouteApi('/trials', {method: 'POST', body: JSON.stringify(o)});
      await loadReroute();
    } catch (error) { alert(error.message); }
  });
  host.querySelectorAll('[data-reroute-recalc]').forEach(btn => {
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await rerouteApi(`/plans/${btn.dataset.rerouteRecalc}/recalc`, {method: 'POST'});
        await loadReroute();
      } catch (error) { alert(error.message); btn.disabled = false; }
    };
  });
  host.querySelectorAll('[data-reroute-confirm]').forEach(btn => {
    btn.onclick = () => confirmReroute(+btn.dataset.rerouteConfirm);
  });
  host.querySelectorAll('.belt-cap-form').forEach(form => {
    form.onsubmit = async event => {
      event.preventDefault();
      const code = form.dataset.belt;
      const capacity_bags = +new FormData(form).get('capacity_bags');
      if (!(capacity_bags > 0)) { alert('容量必须大于 0'); return; }
      try {
        await rerouteApi(`/belts/${encodeURIComponent(code)}/capacity`, {
          method: 'PATCH', body: JSON.stringify({capacity_bags}),
        });
        await loadReroute();
      } catch (error) { alert(error.message); }
    };
  });
}

function confirmReroute(planId) {
  const d = modal('确认行李带改送方案', `<form id="modal-form">
    <p class="modal-warning">确认后所有受影响波次将一起换用改送后的新预测；若期间发生补报计数、容量调整或其他方案确认，本试算已作废，需要重算。</p>
    <label>值班经理确认说明<textarea name="note" required minlength="3">已核对备带峰值与排队余量，同意按试算结果改送。</textarea></label>
    <button class="primary wide">确认并让受影响波次换用新预测</button></form>`);
  d.querySelector('form').onsubmit = async event => {
    event.preventDefault();
    try {
      await rerouteApi(`/plans/${planId}/confirm`, {
        method: 'POST', body: JSON.stringify({note: new FormData(event.target).get('note')}),
      });
      d.remove();
      await loadReroute();
      await load();
    } catch (error) { alert(error.message); }
  };
}

export async function loadReroute() {
  const [overview, plans] = await Promise.all([rerouteApi('/overview'), rerouteApi('/plans')]);
  rerouteData = {overview, plans};
  if (state.page === 'reroute') renderPage();
}

export function resetReroute() {
  rerouteData = null;
}
