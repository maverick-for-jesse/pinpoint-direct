"""
db_helpers.py — Postgres-native CRUD layer with Airtable-compatible return format.

Every function returns records as:
    {'id': int, 'fields': {'Airtable Field Name': value, ...}, 'createdTime': str}

This lets existing routes work with minimal changes — just swap the import.
"""

import os
import re
from datetime import datetime
from app.utils.database import get_db, get_db_type, init_db

# Placeholder character for parametrized queries
PH = '%s' if get_db_type() == 'postgres' else '?'


# ─── SELECT queries (denormalized via JOINs) ──────────────────────────────────

_SELECT = {
    'clients': """
        SELECT c.id, c.company_name, c.contact_name, c.contact_email,
               c.contact_phone, c.portal_username, c.status, c.notes, c.created_at
        FROM clients c
    """,
    'campaigns': """
        SELECT c.id, c.name, c.postcard_size, c.status, c.piece_count,
               c.mail_date, c.notes, c.created_at, c.client_id,
               cl.company_name AS client_name
        FROM campaigns c
        LEFT JOIN clients cl ON c.client_id = cl.id
    """,
    'artwork': """
        SELECT a.id, a.name, a.version, a.status, a.staff_notes, a.client_notes,
               a.created_at, a.campaign_id, a.client_id,
               c.name AS campaign_name,
               cl.company_name AS client_name
        FROM artwork a
        LEFT JOIN campaigns c ON a.campaign_id = c.id
        LEFT JOIN clients cl ON a.client_id = cl.id
    """,
    'invoices': """
        SELECT i.id, i.invoice_number, i.status, i.amount, i.due_date,
               i.paid_date, i.notes, i.created_at, i.client_id, i.campaign_id,
               cl.company_name AS client_name,
               c.name AS campaign_name
        FROM invoices i
        LEFT JOIN clients cl ON i.client_id = cl.id
        LEFT JOIN campaigns c ON i.campaign_id = c.id
    """,
    'print_jobs': """
        SELECT pj.id, pj.job_name, pj.piece_count, pj.status, pj.print_date,
               pj.mail_date, pj.pdf_url, pj.notes, pj.created_at,
               pj.campaign_id, pj.client_id,
               c.name AS campaign_name,
               cl.company_name AS client_name
        FROM print_jobs pj
        LEFT JOIN campaigns c ON pj.campaign_id = c.id
        LEFT JOIN clients cl ON pj.client_id = cl.id
    """,
    'new_movers': """
        SELECT id, address, city, zip, state, county, sale_date, sale_price,
               tier, year_built, sqft, neighborhood, upload_batch, created_at
        FROM new_movers
    """,
    'users': """
        SELECT u.id, u.name, u.email, u.role, u.password_hash, u.last_login,
               u.created_at, u.client_id,
               cl.company_name AS client_name
        FROM users u
        LEFT JOIN clients cl ON u.client_id = cl.id
    """,
}


# ─── Row → Airtable-compatible dict ──────────────────────────────────────────

