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
        raise ValueError("GEMINI_API_KEY not configured.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-preview-image-generation:generateContent?key={api_key}"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "responseMimeType": "image/png"
        }
    }

    resp = requests.post(url, json=payload, timeout=60)

    if not resp.ok:
        # Fallback to standard gemini-2.0-flash-exp
        url2 = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"
        payload2 = {
            "contents": [{"parts": [{"text": f"Generate a photorealistic image: {prompt}"}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}
        }
        resp = requests.post(url2, json=payload2, timeout=60)
        resp.raise_for_status()

    data = resp.json()

    # Extract base64 image from response
    candidates = data.get('candidates', [])
    if not candidates:
        raise ValueError("No image returned from Gemini API.")

    for part in candidates[0].get('content', {}).get('parts', []):
        if 'inlineData' in part:
            return part['inlineData']['data']

    raise ValueError("No image data in Gemini response.")
