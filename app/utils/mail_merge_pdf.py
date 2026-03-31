"""
mail_merge_pdf.py — Generate a duplex 11×17 print-ready PDF for 6×9 postcard mail merge.

Layout:
  Page size: 11" × 17" = 792pt × 1224pt
  Card bleed size: 6.41" × 9.48" = 461.52pt × 682.56pt
  Card 1 top edge at 1" from page top  → reportlab y_bottom = 469.44pt
  Card 2 top edge at 9" from page top  → reportlab y_bottom = -106.56pt (bleed clips at bottom, intentional)
  Horizontal center: x = (792 - 461.52) / 2 = 165.24pt
"""

from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.pagesizes import landscape
import os

# Page dimensions (points)
PAGE_W = 792.0   # 11"
PAGE_H = 1224.0  # 17"

# Card dimensions (points) — LANDSCAPE orientation: 9.48" wide × 6.41" tall
CARD_W = 682.56  # 9.48"
CARD_H = 461.52  # 6.41"

# Card horizontal position (centered on 11" page)
CARD_X = (PAGE_W - CARD_W) / 2  # (792 - 682.56) / 2 = 54.72pt

# Card vertical positions (reportlab bottom-left origin)
# Card 1: top edge at 1" from page top
CARD1_Y = PAGE_H - 72.0 - CARD_H    # 1224 - 72 - 461.52 = 690.48pt
# Card 2: top edge at 9" from page top
CARD2_Y = PAGE_H - 648.0 - CARD_H   # 1224 - 648 - 461.52 = 114.48pt (fits on page)


def _get_address_lines(record, column_map):
    """Build address lines from a record dict using the column map."""
    def val(key):
        col = column_map.get(key, '')
        if col:
            return str(record.get(col, '') or '').strip()
        return ''

    name = val('name')
    title = val('title')
    org = val('org')
    address = val('address')
    city = val('city')
    state = val('state')
    zip_code = val('zip')
    plus4 = val('plus4')

    lines = []

    # Line 1: Name, Title
    line1_parts = [p for p in [name, title] if p]
    if line1_parts:
        lines.append(', '.join(line1_parts))

    # Line 2: Organization
    if org:
        lines.append(org)

    # Line 3: Street
    if address:
        lines.append(address)

    # Line 4: City, State ZIP-Plus4
    city_state_zip = ''
    if city and state and zip_code:
        if plus4:
            city_state_zip = f"{city}, {state} {zip_code}-{plus4}"
        else:
            city_state_zip = f"{city}, {state} {zip_code}"
    elif city and state:
        city_state_zip = f"{city}, {state}"
    elif city:
        city_state_zip = city
    if city_state_zip:
        lines.append(city_state_zip)

    return lines


def _draw_imb_barcode(c, imb_alpha, zone_x, zone_y_bottom, zone_w):
    """
    Draw an Intelligent Mail Barcode from the MD_IMBAlphaCode string.

    USPS Publication 197 bar dimensions (at 300 dpi):
      Bar width:   0.015" = 1.08pt
      Bar spacing: 0.0437" = 3.15pt (center-to-center)
      Full bar:    0.125" = 9.0pt  (full height, tracker + ascender + descender)
      Ascender:    0.091" = 6.55pt (top half: tracker + ascender)
      Descender:   0.091" = 6.55pt (bottom half: tracker + descender)
      Tracker:     0.057" = 4.10pt (middle only)
      Tracker baseline offset from barcode bottom: 0.034" = 2.45pt

    Bar types:
      F = Full bar    (bottom of descender to top of ascender)
      A = Ascender    (tracker baseline up through ascender top)
      D = Descender   (descender bottom up through tracker top)
      T = Tracker     (tracker only — middle band)
    """
    if not imb_alpha or len(imb_alpha) < 65:
        return

    # USPS spec dimensions in points
    BAR_W       = 1.08   # bar width
    BAR_PITCH   = 3.15   # center-to-center spacing
    FULL_H      = 9.0    # F bar height
    HALF_H      = 6.55   # A and D bar height
    TRACKER_H   = 4.10   # T bar height
    # Tracker bottom sits at zone_y_bottom + TRACKER_OFFSET
    TRACKER_BOT_OFFSET = 2.45
    # Full bar baseline = zone_y_bottom (descender goes all the way down)
    FULL_BOT_OFFSET    = 0.0
    # Descender bottom = zone_y_bottom
    DESC_BOT_OFFSET    = 0.0
    # Ascender bottom = tracker top = TRACKER_BOT_OFFSET + TRACKER_H
    ASC_BOT_OFFSET     = TRACKER_BOT_OFFSET + TRACKER_H

    total_barcode_w = 65 * BAR_PITCH
    # Center barcode within zone_w
    start_x = zone_x + (zone_w - total_barcode_w) / 2

    c.setFillColorRGB(0, 0, 0)

    for i, ch in enumerate(imb_alpha[:65]):
        bar_x = start_x + i * BAR_PITCH - BAR_W / 2
        ch = ch.upper()

        if ch == 'F':
            bar_bottom = zone_y_bottom + FULL_BOT_OFFSET
            bar_height = FULL_H
        elif ch == 'A':
            bar_bottom = zone_y_bottom + ASC_BOT_OFFSET
            bar_height = HALF_H
        elif ch == 'D':
            bar_bottom = zone_y_bottom + DESC_BOT_OFFSET
            bar_height = HALF_H
        elif ch == 'T':
            bar_bottom = zone_y_bottom + TRACKER_BOT_OFFSET
            bar_height = TRACKER_H
        else:
            continue  # skip unexpected characters

        c.rect(bar_x, bar_bottom, BAR_W, bar_height, fill=1, stroke=0)


