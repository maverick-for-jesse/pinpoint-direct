from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.utils.db_helpers import get_records, get_record, update_record, create_record
from app.utils.database import get_db, get_db_type, db_fetchone
from functools import wraps
import os, time
from datetime import datetime
from werkzeug.utils import secure_filename

client_bp = Blueprint('client', __name__)


def client_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_client():
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated


def client_name():
    return current_user.client or ''


def has_business_profile():
    """Check if current user has completed their business profile."""
    try:
        with get_db() as db:
            row = db_fetchone(db, "SELECT id FROM business_profiles WHERE user_id = ?",
                              (current_user.id,))
        return row is not None
    except Exception:
        # Table may not exist yet (migration not run) — don't block access
        return True


def get_client_campaigns():
    name = client_name()
    campaigns = get_records('campaigns', filter_formula=f"{{Client}}='{name}'")
    return sorted(campaigns, key=lambda x: x.get('createdTime',''), reverse=True)


def get_client_invoices():
    name = client_name()
    invoices = get_records('invoices', filter_formula=f"{{Client}}='{name}'")
    return sorted(invoices, key=lambda x: x.get('createdTime',''), reverse=True)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@client_bp.route('/')
@login_required
@client_required
def dashboard():
    campaigns = get_client_campaigns()
    invoices  = get_client_invoices()

    active_statuses = ('Artwork Pending', 'List Building', 'List Approval Pending', 'In Production')
    active = [c for c in campaigns if c['fields'].get('Status') in active_statuses]

    pieces_mailed = sum(
        int(c['fields'].get('Piece Count', 0) or 0)
        for c in campaigns if c['fields'].get('Status') == 'Mailed'
    )

    outstanding = sum(
        float(i['fields'].get('Amount', 0) or 0)
        for i in invoices if i['fields'].get('Status') in ('Sent','Overdue')
    )

    pending_approvals = len([
        c for c in campaigns
        if c['fields'].get('Status') in ('Artwork Pending', 'List Approval Pending')
    ])

    # Get pending artwork items
    name = client_name()
    artwork_items = get_records('artwork', filter_formula=f"{{Client}}='{name}'")
    pending_artwork = [a for a in artwork_items if a['fields'].get('Status') == 'Pending Review']
    pending_approvals += len(pending_artwork)  # add artwork items too

    unpaid_invoices = [i for i in invoices if i['fields'].get('Status') in ('Sent','Overdue')]

    stats = {
        'active':        len(active),
        'pieces_mailed': pieces_mailed,
        'outstanding':   outstanding,
    }

    return render_template('client/dashboard.html',
                           campaigns=campaigns,
                           stats=stats,
                           pending_approvals=pending_approvals,
                           unpaid_invoices=unpaid_invoices[:3],
                           has_profile=has_business_profile())


# ── Business Profile / Onboarding ─────────────────────────────────────────────

@client_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@client_required
def onboarding():
    from app.utils.database import get_db, db_fetchone, db_exec, db_insert
    db = get_db()
    user_id = current_user.id

    profile = db_fetchone(db, 'SELECT * FROM business_profiles WHERE user_id = ?', (user_id,))

    if request.method == 'POST':
        fields = [
            'business_name', 'business_type', 'years_in_business',
            'average_transaction_value', 'top_services', 'best_customer_description',
            'customer_compliment', 'main_competitor', 'competitive_advantage', 'website_url'
        ]
        values = {f: request.form.get(f, '').strip() for f in fields}

        if profile:
            set_clause = ', '.join(f'{f}=?' for f in fields) + ', updated_at=CURRENT_TIMESTAMP'
            params = list(values.values()) + [user_id]
            db_exec(db, f'UPDATE business_profiles SET {set_clause} WHERE user_id=?', params)
        else:
            # Only include client_id if available
            client_id = getattr(current_user, 'client_id', None)
            insert_cols = ['user_id'] + (['client_id'] if client_id is not None else []) + fields
            insert_vals = [user_id] + ([client_id] if client_id is not None else []) + list(values.values())
            placeholders = ', '.join(['?'] * len(insert_vals))
            cols = ', '.join(insert_cols)
            db_insert(db, f'INSERT INTO business_profiles ({cols}) VALUES ({placeholders})', insert_vals)

        db.commit()
        if hasattr(db, 'close'):
            db.close()
        flash('✅ Business profile saved!', 'success')
        return redirect(url_for('client.campaigns'))

    if hasattr(db, 'close'):
        db.close()
    return render_template('client/onboarding.html', profile=profile)


