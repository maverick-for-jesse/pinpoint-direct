"""
marketing.py — Public-facing marketing site blueprint.
Routes: / | /how-it-works | /pricing | /get-started
"""
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Blueprint, render_template, redirect, url_for, request, flash
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
    if not current_user.is_authenticated:
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
