"""行李带改送相关的数据访问层（薄封装 SQL，便于领域服务保持可测）。"""
from __future__ import annotations


def get_active_belt(conn, code):
    return conn.execute('SELECT * FROM belts WHERE belt_code=%s AND active', (code,)).fetchone()


def list_belts(conn):
    return conn.execute('SELECT * FROM belts ORDER BY belt_code').fetchall()


def waves_on_belt(conn, belt_code):
    return conn.execute(
        "SELECT DISTINCT w.id, w.code FROM flight_waves w "
        "JOIN belt_counts c ON c.wave_id=w.id AND c.status='accepted' "
        "WHERE c.belt_code=%s ORDER BY w.id", (belt_code,)).fetchall()


def belt_count_points(conn, wave_id, belt_code):
    return conn.execute(
        "SELECT counted_at,bag_count FROM belt_counts WHERE wave_id=%s AND belt_code=%s "
        "AND status='accepted' ORDER BY counted_at", (wave_id, belt_code)).fetchall()


def count_rows_for_basis(conn, belt_codes):
    return conn.execute(
        "SELECT wave_id,belt_code,counted_at,bag_count,status FROM belt_counts "
        "WHERE belt_code IN (%s,%s) ORDER BY wave_id,belt_code,counted_at", tuple(belt_codes)).fetchall()


def capacities_for_basis(conn, belt_codes):
    return conn.execute(
        'SELECT belt_code,capacity_bags FROM belts WHERE belt_code IN (%s,%s) ORDER BY belt_code',
        tuple(belt_codes)).fetchall()


def confirmed_plans_touching(conn, belt_codes):
    codes = list(belt_codes)
    return conn.execute(
        "SELECT disabled_belt_code,backup_belt_code,id,updated_at FROM belt_reroute_plans "
        "WHERE status='confirmed' AND (disabled_belt_code IN (%s,%s) OR backup_belt_code IN (%s,%s)) "
        "ORDER BY id", (codes[0], codes[1], codes[0], codes[1])).fetchall()


def void_trials_on_belts(conn, belt_codes, reason):
    result = conn.execute(
        "UPDATE belt_reroute_plans SET status='superseded', stale_reason=%s, updated_at=now() "
        "WHERE status='trial' AND (disabled_belt_code = ANY(%s) OR backup_belt_code = ANY(%s))",
        (reason, list(belt_codes), list(belt_codes)))
    return result.rowcount


def void_trials_for_disabled(conn, disabled_code, reason):
    return conn.execute(
        "UPDATE belt_reroute_plans SET status='superseded', stale_reason=%s, updated_at=now() "
        "WHERE status='trial' AND disabled_belt_code=%s", (reason, disabled_code))


def insert_plan(conn, payload):
    return conn.execute(
        "INSERT INTO belt_reroute_plans(disabled_belt_code,backup_belt_code,stop_at,window_size,"
        "status,basis_hash,trial_result,affected_wave_ids,created_by) "
        "VALUES (%s,%s,%s,%s,'trial',%s,%s::jsonb,%s,%s) RETURNING *",
        (payload['disabled_belt_code'], payload['backup_belt_code'], payload['stop_at'],
         payload['window_size'], payload['basis_hash'], payload['trial_result'],
         payload['affected_wave_ids'], payload['created_by'])).fetchone()


def get_plan_for_update(conn, plan_id):
    return conn.execute('SELECT * FROM belt_reroute_plans WHERE id=%s FOR UPDATE', (plan_id,)).fetchone()


def get_plan(conn, plan_id):
    return conn.execute('SELECT * FROM belt_reroute_plans WHERE id=%s', (plan_id,)).fetchone()


def list_plans_desc(conn):
    return conn.execute('SELECT * FROM belt_reroute_plans ORDER BY id DESC LIMIT 100').fetchall()


def list_open_trials(conn):
    return conn.execute(
        "SELECT id,disabled_belt_code,backup_belt_code,status,stale_reason FROM belt_reroute_plans "
        "WHERE status='trial' ORDER BY id DESC").fetchall()


def update_trial_result(conn, plan_id, trial_result, basis_hash, wave_ids):
    return conn.execute(
        "UPDATE belt_reroute_plans SET status='trial',trial_result=%s::jsonb,basis_hash=%s,stale_reason='',"
        "affected_wave_ids=%s,updated_at=now() WHERE id=%s RETURNING *",
        (trial_result, basis_hash, wave_ids, plan_id)).fetchone()


def mark_plan_superseded(conn, plan_id, reason):
    return conn.execute(
        "UPDATE belt_reroute_plans SET status='superseded', stale_reason=%s, updated_at=now() WHERE id=%s",
        (reason, plan_id))


def insert_reroute_forecast(conn, wave_id, peak, window_size, parameters, result, user_id):
    return conn.execute(
        "INSERT INTO peak_forecasts(wave_id,status,peak_bags,forecast_at,window_size,parameters,result,created_by) "
        "VALUES (%s,'published',%s,now(),%s,%s::jsonb,%s::jsonb,%s) RETURNING id",
        (wave_id, peak, window_size, parameters, result, user_id)).fetchone()


def mark_wave_forecasted(conn, wave_id):
    return conn.execute("UPDATE flight_waves SET status='forecasted' WHERE id=%s", (wave_id,))


def get_wave(conn, wave_id):
    return conn.execute('SELECT * FROM flight_waves WHERE id=%s', (wave_id,)).fetchone()


def void_other_trials_for_belts(conn, plan_id, belt_codes):
    return conn.execute(
        "UPDATE belt_reroute_plans SET status='superseded', stale_reason='改送方案已确认，试算被新方案取代', updated_at=now() "
        "WHERE id<>%s AND status='trial' AND (disabled_belt_code=%s OR backup_belt_code=%s)",
        (plan_id, belt_codes[0], belt_codes[1]))


def confirm_plan(conn, plan_id, user_id, forecast_ids):
    return conn.execute(
        "UPDATE belt_reroute_plans SET status='confirmed',confirmed_by=%s,confirmed_at=now(),"
        "confirmed_forecast_ids=%s,confirmed_result=trial_result,updated_at=now() WHERE id=%s RETURNING *",
        (user_id, forecast_ids, plan_id)).fetchone()


def update_belt_capacity(conn, belt_code, capacity):
    return conn.execute(
        'UPDATE belts SET capacity_bags=%s,updated_at=now() WHERE belt_code=%s RETURNING *',
        (capacity, belt_code)).fetchone()


def list_confirmed_plans_desc(conn):
    return conn.execute(
        "SELECT * FROM belt_reroute_plans WHERE status='confirmed' ORDER BY confirmed_at DESC, id DESC").fetchall()