def _row_to_record(table, row):
    """Convert a DB row to Airtable-compatible {'id': int, 'fields': {...}} dict."""
    if row is None:
        return None
    r = dict(row)
    created_at = r.get('created_at')
    created_str = created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at or '')

    fields = {}

    if table == 'clients':
        fields = {
            'Company Name':    r.get('company_name') or '',
            'Contact Name':    r.get('contact_name') or '',
            'Contact Email':   r.get('contact_email') or '',
            'Contact Phone':   r.get('contact_phone') or '',
            'Portal Username': r.get('portal_username') or '',
            'Status':          r.get('status') or 'Active',
            'Client Status':   r.get('status') or 'Active',
            'Notes':           r.get('notes') or '',
        }
    elif table == 'campaigns':
        fields = {
            'Campaign Name': r.get('name') or '',
            'Client':        r.get('client_name') or '',
            'Postcard Size': r.get('postcard_size') or '6x9',
            'Status':        r.get('status') or 'Draft',
            'Piece Count':   r.get('piece_count') or 0,
            'Mail Date':     _date_str(r.get('mail_date')),
            'Notes':         r.get('notes') or '',
        }
    elif table == 'artwork':
        fields = {
            'Artwork Name':  r.get('name') or '',
            'Campaign':      r.get('campaign_name') or '',
            'Client':        r.get('client_name') or '',
            'Version':       r.get('version') or 1,
            'Status':        r.get('status') or 'Pending Review',
            'Staff Notes':   r.get('staff_notes') or '',
            'Client Notes':  r.get('client_notes') or '',
        }
    elif table == 'invoices':
        fields = {
            'Invoice Number': r.get('invoice_number') or '',
            'Client':         r.get('client_name') or '',
            'Campaign':       r.get('campaign_name') or '',
            'Status':         r.get('status') or 'Draft',
            'Amount':         float(r['amount']) if r.get('amount') is not None else 0.0,
            'Due Date':       _date_str(r.get('due_date')),
            'Paid Date':      _date_str(r.get('paid_date')),
            'Notes':          r.get('notes') or '',
        }
    elif table == 'print_jobs':
        fields = {
            'Job Name':    r.get('job_name') or '',
            'Campaign':    r.get('campaign_name') or '',
            'Client':      r.get('client_name') or '',
            'Piece Count': r.get('piece_count') or 0,
            'Status':      r.get('status') or 'Queued',
            'Print Date':  _date_str(r.get('print_date')),
            'Mail Date':   _date_str(r.get('mail_date')),
            'PDF URL':     r.get('pdf_url') or '',
            'Notes':       r.get('notes') or '',
        }
    elif table == 'new_movers':
        fields = {
            'Address':        r.get('address') or '',
            'City':           r.get('city') or '',
            'Zip':            r.get('zip') or '',
            'State':          r.get('state') or '',
            'County':         r.get('county') or '',
            'Sale Date':      r.get('sale_date') or '',
            'Sale Price':     r.get('sale_price') or '',
            'Tier':           r.get('tier') or '',
            'Year Built':     r.get('year_built') or '',
            'Square Ft':      r.get('sqft') or '',
            'Neighborhood':   r.get('neighborhood') or '',
            'Upload Batch':   r.get('upload_batch') or '',
            'Verify Status':  r.get('verify_status') or '',   # populated by verify route
            'Verify Message': r.get('verify_message') or '',  # populated by verify route
        }
    elif table == 'users':
        fields = {
            'Name':          r.get('name') or '',
            'Email':         r.get('email') or '',
            'Role':          r.get('role') or 'Client',
            'Client':        r.get('client_name') or '',
            'Password Hash': r.get('password_hash') or '',
            'Last Login':    r.get('last_login').isoformat() if hasattr(r.get('last_login'), 'isoformat') else (r.get('last_login') or ''),
        }

    return {
        'id': r['id'],
        'fields': fields,
        'createdTime': created_str,
    }


def _date_str(val):
    if val is None:
        return ''
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)


# ─── FK resolution helpers ────────────────────────────────────────────────────

def _lookup_client_id(db, company_name):
    """Return client.id for a given company_name, or None."""
    if not company_name:
        return None
    ph = '%s' if get_db_type() == 'postgres' else '?'
    if get_db_type() == 'postgres':
        with db.cursor() as cur:
            cur.execute(f"SELECT id FROM clients WHERE company_name = {ph}", (company_name,))
            row = cur.fetchone()
            return row['id'] if row else None
    else:
        row = db.execute(f"SELECT id FROM clients WHERE company_name = {ph}", (company_name,)).fetchone()
        return row['id'] if row else None


