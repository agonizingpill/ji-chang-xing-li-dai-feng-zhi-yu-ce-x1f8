from datetime import datetime, timedelta, timezone
from src.db import connect
from src.auth import password_hash

def main():
    base=datetime(2026,11,21,6,0,tzinfo=timezone.utc)
    with connect() as conn:
        for username,display,role in [('ops.demo','值机调度员','operator'),('manager.demo','值班经理','supervisor'),('audit.demo','运行观察员','viewer')]:
            conn.execute('INSERT INTO users(username,password_hash,display_name,role) VALUES (%s,%s,%s,%s) ON CONFLICT(username) DO UPDATE SET display_name=EXCLUDED.display_name, role=EXCLUDED.role', (username,password_hash('Airport1072!'),display,role))
        op=conn.execute("SELECT id FROM users WHERE username='ops.demo'").fetchone()['id']
        waves=[('WAVE-AM-0615','T2',base,base+timedelta(hours=2),8,420,'normal','早高峰国际到达'),('WAVE-PM-1810','T3',base+timedelta(hours=12),base+timedelta(hours=14),6,300,'normal','晚高峰转机波次'),('WAVE-CANCEL-0900','T1',base+timedelta(hours=3),base+timedelta(hours=4),3,140,'cancelled_unmarked','航班取消但未完成运行标记')]
        for code,terminal,start,end,flights,bags,cancel,notes in waves:
            conn.execute('INSERT INTO flight_waves(code,terminal,arrival_start,arrival_end,flight_count,planned_bags,cancellation_state,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(code) DO NOTHING',(code,terminal,start,end,flights,bags,cancel,notes))
        wave_ids={r['code']:r['id'] for r in conn.execute('SELECT id,code FROM flight_waves').fetchall()}
        belts=[('BAG-AM','T2 早高峰主带','T2',280.0,False),('BAG-PM','T3 晚高峰主带','T3',240.0,False),
               ('BAG-CANCEL','T1 备用主带','T1',180.0,False),('BAG-AM-BK','T2 北侧备带','T2',260.0,True),
               ('BAG-PM-BK','T3 西侧备带','T3',220.0,True)]
        for code,name,terminal,capacity,is_backup in belts:
            conn.execute('INSERT INTO belts(belt_code,belt_name,terminal,capacity_bags,is_backup) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(belt_code) DO UPDATE SET belt_name=EXCLUDED.belt_name,terminal=EXCLUDED.terminal,capacity_bags=EXCLUDED.capacity_bags,is_backup=EXCLUDED.is_backup,active=TRUE',(code,name,terminal,capacity,is_backup))
        for code, wave_code, start, vals in [
            ('BAG-AM','WAVE-AM-0615',base,[42,55,68,80,96,115,132,145,158,176,189,205,220,238,252,268]),
            ('BAG-PM','WAVE-PM-1810',base+timedelta(hours=12),[35,44,58,65,74,88,102,120,138,151,166,180]),
            ('BAG-CANCEL','WAVE-CANCEL-0900',base+timedelta(hours=3),[20,25,30,35,40,45,50,55])]:
            wid=wave_ids[wave_code]
            for i,value in enumerate(vals):
                conn.execute('INSERT INTO belt_counts(wave_id,belt_code,counted_at,bag_count,scan_source) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(wave_id,belt_code,counted_at) DO NOTHING',(wid,code,start+timedelta(minutes=10*i),value,'belt-counter-07'))
        # 第二个 T2 波次同样落在 BAG-AM，停用后与早高峰波次共用 BAG-AM-BK；
        # BAG-AM-BK 自身在该波次上已有负荷，演示“原有负荷 + 转入量 + 余量排队”。
        late_wave=('WAVE-AM-0845','T2',base+timedelta(hours=2,minutes=45),base+timedelta(hours=4,minutes=45),5,260,'normal','早高峰补班波次，与主波次共用 T2 备带')
        conn.execute('INSERT INTO flight_waves(code,terminal,arrival_start,arrival_end,flight_count,planned_bags,cancellation_state,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(code) DO NOTHING',late_wave)
        wave_ids={r['code']:r['id'] for r in conn.execute('SELECT id,code FROM flight_waves').fetchall()}
        late_id=wave_ids['WAVE-AM-0845']
        late_start=base+timedelta(hours=2,minutes=45)
        late_main=[48,60,72,85,98,112,126,140,152,166,178,190,202,214,226,238]
        late_backup=[26,32,39,45,52,58,64,70,76,82,88,94,100,106,112,118]
        for i,value in enumerate(late_main):
            conn.execute('INSERT INTO belt_counts(wave_id,belt_code,counted_at,bag_count,scan_source) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(wave_id,belt_code,counted_at) DO NOTHING',(late_id,'BAG-AM',late_start+timedelta(minutes=10*i),value,'belt-counter-11'))
        for i,value in enumerate(late_backup):
            conn.execute('INSERT INTO belt_counts(wave_id,belt_code,counted_at,bag_count,scan_source) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(wave_id,belt_code,counted_at) DO NOTHING',(late_id,'BAG-AM-BK',late_start+timedelta(minutes=10*i),value,'belt-counter-12'))
        conn.execute("INSERT INTO staff_shifts(shift_code,wave_id,start_at,end_at,planned_staff,capacity,status) VALUES ('SHIFT-AM-A',%s,%s,%s,18,20,'draft') ON CONFLICT(shift_code) DO NOTHING",(wave_ids['WAVE-AM-0615'],base+timedelta(minutes=30),base+timedelta(hours=2,minutes=30)))
        conn.execute("INSERT INTO staff_shifts(shift_code,wave_id,start_at,end_at,planned_staff,capacity,status) VALUES ('SHIFT-PM-C',%s,%s,%s,8,10,'draft') ON CONFLICT(shift_code) DO NOTHING",(wave_ids['WAVE-PM-1810'],base+timedelta(hours=12),base+timedelta(hours=15)))
        conn.commit()
if __name__=='__main__': main()
