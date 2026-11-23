import os
import time
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ['DATABASE_URL']

@contextmanager
def connect():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        yield conn

def wait_for_db():
    for _ in range(40):
        try:
            with connect() as conn:
                conn.execute('SELECT 1')
                return
        except Exception:
            time.sleep(1)
    raise RuntimeError('database unavailable')

def migrate():
    with connect() as conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
          id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
          display_name TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('operator','supervisor','viewer')), active BOOLEAN NOT NULL DEFAULT TRUE
        );
        CREATE TABLE IF NOT EXISTS flight_waves (
          id SERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, terminal TEXT NOT NULL, arrival_start TIMESTAMPTZ NOT NULL,
          arrival_end TIMESTAMPTZ NOT NULL, flight_count INT NOT NULL CHECK (flight_count > 0), planned_bags INT NOT NULL CHECK (planned_bags >= 0),
          cancellation_state TEXT NOT NULL DEFAULT 'normal' CHECK (cancellation_state IN ('normal','cancelled_unmarked','cancelled_marked','diverted_marked')),
          status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','counting','forecasted','closed')), notes TEXT DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS belt_counts (
          id SERIAL PRIMARY KEY, wave_id INT NOT NULL REFERENCES flight_waves(id) ON DELETE CASCADE, belt_code TEXT NOT NULL,
          counted_at TIMESTAMPTZ NOT NULL, bag_count INT NOT NULL CHECK (bag_count >= 0), scan_source TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'accepted' CHECK (status IN ('accepted','voided')), UNIQUE(wave_id,belt_code,counted_at)
        );
        CREATE TABLE IF NOT EXISTS peak_forecasts (
          id SERIAL PRIMARY KEY, wave_id INT NOT NULL REFERENCES flight_waves(id), status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','ready','blocked','failed','published')),
          peak_bags NUMERIC(10,2), forecast_at TIMESTAMPTZ, seasonal_strength NUMERIC(8,4), trend_per_hour NUMERIC(8,4),
          window_size INT, snapshot_hash TEXT, parameters JSONB NOT NULL DEFAULT '{}'::jsonb, result JSONB NOT NULL DEFAULT '{}'::jsonb,
          failure_reason TEXT, created_by INT REFERENCES users(id), attempts INT NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS staff_shifts (
          id SERIAL PRIMARY KEY, shift_code TEXT UNIQUE NOT NULL, wave_id INT REFERENCES flight_waves(id), start_at TIMESTAMPTZ NOT NULL,
          end_at TIMESTAMPTZ NOT NULL, planned_staff INT NOT NULL CHECK (planned_staff >= 0), capacity INT NOT NULL CHECK (capacity > 0),
          status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','needs_confirmation','confirmed','over_capacity','completed')),
          confirmation_note TEXT DEFAULT '', confirmed_by INT REFERENCES users(id), confirmed_at TIMESTAMPTZ
        );
        CREATE TABLE IF NOT EXISTS congestion_reviews (
          id SERIAL PRIMARY KEY, wave_id INT NOT NULL REFERENCES flight_waves(id), forecast_id INT REFERENCES peak_forecasts(id),
          observed_peak INT NOT NULL CHECK (observed_peak >= 0), queue_minutes INT NOT NULL CHECK (queue_minutes >= 0), cause TEXT NOT NULL,
          action TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','actioned','closed')), reviewed_by INT REFERENCES users(id), reviewed_at TIMESTAMPTZ
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
          id SERIAL PRIMARY KEY, actor_id INT REFERENCES users(id), action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id INT, detail JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        ''')

def audit(conn, actor_id, action, entity_type, entity_id=None, detail=None):
    conn.execute('INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,detail) VALUES (%s,%s,%s,%s,%s::jsonb)', (actor_id, action, entity_type, entity_id, __import__('json').dumps(detail or {}, ensure_ascii=False)))
