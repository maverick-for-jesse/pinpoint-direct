import requests
import json
import os
import re
from bs4 import BeautifulSoup


AUTH_PROFILES_PATH = os.path.join(
    os.path.expanduser('~'), '.openclaw', 'agents', 'main', 'agent', 'auth-profiles.json'
)


def get_anthropic_key():
    """Get Anthropic API key: env var first, then auth-profiles.json, then config file."""
    key = os.getenv('ANTHROPIC_API_KEY')
    if key:
        return key
    if os.path.exists(AUTH_PROFILES_PATH):
        try:
            import json as _json
            with open(AUTH_PROFILES_PATH) as f:
                d = _json.load(f)
            key = d.get('profiles', {}).get('anthropic:default', {}).get('key')
            if key:
                return key
        except Exception:
            pass
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


def scrape_website(url):
    """Scrape a website and return raw extracted data."""
    if not url.startswith('http'):
        url = 'https://' + url

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    # Remove scripts and styles from text extraction
    for tag in soup(['script', 'style', 'noscript', 'iframe']):
        tag.decompose()

    # Title
    title = soup.title.string.strip() if soup.title else ''

    # Meta description
    meta_desc = ''
    meta = soup.find('meta', attrs={'name': 'description'}) or \
           soup.find('meta', attrs={'property': 'og:description'})
    if meta:
        meta_desc = meta.get('content', '')

    # OG title/site name
    og_title = ''
    og = soup.find('meta', attrs={'property': 'og:site_name'}) or \
         soup.find('meta', attrs={'property': 'og:title'})
    if og:
        og_title = og.get('content', '')

    # Theme color
    theme_color = ''
    tc = soup.find('meta', attrs={'name': 'theme-color'})
    if tc:
        theme_color = tc.get('content', '')

    # Headings
    headings = []
    for tag in ['h1', 'h2', 'h3']:
        for h in soup.find_all(tag)[:4]:
            text = h.get_text(strip=True)
            if text and len(text) > 3:
                headings.append(text)

    # Body text (first 2000 chars of visible text)
    body_text = ' '.join(soup.get_text(separator=' ').split())[:2500]

    # Phone numbers
    phones = re.findall(
        r'[\+]?[(]?[0-9]{3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4}',
        resp.text
    )
    phone = phones[0] if phones else ''

    # Colors from CSS (hex codes)
    css_colors = list(set(re.findall(r'#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b', resp.text)))[:20]

    # Social proof / trust signals
    trust_signals = []
    for phrase in ['years', 'award', 'certified', 'guarantee', 'trusted', 'rated',
                   'reviews', 'customers', 'satisfaction', 'licensed', 'insured']:
        if phrase.lower() in body_text.lower():
            trust_signals.append(phrase)

    return {
        'url': url,
        'title': title,
        'og_title': og_title,
        'meta_desc': meta_desc,
        'theme_color': theme_color,
        'headings': headings[:8],
        'body_text': body_text[:2000],
        'phone': phone,
        'css_colors': css_colors[:15],
        'trust_signals': trust_signals[:5],
    }


def analyze_with_claude(scraped):
    """Feed scraped data to Claude and get structured postcard data back."""
    api_key = get_anthropic_key()

    prompt = f"""You are analyzing a business website to help create a direct mail postcard.

WEBSITE DATA:
Title: {scraped['title']}
OG Title: {scraped['og_title']}
Meta Description: {scraped['meta_desc']}
Headings: {' | '.join(scraped['headings'])}
Body Text (excerpt): {scraped['body_text'][:1500]}
Phone: {scraped['phone']}
Theme Color: {scraped['theme_color']}
CSS Colors Found: {', '.join(scraped['css_colors'][:10])}
Trust Signals: {', '.join(scraped['trust_signals'])}

Based on this website data, return ONLY valid JSON with this structure:
{{
  "business_name": "The business name",
  "business_type": "One of: E-Commerce, Law Firm, Dental Office, Auto Shop, Restaurant, Real Estate, Home Services, Medical/Health, Retail Store, Other",
  "phone": "Phone number if found, else empty string",
  "website": "The URL without https://",
  "tagline": "Their tagline or a short brand descriptor",
  "offer_suggestion": "A compelling offer you'd recommend for this business based on what they do (e.g. '20% off first visit', 'Free estimate', 'Buy one get one')",
  "target_audience": "Who their ideal postcard recipient would be",
  "primary_color": "Best hex color for their brand (from CSS colors or theme color — pick the most prominent non-white, non-black color)",
  "accent_color": "Secondary/accent hex color that complements the primary",
  "style_recommendation": "One of: REALISTIC, DESIGN, RENDER_3D, ANIME",
  "brand_notes": "2-3 sentences describing their brand vibe, tone, and visual style to help guide image generation",
  "image_prompt_hint": "Key visual elements or themes to include in Ideogram image prompts for this business"
}}"""

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 1024,
        "system": "You analyze business websites and extract structured data for direct mail marketing. Return only valid JSON.",
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    text = resp.json()['content'][0]['text'].strip()
    # Strip markdown fences
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()
    # Extract JSON object if there's surrounding text
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        text = match.group(0)
    return json.loads(text)


def analyze_website(url):
    """Full pipeline: scrape + analyze. Returns structured data for postcard builder."""
    scraped = scrape_website(url)
    analysis = analyze_with_claude(scraped)
    # Merge phone from scrape if Claude didn't find one
    if not analysis.get('phone') and scraped.get('phone'):
        analysis['phone'] = scraped['phone']
    return analysis
