"""A dispatch release view joining cancellations, forecasts and the shift in force at peak."""

from .operations_evidence import query


def readiness_board():
    waves = query("""
        SELECT w.code,w.terminal,w.cancellation_state,f.forecast_at,f.peak_bags,
            COALESCE((SELECT 10*SUM(s.capacity) FROM staff_shifts s WHERE s.wave_id=w.id
                      AND s.status='confirmed' AND s.start_at<=f.forecast_at AND f.forecast_at<s.end_at), 0) AS covered
        FROM flight_waves w LEFT JOIN LATERAL (
            SELECT peak_bags,forecast_at FROM peak_forecasts WHERE wave_id=w.id
              AND status IN ('ready','published') ORDER BY id DESC LIMIT 1
        ) f ON TRUE
        WHERE w.status<>'closed' ORDER BY w.arrival_start,w.code LIMIT 80
    """)
    assignments = query("""
        SELECT w.code,s.shift_code,s.start_at,s.end_at,s.capacity,s.status
        FROM staff_shifts s JOIN flight_waves w ON w.id=s.wave_id
        WHERE w.status<>'closed' ORDER BY s.start_at,s.id LIMIT 500
    """)
    slots = {}
    for wave, shift, start, end, capacity, state in assignments:
        slots.setdefault(wave, []).append({'code': shift, 'start': start, 'end': end, 'bags': 10*capacity, 'state': state})
    output = []
    for code, terminal, cancellation, peak_at, peak, covered in waves:
        if cancellation != 'normal':
            state = '核对取消或备降'
        elif peak is None or peak_at is None:
            state = '等待有效预测'
        elif peak > covered:
            state = '峰值容量不足'
        else:
            state = '当前班组容量达标'
        output.append({'code': code, 'terminal': terminal, 'peak_at': peak_at, 'peak': peak,
                       'coverage': covered, 'state': state, 'shifts': slots.get(code, [])})
    return output
