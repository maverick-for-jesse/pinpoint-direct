"""
Smart CSV parser for the master address list uploader.
Handles: new movers (qPublic format), permit lists (various county formats), generic address lists.
"""

import pandas as pd
import io
import hashlib
from datetime import date
from app.utils.permit_classifier import classify_permit

# Column name mappings — maps variations to standard names
COLUMN_MAP = {
    'first_name':          ['first_name', 'firstname', 'first name', 'fname', 'first', 'buyer', 'buyer_name', 'owner', 'owner_name', 'applicant'],
    'last_name':           ['last_name', 'lastname', 'last name', 'lname', 'last', 'surname'],
    'address1':            ['address1', 'address_1', 'address', 'street', 'street_address', 'addr', 'mailing_address', 'property_address', 'site_address', 'job_address', 'location'],
    'address2':            ['address2', 'address_2', 'apt', 'suite', 'unit'],
    'city':                ['city', 'town', 'municipality'],
    'state':               ['state', 'st', 'province'],
    'zip':                 ['zip', 'zip_code', 'zipcode', 'postal', 'postal_code'],
    'permit_description':  ['permit_description', 'permit_type', 'description', 'work_description', 'type_of_work', 'scope', 'permit description', 'type', 'work type'],
    'permit_value':        ['permit_value', 'value', 'job_value', 'estimated_value', 'cost', 'valuation', 'estimated cost'],
    'permit_date':         ['permit_date', 'issued_date', 'issue_date', 'date_issued', 'date', 'application_date'],
    'permit_number':       ['permit_number', 'permit_no', 'permit #', 'permit_id', 'number'],
    'sale_price':          ['sale_price', 'price', 'amount', 'sales_price', 'sale_amount'],
    'sale_date':           ['sale_date', 'transfer_date', 'deed_date', 'close_date', 'closing_date'],
}


def _normalize_col(col):
    return col.strip().lower().replace(' ', '_').replace('-', '_').replace('/', '_')


def _map_columns(df):
    normalized = {_normalize_col(c): c for c in df.columns}
    mapping = {}
    for standard, variants in COLUMN_MAP.items():
        for v in variants:
            nv = _normalize_col(v)
            if nv in normalized:
                mapping[normalized[nv]] = standard
                break
    return df.rename(columns=mapping)


def _detect_list_type(df):
    """Detect whether this looks like new_mover, permit, or generic."""
    cols = set(df.columns)
    if any(c in cols for c in ['permit_description', 'permit_type', 'permit_number', 'permit_date']):
        return 'permit'
    if any(c in cols for c in ['sale_date', 'sale_price', 'transfer_date']):
        return 'new_mover'
    return 'generic'


def _make_hash(address1, zip_code):
    key = (address1 or '').lower().strip() + (zip_code or '').strip()
    return hashlib.md5(key.encode()).hexdigest()


def _parse_value(val_str):
    if not val_str:
        return None
    try:
        return float(str(val_str).replace('$', '').replace(',', '').strip())
    except (ValueError, TypeError):
        return None


def parse_master_list_file(file_storage, county, list_type_override=None, batch_label=None):
    """
    Parse an uploaded CSV/Excel into master_addresses records.

    Args:
        file_storage: werkzeug FileStorage object
        county: string e.g. "Coweta County GA"
        list_type_override: force 'new_mover', 'permit', or 'generic' (optional)
        batch_label: string label for this upload batch

    Returns:
        records: list of dicts ready for master_addresses insert
        detected_type: the detected list type
        category_summary: dict of {permit_category: count} (for permit lists)
        warnings: list of warning strings
        skipped: count of skipped rows
    """
    filename = file_storage.filename.lower()
    content = file_storage.read()
    warnings = []
    today = date.today().isoformat()
    batch = batch_label or f"{county} upload {today}"
    source_file = file_storage.filename

    try:
        if filename.endswith('.csv'):
            df = None
            for enc in ('utf-8', 'utf-8-sig', 'latin-1', 'cp1252'):
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding=enc, dtype=str)
                    break
                except UnicodeDecodeError:
                    continue
            if df is None:
                raise ValueError("Could not decode CSV file with any supported encoding.")
        elif filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(io.BytesIO(content), dtype=str)
        else:
            raise ValueError("Unsupported file type. Upload CSV or Excel (.xlsx/.xls).")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not read file: {e}")

    df = _map_columns(df)
    df = df.fillna('')

    detected_type = list_type_override or _detect_list_type(df)

    if 'address1' not in df.columns:
        warnings.append("⚠️ Could not find an address column. Check your file format.")

    records = []
    skipped = 0
    seen_hashes = set()

    for _, row in df.iterrows():
        address1 = row.get('address1', '').strip()
        zip_code = str(row.get('zip', '')).strip().split('.')[0]
        city = row.get('city', '').strip()
        state = row.get('state', '').strip() or 'GA'
        first_name = row.get('first_name', '').strip()
        last_name = row.get('last_name', '').strip()

        if not address1:
            skipped += 1
            continue

        # Dedup within this upload
        h = _make_hash(address1, zip_code)
        if h in seen_hashes:
            skipped += 1
            continue
        seen_hashes.add(h)

        permit_description = row.get('permit_description', '').strip()
        permit_category = classify_permit(permit_description) if detected_type == 'permit' else None
        permit_value = _parse_value(row.get('permit_value', ''))
        permit_date = row.get('permit_date', '').strip()
        permit_number = row.get('permit_number', '').strip()

        rec = {
            'first_name':         first_name,
            'last_name':          last_name,
            'address1':           address1,
            'address2':           row.get('address2', '').strip(),
            'city':               city,
            'state':              state,
            'zip':                zip_code,
            'county':             county,
            'list_type':          detected_type,
            'permit_category':    permit_category,
            'permit_description': permit_description,
            'permit_value':       permit_value,
            'permit_date':        permit_date,
            'permit_number':      permit_number,
            'upload_batch':       batch,
            'source_file':        source_file,
            'added_date':         today,
            'address_hash':       h,
        }
        records.append(rec)

    # Build category summary for permit lists
    category_summary = {}
    if detected_type == 'permit':
        for r in records:
            cat = r['permit_category'] or 'Other'
            category_summary[cat] = category_summary.get(cat, 0) + 1

    return records, detected_type, category_summary, warnings, skipped
