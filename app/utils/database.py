import os
import sqlite3

# If DATABASE_URL is set (Railway Postgres), use psycopg2; otherwise SQLite
DATABASE_URL = os.getenv('DATABASE_URL', '')


def db_exec(db, sql, params=()):
    """
    Execute a SQL statement using the right placeholder style (%s vs ?).
    Use this for the mailing_list / list_records routes so they work on both backends.
    """
    if DATABASE_URL:
        # psycopg2: convert ? to %s and use cursor
        pg_sql = sql.replace('?', '%s')
        with db.cursor() as cur:
            cur.execute(pg_sql, params)
            return cur
    else:
        return db.execute(sql, params)


def db_fetchall(db, sql, params=()):
    """Execute a SELECT and return list of dicts, works on both backends."""
    if DATABASE_URL:
        pg_sql = sql.replace('?', '%s')
        with db.cursor() as cur:
            cur.execute(pg_sql, params)
            return [dict(r) for r in cur.fetchall()]
    else:
        return [dict(r) for r in db.execute(sql, params).fetchall()]


def db_fetchone(db, sql, params=()):
    """Execute a SELECT and return one dict, works on both backends."""
    if DATABASE_URL:
        pg_sql = sql.replace('?', '%s')
        with db.cursor() as cur:
            cur.execute(pg_sql, params)
            row = cur.fetchone()
            return dict(row) if row else None
    else:
        row = db.execute(sql, params).fetchone()
        return dict(row) if row else None


def db_insert(db, sql, params=()):
    """
    Execute an INSERT and return the new row's id.
    Handles RETURNING for Postgres, lastrowid for SQLite.
    """
    if DATABASE_URL:
        # Append RETURNING id if not already there
        pg_sql = sql.replace('?', '%s')
        if 'RETURNING' not in pg_sql.upper():
            pg_sql += ' RETURNING id'
        with db.cursor() as cur:
            cur.execute(pg_sql, params)
            row = cur.fetchone()
            return row['id'] if row else None
    else:
        cur = db.execute(sql, params)
        return cur.lastrowid


