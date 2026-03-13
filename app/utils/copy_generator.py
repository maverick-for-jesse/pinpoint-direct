import requests
import json
import os


def get_ai_provider():
    # Prefer xAI Grok (reliable text generation)
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
    # Fallback: Gemini
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'config', 'gemini.json'
    )
    if os.path.exists(config_path):
        with open(config_path) as f:
            key = json.load(f).get('api_key')
        if key:
            return ('gemini', key)
    raise ValueError("No AI API key configured. Add config/xai.json or config/gemini.json.")


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
        "model": "grok-3-mini",
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


def generate_campaign_copy(profile: dict, campaign: dict) -> dict:
    """
    Generate postcard copy using business profile + campaign data.
    Returns: {headlines: [str, str, str], body_copies: [str, str], ctas: [str, str, str]}

    profile keys: business_name, business_type, years_in_business,
                  average_transaction_value, top_services, best_customer_description,
                  customer_compliment, main_competitor, competitive_advantage
    campaign keys: what_promoting, offer_detail, offer_type, has_deadline,
                   deadline_date, desired_action
    """
    provider, api_key = get_ai_provider()

    # Build readable deadline text
    has_deadline = campaign.get('has_deadline') or False
    deadline_date = campaign.get('deadline_date')
    if has_deadline and deadline_date:
        deadline_text = str(deadline_date)
    elif has_deadline:
        deadline_text = 'Limited time'
    else:
        deadline_text = 'None'

    system_prompt = f"""You are an expert direct mail copywriter. Based on this business info and campaign details, generate compelling postcard copy.

BUSINESS: {profile.get('business_name', 'this business')}, {profile.get('business_type', 'local')} business, {profile.get('years_in_business', 'established')} years in business. Average transaction: ${profile.get('average_transaction_value', 'varies')}. Services: {profile.get('top_services', 'see below')}. Best customers: {profile.get('best_customer_description', 'local residents')}. Known for: {profile.get('customer_compliment', 'quality service')}. Differentiator vs {profile.get('main_competitor', 'competitors')}: {profile.get('competitive_advantage', 'superior service')}.

CAMPAIGN: Promoting {campaign.get('what_promoting', 'services')}. Offer type: {campaign.get('offer_type', 'special offer')}. Offer: {campaign.get('offer_detail', 'contact us for details')}. Deadline: {deadline_text}. Desired action: {campaign.get('desired_action', 'call us')}.

Generate:
- 3 headlines (max 10 words each): first benefit-focused, second urgency-focused, third curiosity-focused
- 2 body copy options (max 40 words each): punchy, direct, no fluff — each a complete standalone message
- 3 CTA options (max 8 words each): action-oriented

Return ONLY valid JSON with this exact structure (no markdown fences, no extra text):
{{"headlines": ["headline1", "headline2", "headline3"], "body_copies": ["body1", "body2"], "ctas": ["cta1", "cta2", "cta3"]}}"""

    if provider == 'gemini':
        return _generate_with_gemini(api_key, system_prompt)
    else:
        return _generate_with_xai(api_key, system_prompt)


def generate_postcard_copy(business_name, business_type, offer_description, target_audience='local customers'):
    """
    Generate 2 headline + copy options for a postcard.
    Returns dict with option_a and option_b, each having:
    headline, subheadline, body, cta, image_prompt
    """
    provider, api_key = get_ai_provider()

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
