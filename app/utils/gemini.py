import os
import requests
import base64
import json
from urllib.parse import quote


def generate_image(prompt, aspect_ratio='LANDSCAPE'):
    """
    Generate an image using Pollinations.ai (free, no API key required).
    Returns base64-encoded PNG string or raises on error.
    """
    width  = 900 if aspect_ratio == 'LANDSCAPE' else 600
    height = 600 if aspect_ratio == 'LANDSCAPE' else 800

    encoded = quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&nologo=true&enhance=true"

    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    return base64.b64encode(resp.content).decode('utf-8')
