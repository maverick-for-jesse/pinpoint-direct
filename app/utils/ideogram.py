import requests
import json
import os
import base64
import concurrent.futures


def get_api_key():
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'config', 'ideogram.json'
    )
    with open(config_path) as f:
        return json.load(f)['api_key']


def generate_postcard_image(prompt, style_type='REALISTIC'):
    """Generate a 3:2 landscape image for postcard front. Returns base64 PNG."""
    api_key = get_api_key()
    resp = requests.post(
        'https://api.ideogram.ai/generate',
        headers={'Api-Key': api_key, 'Content-Type': 'application/json'},
        json={
            'image_request': {
                'prompt': prompt,
                'aspect_ratio': 'ASPECT_3_2',
                'model': 'V_2',
                'style_type': style_type,
                'magic_prompt_option': 'AUTO'
            }
        },
        timeout=60
    )
    resp.raise_for_status()
    data = resp.json()
    # Ideogram returns a URL, download and convert to base64
    img_url = data['data'][0]['url']
    img_resp = requests.get(img_url, timeout=30)
    return base64.b64encode(img_resp.content).decode('utf-8')


def generate_two_options(prompt_a, prompt_b, style_type='REALISTIC'):
    """Generate two different image options. Returns list of two base64 strings."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(generate_postcard_image, prompt_a, style_type)
        fb = ex.submit(generate_postcard_image, prompt_b, style_type)
        return [fa.result(), fb.result()]
