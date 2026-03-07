import os
import requests
import base64
import json


def get_api_key():
    key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not key:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config', 'gemini.json')
        if os.path.exists(config_path):
            with open(config_path) as f:
                key = json.load(f).get('api_key')
    return key


def generate_image(prompt, aspect_ratio='LANDSCAPE'):
    """
    Generate an image using Gemini 2.0 Flash image generation.
    Returns base64-encoded PNG string or raises on error.
    """
    api_key = get_api_key()
    if not api_key:
        raise ValueError("GEMINI_API_KEY not configured. Add it in Railway Variables.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp-image-generation:generateContent?key={api_key}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}
    }

    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()

    data = resp.json()
    for part in data.get('candidates', [{}])[0].get('content', {}).get('parts', []):
        if 'inlineData' in part:
            return part['inlineData']['data']

    raise ValueError("No image returned from Gemini. Try a different prompt.")
