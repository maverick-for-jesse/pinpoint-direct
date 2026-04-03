import os
import tempfile
from datetime import datetime

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except Exception:
    WEASYPRINT_AVAILABLE = False


# Postcard dimensions in points (1 inch = 72pt)
SIZES = {
    '4x6':  {'w': 432, 'h': 288},   # 6" x 4"
    '5.25x8.5': {'w': 612, 'h': 378},   # 9" x 6"
    '6x11': {'w': 792, 'h': 432},   # 11" x 6"
}


def render_postcard_html(side_data, size='5.25x8.5'):
    """Build HTML string for one side of the postcard."""
    dims = SIZES.get(size, SIZES['5.25x8.5'])
    w_pt = dims['w']
    h_pt = dims['h']

    bg_color = side_data.get('bg_color', '#ffffff')
    bg_image = side_data.get('bg_image_b64', '')
    headline = side_data.get('headline', '')
    body = side_data.get('body', '')
    cta = side_data.get('cta', '')
    logo_b64 = side_data.get('logo_b64', '')
    layout = side_data.get('layout', 'hero')

    bg_css = f"background-color: {bg_color};"
    if bg_image:
        bg_css += f" background-image: url('data:image/png;base64,{bg_image}'); background-size: cover; background-position: center;"

    headline_color = side_data.get('headline_color', '#1a1a2e')
    body_color = side_data.get('body_color', '#333333')
    cta_color = side_data.get('cta_color', '#ffffff')
    cta_bg = side_data.get('cta_bg', '#e63946')

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
  @page {{ size: {w_pt}pt {h_pt}pt; margin: 0; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ width: {w_pt}pt; height: {h_pt}pt; overflow: hidden; {bg_css} font-family: Arial, sans-serif; }}
  .postcard {{ width: {w_pt}pt; height: {h_pt}pt; position: relative; display: flex; flex-direction: column; justify-content: flex-end; padding: 24pt; }}
  .overlay {{ position: absolute; inset: 0; background: linear-gradient(to top, rgba(0,0,0,0.6) 0%, rgba(0,0,0,0.1) 60%, transparent 100%); }}
  .content {{ position: relative; z-index: 2; }}
  .headline {{ font-size: 28pt; font-weight: 800; color: {headline_color}; line-height: 1.1; margin-bottom: 8pt; text-shadow: 0 2px 4px rgba(0,0,0,0.3); }}
  .body {{ font-size: 11pt; color: {body_color}; line-height: 1.4; margin-bottom: 12pt; }}
  .cta {{ display: inline-block; background: {cta_bg}; color: {cta_color}; padding: 8pt 20pt; border-radius: 4pt; font-size: 12pt; font-weight: 700; }}
  .logo {{ position: absolute; top: 20pt; right: 20pt; z-index: 2; max-height: 40pt; max-width: 120pt; }}
</style>
</head><body>
<div class="postcard">
  {'<div class="overlay"></div>' if bg_image else ''}
  {'<img class="logo" src="data:image/png;base64,' + logo_b64 + '">' if logo_b64 else ''}
  <div class="content">
    {'<div class="headline">' + headline + '</div>' if headline else ''}
    {'<div class="body">' + body + '</div>' if body else ''}
    {'<div class="cta">' + cta + '</div>' if cta else ''}
  </div>
</div>
</body></html>"""
    return html


def generate_postcard_pdf(front_data, back_data, size='5.25x8.5', output_dir=None):
    """Generate a 2-page PDF (front + back) and return the file path."""
    if not WEASYPRINT_AVAILABLE:
        raise RuntimeError("WeasyPrint is not installed.")

    if output_dir is None:
        output_dir = tempfile.gettempdir()

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"postcard_{size}_{timestamp}.pdf"
    output_path = os.path.join(output_dir, filename)

    front_html = render_postcard_html(front_data, size)
    back_html = render_postcard_html(back_data, size)

    dims = SIZES.get(size, SIZES['5.25x8.5'])
    page_css = CSS(string=f"@page {{ size: {dims['w']}pt {dims['h']}pt; margin: 0; }}")

    from weasyprint import HTML as WPHTML
    front_doc = WPHTML(string=front_html).render(stylesheets=[page_css])
    back_doc = WPHTML(string=back_html).render(stylesheets=[page_css])

    all_pages = front_doc.pages + back_doc.pages
    front_doc.copy(all_pages).write_pdf(output_path)

    return output_path
