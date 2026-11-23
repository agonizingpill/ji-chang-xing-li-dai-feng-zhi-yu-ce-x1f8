"""Source records and completion rules for peak-staffing."""

PEAK_STAFFING = {
    'peak-staffing': {
        'title': '峰值班组保障验收',
        'reference_label': '岗班增援调度号',
        'outcomes': {
            'covered': ('确认容量满足预测峰值', ('covered',)),
            'reinforce': ('已提交跨班增援申请', None),
        },
        'sql': """
SELECT f.id::text AS source_key,CONCAT(w.code,' · 预测 ',f.id) AS subject,
       CONCAT('峰值 ',f.peak_bags,' 件 · 已确认容量 ',10*COALESCE(SUM(s.capacity),0),' 件 · 时点 ',f.forecast_at) AS source_summary,
       CASE WHEN f.peak_bags IS NOT NULL AND f.peak_bags<=10*COALESCE(SUM(s.capacity),0) THEN 'covered' ELSE 'shortfall' END AS readiness
FROM peak_forecasts f JOIN flight_waves w ON w.id=f.wave_id LEFT JOIN staff_shifts s ON s.wave_id=f.wave_id
 AND s.status='confirmed' AND s.start_at<=f.forecast_at AND f.forecast_at<s.end_at
WHERE f.status IN ('ready','published') GROUP BY f.id,w.code
""",
    },
}
