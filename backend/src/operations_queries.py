"""Business queries over authoritative project records."""

from .operations_reconciliation import RECONCILIATION_VIEWS

VIEWS = {
    'belt-coverage': (
        '行李带计数覆盖审计',
        '核对波次是否有有效采样、计数是否落在到达窗口内。窗口外采样须由值班人员复核。',
        ['波次', '航站楼', '计划行李', '有效计数', '窗口外计数', '有效行李总量', '处置建议'],
        """
SELECT w.code,w.terminal,w.planned_bags,COUNT(c.id),SUM(CASE WHEN c.counted_at < w.arrival_start OR c.counted_at > w.arrival_end THEN 1 ELSE 0 END) AS outside,
       COALESCE(SUM(c.bag_count),0),CASE WHEN COUNT(c.id)=0 THEN '补录计数' WHEN SUM(CASE WHEN c.counted_at < w.arrival_start OR c.counted_at > w.arrival_end THEN 1 ELSE 0 END)>0 THEN '核对采样时段' ELSE '窗口内' END
FROM flight_waves w LEFT JOIN belt_counts c ON w.id=c.wave_id AND c.status='accepted' GROUP BY w.id ORDER BY outside DESC,w.arrival_start,w.code
""",
    ),
    'shift-conflicts': (
        '排班重叠核对',
        '同航站楼的有效班次若时段重叠，交值班经理确认岗位能否并行覆盖。相邻但互不重叠的班次不计为冲突。',
        ['航站楼', '班次', '并行班次', '重叠开始', '重叠结束', '计划人员总数'],
        """
SELECT wa.terminal,a.shift_code AS first_shift,b.shift_code AS second_shift,GREATEST(a.start_at,b.start_at),LEAST(a.end_at,b.end_at),a.planned_staff+b.planned_staff
FROM staff_shifts a JOIN staff_shifts b ON a.id<b.id AND a.start_at<b.end_at AND b.start_at<a.end_at
JOIN flight_waves wa ON wa.id=a.wave_id JOIN flight_waves wb ON wb.id=b.wave_id AND wb.terminal=wa.terminal
WHERE a.status<>'completed' AND b.status<>'completed' ORDER BY GREATEST(a.start_at,b.start_at),a.id,b.id
""",
    ),
    'forecast-calibration': (
        '峰值预测兑现追踪',
        '对照预测峰值与拥堵复盘实测，高出预测的高峰交给下轮模型校准。',
        ['波次', '预测编号', '复盘号', '预测峰值', '实测峰值', '绝对误差', '误差 %', '结论'],
        """
SELECT w.code,f.id AS forecast_id,r.id AS review_id,f.peak_bags,r.observed_peak,ABS(r.observed_peak-f.peak_bags),
       ABS(r.observed_peak-f.peak_bags)*100.0/NULLIF(r.observed_peak,0),
       CASE WHEN f.peak_bags IS NULL THEN '待模型结果' WHEN r.observed_peak>f.peak_bags THEN '预测低估' WHEN r.observed_peak<f.peak_bags THEN '预测高估' ELSE '一致' END
FROM congestion_reviews r JOIN flight_waves w ON r.wave_id=w.id JOIN peak_forecasts f ON r.forecast_id=f.id AND f.wave_id=w.id ORDER BY r.id DESC
""",
    ),
    'transfer-capacity': (
        '峰值时点保障缺口',
        '只统计覆盖预测峰值时点的已确认班次。沿用发布环节每岗位 10 件的容量口径，以行李件数呈现缺口。',
        ['波次', '预测编号', '峰值时间', '预测峰值', '已确认容量 件', '保障缺口 件'],
        """
SELECT w.code,f.id,f.forecast_at,f.peak_bags,10*COALESCE(SUM(s.capacity),0),
       GREATEST(f.peak_bags-10*COALESCE(SUM(s.capacity),0),0) AS shortfall
FROM peak_forecasts f JOIN flight_waves w ON w.id=f.wave_id LEFT JOIN staff_shifts s ON s.wave_id=w.id
 AND s.status='confirmed' AND s.start_at<=f.forecast_at AND f.forecast_at<s.end_at
WHERE f.status IN ('ready','published') AND f.forecast_at IS NOT NULL AND f.peak_bags IS NOT NULL
GROUP BY w.code,f.id ORDER BY shortfall DESC,f.id
""",
    ),
    **RECONCILIATION_VIEWS,
}