def db_executemany(db, sql, params_list):
    """Execute a statement for each params tuple, works on both backends."""
    if DATABASE_URL:
        pg_sql = sql.replace('?', '%s')
        with db.cursor() as cur:
            for params in params_list:
                cur.execute(pg_sql, params)
    else:
        db.executemany(sql, params_list)

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    import re

    # Normalize DATABASE_URL for psycopg2
    # Standard:  postgres://user:pass@host/db  → postgresql://user:pass@host/db
    # Railway internal: postgres:PASS@host/db (no // , no username)
    #                → postgresql://postgres:PASS@host/db
    if re.match(r'^postgres(?:ql)?://', DATABASE_URL):
        DATABASE_URL = re.sub(r'^postgres(?:ql)?://', 'postgresql://', DATABASE_URL)
    elif re.match(r'^postgres:', DATABASE_URL):
        # Strip leading "postgres:" and inject proper scheme + default user
        rest = DATABASE_URL[len('postgres:'):]
        DATABASE_URL = 'postgresql://postgres:' + rest

    def _build_conn_kwargs():
        """
        Build psycopg2 connection kwargs. Prefer individual PG* env vars (always
        complete) over the DATABASE_URL which Railway sometimes delivers without
        a password field.
        """
        pghost = os.getenv('PGHOST') or os.getenv('RAILWAY_TCP_PROXY_DOMAIN')
        pgport = os.getenv('PGPORT', '5432')
        pguser = os.getenv('PGUSER', 'postgres')
        pgpass = os.getenv('PGPASSWORD')
        pgdb   = os.getenv('PGDATABASE', 'railway')

        if pghost and pgpass:
            return dict(
                host=pghost, port=int(pgport),
                user=pguser, password=pgpass,
                dbname=pgdb,
                cursor_factory=psycopg2.extras.RealDictCursor
            )
        # Fall back to the (normalized) DATABASE_URL
        return dict(dsn=DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

    def get_db():
        conn = psycopg2.connect(**_build_conn_kwargs())
        return conn

    def get_db_type():
        return 'postgres'

    def init_db():
        with get_db() as conn:
            with conn.cursor() as cur:
                # ── Existing tables (DO NOT MODIFY) ──────────────────────────
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

                # ── New tables (migrated from Airtable) ───────────────────────
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS clients (
                        id              SERIAL PRIMARY KEY,
                        company_name    TEXT,
                        contact_name    TEXT,
                        contact_email   TEXT,
                        contact_phone   TEXT,
                        portal_username TEXT,
                        status          TEXT DEFAULT 'Active',
                        notes           TEXT,
                        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id              SERIAL PRIMARY KEY,
                        name            TEXT,
                        email           TEXT UNIQUE,
                        role            TEXT,
                        client_id       INTEGER REFERENCES clients(id),
                        password_hash   TEXT,
                        last_login      TIMESTAMP,
                        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS campaigns (
                        id              SERIAL PRIMARY KEY,
                        client_id       INTEGER REFERENCES clients(id),
                        name            TEXT,
                        postcard_size   TEXT DEFAULT '6x9',
                        status          TEXT DEFAULT 'Draft',
                        piece_count     INTEGER,
                        mail_date       DATE,
                        notes           TEXT,
                        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS artwork (
                        id              SERIAL PRIMARY KEY,
                        campaign_id     INTEGER REFERENCES campaigns(id),
                        client_id       INTEGER REFERENCES clients(id),
                        name            TEXT,
                        version         INTEGER DEFAULT 1,
                        status          TEXT DEFAULT 'Pending Review',
                        staff_notes     TEXT,
                        client_notes    TEXT,
                        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS invoices (
                        id              SERIAL PRIMARY KEY,
                        invoice_number  TEXT,
                        client_id       INTEGER REFERENCES clients(id),
                        campaign_id     INTEGER REFERENCES campaigns(id),
                        status          TEXT DEFAULT 'Draft',
                        amount          DECIMAL(10,2),
                        due_date        DATE,
                        paid_date       DATE,
                        notes           TEXT,
                        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS print_jobs (
                        id              SERIAL PRIMARY KEY,
                        campaign_id     INTEGER REFERENCES campaigns(id),
                        client_id       INTEGER REFERENCES clients(id),
                        job_name        TEXT,
                        piece_count     INTEGER,
                        status          TEXT DEFAULT 'Queued',
                        print_date      DATE,
                        mail_date       DATE,
                        pdf_url         TEXT,
                        notes           TEXT,
                        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS new_movers (
                        id              SERIAL PRIMARY KEY,
                        address         TEXT,
                        city            TEXT,
                        zip             TEXT,
                        state           TEXT,
                        county          TEXT,
                        sale_date       TEXT,
                        sale_price      TEXT,
                        tier            TEXT,
                        year_built      TEXT,
                        sqft            TEXT,
                        neighborhood    TEXT,
                        upload_batch    TEXT,
                        verify_status   TEXT,
                        verify_message  TEXT,
                        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # Add verify columns to existing tables (idempotent)
                for col, col_type in [('verify_status', 'TEXT'), ('verify_message', 'TEXT')]:
                    try:
                        cur.execute(f"ALTER TABLE new_movers ADD COLUMN IF NOT EXISTS {col} {col_type}")
                    except Exception:
                        pass
                cur.execute("CREATE INDEX IF NOT EXISTS idx_new_movers_zip ON new_movers(zip)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_new_movers_batch ON new_movers(upload_batch)")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS leads (
                        id            SERIAL PRIMARY KEY,
                        name          VARCHAR(255),
                        email         VARCHAR(255),
                        business_name VARCHAR(255),
                        phone         VARCHAR(50),
                        message       TEXT,
                        created_at    TIMESTAMP DEFAULT NOW()
                    )
                """)
            conn.commit()

else:
    # SQLite for local development
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'instance', 'pinpoint.db')

    def get_db():
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def get_db_type():
        return 'sqlite'

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

                CREATE TABLE IF NOT EXISTS clients (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name    TEXT,
                    contact_name    TEXT,
                    contact_email   TEXT,
                    contact_phone   TEXT,
                    portal_username TEXT,
                    status          TEXT DEFAULT 'Active',
                    notes           TEXT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS users (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT,
                    email           TEXT UNIQUE,
                    role            TEXT,
                    client_id       INTEGER REFERENCES clients(id),
                    password_hash   TEXT,
                    last_login      DATETIME,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS campaigns (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id       INTEGER REFERENCES clients(id),
                    name            TEXT,
                    postcard_size   TEXT DEFAULT '6x9',
                    status          TEXT DEFAULT 'Draft',
                    piece_count     INTEGER,
                    mail_date       DATE,
                    notes           TEXT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS artwork (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id     INTEGER REFERENCES campaigns(id),
                    client_id       INTEGER REFERENCES clients(id),
                    name            TEXT,
                    version         INTEGER DEFAULT 1,
                    status          TEXT DEFAULT 'Pending Review',
                    staff_notes     TEXT,
                    client_notes    TEXT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS invoices (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_number  TEXT,
                    client_id       INTEGER REFERENCES clients(id),
                    campaign_id     INTEGER REFERENCES campaigns(id),
                    status          TEXT DEFAULT 'Draft',
                    amount          REAL,
                    due_date        DATE,
                    paid_date       DATE,
                    notes           TEXT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS print_jobs (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id     INTEGER REFERENCES campaigns(id),
                    client_id       INTEGER REFERENCES clients(id),
                    job_name        TEXT,
                    piece_count     INTEGER,
                    status          TEXT DEFAULT 'Queued',
                    print_date      DATE,
                    mail_date       DATE,
                    pdf_url         TEXT,
                    notes           TEXT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS new_movers (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    address         TEXT,
                    city            TEXT,
                    zip             TEXT,
                    state           TEXT,
                    county          TEXT,
                    sale_date       TEXT,
                    sale_price      TEXT,
                    tier            TEXT,
                    year_built      TEXT,
                    sqft            TEXT,
                    neighborhood    TEXT,
                    upload_batch    TEXT,
                    verify_status   TEXT,
                    verify_message  TEXT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_new_movers_zip ON new_movers(zip);
                CREATE INDEX IF NOT EXISTS idx_new_movers_batch ON new_movers(upload_batch);
                CREATE TABLE IF NOT EXISTS leads (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT,
                    email         TEXT,
                    business_name TEXT,
                    phone         TEXT,
                    message       TEXT,
                    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Add verify columns to existing SQLite tables (idempotent)
            for col, col_type in [('verify_status', 'TEXT'), ('verify_message', 'TEXT')]:
                try:
                    conn.execute(f"ALTER TABLE new_movers ADD COLUMN {col} {col_type}")
                except Exception:
                    pass  # Column already exists
            conn.commit()
