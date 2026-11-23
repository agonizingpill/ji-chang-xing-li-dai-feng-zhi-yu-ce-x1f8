const states = {confirmed: '已确认', draft: '草稿', needs_confirmation: '待确认', over_capacity: '超额', completed: '已结束'};
const time = value => new Date(value).toLocaleString('zh-CN', {hour12: false, dateStyle: 'short', timeStyle: 'short'});

export function renderShiftTimeline(container, wave) {
  container.replaceChildren();
  const hint = document.createElement('p');
  hint.textContent = wave.peak_at ? `预测峰值时点 ${time(wave.peak_at)}` : '该波次暂无有效峰值时点';
  container.append(hint);
  if (!wave.shifts.length) {
    const empty = document.createElement('p');
    empty.textContent = '当前波次没有已登记班次';
    container.append(empty);
    return;
  }
  const peak = wave.peak_at ? Date.parse(wave.peak_at) : null;
  const entries = [...wave.shifts].sort((left, right) => Date.parse(left.start) - Date.parse(right.start));
  const list = document.createElement('ol');
  for (const shift of entries) {
    const item = document.createElement('li');
    const overlaps = peak !== null && Date.parse(shift.start) <= peak && peak < Date.parse(shift.end);
    const effective = overlaps && shift.state === 'confirmed';
    const label = effective ? '计入峰值保障' : overlaps ? '覆盖时点，班次未确认' : '峰值不在班次期间';
    item.textContent = `${shift.code} · ${time(shift.start)} – ${time(shift.end)} · ${states[shift.state] || shift.state} · ${shift.bags} 件 · ${label}`;
    list.append(item);
  }
  container.append(list);
}
