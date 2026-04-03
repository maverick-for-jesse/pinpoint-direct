"""
mail_merge_pdf.py — Generate a duplex 11×17 print-ready PDF for 5.25×8.5 postcard mail merge.

Layout: 4-up gang print on 11×17 sheet (2 cols × 2 rows)
  Page size: 11" × 17" = 792pt × 1224pt
  Card size: 5.25" × 8.5" = 378pt × 612pt
  Card bleed: +0.125" each side → 5.5" × 8.75" = 396pt × 630pt
  Col 1 X: 0pt  Col 2 X: 396pt  (two cards span 792pt = 11")
  Row 1 Y (top): 594pt  Row 2 Y (bottom): 0pt  (two rows span 1224pt = 17")
"""

from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.pagesizes import landscape
import os

# Page dimensions (points)
PAGE_W = 792.0   # 11"
PAGE_H = 1224.0  # 17"

# Card dimensions with bleed (points) — 5.5" × 8.75" with bleed
CARD_W = 396.0   # 5.5" with bleed
CARD_H = 630.0   # 8.75" with bleed

# 4-up positions: 2 cols × 2 rows
CARD_POSITIONS = [
    (0.0,    594.0),   # top-left
    (396.0,  594.0),   # top-right
    (0.0,    0.0),     # bottom-left
    (396.0,  0.0),     # bottom-right
]

# Legacy 2-up compat aliases
CARD_X  = 0.0
CARD1_Y = 594.0
CARD2_Y = 0.0


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

    # City/State/ZIP line
    city_state_zip = ''
    if city and state and zip_code:
        city_state_zip = f"{city}, {state} {zip_code}-{plus4}" if plus4 else f"{city}, {state} {zip_code}"
    elif city and state:
        city_state_zip = f"{city}, {state}"
    elif city:
        city_state_zip = city

    name_title = ', '.join(p for p in [name, title] if p)

    # Build named slots — order controlled by line_order passed in column_map
    slots = {
        'org':          org,
        'name_title':   name_title,
        'address':      address,
        'city_state_zip': city_state_zip,
    }

    # Default order: org first, then name/title, street, city
    line_order = column_map.get('line_order') or ['org', 'name_title', 'address', 'city_state_zip']

    lines = [slots[key] for key in line_order if slots.get(key)]
    return lines


def _draw_imb_barcode(c, imb_alpha, zone_x, zone_y_bottom, zone_w):
    """
    Draw an Intelligent Mail Barcode from the MD_IMBAlphaCode string.
    USPS Publication 197 spec dimensions. Barcode is centered within zone_w.

    Bar types:
      F = Full bar    (full height — descender through ascender)
      A = Ascender    (tracker + ascender top)
      D = Descender   (descender bottom + tracker)
      T = Tracker     (middle band only)
    """
    if not imb_alpha or len(imb_alpha) < 65:
        return

    # USPS spec in points (1pt = 1/72")
    BAR_W           = 1.44   # 0.020" — slightly wider for visibility at print scale
    BAR_PITCH       = 3.312  # 0.046" center-to-center
    FULL_H          = 9.0    # 0.125" full bar
    HALF_H          = 6.48   # 0.090" ascender / descender
    TRACKER_H       = 4.32   # 0.060" tracker
    TRACKER_OFFSET  = 2.34   # 0.0325" — tracker bottom from barcode baseline
    DESC_OFFSET     = 0.0    # descender starts at baseline
    ASC_OFFSET      = TRACKER_OFFSET + TRACKER_H  # ascender starts above tracker

    total_w = 65 * BAR_PITCH
    start_x = zone_x + (zone_w - total_w) / 2

    c.setFillColorRGB(0, 0, 0)

    for i, ch in enumerate(imb_alpha[:65]):
        bx = start_x + i * BAR_PITCH - BAR_W / 2
        ch = ch.upper()
        if ch == 'F':
            c.rect(bx, zone_y_bottom + DESC_OFFSET,  BAR_W, FULL_H,    fill=1, stroke=0)
        elif ch == 'A':
            c.rect(bx, zone_y_bottom + ASC_OFFSET,   BAR_W, HALF_H,    fill=1, stroke=0)
        elif ch == 'D':
            c.rect(bx, zone_y_bottom + DESC_OFFSET,  BAR_W, HALF_H,    fill=1, stroke=0)
        elif ch == 'T':
            c.rect(bx, zone_y_bottom + TRACKER_OFFSET, BAR_W, TRACKER_H, fill=1, stroke=0)


def _draw_address_block(c, record, column_map, address_zone, card_x, card_y):
    """
    Render IMb barcode + address text block to match standard Melissa output style:
      [barcode — centered]
      Name, Title
      Organization
      Street Address
      City, State ZIP-Plus4

    address_zone: {x_pct, y_pct, w_pct, h_pct} — percentages from card top-left.
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

    # zone_bottom in reportlab coords
    zone_bottom = card_y + CARD_H - zone_y_from_card_top - zone_h
    zone_top    = zone_bottom + zone_h

    lines = _get_address_lines(record, column_map)
    if not lines:
        return

    # --- Barcode dimensions ---
    IMB_FULL_H  = 9.0   # full bar height in pts
    IMB_GAP     = 5.0   # gap between barcode bottom and first text line

    imb_alpha = str(record.get('MD_IMBAlphaCode', '') or '').strip()
    has_barcode = bool(imb_alpha and len(imb_alpha) >= 65)

    # Total height needed: barcode + gap + text lines
    # Start with target font size of 10pt (matches Melissa output appearance)
    FONT        = 'Helvetica'
    FONT_SIZE   = 10.0
    LINE_SPACE  = FONT_SIZE * 1.4   # 14pt leading — matches standard address label

    barcode_block_h = (IMB_FULL_H + IMB_GAP) if has_barcode else 0
    text_h = len(lines) * LINE_SPACE

    total_h = barcode_block_h + text_h

    # Scale font down if content doesn't fit
    if total_h > zone_h and has_barcode:
        # Try scaling font
        available_text_h = zone_h - barcode_block_h
        if available_text_h > 0 and len(lines) > 0:
            FONT_SIZE = min(10.0, available_text_h / (len(lines) * 1.4))
            FONT_SIZE = max(FONT_SIZE, 6.0)
            LINE_SPACE = FONT_SIZE * 1.4

    # Position: start from zone top, work downward
    # Barcode at very top of zone
    y_cursor = zone_top  # working downward from here

    if has_barcode:
        barcode_bottom = y_cursor - IMB_FULL_H
        _draw_imb_barcode(c, imb_alpha, zone_x, barcode_bottom, zone_w)
        y_cursor = barcode_bottom - IMB_GAP

    # Address text — left aligned, top to bottom
    c.setFillColorRGB(0, 0, 0)
    c.setFont(FONT, FONT_SIZE)

    for line in lines:
        if y_cursor - FONT_SIZE < zone_bottom:
            break
        # Draw text at baseline = y_cursor - FONT_SIZE
        c.drawString(zone_x, y_cursor - FONT_SIZE, line)
        y_cursor -= LINE_SPACE


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
