#!/usr/bin/env python3
"""
migrate_airtable_to_postgres.py

Pulls all records from Airtable and inserts them into the Railway Postgres DB.
Safe to re-run: clears and reloads each table (except mailing_lists/list_records).

Usage:
    DATABASE_URL=<your_url> python scripts/migrate_airtable_to_postgres.py

Or just push to Railway and run via Railway CLI:
    railway run python scripts/migrate_airtable_to_postgres.py
"""

import os
import sys
import json
import requests
from datetime import datetime

# ── Load Airtable config ──────────────────────────────────────────────────────
def load_airtable_config():
    token   = os.getenv('AIRTABLE_TOKEN')
    base_id = os.getenv('AIRTABLE_BASE_ID')
    tables  = None

    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'airtable.json')
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = json.load(f)
        token   = token   or cfg.get('token')
        base_id = base_id or cfg.get('base_id')
        tables  = cfg.get('tables', {})

    if not tables:
        tables = {
            'clients':    os.getenv('AIRTABLE_TABLE_CLIENTS',    'tblKlgk5duSPuQKBZ'),
            'campaigns':  os.getenv('AIRTABLE_TABLE_CAMPAIGNS',  'tblEudwCUhFwU32CU'),
            'artwork':    os.getenv('AIRTABLE_TABLE_ARTWORK',     'tbludtNWAqQ1Ttoag'),
            'invoices':   os.getenv('AIRTABLE_TABLE_INVOICES',    'tbloebwZ56XAw6QJU'),
            'print_jobs': os.getenv('AIRTABLE_TABLE_PRINT_JOBS', 'tblJ1cuAi224uoLxI'),
            'users':      os.getenv('AIRTABLE_TABLE_USERS',       'tblEjDO4bnZW9hawl'),
            'new_movers': os.getenv('AIRTABLE_TABLE_NEW_MOVERS', 'tblGAR15Ubn6GwxkV'),
        }
    return token, base_id, tables


def fetch_all(token, base_id, table_id, page_size=100):
    """Fetch all records from an Airtable table."""
    url = f'https://api.airtable.com/v0/{base_id}/{table_id}'
    headers = {'Authorization': f'Bearer {token}'}
    records = []
    offset = None
    while True:
        params = {'pageSize': page_size}
        if offset:
            params['offset'] = offset
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        records.extend(data.get('records', []))
        offset = data.get('offset')
        if not offset:
            break
        print(f"  ... fetched {len(records)} so far")
    return records


# ── Postgres helpers ──────────────────────────────────────────────────────────
def get_pg():
    import psycopg2
    import psycopg2.extras
    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        print("ERROR: DATABASE_URL not set. Cannot migrate.")
        sys.exit(1)
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def run_sql(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)