# ── Campaigns ─────────────────────────────────────────────────────────────────

@client_bp.route('/campaigns')
@login_required
@client_required
def campaigns():
    campaigns = get_client_campaigns()
    return render_template('client/campaigns.html', campaigns=campaigns)


# ── Approvals ─────────────────────────────────────────────────────────────────

@client_bp.route('/approvals')
@login_required
@client_required
def approvals():
    name = client_name()
    campaigns = get_client_campaigns()

    # Artwork needing approval
    artwork_items = get_records('artwork', filter_formula=f"{{Client}}='{name}'")
    artwork_pending = [a for a in artwork_items if a['fields'].get('Status') == 'Pending Review']

    # Campaigns needing mailing approval (legacy)
    mailing_pending = [c for c in campaigns
                       if c['fields'].get('Status') == 'Mailing Approval Pending']

    # Campaigns needing list approval (new flow)
    list_pending = [c for c in campaigns
                    if c['fields'].get('Status') == 'List Approval Pending']

    return render_template('client/approvals.html',
                           artwork_pending=artwork_pending,
                           mailing_pending=mailing_pending,
                           list_pending=list_pending)


@client_bp.route('/approvals/artwork/<int:record_id>', methods=['POST'])
@login_required
@client_required
def artwork_approve(record_id):
    decision     = request.form.get('decision', 'approve')
    client_notes = request.form.get('client_notes', '').strip()

    if decision == 'approve':
        fields = {'Status': 'Approved'}
        if client_notes:
            fields['Client Notes'] = client_notes
        update_record('artwork', record_id, fields)

        # Try to advance campaign to Artwork Approved
        art = get_record('artwork', record_id)
        campaign_name = art['fields'].get('Campaign','')
        if campaign_name:
            campaigns = get_records('campaigns',
                filter_formula=f"{{Campaign Name}}='{campaign_name}'")
            for c in campaigns:
                if c['fields'].get('Status') == 'Artwork Pending':
                    update_record('campaigns', c['id'], {'Status': 'Artwork Approved'})

        flash('Artwork approved! Your account manager has been notified.', 'success')

    elif decision == 'revise':
        fields = {'Status': 'Revision Requested'}
        if client_notes:
            fields['Client Notes'] = client_notes
        update_record('artwork', record_id, fields)
        flash('Revision requested. Your account manager will be in touch.', 'info')

    return redirect(url_for('client.approvals'))


@client_bp.route('/approvals/mailing/<int:record_id>', methods=['POST'])
@login_required
@client_required
def mailing_approve(record_id):
    decision = request.form.get('decision', 'approve')

    if decision == 'approve':
        update_record('campaigns', record_id, {'Status': 'Mailing Approved'})
        # Auto-create print job
        campaign = get_record('campaigns', record_id)
        f = campaign['fields']
        from app.utils.db_helpers import create_record
        existing_jobs = get_records('print_jobs',
            filter_formula=f"{{Campaign}}='{f.get('Campaign Name','')}'")
        if not existing_jobs:
            create_record('print_jobs', {
                'Job Name':    f.get('Campaign Name','') + ' — Print Job',
                'Campaign':    f.get('Campaign Name',''),
                'Client':      f.get('Client',''),
                'Piece Count': f.get('Piece Count', 0),
                'Status':      'Queued',
            })
        flash('Mailing approved and sent to the print queue! 🎉', 'success')

    elif decision == 'hold':
        update_record('campaigns', record_id, {'Status': 'Artwork Approved'})
        flash('Mailing put on hold. Contact your account manager with any questions.', 'info')

    return redirect(url_for('client.approvals'))


@client_bp.route('/approvals/list/<int:record_id>', methods=['POST'])
@login_required
@client_required
def list_approve(record_id):
    decision = request.form.get('decision', 'approve')
    if decision == 'approve':
        update_record('campaigns', record_id, {'Status': 'In Production'})
        campaign = get_record('campaigns', record_id)
        f = campaign['fields']
        existing_jobs = get_records('print_jobs',
            filter_formula=f"{{Campaign}}='{f.get('Campaign Name','')}'")
        if not existing_jobs:
            create_record('print_jobs', {
                'Job Name':    f.get('Campaign Name','') + ' — Print Job',
                'Campaign':    f.get('Campaign Name',''),
                'Client':      f.get('Client',''),
                'Piece Count': f.get('List Count') or f.get('Piece Count', 0),
                'Status':      'Queued',
            })
        flash('List approved! Your campaign is now in production. 🎉', 'success')
    elif decision == 'hold':
        update_record('campaigns', record_id, {'Status': 'List Building'})
        flash('List put on hold. Your account manager has been notified.', 'info')
    return redirect(url_for('client.approvals'))


