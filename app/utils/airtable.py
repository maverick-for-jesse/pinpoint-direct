import os
import json
import requests

def _load_config():
    # Prefer environment variables (Railway)
    token   = os.getenv('AIRTABLE_TOKEN')
    base_id = os.getenv('AIRTABLE_BASE_ID')
    tables  = None

    # Fall back to config file (local dev)
    if not token:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config', 'airtable.json')
        if os.path.exists(config_path):
            with open(config_path) as f:
                cfg = json.load(f)
            token   = cfg.get('token')
            base_id = cfg.get('base_id')
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

def _get_headers():
    token, _, _ = _load_config()
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

def _get_base_url():
    _, base_id, _ = _load_config()
    return f'https://api.airtable.com/v0/{base_id}'

def _get_tables():
    _, _, tables = _load_config()
    return tables


def get_records(table_key, filter_formula=None, fields=None, max_records=None):
    url = f"{_get_base_url()}/{_get_tables()[table_key]}"
    all_records = []
    offset = None

    while True:
        params = {}
        if filter_formula:
            params['filterByFormula'] = filter_formula
        if fields:
            params['fields[]'] = fields
        if offset:
            params['offset'] = offset
        if max_records:
            params['pageSize'] = min(100, max_records - len(all_records))

        resp = requests.get(url, headers=_get_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()
        all_records.extend(data.get('records', []))
        offset = data.get('offset')

        if not offset:
            break
        if max_records and len(all_records) >= max_records:
            break

    return all_records


def get_record(table_key, record_id):
    url = f"{_get_base_url()}/{_get_tables()[table_key]}/{record_id}"
    resp = requests.get(url, headers=_get_headers())
    resp.raise_for_status()
    return resp.json()


def create_record(table_key, fields):
    url = f"{_get_base_url()}/{_get_tables()[table_key]}"
    resp = requests.post(url, headers=_get_headers(), json={'fields': fields})
    resp.raise_for_status()
    return resp.json()


def update_record(table_key, record_id, fields):
    url = f"{_get_base_url()}/{_get_tables()[table_key]}/{record_id}"
    resp = requests.patch(url, headers=_get_headers(), json={'fields': fields})
    resp.raise_for_status()
    return resp.json()


def create_records_batch(table_key, records_list):
    """Create up to 10 records in a single API call. Returns list of created records."""
    url = f"{_get_base_url()}/{_get_tables()[table_key]}"
    payload = {'records': [{'fields': f} for f in records_list]}
    resp = requests.post(url, headers=_get_headers(), json=payload)
    resp.raise_for_status()
    return resp.json().get('records', [])


def delete_record(table_key, record_id):
    url = f"{_get_base_url()}/{_get_tables()[table_key]}/{record_id}"
    resp = requests.delete(url, headers=_get_headers())
    resp.raise_for_status()
    return resp.json()


def find_user_by_email(email):
    records = get_records('users', filter_formula=f"{{Email}}='{email}'")
    return records[0] if records else None


def at_str(value):
    """Escape a string for safe use inside Airtable filter formula single quotes."""
    return str(value).replace("'", "\\'")