def _lookup_campaign_id(db, campaign_name):
    """Return campaigns.id for a given campaign name, or None."""
    if not campaign_name:
        return None
    ph = '%s' if get_db_type() == 'postgres' else '?'
    if get_db_type() == 'postgres':
        with db.cursor() as cur:
            cur.execute(f"SELECT id FROM campaigns WHERE name = {ph}", (campaign_name,))
            row = cur.fetchone()
            return row['id'] if row else None
    else:
        row = db.execute(f"SELECT id FROM campaigns WHERE name = {ph}", (campaign_name,)).fetchone()
        return row['id'] if row else None


# ─── Airtable fields → Postgres column dict ──────────────────────────────────

def _fields_to_pg(table, fields, db):
    """Convert Airtable-style fields dict to {pg_column: value} for INSERT/UPDATE."""
    pg = {}

    if table == 'clients':
        MAP = {
            'Company Name':    'company_name',
            'Contact Name':    'contact_name',
            'Contact Email':   'contact_email',
            'Contact Phone':   'contact_phone',
            'Portal Username': 'portal_username',
            'Status':          'status',
            'Client Status':   'status',
            'Notes':           'notes',
        }
        for at_key, pg_col in MAP.items():
            if at_key in fields:
                pg[pg_col] = fields[at_key]

    elif table == 'campaigns':
        MAP = {
            'Campaign Name': 'name',
            'Postcard Size': 'postcard_size',
            'Status':        'status',
            'Piece Count':   'piece_count',
            'Mail Date':     'mail_date',
            'Notes':         'notes',
        }
        for at_key, pg_col in MAP.items():
            if at_key in fields:
                pg[pg_col] = fields[at_key] if fields[at_key] != '' else None
        if 'Client' in fields:
            pg['client_id'] = _lookup_client_id(db, fields['Client'])

    elif table == 'artwork':
        MAP = {
            'Artwork Name': 'name',
            'Version':      'version',
            'Status':       'status',
            'Staff Notes':  'staff_notes',
            'Client Notes': 'client_notes',
        }
        for at_key, pg_col in MAP.items():
            if at_key in fields:
                pg[pg_col] = fields[at_key]
        if 'Client' in fields:
            pg['client_id'] = _lookup_client_id(db, fields['Client'])
        if 'Campaign' in fields:
            pg['campaign_id'] = _lookup_campaign_id(db, fields['Campaign'])

    elif table == 'invoices':
        MAP = {
            'Invoice Number': 'invoice_number',
            'Status':         'status',
            'Amount':         'amount',
            'Due Date':       'due_date',
            'Paid Date':      'paid_date',
            'Notes':          'notes',
        }
        for at_key, pg_col in MAP.items():
            if at_key in fields:
                pg[pg_col] = fields[at_key] if fields[at_key] != '' else None
        if 'Client' in fields:
            pg['client_id'] = _lookup_client_id(db, fields['Client'])
        if 'Campaign' in fields:
            pg['campaign_id'] = _lookup_campaign_id(db, fields['Campaign'])

    elif table == 'print_jobs':
        MAP = {
            'Job Name':    'job_name',
            'Piece Count': 'piece_count',
            'Status':      'status',
            'Print Date':  'print_date',
            'Mail Date':   'mail_date',
            'PDF URL':     'pdf_url',
            'Notes':       'notes',
        }
        for at_key, pg_col in MAP.items():
            if at_key in fields:
                pg[pg_col] = fields[at_key] if fields[at_key] != '' else None
        if 'Client' in fields:
            pg['client_id'] = _lookup_client_id(db, fields['Client'])
        if 'Campaign' in fields:
            pg['campaign_id'] = _lookup_campaign_id(db, fields['Campaign'])

    elif table == 'new_movers':
        MAP = {
            'Address':        'address',
            'City':           'city',
            'Zip':            'zip',
            'State':          'state',
            'County':         'county',
            'Sale Date':      'sale_date',
            'Sale Price':     'sale_price',
            'Tier':           'tier',
            'Year Built':     'year_built',
            'Square Ft':      'sqft',
            'Neighborhood':   'neighborhood',
            'Upload Batch':   'upload_batch',
            'Verify Status':  'verify_status',
            'Verify Message': 'verify_message',
        }
        for at_key, pg_col in MAP.items():
            if at_key in fields:
                pg[pg_col] = fields[at_key]

    elif table == 'users':
        MAP = {
            'Name':          'name',
            'Email':         'email',
            'Role':          'role',
            'Password Hash': 'password_hash',
            'Last Login':    'last_login',
        }
        for at_key, pg_col in MAP.items():
            if at_key in fields:
                pg[pg_col] = fields[at_key] if fields[at_key] != '' else None
        if 'Client' in fields:
            pg['client_id'] = _lookup_client_id(db, fields['Client'])

    return pg