# ── Invoices ──────────────────────────────────────────────────────────────────

@client_bp.route('/invoices')
@login_required
@client_required
def invoices():
    invoices = get_client_invoices()
    return render_template('client/invoices.html', invoices=invoices)


@client_bp.route('/invoices/<int:record_id>')
@login_required
@client_required
def invoice_detail(record_id):
    invoice = get_record('invoices', record_id)
    # Security: make sure this invoice belongs to this client
    if invoice['fields'].get('Client') != client_name():
        flash('Invoice not found.', 'error')
        return redirect(url_for('client.invoices'))
    return render_template('client/invoice_detail.html', invoice=invoice)


# ── Design Requests ───────────────────────────────────────────────────────────

ALLOWED_DESIGN_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf', '.ai', '.eps', '.svg', '.tif', '.tiff'}


def _allowed_design_file(filename):
    ext = os.path.splitext(filename.lower())[1]
    return ext in ALLOWED_DESIGN_EXTENSIONS


def _save_design_files(file_list, folder):
    """Upload a list of FileStorage objects to R2. Return list of R2 keys."""
    from app.utils.r2 import upload_file
    keys = []
    for f in file_list:
        if f and f.filename and _allowed_design_file(f.filename):
            try:
                key = upload_file(f.stream, f.filename, folder=folder)
                keys.append(key)
            except Exception as e:
                print(f"R2 upload error: {e}")
    return keys


@client_bp.route('/design-request')
@login_required
@client_required
def design_requests():
    client_id = getattr(current_user, 'client_id', None)
    drs = []
    if client_id:
        try:
            all_drs = get_records('design_requests')
            drs = [r for r in all_drs if r['fields'].get('client_id') == client_id]
            drs = sorted(drs, key=lambda x: x.get('createdTime', ''), reverse=True)
        except Exception:
            drs = []
    return render_template('client/design_requests.html', design_requests=drs)


