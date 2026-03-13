"""
Admin Campaign Wizard routes.
Registered on admin_bp (url_prefix='/admin').

Routes:
  GET       /admin/wizard                               — Client picker + profile status
  POST      /admin/wizard/start                         — Create campaign for selected client
  GET/POST  /admin/wizard/<campaign_id>/step1           — Offer details
  GET/POST  /admin/wizard/<campaign_id>/step2           — Audience & postcard size
  GET       /admin/wizard/<campaign_id>/step3           — AI copy selection
  POST      /admin/wizard/<campaign_id>/generate-copy   — AJAX: generate AI copy
  POST      /admin/wizard/<campaign_id>/complete        — Save and finish
  GET/POST  /admin/clients/<client_name>/business-profile  — Create/edit client business profile
"""

from flask import render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app.utils.database import get_db, db_fetchone, db_fetchall, db_insert, db_exec
from app.utils.copy_generator import generate_campaign_copy
from app.routes.admin import admin_bp, admin_required


# ─── DB helpers ──────────────────────────────────────────────────────────────

def _get_all_clients():
    """Return list of client dicts sorted by company_name."""
    with get_db() as db:
        rows = db_fetchall(db, "SELECT id, company_name FROM clients ORDER BY company_name")
    return rows


def _get_client_by_name(client_name):
    """Fetch a client row by company_name."""
    with get_db() as db:
        return db_fetchone(db, "SELECT * FROM clients WHERE company_name = ?", (client_name,))


def _get_client_by_id(client_id):
    """Fetch a client row by id."""
    with get_db() as db:
        return db_fetchone(db, "SELECT * FROM clients WHERE id = ?", (client_id,))


def _get_business_profile_by_client(client_name):
    """Get business profile for a client by client_name, or None."""
    with get_db() as db:
        return db_fetchone(db,
            "SELECT * FROM business_profiles WHERE client_name = ?",
            (client_name,))


def _get_campaign_admin(campaign_id):
    """Get campaign row; admin can see any campaign."""
    with get_db() as db:
        return db_fetchone(db, """
            SELECT c.*, cl.company_name AS client_company
            FROM campaigns c
            LEFT JOIN clients cl ON c.client_id = cl.id
            WHERE c.id = ?
        """, (campaign_id,))


# ─── Client Picker ───────────────────────────────────────────────────────────

@admin_bp.route('/wizard', methods=['GET'])
@login_required
@admin_required
def admin_wizard():
    clients = _get_all_clients()
    # Build a set of client_names that have a business profile
    profiles_with_data = set()
    with get_db() as db:
        profile_rows = db_fetchall(db, "SELECT client_name FROM business_profiles WHERE client_name IS NOT NULL")
    for row in profile_rows:
        profiles_with_data.add(row['client_name'])

    return render_template('admin/wizard_client_picker.html',
                           clients=clients,
                           profiles_with_data=profiles_with_data)


@admin_bp.route('/wizard/start', methods=['POST'])
@login_required
@admin_required
def admin_wizard_start():
    client_id_raw = request.form.get('client_id', '').strip()
    if not client_id_raw or not client_id_raw.isdigit():
        flash('Please select a client.', 'error')
        return redirect(url_for('admin.admin_wizard'))

    client_id = int(client_id_raw)
    client = _get_client_by_id(client_id)
    if not client:
        flash('Client not found.', 'error')
        return redirect(url_for('admin.admin_wizard'))

    client_name = client['company_name']
    profile = _get_business_profile_by_client(client_name)
    if not profile:
        flash(f'No business profile found for {client_name}. Please set one up first.', 'info')
        return redirect(url_for('admin.admin_client_business_profile', client_name=client_name))

    # Create a placeholder campaign (step1 will fill in details)
    with get_db() as db:
        campaign_id = db_insert(db, """
            INSERT INTO campaigns
                (client_id, name, status, wizard_step, wizard_completed)
            VALUES (?, 'New Campaign (Admin)', 'Draft', 1, false)
        """, (client_id,))

    return redirect(url_for('admin.admin_wizard_step1', campaign_id=campaign_id))


# ─── Step 1 — The Offer ──────────────────────────────────────────────────────

