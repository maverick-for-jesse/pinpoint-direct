"""
Campaign Wizard + Business Profile routes.
Registered at /portal (same prefix as client_bp).

Routes:
  GET/POST  /portal/onboarding              — Business profile setup
  GET       /portal/wizard                  — Start new campaign (step 1)
  POST      /portal/wizard/start            — Submit step 1, create campaign
  GET/POST  /portal/wizard/<id>/step2       — Audience & postcard details
  GET/POST  /portal/wizard/<id>/step3       — Design Brief (NEW)
  GET/POST  /portal/wizard/<id>/step4       — Files & Assets (NEW)
  GET       /portal/wizard/<id>/step5       — AI copy selection
  POST      /portal/wizard/<id>/generate-copy  — AJAX: generate AI copy
  POST      /portal/wizard/<id>/complete    — Save selections, finish wizard
"""

import json
import os
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app.utils.database import get_db, db_fetchone, db_fetchall, db_insert, db_exec
from app.utils.copy_generator import generate_campaign_copy
from functools import wraps
from werkzeug.utils import secure_filename

wizard_bp = Blueprint('wizard', __name__)

# ─── Allowed file types for uploads ──────────────────────────────────────────

ALLOWED_CAMPAIGN_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf', '.ai', '.eps', '.svg', '.tif', '.tiff'}


def _allowed_campaign_file(filename):
    ext = os.path.splitext(filename.lower())[1]
    return ext in ALLOWED_CAMPAIGN_EXTENSIONS


def _save_campaign_files(file_list, campaign_id, subfolder):
    """Upload a list of FileStorage objects to R2 under campaigns/<id>/<subfolder>/. Return list of R2 keys."""
    from app.utils.r2 import upload_file
    keys = []
    for f in file_list:
        if f and f.filename and _allowed_campaign_file(f.filename):
            try:
                folder = f"campaigns/{campaign_id}/{subfolder}"
                key = upload_file(f.stream, f.filename, folder=folder)
                keys.append(key)
            except Exception as e:
                print(f"R2 upload error: {e}")
    return keys


# ─── Decorators ──────────────────────────────────────────────────────────────

def client_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_client():
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated


# ─── DB helpers ──────────────────────────────────────────────────────────────

def _get_business_profile():
    """Get business profile row for current user, or None."""
    with get_db() as db:
        return db_fetchone(db, "SELECT * FROM business_profiles WHERE user_id = ?",
                           (current_user.id,))


def _get_user_client_id():
    """Look up the client_id integer for current user."""
    with get_db() as db:
        row = db_fetchone(db, "SELECT client_id FROM users WHERE id = ?", (current_user.id,))
    return row['client_id'] if row else None


def _get_campaign(campaign_id):
    """Get full campaign row (including wizard columns) for current user's client."""
    with get_db() as db:
        # Join to verify this campaign belongs to current client
        return db_fetchone(db, """
            SELECT c.*, cl.company_name AS client_name
            FROM campaigns c
            JOIN clients cl ON c.client_id = cl.id
            JOIN users u ON u.client_id = cl.id
            WHERE c.id = ? AND u.id = ?
        """, (campaign_id, current_user.id))


# ─── Onboarding (Business Profile) ───────────────────────────────────────────

