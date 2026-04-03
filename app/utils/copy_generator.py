import json
import os
import requests


AUTH_PROFILES_PATH = os.path.join(
    os.path.expanduser('~'), '.openclaw', 'agents', 'main', 'agent', 'auth-profiles.json'
)


def _get_anthropic_key():
    """Get Anthropic API key: env var first, then auth-profiles.json."""
    key = os.getenv('ANTHROPIC_API_KEY')
    if key:
        return key
    if os.path.exists(AUTH_PROFILES_PATH):
        try:
            with open(AUTH_PROFILES_PATH) as f:
                d = json.load(f)
            key = d.get('profiles', {}).get('anthropic:default', {}).get('key')
            if key:
                return key
        except Exception:
            pass
    # Fallback: config/anthropic.json
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'config', 'anthropic.json'
    )
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                return json.load(f).get('api_key')
        except Exception:
            pass
    raise ValueError("Anthropic API key not configured. Set ANTHROPIC_API_KEY env var.")


def get_ai_provider():
    """Returns ('claude', api_key). Falls back to gemini if no Anthropic key."""
    try:
        key = _get_anthropic_key()
        return ('claude', key)
    except ValueError:
        pass
    # Fallback: Gemini
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'config', 'gemini.json'
    )
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                key = json.load(f).get('api_key')
            if key:
                return ('gemini', key)
        except Exception:
            pass
    raise ValueError("No AI API key configured. Set ANTHROPIC_API_KEY env var or add config/gemini.json.")


def _generate_with_claude(api_key, system_prompt, user_prompt=None, model='claude-sonnet-4-6'):
    """Call Anthropic Claude API and return parsed JSON."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    messages = [{"role": "user", "content": user_prompt or system_prompt}]
    effective_system = system_prompt if user_prompt else "You are an expert direct mail copywriter. Return only valid JSON as instructed."
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": effective_system,
        "messages": messages,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    text = resp.json()['content'][0]['text'].strip()
    # Strip markdown code fences if present
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text[3:]
        if text.endswith('```'):
            text = text[:-3]
    return json.loads(text.strip())


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


def _scrape_website(url: str, max_chars: int = 2000) -> str:
    """Fetch a website and return clean text content for AI context."""
    if not url:
        return ''
    try:
        import re as _re
        if not url.startswith('http'):
            url = 'https://' + url
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; PinpointDirect/1.0)'}
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        html = resp.text
        # Strip scripts, styles, nav, footer
        html = _re.sub(r'<(script|style|nav|footer|header)[^>]*>.*?</\1>', ' ', html, flags=_re.DOTALL|_re.IGNORECASE)
        # Strip all tags
        text = _re.sub(r'<[^>]+>', ' ', html)
        # Collapse whitespace
        text = _re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars]
    except Exception:
        return ''


def generate_campaign_copy(profile: dict, campaign: dict) -> dict:
    """
    Generate postcard copy using business profile + campaign data.
    Returns: {headlines: [str, str, str], body_copies: [str, str], ctas: [str, str, str]}
    """
    provider, api_key = get_ai_provider()

    has_deadline = campaign.get('has_deadline') or False
    deadline_date = campaign.get('deadline_date')
    if has_deadline and deadline_date:
        deadline_text = str(deadline_date)
    elif has_deadline:
        deadline_text = 'Limited time'
    else:
        deadline_text = 'None'

    # Optionally scrape website for brand voice context
    website_context = ''
    website_url = profile.get('website_url', '')
    if website_url:
        scraped = _scrape_website(website_url)
        if scraped:
            website_context = f'\n\nWEBSITE CONTENT (use for brand voice, tone, and specific offerings):\n{scraped}'

    prompt = f"""You are an expert direct mail copywriter. Based on this business info and campaign details, generate compelling postcard copy.

BUSINESS: {profile.get('business_name', 'this business')}, {profile.get('business_type', 'local')} business, {profile.get('years_in_business', 'established')} years in business. Average transaction: ${profile.get('average_transaction_value', 'varies')}. Services: {profile.get('top_services', 'see below')}. Best customers: {profile.get('best_customer_description', 'local residents')}. Known for: {profile.get('customer_compliment', 'quality service')}. Differentiator vs {profile.get('main_competitor', 'competitors')}: {profile.get('competitive_advantage', 'superior service')}.{website_context}

