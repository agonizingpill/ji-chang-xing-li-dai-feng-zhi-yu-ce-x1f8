"""Source records and completion rules for belt-handoff."""

BELT_HANDOFF = {
    'belt-handoff': {
        'title': '首件接驳放行',
        'reference_label': '行李带交接或工单编号',
        'outcomes': {
            'delivered': ('首件在到达窗口内出现', ('delivered',)),
            'ground': ('转交地服查找首件', None),
        },
        'sql': """
SELECT CONCAT(w.id,'/', b.belt_code) AS source_key,CONCAT(w.code,' · ',b.belt_code) AS subject,
       CONCAT('到达窗口 ',w.arrival_start,' 至 ',w.arrival_end,' · 首件 ',
              COALESCE((MIN(b.counted_at) FILTER (WHERE b.status='accepted' AND b.bag_count>0))::text,'未登记')) AS source_summary,
       CASE WHEN MIN(b.counted_at) FILTER (WHERE b.status='accepted' AND b.bag_count>0) BETWEEN w.arrival_start AND w.arrival_end
            THEN 'delivered' ELSE 'late' END AS readiness
FROM flight_waves w JOIN belt_counts b ON b.wave_id=w.id GROUP BY w.id,b.belt_code
""",
    },
}
