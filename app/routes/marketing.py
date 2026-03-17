"""
marketing.py — Public-facing marketing site blueprint.
Routes: / | /how-it-works | /pricing | /get-started
"""
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import current_user

from app.utils.database import get_db, get_db_type

marketing_bp = Blueprint('marketing', __name__)


# ── helpers ─────────────────────────────────────────────────────────────────

def _send_lead_notification(lead: dict):
    """Send a notification email to jesse@bluealpha.us with the lead details."""
    # Try config/gmail.json first, then fall back to env vars
    gmail_user = None
    gmail_pass = None

    gmail_config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'config', 'gmail.json'
    )
    if os.path.exists(gmail_config_path):
        try:
            with open(gmail_config_path) as f:
                cfg = json.load(f)
                gmail_user = cfg.get('email') or cfg.get('user') or cfg.get('gmail_user')
                gmail_pass = cfg.get('password') or cfg.get('app_password') or cfg.get('gmail_app_password')
        except Exception:
            pass

    if not gmail_user:
        gmail_user = os.getenv('GMAIL_USER')
    if not gmail_pass:
        gmail_pass = os.getenv('GMAIL_APP_PASSWORD')

    if not gmail_user or not gmail_pass:
        print("WARNING: Gmail credentials not configured — skipping lead notification email.")
        return

    recipient = 'jesse@bluealpha.us'
    subject = f"🎯 New Lead: {lead.get('name', 'Unknown')} — {lead.get('business_name', '')}"

    body = f"""New lead from Pinpoint Direct website!

Name:          {lead.get('name', '')}
Business:      {lead.get('business_name', '')}
Email:         {lead.get('email', '')}
Phone:         {lead.get('phone', '')}

Message:
{lead.get('message', '(none)')}

---
View all leads in the admin portal.
"""
    msg = MIMEMultipart()
    msg['From'] = gmail_user
    msg['To'] = recipient
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, recipient, msg.as_string())
        print(f"Lead notification email sent to {recipient}")
    except Exception as e:
        print(f"WARNING: Failed to send lead notification email: {e}")


def _save_lead(name, email, business_name, phone, message):
    """Insert a lead row and return the new id."""
    db_type = get_db_type()
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(
                    """INSERT INTO leads (name, email, business_name, phone, message)
                       VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                    (name, email, business_name, phone, message)
                )
                row = cur.fetchone()
                lead_id = row['id'] if row else None
            db.commit()
        else:
            cur = db.execute(
                """INSERT INTO leads (name, email, business_name, phone, message)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, email, business_name, phone, message)
            )
            lead_id = cur.lastrowid
            db.commit()
    return lead_id


# ── routes ───────────────────────────────────────────────────────────────────

@marketing_bp.route('/')
def index():
    # On the admin subdomain, redirect unauthenticated users to login
    host = request.host.lower().split(':')[0]
    if host == 'admin.pinpointdirect.io' and not current_user.is_authenticated:
        return redirect(url_for('auth.login'))
    # Clients auto-redirect to their portal; admins can see the marketing site
    if current_user.is_authenticated and not current_user.is_admin():
        return redirect(url_for('client.dashboard'))
    return render_template('marketing/index.html', logged_in=current_user.is_authenticated)


@marketing_bp.route('/how-it-works')
def how_it_works():
    return render_template('marketing/how_it_works.html')


@marketing_bp.route('/pricing')
def pricing():
    return render_template('marketing/pricing.html')