@client_bp.route('/design-request/new', methods=['GET', 'POST'])
@login_required
@client_required
def design_request_new():
    # Try to pre-fill business name from client profile
    prefill_name = ''
    try:
        client_rec = get_records('clients', filter_formula=f"{{Company Name}}='{client_name()}'")
        if client_rec:
            prefill_name = client_rec[0]['fields'].get('Company Name', '')
    except Exception:
        pass

    # Load business profile for pre-fill
    profile = None
    try:
        from app.utils.database import get_db, db_fetchone
        with get_db() as db:
            profile = db_fetchone(db, 'SELECT * FROM business_profiles WHERE user_id = ?',
                                  (current_user.id,))
    except Exception:
        pass

    if request.method == 'POST':
        from app.utils.database import get_db, get_db_type
        ph = '%s' if get_db_type() == 'postgres' else '?'

        client_id = getattr(current_user, 'client_id', None)
        now = datetime.utcnow()
        ts = int(time.time())

        # Text fields
        fields_data = {
            'client_id':            client_id,
            'status':               'Submitted',
            'business_name':        request.form.get('business_name', '').strip(),
            'industry':             request.form.get('industry', '').strip(),
            'campaign_goal':        request.form.get('campaign_goal', '').strip(),
            'products_services':    request.form.get('products_services', '').strip(),
            'headline_ideas':       request.form.get('headline_ideas', '').strip(),
            'key_selling_points':   request.form.get('key_selling_points', '').strip(),
            'call_to_action':       request.form.get('call_to_action', '').strip(),
            'cta_url':              request.form.get('cta_url', '').strip(),
            'promo_code':           request.form.get('promo_code', '').strip(),
            'brand_colors':         request.form.get('brand_colors', '').strip(),
            'brand_tone':           request.form.get('brand_tone', '').strip(),
            'target_audience':      request.form.get('target_audience', '').strip(),
            'mailing_list_status':      request.form.get('mailing_list_status', 'Need one'),
            'mailing_list_targeting':   request.form.get('mailing_list_targeting', '').strip(),
            'target_zips':              request.form.get('target_zips', '').strip(),
            'return_address':           request.form.get('return_address', '').strip(),
            'additional_notes':     request.form.get('additional_notes', '').strip(),
            'submitted_at':         now,
            'created_at':           now,
        }
        qty = request.form.get('quantity', '').strip()
        if qty:
            try:
                fields_data['quantity'] = int(qty)
            except ValueError:
                pass
        tmd = request.form.get('target_mail_date', '').strip()
        if tmd:
            fields_data['target_mail_date'] = tmd

        # Insert first (no files yet)
        cols = [k for k in fields_data if fields_data[k] is not None and fields_data[k] != '']
        vals = [fields_data[c] for c in cols]
        placeholders = ', '.join([ph] * len(cols))
        col_str = ', '.join(cols)

        new_id = None
        with get_db() as db:
            if get_db_type() == 'postgres':
                sql = f"INSERT INTO design_requests ({col_str}) VALUES ({placeholders}) RETURNING id"
                with db.cursor() as cur:
                    cur.execute(sql, vals)
                    row = cur.fetchone()
                    new_id = row['id'] if row else None
            else:
                sql = f"INSERT INTO design_requests ({col_str}) VALUES ({placeholders})"
                cur = db.execute(sql, vals)
                new_id = cur.lastrowid
            db.commit()

        if new_id:
            # Handle file uploads to R2
            logo_files = request.files.getlist('logo_files')
            product_files = request.files.getlist('product_files')
            inspiration_files = request.files.getlist('inspiration_files')

            logo_paths = _save_design_files(logo_files, f"design_requests/{new_id}/logos")
            product_paths = _save_design_files(product_files, f"design_requests/{new_id}/products")
            insp_paths = _save_design_files(inspiration_files, f"design_requests/{new_id}/inspiration")

            # Update with file paths
            file_updates = {}
            if logo_paths:
                file_updates['logo_files'] = ','.join(logo_paths)
            if product_paths:
                file_updates['product_files'] = ','.join(product_paths)
            if insp_paths:
                file_updates['inspiration_files'] = ','.join(insp_paths)

            if file_updates:
                set_clause = ', '.join([f"{k} = {ph}" for k in file_updates])
                update_vals = list(file_updates.values()) + [new_id]
                with get_db() as db:
                    if get_db_type() == 'postgres':
                        with db.cursor() as cur:
                            cur.execute(f"UPDATE design_requests SET {set_clause} WHERE id = {ph}", update_vals)
                    else:
                        db.execute(f"UPDATE design_requests SET {set_clause} WHERE id = {ph}", update_vals)
                    db.commit()

        flash('Your design request has been submitted! We\'ll be in touch soon.', 'success')
        return redirect(url_for('client.design_requests'))

    return render_template('client/design_request_new.html', prefill_name=prefill_name, profile=profile)


@client_bp.route('/design-request/<int:dr_id>')
@login_required
@client_required
def design_request_detail(dr_id):
    from app.utils.r2 import get_presigned_url
    try:
        dr = get_record('design_requests', dr_id)
    except Exception:
        flash('Design request not found.', 'error')
        return redirect(url_for('client.design_requests'))
    # Security check
    if dr['fields'].get('client_id') != getattr(current_user, 'client_id', None):
        flash('Design request not found.', 'error')
        return redirect(url_for('client.design_requests'))

    # Generate presigned proof URL if available
    proof_url = None
    f = dr['fields']
    if f.get('Proof File'):
        try:
            proof_url = get_presigned_url(f['Proof File'], expires_in=3600)
        except Exception:
            pass

    return render_template('client/design_request_detail.html', dr=dr, proof_url=proof_url)


@client_bp.route('/design-request/<int:dr_id>/approve', methods=['POST'])
@login_required
@client_required
def design_request_approve(dr_id):
    try:
        dr = get_record('design_requests', dr_id)
    except Exception:
        flash('Design request not found.', 'error')
        return redirect(url_for('client.design_requests'))
    if dr['fields'].get('client_id') != getattr(current_user, 'client_id', None):
        flash('Not authorized.', 'error')
        return redirect(url_for('client.design_requests'))

    ph = '%s' if get_db_type() == 'postgres' else '?'
    now = datetime.utcnow()
    with get_db() as db:
        if get_db_type() == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"UPDATE design_requests SET status={ph}, approved_at={ph} WHERE id={ph}",
                            ('Final Approved', now, dr_id))
        else:
            db.execute(f"UPDATE design_requests SET status={ph}, approved_at={ph} WHERE id={ph}",
                       ('Final Approved', now, dr_id))
        db.commit()

    flash('Proof approved! Your design is finalized. 🎉', 'success')
    return redirect(url_for('client.design_request_detail', dr_id=dr_id))


