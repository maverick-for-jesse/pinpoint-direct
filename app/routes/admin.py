from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, send_file
from flask_login import login_required, current_user
from app.utils.db_helpers import get_records, get_record, create_record, update_record, at_str
import os, base64

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Access denied.', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    campaigns = get_records('campaigns')
    clients = get_records('clients')
    invoices = get_records('invoices')
    print_jobs = get_records('print_jobs')

    active_campaigns = [c for c in campaigns if c['fields'].get('Status') not in ('Mailed', 'Cancelled', 'Draft')]
    pending_approvals = [c for c in campaigns if c['fields'].get('Status') in ('Artwork Pending', 'Mailing Approval Pending')]
    print_queue = [j for j in print_jobs if j['fields'].get('Status') == 'Queued']
    outstanding = sum(
        float(inv['fields'].get('Amount', 0))
        for inv in invoices
        if inv['fields'].get('Status') in ('Sent', 'Overdue')
    )

    stats = {
        'active_campaigns': len(active_campaigns),
        'pending_approvals': len(pending_approvals),
        'print_queue': len(print_queue),
        'outstanding_invoices': f'{outstanding:,.2f}'
    }

    recent_campaigns = sorted(campaigns, key=lambda x: x.get('createdTime', ''), reverse=True)[:5]
    recent_clients = sorted(clients, key=lambda x: x.get('createdTime', ''), reverse=True)[:5]

    return render_template('admin/dashboard.html',
                           stats=stats,
                           recent_campaigns=recent_campaigns,
                           recent_clients=recent_clients)


# ── Clients ──────────────────────────────────────────────────────────────────

@admin_bp.route('/clients')
@login_required
@admin_required
def clients():
    clients = get_records('clients')
    clients = sorted(clients, key=lambda x: x['fields'].get('Company Name', '').lower())
    return render_template('admin/clients.html', clients=clients)


@admin_bp.route('/clients/new', methods=['GET', 'POST'])
@login_required
@admin_required
def client_new():
    if request.method == 'POST':
        fields = {
            'Company Name': request.form.get('company_name', '').strip(),
            'Contact Name': request.form.get('contact_name', '').strip(),
            'Contact Email': request.form.get('contact_email', '').strip(),
            'Contact Phone': request.form.get('contact_phone', '').strip(),
            'Portal Username': request.form.get('portal_username', '').strip(),
            'Client Status': request.form.get('status', 'Active'),
            'Notes': request.form.get('notes', '').strip(),
        }
        # Remove empty fields
        fields = {k: v for k, v in fields.items() if v}
        try:
            create_record('clients', fields)
            flash(f"Client '{fields.get('Company Name')}' created.", 'success')
            return redirect(url_for('admin.clients'))
        except Exception as e:
            flash(f"Error: {str(e)}", 'error')
    return render_template('admin/client_form.html', client=None)


@admin_bp.route('/clients/<int:record_id>')
@login_required
@admin_required
def client_detail(record_id):
    client = get_record('clients', record_id)
    company_name = client['fields'].get('Company Name', '')
    campaigns = get_records('campaigns', filter_formula=f"{{Client}}='{company_name}'")
    invoices = get_records('invoices', filter_formula=f"{{Client}}='{company_name}'")
    return render_template('admin/client_detail.html',
                           client=client,
                           campaigns=campaigns,
                           invoices=invoices)


