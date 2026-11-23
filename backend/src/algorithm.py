import hashlib, json
from datetime import datetime, timezone
import numpy as np

def stl_rolling_forecast(points, window_size=8):
    points = sorted(points, key=lambda row: row['counted_at'])
    values = np.array([float(row['bag_count']) for row in points], dtype=float)
    if len(values) < max(window_size, 8): raise ValueError('至少需要 8 个连续计数点')
    period = 4 if len(values) < 16 else 8
    seasonal_template = np.array([values[i::period].mean() for i in range(period)])
    seasonal = np.array([seasonal_template[i % period] for i in range(len(values))])
    deseasonal = values - seasonal + values.mean()
    kernel = np.ones(min(5, len(values))) / min(5, len(values))
    trend = np.convolve(deseasonal, kernel, mode='same')
    trend[:2] = deseasonal[:2]
    trend[-2:] = deseasonal[-2:]
    residual = values - (trend + seasonal - values.mean())
    recent = deseasonal[-window_size:]
    x = np.arange(window_size, dtype=float)
    slope, intercept = np.polyfit(x, recent, 1)
    future_x = np.arange(window_size, window_size + 4, dtype=float)
    future_trend = intercept + slope * future_x
    future_seasonal = np.array([seasonal_template[(len(values)+i) % period] for i in range(4)])
    predicted = np.maximum(0, future_trend + future_seasonal - values.mean())
    peak = float(predicted.max())
    strength = float(max(0, 1 - np.var(residual) / max(np.var(values), 1)))
    snapshot = hashlib.sha256(json.dumps([(str(p['counted_at']), p['bag_count']) for p in points], default=str).encode()).hexdigest()
    return {'peak_bags': round(peak, 2), 'seasonal_strength': round(strength, 4), 'trend_per_hour': round(float(slope), 4), 'window_size': window_size, 'period': period, 'predicted_next_4': [round(float(v),2) for v in predicted], 'snapshot_hash': snapshot, 'input_points': len(values)}