@wizard_bp.route('/onboarding', methods=['GET', 'POST'])
@login_required
@client_required
def onboarding():
    profile = _get_business_profile()

    if request.method == 'POST':
        bname  = request.form.get('business_name', '').strip()
        btype  = request.form.get('business_type', '').strip()
        years  = request.form.get('years_in_business', '').strip()
        avg_tx = request.form.get('average_transaction_value', '').strip()
        svcs   = request.form.get('top_services', '').strip()
        cust   = request.form.get('best_customer_description', '').strip()
        comp   = request.form.get('customer_compliment', '').strip()
        rival  = request.form.get('main_competitor', '').strip()
        adv    = request.form.get('competitive_advantage', '').strip()

        if not bname or not btype:
            flash('Business name and type are required.', 'error')
            return render_template('client/onboarding.html', profile=profile)

        with get_db() as db:
            if profile:
                db_exec(db, """
                    UPDATE business_profiles SET
                        business_name=?, business_type=?, years_in_business=?,
                        average_transaction_value=?, top_services=?,
                        best_customer_description=?, customer_compliment=?,
                        main_competitor=?, competitive_advantage=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE user_id=?
                """, (bname, btype, years, avg_tx, svcs, cust, comp, rival, adv, current_user.id))
            else:
                db_insert(db, """
                    INSERT INTO business_profiles
                        (user_id, client_name, business_name, business_type,
                         years_in_business, average_transaction_value, top_services,
                         best_customer_description, customer_compliment,
                         main_competitor, competitive_advantage)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (current_user.id, current_user.client, bname, btype, years,
                      avg_tx, svcs, cust, comp, rival, adv))

        flash('Business profile saved! Now let\'s create your first campaign.', 'success')
        return redirect(url_for('wizard.new_campaign'))

    return render_template('client/onboarding.html', profile=profile)


# ─── Wizard Step 1 — The Offer ────────────────────────────────────────────────

@wizard_bp.route('/wizard', methods=['GET'])
@login_required
@client_required
def new_campaign():
    # If no business profile, redirect to onboarding
    if not _get_business_profile():
        flash('Please complete your business profile first.', 'info')
        return redirect(url_for('wizard.onboarding'))
    return render_template('client/wizard_step1.html')


@wizard_bp.route('/wizard/start', methods=['POST'])
@login_required
@client_required
def wizard_step1_submit():
    if not _get_business_profile():
        return redirect(url_for('wizard.onboarding'))

    campaign_name  = request.form.get('campaign_name', '').strip()
    what_promoting = request.form.get('what_promoting', '').strip()
    offer_type     = request.form.get('offer_type', '').strip()
    offer_detail   = request.form.get('offer_detail', '').strip()
    has_deadline   = request.form.get('has_deadline') == '1'
    deadline_date  = request.form.get('deadline_date', '').strip() or None
    desired_action = request.form.get('desired_action', '').strip()
    phone_number   = request.form.get('phone_number', '').strip()
    website_url    = request.form.get('website_url', '').strip()

    if not campaign_name or not what_promoting:
        flash('Campaign name and what you\'re promoting are required.', 'error')
        return render_template('client/wizard_step1.html')

    client_id = _get_user_client_id()
    if not client_id:
        flash('Account setup issue — please contact support.', 'error')
        return redirect(url_for('client.dashboard'))

    with get_db() as db:
        campaign_id = db_insert(db, """
            INSERT INTO campaigns
                (client_id, name, status, what_promoting, offer_type, offer_detail,
                 has_deadline, deadline_date, desired_action, phone_number, website_url,
                 wizard_step, wizard_completed)
            VALUES (?, ?, 'Draft', ?, ?, ?, ?, ?, ?, ?, ?, 2, false)
        """, (client_id, campaign_name, what_promoting, offer_type, offer_detail,
              has_deadline, deadline_date, desired_action, phone_number, website_url))

    return redirect(url_for('wizard.wizard_step2', campaign_id=campaign_id))


# ─── Wizard Step 2 — The Audience ─────────────────────────────────────────────

@wizard_bp.route('/wizard/<int:campaign_id>/step2', methods=['GET', 'POST'])
@login_required
@client_required
def wizard_step2(campaign_id):
    campaign = _get_campaign(campaign_id)
    if not campaign:
        flash('Campaign not found.', 'error')
        return redirect(url_for('client.campaigns'))

    if request.method == 'POST':
        target_area = request.form.get('target_area_description', '').strip()
        postcard_size = request.form.get('postcard_size', '6x9').strip()
        qty_raw = request.form.get('estimated_quantity', '').strip()
        estimated_quantity = int(qty_raw) if qty_raw.isdigit() else None

        with get_db() as db:
            db_exec(db, """
                UPDATE campaigns SET
                    target_area_description=?, postcard_size=?,
                    estimated_quantity=?, wizard_step=3
                WHERE id=?
            """, (target_area, postcard_size, estimated_quantity, campaign_id))

        return redirect(url_for('wizard.wizard_step3', campaign_id=campaign_id))

    return render_template('client/wizard_step2.html', campaign=campaign)


# ─── Wizard Step 3 — Design Brief ─────────────────────────────────────────────

@wizard_bp.route('/wizard/<int:campaign_id>/step3', methods=['GET', 'POST'])
@login_required
@client_required
def wizard_step3(campaign_id):
    campaign = _get_campaign(campaign_id)
    if not campaign:
        flash('Campaign not found.', 'error')
        return redirect(url_for('client.campaigns'))

    if request.method == 'POST':
        headline_ideas    = request.form.get('headline_ideas', '').strip()
        key_selling_pts   = request.form.get('key_selling_points', '').strip()
        brand_colors      = request.form.get('brand_colors', '').strip()
        brand_tone        = request.form.get('brand_tone', '').strip()
        return_address    = request.form.get('return_address', '').strip()

        with get_db() as db:
            db_exec(db, """
                UPDATE campaigns SET
                    headline_ideas=?, key_selling_points=?, brand_colors=?,
                    brand_tone=?, return_address=?, wizard_step=4
                WHERE id=?
            """, (headline_ideas, key_selling_pts, brand_colors, brand_tone,
                  return_address, campaign_id))

        return redirect(url_for('wizard.wizard_step4', campaign_id=campaign_id))

    return render_template('client/wizard_step3.html', campaign=campaign)


# ─── Wizard Step 4 — Files & Assets ───────────────────────────────────────────

@wizard_bp.route('/wizard/<int:campaign_id>/step4', methods=['GET', 'POST'])
@login_required
@client_required
def wizard_step4(campaign_id):
    campaign = _get_campaign(campaign_id)
    if not campaign:
        flash('Campaign not found.', 'error')
        return redirect(url_for('client.campaigns'))

    if request.method == 'POST':
        logo_files        = request.files.getlist('logo_files')
        product_files     = request.files.getlist('product_files')
        inspiration_files = request.files.getlist('inspiration_files')

        logo_keys        = _save_campaign_files(logo_files, campaign_id, 'logos')
        product_keys     = _save_campaign_files(product_files, campaign_id, 'products')
        inspiration_keys = _save_campaign_files(inspiration_files, campaign_id, 'inspiration')

        # Merge with any previously saved keys
        existing_logo    = json.loads(campaign.get('logo_files') or '[]')
        existing_product = json.loads(campaign.get('product_files') or '[]')
        existing_insp    = json.loads(campaign.get('inspiration_files') or '[]')

        all_logo    = existing_logo + logo_keys
        all_product = existing_product + product_keys
        all_insp    = existing_insp + inspiration_keys

        with get_db() as db:
            db_exec(db, """
                UPDATE campaigns SET
                    logo_files=?, product_files=?, inspiration_files=?, wizard_step=5
                WHERE id=?
            """, (json.dumps(all_logo), json.dumps(all_product), json.dumps(all_insp), campaign_id))

        return redirect(url_for('wizard.wizard_step5', campaign_id=campaign_id))

    return render_template('client/wizard_step4.html', campaign=campaign)


# ─── Wizard Step 5 — AI Copy ──────────────────────────────────────────────────

@wizard_bp.route('/wizard/<int:campaign_id>/step5', methods=['GET'])
@login_required
@client_required
def wizard_step5(campaign_id):
    campaign = _get_campaign(campaign_id)
    if not campaign:
        flash('Campaign not found.', 'error')
        return redirect(url_for('client.campaigns'))
    profile = _get_business_profile()
    return render_template('client/wizard_step5.html', campaign=campaign, profile=profile)


@wizard_bp.route('/wizard/<int:campaign_id>/generate-copy', methods=['POST'])
@login_required
@client_required
def generate_copy(campaign_id):
    """AJAX endpoint — returns JSON with headlines, body_copies, ctas."""
    campaign = _get_campaign(campaign_id)
    if not campaign:
        return jsonify({'error': 'Campaign not found'}), 404

    profile = _get_business_profile()
    if not profile:
        return jsonify({'error': 'Business profile not found'}), 400

    try:
        result = generate_campaign_copy(dict(profile), dict(campaign))
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@wizard_bp.route('/wizard/<int:campaign_id>/complete', methods=['POST'])
@login_required
@client_required
def wizard_complete(campaign_id):
    campaign = _get_campaign(campaign_id)
    if not campaign:
        flash('Campaign not found.', 'error')
        return redirect(url_for('client.campaigns'))

    selected_headline = request.form.get('selected_headline', '').strip()
    selected_body     = request.form.get('selected_body', '').strip()
    selected_cta      = request.form.get('selected_cta', '').strip()

    if not selected_headline or not selected_body or not selected_cta:
        flash('Please select a headline, body copy, and call-to-action.', 'error')
        return redirect(url_for('wizard.wizard_step5', campaign_id=campaign_id))

    with get_db() as db:
        db_exec(db, """
            UPDATE campaigns SET
                selected_headline=?, selected_body=?, selected_cta=?,
                wizard_completed=true, wizard_step=6, status='Draft'
            WHERE id=?
        """, (selected_headline, selected_body, selected_cta, campaign_id))

    flash('🎉 Campaign created! Your account manager will be in touch to finalize your design.', 'success')
    return redirect(url_for('client.campaigns'))


# ─── Edit Business Profile ───────────────────────────────────────────────────

@wizard_bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
@client_required
def edit_profile():
    """Allow client to update their business profile later."""
    return redirect(url_for('wizard.onboarding'))
