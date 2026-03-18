# Postcard Builder — Product Vision & Plan
*Last updated: 2026-03-18*

## Goal
A polished, end-to-end postcard builder that takes a business and campaign idea as input and produces a print-ready direct mail postcard design. No design experience required.

---

## User Flow (5 Steps)

### Step 1 — Business Info
- Business name (text input)
- Business type (dropdown: Home Services, Real Estate, Dental, Restaurant, Retail, E-Commerce, Other)
- Phone number
- Website URL → "Auto-Fill" button (uses website analyzer → Claude to extract brand info)
- Logo upload (optional — used on postcard back)
- Brand colors (auto-filled from website analyzer, editable)

### Step 2 — Campaign Details
- What are you promoting? (free text: "fall HVAC tune-up special")
- Offer type (dropdown: % Discount, $ Off, Free Service, Free Estimate, Gift, Event, Other)
- Offer detail (free text: "20% off first service call")
- Target audience (dropdown: New Movers, Neighborhood, Existing Customers, Custom List)
- Desired action (dropdown: Call Us, Visit Website, Scan QR Code, Visit In Person)
- Deadline? (checkbox + date picker)

### Step 3 — AI Design Generation (Claude)
- Claude generates using PostcardPro expert system prompt
- Output: headline, subheadline, body copy, CTA, image prompts (front + back), color suggestions, style notes
- Returns 2 variants (A & B) side-by-side
- User picks one (or mixes elements from both)
- Image generated via Ideogram based on AI-provided prompt

### Step 4 — Visual Canvas Editor
- Split view: front and back of postcard
- Postcard size selector: 4x6, 6x9, 6x11 (USPS standard sizes)
- Front canvas: hero image, headline, subheadline, logo, CTA button/strip
- Back canvas: body copy, contact info, logo, QR code placeholder, address panel (locked/enforced), indicia box (locked/enforced)
- Drag-to-reposition text blocks
- Font selector (3-4 curated options: bold, clean, friendly, professional)
- Color swatches (primary/secondary pulled from brand colors)
- "Regenerate Image" button (re-prompts Ideogram)
- Live USPS compliance checklist (address panel clear, indicia present, size valid, min 200 pieces)

### Step 5 — Save & Export
- Save design to campaign (links postcard to campaign record in DB)
- Export as print-ready PDF (bleed marks, 300dpi guidance, CMYK note)
- Download front/back as separate high-res PNGs
- Preview mode (shows how it'll look in a mailbox)

---

## Technical Architecture

### Frontend
- Canvas: HTML5 Canvas or Fabric.js (drag/drop, text editing)
- No external design tool dependency (fully in-app)
- Mobile-friendly preview mode

### Backend (Flask)
- `/admin/postcard-builder` — main builder page (wizard UI)
- `/admin/postcard-builder/ai-design` — POST, calls Claude for design spec
- `/admin/postcard-builder/generate-image` — POST, calls Ideogram
- `/admin/postcard-builder/analyze-website` — POST, scrapes + Claude analysis
- `/admin/postcard-builder/save` — POST, saves to `artwork` table
- `/admin/postcard-builder/export-pdf` — POST, generates print-ready PDF

### AI Models
- **Website analyzer**: claude-sonnet-4-6 (extract brand info)
- **Copy/design generation**: claude-sonnet-4-6 with PostcardPro system prompt
- **Image generation**: Ideogram (already integrated)

### Database
- `artwork` table stores saved designs (campaign_id, version, layout_json, image_urls)
- `campaigns` table links to artwork

---

## What's Already Built (as of 2026-03-18)
- ✅ Website analyzer (Claude-powered, SerpAPI fallback)
- ✅ Copy generator (Claude-powered, headline/body/CTA)
- ✅ Image generator (Ideogram, 4-image grid)
- ✅ AI auto-design endpoint + UI panel (PostcardPro prompt, A/B variants)
- ✅ Basic canvas editor (postcard_builder.html)
- ✅ PDF export (ReportLab)
- ✅ Save to artwork table
- ⬜ Wizard step-by-step flow (needs rebuild)
- ⬜ Fabric.js canvas (drag/drop, proper visual editing)
- ⬜ USPS compliance checklist UI
- ⬜ QR code generation
- ⬜ Font selector
- ⬜ Print-ready PDF with bleed marks

---

## Build Order (Recommended)
1. **Wizard UI** — replace current single-page form with clean 5-step flow
2. **Canvas editor** — Fabric.js for front/back with locked USPS zones
3. **USPS compliance checker** — live checklist in the UI
4. **QR code** — simple endpoint, display on postcard back
5. **Print PDF polish** — bleed marks, proper resolution guidance
6. **Preview mode** — "how it looks in a mailbox" mockup

---

## USPS Requirements (enforced in builder)
- Standard postcard sizes: 4.25x6, 5x7, 6x9, 6x11 inches
- Back: address panel 4x1.5 inches, bottom-right, clear of any graphics
- Back: indicia box 2x1 inches, top-right
- Minimum 200 pieces for bulk/Marketing Mail rates
- Return address required (top-left, back)