@admin_bp.route('/clients/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def client_edit(record_id):
    client = get_record('clients', record_id)
    if request.method == 'POST':
        fields = {
            'Company Name': request.form.get('company_name', '').strip(),
            'Contact Name': request.form.get('contact_name', '').strip(),
            'Contact Email': request.form.get('contact_email', '').strip(),
            'Contact Phone': request.form.get('contact_phone', '').strip(),
            'Portal Username': request.form.get('portal_username', '').strip(),
            'Status': request.form.get('status', 'Active'),
            'Notes': request.form.get('notes', '').strip(),
        }
        update_record('clients', record_id, fields)
        flash('Client updated.', 'success')
        return redirect(url_for('admin.client_detail', record_id=record_id))
    return render_template('admin/client_form.html', client=client)


# ── Campaigns ─────────────────────────────────────────────────────────────────

@admin_bp.route('/campaigns')
@login_required
@admin_required
def campaigns():
    campaigns = get_records('campaigns')
    campaigns = sorted(campaigns, key=lambda x: x.get('createdTime', ''), reverse=True)
    return render_template('admin/campaigns.html', campaigns=campaigns)


@admin_bp.route('/campaigns/new', methods=['GET', 'POST'])
@login_required
@admin_required
def campaign_new():
    clients = get_records('clients')
    if request.method == 'POST':
        fields = {
            'Campaign Name': request.form.get('campaign_name', '').strip(),
            'Client': request.form.get('client', '').strip(),
            'Postcard Size': request.form.get('postcard_size', '6x9'),
            'Status': request.form.get('status', 'Draft'),
            'Notes': request.form.get('notes', '').strip(),
        }
        piece_count = request.form.get('piece_count', '').strip()
        if piece_count:
            fields['Piece Count'] = int(piece_count)
        mail_date = request.form.get('mail_date', '').strip()
        if mail_date:
            fields['Mail Date'] = mail_date
        fields = {k: v for k, v in fields.items() if v != ''}
        try:
            record = create_record('campaigns', fields)
            flash(f"Campaign '{fields.get('Campaign Name')}' created.", 'success')
            return redirect(url_for('admin.campaign_detail', record_id=record['id']))
        except Exception as e:
            flash(f"Error creating campaign: {str(e)}", 'error')
    return render_template('admin/campaign_form.html', campaign=None, clients=clients)


@admin_bp.route('/campaigns/<int:record_id>')
@login_required
@admin_required
def campaign_detail(record_id):
    campaign = get_record('campaigns', record_id)
    campaign_name = campaign['fields'].get('Campaign Name', '')
    safe_name = at_str(campaign_name)
    artwork = get_records('artwork', filter_formula=f"{{Campaign}}='{safe_name}'")
    artwork = sorted(artwork, key=lambda x: x['fields'].get('Version', 0), reverse=True)
    print_jobs = get_records('print_jobs', filter_formula=f"{{Campaign}}='{safe_name}'")
    print_job = print_jobs[0] if print_jobs else None
    return render_template('admin/campaign_detail.html',
                           campaign=campaign,
                           artwork=artwork,
                           print_job=print_job)


@admin_bp.route('/campaigns/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def campaign_edit(record_id):
    campaign = get_record('campaigns', record_id)
    clients = get_records('clients')
    if request.method == 'POST':
        fields = {
            'Campaign Name': request.form.get('campaign_name', '').strip(),
            'Client': request.form.get('client', '').strip(),
            'Postcard Size': request.form.get('postcard_size', '6x9'),
            'Status': request.form.get('status', 'Draft'),
            'Notes': request.form.get('notes', '').strip(),
        }
        piece_count = request.form.get('piece_count', '').strip()
        if piece_count:
            fields['Piece Count'] = int(piece_count)
        mail_date = request.form.get('mail_date', '').strip()
        if mail_date:
            fields['Mail Date'] = mail_date
        update_record('campaigns', record_id, fields)
        flash('Campaign updated.', 'success')
        return redirect(url_for('admin.campaign_detail', record_id=record_id))
    return render_template('admin/campaign_form.html', campaign=campaign, clients=clients)


@admin_bp.route('/campaigns/<int:record_id>/advance', methods=['POST'])
@login_required
@admin_required
def campaign_advance(record_id):
    campaign = get_record('campaigns', record_id)
    current = campaign['fields'].get('Status', 'Draft')
    next_map = {
        'Draft': 'Artwork Pending',
        'Artwork Pending': 'Artwork Approved',
        'Artwork Approved': 'Mailing Approval Pending',
        'Mailing Approval Pending': 'Mailing Approved',
        'Mailing Approved': 'In Production',
        'In Production': 'Mailed',
    }
    next_status = next_map.get(current)
    if next_status:
        update_record('campaigns', record_id, {'Status': next_status})
        flash(f'Campaign moved to "{next_status}".', 'success')

        # Auto-create print job when campaign reaches Mailing Approved
        if next_status == 'Mailing Approved':
            campaign = get_record('campaigns', record_id)
            f = campaign['fields']
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
                flash('Print job created and added to queue.', 'info')

    return redirect(url_for('admin.campaign_detail', record_id=record_id))


@admin_bp.route('/campaigns/<int:record_id>/cancel', methods=['POST'])
@login_required
@admin_required
def campaign_cancel(record_id):
    update_record('campaigns', record_id, {'Status': 'Cancelled'})
    flash('Campaign cancelled.', 'success')
    return redirect(url_for('admin.campaign_detail', record_id=record_id))


# ── Postcard Builder ──────────────────────────────────────────────────────────

@admin_bp.route('/postcard-builder')
@login_required
@admin_required
def postcard_builder():
    campaigns = get_records('campaigns')
    campaigns = [c for c in campaigns if c['fields'].get('Status') not in ('Mailed', 'Cancelled')]
    campaigns = sorted(campaigns, key=lambda x: x['fields'].get('Campaign Name', ''))
    preselect = request.args.get('campaign', '')
    return render_template('admin/postcard_builder.html',
                           campaigns=campaigns,
                           preselect=preselect)


@admin_bp.route('/postcard-builder/generate-image', methods=['POST'])
@login_required
@admin_required
def generate_image():
    from app.utils.ideogram import generate_four_images
    data = request.get_json()
    prompt_a   = data.get('prompt_a', '').strip()
    prompt_b   = data.get('prompt_b', prompt_a).strip()
    style_type = data.get('style_type', 'REALISTIC')
    biz_type   = data.get('biz_type', 'business')
    biz_name   = data.get('biz_name', '')
    if not prompt_a:
        return jsonify({'error': 'Prompt is required.'}), 400
    # Back image prompts: softer, texture-based — complements front without competing
    back_prompt_a = (
        f"Soft lifestyle background for {biz_type} postcard back. "
        f"Muted tones, shallow depth of field, no text, no people, minimal, premium feel. "
        f"Same mood as: {prompt_a[:120]}"
    )
    back_prompt_b = (
        f"Subtle textured background for {biz_type} postcard back. "
        f"Different color palette from option A, elegant, no text, no faces. "
        f"Complements: {prompt_b[:120]}"
    )
    try:
        images = generate_four_images(prompt_a, prompt_b, back_prompt_a, back_prompt_b, style_type)
        return jsonify(images)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/postcard-builder/analyze-website', methods=['POST'])
@login_required
@admin_required
def analyze_website():
    from app.utils.website_analyzer import analyze_website as do_analyze
    data = request.get_json()
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL is required.'}), 400
    try:
        result = do_analyze(url)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'Could not analyze site: {str(e)}'}), 500


@admin_bp.route('/postcard-builder/generate-copy', methods=['POST'])
@login_required
@admin_required
def generate_copy():
    from app.utils.copy_generator import generate_postcard_copy
    data = request.get_json()
    try:
        result = generate_postcard_copy(
            business_name=data.get('business_name', ''),
            business_type=data.get('business_type', ''),
            offer_description=data.get('offer_description', ''),
            target_audience=data.get('target_audience', 'local customers')
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/postcard-builder/upload-asset', methods=['POST'])
@login_required
@admin_required
def upload_asset():
    import uuid
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file'}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']:
        return jsonify({'error': 'Invalid file type'}), 400
    filename = f"{uuid.uuid4().hex}{ext}"
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'uploads', 'assets')
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)
    # Return as base64 for preview
    with open(filepath, 'rb') as f:
        import base64 as _b64
        b64 = _b64.b64encode(f.read()).decode()
    return jsonify({'filename': filename, 'url': f'/uploads/assets/{filename}', 'base64': b64})


@admin_bp.route('/postcard-builder/save', methods=['POST'])
@login_required
@admin_required
def postcard_save():
    data = request.get_json()
    campaign_name = data.get('campaign_name', '').strip()
    campaign_id = data.get('campaign_id', '').strip()

    # Figure out version number
    existing = get_records('artwork', filter_formula=f"{{Campaign}}='{campaign_name.replace(chr(39), chr(92)+chr(39))}'") 
    version = len(existing) + 1

    fields = {
        'Artwork Name': f"{campaign_name} — v{version}",
        'Campaign': campaign_name,
        'Client': data.get('client', ''),
        'Status': 'Pending Review',
        'Version': version,
        'Staff Notes': data.get('staff_notes', ''),
    }
    fields = {k: v for k, v in fields.items() if v != '' and v != 0}
    record = create_record('artwork', fields)

    # Advance campaign to Artwork Pending if still Draft
    if campaign_id:
        try:
            campaign = get_record('campaigns', campaign_id)
            if campaign['fields'].get('Status') == 'Draft':
                update_record('campaigns', campaign_id, {'Status': 'Artwork Pending'})
        except Exception:
            pass

    return jsonify({'success': True, 'record_id': record['id'], 'version': version})


@admin_bp.route('/postcard-builder/export-pdf', methods=['POST'])
@login_required
@admin_required
def export_pdf():
    from app.utils.pdf import generate_postcard_pdf, WEASYPRINT_AVAILABLE
    if not WEASYPRINT_AVAILABLE:
        return jsonify({'error': 'WeasyPrint not installed. Run: pip install weasyprint'}), 500

    data = request.get_json()
    export_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'exports', 'print-jobs')
    os.makedirs(export_dir, exist_ok=True)

    try:
        path = generate_postcard_pdf(
            front_data=data.get('front', {}),
            back_data=data.get('back', {}),
            size=data.get('size', '6x9'),
            output_dir=export_dir
        )
        return send_file(path, as_attachment=True, download_name=os.path.basename(path), mimetype='application/pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/lists')
@login_required
@admin_required
def lists():
    from app.utils.database import get_db, init_db, db_fetchall
    init_db()
    with get_db() as db:
        mailing_lists = db_fetchall(db, "SELECT * FROM mailing_lists ORDER BY created_at DESC")
    campaigns = get_records('campaigns')
    return render_template('admin/lists.html', mailing_lists=mailing_lists, campaigns=campaigns)


