from datetime import datetime
from pydantic import BaseModel, Field
class Login(BaseModel): username: str; password: str
class WaveIn(BaseModel): code: str = Field(min_length=3); terminal: str; arrival_start: datetime; arrival_end: datetime; flight_count: int = Field(gt=0); planned_bags: int = Field(ge=0); cancellation_state: str = 'normal'; notes: str = ''
class CountIn(BaseModel): wave_id: int; belt_code: str; counted_at: datetime; bag_count: int = Field(ge=0); scan_source: str = 'belt-counter'
class ForecastIn(BaseModel): wave_id: int; window_size: int = Field(default=8, ge=4, le=24)
class ShiftIn(BaseModel): shift_code: str; wave_id: int; start_at: datetime; end_at: datetime; planned_staff: int = Field(ge=0); capacity: int = Field(gt=0)
class ConfirmIn(BaseModel): note: str = Field(min_length=3)
class ReviewIn(BaseModel): wave_id: int; forecast_id: int | None = None; observed_peak: int = Field(ge=0); queue_minutes: int = Field(ge=0); cause: str = Field(min_length=2); action: str = Field(min_length=2)
