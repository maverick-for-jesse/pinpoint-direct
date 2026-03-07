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
        }
    return token, base_id, tables

TOKEN, BASE_ID, TABLES = _load_config()
HEADERS  = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'}
BASE_URL = f'https://api.airtable.com/v0/{BASE_ID}'


def get_records(table_key, filter_formula=None, fields=None):
    url = f"{BASE_URL}/{TABLES[table_key]}"
    params = {}
    if filter_formula:
        params['filterByFormula'] = filter_formula
    if fields:
        for f in fields:
            params.setdefault('fields[]', []).append(f)
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    return resp.json().get('records', [])


def get_record(table_key, record_id):
    url = f"{BASE_URL}/{TABLES[table_key]}/{record_id}"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def create_record(table_key, fields):
    url = f"{BASE_URL}/{TABLES[table_key]}"
    resp = requests.post(url, headers=HEADERS, json={'fields': fields})
    resp.raise_for_status()
    return resp.json()


def update_record(table_key, record_id, fields):
    url = f"{BASE_URL}/{TABLES[table_key]}/{record_id}"
    resp = requests.patch(url, headers=HEADERS, json={'fields': fields})
    resp.raise_for_status()
    return resp.json()


def delete_record(table_key, record_id):
    url = f"{BASE_URL}/{TABLES[table_key]}/{record_id}"
    resp = requests.delete(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def find_user_by_email(email):
    records = get_records('users', filter_formula=f"{{Email}}='{email}'")
    return records[0] if records else None
