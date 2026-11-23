"""行李带停用改送：试算、版本失效、确认换用新预测的领域服务。

并发口径：
- 每次试算对参与行李带的计数快照、容量和当时的已确认方案计算 basis_hash。
- 补报计数（POST /counts）、调整容量、确认其他改送方案都会让未确认试算的
  basis_hash 过期，旧试算置为 superseded，确认接口返回 409，要求重算。
- 确认在单事务内对试算行 SELECT ... FOR UPDATE，并复核 basis_hash，
  保证“确认另一个方案与本次确认并发”时后提交的一方失败。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException

from . import reroute_engine, reroute_repo as repo
from .db import audit, connect


def _utc(value: datetime):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f'无法序列化 {type(value)}')


def _dumps(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default)


def _belt(conn, code):
    belt = repo.get_active_belt(conn, code)
    if not belt:
        raise HTTPException(404, f'行李带 {code} 不存在或已停用登记')
    return belt


def _series_for(conn, disabled_code, backup_code):
    """收集所有在停用带上有计数的波次，连同备带计数一起返回给试算引擎。"""
    waves = repo.waves_on_belt(conn, disabled_code)
    if not waves:
        raise HTTPException(409, f'行李带 {disabled_code} 还没有任何有效计数，无法按带预测')
    series = {}
    for wave in waves:
        belts = {}
        for belt_code in (disabled_code, backup_code):
            rows = repo.belt_count_points(conn, wave['id'], belt_code)
            if rows:
                belts[belt_code] = [dict(row) for row in rows]
        series[wave['id']] = {'code': wave['code'], 'belts': belts}
    return series, [row['id'] for row in waves]


def compute_basis(conn, disabled_code, backup_code):
    """对计数快照、容量、已确认方案计算指纹；任一变化都会使旧试算作废。"""
    count_rows = repo.count_rows_for_basis(conn, (disabled_code, backup_code))
    counts = [(r['wave_id'], r['belt_code'], r['counted_at'].isoformat(), r['bag_count'], r['status'])
              for r in count_rows]
    capacities = {r['belt_code']: float(r['capacity_bags'])
                  for r in repo.capacities_for_basis(conn, (disabled_code, backup_code))}
    confirmed = [(r['id'], r['disabled_belt_code'], r['backup_belt_code'], r['updated_at'].isoformat())
                 for r in repo.confirmed_plans_touching(conn, (disabled_code, backup_code))]
    payload = {'counts': counts, 'capacities': capacities, 'confirmed': confirmed}
    return hashlib.sha256(_dumps(payload).encode()).hexdigest(), payload


def invalidate_open_trials(conn, belt_codes, reason):
    """补报计数或调容量时，把受影响行李带的未确认试算置为作废。"""
    if not belt_codes:
        return 0
    return repo.void_trials_on_belts(conn, belt_codes, reason)


def create_trial(data, user):
    stop_at = _utc(data.stop_at)
    if data.disabled_belt_code == data.backup_belt_code:
        raise HTTPException(400, '备带不能与停用带是同一条行李带')
    with connect() as conn:
        disabled = _belt(conn, data.disabled_belt_code)
        backup = _belt(conn, data.backup_belt_code)
        if not backup['is_backup']:
            raise HTTPException(400, f'{backup["belt_code"]} 不是备带，不能承接改送')
        series, wave_ids = _series_for(conn, data.disabled_belt_code, data.backup_belt_code)
        # 同一停用带只保留一个未确认试算：再次试算先把旧试算作废
        repo.void_trials_for_disabled(conn, data.disabled_belt_code, '同一停用带发起了新的试算')
        try:
            trial = reroute_engine.simulate_reroute(
                series, data.disabled_belt_code, data.backup_belt_code, stop_at,
                backup_capacity=float(backup['capacity_bags']),
                disabled_capacity=float(disabled['capacity_bags']),
                window_size=data.window_size)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        basis_hash, _ = compute_basis(conn, data.disabled_belt_code, data.backup_belt_code)
        row = repo.insert_plan(conn, {
            'disabled_belt_code': data.disabled_belt_code, 'backup_belt_code': data.backup_belt_code,
            'stop_at': stop_at, 'window_size': data.window_size, 'basis_hash': basis_hash,
            'trial_result': _dumps(trial), 'affected_wave_ids': wave_ids, 'created_by': user['id']})
        audit(conn, user['id'], 'reroute_trial', 'belt_reroute_plan', row['id'],
              {'disabled': data.disabled_belt_code, 'backup': data.backup_belt_code,
               'waves': wave_ids, 'backup_peak': trial['backup_peak_load'],
               'backup_backlog': trial['backup_final_backlog']})
        conn.commit()
        return _plan_view(conn, row)


def recalc(plan_id, user):
    with connect() as conn:
        plan = repo.get_plan_for_update(conn, plan_id)
        if not plan:
            raise HTTPException(404, '试算方案不存在')
        if plan['status'] not in ('trial', 'superseded'):
            raise HTTPException(409, '只有未确认或已作废的试算可以重新计算')
        disabled = _belt(conn, plan['disabled_belt_code'])
        backup = _belt(conn, plan['backup_belt_code'])
        series, wave_ids = _series_for(conn, plan['disabled_belt_code'], plan['backup_belt_code'])
        try:
            trial = reroute_engine.simulate_reroute(
                series, plan['disabled_belt_code'], plan['backup_belt_code'], plan['stop_at'],
                backup_capacity=float(backup['capacity_bags']),
                disabled_capacity=float(disabled['capacity_bags']),
                window_size=plan['window_size'])
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        basis_hash, _ = compute_basis(conn, plan['disabled_belt_code'], plan['backup_belt_code'])
        row = repo.update_trial_result(conn, plan_id, _dumps(trial), basis_hash, wave_ids)
        audit(conn, user['id'], 'reroute_recalc', 'belt_reroute_plan', plan_id,
              {'basis_hash': basis_hash[:12], 'waves': wave_ids})
        conn.commit()
        return _plan_view(conn, row)


def confirm(plan_id, data, user):
    with connect() as conn:
        plan = repo.get_plan_for_update(conn, plan_id)
        if not plan:
            raise HTTPException(404, '试算方案不存在')
        if plan['status'] == 'confirmed':
            raise HTTPException(409, '该改送方案已经确认过')
        if plan['status'] == 'superseded':
            raise HTTPException(409, f'旧试算已作废（{plan["stale_reason"] or "基础数据变化"}），请重新试算后再确认')
        current_hash, _ = compute_basis(conn, plan['disabled_belt_code'], plan['backup_belt_code'])
        if current_hash != plan['basis_hash']:
            repo.mark_plan_superseded(conn, plan_id, '计数补报、容量调整或其他方案确认导致基础数据变化')
            audit(conn, user['id'], 'reroute_stale', 'belt_reroute_plan', plan_id, {})
            conn.commit()
            raise HTTPException(409, '试算依据已变化，旧试算已作废，请重新试算后再确认')

        trial = plan['trial_result']
        # 确认成功：所有受影响波次一起换用新预测（每带新预测写回 peak_forecasts）
        forecast_ids = []
        for wave_id in plan['affected_wave_ids']:
            wave = repo.get_wave(conn, wave_id)
            if not wave:
                continue
            peak = _wave_rerouted_peak(trial, wave_id)
            result = {
                'source': 'belt-reroute-confirmation',
                'reroute_plan_id': plan_id,
                'disabled_belt': plan['disabled_belt_code'],
                'backup_belt': plan['backup_belt_code'],
                'stop_at': plan['stop_at'].isoformat(),
                'trial': trial,
            }
            row = repo.insert_reroute_forecast(
                conn, wave_id, peak, plan['window_size'],
                _dumps({'method': 'belt reroute trial confirmation', 'seed': 1072}),
                _dumps(result), user['id'])
            forecast_ids.append(row['id'])
            repo.mark_wave_forecasted(conn, wave_id)
        # 并发保护：同一对停用/备带的其他未确认试算一并作废
        repo.void_other_trials_for_belts(conn, plan_id, [plan['disabled_belt_code'], plan['backup_belt_code']])
        row = repo.confirm_plan(conn, plan_id, user['id'], forecast_ids)
        audit(conn, user['id'], 'reroute_confirm', 'belt_reroute_plan', plan_id,
              {'note': data.note, 'forecast_ids': forecast_ids, 'waves': plan['affected_wave_ids']})
        conn.commit()
        return _plan_view(conn, row)


def _wave_rerouted_peak(trial, wave_id):
    """受影响波次换用的新峰值。

    停用带保留档取该波次自己的峰值；改投档取该波次有转入件数的备带档峰值
    负荷（备带为共用资源，档内还包含其他波次转入与备带原有负荷）。
    """
    candidates = []
    for item in trial.get('disabled_slots', []):
        if item['wave_id'] == wave_id:
            candidates.extend(slot['peak_load'] for slot in item['slots'])
    transferred_times = {
        slot['at']
        for wave in trial.get('affected_waves', [])
        if wave['wave_id'] == wave_id
        for slot in wave.get('transferred_slots', [])
    }
    for slot in trial.get('backup_slots', []):
        if slot['at'] in transferred_times and slot.get('transfer_inflow', 0) > 0:
            candidates.append(float(slot['peak_load']))
    return round(max(candidates, default=0.0), 2)


def _plan_view(conn, row):
    view = dict(row)
    view['trial_result'] = row['trial_result'] if isinstance(row['trial_result'], dict) else json.loads(row['trial_result'] or '{}')
    view['confirmed_result'] = row['confirmed_result'] if isinstance(row['confirmed_result'], dict) else json.loads(row['confirmed_result'] or '{}')
    view['stale'] = view['status'] == 'trial' and _plan_is_stale(conn, row)
    return view


def _plan_is_stale(conn, row):
    current_hash, _ = compute_basis(conn, row['disabled_belt_code'], row['backup_belt_code'])
    return current_hash != row['basis_hash']


def list_plans():
    with connect() as conn:
        return [_plan_view(conn, row) for row in repo.list_plans_desc(conn)]


def get_plan(plan_id):
    with connect() as conn:
        row = repo.get_plan(conn, plan_id)
        if not row:
            raise HTTPException(404, '试算方案不存在')
        return _plan_view(conn, row)


def overview():
    """值班页面：各行李带当前峰值与积压（基线预测 + 最新方案影响）。"""
    with connect() as conn:
        plans = repo.list_confirmed_plans_desc(conn)
        latest_plan = {}
        for plan in plans:
            key = (plan['disabled_belt_code'], plan['backup_belt_code'])
            latest_plan.setdefault(key, plan)
        output = []
        for belt in repo.list_belts(conn):
            code = belt['belt_code']
            baseline = _baseline_peaks(conn, code)
            active = None
            for (disabled_code, backup_code), plan in latest_plan.items():
                if code in (disabled_code, backup_code):
                    active = {'plan_id': plan['id'], 'disabled_belt': disabled_code,
                              'backup_belt': backup_code, 'stop_at': plan['stop_at'].isoformat(),
                              'confirmed_at': plan['confirmed_at'].isoformat()}
                    break
            output.append({
                'belt_code': code, 'belt_name': belt['belt_name'], 'terminal': belt['terminal'],
                'is_backup': belt['is_backup'], 'active': belt['active'],
                'capacity_bags': float(belt['capacity_bags']),
                'baseline_peak': baseline['peak'], 'baseline_slots': baseline['slots'],
                'active_reroute': active,
            })
        return {'belts': output, 'open_trials': [dict(row) for row in repo.list_open_trials(conn)]}


def _baseline_peaks(conn, belt_code):
    """按带预测：汇总该带上每个波次的独立预测，取峰值最大的波次作为带基线。"""
    peaks = []
    slots_out = []
    for wave in repo.waves_on_belt(conn, belt_code):
        points = repo.belt_count_points(conn, wave['id'], belt_code)
        if len(points) < reroute_engine.MIN_POINTS:
            continue
        forecast = reroute_engine.forecast_belt_series([dict(row) for row in points])
        peaks.append((forecast['peak'], wave['code']))
        slots_out.append({'wave_code': wave['code'], 'peak': forecast['peak'],
                          'slots': [{'at': s['at'].isoformat(), 'bags': s['bags']} for s in forecast['slots']]})
    if not peaks:
        return {'peak': None, 'slots': []}
    peak, code = max(peaks)
    return {'peak': peak, 'wave_code': code, 'slots': slots_out}


def update_capacity(belt_code, data, user):
    with connect() as conn:
        belt = _belt(conn, belt_code)
        old = float(belt['capacity_bags'])
        row = repo.update_belt_capacity(conn, belt_code, data.capacity_bags)
        changed = invalidate_open_trials(conn, [belt_code], '行李带容量已调整，试算依据变化')
        audit(conn, user['id'], 'belt_capacity', 'belt', row['id'],
              {'belt_code': belt_code, 'old': old, 'new': float(data.capacity_bags), 'trials_voided': changed})
        conn.commit()
        return dict(row)