@admin_bp.route('/lists/upload', methods=['POST'])
@login_required
@admin_required
def list_upload():
    from app.utils.database import get_db, init_db
    from app.utils.list_parser import parse_list_file
    init_db()

    file = request.files.get('file')
    if not file or file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('admin.lists'))

    list_name   = request.form.get('list_name', file.filename).strip()
    client      = request.form.get('client', '').strip()
    campaign    = request.form.get('campaign', '').strip()
    notes       = request.form.get('notes', '').strip()

    try:
        records, warnings = parse_list_file(file)
    except ValueError as e:
        flash(str(e), 'error')
        return redirect(url_for('admin.lists'))

    with get_db() as db:
        from app.utils.database import db_insert, db_executemany
        list_id = db_insert(db,
            "INSERT INTO mailing_lists (name, client, campaign, total, notes) VALUES (?,?,?,?,?)",
            (list_name, client, campaign, len(records), notes)
        )
        db_executemany(db,
            """INSERT INTO list_records
               (list_id, first_name, last_name, company, address1, address2, city, state, zip, offer_code)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [(list_id, r['first_name'], r['last_name'], r['company'],
              r['address1'], r['address2'], r['city'], r['state'], r['zip'], r['offer_code'])
             for r in records]
        )
        db.commit()

    for w in warnings:
        flash(w, 'info')
    flash(f"✅ Uploaded '{list_name}' — {len(records):,} records.", 'success')
    return redirect(url_for('admin.list_detail', list_id=list_id))


@admin_bp.route('/lists/<int:list_id>')
@login_required
@admin_required
def list_detail(list_id):
    from app.utils.database import get_db, db_fetchone, db_fetchall
    page = int(request.args.get('page', 1))
    per_page = 50
    offset = (page - 1) * per_page

    with get_db() as db:
        mailing_list = db_fetchone(db, "SELECT * FROM mailing_lists WHERE id=?", (list_id,))
        count_row = db_fetchone(db, "SELECT COUNT(*) as cnt FROM list_records WHERE list_id=?", (list_id,))
        total_records = count_row['cnt'] if count_row else 0
        records = db_fetchall(db,
            "SELECT * FROM list_records WHERE list_id=? LIMIT ? OFFSET ?",
            (list_id, per_page, offset)
        )
        stats = db_fetchone(db,
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN verify_status='verified' THEN 1 ELSE 0 END) as verified,
                SUM(CASE WHEN verify_status='failed'   THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN verify_status='pending'  THEN 1 ELSE 0 END) as pending
               FROM list_records WHERE list_id=?""",
            (list_id,)
        )

    total_pages = (total_records + per_page - 1) // per_page
    campaigns = get_records('campaigns')
    return render_template('admin/list_detail.html',
                           mailing_list=mailing_list,
                           records=records,
                           stats=stats,
                           page=page,
                           total_pages=total_pages,
                           campaigns=campaigns)


@admin_bp.route('/lists/<int:list_id>/verify', methods=['POST'])
@login_required
@admin_required
def list_verify(list_id):
    from app.utils.database import get_db, db_fetchall, db_exec
    from app.utils.usps import verify_address

    with get_db() as db:
        pending = db_fetchall(db,
            "SELECT * FROM list_records WHERE list_id=? AND verify_status='pending' LIMIT 500",
            (list_id,)
        )

        verified_count = 0
        failed_count = 0
        for row in pending:
            result = verify_address(
                address1=row['address1'] or '',
                city=row['city'] or '',
                state=row['state'] or '',
                zip5=row['zip'] or '',
                address2=row['address2'] or ''
            )
            status  = 'verified' if result['success'] else 'failed'
            message = result.get('message', '')
            updates = {'verify_status': status, 'verify_message': message}
            if result['success']:
                updates['address1'] = result.get('address1', row['address1'])
                updates['city']     = result.get('city', row['city'])
                updates['state']    = result.get('state', row['state'])
                updates['zip']      = result.get('zip5', row['zip'])
            db_exec(db,
                """UPDATE list_records SET verify_status=?, verify_message=?,
                   address1=?, city=?, state=?, zip=? WHERE id=?""",
                (status, message,
                 updates.get('address1', row['address1']),
                 updates.get('city', row['city']),
                 updates.get('state', row['state']),
                 updates.get('zip', row['zip']),
                 row['id'])
            )
            if result['success']: verified_count += 1
            else: failed_count += 1

        # Update summary counts
        db_exec(db,
            """UPDATE mailing_lists SET
               verified = (SELECT COUNT(*) FROM list_records WHERE list_id=? AND verify_status='verified'),
               failed   = (SELECT COUNT(*) FROM list_records WHERE list_id=? AND verify_status='failed')
               WHERE id=?""",
            (list_id, list_id, list_id)
        )
        db.commit()

    flash(f"Verified {verified_count:,} addresses. {failed_count:,} failed.", 'success')
    return redirect(url_for('admin.list_detail', list_id=list_id))


@admin_bp.route('/lists/<int:list_id>/assign', methods=['POST'])
@login_required
@admin_required
def list_assign(list_id):
    from app.utils.database import get_db, db_exec, db_fetchone
    campaign_name = request.form.get('campaign_name', '').strip()
    campaign_id   = request.form.get('campaign_id', '').strip()

    with get_db() as db:
        db_exec(db, "UPDATE mailing_lists SET campaign=? WHERE id=?", (campaign_name, list_id))
        db.commit()

    # Also update piece count on campaign
    if campaign_id:
        with get_db() as db:
            row = db_fetchone(db,
                "SELECT COUNT(*) as cnt FROM list_records WHERE list_id=? AND verify_status != 'failed'",
                (list_id,)
            )
            total = row['cnt'] if row else 0
        try:
            update_record('campaigns', int(campaign_id), {'Piece Count': total})
        except Exception:
            pass

    flash(f"List assigned to {campaign_name}.", 'success')
    return redirect(url_for('admin.list_detail', list_id=list_id))


@admin_bp.route('/lists/<int:list_id>/export')
@login_required
@admin_required
def list_export(list_id):
    from app.utils.database import get_db, db_fetchone, db_fetchall
    import csv
    import io
    from flask import Response

    only_verified = request.args.get('verified_only', '0') == '1'
    with get_db() as db:
        mailing_list = db_fetchone(db, "SELECT * FROM mailing_lists WHERE id=?", (list_id,))
        query = "SELECT * FROM list_records WHERE list_id=?"
        params = [list_id]
        if only_verified:
            query += " AND verify_status='verified'"
        records = db_fetchall(db, query, params)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        'first_name','last_name','company','address1','address2','city','state','zip','offer_code','verify_status'
    ])
    writer.writeheader()
    for r in records:
        writer.writerow({k: r.get(k,'') for k in writer.fieldnames})

    filename = f"{mailing_list['name'].replace(' ','_')}_{'verified_' if only_verified else ''}export.csv"
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@admin_bp.route('/lists/<int:list_id>/delete', methods=['POST'])
@login_required
@admin_required
def list_delete(list_id):
    from app.utils.database import get_db, db_exec
    with get_db() as db:
        db_exec(db, "DELETE FROM list_records WHERE list_id=?", (list_id,))
        db_exec(db, "DELETE FROM mailing_lists WHERE id=?", (list_id,))
        db.commit()
    flash('List deleted.', 'success')
    return redirect(url_for('admin.lists'))


