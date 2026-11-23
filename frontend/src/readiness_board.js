import {renderShiftTimeline} from './schedule_timeline.js';

export async function renderReadinessBoard(host, request) {
  const panel = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = '波次发布与保障看板';
  const content = document.createElement('section');
  panel.append(summary, content);
  host.replaceChildren(panel);
  let lastRequest = 0;
  panel.addEventListener('toggle', async () => {
    if (!panel.open) return;
    const sequence = ++lastRequest;
    content.textContent = '正在读取波次与排班…';
    try {
      const waves = await request('/readiness');
      if (!panel.open || sequence !== lastRequest) return;
      content.replaceChildren();
      const selector = document.createElement('select');
      selector.setAttribute('aria-label', '查看波次班次');
      const table = document.createElement('table');
      const labels = table.createTHead().insertRow();
      for (const heading of ['到达波次', '航站楼', '峰值 件', '保障 件', '发布核对']) {
        const label = document.createElement('th');
        label.scope = 'col'; label.textContent = heading; labels.append(label);
      }
      const body = table.createTBody();
      for (const wave of waves) {
        const row = body.insertRow();
        for (const value of [wave.code, wave.terminal, wave.peak ?? '—', wave.coverage, wave.state]) row.insertCell().textContent = value;
        selector.add(new Option(`${wave.code} 班次`, wave.code));
      }
      if (!waves.length) { content.textContent = '当前没有开放波次'; return; }
      const timeline = document.createElement('section');
      const show = () => renderShiftTimeline(timeline, waves.find(wave => wave.code === selector.value));
      selector.addEventListener('change', show);
      content.append(table, selector, timeline);
      show();
    } catch (error) {
      if (sequence === lastRequest) content.textContent = error.message;
    }
  });
}
