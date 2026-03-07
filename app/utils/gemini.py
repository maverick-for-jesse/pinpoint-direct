import os
import requests
import base64
import json
import time
from urllib.parse import quote


def get_hf_token():
    token = os.getenv('HF_TOKEN')
    if not token:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config', 'hf.json')
        if os.path.exists(config_path):
            with open(config_path) as f:
                token = json.load(f).get('token')
    return token


def generate_image(prompt, aspect_ratio='LANDSCAPE'):
    """
    Generate an image. Tries Hugging Face first, falls back to Pollinations.
    Returns base64-encoded PNG string or raises on error.
    """
    # Try Hugging Face Inference API first (more reliable)
    hf_token = get_hf_token()
    if hf_token:
        try:
            return _generate_hf(prompt, hf_token, aspect_ratio)
        except Exception as e:
            pass  # Fall through to Pollinations

    # Fall back to Pollinations with retries
    return _generate_pollinations(prompt, aspect_ratio)


def _generate_hf(prompt, token, aspect_ratio):
    """Hugging Face Inference API — SDXL."""
    width  = 1024 if aspect_ratio == 'LANDSCAPE' else 768
    height = 640  if aspect_ratio == 'LANDSCAPE' else 1024

    url = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "inputs": prompt,
        "parameters": {"width": width, "height": height}
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return base64.b64encode(resp.content).decode('utf-8')


def _generate_pollinations(prompt, aspect_ratio, retries=3):
    """Pollinations.ai with retry logic."""
    width  = 900 if aspect_ratio == 'LANDSCAPE' else 600
    height = 600 if aspect_ratio == 'LANDSCAPE' else 800

    encoded = quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&nologo=true&seed={int(time.time())}"

    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            return base64.b64encode(resp.content).decode('utf-8')
        except Exception as e:
            last_err = e
            time.sleep(3)

    raise ValueError(f"Image generation failed after {retries} attempts: {last_err}")
