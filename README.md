# Pinpoint Direct — Platform

Direct mail marketing agency platform built with Flask.

## Stack
- **Flask** — backend
- **Airtable** — clients, campaigns, invoices, job status
- **SQLite** — mailing lists and address data
- **Stripe** — invoicing + payments
- **WeasyPrint** — HTML → print-ready PDF
- **USPS Web Tools API** — address verification
- **Google Gemini** — AI image generation for postcard builder

## Structure
- `/admin` — staff backend (campaign builder, postcard builder, list mgmt, print queue)
- `/portal` — client portal (metrics, artwork approval, mailing approval, invoices)
- `/login` — shared auth, role-based (admin vs client)

## Setup
1. `cp .env.example .env` and fill in keys
2. `pip install -r requirements.txt`
3. `python run.py`
4. Visit `http://localhost:5000`