# ─── Filter formula → Python predicate ───────────────────────────────────────

def _make_filter(formula):
    """
    Convert a simple Airtable-style formula string to a Python predicate
    that operates on the 'fields' dict of a record.

    Supported patterns:
      {FieldName}='value'
      FieldName=''
      AND(cond1, cond2, ...)
    """
    if not formula:
        return lambda rec: True

    formula = formula.strip()

    # AND(...) — recursively parse sub-conditions
    and_match = re.match(r'^AND\((.+)\)$', formula, re.IGNORECASE | re.DOTALL)
    if and_match:
        # Split top-level commas (not inside nested parens)
        inner = and_match.group(1)
        parts = _split_top_level(inner)
        preds = [_make_filter(p.strip()) for p in parts]
        return lambda rec, ps=preds: all(p(rec) for p in ps)

    # {FieldName}='value' or {FieldName}="" or {FieldName}=''
    m = re.match(r"^\{([^}]+)\}='([^']*)'$", formula)
    if m:
        field_name, value = m.group(1), m.group(2)
        return lambda rec, f=field_name, v=value: str(rec['fields'].get(f, '')) == v

    # FieldName='value' (no braces)
    m = re.match(r"^([A-Za-z0-9_ ]+)='([^']*)'$", formula)
    if m:
        field_name, value = m.group(1).strip(), m.group(2)
        return lambda rec, f=field_name, v=value: str(rec['fields'].get(f, '')) == v

    # {FieldName}="" (empty string with double quotes)
    m = re.match(r'^\{([^}]+)\}=""$', formula)
    if m:
        field_name = m.group(1)
        return lambda rec, f=field_name: str(rec['fields'].get(f, '')) == ''

    # FieldName="" (no braces, double quotes)
    m = re.match(r'^([A-Za-z0-9_ ]+)=""$', formula)
    if m:
        field_name = m.group(1).strip()
        return lambda rec, f=field_name: str(rec['fields'].get(f, '')) == ''

    # If we can't parse, allow everything (safe default)
    return lambda rec: True


def _split_top_level(s):
    """Split string by commas at the top level (not inside parens)."""
    parts = []
    depth = 0
    current = []
    for ch in s:
        if ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append(''.join(current).strip())
    return parts


# ─── Public API ───────────────────────────────────────────────────────────────

def _fetchall(db, sql, params=()):
    if get_db_type() == 'postgres':
        with db.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    else:
        rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def _fetchone(db, sql, params=()):
    if get_db_type() == 'postgres':
        with db.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None
    else:
        row = db.execute(sql, params).fetchone()
        return dict(row) if row else None


def _execute(db, sql, params=()):
    if get_db_type() == 'postgres':
        with db.cursor() as cur:
            cur.execute(sql, params)
            # Try to get RETURNING id
            try:
                row = cur.fetchone()
                return dict(row) if row else None
            except Exception:
                return None
    else:
        cur = db.execute(sql, params)
        return {'id': cur.lastrowid}