@admin_bp.route('/print-queue')
@login_required
@admin_required
def print_queue():
    current_filter = request.args.get('status', 'all')
    all_jobs = get_records('print_jobs')
    all_jobs = sorted(all_jobs, key=lambda x: x.get('createdTime',''), reverse=True)

    counts = {}
    for job in all_jobs:
        s = job['fields'].get('Status','Queued')
        counts[s] = counts.get(s, 0) + 1

    if current_filter != 'all':
        jobs = [j for j in all_jobs if j['fields'].get('Status') == current_filter]
    else:
        jobs = all_jobs

    return render_template('admin/print_queue.html', jobs=jobs,
                           current_filter=current_filter, counts=counts)


@admin_bp.route('/print-queue/<int:record_id>')
@login_required
@admin_required
def print_job_detail(record_id):
    from datetime import date
    job = get_record('print_jobs', record_id)
    return render_template('admin/print_job_detail.html', job=job, today=date.today().isoformat())


@admin_bp.route('/print-queue/<int:record_id>/update', methods=['POST'])
@login_required
@admin_required
def print_job_update(record_id):
    from datetime import date
    action = request.form.get('action')
    job = get_record('print_jobs', record_id)
    fields = {}

    if action == 'start_printing':
        fields['Status'] = 'Printing'
    elif action == 'mark_printed':
        fields['Status'] = 'Printed'
        fields['Print Date'] = request.form.get('print_date', date.today().isoformat())
    elif action == 'mark_mailed':
        fields['Status'] = 'Mailed'
        fields['Mail Date'] = request.form.get('mail_date', date.today().isoformat())
        # Also advance campaign to Mailed
        campaign_name = job['fields'].get('Campaign', '')
        if campaign_name:
            campaigns = get_records('campaigns', filter_formula=f"{{Campaign Name}}='{campaign_name.replace(chr(39), chr(92)+chr(39))}'")
            for c in campaigns:
                if c['fields'].get('Status') == 'In Production':
                    update_record('campaigns', c['id'], {'Status': 'Mailed'})
    elif action == 'add_pdf':
        fields['PDF URL'] = request.form.get('pdf_url', '')
    elif action == 'add_note':
        existing = job['fields'].get('Notes', '')
        new_note = request.form.get('notes', '').strip()
        if new_note:
            fields['Notes'] = (existing + '\n' + new_note).strip()

    if fields:
        update_record('print_jobs', record_id, fields)
        flash('Print job updated.', 'success')
    return redirect(url_for('admin.print_job_detail', record_id=record_id))


# ── Invoices ──────────────────────────────────────────────────────────────────

@admin_bp.route('/invoices')
@login_required
@admin_required
def invoices():
    current_filter = request.args.get('status', 'all')
    all_invoices = get_records('invoices')
    all_invoices = sorted(all_invoices, key=lambda x: x.get('createdTime',''), reverse=True)

    def amount(inv):
        return float(inv['fields'].get('Amount', 0) or 0)

    totals = {
        'all':     sum(amount(i) for i in all_invoices),
        'sent':    sum(amount(i) for i in all_invoices if i['fields'].get('Status') == 'Sent'),
        'overdue': sum(amount(i) for i in all_invoices if i['fields'].get('Status') == 'Overdue'),
        'paid':    sum(amount(i) for i in all_invoices if i['fields'].get('Status') == 'Paid'),
    }

    if current_filter != 'all':
        invoices = [i for i in all_invoices if i['fields'].get('Status') == current_filter]
    else:
        invoices = all_invoices

    return render_template('admin/invoices.html', invoices=invoices,
                           current_filter=current_filter, totals=totals)


@admin_bp.route('/invoices/new', methods=['GET', 'POST'])
@login_required
@admin_required
def invoice_new():
    clients = get_records('clients')
    campaigns = get_records('campaigns')

    # Auto-generate next invoice number
    existing = get_records('invoices')
    next_num = f"INV-{len(existing)+1:04d}"

    if request.method == 'POST':
        fields = {
            'Invoice Number': request.form.get('invoice_number','').strip(),
            'Client':         request.form.get('client','').strip(),
            'Campaign':       request.form.get('campaign','').strip(),
            'Status':         request.form.get('status','Draft'),
            'Notes':          request.form.get('notes','').strip(),
        }
        amount = request.form.get('amount','').strip()
        if amount:
            fields['Amount'] = float(amount)
        due_date = request.form.get('due_date','').strip()
        if due_date:
            fields['Due Date'] = due_date
        fields = {k: v for k, v in fields.items() if v != ''}
        record = create_record('invoices', fields)
        flash(f"Invoice {fields.get('Invoice Number')} created.", 'success')
        return redirect(url_for('admin.invoice_detail', record_id=record['id']))

    return render_template('admin/invoice_form.html', invoice=None,
                           clients=clients, campaigns=campaigns, next_number=next_num)


@admin_bp.route('/invoices/<int:record_id>')
@login_required
@admin_required
def invoice_detail(record_id):
    from datetime import date
    invoice = get_record('invoices', record_id)
    return render_template('admin/invoice_detail.html', invoice=invoice, today=date.today().isoformat())