def _draw_address_block(c, record, column_map, address_zone, card_x, card_y):
    """
    Render IMb barcode + address text block onto the canvas within the address zone.

    address_zone: dict with x_pct, y_pct, w_pct, h_pct (0-100 floats)
                  measured from the top-left of the card image.
    card_x, card_y: reportlab bottom-left origin of the card on the page.
    """
    x_pct = float(address_zone.get('x_pct', 0))
    y_pct = float(address_zone.get('y_pct', 0))
    w_pct = float(address_zone.get('w_pct', 60))
    h_pct = float(address_zone.get('h_pct', 40))

    zone_x = card_x + (x_pct / 100.0) * CARD_W
    zone_y_from_card_top = (y_pct / 100.0) * CARD_H
    zone_w = (w_pct / 100.0) * CARD_W
    zone_h = (h_pct / 100.0) * CARD_H

    # Convert card-top-relative y to reportlab bottom-relative
    zone_bottom = card_y + CARD_H - zone_y_from_card_top - zone_h

    lines = _get_address_lines(record, column_map)
    if not lines:
        return

    # --- IMb barcode ---
    # Barcode sits at the top of the address zone
    # Full bar height = 9pt, add 4pt padding below barcode before text starts
    IMB_HEIGHT   = 9.0   # Full bar height in points
    IMB_PADDING  = 4.0   # Gap between barcode bottom and first text line

    imb_alpha = str(record.get('MD_IMBAlphaCode', '') or '').strip()
    barcode_drawn = bool(imb_alpha and len(imb_alpha) >= 65)

    if barcode_drawn:
        # Barcode top = zone top - 2pt padding
        barcode_top = zone_bottom + zone_h - 2
        barcode_bottom = barcode_top - IMB_HEIGHT
        _draw_imb_barcode(c, imb_alpha, zone_x, barcode_bottom, zone_w)
        # Address text starts below barcode
        text_top = barcode_bottom - IMB_PADDING
    else:
        text_top = zone_bottom + zone_h - 2

    # Height available for text
    text_zone_h = text_top - zone_bottom

    c.setFillColorRGB(0, 0, 0)

    # Auto-size font to fit all lines within available text height and zone width
    font_size = 11
    line_spacing_factor = 1.3
    while font_size >= 6:
        total_text_h = len(lines) * font_size * line_spacing_factor
        max_line_w = max(
            c.stringWidth(line, 'Helvetica', font_size)
            for line in lines
        ) if lines else 0
        if total_text_h <= text_zone_h and max_line_w <= zone_w:
            break
        font_size -= 0.5

    font_size = max(font_size, 6)
    line_height = font_size * line_spacing_factor
    c.setFont('Helvetica', font_size)

    # Draw lines top-to-bottom
    y_cursor = text_top - font_size

    for line in lines:
        if y_cursor < zone_bottom:
            break
        c.drawString(zone_x + 2, y_cursor, line)
        y_cursor -= line_height


def _draw_card_image(c, image_path, card_x, card_y):
    """
    Draw the postcard image at the given card position.
    Image is scaled to fill the card box (preserving aspect ratio),
    centered within the box. Source image data is embedded at full resolution.
    """
    from reportlab.lib.utils import ImageReader
    from PIL import Image as PILImage

    # Get native image dimensions
    with PILImage.open(image_path) as img:
        img_w, img_h = img.size  # pixels

    # Scale to fill card box, preserving aspect ratio (cover, not fit)
    # This means the image fills the entire card area — matching bleed intent
    img_aspect = img_w / img_h
    card_aspect = CARD_W / CARD_H

    if img_aspect > card_aspect:
        # Image is wider than card — scale by height
        draw_h = CARD_H
        draw_w = CARD_H * img_aspect
    else:
        # Image is taller than card — scale by width
        draw_w = CARD_W
        draw_h = CARD_W / img_aspect

    # Center the image within the card box
    offset_x = card_x + (CARD_W - draw_w) / 2
    offset_y = card_y + (CARD_H - draw_h) / 2

    c.drawImage(
        image_path,
        offset_x, offset_y,
        width=draw_w,
        height=draw_h,
        mask='auto',
    )


def generate_mail_merge_pdf(front_image_path, back_image_path, records,
                             address_zone, column_map, output_path):
    """
    Generate a print-ready duplex 11×17 PDF with 2 postcards per sheet.

    front_image_path: str path to front PNG/JPG
    back_image_path: str path to back PNG/JPG
    records: list of dicts (CSV rows)
    address_zone: {x_pct, y_pct, w_pct, h_pct} (0-100 floats, top-left origin)
    column_map: {name, title, org, address, city, state, zip, plus4} -> CSV column name strings
    output_path: str path to write output PDF
    """
    c = canvas.Canvas(output_path, pagesize=(PAGE_W, PAGE_H))

    # Process records in pairs
    i = 0
    while i < len(records):
        record_a = records[i]
        record_b = records[i + 1] if i + 1 < len(records) else None
        i += 2

        # === Page 1: Fronts ===
        _draw_card_image(c, front_image_path, CARD_X, CARD1_Y)
        if record_b is not None:
            _draw_card_image(c, front_image_path, CARD_X, CARD2_Y)
        c.showPage()

        # === Page 2: Backs with address blocks ===
        _draw_card_image(c, back_image_path, CARD_X, CARD1_Y)
        _draw_address_block(c, record_a, column_map, address_zone, CARD_X, CARD1_Y)

        if record_b is not None:
            _draw_card_image(c, back_image_path, CARD_X, CARD2_Y)
            _draw_address_block(c, record_b, column_map, address_zone, CARD_X, CARD2_Y)

        c.showPage()

    c.save()
