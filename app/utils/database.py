import os
import sqlite3

# If DATABASE_URL is set (Railway Postgres), use psycopg2; otherwise SQLite
DATABASE_URL = os.getenv('DATABASE_URL', '')

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras

    # Railway gives postgres:// but psycopg2 needs postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

    def get_db():
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn

    def init_db():
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS mailing_lists (
                        id          SERIAL PRIMARY KEY,
                        name        TEXT NOT NULL,
                        client      TEXT,
                        campaign    TEXT,
                        total       INTEGER DEFAULT 0,
                        verified    INTEGER DEFAULT 0,
                        failed      INTEGER DEFAULT 0,
                        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        notes       TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS list_records (
                        id              SERIAL PRIMARY KEY,
                        list_id         INTEGER NOT NULL REFERENCES mailing_lists(id) ON DELETE CASCADE,
                        first_name      TEXT,
                        last_name       TEXT,
                        company         TEXT,
                        address1        TEXT,
                        address2        TEXT,
                        city            TEXT,
                        state           TEXT,
                        zip             TEXT,
                        offer_code      TEXT,
                        verify_status   TEXT DEFAULT 'pending',
                        verify_message  TEXT
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_records_list ON list_records(list_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_records_status ON list_records(verify_status)")
            conn.commit()

else:
    # SQLite for local development
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'instance', 'pinpoint.db')

    def get_db():
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_db():
        with get_db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS mailing_lists (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    client      TEXT,
                    campaign    TEXT,
                    total       INTEGER DEFAULT 0,
                    verified    INTEGER DEFAULT 0,
                    failed      INTEGER DEFAULT 0,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    notes       TEXT
                );
                CREATE TABLE IF NOT EXISTS list_records (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    list_id         INTEGER NOT NULL REFERENCES mailing_lists(id) ON DELETE CASCADE,
                    first_name      TEXT,
                    last_name       TEXT,
                    company         TEXT,
                    address1        TEXT,
                    address2        TEXT,
                    city            TEXT,
                    state           TEXT,
                    zip             TEXT,
                    offer_code      TEXT,
                    verify_status   TEXT DEFAULT 'pending',
                    verify_message  TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_records_list ON list_records(list_id);
                CREATE INDEX IF NOT EXISTS idx_records_status ON list_records(verify_status);
            """)
            conn.commit()
