"""行李带停用改送的试算引擎（仅依赖标准库，保证可独立验证）。

口径：
- 按 (波次, 行李带) 独立做 STL 风格季节分解 + 滚动窗口线性回归，
  外推未来 HORIZON 个时间档（默认每档 SLOT_MINUTES 分钟，共 4 档）。
- 停用带在停带时刻之前的档保留原负荷，停带时刻起的整档流量改投备带。
- 备带负荷 = 备带自身原有预测 + 各波次转入量；单档超过容量的余量作为积压
  结转到下一档（先消化积压、再处理新到件）。
- 每个时间档都输出峰值、容量、积压，便于值班页面逐带查看。
"""
from __future__ import annotations

from datetime import timedelta

SLOT_MINUTES = 10
HORIZON = 4
MIN_POINTS = 8


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def _variance(values):
    if not values:
        return 0.0
    avg = _mean(values)
    return sum((v - avg) ** 2 for v in values) / len(values)


def _linear_fit(xs, ys):
    """一元线性回归，返回 (slope, intercept)。"""
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    avg_x = _mean(xs)
    avg_y = _mean(ys)
    denom = sum((x - avg_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0, avg_y
    slope = sum((x - avg_x) * (y - avg_y) for x, y in zip(xs, ys)) / denom
    return slope, avg_y - slope * avg_x


def forecast_belt_series(points, window_size=8):
    """对单条行李带的计数点做 STL 风格分解并外推未来 4 档。

    points: [{'counted_at': aware datetime, 'bag_count': number}, ...]
    返回 {'slots': [{'at': datetime, 'bags': float}], 'peak': float, ...}
    """
    rows = sorted(points, key=lambda row: row['counted_at'])
    values = [float(row['bag_count']) for row in rows]
    if len(values) < max(window_size, MIN_POINTS):
        raise ValueError(f'该行李带至少需要 {max(window_size, MIN_POINTS)} 个连续计数点')
    period = 4 if len(values) < 16 else 8
    seasonal_template = [_mean(values[i::period]) for i in range(period)]
    seasonal = [seasonal_template[i % period] for i in range(len(values))]
    base = _mean(values)
    deseasonal = [v - s + base for v, s in zip(values, seasonal)]
    kernel_n = min(5, len(values))
    kernel = [1.0 / kernel_n] * kernel_n
    trend_full = [0.0] * len(values)
    for i in range(len(values)):
        lo = max(0, i - kernel_n // 2)
        hi = min(len(values), lo + kernel_n)
        lo = max(0, hi - kernel_n)
        trend_full[i] = _mean(deseasonal[lo:hi])
    trend_full[:2] = deseasonal[:2]
    trend_full[-2:] = deseasonal[-2:]
    fitted = [t + s - base for t, s in zip(trend_full, seasonal)]
    residual = [v - f for v, f in zip(values, fitted)]
    strength = max(0.0, 1.0 - _variance(residual) / max(_variance(values), 1.0))
    recent = deseasonal[-window_size:]
    xs = list(range(window_size))
    slope, intercept = _linear_fit(xs, recent)
    future_slots = []
    last_at = rows[-1]['counted_at']
    for step in range(HORIZON):
        future_x = window_size + step
        future_trend = intercept + slope * future_x
        future_seasonal = seasonal_template[(len(values) + step) % period]
        bags = max(0.0, future_trend + future_seasonal - base)
        future_slots.append({
            'at': last_at + timedelta(minutes=SLOT_MINUTES * (step + 1)),
            'bags': round(bags, 2),
        })
    return {
        'slots': future_slots,
        'peak': round(max(slot['bags'] for slot in future_slots), 2),
        'seasonal_strength': round(strength, 4),
        'trend_per_slot': round(slope, 4),
        'window_size': window_size,
        'period': period,
        'input_points': len(values),
    }


def _slot_key(at):
    return at.isoformat()


def _run_belt(arrivals, capacity, pre_queue=0.0):
    """逐档模拟一条行李带，返回每档峰值与积压。

    arrivals: [{'at': datetime, 'bags': float}] 已按时间排序
    每档：先把上一档积压结转到本档，与本档新到件合并，容量内的消化，
    超出部分成为本档结束积压（留到下一档）。
    """
    backlog = float(pre_queue)
    slots = []
    for arrival in arrivals:
        inflow = round(float(arrival['bags']), 2)
        offered = round(backlog + inflow, 2)
        processed = round(min(offered, float(capacity)), 2)
        backlog = round(max(0.0, offered - float(capacity)), 2)
        slots.append({
            'at': arrival['at'],
            'inflow': inflow,
            'carried_queue': round(offered - inflow, 2),
            'capacity': float(capacity),
            'processed': processed,
            'backlog': backlog,
            'peak_load': offered,
        })
    return slots, backlog


def simulate_reroute(series_by_wave, disabled_belt, backup_belt, stop_at,
                     backup_capacity, disabled_capacity, window_size=8):
    """执行一次停用改送试算。

    series_by_wave: {
        wave_id: {
            'code': 波次号,
            'belts': {belt_code: [count points...]}
        }
    }
    每个涉及停用带的波次独立预测停用带与备带，停用带停带时刻之后的预测
    整档改投备带；多个波次共用备带时，备带自身预测与全部转入量逐档合并，
    超容量余量排队到下一档。
    """
    stop_at_iso = stop_at.isoformat()
    affected = {}
    baseline = {}
    # 备带自身（原有）负荷按波次分别预测，再逐档合并
    backup_own = {}
    transfers = []
    for wave_id, wave in series_by_wave.items():
        belts = wave['belts']
        if disabled_belt not in belts:
            continue
        disabled_forecast = forecast_belt_series(belts[disabled_belt], window_size)
        backup_points = belts.get(backup_belt, [])
        backup_forecast = forecast_belt_series(backup_points, window_size) if len(backup_points) >= MIN_POINTS else None
        affected[wave_id] = {
            'wave_id': wave_id,
            'code': wave['code'],
            'disabled_peak': disabled_forecast['peak'],
            'transferred_slots': [],
            'kept_slots': [],
        }
        baseline[(wave_id, disabled_belt)] = disabled_forecast
        if backup_forecast:
            baseline[(wave_id, backup_belt)] = backup_forecast
            for slot in backup_forecast['slots']:
                bucket = backup_own.setdefault(_slot_key(slot['at']), {'at': slot['at'], 'bags': 0.0})
                bucket['bags'] += float(slot['bags'])
        for slot in disabled_forecast['slots']:
            entry = {'at': slot['at'], 'bags': slot['bags'], 'wave_id': wave_id, 'code': wave['code']}
            if slot['at'] >= stop_at:
                transfers.append(entry)
                affected[wave_id]['transferred_slots'].append(
                    {'at': slot['at'].isoformat(), 'bags': slot['bags']})
            else:
                affected[wave_id]['kept_slots'].append(
                    {'at': slot['at'].isoformat(), 'bags': slot['bags']})
    if not affected:
        raise ValueError('没有波次在该行李带上存在有效计数，无法试算')

    # 停用带：保留停带前的档（停带后不再进件，剩余为停带时点积压口径）
    disabled_slots = []
    for wave_id in affected:
        forecast = baseline[(wave_id, disabled_belt)]
        kept = [slot for slot in forecast['slots'] if slot['at'] < stop_at]
        slots, _ = _run_belt(kept, disabled_capacity)
        disabled_slots.append({'wave_id': wave_id, 'code': affected[wave_id]['code'], 'slots': slots})

    # 备带：原有负荷 + 各波次转入量，逐档合并后统一过容量、排队
    merged = {}
    for bucket in backup_own.values():
        merged[_slot_key(bucket['at'])] = {'at': bucket['at'], 'own': round(bucket['bags'], 2), 'transfer': 0.0}
    for entry in transfers:
        key = _slot_key(entry['at'])
        bucket = merged.setdefault(key, {'at': entry['at'], 'own': 0.0, 'transfer': 0.0})
        bucket['transfer'] = round(bucket['transfer'] + float(entry['bags']), 2)
    ordered = [merged[key] for key in sorted(merged)]
    backup_arrivals = [{'at': row['at'], 'bags': round(row['own'] + row['transfer'], 2)} for row in ordered]
    backup_slots, final_backlog = _run_belt(backup_arrivals, backup_capacity)
    for slot, row in zip(backup_slots, ordered):
        slot['own_inflow'] = row['own']
        slot['transfer_inflow'] = row['transfer']

    transfer_total = round(sum(float(e['bags']) for e in transfers), 2)
    return {
        'stop_at': stop_at_iso,
        'slot_minutes': SLOT_MINUTES,
        'horizon': HORIZON,
        'disabled_belt': disabled_belt,
        'backup_belt': backup_belt,
        'disabled_capacity': float(disabled_capacity),
        'backup_capacity': float(backup_capacity),
        'transfer_total_bags': transfer_total,
        'backup_final_backlog': final_backlog,
        'backup_peak_load': round(max((s['peak_load'] for s in backup_slots), default=0.0), 2),
        'backup_slots': [{**slot, 'at': slot['at'].isoformat()} for slot in backup_slots],
        'disabled_slots': [
            {'wave_id': item['wave_id'], 'code': item['code'],
             'slots': [{**slot, 'at': slot['at'].isoformat()} for slot in item['slots']]}
            for item in disabled_slots
        ],
        'affected_waves': [affected[key] for key in sorted(affected)],
        'baseline_peaks': [
            {'wave_id': wave_id, 'belt_code': belt_code, 'peak': forecast['peak'],
             'slots': [{'at': slot['at'].isoformat(), 'bags': slot['bags']} for slot in forecast['slots']]}
            for (wave_id, belt_code), forecast in sorted(baseline.items())
        ],
    }
