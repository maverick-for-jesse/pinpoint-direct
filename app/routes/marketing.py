"""
marketing.py — Public-facing marketing site blueprint.
Routes: / | /how-it-works | /pricing | /get-started
"""
import requests

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import current_user

from app.utils.database import get_db, get_db_type

marketing_bp = Blueprint('marketing', __name__)

AGENTMAIL_API_KEY = 'am_us_96c61f9a09f2fd38ea048790b4cd69750020ca68e31751204805915dacf55fbb'
AGENTMAIL_FROM    = 'info@pinpointdirect.io'
LEAD_NOTIFY_TO    = 'jesse@bluealpha.us'


# ── helpers ─────────────────────────────────────────────────────────────────

def _send_lead_notification(lead: dict):
    """Send a lead notification email via the AgentMail API."""
    subject = f"🎯 New Lead: {lead.get('name', 'Unknown')} — {lead.get('business_name', '')}"

    html_body = f"""
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #1a1a2e; background: #f4f5f7; margin: 0; padding: 0;">
  <div style="max-width: 560px; margin: 32px auto; background: white; border-radius: 12px;
              box-shadow: 0 2px 12px rgba(0,0,0,0.08); overflow: hidden;">
    <div style="background: #1a1a2e; padding: 24px 32px;">
      <h1 style="color: white; font-size: 20px; margin: 0;">🎯 New Lead — Pinpoint Direct</h1>
    </div>
    <div style="padding: 32px;">
      <table style="width: 100%; border-collapse: collapse; font-size: 15px;">
        <tr>
          <td style="padding: 10px 0; color: #888; font-weight: 600; width: 120px;">Name</td>
          <td style="padding: 10px 0; color: #1a1a2e; font-weight: 700;">{lead.get('name', '—')}</td>
        </tr>
        <tr style="background: #f8f8f8;">
          <td style="padding: 10px 8px; color: #888; font-weight: 600;">Business</td>
          <td style="padding: 10px 8px; color: #1a1a2e;">{lead.get('business_name', '—')}</td>
        </tr>
        <tr>
          <td style="padding: 10px 0; color: #888; font-weight: 600;">Email</td>
          <td style="padding: 10px 0;"><a href="mailto:{lead.get('email', '')}" style="color: #e63946;">{lead.get('email', '—')}</a></td>
        </tr>
        <tr style="background: #f8f8f8;">
          <td style="padding: 10px 8px; color: #888; font-weight: 600;">Phone</td>
          <td style="padding: 10px 8px; color: #1a1a2e;">{lead.get('phone', '—') or '—'}</td>
        </tr>
      </table>
      {"<div style='margin-top: 24px; padding: 16px; background: #f4f5f7; border-radius: 8px; font-size: 14px; color: #444; line-height: 1.6;'><strong style='display:block; margin-bottom:8px; color:#1a1a2e;'>Message:</strong>" + lead.get('message', '') + "</div>" if lead.get('message') else ""}
      <div style="margin-top: 28px; text-align: center;">
        <a href="https://admin.pinpointdirect.io/admin/leads"
           style="display: inline-block; padding: 12px 28px; background: #e63946; color: white;
                  border-radius: 8px; font-weight: 700; font-size: 14px; text-decoration: none;">
          View All Leads →
        </a>
      </div>
    </div>
    <div style="padding: 16px 32px; border-top: 1px solid #eee; font-size: 12px; color: #aaa; text-align: center;">
      Pinpoint Direct · 35 Andrew St, Newnan, GA 30263
    </div>
  </div>
</body>
</html>
"""

    try:
        resp = requests.post(
            f'https://api.agentmail.to/v0/inboxes/{AGENTMAIL_FROM}/messages',
            headers={
                'Authorization': f'Bearer {AGENTMAIL_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'to': [LEAD_NOTIFY_TO],
                'subject': subject,
                'html': html_body,
            },
            timeout=10,
        )
        if resp.status_code in (200, 201, 202):
            print(f"Lead notification sent to {LEAD_NOTIFY_TO} via AgentMail.")
        else:
            print(f"WARNING: AgentMail returned {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"WARNING: Failed to send lead notification via AgentMail: {e}")


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
