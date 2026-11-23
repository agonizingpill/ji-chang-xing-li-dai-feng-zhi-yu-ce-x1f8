"""Additional operational reconciliation rules for this project."""

RECONCILIATION_VIEWS = {
    'cancellation-reconciliation': (
        '取消与备降波次核销',
        '对照航班波次标记与最近预测状态，优先处理取消未标和停用波次中的遗留发布。',
        ['波次', '航站楼', '波次状态', '取消或备降标记', '最近预测', '预测状态', '核销动作'],
        """
SELECT w.code,w.terminal,w.status AS wave_status,w.cancellation_state,f.id,f.status AS forecast_status,
       CASE WHEN w.cancellation_state='cancelled_unmarked' THEN '补录取消标记'
            WHEN w.cancellation_state IN ('cancelled_marked','diverted_marked') AND f.status='published' THEN '复核遗留预测发布'
            WHEN w.cancellation_state IN ('cancelled_marked','diverted_marked') THEN '维护取消或备降记录'
            ELSE '正常波次' END
FROM flight_waves w LEFT JOIN peak_forecasts f ON f.id=(SELECT MAX(p.id) FROM peak_forecasts p WHERE p.wave_id=w.id)
ORDER BY CASE WHEN w.cancellation_state='normal' THEN 1 ELSE 0 END,w.arrival_start,w.code
""",
    ),
    'first-bag-window': (
        '首件行李接驳偏差',
        '逐波次和行李带定位首个实际有件的有效计数，对照波次窗口识别等待或时间对齐异常。',
        ['波次', '行李带', '到达窗口开始', '窗口结束', '首个有件计数', '与窗口起点差 分', '核对建议'],
        """
WITH first_bags AS (
    SELECT wave_id,belt_code,MIN(counted_at) FILTER (WHERE status='accepted' AND bag_count>0) AS first_at
    FROM belt_counts GROUP BY wave_id,belt_code
)
SELECT w.code,f.belt_code,w.arrival_start,w.arrival_end,f.first_at,
       ROUND(EXTRACT(EPOCH FROM (f.first_at-w.arrival_start))/60,1),
       CASE WHEN f.first_at IS NULL THEN '待录入首件'
            WHEN f.first_at<w.arrival_start THEN '核对提前与时钟差'
            WHEN f.first_at>w.arrival_end THEN '首件超出波次窗口'
            ELSE '窗口内已有件' END
FROM flight_waves w LEFT JOIN first_bags f ON w.id=f.wave_id ORDER BY w.arrival_start,w.code,f.belt_code
""",
    ),
    'congestion-action-followup': (
        '拥堵复盘行动回收',
        '按复盘行动、当时排队分钟和处置状态分拣主管待关闭事项。',
        ['波次', '复盘号', '排队 分', '拥堵原因', '处置行动', '复核时间', '行动去向'],
        """
SELECT w.code,r.id,r.queue_minutes,r.cause,r.action,r.reviewed_at,
       CASE WHEN r.status='closed' THEN '已销项'
            WHEN NULLIF(TRIM(r.action),'') IS NULL THEN '待补处置行动'
            WHEN r.status='actioned' THEN '待主管核验销项'
            ELSE '待落实行动' END
FROM congestion_reviews r JOIN flight_waves w ON w.id=r.wave_id
ORDER BY CASE WHEN r.status='closed' THEN 1 ELSE 0 END,r.queue_minutes DESC,r.id
""",
    ),
}