@admin_bp.route('/invoices/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def invoice_edit(record_id):
    invoice  = get_record('invoices', record_id)
    clients  = get_records('clients')
    campaigns = get_records('campaigns')

    if request.method == 'POST':
        fields = {
            'Invoice Number': request.form.get('invoice_number','').strip(),
            'Client':         request.form.get('client','').strip(),
            'Campaign':       request.form.get('campaign','').strip(),
            'Status':         request.form.get('status','Draft'),
            'Notes':          request.form.get('notes','').strip(),
        }
        amount = request.form.get('amount','').strip()
        if amount:
            fields['Amount'] = float(amount)
        due_date = request.form.get('due_date','').strip()
        if due_date:
            fields['Due Date'] = due_date
        paid_date = request.form.get('paid_date','').strip()
        if paid_date:
            fields['Paid Date'] = paid_date
        update_record('invoices', record_id, fields)
        flash('Invoice updated.', 'success')
        return redirect(url_for('admin.invoice_detail', record_id=record_id))

    return render_template('admin/invoice_form.html', invoice=invoice,
                           clients=clients, campaigns=campaigns, next_number='')


# ── New Movers ────────────────────────────────────────────────────────────────

SUPPORTED_COUNTIES = [
    'Coweta County GA',
    # Add more here as data becomes available
]

@admin_bp.route('/new-movers')
@login_required
@admin_required
def new_movers():
    from app.utils.db_helpers import get_records
    # Get all records (we need full fields for stats)
    try:
        records = get_records('new_movers')
    except Exception:
        records = []

    # Summarize by batch
    batches = {}
    for r in records:
        f = r['fields']
        batch = f.get('Upload Batch', 'Unknown')
        if batch not in batches:
            batches[batch] = {
                'county': f.get('County', ''),
                'count': 0,
                'tiers': {},
                'verified': 0,
                'failed': 0,
                'earliest_sale_date': None,
            }
        batches[batch]['count'] += 1
        tier = f.get('Tier', 'Standard')
        batches[batch]['tiers'][tier] = batches[batch]['tiers'].get(tier, 0) + 1
        vs = f.get('Verify Status', '')
        if vs == 'verified':
            batches[batch]['verified'] += 1
        elif vs == 'failed':
            batches[batch]['failed'] += 1
        # Track earliest (oldest) sale_date for golden window badge
        sd = f.get('Sale Date', '')
        if sd:
            prev = batches[batch]['earliest_sale_date']
            if prev is None or sd < prev:
                batches[batch]['earliest_sale_date'] = sd

    batch_list = sorted(batches.items(), reverse=True)

    # ── Missing Fields Report ─────────────────────────────────────────────────
    total = len(records)
    missing_zip          = sum(1 for r in records if not r['fields'].get('Zip', '').strip())
    missing_city         = sum(1 for r in records if not r['fields'].get('City', '').strip())
    missing_neighborhood = sum(1 for r in records if not r['fields'].get('Neighborhood', '').strip())
    missing_sale_price   = sum(1 for r in records if not r['fields'].get('Sale Price', ''))
    missing_fields = {
        'total':              total,
        'missing_zip':        missing_zip,
        'missing_city':       missing_city,
        'missing_neighborhood': missing_neighborhood,
        'missing_sale_price': missing_sale_price,
        'has_gaps':           any([missing_zip, missing_city, missing_neighborhood, missing_sale_price]),
    }

    return render_template('admin/new_movers.html',
                           batches=batch_list,
                           counties=SUPPORTED_COUNTIES,
                           total_records=total,
                           missing_fields=missing_fields)


@admin_bp.route('/new-movers/upload', methods=['POST'])
@login_required
@admin_required
def new_movers_upload():
    from app.utils.county_csv_parser import parse_county_csv
    from app.utils.db_helpers import create_record
    import time

    file = request.files.get('file')
    if not file or file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected.'})

    county = request.form.get('county', 'Coweta County GA')
    batch_label = request.form.get('batch_label', '').strip() or None

    try:
        records, stats, warnings = parse_county_csv(file, county=county, batch_label=batch_label)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error parsing CSV: {str(e)}'})

    if not records:
        return jsonify({'success': False, 'error': 'No qualifying records found (need Qualified FM Residential sales with addresses).'})

    # ── Sale Price Outlier Detection ──────────────────────────────────────────
    price_outliers = 0
    for rec in records:
        try:
            price = float(str(rec.get('Sale Price', 0) or 0))
            if price > 0 and (price < 50_000 or price > 2_000_000):
                price_outliers += 1
        except (ValueError, TypeError):
            pass

    # Build a set of (address, sale_date) already in Postgres to prevent duplicates on re-upload
    from app.utils.db_helpers import create_records_batch, get_records
    existing_keys = set()
    try:
        existing = get_records('new_movers', fields=['Address', 'Sale Date'])
        for r in existing:
            f = r.get('fields', {})
            key = (f.get('Address', '').strip().upper(), f.get('Sale Date', '').strip())
            existing_keys.add(key)
    except Exception:
        pass  # If we can't fetch, proceed without dedup check (better than blocking upload)

    deduped = []
    already_exists = 0
    for rec in records:
        key = (rec.get('Address', '').strip().upper(), rec.get('Sale Date', '').strip())
        if key in existing_keys:
            already_exists += 1
        else:
            deduped.append(rec)
            existing_keys.add(key)  # Prevent within-batch dupes too

    if not deduped:
        return jsonify({
            'success': True,
            'imported': 0,
            'skipped': stats.get('skipped', 0) + already_exists,
            'already_exists': already_exists,
            'skipped_investor': stats.get('skipped_investor', 0),
            'price_outliers': price_outliers,
            'errors': 0,
            'tier_summary': 'none',
            'warnings': [f'All {already_exists} records already exist in Postgres — nothing to import.'],
        })

    # Batch insert to Postgres (10 records per batch)
    uploaded = 0
    errors = 0
    BATCH_SIZE = 10

    for i in range(0, len(deduped), BATCH_SIZE):
        batch = deduped[i:i + BATCH_SIZE]
        try:
            created = create_records_batch('new_movers', batch)
            uploaded += len(created)
        except Exception as e:
            errors += len(batch)
        time.sleep(0.25)

    tier_summary = ', '.join(f"{v} {k}" for k, v in stats['by_tier'].items())
    # Note: dedup checks against ALL existing records (built from get_records above)
    dedup_note = f'{already_exists} duplicate(s) found and skipped' if already_exists else None
    return jsonify({
        'success': True,
        'imported': uploaded,
        'skipped': stats.get('skipped', 0),
        'already_exists': already_exists,
        'skipped_investor': stats.get('skipped_investor', 0),
        'price_outliers': price_outliers,
        'errors': errors,
        'tier_summary': tier_summary,
        'warnings': warnings,
        'dedup_note': dedup_note,
    })


COUNTY_CITIES = {
    'Coweta County GA': ['Newnan', 'Senoia', 'Grantville', 'Sharpsburg', 'Palmetto', 'Moreland', 'Turin'],
    'Fayette County GA': ['Fayetteville', 'Peachtree City', 'Tyrone', 'Brooks', 'Woolsey'],
}

# Coweta County subdivision → zip code map (for new construction Census can't find)
# Derived from known data + school district geography
COWETA_SUBDIVISION_ZIPS = {
    # Northgate HS area → mostly 30265
    'UL-Northgate HS-Arbor Springs': '30265',
    'UL-Northgate HS-Highgate': '30265',
    'UL-Northgate HS-Beaumont Farms': '30265',
    'UL-Northgate HS-Dappers Landing': '30265',
    'UL-Northgate HS-Creekrise': '30265',
    'UL-Northgate HS-Oconee Woods': '30265',
    'UL-Northgate HS-Kentucky Downs': '30263',
    'UL-Northgate HS-Genesee': '30268',
    'UL-Northgate HS-Wellborn': '30265',
    'UL-Northgate HS-Ashland Hills': '30265',
    'UL-Northgate HS-Barrington Farms': '30265',
    'UL-Northgate HS-Indian Bluff': '30265',
    'UL-Northgate HS-Britain Woods': '30265',
    'UL-Northgate HS-Oak Hill Reserve': '30265',
    'UL-Northgate HS-Mill Creek': '30265',
    'UL-Northgate HS-Platinum Ridge': '30265',
    'UL-Northgate HS-Spring Forest': '30265',
    'UL-Northgate HS-Strathmore': '30265',
    'UL-Northgate HS-Cannon Gate Acres': '30265',
    'UL-Northgate HS-Cannongate Village': '30265',
    'UL-Northgate HS-Widewater': '30265',
    'UL-Northgate HS-Chatsworth': '30265',
    'UL-Northgate HS-Wexford Plantation': '30265',
    'UL-Northgate HS-Firethorne': '30265',
    'UL-Northgate HS-Rayner Woods': '30265',
    'UL-Northgate HS-River Park': '30265',
    'UL-Northgate HS-HERRING FARMS': '30265',
    'UL-Northgate HS-Persimmon Creek Estates': '30265',
    'UL-Northgate HS-Stone Mill': '30265',
    'UL-Northgate HS-Riva Ridge at Calumet': '30263',
    'UL-Northgate HS-Windemerer': '30265',
    'UL-Northgate HS-Sawgrass Manor': '30265',
    'UL-Northgate HS-Pebble Brook': '30265',
    'UL-Northgate HS-Timberidge': '30265',
    'UL-Northgate HS-Timberlane': '30265',
    'UL-Northgate HS-White Oak': '30265',
    'UL-Northgate HS-Woodstream': '30265',
    'UL-Northgate HS-Highlands': '30265',
    'UL-Northgate HS-Gosdin Park': '30265',
    'UL-Northgate HS-Summerhill Farms': '30265',
    'UL-Northgate HS-Bailey Forest': '30265',
    'UL-Northgate HS-Creekwood': '30265',
    'UL-Northgate HS-Serenbe Overlook': '30268',
    'UL-Northgate HS-PALMETTO WEST PLANTATION': '30268',
    # East Coweta HS, Senoia/SE area → 30276
    'UL-East Coweta HS-Heritage Pointe': '30276',
    'UL-East Coweta HS-Keg Creek Landing': '30276',
    'UL-East Coweta HS-The Enclave @ Keg Creek': '30276',
    'UL-East Coweta HS-Grafton': '30276',
    'UL-East Coweta HS-Graceton Farms': '30276',
    'UL-East Coweta HS-Fox Hall': '30276',
    'UL-East Coweta HS-Traditions of Senoia': '30276',
    'UL-East Coweta HS-Walden Pond Estates': '30276',
    'UL-East Coweta HS-Standing Rock Estates': '30276',
    'UL-East Coweta HS-Morningside': '30276',
    'UL-East Coweta HS-Elders Mills Estates': '30276',
    'UL-East Coweta HS-Apache Point': '30276',
    'UL-East Coweta HS-HARALSON FARMS': '30276',
    'UL-East Coweta HS-Couchs Corner': '30276',
    'UL-East Coweta HS-Grove Park': '30276',
    'UL-East Coweta HS-Waldens Plantation': '30276',
    'UL-East Coweta HS-Saddleridge Estates': '30276',
    'UL-East Coweta HS-Big T': '30276',
    'UL-East Coweta HS-Barnsley Farms': '30276',
    'UL-East Coweta HS-Old Mill Reserve': '30276',
    'UL-East Coweta HS-Old Mill Crossing': '30276',
    'UL-East Coweta HS-Peeks Crossing': '30276',
    'UL-East Coweta HS-McIntosh Estates': '30276',
    'UL-East Coweta HS-Black Jack': '30276',
    'UL-East Coweta HS-The Overlook At Summer Grove': '30265',
    # East Coweta HS, Summergrove/Newnan area → 30265
    'UL-East Coweta HS-Tapestry at Summergrove': '30265',
    'UL-East Coweta HS-Bellaire at Summer Grove': '30265',
    'UL-East Coweta HS-Stone Bridge': '30265',
    'UL-East Coweta HS-Ashton Place': '30265',
    'UL-East Coweta HS-Golfview at Summer Grove': '30265',
    'UL-East Coweta HS- TWNHSE Stonebridge Newnan': '30265',
    'UL-East Coweta HS-Stonebridge Newnan': '30265',
    'UL-East Coweta HS-Woodbury Estates': '30265',
    'UL-East Coweta HS-Daybreak': '30265',
    'UL-East Coweta HS-Keystone at Summer Grove': '30265',
    'UL-East Coweta HS-Hillcrest': '30265',
    'UL-East Coweta HS-Carriage Park': '30265',
    'UL-East Coweta HS-Cascades at Summer Grove': '30265',
    'UL-East Coweta HS-Cascade at Summer Grove': '30265',
    'UL-East Coweta HS-Oakpark at Summergrove': '30265',
    'UL-East Coweta HS-Loras Place at Summergrove': '30265',
    'UL-East Coweta HS-The Arbors at Summergrove': '30265',
    'UL-East Coweta HS-Wicker Place': '30265',
    'UL-East Coweta HS-Eastlake at Summergrove': '30265',
    'UL-East Coweta HS-Beacon crest at Summergrove': '30265',
    'UL-East Coweta HS-Southwind at Stillwood Farms': '30265',
    'UL-East Coweta HS-Heritage Ridge at Summergrove': '30265',
    'UL-East Coweta HS-The Dale at Summergrove': '30265',
    'UL-East Coweta HS-Belltree at Summergrove': '30265',
    'UL-East Coweta HS-Camden Village at Still Farms': '30265',
    'UL-East Coweta HS-Townhomes at Eastlake': '30265',
    'UL-East Coweta HS-Lakeshore': '30265',
    'UL-East Coweta HS-Nickel Creek at Newnan Crossing': '30265',
    'UL-East Coweta HS-Highlands at Madison Park': '30265',
    'UL-East Coweta HS-Madison Park at Newnan Lakes': '30265',
    'UL-East Coweta HS-Leesburg Plantation': '30265',
    'UL-East Coweta HS-Twelve Parks': '30265',
    'UL-East Coweta HS-Twelve Parks  55+': '30265',
    'UL-East Coweta HS-Springdale': '30265',
    'UL-East Coweta HS-Cresswind': '30265',
    'UL-East Coweta HS-Highgate': '30265',
    'UL-East Coweta HS-The Retreat at Browns Ridge': '30265',
    'UL-East Coweta HS-Leverett Park': '30265',
    'UL-East Coweta HS-Chapman Farm': '30265',
    # East Coweta HS, Newnan/Poplar area → 30263
    'UL-East Coweta HS-Poplar Preserve': '30263',
    'UL-East Coweta HS-Candleberry Place': '30263',
    'UL-East Coweta HS-Parkside Village': '30263',
    'UL-East Coweta HS-The Cottages at Lake Shore': '30263',
    'UL-East Coweta HS-Hutchinson Cove': '30263',
    'UL-East Coweta HS-Abbott Walk': '30263',
    'UL-East Coweta HS-Bedford Forest': '30263',
    'UL-East Coweta HS-Winchester': '30263',
    'UL-East Coweta HS-Huntington Chase': '30263',
    'UL-East Coweta HS-Sandstone': '30263',
    'UL-East Coweta HS-Willow Bend': '30263',
    'UL-East Coweta HS-City View': '30263',
    'UL-East Coweta HS-Olympia Park': '30263',
    'UL-East Coweta HS-MLK/Pinson': '30263',
    'UL-East Coweta HS-East Newnan Village': '30263',
    'UL-East Coweta HS-Chestlehurst Acres': '30276',
    'UL-East Coweta HS-Stone Mill at Summer Grove': '30265',
    'UL-East Coweta HS-Turnberry Park': '30276',
    'UL-East Coweta HS-Knoll Park at Summer Grove': '30265',
    'UL-East Coweta HS-Rock House Ridge': '30276',
    'UL-East Coweta HS-WOODVALLEY ESTATES': '30276',
    'UL-East Coweta HS-Saddlebrook': '30276',
    'UL-East Coweta HS-Ashton at Summergrove': '30265',
    # Newnan HS area → mostly 30263
    'UL-Newnan HS-Chapel Hill': '30265',
    'UL-Newnan HS-Belle Hall': '30265',
    'UL-Newnan HS-Piney Woods': '30263',
    'UL-Newnan HS-Avery park': '30263',
    'UL-Newnan HS-Lake Redwine Plantation': '30263',
    'UL-Newnan HS-Maple Creek Plantation': '30263',
    'UL-Newnan HS-Savannah Woods': '30263',
    'UL-Newnan HS-The Crest': '30263',
    'UL-Newnan HS-Farrington Ridge': '30263',
    'UL-Newnan HS-Hickory Hills': '30263',
    'UL-Newnan HS-Sargent Village': '30263',
    'UL-Newnan HS-Beverly Park': '30263',
    'UL-Newnan HS-Corn Crib': '30263',
    'UL-Newnan HS-Lake Coweta': '30263',
    'UL-Newnan HS-Irish Trace': '30263',
    'UL-Newnan HS-Woodsmoke': '30263',
    'UL-Newnan HS-Windsor Estates': '30263',
    'UL-Newnan HS-Alatus Acres': '30263',
    'UL-Newnan HS-Pinecrest': '30263',
    'UL-Newnan HS-Harpers Farms': '30263',
    'UL-Newnan HS-Newnan Pines': '30263',
    'UL-Newnan HS-WILLOW CREEK': '30263',
    'UL-Newnan HS-Otara Woods': '30263',
    'UL-Newnan HS-Rosewood': '30263',
    'UL-Newnan HS-Cross Brook Estates': '30263',
    'UL-Newnan HS-Browns Place': '30263',
    'UL-Newnan HS-Pineland Plantation': '30263',
    'UL-Newnan HS-High gardens at Lake Redwine': '30263',
    'UL-Newnan HS-Lake Redwine': '30263',
    'UL-Newnan HS-The Woods Lake Redwine': '30263',
    'UL-Newnan HS-Macedonia Woods': '30263',
    'UL-Newnan HS-Hubbard Place': '30263',
    'UL-Newnan HS-Westgate Park': '30263',
    'UL-Newnan HS-Bohannon Woods': '30263',
    'UL-Newnan HS-Charlesburg': '30263',
    'UL-Newnan HS-Rock Cabin Lake': '30263',
    'UL-Newnan HS-SADDLEBACK FARMS': '30263',
    'UL-Newnan HS-Newnan City': '30263',
    'UL-Newnan HS-Newnan Waverly': '30263',
    'UL-Newnan HS-Newnan/Featherstone': '30263',
    'UL-Newnan HS-Rocky Hill': '30263',
    'UL-Newnan HS-Pine Grove Estates': '30263',
    'UL-Newnan HS-Woodrow Place': '30263',
    'UL-Newnan HS-Calico Corners': '30220',
    'UL-Newnan HS-Canterbury Springs': '30220',
    'UL-Newnan HS-Bears Bend': '30263',
    'UL-Newnan HS-Lamb Road': '30263',
    'UL-Newnan HS-Allen Place': '30263',
    'UL-Newnan HS-BELLE LAKE PLANTATION': '30263',
    'UL-Newnan HS-Country Club Rd': '30263',
    'UL-Newnan HS-Halt Whistle': '30263',
    'UL-Newnan HS-Meadowview': '30263',
    'UL-Newnan HS-Rustica Estates': '30263',
    'UL-Newnan HS-Welcome Woods': '30263',
    'UL-Newnan HS-Woodland Acres': '30263',
    'UL-Newnan HS-Grantville City': '30220',
    'UL-Newnan HS-Moreland City': '30259',
    'UL-Newnan HS-QUIGS FARM': '30263',
    # Senoia city
    'UL-East Coweta HS-Senoia (Historic)': '30276',
    'UL-East Coweta HS-Senoia Gin Property': '30276',
    'UL-East Coweta HS-Todd Seven': '30276',
    # Sharpsburg area
    'UL-Northgate HS-Peachtree Farms': '30277',
    'UL-Northgate HS-Tyler Woods': '30277',
    'UL-East Coweta HS-Clearwater Lake': '30277',
    'UL-East Coweta HS-Melrose Park': '30277',
    'UL-East Coweta HS-Winchester': '30277',
    # Area defaults by school district
    'RL-East Coweta HS-Georgian Pines': '30276',
    'RL-Newnan HS-Bears Bend': '30263',
}

def _zip_from_neighborhood(neighborhood):
    """Look up zip from our subdivision map, falling back to school-district defaults."""
    if not neighborhood:
        return None
    # Exact match
    if neighborhood in COWETA_SUBDIVISION_ZIPS:
        return COWETA_SUBDIVISION_ZIPS[neighborhood]
    # School district fallback
    n = neighborhood.upper()
    if 'NORTHGATE' in n:
        return '30265'
    if 'NEWNAN HS' in n:
        return '30263'
    if 'EAST COWETA' in n:
        return '30265'   # conservative default
    if 'GRANTVILLE' in n:
        return '30220'
    if 'SENOIA' in n:
        return '30276'
    return None


@admin_bp.route('/new-movers/enrich-zips', methods=['POST'])
@login_required
@admin_required
def new_movers_enrich_zips():
    """Process one batch of 40 records — client calls repeatedly until remaining=0."""
    import time
    from app.utils.db_helpers import get_records, update_record
    import requests as req_lib

    # Fetch records missing zip (with neighborhood for map lookup)
    missing = get_records('new_movers',
                          filter_formula="Zip=''",
                          fields=['Address', 'County', 'State', 'City', 'Neighborhood'],
                          max_records=100)

    if not missing:
        return jsonify({'done': True, 'message': 'All records have ZIP codes!', 'updated': 0, 'remaining': 0})

    batch   = missing[:25]
    session = req_lib.Session()
    session.headers.update({'User-Agent': 'PinpointDirect/1.0'})

    updated = 0
    failed  = 0

    for r in batch:
        f            = r['fields']
        address      = f.get('Address', '').strip()
        county       = f.get('County', 'Coweta County GA')
        state        = f.get('State', 'GA')
        neighborhood = f.get('Neighborhood', '').strip()

        if not address:
            failed += 1
            continue

        zip_code = None
        city     = f.get('City', 'Newnan')

        # 1) Try neighborhood→zip map first (instant, no network)
        zip_code = _zip_from_neighborhood(neighborhood)

        # 2) Fall back to Census geocoder for established streets
        if not zip_code:
            for try_city in COUNTY_CITIES.get(county, ['Newnan'])[:2]:
                try:
                    resp = session.get(
                        'https://geocoding.geo.census.gov/geocoder/locations/onelineaddress',
                        params={'address': f"{address}, {try_city}, {state}",
                                'benchmark': 'Public_AR_Current', 'format': 'json'},
                        timeout=5
                    )
                    matches = resp.json().get('result', {}).get('addressMatches', [])
                    if matches:
                        comps    = matches[0].get('addressComponents', {})
                        zip_code = comps.get('zip', '')
                        city     = comps.get('city', try_city).title()
                        if zip_code:
                            break
                except Exception:
                    pass

        # 3) Fall back to Google Address Validation API (handles new construction)
        if not zip_code:
            try:
                import json as _json
                goog_key = None
                try:
                    import json as _j, os as _os
                    cfg_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), 'config', 'google_address_validation.json')
                    goog_key = _j.load(open(cfg_path)).get('api_key') if _os.path.exists(cfg_path) else _os.getenv('GOOGLE_ADDRESS_VALIDATION_KEY')
                except Exception:
                    goog_key = os.getenv('GOOGLE_ADDRESS_VALIDATION_KEY')

                if goog_key:
                    try_city = COUNTY_CITIES.get(county, ['Newnan'])[0]
                    payload = {
                        'address': {
                            'addressLines': [address],
                            'locality': try_city,
                            'administrativeArea': state,
                        }
                    }
                    gresp = session.post(
                        f'https://addressvalidation.googleapis.com/v1:validateAddress?key={goog_key}',
                        json=payload,
                        timeout=6
                    )
                    gdata = gresp.json()
                    postal = gdata.get('result', {}).get('address', {}).get('postalAddress', {})
                    zip_code = postal.get('postalCode', '').split('-')[0]  # strip +4
                    city     = postal.get('locality', city) or city
            except Exception:
                pass

        if zip_code:
            update_record('new_movers', r['id'], {'Zip': zip_code, 'City': city})
            updated += 1
        else:
            failed += 1

    remaining = max(0, len(missing) - len(batch))
    done      = remaining == 0

    return jsonify({
        'done':      done,
        'updated':   updated,
        'failed':    failed,
        'remaining': remaining,
        'message':   'All done! ZIPs enriched.' if done else f'{remaining} records still need ZIPs — continuing...'
    })