CAMPAIGN: Promoting {campaign.get('what_promoting', 'services')}. Offer type: {campaign.get('offer_type', 'special offer')}. Offer: {campaign.get('offer_detail', 'contact us for details')}. Deadline: {deadline_text}. Desired action: {campaign.get('desired_action', 'call us')}.

Generate:
- 3 headlines (max 10 words each): first benefit-focused, second urgency-focused, third curiosity-focused
- 2 body copy options (max 40 words each): punchy, direct, no fluff — each a complete standalone message
- 3 CTA options (max 8 words each): action-oriented

Return ONLY valid JSON with this exact structure (no markdown fences, no extra text):
{{"headlines": ["headline1", "headline2", "headline3"], "body_copies": ["body1", "body2"], "ctas": ["cta1", "cta2", "cta3"]}}"""

    if provider == 'claude':
        return _generate_with_claude(api_key, prompt, user_prompt=prompt, model='claude-sonnet-4-6')
    else:
        return _generate_with_gemini(api_key, prompt)


def generate_postcard_copy(business_name, business_type, offer_description, target_audience='local customers'):
    """
    Generate 2 headline + copy options for a postcard.
    Returns dict with option_a and option_b, each having:
    headline, subheadline, body, cta, image_prompt
    """
    provider, api_key = get_ai_provider()

    prompt = f"""You are an expert direct mail copywriter specializing in 5.25x8.5 postcards for local businesses.
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

    if provider == 'claude':
        return _generate_with_claude(api_key, prompt, user_prompt=prompt, model='claude-sonnet-4-6')
    else:
        return _generate_with_gemini(api_key, prompt)


def generate_ai_postcard_design(business_name, business_type, target_audience, key_message, offer, style='modern professional'):
    """
    Generate a full AI-powered postcard design using the PostcardPro expert prompt.
    Returns JSON with layout, copy, image_prompts, compliance_notes, variants.
    """
    provider, api_key = get_ai_provider()

    system_prompt = """You are PostcardPro, a world-class direct mail design expert with 20+ years creating high-response postcards (2-5%+ response rates). You strictly follow USPS Marketing Mail guidelines: sizes 4.25x6 to 6x11 inches, back requires clear 4x1.5 inch address panel (bottom-right), indicia top-right (1x2 inches), no bleeding over edges. Use AIDA structure (Attention, Interest, Desire, Action). Front: eye-catching teaser/image-heavy. Back: details, CTA, address panel. Optimize for scannability, benefit-driven copy, and 200+ mailer minimum compliance."""

    user_prompt = f"""Generate a complete postcard design for:
- Business: {business_name}
- Type: {business_type}
- Target Audience: {target_audience}
- Key Message: {key_message}
- Offer: {offer}
- Style: {style}

Return ONLY valid JSON with this exact structure:
{{
  "variant_a": {{
    "headline": "Bold attention-grabbing headline",
    "subheadline": "Supporting benefit statement",
    "body": "2-3 sentences max. Clear, benefit-focused, audience-tailored.",
    "cta": "Clear action-oriented CTA (max 8 words)",
    "front_image_prompt": "Detailed image generation prompt for front hero image. Photorealistic, commercial quality, no text in image.",
    "back_image_prompt": "Subtle background image for back. Muted tones, no text.",
    "colors": {{"primary": "#hex", "secondary": "#hex", "text": "#hex"}},
    "style_notes": "Brief design direction"
  }},
  "variant_b": {{
    "headline": "Alternative headline with different angle",
    "subheadline": "Different supporting line",
    "body": "Different body copy approach.",
    "cta": "Alternative CTA",
    "front_image_prompt": "Different image concept from variant A.",
    "back_image_prompt": "Different subtle background.",
    "colors": {{"primary": "#hex", "secondary": "#hex", "text": "#hex"}},
    "style_notes": "Different design direction"
  }},
  "compliance_notes": ["note1", "note2"],
  "recommended_size": "5.25x8.5"
}}"""

    if provider == 'claude':
        return _generate_with_claude(api_key, system_prompt, user_prompt=user_prompt, model='claude-sonnet-4-6')
    else:
        return _generate_with_gemini(api_key, system_prompt + '\n\n' + user_prompt)
