"""
Parser for qPublic / Schneider Corp county property transfer CSVs.
Handles Coweta County GA format — expandable to other counties.
"""

import csv
import io
from datetime import datetime

# County config: name → default city/state for address appending
COUNTY_CONFIG = {
    'Coweta County GA': {
        'state': 'GA',
        'city': 'Newnan',  # default — most addresses are Newnan
    },
    # Add more counties here as needed
}

# Price tiers
TIER_STANDARD      = 'Standard'       # < $500k
TIER_PREMIUM       = 'Premium'        # $500k – $749,999
TIER_ULTRA_PREMIUM = 'Ultra-Premium'  # $750k+


def _parse_price(price_str):
    """Parse '$285,400.00' → 285400.0"""
    if not price_str:
        return 0.0
    return float(price_str.replace('$', '').replace(',', '').strip() or 0)


def _get_tier(price):
    if price >= 750_000:
        return TIER_ULTRA_PREMIUM
    elif price >= 500_000:
        return TIER_PREMIUM
    else:
        return TIER_STANDARD


def parse_county_csv(file_obj, county='Coweta County GA', batch_label=None):
    """
    Parse a qPublic property transfer CSV.

    Returns:
        records  — list of dicts ready for Airtable
        stats    — summary dict (total_rows, imported, skipped, by_tier)
        warnings — list of warning strings
    """
    cfg = COUNTY_CONFIG.get(county, {'state': 'GA', 'city': ''})
    today = datetime.today().strftime('%Y-%m-%d')
    batch = batch_label or f"{county} upload {today}"

    if hasattr(file_obj, 'read'):
        raw = file_obj.read()
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8-sig')  # handle BOM
        lines = raw.splitlines()
    else:
        lines = file_obj.splitlines()

    reader = csv.DictReader(lines)

    records = []
    skipped = 0
    warnings = []
    seen = set()  # deduplicate by (address, sale_date)

    for row in reader:
        # Normalize field names (strip whitespace)
        row = {k.strip(): v.strip() for k, v in row.items()}

        # Only want: Qualified = "Qualified", Reason = "FM", Parcel Class = "Residential"
        if row.get('Qualified Sales') != 'Qualified':
            skipped += 1
            continue
        if row.get('Reason') != 'FM':
            skipped += 1
            continue
        # Normalize parcel class (may have trailing spaces)
        parcel_class = row.get('Parcel  Class ', row.get('Parcel Class', '')).strip()
        if parcel_class != 'Residential':
            skipped += 1
            continue

        address = row.get('Address', '').strip()
        if not address:
            skipped += 1
            continue

        sale_date_raw = row.get('Sale Date', '').strip()
        # Deduplicate: same address + same sale date
        dedup_key = (address.upper(), sale_date_raw)
        if dedup_key in seen:
            skipped += 1
            continue
        seen.add(dedup_key)

        # Parse sale date MM/DD/YYYY → YYYY-MM-DD
        try:
            sale_date = datetime.strptime(sale_date_raw, '%m/%d/%Y').strftime('%Y-%m-%d')
        except ValueError:
            sale_date = None

        price = _parse_price(row.get('Sale Price', ''))
        tier = _get_tier(price)

        year_built_raw = row.get('Year  Built ', row.get('Year Built', '')).strip()
        try:
            year_built = int(year_built_raw) if year_built_raw else None
        except ValueError:
            year_built = None

        sqft_raw = row.get('Square Ft ', row.get('Square Ft', '')).strip()
        try:
            sqft = int(sqft_raw.replace(',', '')) if sqft_raw else None
        except ValueError:
            sqft = None

        neighborhood = row.get('Neighborhood', '').strip()
        # Try to extract city from neighborhood label (e.g. "UL-Newnan HS-...")
        city = cfg['city']

        record = {
            'Address':       address,
            'City':          city,
            'State':         cfg['state'],
            'County':        county,
            'Tier':          tier,
            'Neighborhood':  neighborhood,
            'Upload Batch':  batch,
            'Uploaded Date': today,
        }
        if sale_date:
            record['Sale Date'] = sale_date
        if price:
            record['Sale Price'] = price
        if year_built:
            record['Year Built'] = year_built
        if sqft:
            record['Square Ft'] = sqft

        records.append(record)

    by_tier = {}
    for r in records:
        t = r['Tier']
        by_tier[t] = by_tier.get(t, 0) + 1

    stats = {
        'total_rows': len(records) + skipped,
        'imported':   len(records),
        'skipped':    skipped,
        'by_tier':    by_tier,
    }

    return records, stats, warnings