@admin_bp.route('/new-movers/verify', methods=['POST'])
@login_required
@admin_required
def new_movers_verify():
    """Process one batch of 50 unverified records — client calls repeatedly until done=True."""
    from app.utils.usps import verify_address
    from app.utils.database import get_db, get_db_type

    BATCH_SIZE = 50
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'

    with get_db() as db:
        # Fetch unverified records
        sql = f"""
            SELECT id, address, city, state, zip
            FROM new_movers
            WHERE (verify_status IS NULL OR verify_status = 'pending')
            LIMIT {BATCH_SIZE}
        """
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(sql)
                rows = [dict(r) for r in cur.fetchall()]
        else:
            rows = [dict(r) for r in db.execute(sql).fetchall()]

        if not rows:
            # Count remaining just in case
            count_sql = "SELECT COUNT(*) as cnt FROM new_movers WHERE (verify_status IS NULL OR verify_status = 'pending')"
            if db_type == 'postgres':
                with db.cursor() as cur:
                    cur.execute(count_sql)
                    cnt = cur.fetchone()['cnt']
            else:
                cnt = db.execute(count_sql).fetchone()[0]
            return jsonify({'done': True, 'updated': 0, 'failed': 0, 'remaining': 0, 'message': 'All addresses verified!'})

        updated = 0
        failed = 0
        for row in rows:
            result = verify_address(
                address1=row.get('address', '') or '',
                city=row.get('city', '') or '',
                state=row.get('state', 'GA') or 'GA',
                zip5=row.get('zip', '') or '',
            )
            status = 'verified' if result.get('success') else 'failed'
            msg    = result.get('message', '')
            update_sql = f"UPDATE new_movers SET verify_status = {ph}, verify_message = {ph} WHERE id = {ph}"
            if db_type == 'postgres':
                with db.cursor() as cur:
                    cur.execute(update_sql, (status, msg, row['id']))
            else:
                db.execute(update_sql, (status, msg, row['id']))
            if result.get('success'):
                updated += 1
            else:
                failed += 1

        db.commit()

        # Count remaining
        count_sql = f"SELECT COUNT(*) as cnt FROM new_movers WHERE (verify_status IS NULL OR verify_status = 'pending')"
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(count_sql)
                remaining = cur.fetchone()['cnt']
        else:
            remaining = db.execute(count_sql).fetchone()[0]

    done = remaining == 0
    return jsonify({
        'done':      done,
        'updated':   updated,
        'failed':    failed,
        'remaining': remaining,
        'message':   'All addresses verified!' if done else f'{remaining} records remaining...',
    })


