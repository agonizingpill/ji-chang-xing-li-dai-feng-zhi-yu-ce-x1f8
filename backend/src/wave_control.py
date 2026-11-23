"""Source records and completion rules for wave-release."""

WAVE_CONTROL = {
    'wave-release': {
        'title': '取消备降波次发布核销',
        'reference_label': '航班变更核销单号',
        'outcomes': {
            'cleared': ('取消标记已核对且无遗留发布', ('clear',)),
            'tower': ('移交运控中心继续处理', None),
        },
        'sql': """
SELECT w.code AS source_key,CONCAT(w.code,' · ',w.terminal) AS subject,
       CONCAT(w.cancellation_state,' · 已发布预测 ',(SELECT COUNT(*) FROM peak_forecasts f WHERE f.wave_id=w.id AND f.status='published')) AS source_summary,
       CASE WHEN w.cancellation_state IN ('cancelled_marked','diverted_marked') AND NOT EXISTS (
            SELECT 1 FROM peak_forecasts f WHERE f.wave_id=w.id AND f.status='published') THEN 'clear' ELSE 'check' END AS readiness
FROM flight_waves w
""",
    },
}
