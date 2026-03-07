import pandas as pd
import io

# Map common column name variations to standard field names
COLUMN_MAP = {
    'first_name':  ['first_name','firstname','first name','fname','first'],
    'last_name':   ['last_name','lastname','last name','lname','last','surname'],
    'company':     ['company','company_name','business','organization','org'],
    'address1':    ['address1','address_1','address','street','street_address','addr','mailing_address'],
    'address2':    ['address2','address_2','apt','suite','unit'],
    'city':        ['city','town'],
    'state':       ['state','st','province'],
    'zip':         ['zip','zip_code','zipcode','postal','postal_code'],
    'offer_code':  ['offer_code','offer','code','promo','promo_code'],
}


def _normalize_col(col):
    return col.strip().lower().replace(' ', '_').replace('-', '_')


def _map_columns(df):
    """Map DataFrame columns to standard names."""
    normalized = {_normalize_col(c): c for c in df.columns}
    mapping = {}
    for standard, variants in COLUMN_MAP.items():
        for v in variants:
            if v in normalized:
                mapping[normalized[v]] = standard
                break
    return df.rename(columns=mapping)


def parse_list_file(file_storage):
    """
    Parse an uploaded CSV or Excel file.
    Returns (records: list[dict], warnings: list[str])
    """
    filename = file_storage.filename.lower()
    content = file_storage.read()
    warnings = []

    try:
        if filename.endswith('.csv'):
            # Try multiple encodings
            for enc in ('utf-8', 'latin-1', 'cp1252'):
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding=enc, dtype=str)
                    break
                except UnicodeDecodeError:
                    continue
        elif filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(io.BytesIO(content), dtype=str)
        else:
            raise ValueError("Unsupported file type. Please upload CSV or Excel (.xlsx/.xls).")
    except Exception as e:
        raise ValueError(f"Could not read file: {e}")

    # Normalize + map columns
    df = _map_columns(df)
    df = df.fillna('')

    # Check for required fields
    required = ['address1', 'city', 'state', 'zip']
    missing = [f for f in required if f not in df.columns]
    if missing:
        warnings.append(f"⚠️ Missing expected columns: {', '.join(missing)}. Address verification may be incomplete.")

    # Build records
    records = []
    for _, row in df.iterrows():
        rec = {
            'first_name':   row.get('first_name', '').strip(),
            'last_name':    row.get('last_name', '').strip(),
            'company':      row.get('company', '').strip(),
            'address1':     row.get('address1', '').strip(),
            'address2':     row.get('address2', '').strip(),
            'city':         row.get('city', '').strip(),
            'state':        row.get('state', '').strip(),
            'zip':          str(row.get('zip', '')).strip().split('.')[0],  # remove .0 from Excel
            'offer_code':   row.get('offer_code', '').strip(),
            'verify_status': 'pending',
            'verify_message': '',
        }
        # Skip completely empty rows
        if not any([rec['address1'], rec['city'], rec['first_name'], rec['last_name']]):
            continue
        records.append(rec)

    return records, warnings