@admin_bp.route('/new-movers/export')
@login_required
@admin_required
def new_movers_export():
    from app.utils.db_helpers import get_records
    import csv, io
    from flask import Response

    county = request.args.get('county', '')
    tier = request.args.get('tier', '')
    batch = request.args.get('batch', '')

    formula_parts = []
    if county:
        formula_parts.append(f"{{County}}='{county}'")
    if tier:
        formula_parts.append(f"{{Tier}}='{tier}'")
    if batch:
        formula_parts.append(f"{{Upload Batch}}='{batch}'")

    formula = None
    if formula_parts:
        formula = 'AND(' + ','.join(formula_parts) + ')' if len(formula_parts) > 1 else formula_parts[0]

    records = get_records('new_movers', filter_formula=formula)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        'Address', 'City', 'Zip', 'State', 'County', 'Sale Date', 'Sale Price',
        'Tier', 'Year Built', 'Square Ft', 'Neighborhood', 'Upload Batch'
    ])
    writer.writeheader()
    for r in records:
        f = r['fields']
        writer.writerow({col: f.get(col, '') for col in writer.fieldnames})

    parts = [county or 'All', tier or 'All-Tiers']
    filename = f"NewMovers_{'_'.join(p.replace(' ','') for p in parts)}.csv"
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@admin_bp.route('/invoices/<int:record_id>/action', methods=['POST'])
@login_required
@admin_required
def invoice_action(record_id):
    from datetime import date
    action = request.form.get('action')
    fields = {}

    if action == 'send':
        fields['Status'] = 'Sent'
    elif action == 'mark_paid':
        fields['Status'] = 'Paid'
        fields['Paid Date'] = request.form.get('paid_date', date.today().isoformat())
    elif action == 'mark_overdue':
        fields['Status'] = 'Overdue'
    elif action == 'cancel':
        fields['Status'] = 'Cancelled'

    if fields:
        update_record('invoices', record_id, fields)
        flash('Invoice updated.', 'success')
    return redirect(url_for('admin.invoice_detail', record_id=record_id))
