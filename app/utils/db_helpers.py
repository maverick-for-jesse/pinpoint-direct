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
               c.list_count, c.quote_amount,
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
    'mailing_jobs': """
        SELECT mj.id, mj.job_name, mj.status, mj.piece_count, mj.sheet_count,
               mj.list_filename, mj.list_uploaded_at, mj.cass_status, mj.cass_notes,
               mj.print_file_url, mj.print_started_at, mj.print_completed_at,
               mj.tray_count, mj.tray_notes, mj.drop_date, mj.bmeu_location,
               mj.form_3602_ref, mj.mail_class, mj.postage_paid, mj.notes, mj.created_at,
               mj.campaign_id, mj.client_id,
               c.name AS campaign_name,
               cl.company_name AS client_name
        FROM mailing_jobs mj
        LEFT JOIN campaigns c ON mj.campaign_id = c.id
        LEFT JOIN clients cl ON mj.client_id = cl.id
    """,
    'mailing_trays': """
        SELECT mt.id, mt.tray_number, mt.piece_count, mt.zip_range, mt.tray_label, mt.created_at,
               mt.mailing_job_id,
               mj.job_name AS job_name
        FROM mailing_trays mt
        LEFT JOIN mailing_jobs mj ON mt.mailing_job_id = mj.id
    """,
    'design_requests': """
        SELECT dr.id, dr.status, dr.business_name, dr.industry, dr.campaign_goal,
               dr.products_services, dr.headline_ideas, dr.key_selling_points,
               dr.call_to_action, dr.cta_url, dr.promo_code, dr.brand_colors, dr.brand_tone,
               dr.target_audience, dr.mailing_list_status, dr.return_address,
               dr.quantity, dr.target_mail_date, dr.additional_notes,
               dr.logo_files, dr.product_files, dr.inspiration_files,
               dr.proof_file, dr.proof_uploaded_at, dr.revision_round, dr.revision_limit,
               dr.client_feedback, dr.admin_notes, dr.fiverr_order_ref,
               dr.submitted_at, dr.approved_at, dr.created_at,
               dr.client_id, dr.campaign_id,
               cl.company_name AS client_name,
               c.name AS campaign_name
        FROM design_requests dr
        LEFT JOIN clients cl ON dr.client_id = cl.id
        LEFT JOIN campaigns c ON dr.campaign_id = c.id
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
            'List Count':    r.get('list_count') or 0,
            'Quote Amount':  r.get('quote_amount') or 0.0,
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
    elif table == 'mailing_jobs':
        fields = {
            'Job Name':           r.get('job_name') or '',
            'Status':             r.get('status') or 'Address Processing',
            'Piece Count':        r.get('piece_count') or 0,
            'Sheet Count':        r.get('sheet_count') or 0,
            'List Filename':      r.get('list_filename') or '',
            'List Uploaded At':   _date_str(r.get('list_uploaded_at')),
            'CASS Status':        r.get('cass_status') or 'Pending',
            'CASS Notes':         r.get('cass_notes') or '',
            'Print File URL':     r.get('print_file_url') or '',
            'Print Started At':   _date_str(r.get('print_started_at')),
            'Print Completed At': _date_str(r.get('print_completed_at')),
            'Tray Count':         r.get('tray_count') or 0,
            'Tray Notes':         r.get('tray_notes') or '',
            'Drop Date':          _date_str(r.get('drop_date')),
            'BMEU Location':      r.get('bmeu_location') or '',
            'Form 3602 Ref':      r.get('form_3602_ref') or '',
            'Mail Class':         r.get('mail_class') or 'USPS Marketing Mail',
            'Postage Paid':       float(r['postage_paid']) if r.get('postage_paid') is not None else 0.0,
            'Notes':              r.get('notes') or '',
            'Campaign':           r.get('campaign_name') or '',
            'Client':             r.get('client_name') or '',
        }
    elif table == 'mailing_trays':
        fields = {
            'Tray Number':    r.get('tray_number') or 0,
            'Piece Count':    r.get('piece_count') or 0,
            'ZIP Range':      r.get('zip_range') or '',
            'Tray Label':     r.get('tray_label') or '',
            'Job Name':       r.get('job_name') or '',
            'Mailing Job ID': r.get('mailing_job_id'),
        }
    elif table == 'design_requests':
        fields = {
            'Status':               r.get('status') or 'Draft',
            'Business Name':        r.get('business_name') or '',
            'Industry':             r.get('industry') or '',
            'Campaign Goal':        r.get('campaign_goal') or '',
            'Products Services':    r.get('products_services') or '',
            'Headline Ideas':       r.get('headline_ideas') or '',
            'Key Selling Points':   r.get('key_selling_points') or '',
            'Call To Action':       r.get('call_to_action') or '',
            'CTA URL':              r.get('cta_url') or '',
            'Promo Code':           r.get('promo_code') or '',
            'Brand Colors':         r.get('brand_colors') or '',
            'Brand Tone':           r.get('brand_tone') or '',
            'Target Audience':      r.get('target_audience') or '',
            'Mailing List Status':  r.get('mailing_list_status') or 'Have one',
            'Return Address':       r.get('return_address') or '',
            'Quantity':             r.get('quantity'),
            'Target Mail Date':     _date_str(r.get('target_mail_date')),
            'Additional Notes':     r.get('additional_notes') or '',
            'Logo Files':           r.get('logo_files') or '',
            'Product Files':        r.get('product_files') or '',
            'Inspiration Files':    r.get('inspiration_files') or '',
            'Proof File':           r.get('proof_file') or '',
            'Proof Uploaded At':    _date_str(r.get('proof_uploaded_at')),
            'Revision Round':       r.get('revision_round') or 0,
            'Revision Limit':       r.get('revision_limit') or 2,
            'Client Feedback':      r.get('client_feedback') or '',
            'Admin Notes':          r.get('admin_notes') or '',
            'Fiverr Ref':           r.get('fiverr_order_ref') or '',
            'Submitted At':         _date_str(r.get('submitted_at')),
            'Approved At':          _date_str(r.get('approved_at')),
            'Client':               r.get('client_name') or '',
            'Campaign':             r.get('campaign_name') or '',
            'client_id':            r.get('client_id'),
            'campaign_id':          r.get('campaign_id'),
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
            'List Count':    'list_count',
            'Quote Amount':  'quote_amount',
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

    elif table == 'mailing_jobs':
        MAP = {
            'Job Name':           'job_name',
            'Status':             'status',
            'Piece Count':        'piece_count',
            'Sheet Count':        'sheet_count',
            'List Filename':      'list_filename',
            'List Uploaded At':   'list_uploaded_at',
            'CASS Status':        'cass_status',
            'CASS Notes':         'cass_notes',
            'Print File URL':     'print_file_url',
            'Print Started At':   'print_started_at',
            'Print Completed At': 'print_completed_at',
            'Tray Count':         'tray_count',
            'Tray Notes':         'tray_notes',
            'Drop Date':          'drop_date',
            'BMEU Location':      'bmeu_location',
            'Form 3602 Ref':      'form_3602_ref',
            'Mail Class':         'mail_class',
            'Postage Paid':       'postage_paid',
            'Notes':              'notes',
        }
        for at_key, pg_col in MAP.items():
            if at_key in fields:
                pg[pg_col] = fields[at_key] if fields[at_key] != '' else None
        if 'Client' in fields:
            pg['client_id'] = _lookup_client_id(db, fields['Client'])
        if 'Campaign' in fields:
            pg['campaign_id'] = _lookup_campaign_id(db, fields['Campaign'])

    elif table == 'mailing_trays':
        MAP = {
            'Tray Number':    'tray_number',
            'Piece Count':    'piece_count',
            'ZIP Range':      'zip_range',
            'Tray Label':     'tray_label',
            'Mailing Job ID': 'mailing_job_id',
        }
        for at_key, pg_col in MAP.items():
            if at_key in fields:
                pg[pg_col] = fields[at_key] if fields[at_key] != '' else None

    elif table == 'design_requests':
        MAP = {
            'Status':              'status',
            'Business Name':       'business_name',
            'Industry':            'industry',
            'Campaign Goal':       'campaign_goal',
            'Products Services':   'products_services',
            'Headline Ideas':      'headline_ideas',
            'Key Selling Points':  'key_selling_points',
            'Call To Action':      'call_to_action',
            'CTA URL':             'cta_url',
            'Promo Code':          'promo_code',
            'Brand Colors':        'brand_colors',
            'Brand Tone':          'brand_tone',
            'Target Audience':     'target_audience',
            'Mailing List Status': 'mailing_list_status',
            'Return Address':      'return_address',
            'Quantity':            'quantity',
            'Target Mail Date':    'target_mail_date',
            'Additional Notes':    'additional_notes',
            'Logo Files':          'logo_files',
            'Product Files':       'product_files',
            'Inspiration Files':   'inspiration_files',
            'Proof File':          'proof_file',
            'Proof Uploaded At':   'proof_uploaded_at',
            'Revision Round':      'revision_round',
            'Revision Limit':      'revision_limit',
            'Client Feedback':     'client_feedback',
            'Admin Notes':         'admin_notes',
            'Fiverr Ref':          'fiverr_order_ref',
            'Submitted At':        'submitted_at',
            'Approved At':         'approved_at',
            'client_id':           'client_id',
            'campaign_id':         'campaign_id',
        }
        for at_key, pg_col in MAP.items():
            if at_key in fields:
                pg[pg_col] = fields[at_key] if fields[at_key] != '' else None

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
    """Create multiple records. Returns list of created record IDs (lightweight — no re-fetch)."""
    created = []
    init_db()
    ph = PH
    with get_db() as db:
        for fields in records_list:
            try:
                pg = _fields_to_pg(table, fields, db)
                if not pg:
                    continue
                cols = list(pg.keys())
                vals = [pg[c] for c in cols]
                placeholders = ', '.join([ph] * len(cols))
                col_str = ', '.join(cols)
                if get_db_type() == 'postgres':
                    sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) RETURNING id"
                    result = _execute(db, sql, vals)
                    created.append(result['id'])
                else:
                    sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})"
                    result = _execute(db, sql, vals)
                    created.append(result['id'])
            except Exception:
                pass
        db.commit()
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
        'clients':          'c',
        'campaigns':        'c',
        'artwork':          'a',
        'invoices':         'i',
        'print_jobs':       'pj',
        'new_movers':       'new_movers',
        'users':            'u',
        'mailing_jobs':     'mj',
        'mailing_trays':    'mt',
        'design_requests':  'dr',
    }
    return aliases.get(table, table)
