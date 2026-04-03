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
                        postcard_size   TEXT DEFAULT '5.25x8.5',
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
                        status        VARCHAR(50) DEFAULT 'New',
                        approved_at   TIMESTAMP,
                        created_at    TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS business_profiles (
                        id                          SERIAL PRIMARY KEY,
                        user_id                     INTEGER REFERENCES users(id) ON DELETE CASCADE,
                        client_id                   INTEGER REFERENCES clients(id) ON DELETE CASCADE,
                        business_name               TEXT,
                        business_type               TEXT,
                        years_in_business           TEXT,
                        average_transaction_value   TEXT,
                        top_services                TEXT,
                        best_customer_description   TEXT,
                        customer_compliment         TEXT,
                        main_competitor             TEXT,
                        competitive_advantage       TEXT,
                        created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # Idempotent migrations for business_profiles
                for col, col_type in [
                    ('client_id', 'INTEGER'),
                    ('years_in_business', 'TEXT'),
                    ('average_transaction_value', 'TEXT'),
                    ('top_services', 'TEXT'),
                    ('best_customer_description', 'TEXT'),
                    ('customer_compliment', 'TEXT'),
                    ('main_competitor', 'TEXT'),
                    ('competitive_advantage', 'TEXT'),
                    ('updated_at', 'TIMESTAMP'),
                ]:
                    try:
                        cur.execute(f"ALTER TABLE business_profiles ADD COLUMN IF NOT EXISTS {col} {col_type}")
                    except Exception:
                        pass
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS drip_campaigns (
                        id              SERIAL PRIMARY KEY,
                        client_id       INTEGER REFERENCES clients(id) ON DELETE CASCADE,
                        name            TEXT NOT NULL,
                        status          TEXT DEFAULT 'active',
                        max_months      INTEGER DEFAULT 7,
                        monthly_cap     INTEGER,
                        tier_filter     TEXT,
                        verified_only   BOOLEAN DEFAULT FALSE,
                        subdivisions    TEXT,
                        created_at      TIMESTAMP DEFAULT NOW(),
                        updated_at      TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS drip_mailings (
                        id              SERIAL PRIMARY KEY,
                        campaign_id     INTEGER REFERENCES drip_campaigns(id) ON DELETE CASCADE,
                        mover_id        INTEGER REFERENCES new_movers(id) ON DELETE CASCADE,
                        month_number    INTEGER NOT NULL,
                        mailed_at       TIMESTAMP DEFAULT NOW(),
                        UNIQUE(campaign_id, mover_id, month_number)
                    )
                """)
                # ── Campaigns column migrations (idempotent) ──────────────────────
                cur.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='campaigns' AND column_name='list_count') THEN
                        ALTER TABLE campaigns ADD COLUMN list_count INTEGER;
                      END IF;
                    END $$;
                """)
                cur.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='campaigns' AND column_name='quote_amount') THEN
                        ALTER TABLE campaigns ADD COLUMN quote_amount DECIMAL(10,2);
                      END IF;
                    END $$;
                """)
                # ── Campaign design brief + file columns (idempotent) ─────────────
                cur.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='campaigns' AND column_name='headline_ideas') THEN
                        ALTER TABLE campaigns ADD COLUMN headline_ideas TEXT;
                      END IF;
                    END $$;
                """)
                cur.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='campaigns' AND column_name='key_selling_points') THEN
                        ALTER TABLE campaigns ADD COLUMN key_selling_points TEXT;
                      END IF;
                    END $$;
                """)
                cur.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='campaigns' AND column_name='brand_colors') THEN
                        ALTER TABLE campaigns ADD COLUMN brand_colors TEXT;
                      END IF;
                    END $$;
                """)
                cur.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='campaigns' AND column_name='brand_tone') THEN
                        ALTER TABLE campaigns ADD COLUMN brand_tone TEXT;
                      END IF;
                    END $$;
                """)
                cur.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='campaigns' AND column_name='return_address') THEN
                        ALTER TABLE campaigns ADD COLUMN return_address TEXT;
                      END IF;
                    END $$;
                """)
                cur.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='campaigns' AND column_name='logo_files') THEN
                        ALTER TABLE campaigns ADD COLUMN logo_files TEXT;
                      END IF;
                    END $$;
                """)
                cur.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='campaigns' AND column_name='product_files') THEN
                        ALTER TABLE campaigns ADD COLUMN product_files TEXT;
                      END IF;
                    END $$;
                """)
                cur.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='campaigns' AND column_name='inspiration_files') THEN
                        ALTER TABLE campaigns ADD COLUMN inspiration_files TEXT;
                      END IF;
                    END $$;
                """)

                # ── Leads column migrations (idempotent) ─────────────────────────
                cur.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='leads' AND column_name='status') THEN
                        ALTER TABLE leads ADD COLUMN status VARCHAR(50) DEFAULT 'New';
                      END IF;
                    END $$;
                """)
                cur.execute("""
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='leads' AND column_name='approved_at') THEN
                        ALTER TABLE leads ADD COLUMN approved_at TIMESTAMP;
                      END IF;
                    END $$;
                """)

                # ── Mailing Operations tables ─────────────────────────────────────
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS mailing_jobs (
                        id SERIAL PRIMARY KEY,
                        job_name VARCHAR(255) NOT NULL,
                        campaign_id INTEGER REFERENCES campaigns(id),
                        client_id INTEGER REFERENCES clients(id),
                        status VARCHAR(50) DEFAULT 'Address Processing',
                        piece_count INTEGER DEFAULT 0,
                        sheet_count INTEGER DEFAULT 0,
                        list_filename VARCHAR(255),
                        list_uploaded_at TIMESTAMP,
                        cass_status VARCHAR(50) DEFAULT 'Pending',
                        cass_notes TEXT,
                        print_file_url VARCHAR(500),
                        print_started_at TIMESTAMP,
                        print_completed_at TIMESTAMP,
                        tray_count INTEGER DEFAULT 0,
                        tray_notes TEXT,
                        drop_date DATE,
                        bmeu_location VARCHAR(255),
                        form_3602_ref VARCHAR(100),
                        mail_class VARCHAR(50) DEFAULT 'USPS Marketing Mail',
                        postage_paid DECIMAL(10,2),
                        notes TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS mailing_trays (
                        id SERIAL PRIMARY KEY,
                        mailing_job_id INTEGER REFERENCES mailing_jobs(id),
                        tray_number INTEGER,
                        piece_count INTEGER,
                        zip_range VARCHAR(100),
                        tray_label VARCHAR(255),
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)

                # ── Production tables ─────────────────────────────────────────────
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS production_jobs (
                        id              SERIAL PRIMARY KEY,
                        campaign_id     INTEGER REFERENCES drip_campaigns(id) ON DELETE SET NULL,
                        name            TEXT NOT NULL,
                        status          TEXT DEFAULT 'pending',
                        piece_count     INTEGER DEFAULT 0,
                        permit_number   TEXT DEFAULT 'PERMIT #15',
                        permit_city     TEXT DEFAULT 'NEWNAN',
                        permit_state    TEXT DEFAULT 'GA',
                        permit_zip      TEXT DEFAULT '30263',
                        mail_class      TEXT DEFAULT 'Marketing Mail',
                        cass_validated  BOOLEAN DEFAULT FALSE,
                        presorted       BOOLEAN DEFAULT FALSE,
                        pdf_path        TEXT,
                        tray_labels_path TEXT,
                        created_at      TIMESTAMP DEFAULT NOW(),
                        mailed_at       TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS production_job_addresses (
                        id              SERIAL PRIMARY KEY,
                        job_id          INTEGER REFERENCES production_jobs(id) ON DELETE CASCADE,
                        mover_id        INTEGER,
                        address         TEXT,
                        city            TEXT,
                        state           TEXT,
                        zip5            TEXT,
                        zip4            TEXT,
                        address_std     TEXT,
                        city_std        TEXT,
                        state_std       TEXT,
                        zip5_std        TEXT,
                        zip4_std        TEXT,
                        dpbc            TEXT,
                        sort_key        TEXT,
                        tray_number     INTEGER,
                        bundle_number   INTEGER,
                        sequence_number INTEGER,
                        cass_valid      BOOLEAN DEFAULT FALSE,
                        imb_barcode     TEXT
                    )
                """)
                # ── Master Address List ───────────────────────────────────────────
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS master_addresses (
                        id                  SERIAL PRIMARY KEY,
                        first_name          TEXT,
                        last_name           TEXT,
                        address1            TEXT NOT NULL,
                        address2            TEXT,
                        city                TEXT,
                        state               TEXT,
                        zip                 TEXT,
                        county              TEXT,
                        list_type           TEXT,
                        permit_category     TEXT,
                        permit_description  TEXT,
                        permit_value        NUMERIC(12,2),
                        permit_date         TEXT,
                        permit_number       TEXT,
                        permit_status       TEXT,
                        sale_price          NUMERIC(12,2),
                        sale_date           TEXT,
                        tier                TEXT,
                        year_built          INTEGER,
                        square_ft           INTEGER,
                        neighborhood        TEXT,
                        parcel_class        TEXT,
                        upload_batch        TEXT,
                        source_file         TEXT,
                        added_date          TEXT,
                        address_hash        TEXT,
                        last_mailed_at      TIMESTAMP,
                        times_mailed        INTEGER DEFAULT 0,
                        cass_validated      BOOLEAN DEFAULT FALSE,
                        cass_date           TEXT,
                        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ma_county ON master_addresses(county)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ma_list_type ON master_addresses(list_type)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ma_permit_category ON master_addresses(permit_category)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ma_zip ON master_addresses(zip)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ma_address_hash ON master_addresses(address_hash)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ma_upload_batch ON master_addresses(upload_batch)")
                # Migrate existing master_addresses tables that predate these columns
                for col, col_type in [
                    ('sale_price',   'NUMERIC(12,2)'),
                    ('sale_date',    'TEXT'),
                    ('tier',         'TEXT'),
                    ('year_built',   'INTEGER'),
                    ('square_ft',    'INTEGER'),
                    ('neighborhood', 'TEXT'),
                    ('parcel_class', 'TEXT'),
                    ('permit_status', 'TEXT'),
                ]:
                    try:
                        cur.execute(f"ALTER TABLE master_addresses ADD COLUMN IF NOT EXISTS {col} {col_type}")
                    except Exception:
                        pass
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS master_address_campaign_uses (
                        id          SERIAL PRIMARY KEY,
                        address_id  INTEGER NOT NULL REFERENCES master_addresses(id) ON DELETE CASCADE,
                        campaign_id INTEGER,
                        client_id   INTEGER,
                        mailed_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        month_label TEXT
                    )
                """)

                # ── Design Requests columns migration (idempotent) ────────────────
                for _dr_col, _dr_type in [
                    ('mailing_list_targeting', 'TEXT'),
                    ('target_zips',            'TEXT'),
                ]:
                    try:
                        cur.execute(f"ALTER TABLE design_requests ADD COLUMN IF NOT EXISTS {_dr_col} {_dr_type}")
                    except Exception:
                        pass

                # ── Design Requests ───────────────────────────────────────────────
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS design_requests (
                        id SERIAL PRIMARY KEY,
                        client_id INTEGER REFERENCES clients(id),
                        campaign_id INTEGER REFERENCES campaigns(id),
                        status VARCHAR(50) DEFAULT 'Draft',
                        business_name VARCHAR(255),
                        industry VARCHAR(255),
                        campaign_goal TEXT,
                        products_services TEXT,
                        headline_ideas TEXT,
                        key_selling_points TEXT,
                        call_to_action VARCHAR(255),
                        cta_url VARCHAR(500),
                        promo_code VARCHAR(100),
                        brand_colors VARCHAR(255),
                        brand_tone VARCHAR(100),
                        target_audience TEXT,
                        mailing_list_status VARCHAR(50) DEFAULT 'Have one',
                        mailing_list_targeting TEXT,
                        target_zips VARCHAR(500),
                        return_address TEXT,
                        quantity INTEGER,
                        target_mail_date DATE,
                        additional_notes TEXT,
                        logo_files TEXT,
                        product_files TEXT,
                        inspiration_files TEXT,
                        proof_file VARCHAR(500),
                        proof_uploaded_at TIMESTAMP,
                        revision_round INTEGER DEFAULT 0,
                        revision_limit INTEGER DEFAULT 2,
                        client_feedback TEXT,
                        admin_notes TEXT,
                        fiverr_order_ref VARCHAR(100),
                        submitted_at TIMESTAMP,
                        approved_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT NOW()
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
                    postcard_size   TEXT DEFAULT '5.25x8.5',
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
                    status        TEXT DEFAULT 'New',
                    approved_at   DATETIME,
                    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS business_profiles (
                    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id                     INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    client_id                   INTEGER REFERENCES clients(id) ON DELETE CASCADE,
                    business_name               TEXT,
                    business_type               TEXT,
                    years_in_business           TEXT,
                    average_transaction_value   TEXT,
                    top_services                TEXT,
                    best_customer_description   TEXT,
                    customer_compliment         TEXT,
                    main_competitor             TEXT,
                    competitive_advantage       TEXT,
                    created_at                  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at                  DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS drip_campaigns (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id       INTEGER REFERENCES clients(id) ON DELETE CASCADE,
                    name            TEXT NOT NULL,
                    status          TEXT DEFAULT 'active',
                    max_months      INTEGER DEFAULT 7,
                    monthly_cap     INTEGER,
                    tier_filter     TEXT,
                    verified_only   INTEGER DEFAULT 0,
                    subdivisions    TEXT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS drip_mailings (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id     INTEGER REFERENCES drip_campaigns(id) ON DELETE CASCADE,
                    mover_id        INTEGER REFERENCES new_movers(id) ON DELETE CASCADE,
                    month_number    INTEGER NOT NULL,
                    mailed_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(campaign_id, mover_id, month_number)
                );
                CREATE TABLE IF NOT EXISTS mailing_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_name VARCHAR(255) NOT NULL,
                    campaign_id INTEGER REFERENCES campaigns(id),
                    client_id INTEGER REFERENCES clients(id),
                    status VARCHAR(50) DEFAULT 'Address Processing',
                    piece_count INTEGER DEFAULT 0,
                    sheet_count INTEGER DEFAULT 0,
                    list_filename VARCHAR(255),
                    list_uploaded_at DATETIME,
                    cass_status VARCHAR(50) DEFAULT 'Pending',
                    cass_notes TEXT,
                    print_file_url VARCHAR(500),
                    print_started_at DATETIME,
                    print_completed_at DATETIME,
                    tray_count INTEGER DEFAULT 0,
                    tray_notes TEXT,
                    drop_date DATE,
                    bmeu_location VARCHAR(255),
                    form_3602_ref VARCHAR(100),
                    mail_class VARCHAR(50) DEFAULT 'USPS Marketing Mail',
                    postage_paid REAL,
                    notes TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS mailing_trays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mailing_job_id INTEGER REFERENCES mailing_jobs(id),
                    tray_number INTEGER,
                    piece_count INTEGER,
                    zip_range VARCHAR(100),
                    tray_label VARCHAR(255),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS production_jobs (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id     INTEGER REFERENCES drip_campaigns(id) ON DELETE SET NULL,
                    name            TEXT NOT NULL,
                    status          TEXT DEFAULT 'pending',
                    piece_count     INTEGER DEFAULT 0,
                    permit_number   TEXT DEFAULT 'PERMIT #15',
                    permit_city     TEXT DEFAULT 'NEWNAN',
                    permit_state    TEXT DEFAULT 'GA',
                    permit_zip      TEXT DEFAULT '30263',
                    mail_class      TEXT DEFAULT 'Marketing Mail',
                    cass_validated  INTEGER DEFAULT 0,
                    presorted       INTEGER DEFAULT 0,
                    pdf_path        TEXT,
                    tray_labels_path TEXT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    mailed_at       DATETIME
                );
                CREATE TABLE IF NOT EXISTS production_job_addresses (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id          INTEGER REFERENCES production_jobs(id) ON DELETE CASCADE,
                    mover_id        INTEGER,
                    address         TEXT,
                    city            TEXT,
                    state           TEXT,
                    zip5            TEXT,
                    zip4            TEXT,
                    address_std     TEXT,
                    city_std        TEXT,
                    state_std       TEXT,
                    zip5_std        TEXT,
                    zip4_std        TEXT,
                    dpbc            TEXT,
                    sort_key        TEXT,
                    tray_number     INTEGER,
                    bundle_number   INTEGER,
                    sequence_number INTEGER,
                    cass_valid      INTEGER DEFAULT 0,
                    imb_barcode     TEXT
                );
                CREATE TABLE IF NOT EXISTS master_addresses (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    first_name          TEXT,
                    last_name           TEXT,
                    address1            TEXT NOT NULL,
                    address2            TEXT,
                    city                TEXT,
                    state               TEXT,
                    zip                 TEXT,
                    county              TEXT,
                    list_type           TEXT,
                    permit_category     TEXT,
                    permit_description  TEXT,
                    permit_value        REAL,
                    permit_date         TEXT,
                    permit_number       TEXT,
                    permit_status       TEXT,
                    upload_batch        TEXT,
                    source_file         TEXT,
                    added_date          TEXT,
                    address_hash        TEXT,
                    last_mailed_at      DATETIME,
                    times_mailed        INTEGER DEFAULT 0,
                    cass_validated      INTEGER DEFAULT 0,
                    cass_date           TEXT,
                    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_ma_county ON master_addresses(county);
                CREATE INDEX IF NOT EXISTS idx_ma_list_type ON master_addresses(list_type);
                CREATE INDEX IF NOT EXISTS idx_ma_permit_category ON master_addresses(permit_category);
                CREATE INDEX IF NOT EXISTS idx_ma_zip ON master_addresses(zip);
                CREATE INDEX IF NOT EXISTS idx_ma_address_hash ON master_addresses(address_hash);
                CREATE INDEX IF NOT EXISTS idx_ma_upload_batch ON master_addresses(upload_batch);
                CREATE TABLE IF NOT EXISTS master_address_campaign_uses (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    address_id  INTEGER NOT NULL REFERENCES master_addresses(id) ON DELETE CASCADE,
                    campaign_id INTEGER,
                    client_id   INTEGER,
                    mailed_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                    month_label TEXT
                );
                CREATE TABLE IF NOT EXISTS design_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER REFERENCES clients(id),
                    campaign_id INTEGER REFERENCES campaigns(id),
                    status VARCHAR(50) DEFAULT 'Draft',
                    business_name VARCHAR(255),
                    industry VARCHAR(255),
                    campaign_goal TEXT,
                    products_services TEXT,
                    headline_ideas TEXT,
                    key_selling_points TEXT,
                    call_to_action VARCHAR(255),
                    cta_url VARCHAR(500),
                    promo_code VARCHAR(100),
                    brand_colors VARCHAR(255),
                    brand_tone VARCHAR(100),
                    target_audience TEXT,
                    mailing_list_status VARCHAR(50) DEFAULT 'Have one',
                    mailing_list_targeting TEXT,
                    target_zips VARCHAR(500),
                    return_address TEXT,
                    quantity INTEGER,
                    target_mail_date DATE,
                    additional_notes TEXT,
                    logo_files TEXT,
                    product_files TEXT,
                    inspiration_files TEXT,
                    proof_file VARCHAR(500),
                    proof_uploaded_at DATETIME,
                    revision_round INTEGER DEFAULT 0,
                    revision_limit INTEGER DEFAULT 2,
                    client_feedback TEXT,
                    admin_notes TEXT,
                    fiverr_order_ref VARCHAR(100),
                    submitted_at DATETIME,
                    approved_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Add verify columns to existing SQLite tables (idempotent)
            for col, col_type in [('verify_status', 'TEXT'), ('verify_message', 'TEXT')]:
                try:
                    conn.execute(f"ALTER TABLE new_movers ADD COLUMN {col} {col_type}")
                except Exception:
                    pass  # Column already exists
            # Add leads columns (idempotent)
            for col, col_type in [('status', "TEXT DEFAULT 'New'"), ('approved_at', 'DATETIME')]:
                try:
                    conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {col_type}")
                except Exception:
                    pass  # Column already exists
            # Add campaign list/quote columns (idempotent)
            for col, col_type in [('list_count', 'INTEGER'), ('quote_amount', 'REAL')]:
                try:
                    conn.execute(f"ALTER TABLE campaigns ADD COLUMN {col} {col_type}")
                except Exception:
                    pass  # Column already exists
            # Add campaign design brief + file columns (idempotent)
            for col, col_type in [
                ('headline_ideas',    'TEXT'),
                ('key_selling_points','TEXT'),
                ('brand_colors',      'TEXT'),
                ('brand_tone',        'TEXT'),
                ('return_address',    'TEXT'),
                ('logo_files',        'TEXT'),
                ('product_files',     'TEXT'),
                ('inspiration_files', 'TEXT'),
            ]:
                try:
                    conn.execute(f"ALTER TABLE campaigns ADD COLUMN {col} {col_type}")
                except Exception:
                    pass  # Column already exists
            conn.commit()

            # Add design_requests columns (idempotent)
            for col, col_type in [
                ('mailing_list_targeting', 'TEXT'),
                ('target_zips',            'TEXT'),
            ]:
                try:
                    conn.execute(f"ALTER TABLE design_requests ADD COLUMN {col} {col_type}")
                except Exception:
                    pass  # Column already exists
            conn.commit()

            # Migrate master_addresses — add new_mover fields if not present
            for col, col_type in [
                ('sale_price',   'REAL'),
                ('sale_date',    'TEXT'),
                ('tier',         'TEXT'),
                ('year_built',   'INTEGER'),
                ('square_ft',    'INTEGER'),
                ('neighborhood', 'TEXT'),
                ('parcel_class', 'TEXT'),
                ('permit_status', 'TEXT'),
            ]:
                try:
                    conn.execute(f"ALTER TABLE master_addresses ADD COLUMN {col} {col_type}")
                except Exception:
                    pass  # Column already exists
            conn.commit()
