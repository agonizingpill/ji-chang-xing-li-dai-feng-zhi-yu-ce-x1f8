import json, os, time
from contextlib import asynccontextmanager
from datetime import datetime
import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from .casework_routes import router as operational_cases
from .operations_evidence import router as operations_evidence
from .auth import current_user, issue, password_hash, require
from .db import audit, connect, migrate, wait_for_db
from .schemas import Login, WaveIn, CountIn, ForecastIn, ShiftIn, ConfirmIn, ReviewIn

r=redis.Redis.from_url(os.environ['REDIS_URL'], decode_responses=True)

def dump(rows): return [dict(row) for row in rows]
@asynccontextmanager
async def lifespan(_):
    wait_for_db(); migrate()
    if os.getenv('SEED_DEMO','true').lower()=='true':
        from scripts.seed_demo import main as seed_main
        seed_main()
    yield
app=FastAPI(title='机场行李带峰值预测', lifespan=lifespan)
app.include_router(operational_cases)
app.include_router(operations_evidence)
@app.middleware('http')
async def guard(request: Request, call_next):
    started=time.monotonic()
    try: response=await call_next(request)
    except HTTPException: raise
    except Exception as exc: return JSONResponse(status_code=500,content={'detail':str(exc)})
    response.headers['X-Request-ID']=os.urandom(8).hex(); response.headers['X-Process-Time']=f'{time.monotonic()-started:.4f}'; response.headers['Cache-Control']='no-store'; return response
@app.get('/health')
def health():
    with connect() as conn: conn.execute('SELECT 1')
    return {'status':'healthy','redis':bool(r.ping())}
@app.post('/login')
def login(data: Login):
    with connect() as conn:
        user=conn.execute('SELECT id,username,display_name,role,password_hash FROM users WHERE username=%s AND active',(data.username,)).fetchone()
        if not user or user['password_hash']!=password_hash(data.password): raise HTTPException(401,'用户名或密码不正确')
        audit(conn,user['id'],'login','user',user['id'],{'role':user['role']}); conn.commit()
        return {'access_token':issue(user),'token_type':'bearer','user':{k:user[k] for k in ('id','username','display_name','role')}}
@app.get('/me')
def me(user=Depends(current_user)): return user
@app.get('/dashboard')
def dashboard(user=Depends(current_user)):
    with connect() as conn:
        return {'waves':conn.execute('SELECT COUNT(*) c FROM flight_waves').fetchone()['c'],'active_waves':conn.execute("SELECT COUNT(*) c FROM flight_waves WHERE status IN ('open','counting','forecasted')").fetchone()['c'],'forecasts_ready':conn.execute("SELECT COUNT(*) c FROM peak_forecasts WHERE status IN ('ready','published')").fetchone()['c'],'blocked_waves':conn.execute("SELECT COUNT(*) c FROM peak_forecasts WHERE status='blocked'").fetchone()['c'],'needs_confirmation':conn.execute("SELECT COUNT(*) c FROM staff_shifts WHERE status='needs_confirmation'").fetchone()['c'],'open_reviews':conn.execute("SELECT COUNT(*) c FROM congestion_reviews WHERE status!='closed'").fetchone()['c']}
@app.get('/waves')
def waves(user=Depends(current_user)):
    with connect() as conn: return dump(conn.execute('SELECT * FROM flight_waves ORDER BY arrival_start').fetchall())
@app.post('/waves',status_code=201)
def create_wave(data: WaveIn,user=Depends(require('operator','supervisor'))):
    if data.arrival_end<=data.arrival_start: raise HTTPException(400,'到达结束时间必须晚于开始时间')
    with connect() as conn:
        try:
            row=conn.execute('INSERT INTO flight_waves(code,terminal,arrival_start,arrival_end,flight_count,planned_bags,cancellation_state,notes,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,\'open\') RETURNING *',(data.code,data.terminal,data.arrival_start,data.arrival_end,data.flight_count,data.planned_bags,data.cancellation_state,data.notes)).fetchone()
        except Exception as exc: raise HTTPException(409,'航班波次编号已存在或字段不符合约束') from exc
        audit(conn,user['id'],'create','flight_wave',row['id'],{'code':row['code']}); conn.commit(); return row
