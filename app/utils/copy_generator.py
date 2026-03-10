import requests
import json
import os


def get_gemini_key():
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'config', 'gemini.json'
    )
    if os.path.exists(config_path):
        with open(config_path) as f:
            key = json.load(f).get('api_key')
        if key:
            return ('gemini', key)
    # Fallback: env vars
    key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if key:
        return ('gemini', key)
    # Fallback: xAI Grok
    xai_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'config', 'xai.json'
    )
    if os.path.exists(xai_path):
        with open(xai_path) as f:
            key = json.load(f).get('api_key')
        if key:
            return ('xai', key)
    key = os.getenv('XAI_API_KEY')
    if key:
        return ('xai', key)
    raise ValueError("No AI API key configured. Add config/gemini.json or config/xai.json.")


def _generate_with_gemini(api_key, system_prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": system_prompt}]}],
        "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"}
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    text = resp.json()['candidates'][0]['content']['parts'][0]['text']
    return json.loads(text)


def _generate_with_xai(api_key, system_prompt):
    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "grok-2-latest",
        "messages": [
            {"role": "system", "content": "You are an expert direct mail copywriter. Return only valid JSON as instructed."},
            {"role": "user", "content": system_prompt}
        ],
        "temperature": 0.8
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    text = resp.json()['choices'][0]['message']['content']
    # Strip markdown code fences if present
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text[3:]
        if text.endswith('```'):
            text = text[:-3]
    return json.loads(text.strip())


def generate_postcard_copy(business_name, business_type, offer_description, target_audience='local customers'):
    """
    Generate 2 headline + copy options for a postcard.
    Returns dict with option_a and option_b, each having:
    headline, subheadline, body, cta, image_prompt
    """
    provider, api_key = get_gemini_key()

    system_prompt = f"""You are an expert direct mail copywriter specializing in 6x9 postcards for local businesses.
Generate compelling postcard copy that gets recipients to take action.
For a {business_type} called "{business_name}" with this offer: {offer_description}
Target audience: {target_audience}

Return ONLY valid JSON with this exact structure:
{{
  "option_a": {{
    "headline": "Bold 4-8 word headline",
    "subheadline": "Supporting line that adds detail",
    "body": "2-3 sentences max. Clear, benefit-focused.",
    "cta": "Call to action text (e.g. Call Today, Visit Us, Claim Your Offer)",
    "image_prompt": "Detailed Ideogram image generation prompt for the front background/hero image. Should be photorealistic, commercial-quality, relevant to the business type and offer. No text in image. Describe lighting, mood, composition."
  }},
  "option_b": {{
    "headline": "Alternative headline with different angle",
    "subheadline": "Supporting line",
    "body": "Different approach to the body copy.",
    "cta": "Alternative CTA",
    "image_prompt": "Different image concept for option B. Different angle, composition, or mood from option A."
  }}
}}"""

    if provider == 'gemini':
        return _generate_with_gemini(api_key, system_prompt)
    else:
        return _generate_with_xai(api_key, system_prompt)
