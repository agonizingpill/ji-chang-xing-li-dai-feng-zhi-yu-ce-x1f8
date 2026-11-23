"""Source records and completion rules for congestion-closeout."""

CONGESTION_CLOSEOUT = {
    'congestion-closeout': {
        'title': '拥堵复盘对外交接',
        'reference_label': '地服复盘签收编号',
        'outcomes': {
            'complete': ('复盘已由负责人关闭', ('closed',)),
            'followup': ('交给下轮波次复测', None),
        },
        'sql': """
SELECT r.id::text AS source_key,CONCAT(w.code,' · 复盘 ',r.id) AS subject,
       CONCAT('排队 ',r.queue_minutes,' 分钟 · ',r.status,' · ',NULLIF(TRIM(r.action),'')) AS source_summary,
       CASE WHEN r.status='closed' AND NULLIF(TRIM(r.action),'') IS NOT NULL THEN 'closed' ELSE 'pending' END AS readiness
FROM congestion_reviews r JOIN flight_waves w ON w.id=r.wave_id
""",
    },
}
