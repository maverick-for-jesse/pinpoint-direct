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

# Card dimensions (points)
CARD_W = 461.52  # 6.41"
CARD_H = 682.56  # 9.48"

# Card horizontal position (centered)
CARD_X = (PAGE_W - CARD_W) / 2  # 165.24pt

# Card vertical positions (reportlab bottom-left origin)
# Card 1: top at 1" from page top
CARD1_Y = PAGE_H - 72.0 - CARD_H    # 1224 - 72 - 682.56 = 469.44
# Card 2: top at 9" from page top
CARD2_Y = PAGE_H - 648.0 - CARD_H   # 1224 - 648 - 682.56 = -106.56 (intentional clip)


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


def _draw_address_block(c, record, column_map, address_zone, card_x, card_y):
    """
    Render address text block onto the canvas within the address zone.

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
    # zone_top in reportlab = card_y + CARD_H - zone_y_from_card_top
    # zone_bottom in reportlab = zone_top - zone_h
    zone_bottom = card_y + CARD_H - zone_y_from_card_top - zone_h

    lines = _get_address_lines(record, column_map)
    if not lines:
        return

    c.setFillColorRGB(0, 0, 0)
    c.setFont('Helvetica', 11)

    # Auto-size font to fit all lines within zone_h and zone_w
    font_size = 11
    line_spacing_factor = 1.3
    while font_size >= 7:
        total_text_h = len(lines) * font_size * line_spacing_factor
        max_line_w = max(
            c.stringWidth(line, 'Helvetica', font_size)
            for line in lines
        ) if lines else 0
        if total_text_h <= zone_h and max_line_w <= zone_w:
            break
        font_size -= 0.5

    font_size = max(font_size, 6)
    line_height = font_size * line_spacing_factor

    c.setFont('Helvetica', font_size)

    # Draw lines top-to-bottom within the zone
    # Start at top of zone, pad slightly
    y_cursor = zone_bottom + zone_h - font_size - 2

    for line in lines:
        if y_cursor < zone_bottom:
            break
        c.drawString(zone_x + 2, y_cursor, line)
        y_cursor -= line_height


def _draw_card_image(c, image_path, card_x, card_y):
    """Draw the postcard image at the given card position."""
    c.drawImage(
        image_path,
        card_x, card_y,
        width=CARD_W,
        height=CARD_H,
        preserveAspectRatio=False,
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
