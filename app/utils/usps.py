import os
import json
import requests
import xml.etree.ElementTree as ET

def get_usps_user_id():
    key = os.getenv('USPS_USER_ID')
    if not key:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config', 'usps.json')
        if os.path.exists(config_path):
            with open(config_path) as f:
                key = json.load(f).get('user_id')
    return key


def verify_address(address1, city, state, zip5, address2=''):
    """
    Verify a single address via USPS Web Tools API.
    Returns dict with keys: success, address1, address2, city, state, zip5, zip4, message
    Falls back to basic format validation if no USPS key is configured.
    """
    user_id = get_usps_user_id()

    if not user_id:
        return _basic_validate(address1, city, state, zip5)

    xml = f"""<AddressValidateRequest USERID="{user_id}">
  <Revision>1</Revision>
  <Address ID="0">
    <Address1>{address2}</Address1>
    <Address2>{address1}</Address2>
    <City>{city}</City>
    <State>{state.upper()}</State>
    <Zip5>{zip5[:5]}</Zip5>
    <Zip4></Zip4>
  </Address>
</AddressValidateRequest>"""

    try:
        resp = requests.get(
            'https://secure.shippingapis.com/ShippingAPI.dll',
            params={'API': 'Verify', 'XML': xml},
            timeout=10
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        addr = root.find('Address')

        if addr is None:
            return {'success': False, 'message': 'No response from USPS'}

        error = addr.find('Error')
        if error is not None:
            desc = error.findtext('Description', 'Unknown error')
            return {'success': False, 'message': desc}

        return {
            'success':  True,
            'address1': addr.findtext('Address2', address1),
            'address2': addr.findtext('Address1', address2),
            'city':     addr.findtext('City', city),
            'state':    addr.findtext('State', state),
            'zip5':     addr.findtext('Zip5', zip5),
            'zip4':     addr.findtext('Zip4', ''),
            'message':  'Verified by USPS'
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}


def _basic_validate(address1, city, state, zip5):
    """Basic format validation when no USPS key is available."""
    STATES = {
        'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA',
        'KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ',
        'NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT',
        'VA','WA','WV','WI','WY','DC'
    }
    errors = []
    if not address1.strip():
        errors.append('Missing street address')
    if not city.strip():
        errors.append('Missing city')
    if state.upper() not in STATES:
        errors.append(f'Invalid state: {state}')
    z = zip5.strip().split('-')[0]
    if not z.isdigit() or len(z) != 5:
        errors.append(f'Invalid zip: {zip5}')

    if errors:
        return {'success': False, 'message': '; '.join(errors)}
    return {
        'success': True,
        'address1': address1.strip().upper(),
        'address2': '',
        'city': city.strip().upper(),
        'state': state.strip().upper(),
        'zip5': z,
        'zip4': '',
        'message': 'Format valid (no USPS key)'
    }


def verify_batch(records, progress_callback=None):
    """
    Verify a list of record dicts. Each dict needs: address1, city, state, zip.
    Returns list of result dicts with original record data + verify fields.
    """
    results = []
    for i, rec in enumerate(records):
        result = verify_address(
            address1=rec.get('address1', ''),
            city=rec.get('city', ''),
            state=rec.get('state', ''),
            zip5=rec.get('zip', ''),
            address2=rec.get('address2', '')
        )
        rec.update({
            'verify_status': 'verified' if result['success'] else 'failed',
            'verify_message': result.get('message', ''),
        })
        if result['success']:
            rec['address1'] = result.get('address1', rec.get('address1', ''))
            rec['city']     = result.get('city', rec.get('city', ''))
            rec['state']    = result.get('state', rec.get('state', ''))
            rec['zip']      = result.get('zip5', rec.get('zip', ''))
        results.append(rec)
        if progress_callback:
            progress_callback(i + 1, len(records))
    return results