@app.get('/waves/{wave_id}/counts')
def counts(wave_id:int,user=Depends(current_user)):
    with connect() as conn: return dump(conn.execute('SELECT * FROM belt_counts WHERE wave_id=%s ORDER BY counted_at',(wave_id,)).fetchall())
@app.post('/counts',status_code=201)
def create_count(data:CountIn,user=Depends(require('operator','supervisor'))):
    with connect() as conn:
        wave=conn.execute('SELECT * FROM flight_waves WHERE id=%s',(data.wave_id,)).fetchone()
        if not wave: raise HTTPException(404,'航班波次不存在')
        try: row=conn.execute('INSERT INTO belt_counts(wave_id,belt_code,counted_at,bag_count,scan_source) VALUES (%s,%s,%s,%s,%s) RETURNING *',(data.wave_id,data.belt_code,data.counted_at,data.bag_count,data.scan_source)).fetchone()
        except Exception as exc: raise HTTPException(409,'同一航班波次、行李带和时间不能重复计数') from exc
        conn.execute("UPDATE flight_waves SET status='counting' WHERE id=%s AND status='open'",(data.wave_id,)); audit(conn,user['id'],'create','belt_count',row['id'],{'wave_id':data.wave_id}); conn.commit(); return row
@app.get('/forecasts')
def forecasts(user=Depends(current_user)):
    with connect() as conn: return dump(conn.execute('SELECT f.*,w.code,w.terminal FROM peak_forecasts f JOIN flight_waves w ON w.id=f.wave_id ORDER BY f.id DESC').fetchall())
@app.post('/forecasts',status_code=202)
def create_forecast(data:ForecastIn,user=Depends(require('operator','supervisor'))):
    with connect() as conn:
        wave=conn.execute('SELECT * FROM flight_waves WHERE id=%s',(data.wave_id,)).fetchone()
        if not wave: raise HTTPException(404,'航班波次不存在')
        if wave['cancellation_state']=='cancelled_unmarked':
            raise HTTPException(409,'航班取消或改降尚未标记，禁止发布峰值预测')
        point_count=conn.execute("SELECT COUNT(*) c FROM belt_counts WHERE wave_id=%s AND status='accepted'",(data.wave_id,)).fetchone()['c']
        if point_count<8: raise HTTPException(409,'计数点不足 8 个，无法进行时序分解')
        row=conn.execute("INSERT INTO peak_forecasts(wave_id,status,window_size,created_by) VALUES (%s,'queued',%s,%s) RETURNING *",(data.wave_id,data.window_size,user['id'])).fetchone(); audit(conn,user['id'],'queue','peak_forecast',row['id'],{'method':'STL + rolling linear'}); conn.commit()
    try: r.rpush('airport:forecast',str(row['id']))
    except Exception: pass
    return row
@app.post('/forecasts/{forecast_id}/publish')
def publish(forecast_id:int,user=Depends(require('operator','supervisor'))):
    with connect() as conn:
        f=conn.execute('SELECT * FROM peak_forecasts WHERE id=%s',(forecast_id,)).fetchone()
        if not f or f['status'] not in ('ready','published'): raise HTTPException(409,'预测尚未就绪')
        shift=conn.execute('SELECT * FROM staff_shifts WHERE wave_id=%s ORDER BY id DESC LIMIT 1',(f['wave_id'],)).fetchone()
        if not shift: raise HTTPException(409,'发布前必须先建立人员班次')
        if float(f['peak_bags'])>shift['capacity']*10 and shift['status']!='confirmed':
            conn.execute("UPDATE staff_shifts SET status='needs_confirmation' WHERE id=%s",(shift['id'],)); conn.commit(); raise HTTPException(409,'预测峰值超过当前岗位容量，需拆分班次并由值班经理确认')
        row=conn.execute("UPDATE peak_forecasts SET status='published',updated_at=now() WHERE id=%s RETURNING *",(forecast_id,)).fetchone(); audit(conn,user['id'],'publish','peak_forecast',forecast_id,{}); conn.commit(); return row