def get_records(table, filter_formula=None, fields=None, max_records=None, filter=None):
    """
    Returns list of {'id': int, 'fields': {...}, 'createdTime': str} dicts.
    filter_formula: Airtable-style formula string (basic support)
    fields: ignored (we always return all fields)
    max_records: limit
    filter: alias for filter_formula
    """
    init_db()
    formula = filter_formula or filter
    predicate = _make_filter(formula)

    sql = _SELECT[table]
    limit_clause = f" LIMIT {int(max_records)}" if max_records else ""
    # For new_movers with zip='' filter, use SQL directly for performance
    if table == 'new_movers' and formula and ("Zip=''" in formula or 'Zip=""' in formula):
        ph = PH
        sql = _SELECT['new_movers'] + f" WHERE (zip IS NULL OR zip = '') ORDER BY id {limit_clause}"
        with get_db() as db:
            rows = _fetchall(db, sql)
        return [_row_to_record(table, r) for r in rows]

    alias = _table_alias(table)
    order_col = f"{alias}.id" if alias != table else "id"
    sql_with_limit = sql + f" ORDER BY {order_col}{limit_clause}"
    with get_db() as db:
        rows = _fetchall(db, sql_with_limit)

    records = [_row_to_record(table, r) for r in rows]

    if formula:
        records = [r for r in records if predicate(r)]

    if max_records:
        records = records[:int(max_records)]

    return records


def get_record(table, record_id):
    """Returns a single {'id': int, 'fields': {...}} dict."""
    init_db()
    alias = _table_alias(table)
    sql = _SELECT[table] + f" WHERE {alias}.id = {PH}"
    with get_db() as db:
        row = _fetchone(db, sql, (int(record_id),))
    if not row:
        raise Exception(f"Record {record_id} not found in {table}")
    return _row_to_record(table, row)


def create_record(table, fields):
    """Create a record. Returns {'id': int, 'fields': {...}}."""
    init_db()
    with get_db() as db:
        pg = _fields_to_pg(table, fields, db)
        if not pg:
            raise Exception(f"No valid fields provided for {table}")
        cols = list(pg.keys())
        vals = [pg[c] for c in cols]
        ph = PH
        placeholders = ', '.join([ph] * len(cols))
        col_str = ', '.join(cols)
        if get_db_type() == 'postgres':
            sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) RETURNING id"
        else:
            sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})"
        result = _execute(db, sql, vals)
        if get_db_type() == 'postgres':
            db.commit()
            new_id = result['id']
        else:
            db.commit()
            new_id = result['id']
    return get_record(table, new_id)


def update_record(table, record_id, fields):
    """Update a record. Returns the updated {'id': int, 'fields': {...}}."""
    init_db()
    with get_db() as db:
        pg = _fields_to_pg(table, fields, db)
        if not pg:
            return get_record(table, record_id)
        ph = PH
        set_clause = ', '.join([f"{col} = {ph}" for col in pg.keys()])
        vals = list(pg.values()) + [int(record_id)]
        sql = f"UPDATE {table} SET {set_clause} WHERE id = {ph}"
        _execute(db, sql, vals)
        db.commit()
    return get_record(table, record_id)


def delete_record(table, record_id):
    """Delete a record."""
    init_db()
    ph = PH
    with get_db() as db:
        _execute(db, f"DELETE FROM {table} WHERE id = {ph}", (int(record_id),))
        db.commit()
    return {'deleted': True, 'id': int(record_id)}


def create_records_batch(table, records_list):
    """Create multiple records. Returns list of created records."""
    created = []
    for fields in records_list:
        try:
            rec = create_record(table, fields)
            created.append(rec)
        except Exception:
            pass
    return created


def find_user_by_email(email):
    """Find user by email. Returns record dict or None."""
    records = get_records('users')
    for r in records:
        if r['fields'].get('Email', '').lower() == email.lower():
            return r
    return None


def at_str(value):
    """Escape a string for safe use inside filter formula single quotes."""
    return str(value).replace("'", "\\'")


def _table_alias(table):
    """Return the main table alias used in SELECT queries."""
    aliases = {
        'clients':    'c',
        'campaigns':  'c',
        'artwork':    'a',
        'invoices':   'i',
        'print_jobs': 'pj',
        'new_movers': 'new_movers',
        'users':      'u',
    }
    return aliases.get(table, table)