@admin_bp.route('/wizard/<int:campaign_id>/step1', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_wizard_step1(campaign_id):
    campaign = _get_campaign_admin(campaign_id)
    if not campaign:
        flash('Campaign not found.', 'error')
        return redirect(url_for('admin.admin_wizard'))

    if request.method == 'POST':
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
            return render_template('admin/wizard_step1.html', campaign=campaign)

        with get_db() as db:
            db_exec(db, """
                UPDATE campaigns SET
                    name=?, what_promoting=?, offer_type=?, offer_detail=?,
                    has_deadline=?, deadline_date=?, desired_action=?,
                    phone_number=?, website_url=?, wizard_step=2
                WHERE id=?
            """, (campaign_name, what_promoting, offer_type, offer_detail,
                  has_deadline, deadline_date, desired_action,
                  phone_number, website_url, campaign_id))

        return redirect(url_for('admin.admin_wizard_step2', campaign_id=campaign_id))

    return render_template('admin/wizard_step1.html', campaign=campaign)


# ─── Step 2 — Audience ───────────────────────────────────────────────────────

@admin_bp.route('/wizard/<int:campaign_id>/step2', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_wizard_step2(campaign_id):
    campaign = _get_campaign_admin(campaign_id)
    if not campaign:
        flash('Campaign not found.', 'error')
        return redirect(url_for('admin.admin_wizard'))

    if request.method == 'POST':
        target_area    = request.form.get('target_area_description', '').strip()
        postcard_size  = request.form.get('postcard_size', '6x9').strip()
        qty_raw        = request.form.get('estimated_quantity', '').strip()
        estimated_qty  = int(qty_raw) if qty_raw.isdigit() else None

        with get_db() as db:
            db_exec(db, """
                UPDATE campaigns SET
                    target_area_description=?, postcard_size=?,
                    estimated_quantity=?, wizard_step=3
                WHERE id=?
            """, (target_area, postcard_size, estimated_qty, campaign_id))

        return redirect(url_for('admin.admin_wizard_step3', campaign_id=campaign_id))

    return render_template('admin/wizard_step2.html', campaign=campaign)


# ─── Step 3 — AI Copy ────────────────────────────────────────────────────────

@admin_bp.route('/wizard/<int:campaign_id>/step3', methods=['GET'])
@login_required
@admin_required
def admin_wizard_step3(campaign_id):
    campaign = _get_campaign_admin(campaign_id)
    if not campaign:
        flash('Campaign not found.', 'error')
        return redirect(url_for('admin.admin_wizard'))

    client_name = campaign.get('client_company') or ''
    profile = _get_business_profile_by_client(client_name)
    return render_template('admin/wizard_step3.html', campaign=campaign, profile=profile)


@admin_bp.route('/wizard/<int:campaign_id>/generate-copy', methods=['POST'])
@login_required
@admin_required
def admin_generate_copy(campaign_id):
    """AJAX endpoint — returns JSON with headlines, body_copies, ctas."""
    campaign = _get_campaign_admin(campaign_id)
    if not campaign:
        return jsonify({'error': 'Campaign not found'}), 404

    client_name = campaign.get('client_company') or ''
    profile = _get_business_profile_by_client(client_name)
    if not profile:
        return jsonify({'error': 'Business profile not found for this client'}), 400

    try:
        result = generate_campaign_copy(dict(profile), dict(campaign))
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/wizard/<int:campaign_id>/complete', methods=['POST'])
@login_required
@admin_required
def admin_wizard_complete(campaign_id):
    campaign = _get_campaign_admin(campaign_id)
    if not campaign:
        flash('Campaign not found.', 'error')
        return redirect(url_for('admin.admin_wizard'))

    selected_headline = request.form.get('selected_headline', '').strip()
    selected_body     = request.form.get('selected_body', '').strip()
    selected_cta      = request.form.get('selected_cta', '').strip()

    if not selected_headline or not selected_body or not selected_cta:
        flash('Please select a headline, body copy, and call-to-action.', 'error')
        return redirect(url_for('admin.admin_wizard_step3', campaign_id=campaign_id))

    with get_db() as db:
        db_exec(db, """
            UPDATE campaigns SET
                selected_headline=?, selected_body=?, selected_cta=?,
                wizard_completed=true, wizard_step=4, status='Draft'
            WHERE id=?
        """, (selected_headline, selected_body, selected_cta, campaign_id))

    flash('✅ Campaign created via wizard! Review and advance status as needed.', 'success')
    # Redirect to admin campaign detail
    return redirect(url_for('admin.campaign_detail', record_id=campaign_id))


# ─── Business Profile (Admin) ─────────────────────────────────────────────────

@admin_bp.route('/clients/<path:client_name>/business-profile', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_client_business_profile(client_name):
    """Create or edit a business profile for any client."""
    client = _get_client_by_name(client_name)
    if not client:
        flash(f'Client "{client_name}" not found.', 'error')
        return redirect(url_for('admin.clients'))

    profile = _get_business_profile_by_client(client_name)

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
            return render_template('admin/wizard_business_profile.html',
                                   client=client, profile=profile, client_name=client_name)

        with get_db() as db:
            if profile:
                db_exec(db, """
                    UPDATE business_profiles SET
                        business_name=?, business_type=?, years_in_business=?,
                        average_transaction_value=?, top_services=?,
                        best_customer_description=?, customer_compliment=?,
                        main_competitor=?, competitive_advantage=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE client_name=?
                """, (bname, btype, years, avg_tx, svcs, cust, comp, rival, adv, client_name))
            else:
                db_insert(db, """
                    INSERT INTO business_profiles
                        (user_id, client_name, business_name, business_type,
                         years_in_business, average_transaction_value, top_services,
                         best_customer_description, customer_compliment,
                         main_competitor, competitive_advantage)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (None, client_name, bname, btype, years, avg_tx,
                      svcs, cust, comp, rival, adv))

        flash(f'Business profile for {client_name} saved!', 'success')
        next_url = request.form.get('next') or url_for('admin.admin_wizard')
        return redirect(next_url)

    return render_template('admin/wizard_business_profile.html',
                           client=client, profile=profile, client_name=client_name)