@app.post('/forecasts/{forecast_id}/retry',status_code=202)
def retry(forecast_id:int,user=Depends(require('operator','supervisor'))):
    with connect() as conn:
        row=conn.execute("UPDATE peak_forecasts SET status='queued',failure_reason=NULL WHERE id=%s AND status='failed' RETURNING *",(forecast_id,)).fetchone()
        if not row: raise HTTPException(409,'只有失败预测可以重试')
        conn.commit()
    r.rpush('airport:forecast',str(forecast_id)); return row
@app.get('/shifts')
def shifts(user=Depends(current_user)):
    with connect() as conn: return dump(conn.execute('SELECT s.*,w.code FROM staff_shifts s JOIN flight_waves w ON w.id=s.wave_id ORDER BY s.start_at').fetchall())
@app.post('/shifts',status_code=201)
def create_shift(data:ShiftIn,user=Depends(require('operator','supervisor'))):
    if data.end_at<=data.start_at: raise HTTPException(400,'班次结束时间必须晚于开始时间')
    with connect() as conn:
        wave=conn.execute('SELECT id FROM flight_waves WHERE id=%s',(data.wave_id,)).fetchone()
        if not wave: raise HTTPException(404,'波次不存在')
        status='needs_confirmation' if data.planned_staff>data.capacity else 'draft'
        row=conn.execute('INSERT INTO staff_shifts(shift_code,wave_id,start_at,end_at,planned_staff,capacity,status) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *',(data.shift_code,data.wave_id,data.start_at,data.end_at,data.planned_staff,data.capacity,status)).fetchone(); audit(conn,user['id'],'create','staff_shift',row['id'],{'status':status}); conn.commit(); return row
@app.post('/shifts/{shift_id}/confirm')
def confirm_shift(shift_id:int,data:ConfirmIn,user=Depends(require('supervisor'))):
    with connect() as conn:
        row=conn.execute("UPDATE staff_shifts SET status='confirmed',confirmation_note=%s,confirmed_by=%s,confirmed_at=now() WHERE id=%s RETURNING *",(data.note,user['id'],shift_id)).fetchone()
        if not row: raise HTTPException(404,'班次不存在')
        audit(conn,user['id'],'confirm','staff_shift',shift_id,{'note':data.note}); conn.commit(); return row
@app.get('/reviews')
def reviews(user=Depends(current_user)):
    with connect() as conn: return dump(conn.execute('SELECT r.*,w.code FROM congestion_reviews r JOIN flight_waves w ON w.id=r.wave_id ORDER BY r.id DESC').fetchall())
@app.post('/reviews',status_code=201)
def create_review(data:ReviewIn,user=Depends(require('operator','supervisor'))):
    with connect() as conn:
        wave=conn.execute('SELECT id FROM flight_waves WHERE id=%s',(data.wave_id,)).fetchone()
        if not wave: raise HTTPException(404,'波次不存在')
        row=conn.execute('INSERT INTO congestion_reviews(wave_id,forecast_id,observed_peak,queue_minutes,cause,action) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *',(data.wave_id,data.forecast_id,data.observed_peak,data.queue_minutes,data.cause,data.action)).fetchone(); audit(conn,user['id'],'create','congestion_review',row['id'],{}); conn.commit(); return row
@app.post('/reviews/{review_id}/close')
def close_review(review_id:int,user=Depends(require('supervisor'))):
    with connect() as conn:
        row=conn.execute("UPDATE congestion_reviews SET status='closed',reviewed_by=%s,reviewed_at=now() WHERE id=%s RETURNING *",(user['id'],review_id)).fetchone()
        if not row: raise HTTPException(404,'复盘单不存在')
        audit(conn,user['id'],'close','congestion_review',review_id,{}); conn.commit(); return row