@client_bp.route('/design-request/<int:dr_id>/revise', methods=['POST'])
@login_required
@client_required
def design_request_revise(dr_id):
    try:
        dr = get_record('design_requests', dr_id)
    except Exception:
        flash('Design request not found.', 'error')
        return redirect(url_for('client.design_requests'))
    if dr['fields'].get('client_id') != getattr(current_user, 'client_id', None):
        flash('Not authorized.', 'error')
        return redirect(url_for('client.design_requests'))

    feedback = request.form.get('client_feedback', '').strip()
    rev_round = (dr['fields'].get('Revision Round') or 0) + 1
    rev_limit = dr['fields'].get('Revision Limit') or 2

    ph = '%s' if get_db_type() == 'postgres' else '?'
    with get_db() as db:
        if get_db_type() == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"UPDATE design_requests SET status={ph}, client_feedback={ph}, revision_round={ph} WHERE id={ph}",
                            ('Revision Requested', feedback, rev_round, dr_id))
        else:
            db.execute(f"UPDATE design_requests SET status={ph}, client_feedback={ph}, revision_round={ph} WHERE id={ph}",
                       ('Revision Requested', feedback, rev_round, dr_id))
        db.commit()

    if rev_round >= rev_limit:
        flash(f'Revision {rev_round} of {rev_limit} requested. Note: you\'ve reached your revision limit — additional revisions may incur extra charges.', 'warning')
    else:
        flash(f'Revision {rev_round} of {rev_limit} requested. Our designer will update the proof shortly.', 'info')
    return redirect(url_for('client.design_request_detail', dr_id=dr_id))


# ── AI Copy Generator ──────────────────────────────────────────────────────────

@client_bp.route('/ai-copy', methods=['POST'])
@login_required
@client_required
def ai_copy():
    """Generate headline/body/CTA suggestions from the design brief form data."""
    from app.utils.copy_generator import generate_campaign_copy
    from app.utils.database import get_db, db_fetchone

    db = get_db()
    try:
        profile = db_fetchone(db, 'SELECT * FROM business_profiles WHERE user_id = ?', (current_user.id,))
    except Exception:
        profile = None
    if hasattr(db, 'close'): db.close()

    data = request.get_json() or {}

    # Build profile dict — merge saved profile with any live form overrides
    profile_dict = dict(profile) if profile else {}
    for field in ['business_name', 'business_type', 'top_services', 'best_customer_description',
                  'customer_compliment', 'competitive_advantage', 'years_in_business',
                  'average_transaction_value', 'website_url']:
        if data.get(field):
            profile_dict[field] = data[field]

    campaign_dict = {
        'what_promoting':  data.get('products_services', ''),
        'offer_type':      data.get('offer_type', 'special offer'),
        'offer_detail':    data.get('offer_detail', data.get('additional_notes', '')),
        'desired_action':  data.get('call_to_action', 'call us'),
        'has_deadline':    bool(data.get('target_mail_date')),
        'deadline_date':   data.get('target_mail_date', ''),
    }

    try:
        result = generate_campaign_copy(profile_dict, campaign_dict)
        return jsonify({'ok': True, 'copy': result})
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"AI copy error: {e}\n{tb}")
        return jsonify({'ok': False, 'error': str(e), 'detail': tb[-500:]}), 500


# ── Edit Design Request ────────────────────────────────────────────────────────