def fetchone(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetchall(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


# ── Table creation (ensure schema exists) ────────────────────────────────────
def ensure_schema(conn):
    print("Creating tables if not exist...")
    sqls = [
        """CREATE TABLE IF NOT EXISTS clients (
            id              SERIAL PRIMARY KEY,
            company_name    TEXT,
            contact_name    TEXT,
            contact_email   TEXT,
            contact_phone   TEXT,
            portal_username TEXT,
            status          TEXT DEFAULT 'Active',
            notes           TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS users (
            id              SERIAL PRIMARY KEY,
            name            TEXT,
            email           TEXT UNIQUE,
            role            TEXT,
            client_id       INTEGER REFERENCES clients(id),
            password_hash   TEXT,
            last_login      TIMESTAMP,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS campaigns (
            id              SERIAL PRIMARY KEY,
            client_id       INTEGER REFERENCES clients(id),
            name            TEXT,
            postcard_size   TEXT DEFAULT '6x9',
            status          TEXT DEFAULT 'Draft',
            piece_count     INTEGER,
            mail_date       DATE,
            notes           TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS artwork (
            id              SERIAL PRIMARY KEY,
            campaign_id     INTEGER REFERENCES campaigns(id),
            client_id       INTEGER REFERENCES clients(id),
            name            TEXT,
            version         INTEGER DEFAULT 1,
            status          TEXT DEFAULT 'Pending Review',
            staff_notes     TEXT,
            client_notes    TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS invoices (
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
        )""",
        """CREATE TABLE IF NOT EXISTS print_jobs (
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
        )""",
        """CREATE TABLE IF NOT EXISTS new_movers (
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
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_new_movers_zip ON new_movers(zip)",
        "CREATE INDEX IF NOT EXISTS idx_new_movers_batch ON new_movers(upload_batch)",
    ]
    for sql in sqls:
        run_sql(conn, sql)
    conn.commit()
    print("Schema ready.")


# ── Migration functions ───────────────────────────────────────────────────────

def clear_table(conn, table):
    """Clear a table (with cascade for FK tables)."""
    run_sql(conn, f"TRUNCATE {table} RESTART IDENTITY CASCADE")
    conn.commit()


def resolve_client_id(conn, client_name_or_list):
    """Look up client_id from Postgres clients table by company name."""
    if not client_name_or_list:
        return None
    # Airtable sometimes stores linked records as a list
    name = client_name_or_list
    if isinstance(name, list):
        name = name[0] if name else None
    if not name:
        return None
    row = fetchone(conn, "SELECT id FROM clients WHERE company_name = %s", (str(name),))
    return row['id'] if row else None


def resolve_campaign_id(conn, campaign_name_or_list):
    """Look up campaign_id from Postgres campaigns table by name."""
    if not campaign_name_or_list:
        return None
    name = campaign_name_or_list
    if isinstance(name, list):
        name = name[0] if name else None
    if not name:
        return None
    row = fetchone(conn, "SELECT id FROM campaigns WHERE name = %s", (str(name),))
    return row['id'] if row else None


def safe_date(val):
    if not val:
        return None
    if isinstance(val, str):
        # Handle ISO datetime strings
        try:
            return val[:10]  # Take YYYY-MM-DD part
        except Exception:
            return None
    return val


def safe_decimal(val):
    if val is None or val == '':
        return None
    try:
        return float(str(val).replace(',', ''))
    except Exception:
        return None


def safe_int(val):
    if val is None or val == '':
        return None
    try:
        return int(val)
    except Exception:
        return None


def migrate_clients(conn, at_token, at_base, at_tables):
    print("\n── Migrating CLIENTS ──")
    records = fetch_all(at_token, at_base, at_tables['clients'])
    print(f"  Fetched {len(records)} from Airtable")
    clear_table(conn, 'clients')

    inserted = 0
    for r in records:
        f = r.get('fields', {})
        run_sql(conn, """
            INSERT INTO clients (company_name, contact_name, contact_email, contact_phone,
                                 portal_username, status, notes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            f.get('Company Name', ''),
            f.get('Contact Name', ''),
            f.get('Contact Email', ''),
            f.get('Contact Phone', ''),
            f.get('Portal Username', ''),
            f.get('Client Status') or f.get('Status', 'Active'),
            f.get('Notes', ''),
            _parse_created(r.get('createdTime')),
        ))
        inserted += 1

    conn.commit()
    print(f"  ✅ Inserted {inserted} clients")
    return inserted


def migrate_users(conn, at_token, at_base, at_tables):
    print("\n── Migrating USERS ──")
    records = fetch_all(at_token, at_base, at_tables['users'])
    print(f"  Fetched {len(records)} from Airtable")
    clear_table(conn, 'users')

    inserted = 0
    skipped  = 0
    for r in records:
        f = r.get('fields', {})
        email = f.get('Email', '').strip().lower()
        if not email:
            skipped += 1
            continue

        # Resolve client FK
        client_field = f.get('Client', '')
        client_id = resolve_client_id(conn, client_field)

        # Parse last_login
        last_login_raw = f.get('Last Login', '')
        last_login = None
        if last_login_raw:
            try:
                last_login = datetime.fromisoformat(last_login_raw.replace('Z', '+00:00'))
            except Exception:
                pass

        try:
            run_sql(conn, """
                INSERT INTO users (name, email, role, client_id, password_hash, last_login, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET
                    name=EXCLUDED.name, role=EXCLUDED.role, client_id=EXCLUDED.client_id,
                    password_hash=EXCLUDED.password_hash, last_login=EXCLUDED.last_login
            """, (
                f.get('Name', ''),
                email,
                f.get('Role', 'Client'),
                client_id,
                f.get('Password Hash', ''),
                last_login,
                _parse_created(r.get('createdTime')),
            ))
            inserted += 1
        except Exception as e:
            print(f"    WARN: skipped user {email}: {e}")
            skipped += 1

    conn.commit()
    print(f"  ✅ Inserted/updated {inserted} users, skipped {skipped}")
    return inserted


def migrate_campaigns(conn, at_token, at_base, at_tables):
    print("\n── Migrating CAMPAIGNS ──")
    records = fetch_all(at_token, at_base, at_tables['campaigns'])
    print(f"  Fetched {len(records)} from Airtable")
    clear_table(conn, 'campaigns')

    inserted = 0
    for r in records:
        f = r.get('fields', {})
        client_field = f.get('Client', '')
        client_id = resolve_client_id(conn, client_field)

        run_sql(conn, """
            INSERT INTO campaigns (client_id, name, postcard_size, status,
                                   piece_count, mail_date, notes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            client_id,
            f.get('Campaign Name', ''),
            f.get('Postcard Size', '6x9'),
            f.get('Status', 'Draft'),
            safe_int(f.get('Piece Count')),
            safe_date(f.get('Mail Date')),
            f.get('Notes', ''),
            _parse_created(r.get('createdTime')),
        ))
        inserted += 1

    conn.commit()
    print(f"  ✅ Inserted {inserted} campaigns")
    return inserted


def migrate_artwork(conn, at_token, at_base, at_tables):
    print("\n── Migrating ARTWORK ──")
    records = fetch_all(at_token, at_base, at_tables['artwork'])
    print(f"  Fetched {len(records)} from Airtable")
    clear_table(conn, 'artwork')

    inserted = 0
    for r in records:
        f = r.get('fields', {})
        client_id   = resolve_client_id(conn, f.get('Client', ''))
        campaign_id = resolve_campaign_id(conn, f.get('Campaign', ''))

        run_sql(conn, """
            INSERT INTO artwork (campaign_id, client_id, name, version, status,
                                 staff_notes, client_notes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            campaign_id,
            client_id,
            f.get('Artwork Name', ''),
            safe_int(f.get('Version')) or 1,
            f.get('Status', 'Pending Review'),
            f.get('Staff Notes', ''),
            f.get('Client Notes', ''),
            _parse_created(r.get('createdTime')),
        ))
        inserted += 1

    conn.commit()
    print(f"  ✅ Inserted {inserted} artwork records")
    return inserted


def migrate_invoices(conn, at_token, at_base, at_tables):
    print("\n── Migrating INVOICES ──")
    records = fetch_all(at_token, at_base, at_tables['invoices'])
    print(f"  Fetched {len(records)} from Airtable")
    clear_table(conn, 'invoices')

    inserted = 0
    for r in records:
        f = r.get('fields', {})
        client_id   = resolve_client_id(conn, f.get('Client', ''))
        campaign_id = resolve_campaign_id(conn, f.get('Campaign', ''))

        run_sql(conn, """
            INSERT INTO invoices (invoice_number, client_id, campaign_id, status,
                                  amount, due_date, paid_date, notes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            f.get('Invoice Number', ''),
            client_id,
            campaign_id,
            f.get('Status', 'Draft'),
            safe_decimal(f.get('Amount')),
            safe_date(f.get('Due Date')),
            safe_date(f.get('Paid Date')),
            f.get('Notes', ''),
            _parse_created(r.get('createdTime')),
        ))
        inserted += 1

    conn.commit()
    print(f"  ✅ Inserted {inserted} invoices")
    return inserted


def migrate_print_jobs(conn, at_token, at_base, at_tables):
    print("\n── Migrating PRINT JOBS ──")
    records = fetch_all(at_token, at_base, at_tables['print_jobs'])
    print(f"  Fetched {len(records)} from Airtable")
    clear_table(conn, 'print_jobs')

    inserted = 0
    for r in records:
        f = r.get('fields', {})
        client_id   = resolve_client_id(conn, f.get('Client', ''))
        campaign_id = resolve_campaign_id(conn, f.get('Campaign', ''))

        run_sql(conn, """
            INSERT INTO print_jobs (campaign_id, client_id, job_name, piece_count,
                                    status, print_date, mail_date, pdf_url, notes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            campaign_id,
            client_id,
            f.get('Job Name', ''),
            safe_int(f.get('Piece Count')),
            f.get('Status', 'Queued'),
            safe_date(f.get('Print Date')),
            safe_date(f.get('Mail Date')),
            f.get('PDF URL', ''),
            f.get('Notes', ''),
            _parse_created(r.get('createdTime')),
        ))
        inserted += 1

    conn.commit()
    print(f"  ✅ Inserted {inserted} print jobs")
    return inserted


def migrate_new_movers(conn, at_token, at_base, at_tables):
    print("\n── Migrating NEW MOVERS ──")
    records = fetch_all(at_token, at_base, at_tables['new_movers'])
    print(f"  Fetched {len(records)} from Airtable")
    clear_table(conn, 'new_movers')

    inserted = 0
    for r in records:
        f = r.get('fields', {})
        run_sql(conn, """
            INSERT INTO new_movers (address, city, zip, state, county,
                                    sale_date, sale_price, tier, year_built,
                                    sqft, neighborhood, upload_batch, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            f.get('Address', ''),
            f.get('City', ''),
            f.get('Zip', ''),
            f.get('State', ''),
            f.get('County', ''),
            f.get('Sale Date', ''),
            f.get('Sale Price', ''),
            f.get('Tier', ''),
            f.get('Year Built', ''),
            f.get('Square Ft', ''),
            f.get('Neighborhood', ''),
            f.get('Upload Batch', ''),
            _parse_created(r.get('createdTime')),
        ))
        inserted += 1

    conn.commit()
    print(f"  ✅ Inserted {inserted} new movers")
    return inserted


def _parse_created(created_time):
    if not created_time:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(created_time.replace('Z', '+00:00'))
    except Exception:
        return datetime.utcnow()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Pinpoint Direct — Airtable → Postgres Migration")
    print("=" * 60)

    if not os.getenv('DATABASE_URL'):
        print("\nERROR: DATABASE_URL environment variable not set.")
        print("Set it and re-run:")
        print("  export DATABASE_URL=postgresql://...")
        print("  python scripts/migrate_airtable_to_postgres.py")
        print("\nOn Railway, run via:")
        print("  railway run python scripts/migrate_airtable_to_postgres.py")
        sys.exit(1)

    at_token, at_base, at_tables = load_airtable_config()
    if not at_token or not at_base:
        print("ERROR: Airtable token/base_id not found.")
        sys.exit(1)

    print(f"\nAirtable base: {at_base}")
    print(f"Postgres: {os.getenv('DATABASE_URL')[:40]}...")

    conn = get_pg()
    ensure_schema(conn)

    summary = {}

    # Order matters: clients first (others FK to it)
    summary['clients']    = migrate_clients(conn, at_token, at_base, at_tables)
    summary['users']      = migrate_users(conn, at_token, at_base, at_tables)
    summary['campaigns']  = migrate_campaigns(conn, at_token, at_base, at_tables)
    summary['artwork']    = migrate_artwork(conn, at_token, at_base, at_tables)
    summary['invoices']   = migrate_invoices(conn, at_token, at_base, at_tables)
    summary['print_jobs'] = migrate_print_jobs(conn, at_token, at_base, at_tables)
    summary['new_movers'] = migrate_new_movers(conn, at_token, at_base, at_tables)

    conn.close()

    print("\n" + "=" * 60)
    print("  Migration Complete!")
    print("=" * 60)
    for table, count in summary.items():
        print(f"  {table:20s} → {count:5d} records")
    print("=" * 60)
    print("\n✅ All done. Postgres is now the source of truth.")
    print("   The Airtable config files are kept as backup.")


if __name__ == '__main__':
    main()
