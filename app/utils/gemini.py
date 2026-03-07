import os
import requests
import base64
import json

# Load Gemini key from env or config
def get_api_key():
    key = os.getenv('GEMINI_API_KEY')
    if not key:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config', 'gemini.json')
        if os.path.exists(config_path):
            with open(config_path) as f:
                key = json.load(f).get('api_key')
    return key or os.getenv('GOOGLE_API_KEY')


def generate_image(prompt, aspect_ratio='LANDSCAPE'):
    """
    Generate an image using Google Imagen 3 via Gemini API.
    Returns base64-encoded PNG string or raises on error.
    aspect_ratio: LANDSCAPE (6x9 postcard) or PORTRAIT
    """
    api_key = get_api_key()
    if not api_key:
        raise ValueError("GEMINI_API_KEY not configured.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={api_key}"

    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "16:9" if aspect_ratio == "LANDSCAPE" else "4:3",
            "safetyFilterLevel": "block_only_high",
            "personGeneration": "allow_adult"
        }
    }

    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    predictions = data.get('predictions', [])
    if not predictions:
        raise ValueError("No image returned from Gemini API.")

    return predictions[0].get('bytesBase64Encoded', '')
