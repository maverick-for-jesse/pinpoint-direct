from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, send_file
from flask_login import login_required, current_user
from app.utils.airtable import get_records, get_record, create_record, update_record
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
            'Status': request.form.get('status', 'Active'),
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


@admin_bp.route('/clients/<record_id>')
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


@admin_bp.route('/clients/<record_id>/edit', methods=['GET', 'POST'])
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
        record = create_record('campaigns', fields)
        flash(f"Campaign '{fields.get('Campaign Name')}' created.", 'success')
        return redirect(url_for('admin.campaign_detail', record_id=record['id']))
    return render_template('admin/campaign_form.html', campaign=None, clients=clients)


@admin_bp.route('/campaigns/<record_id>')
@login_required
@admin_required
def campaign_detail(record_id):
    campaign = get_record('campaigns', record_id)
    campaign_name = campaign['fields'].get('Campaign Name', '')
    artwork = get_records('artwork', filter_formula=f"{{Campaign}}='{campaign_name}'")
    artwork = sorted(artwork, key=lambda x: x['fields'].get('Version', 0), reverse=True)
    print_jobs = get_records('print_jobs', filter_formula=f"{{Campaign}}='{campaign_name}'")
    print_job = print_jobs[0] if print_jobs else None
    return render_template('admin/campaign_detail.html',
                           campaign=campaign,
                           artwork=artwork,
                           print_job=print_job)


@admin_bp.route('/campaigns/<record_id>/edit', methods=['GET', 'POST'])
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


@admin_bp.route('/campaigns/<record_id>/advance', methods=['POST'])
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


@admin_bp.route('/campaigns/<record_id>/cancel', methods=['POST'])
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
    from app.utils.gemini import generate_image as gen_img
    data = request.get_json()
    prompt = data.get('prompt', '').strip()
    if not prompt:
        return jsonify({'error': 'Prompt is required.'}), 400
    try:
        b64 = gen_img(prompt, aspect_ratio=data.get('aspect_ratio', 'LANDSCAPE'))
        return jsonify({'image': b64})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/postcard-builder/save', methods=['POST'])
@login_required
@admin_required
def postcard_save():
    data = request.get_json()
    campaign_name = data.get('campaign_name', '').strip()
    campaign_id = data.get('campaign_id', '').strip()

    # Figure out version number
    existing = get_records('artwork', filter_formula=f"{{Campaign}}='{campaign_name}'")
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
    from app.utils.database import get_db, init_db
    init_db()
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM mailing_lists ORDER BY created_at DESC"
        ).fetchall()
    mailing_lists = [dict(r) for r in rows]
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
        cur = db.execute(
            "INSERT INTO mailing_lists (name, client, campaign, total, notes) VALUES (?,?,?,?,?)",
            (list_name, client, campaign, len(records), notes)
        )
        list_id = cur.lastrowid
        db.executemany(
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
    from app.utils.database import get_db
    page = int(request.args.get('page', 1))
    per_page = 50
    offset = (page - 1) * per_page

    with get_db() as db:
        mailing_list = dict(db.execute("SELECT * FROM mailing_lists WHERE id=?", (list_id,)).fetchone())
        total_records = db.execute("SELECT COUNT(*) FROM list_records WHERE list_id=?", (list_id,)).fetchone()[0]
        records = [dict(r) for r in db.execute(
            "SELECT * FROM list_records WHERE list_id=? LIMIT ? OFFSET ?",
            (list_id, per_page, offset)
        ).fetchall()]
        stats = dict(db.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN verify_status='verified' THEN 1 ELSE 0 END) as verified,
                SUM(CASE WHEN verify_status='failed'   THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN verify_status='pending'  THEN 1 ELSE 0 END) as pending
               FROM list_records WHERE list_id=?""",
            (list_id,)
        ).fetchone())

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
    from app.utils.database import get_db
    from app.utils.usps import verify_address

    with get_db() as db:
        pending = db.execute(
            "SELECT * FROM list_records WHERE list_id=? AND verify_status='pending' LIMIT 500",
            (list_id,)
        ).fetchall()

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
            db.execute(
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
        db.execute(
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
    from app.utils.database import get_db
    campaign_name = request.form.get('campaign_name', '').strip()
    campaign_id   = request.form.get('campaign_id', '').strip()

    with get_db() as db:
        db.execute("UPDATE mailing_lists SET campaign=? WHERE id=?", (campaign_name, list_id))
        db.commit()

    # Also update piece count on campaign
    if campaign_id:
        with get_db() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM list_records WHERE list_id=? AND verify_status != 'failed'",
                (list_id,)
            ).fetchone()[0]
        try:
            update_record('campaigns', campaign_id, {'Piece Count': total})
        except Exception:
            pass

    flash(f"List assigned to {campaign_name}.", 'success')
    return redirect(url_for('admin.list_detail', list_id=list_id))


@admin_bp.route('/lists/<int:list_id>/export')
@login_required
@admin_required
def list_export(list_id):
    from app.utils.database import get_db
    import csv
    import io
    from flask import Response

    only_verified = request.args.get('verified_only', '0') == '1'
    with get_db() as db:
        mailing_list = dict(db.execute("SELECT * FROM mailing_lists WHERE id=?", (list_id,)).fetchone())
        query = "SELECT * FROM list_records WHERE list_id=?"
        params = [list_id]
        if only_verified:
            query += " AND verify_status='verified'"
        records = [dict(r) for r in db.execute(query, params).fetchall()]

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
    from app.utils.database import get_db
    with get_db() as db:
        db.execute("DELETE FROM list_records WHERE list_id=?", (list_id,))
        db.execute("DELETE FROM mailing_lists WHERE id=?", (list_id,))
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


@admin_bp.route('/print-queue/<record_id>')
@login_required
@admin_required
def print_job_detail(record_id):
    from datetime import date
    job = get_record('print_jobs', record_id)
    return render_template('admin/print_job_detail.html', job=job, today=date.today().isoformat())


@admin_bp.route('/print-queue/<record_id>/update', methods=['POST'])
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
            campaigns = get_records('campaigns', filter_formula=f"{{Campaign Name}}='{campaign_name}'")
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


@admin_bp.route('/invoices/<record_id>')
@login_required
@admin_required
def invoice_detail(record_id):
    from datetime import date
    invoice = get_record('invoices', record_id)
    return render_template('admin/invoice_detail.html', invoice=invoice, today=date.today().isoformat())


@admin_bp.route('/invoices/<record_id>/edit', methods=['GET', 'POST'])
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


@admin_bp.route('/invoices/<record_id>/action', methods=['POST'])
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