@marketing_bp.route('/get-started', methods=['GET', 'POST'])
def get_started():
    if request.method == 'POST':
        name          = request.form.get('name', '').strip()
        business_name = request.form.get('business_name', '').strip()
        email         = request.form.get('email', '').strip()
        phone         = request.form.get('phone', '').strip()
        message       = request.form.get('message', '').strip()

        if not name or not email:
            flash('Please provide your name and email.', 'error')
            return render_template('marketing/get_started.html',
                                   form_data=request.form)

        try:
            _save_lead(name, email, business_name, phone, message)
            _send_lead_notification({
                'name': name,
                'email': email,
                'business_name': business_name,
                'phone': phone,
                'message': message,
            })
            return render_template('marketing/get_started.html', success=True)
        except Exception as e:
            print(f"ERROR saving lead: {e}")
            flash('Something went wrong. Please try again.', 'error')
            return render_template('marketing/get_started.html',
                                   form_data=request.form)

    return render_template('marketing/get_started.html')


@marketing_bp.route('/api/market-stats')
def market_stats():
    """Public endpoint — returns live Coweta County new mover stats for the marketing homepage."""
    try:
        db_type = get_db_type()
        with get_db() as db:
            def q(sql):
                if db_type == 'postgres':
                    with db.cursor() as cur:
                        cur.execute(sql)
                        return cur.fetchone()
                else:
                    return db.execute(sql).fetchone()

            def qa(sql):
                if db_type == 'postgres':
                    with db.cursor() as cur:
                        cur.execute(sql)
                        return cur.fetchall()
                else:
                    return db.execute(sql).fetchall()

            # Total records
            total = (q("SELECT COUNT(*) as cnt FROM new_movers") or {}).get('cnt', 0)

            # Tier breakdown
            tier_rows = qa("SELECT tier, COUNT(*) as cnt FROM new_movers GROUP BY tier")
            tiers = {r['tier'] or 'Standard': r['cnt'] for r in tier_rows}

            # Monthly volume (last 12 months)
            monthly_rows = qa("""
                SELECT TO_CHAR(DATE_TRUNC('month', sale_date::date), 'Mon YYYY') as month,
                       COUNT(*) as cnt
                FROM new_movers
                WHERE sale_date IS NOT NULL
                  AND sale_date::date >= NOW() - INTERVAL '12 months'
                GROUP BY DATE_TRUNC('month', sale_date::date)
                ORDER BY DATE_TRUNC('month', sale_date::date) DESC
            """) if db_type == 'postgres' else qa("""
                SELECT strftime('%b %Y', sale_date) as month, COUNT(*) as cnt
                FROM new_movers
                WHERE sale_date IS NOT NULL
                GROUP BY strftime('%Y-%m', sale_date)
                ORDER BY sale_date DESC
                LIMIT 12
            """)
            monthly = [{'month': r['month'], 'count': r['cnt']} for r in monthly_rows]

            # Top neighborhoods
            neighborhood_rows = qa("""
                SELECT neighborhood, COUNT(*) as cnt
                FROM new_movers
                WHERE neighborhood IS NOT NULL AND neighborhood != ''
                GROUP BY neighborhood
                ORDER BY cnt DESC
                LIMIT 8
            """)
            neighborhoods = [{'name': r['neighborhood'], 'count': r['cnt']} for r in neighborhood_rows]

            # Avg sale price
            avg_price = (q("SELECT AVG(sale_price::numeric) as avg FROM new_movers WHERE sale_price IS NOT NULL AND sale_price != '' AND sale_price::numeric > 0") or {}).get('avg', 0)

            # Months of data
            date_range = q("""
                SELECT MIN(sale_date) as earliest, MAX(sale_date) as latest
                FROM new_movers WHERE sale_date IS NOT NULL
            """)

        return jsonify({
            'total': int(total),
            'tiers': {k: int(v) for k, v in tiers.items()},
            'monthly': monthly,
            'neighborhoods': neighborhoods,
            'avg_sale_price': int(float(avg_price or 0)),
            'date_range': {
                'earliest': str(date_range['earliest']) if date_range and date_range['earliest'] else None,
                'latest': str(date_range['latest']) if date_range and date_range['latest'] else None,
            },
            'county': 'Coweta County, GA',
        })
    except Exception as e:
        import traceback
        print(f"market_stats error: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500