@client_bp.route('/design-request/<int:dr_id>/edit', methods=['GET', 'POST'])
@login_required
@client_required
def design_request_edit(dr_id):
    """Allow client to edit a design request that hasn't been picked up yet."""
    from app.utils.database import get_db, db_fetchone, db_exec, get_db_type

    db = get_db()
    dr = db_fetchone(db, 'SELECT * FROM design_requests WHERE id = ?', (dr_id,))
    if hasattr(db, 'close'): db.close()

    if not dr:
        flash('Design request not found.', 'error')
        return redirect(url_for('client.design_requests'))

    # Security check
    if dr.get('client_id') != getattr(current_user, 'client_id', None):
        flash('Not authorised.', 'error')
        return redirect(url_for('client.design_requests'))

    # Only allow editing if still in editable status
    editable_statuses = ('Draft', 'Submitted', 'Revision Requested', 'Needs Client Input')
    if dr.get('status') not in editable_statuses:
        flash('This request is already in progress and can no longer be edited. Use the revision request instead.', 'warning')
        return redirect(url_for('client.design_request_detail', dr_id=dr_id))

    # Load business profile for pre-fill
    db2 = get_db()
    profile = db_fetchone(db2, 'SELECT * FROM business_profiles WHERE user_id = ?', (current_user.id,))
    if hasattr(db2, 'close'): db2.close()

    if request.method == 'POST':
        import time
        from app.utils.database import get_db, get_db_type
        ph = '%s' if get_db_type() == 'postgres' else '?'

        fields_data = {
            'business_name':        request.form.get('business_name', '').strip(),
            'industry':             request.form.get('industry', '').strip(),
            'campaign_goal':        request.form.get('campaign_goal', '').strip(),
            'products_services':    request.form.get('products_services', '').strip(),
            'headline_ideas':       request.form.get('headline_ideas', '').strip(),
            'key_selling_points':   request.form.get('key_selling_points', '').strip(),
            'call_to_action':       request.form.get('call_to_action', '').strip(),
            'cta_url':              request.form.get('cta_url', '').strip(),
            'promo_code':           request.form.get('promo_code', '').strip(),
            'brand_colors':         request.form.get('brand_colors', '').strip(),
            'brand_tone':           request.form.get('brand_tone', '').strip(),
            'target_audience':      request.form.get('target_audience', '').strip(),
            'mailing_list_status':  request.form.get('mailing_list_status', '').strip(),
            'return_address':       request.form.get('return_address', '').strip(),
            'additional_notes':     request.form.get('additional_notes', '').strip(),
            'mailing_list_targeting': request.form.get('mailing_list_targeting', '').strip(),
            'target_zips':          request.form.get('target_zips', '').strip(),
            'status':               'Submitted',
        }
        qty = request.form.get('quantity', '').strip()
        if qty:
            try: fields_data['quantity'] = int(qty)
            except ValueError: pass
        tmd = request.form.get('target_mail_date', '').strip()
        if tmd:
            fields_data['target_mail_date'] = tmd

        set_clause = ', '.join(f'{k} = {ph}' for k in fields_data)
        vals = list(fields_data.values()) + [dr_id]

        db3 = get_db()
        db_exec(db3, f'UPDATE design_requests SET {set_clause} WHERE id = {ph}', vals)

        # Handle new file uploads (append to existing)
        ts = int(time.time())
        logo_files = request.files.getlist('logo_files')
        product_files = request.files.getlist('product_files')
        inspiration_files = request.files.getlist('inspiration_files')

        new_logos = _save_design_files(logo_files, f"design_requests/{dr_id}/logos")
        new_products = _save_design_files(product_files, f"design_requests/{dr_id}/products")
        new_inspi = _save_design_files(inspiration_files, f"design_requests/{dr_id}/inspiration")

        file_updates = {}
        if new_logos:
            existing = dr.get('logo_files') or ''
            file_updates['logo_files'] = ','.join(filter(None, [existing] + new_logos))
        if new_products:
            existing = dr.get('product_files') or ''
            file_updates['product_files'] = ','.join(filter(None, [existing] + new_products))
        if new_inspi:
            existing = dr.get('inspiration_files') or ''
            file_updates['inspiration_files'] = ','.join(filter(None, [existing] + new_inspi))

        if file_updates:
            set2 = ', '.join(f'{k} = {ph}' for k in file_updates)
            db_exec(db3, f'UPDATE design_requests SET {set2} WHERE id = {ph}', list(file_updates.values()) + [dr_id])

        db3.commit()
        if hasattr(db3, 'close'): db3.close()

        flash('✅ Design request updated.', 'success')
        return redirect(url_for('client.design_request_detail', dr_id=dr_id))

    return render_template('client/design_request_new.html',
                           prefill_name=dr.get('business_name', ''),
                           profile=profile,
                           editing=dr,
                           edit_id=dr_id)
