from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user
from app.utils.db_helpers import get_records, get_record, create_record, update_record, at_str
import os, base64
from datetime import datetime
from werkzeug.utils import secure_filename

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
    pending_approvals = [c for c in campaigns if c['fields'].get('Status') in ('Artwork Pending', 'List Approval Pending')]
    print_queue = [j for j in print_jobs if j['fields'].get('Status') == 'Queued']
    outstanding = sum(
        float(inv['fields'].get('Amount', 0))
        for inv in invoices
        if inv['fields'].get('Status') in ('Sent', 'Overdue')
    )

    # Design requests needing attention
    design_requests_pending = 0
    try:
        all_drs = get_records('design_requests')
        design_requests_pending = len([
            dr for dr in all_drs
            if dr['fields'].get('Status') in ('Submitted', 'Revision Requested')
        ])
    except Exception:
        design_requests_pending = 0

    # New leads count
    new_leads = 0
    try:
        from app.utils.database import get_db, get_db_type
        db_type = get_db_type()
        ph = '%s' if db_type == 'postgres' else '?'
        with get_db() as db:
            if db_type == 'postgres':
                with db.cursor() as cur:
                    cur.execute("SELECT COUNT(*) as cnt FROM leads WHERE status = 'New' OR status IS NULL")
                    row = cur.fetchone()
                    new_leads = row['cnt'] if row else 0
            else:
                row = db.execute("SELECT COUNT(*) as cnt FROM leads WHERE status = 'New' OR status IS NULL").fetchone()
                new_leads = row['cnt'] if row else 0
    except Exception:
        new_leads = 0

    stats = {
        'active_campaigns': len(active_campaigns),
        'pending_approvals': len(pending_approvals),
        'print_queue': len(print_queue),
        'outstanding_invoices': f'{outstanding:,.2f}',
        'design_requests_pending': design_requests_pending,
        'new_leads': new_leads,
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
        'Artwork Pending': 'List Building',
        'List Building': 'List Approval Pending',
        'List Approval Pending': 'In Production',
        'In Production': 'Mailed',
    }
    next_status = next_map.get(current)
    if next_status:
        update_record('campaigns', record_id, {'Status': next_status})
        flash(f'Campaign moved to "{next_status}".', 'success')

    return redirect(url_for('admin.campaign_detail', record_id=record_id))


@admin_bp.route('/campaigns/<int:record_id>/set-quote', methods=['POST'])
@login_required
@admin_required
def campaign_set_quote(record_id):
    list_count = request.form.get('list_count', '').strip()
    quote_amount = request.form.get('quote_amount', '').strip()
    fields = {}
    if list_count:
        fields['List Count'] = int(list_count)
    if quote_amount:
        fields['Quote Amount'] = float(quote_amount)
    if fields:
        update_record('campaigns', record_id, fields)
    update_record('campaigns', record_id, {'Status': 'List Approval Pending'})
    flash('List details saved. Client can now review the quote.', 'success')
    return redirect(url_for('admin.campaign_detail', record_id=record_id))


@admin_bp.route('/campaigns/<int:record_id>/cancel', methods=['POST'])
@login_required
@admin_required
def campaign_cancel(record_id):
    update_record('campaigns', record_id, {'Status': 'Cancelled'})
    flash('Campaign cancelled.', 'success')
    return redirect(url_for('admin.campaign_detail', record_id=record_id))


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
    from app.utils.database import get_db, get_db_type
    # Get all records (we need full fields for stats)
    try:
        records = get_records('new_movers')
    except Exception:
        records = []

    # Pull verified/failed counts per batch directly from Postgres
    verify_counts = {}  # batch_label -> {'verified': N, 'failed': N}
    try:
        db_type = get_db_type()
        with get_db() as db:
            sql = """
                SELECT upload_batch, verify_status, COUNT(*) as cnt
                FROM new_movers
                WHERE verify_status IN ('verified', 'failed')
                GROUP BY upload_batch, verify_status
            """
            if db_type == 'postgres':
                with db.cursor() as cur:
                    cur.execute(sql)
                    rows = cur.fetchall()
            else:
                rows = db.execute(sql).fetchall()
            for row in rows:
                batch = row['upload_batch'] or 'Unknown'
                vs = row['verify_status']
                cnt = row['cnt']
                if batch not in verify_counts:
                    verify_counts[batch] = {'verified': 0, 'failed': 0}
                if vs == 'verified':
                    verify_counts[batch]['verified'] += cnt
                elif vs == 'failed':
                    verify_counts[batch]['failed'] += cnt
    except Exception:
        pass  # If Postgres query fails, verified/failed will show 0

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
        # Track earliest (oldest) sale_date for golden window badge
        sd = f.get('Sale Date', '')
        if sd:
            prev = batches[batch]['earliest_sale_date']
            if prev is None or sd < prev:
                batches[batch]['earliest_sale_date'] = sd

    # Merge in verified/failed counts from Postgres
    for batch, vc in verify_counts.items():
        if batch in batches:
            batches[batch]['verified'] = vc['verified']
            batches[batch]['failed'] = vc['failed']

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
    try:
        return _new_movers_upload_inner()
    except Exception as e:
        import traceback
        return jsonify({'success': False, 'error': f'Server error: {str(e)}', 'detail': traceback.format_exc()})

def _new_movers_upload_inner():
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
    # Use direct SQL for performance — get_records loads all fields which is slow at scale
    from app.utils.db_helpers import create_records_batch
    from app.utils.database import get_db, get_db_type
    existing_keys = set()
    try:
        db_type = get_db_type()
        with get_db() as db:
            sql = "SELECT UPPER(address) as addr, sale_date FROM new_movers"
            if db_type == 'postgres':
                with db.cursor() as cur:
                    cur.execute(sql)
                    for row in cur.fetchall():
                        existing_keys.add((row['addr'] or '', row['sale_date'] or ''))
            else:
                for row in db.execute(sql).fetchall():
                    existing_keys.add((row[0] or '', row[1] or ''))
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

        # 3) Fall back to SerpAPI Google Maps (handles new construction)
        if not zip_code:
            try:
                import re as _re, json as _j, os as _os
                # Load SerpAPI key
                serp_key = None
                try:
                    cfg = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), 'config', 'agency_scraper.json')
                    serp_key = _j.load(open(cfg)).get('serpapi_key') if _os.path.exists(cfg) else None
                except Exception:
                    pass
                serp_key = serp_key or _os.getenv('SERPAPI_KEY')

                # County center coordinates for accurate local search
                COUNTY_LL = {
                    'Coweta County GA':  '@33.3812,-84.7600,12z',
                    'Fayette County GA': '@33.4300,-84.5000,12z',
                }
                ll = COUNTY_LL.get(county, '@33.3812,-84.7600,12z')
                try_city = COUNTY_CITIES.get(county, ['Newnan'])[0]

                if serp_key:
                    sresp = session.get(
                        'https://serpapi.com/search.json',
                        params={
                            'engine':  'google_maps',
                            'q':       f'{address}, {try_city}, {state}',
                            'll':      ll,
                            'type':    'search',
                            'api_key': serp_key,
                        },
                        timeout=8
                    )
                    sdata = sresp.json()
                    addr_str = sdata.get('place_results', {}).get('address', '')
                    if not addr_str:
                        results = sdata.get('local_results', [])
                        addr_str = results[0].get('address', '') if results else ''
                    if addr_str:
                        zm = _re.search(r'\b(\d{5})\b', addr_str)
                        if zm:
                            zip_code = zm.group(1)
                            # Extract city from address string (before ", STATE ZIP")
                            parts = addr_str.split(',')
                            if len(parts) >= 2:
                                city = parts[-2].strip().split(' ')[0] or city
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

    # Ensure verify columns exist (safe to run every time)
    with get_db() as db:
        try:
            if db_type == 'postgres':
                with db.cursor() as cur:
                    cur.execute("ALTER TABLE new_movers ADD COLUMN IF NOT EXISTS verify_status TEXT")
                    cur.execute("ALTER TABLE new_movers ADD COLUMN IF NOT EXISTS verify_message TEXT")
            else:
                for col in ['verify_status', 'verify_message']:
                    try:
                        db.execute(f"ALTER TABLE new_movers ADD COLUMN {col} TEXT")
                    except Exception:
                        pass
            db.commit()
        except Exception:
            pass

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


# ── Leads ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/leads')
@login_required
@admin_required
def leads():
    from app.utils.database import get_db, get_db_type, init_db
    init_db()
    db_type = get_db_type()
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute("""
                    SELECT id, name, email, business_name, phone, message, status, approved_at, created_at
                    FROM leads
                    ORDER BY created_at DESC
                """)
                all_leads = [dict(r) for r in cur.fetchall()]
        else:
            rows = db.execute("""
                SELECT id, name, email, business_name, phone, message, status, approved_at, created_at
                FROM leads
                ORDER BY created_at DESC
            """).fetchall()
            all_leads = [dict(r) for r in rows]
    new_leads_count = sum(1 for l in all_leads if not l.get('status') or l.get('status') == 'New')
    return render_template('admin/leads.html', leads=all_leads, new_leads_count=new_leads_count)


@admin_bp.route('/leads/<int:lead_id>/approve', methods=['POST'])
@login_required
@admin_required
def lead_approve(lead_id):
    import random, json, requests as req_lib
    from app.utils.database import get_db, get_db_type
    from werkzeug.security import generate_password_hash
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'

    # 1. Get lead
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"SELECT * FROM leads WHERE id = {ph}", (lead_id,))
                lead = dict(cur.fetchone())
        else:
            row = db.execute(f"SELECT * FROM leads WHERE id = {ph}", (lead_id,)).fetchone()
            lead = dict(row)

    lead_name = lead.get('name', '')
    lead_email = lead.get('email', '')
    lead_phone = lead.get('phone', '')
    lead_business = lead.get('business_name', '') or lead_name

    # 2. Generate temp password
    temp_password = f"Pinpoint{random.randint(1000, 9999)}"
    password_hash = generate_password_hash(temp_password)

    with get_db() as db:
        # 3. Create client record
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO clients (company_name, contact_name, contact_email, contact_phone, status)
                    VALUES ({ph},{ph},{ph},{ph},{ph}) RETURNING id
                """, (lead_business, lead_name, lead_email, lead_phone, 'Active'))
                client_id = cur.fetchone()['id']
        else:
            cur = db.execute(f"""
                INSERT INTO clients (company_name, contact_name, contact_email, contact_phone, status)
                VALUES ({ph},{ph},{ph},{ph},{ph})
            """, (lead_business, lead_name, lead_email, lead_phone, 'Active'))
            client_id = cur.lastrowid

        # 4. Create user record
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO users (name, email, password_hash, role, client_id)
                    VALUES ({ph},{ph},{ph},{ph},{ph}) RETURNING id
                """, (lead_name, lead_email, password_hash, 'Client', client_id))
        else:
            db.execute(f"""
                INSERT INTO users (name, email, password_hash, role, client_id)
                VALUES ({ph},{ph},{ph},{ph},{ph})
            """, (lead_name, lead_email, password_hash, 'Client', client_id))

        # 5. Update lead status
        from datetime import datetime
        now = datetime.utcnow()
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"UPDATE leads SET status='Approved', approved_at={ph} WHERE id={ph}", (now, lead_id))
        else:
            db.execute(f"UPDATE leads SET status='Approved', approved_at={ph} WHERE id={ph}", (now.isoformat(), lead_id))

        db.commit()

    # 6. Send welcome email via AgentMail
    try:
        import os
        api_key = os.getenv('AGENTMAIL_API_KEY')
        if not api_key:
            # fallback for local dev
            try:
                with open('/Users/maverick/.openclaw/workspace/config/agentmail.json') as f:
                    cfg = json.load(f)
                api_key = cfg['api_key']
            except Exception:
                pass
        if not api_key:
            raise ValueError("No AgentMail API key found")
        inbox_id = 'maverickforjesse@agentmail.to'
        req_lib.post(
            f'https://api.agentmail.to/v0/inboxes/{inbox_id}/messages',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'to': [lead_email],
                'subject': 'Welcome to Pinpoint Direct — Your Portal Access',
                'text': f"""Hi {lead_name},

Welcome to Pinpoint Direct! Your client portal account has been created.

Login at: https://pinpoint-direct-production.up.railway.app/login

Email: {lead_email}
Temporary Password: {temp_password}

Please log in and change your password at your earliest convenience.

If you have any questions, reply to this email or call us.

— The Pinpoint Direct Team
pinpointdirect.io"""
            },
            timeout=10
        )
        email_status = 'sent'
    except Exception as e:
        email_status = f'failed ({e})'

    flash(
        f"✅ Lead approved! Client account created for {lead_name}. "
        f"Temp password: <strong>{temp_password}</strong>. "
        f"Welcome email: {email_status}.",
        'success'
    )
    return redirect(url_for('admin.leads'))


@admin_bp.route('/leads/<int:lead_id>/delete', methods=['POST'])
@login_required
@admin_required
def lead_delete(lead_id):
    from app.utils.database import get_db, get_db_type
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"DELETE FROM leads WHERE id = {ph}", (lead_id,))
        else:
            db.execute(f"DELETE FROM leads WHERE id = {ph}", (lead_id,))
        db.commit()
    flash('Lead deleted.', 'success')
    return redirect(url_for('admin.leads'))


# ── Drip Campaigns ────────────────────────────────────────────────────────────

@admin_bp.route('/drip-campaigns')
@login_required
@admin_required
def drip_campaigns():
    from app.utils.database import get_db, get_db_type, init_db
    init_db()
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute("""
                    SELECT dc.*,
                           c.company_name AS client_name,
                           (SELECT COUNT(DISTINCT dm.mover_id)
                            FROM drip_mailings dm
                            WHERE dm.campaign_id = dc.id
                            GROUP BY dm.campaign_id
                            HAVING COUNT(dm.id) < dc.max_months
                           ) AS active_movers_raw,
                           (SELECT MAX(dm.mailed_at) FROM drip_mailings dm WHERE dm.campaign_id = dc.id) AS last_run
                    FROM drip_campaigns dc
                    LEFT JOIN clients c ON c.id = dc.client_id
                    ORDER BY dc.created_at DESC
                """)
                campaigns_raw = [dict(r) for r in cur.fetchall()]
                # active_movers_raw subquery workaround — simpler count approach
                for camp in campaigns_raw:
                    cur.execute("""
                        SELECT COUNT(DISTINCT mover_id) as cnt
                        FROM drip_mailings
                        WHERE campaign_id = %s
                        GROUP BY mover_id
                        HAVING COUNT(id) < (SELECT max_months FROM drip_campaigns WHERE id = %s)
                    """, (camp['id'], camp['id']))
                    rows = cur.fetchall()
                    camp['active_movers'] = len(rows)
        else:
            rows = db.execute("""
                SELECT dc.*, c.company_name AS client_name,
                       (SELECT MAX(dm.mailed_at) FROM drip_mailings dm WHERE dm.campaign_id = dc.id) AS last_run
                FROM drip_campaigns dc
                LEFT JOIN clients c ON c.id = dc.client_id
                ORDER BY dc.created_at DESC
            """).fetchall()
            campaigns_raw = [dict(r) for r in rows]
            for camp in campaigns_raw:
                sub = db.execute("""
                    SELECT COUNT(*) as cnt FROM (
                        SELECT mover_id FROM drip_mailings
                        WHERE campaign_id = ?
                        GROUP BY mover_id
                        HAVING COUNT(id) < ?
                    )
                """, (camp['id'], camp['max_months'])).fetchone()
                camp['active_movers'] = sub['cnt'] if sub else 0
    return render_template('admin/drip_campaigns.html', campaigns=campaigns_raw)


@admin_bp.route('/drip-campaigns/new', methods=['GET', 'POST'])
@login_required
@admin_required
def drip_campaign_new():
    from app.utils.database import get_db, get_db_type, init_db
    init_db()
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'

    if request.method == 'POST':
        name         = request.form.get('name', '').strip()
        client_id    = request.form.get('client_id', '').strip() or None
        max_months   = int(request.form.get('max_months', 7) or 7)
        monthly_cap  = request.form.get('monthly_cap', '').strip() or None
        tier_filter  = request.form.get('tier_filter', '').strip() or None
        verified_only = 1 if request.form.get('verified_only') else 0
        subdivisions_list = request.form.getlist('subdivisions')
        subdivisions = None
        if subdivisions_list:
            import json
            subdivisions = json.dumps(subdivisions_list)

        if monthly_cap:
            monthly_cap = int(monthly_cap)
        if client_id:
            client_id = int(client_id)

        with get_db() as db:
            if db_type == 'postgres':
                with db.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO drip_campaigns (client_id, name, max_months, monthly_cap, tier_filter, verified_only, subdivisions)
                        VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph}) RETURNING id
                    """, (client_id, name, max_months, monthly_cap, tier_filter, verified_only, subdivisions))
                    new_id = cur.fetchone()['id']
            else:
                cur = db.execute(f"""
                    INSERT INTO drip_campaigns (client_id, name, max_months, monthly_cap, tier_filter, verified_only, subdivisions)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})
                """, (client_id, name, max_months, monthly_cap, tier_filter, verified_only, subdivisions))
                new_id = cur.lastrowid
            db.commit()
        flash(f"Drip campaign '{name}' created.", 'success')
        return redirect(url_for('admin.drip_campaign_detail', campaign_id=new_id))

    # GET — load clients and subdivisions
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute("SELECT id, company_name FROM clients ORDER BY company_name")
                clients = [dict(r) for r in cur.fetchall()]
                cur.execute("SELECT DISTINCT neighborhood FROM new_movers WHERE neighborhood IS NOT NULL AND neighborhood != '' ORDER BY neighborhood")
                neighborhoods = [r['neighborhood'] for r in cur.fetchall()]
        else:
            clients = [dict(r) for r in db.execute("SELECT id, company_name FROM clients ORDER BY company_name").fetchall()]
            neighborhoods = [r[0] for r in db.execute("SELECT DISTINCT neighborhood FROM new_movers WHERE neighborhood IS NOT NULL AND neighborhood != '' ORDER BY neighborhood").fetchall()]

    return render_template('admin/drip_campaign_form.html', clients=clients, neighborhoods=neighborhoods)


@admin_bp.route('/drip-campaigns/<int:campaign_id>')
@login_required
@admin_required
def drip_campaign_detail(campaign_id):
    from app.utils.database import get_db, get_db_type, init_db
    import json
    init_db()
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'

    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"""
                    SELECT dc.*, c.company_name AS client_name
                    FROM drip_campaigns dc
                    LEFT JOIN clients c ON c.id = dc.client_id
                    WHERE dc.id = {ph}
                """, (campaign_id,))
                campaign = dict(cur.fetchone())

                # Stats
                cur.execute(f"""
                    SELECT COUNT(DISTINCT mover_id) as total_in_pool
                    FROM drip_mailings WHERE campaign_id = {ph}
                """, (campaign_id,))
                total_in_pool = cur.fetchone()['total_in_pool']

                cur.execute(f"""
                    SELECT COUNT(*) as mailed_this_month
                    FROM drip_mailings
                    WHERE campaign_id = {ph}
                    AND DATE_TRUNC('month', mailed_at) = DATE_TRUNC('month', NOW())
                """, (campaign_id,))
                mailed_this_month = cur.fetchone()['mailed_this_month']

                cur.execute(f"""
                    SELECT COUNT(DISTINCT mover_id) as aged_out
                    FROM drip_mailings WHERE campaign_id = {ph}
                    GROUP BY mover_id
                    HAVING COUNT(id) >= {ph}
                """, (campaign_id, campaign['max_months']))
                aged_out = len(cur.fetchall())

                # Mover pool with month numbers
                cur.execute(f"""
                    SELECT nm.address, nm.city, nm.zip, nm.tier, nm.sale_price,
                           nm.sale_date, nm.neighborhood, nm.id as mover_id,
                           COUNT(dm.id) as month_number
                    FROM drip_mailings dm
                    JOIN new_movers nm ON nm.id = dm.mover_id
                    WHERE dm.campaign_id = {ph}
                    GROUP BY nm.id, nm.address, nm.city, nm.zip, nm.tier, nm.sale_price, nm.sale_date, nm.neighborhood
                    HAVING COUNT(dm.id) < {ph}
                    ORDER BY COUNT(dm.id) ASC, nm.sale_date ASC
                """, (campaign_id, campaign['max_months']))
                movers = [dict(r) for r in cur.fetchall()]
        else:
            row = db.execute(f"""
                SELECT dc.*, c.company_name AS client_name
                FROM drip_campaigns dc
                LEFT JOIN clients c ON c.id = dc.client_id
                WHERE dc.id = {ph}
            """, (campaign_id,)).fetchone()
            campaign = dict(row)

            total_in_pool = db.execute(f"SELECT COUNT(DISTINCT mover_id) FROM drip_mailings WHERE campaign_id = {ph}", (campaign_id,)).fetchone()[0]
            mailed_this_month = db.execute(f"""
                SELECT COUNT(*) FROM drip_mailings
                WHERE campaign_id = {ph} AND strftime('%Y-%m', mailed_at) = strftime('%Y-%m', 'now')
            """, (campaign_id,)).fetchone()[0]
            aged_rows = db.execute(f"""
                SELECT mover_id FROM drip_mailings WHERE campaign_id = {ph}
                GROUP BY mover_id HAVING COUNT(id) >= {ph}
            """, (campaign_id, campaign['max_months'])).fetchall()
            aged_out = len(aged_rows)

            movers = [dict(r) for r in db.execute(f"""
                SELECT nm.address, nm.city, nm.zip, nm.tier, nm.sale_price,
                       nm.sale_date, nm.neighborhood, nm.id as mover_id,
                       COUNT(dm.id) as month_number
                FROM drip_mailings dm
                JOIN new_movers nm ON nm.id = dm.mover_id
                WHERE dm.campaign_id = {ph}
                GROUP BY nm.id
                HAVING COUNT(dm.id) < {ph}
                ORDER BY COUNT(dm.id) ASC, nm.sale_date ASC
            """, (campaign_id, campaign['max_months'])).fetchall()]

    stats = {
        'total_in_pool': total_in_pool,
        'mailed_this_month': mailed_this_month,
        'aged_out': aged_out,
    }

    # Decode subdivisions for display
    subdivisions_display = ''
    if campaign.get('subdivisions'):
        try:
            subdivisions_display = ', '.join(json.loads(campaign['subdivisions']))
        except Exception:
            subdivisions_display = campaign['subdivisions']

    return render_template('admin/drip_campaign_detail.html',
                           campaign=campaign,
                           stats=stats,
                           movers=movers,
                           subdivisions_display=subdivisions_display)


@admin_bp.route('/drip-campaigns/<int:campaign_id>/generate', methods=['POST'])
@login_required
@admin_required
def drip_campaign_generate(campaign_id):
    from app.utils.database import get_db, get_db_type, init_db
    import json, csv, io, os
    from datetime import datetime
    init_db()
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'

    with get_db() as db:
        # Load campaign
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"SELECT * FROM drip_campaigns WHERE id = {ph}", (campaign_id,))
                campaign = dict(cur.fetchone())
        else:
            campaign = dict(db.execute(f"SELECT * FROM drip_campaigns WHERE id = {ph}", (campaign_id,)).fetchone())

        max_months  = campaign['max_months']
        monthly_cap = campaign['monthly_cap']
        tier_filter = campaign.get('tier_filter')
        verified_only = campaign.get('verified_only') or False
        subdivisions_raw = campaign.get('subdivisions')
        subdivisions = None
        if subdivisions_raw:
            try:
                subdivisions = json.loads(subdivisions_raw)
            except Exception:
                subdivisions = None

        # Build filter query for qualifying movers
        conditions = []
        params = []
        if tier_filter:
            if tier_filter == 'Premium + Ultra-Premium':
                conditions.append(f"nm.tier IN ({ph},{ph})")
                params.extend(['Premium', 'Ultra-Premium'])
            else:
                conditions.append(f"nm.tier = {ph}")
                params.append(tier_filter)
        if verified_only:
            conditions.append("nm.verify_status = 'verified'")
        if subdivisions:
            placeholders = ','.join([ph] * len(subdivisions))
            conditions.append(f"nm.neighborhood IN ({placeholders})")
            params.extend(subdivisions)

        where_clause = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''

        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"""
                    SELECT nm.id, nm.address, nm.city, nm.state, nm.zip,
                           nm.tier, nm.sale_price, nm.sale_date, nm.neighborhood,
                           COALESCE(mail_counts.cnt, 0) AS times_mailed
                    FROM new_movers nm
                    LEFT JOIN (
                        SELECT mover_id, COUNT(*) as cnt
                        FROM drip_mailings WHERE campaign_id = {ph}
                        GROUP BY mover_id
                    ) mail_counts ON mail_counts.mover_id = nm.id
                    {where_clause}
                    ORDER BY nm.sale_date ASC
                """, [campaign_id] + params)
                all_movers = [dict(r) for r in cur.fetchall()]
        else:
            all_movers = [dict(r) for r in db.execute(f"""
                SELECT nm.id, nm.address, nm.city, nm.state, nm.zip,
                       nm.tier, nm.sale_price, nm.sale_date, nm.neighborhood,
                       COALESCE(mail_counts.cnt, 0) AS times_mailed
                FROM new_movers nm
                LEFT JOIN (
                    SELECT mover_id, COUNT(*) as cnt
                    FROM drip_mailings WHERE campaign_id = {ph}
                    GROUP BY mover_id
                ) mail_counts ON mail_counts.mover_id = nm.id
                {where_clause}
                ORDER BY nm.sale_date ASC
            """, [campaign_id] + params).fetchall()]

        # Separate eligible vs aged out (already at max)
        eligible = [m for m in all_movers if m['times_mailed'] < max_months]
        aged_out_movers = [m for m in all_movers if m['times_mailed'] >= max_months]
        aged_out_count = len(aged_out_movers)

        # Apply monthly cap
        if monthly_cap and len(eligible) > monthly_cap:
            eligible = eligible[:monthly_cap]

        new_movers_added = sum(1 for m in eligible if m['times_mailed'] == 0)

        # Insert drip_mailings records
        now = datetime.utcnow()
        inserted = 0
        for mover in eligible:
            next_month = mover['times_mailed'] + 1
            try:
                if db_type == 'postgres':
                    with db.cursor() as cur:
                        cur.execute(f"""
                            INSERT INTO drip_mailings (campaign_id, mover_id, month_number, mailed_at)
                            VALUES ({ph},{ph},{ph},{ph})
                            ON CONFLICT (campaign_id, mover_id, month_number) DO NOTHING
                        """, (campaign_id, mover['id'], next_month, now))
                else:
                    db.execute(f"""
                        INSERT OR IGNORE INTO drip_mailings (campaign_id, mover_id, month_number, mailed_at)
                        VALUES ({ph},{ph},{ph},{ph})
                    """, (campaign_id, mover['id'], next_month, now))
                inserted += 1
            except Exception:
                pass

        db.commit()

    # Build CSV export
    exports_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'exports')
    os.makedirs(exports_dir, exist_ok=True)
    ts = now.strftime('%Y%m%d_%H%M%S')
    csv_filename = f"drip_{campaign_id}_month_{ts}.csv"
    csv_path = os.path.join(exports_dir, csv_filename)

    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['First Name', 'Last Name', 'Address', 'City', 'State', 'Zip',
                         'Tier', 'Sale Price', 'Month Number', 'Neighborhood'])
        for mover in eligible:
            writer.writerow([
                '', '',
                mover.get('address', ''), mover.get('city', ''), mover.get('state', ''), mover.get('zip', ''),
                mover.get('tier', ''), mover.get('sale_price', ''),
                mover['times_mailed'] + 1,
                mover.get('neighborhood', '')
            ])

    return jsonify({
        'success': True,
        'generated': inserted,
        'aged_out': aged_out_count,
        'new_movers_added': new_movers_added,
        'csv_file': csv_filename,
    })


@admin_bp.route('/drip-campaigns/<int:campaign_id>/export-latest')
@login_required
@admin_required
def drip_campaign_export_latest(campaign_id):
    from app.utils.database import get_db, get_db_type
    import csv, io
    from flask import Response

    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'

    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                # Get the most recent generation timestamp
                cur.execute(f"""
                    SELECT DATE_TRUNC('minute', MAX(mailed_at)) as last_gen
                    FROM drip_mailings WHERE campaign_id = {ph}
                """, (campaign_id,))
                row = cur.fetchone()
                last_gen = row['last_gen'] if row else None

                if not last_gen:
                    flash('No mailings generated yet.', 'error')
                    return redirect(url_for('admin.drip_campaign_detail', campaign_id=campaign_id))

                cur.execute(f"""
                    SELECT nm.address, nm.city, nm.state, nm.zip,
                           nm.tier, nm.sale_price, nm.neighborhood,
                           dm.month_number
                    FROM drip_mailings dm
                    JOIN new_movers nm ON nm.id = dm.mover_id
                    WHERE dm.campaign_id = {ph}
                    AND DATE_TRUNC('minute', dm.mailed_at) = {ph}
                    ORDER BY dm.month_number ASC, nm.sale_date ASC
                """, (campaign_id, last_gen))
                records = [dict(r) for r in cur.fetchall()]
        else:
            row = db.execute(f"""
                SELECT strftime('%Y-%m-%d %H:%M', MAX(mailed_at)) as last_gen
                FROM drip_mailings WHERE campaign_id = {ph}
            """, (campaign_id,)).fetchone()
            last_gen = row['last_gen'] if row else None

            if not last_gen:
                flash('No mailings generated yet.', 'error')
                return redirect(url_for('admin.drip_campaign_detail', campaign_id=campaign_id))

            records = [dict(r) for r in db.execute(f"""
                SELECT nm.address, nm.city, nm.state, nm.zip,
                       nm.tier, nm.sale_price, nm.neighborhood,
                       dm.month_number
                FROM drip_mailings dm
                JOIN new_movers nm ON nm.id = dm.mover_id
                WHERE dm.campaign_id = {ph}
                AND strftime('%Y-%m-%d %H:%M', dm.mailed_at) = {ph}
                ORDER BY dm.month_number ASC, nm.sale_date ASC
            """, (campaign_id, last_gen)).fetchall()]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['First Name', 'Last Name', 'Address', 'City', 'State', 'Zip',
                     'Tier', 'Sale Price', 'Month Number', 'Neighborhood'])
    for r in records:
        writer.writerow([
            '', '',
            r.get('address', ''), r.get('city', ''), r.get('state', ''), r.get('zip', ''),
            r.get('tier', ''), r.get('sale_price', ''), r.get('month_number', ''),
            r.get('neighborhood', '')
        ])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="drip_campaign_{campaign_id}_latest.csv"'}
    )


@admin_bp.route('/drip-campaigns/<int:campaign_id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def drip_campaign_toggle_status(campaign_id):
    from app.utils.database import get_db, get_db_type
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'

    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"SELECT status FROM drip_campaigns WHERE id = {ph}", (campaign_id,))
                row = cur.fetchone()
                current = row['status'] if row else 'active'
                new_status = 'paused' if current == 'active' else 'active'
                cur.execute(f"UPDATE drip_campaigns SET status = {ph} WHERE id = {ph}", (new_status, campaign_id))
        else:
            row = db.execute(f"SELECT status FROM drip_campaigns WHERE id = {ph}", (campaign_id,)).fetchone()
            current = row['status'] if row else 'active'
            new_status = 'paused' if current == 'active' else 'active'
            db.execute(f"UPDATE drip_campaigns SET status = {ph} WHERE id = {ph}", (new_status, campaign_id))
        db.commit()

    flash(f"Campaign {'paused' if new_status == 'paused' else 'resumed'}.", 'success')
    return redirect(url_for('admin.drip_campaign_detail', campaign_id=campaign_id))


# ── Production ────────────────────────────────────────────────────────────────

@admin_bp.route('/production')
@login_required
@admin_required
def production_list():
    from app.utils.database import get_db, get_db_type, init_db
    init_db()
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute("""
                    SELECT pj.*, dc.name AS campaign_name
                    FROM production_jobs pj
                    LEFT JOIN drip_campaigns dc ON dc.id = pj.campaign_id
                    ORDER BY pj.created_at DESC
                """)
                jobs = [dict(r) for r in cur.fetchall()]
        else:
            rows = db.execute("""
                SELECT pj.*, dc.name AS campaign_name
                FROM production_jobs pj
                LEFT JOIN drip_campaigns dc ON dc.id = pj.campaign_id
                ORDER BY pj.created_at DESC
            """).fetchall()
            jobs = [dict(r) for r in rows]
    return render_template('admin/production.html', jobs=jobs)


@admin_bp.route('/production/new', methods=['GET', 'POST'])
@login_required
@admin_required
def production_new():
    from app.utils.database import get_db, get_db_type, init_db
    init_db()
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'

    if request.method == 'POST':
        name          = request.form.get('name', '').strip()
        campaign_id   = request.form.get('campaign_id', '').strip() or None
        permit_number = request.form.get('permit_number', 'PERMIT #15').strip()

        if not name:
            flash('Job name is required.', 'error')
            return redirect(url_for('admin.production_new'))

        if campaign_id:
            campaign_id = int(campaign_id)

        with get_db() as db:
            # Create the production job
            if db_type == 'postgres':
                with db.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO production_jobs (campaign_id, name, permit_number, status)
                        VALUES ({ph},{ph},{ph},'pending') RETURNING id
                    """, (campaign_id, name, permit_number))
                    job_id = cur.fetchone()['id']
            else:
                cur = db.execute(f"""
                    INSERT INTO production_jobs (campaign_id, name, permit_number, status)
                    VALUES ({ph},{ph},{ph},'pending')
                """, (campaign_id, name, permit_number))
                job_id = cur.lastrowid

            # Pull addresses from campaign's latest drip_mailings
            if campaign_id:
                if db_type == 'postgres':
                    with db.cursor() as cur:
                        cur.execute(f"""
                            SELECT DISTINCT nm.id, nm.address, nm.city, nm.state, nm.zip
                            FROM drip_mailings dm
                            JOIN new_movers nm ON nm.id = dm.mover_id
                            WHERE dm.campaign_id = {ph}
                        """, (campaign_id,))
                        movers = [dict(r) for r in cur.fetchall()]
                else:
                    movers = [dict(r) for r in db.execute(f"""
                        SELECT DISTINCT nm.id, nm.address, nm.city, nm.state, nm.zip
                        FROM drip_mailings dm
                        JOIN new_movers nm ON nm.id = dm.mover_id
                        WHERE dm.campaign_id = {ph}
                    """, (campaign_id,)).fetchall()]

                # Insert addresses
                for mover in movers:
                    zip_raw = mover.get('zip', '') or ''
                    zip5 = zip_raw[:5] if zip_raw else ''
                    zip4 = zip_raw[6:10] if len(zip_raw) > 5 else ''
                    if db_type == 'postgres':
                        with db.cursor() as cur:
                            cur.execute(f"""
                                INSERT INTO production_job_addresses
                                (job_id, mover_id, address, city, state, zip5, zip4)
                                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})
                            """, (job_id, mover['id'], mover.get('address',''),
                                  mover.get('city',''), mover.get('state','GA'),
                                  zip5, zip4))
                    else:
                        db.execute(f"""
                            INSERT INTO production_job_addresses
                            (job_id, mover_id, address, city, state, zip5, zip4)
                            VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})
                        """, (job_id, mover['id'], mover.get('address',''),
                              mover.get('city',''), mover.get('state','GA'),
                              zip5, zip4))

                # Update piece count
                piece_count = len(movers)
                if db_type == 'postgres':
                    with db.cursor() as cur:
                        cur.execute(f"UPDATE production_jobs SET piece_count = {ph} WHERE id = {ph}",
                                    (piece_count, job_id))
                else:
                    db.execute(f"UPDATE production_jobs SET piece_count = {ph} WHERE id = {ph}",
                               (piece_count, job_id))

            db.commit()

        flash(f"Production job '{name}' created.", 'success')
        return redirect(url_for('admin.production_detail', job_id=job_id))

    # GET — load drip campaigns
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute("SELECT id, name FROM drip_campaigns ORDER BY name")
                campaigns = [dict(r) for r in cur.fetchall()]
        else:
            campaigns = [dict(r) for r in db.execute(
                "SELECT id, name FROM drip_campaigns ORDER BY name").fetchall()]

    return render_template('admin/production_new.html', campaigns=campaigns)


@admin_bp.route('/production/<int:job_id>')
@login_required
@admin_required
def production_detail(job_id):
    from app.utils.database import get_db, get_db_type
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"""
                    SELECT pj.*, dc.name AS campaign_name
                    FROM production_jobs pj
                    LEFT JOIN drip_campaigns dc ON dc.id = pj.campaign_id
                    WHERE pj.id = {ph}
                """, (job_id,))
                job = dict(cur.fetchone())

                cur.execute(f"""
                    SELECT * FROM production_job_addresses
                    WHERE job_id = {ph}
                    ORDER BY tray_number ASC NULLS LAST, sequence_number ASC NULLS LAST
                    LIMIT 500
                """, (job_id,))
                addresses = [dict(r) for r in cur.fetchall()]

                cur.execute(f"""
                    SELECT COUNT(DISTINCT tray_number) as tray_count
                    FROM production_job_addresses
                    WHERE job_id = {ph} AND tray_number IS NOT NULL
                """, (job_id,))
                tray_row = cur.fetchone()
                tray_count = tray_row['tray_count'] if tray_row else 0
        else:
            row = db.execute(f"""
                SELECT pj.*, dc.name AS campaign_name
                FROM production_jobs pj
                LEFT JOIN drip_campaigns dc ON dc.id = pj.campaign_id
                WHERE pj.id = {ph}
            """, (job_id,)).fetchone()
            job = dict(row)

            addresses = [dict(r) for r in db.execute(f"""
                SELECT * FROM production_job_addresses
                WHERE job_id = {ph}
                ORDER BY tray_number ASC, sequence_number ASC
                LIMIT 500
            """, (job_id,)).fetchall()]

            tray_row = db.execute(f"""
                SELECT COUNT(DISTINCT tray_number) as tray_count
                FROM production_job_addresses
                WHERE job_id = {ph} AND tray_number IS NOT NULL
            """, (job_id,)).fetchone()
            tray_count = tray_row['tray_count'] if tray_row else 0

    return render_template('admin/production_detail.html',
                           job=job,
                           addresses=addresses,
                           tray_count=tray_count)


@admin_bp.route('/production/<int:job_id>/validate', methods=['POST'])
@login_required
@admin_required
def production_validate(job_id):
    import json
    from app.utils.database import get_db, get_db_type
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'

    # Check for SmartyStreets config
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                               'config', 'smartystreets.json')
    smarty_key = None
    smarty_token = None
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            smarty_key = cfg.get('auth_id') or cfg.get('api_key')
            smarty_token = cfg.get('auth_token') or cfg.get('token')
        except Exception:
            pass

    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"SELECT * FROM production_job_addresses WHERE job_id = {ph}", (job_id,))
                addresses = [dict(r) for r in cur.fetchall()]
        else:
            addresses = [dict(r) for r in db.execute(
                f"SELECT * FROM production_job_addresses WHERE job_id = {ph}", (job_id,)).fetchall()]

    validated_count = 0
    failed_count = 0
    skipped_count = 0

    import requests as req_lib

    for addr in addresses:
        addr_line = addr.get('address') or ''
        city = addr.get('city') or ''
        state = addr.get('state') or 'GA'
        zip5 = addr.get('zip5') or ''

        if smarty_key:
            # Call SmartyStreets
            try:
                params = {
                    'street': addr_line,
                    'city': city,
                    'state': state,
                    'zipcode': zip5,
                    'candidates': 1,
                }
                if smarty_token:
                    params['auth-id'] = smarty_key
                    params['auth-token'] = smarty_token
                else:
                    params['key'] = smarty_key

                resp = req_lib.get(
                    'https://us-street.api.smartystreets.com/street-address',
                    params=params,
                    timeout=5
                )
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    result = data[0]
                    components = result.get('components', {})
                    delivery = result.get('delivery_info', {})
                    analysis = result.get('analysis', {})

                    address_std = result.get('delivery_line_1', addr_line)
                    city_std = components.get('city_name', city)
                    state_std = components.get('state_abbreviation', state)
                    zip5_std = components.get('zipcode', zip5)
                    zip4_std = components.get('plus4_code', '')
                    dpbc = components.get('delivery_point_barcode', '')

                    with get_db() as db:
                        if db_type == 'postgres':
                            with db.cursor() as cur:
                                cur.execute(f"""
                                    UPDATE production_job_addresses SET
                                        address_std={ph}, city_std={ph}, state_std={ph},
                                        zip5_std={ph}, zip4_std={ph}, dpbc={ph}, cass_valid=TRUE
                                    WHERE id={ph}
                                """, (address_std, city_std, state_std, zip5_std, zip4_std, dpbc, addr['id']))
                        else:
                            db.execute(f"""
                                UPDATE production_job_addresses SET
                                    address_std={ph}, city_std={ph}, state_std={ph},
                                    zip5_std={ph}, zip4_std={ph}, dpbc={ph}, cass_valid=1
                                WHERE id={ph}
                            """, (address_std, city_std, state_std, zip5_std, zip4_std, dpbc, addr['id']))
                        db.commit()
                    validated_count += 1
                else:
                    with get_db() as db:
                        if db_type == 'postgres':
                            with db.cursor() as cur:
                                cur.execute(f"UPDATE production_job_addresses SET cass_valid=FALSE WHERE id={ph}",
                                            (addr['id'],))
                        else:
                            db.execute(f"UPDATE production_job_addresses SET cass_valid=0 WHERE id={ph}",
                                       (addr['id'],))
                        db.commit()
                    failed_count += 1
            except Exception:
                failed_count += 1
        else:
            # No API key — mark as skipped (copy input data to std fields)
            with get_db() as db:
                if db_type == 'postgres':
                    with db.cursor() as cur:
                        cur.execute(f"""
                            UPDATE production_job_addresses SET
                                address_std={ph}, city_std={ph}, state_std={ph},
                                zip5_std={ph}, cass_valid=FALSE
                            WHERE id={ph}
                        """, (addr_line, city, state, zip5, addr['id']))
                else:
                    db.execute(f"""
                        UPDATE production_job_addresses SET
                            address_std={ph}, city_std={ph}, state_std={ph},
                            zip5_std={ph}, cass_valid=0
                        WHERE id={ph}
                    """, (addr_line, city, state, zip5, addr['id']))
                db.commit()
            skipped_count += 1

    # Mark job as cass_validated
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"UPDATE production_jobs SET cass_validated=TRUE WHERE id={ph}", (job_id,))
        else:
            db.execute(f"UPDATE production_jobs SET cass_validated=1 WHERE id={ph}", (job_id,))
        db.commit()

    return jsonify({
        'success': True,
        'validated': validated_count,
        'failed': failed_count,
        'skipped': skipped_count,
        'api_key_present': bool(smarty_key),
        'message': 'Validation complete.' if smarty_key else
                   'No SmartyStreets API key found (config/smartystreets.json). Addresses copied as-is. Add auth_id/auth_token to enable CASS validation.'
    })


@admin_bp.route('/production/<int:job_id>/presort', methods=['POST'])
@login_required
@admin_required
def production_presort(job_id):
    from app.utils.database import get_db, get_db_type
    from collections import defaultdict
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'

    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"SELECT * FROM production_job_addresses WHERE job_id = {ph}", (job_id,))
                addresses = [dict(r) for r in cur.fetchall()]
        else:
            addresses = [dict(r) for r in db.execute(
                f"SELECT * FROM production_job_addresses WHERE job_id = {ph}", (job_id,)).fetchall()]

    # Sort: use standardized fields if available, fall back to raw
    def get_sort_key(addr):
        zip5 = addr.get('zip5_std') or addr.get('zip5') or ''
        zip4 = addr.get('zip4_std') or addr.get('zip4') or ''
        address = addr.get('address_std') or addr.get('address') or ''
        return (zip5, zip4, address)

    addresses.sort(key=get_sort_key)

    # Group by ZIP5
    by_zip5 = defaultdict(list)
    for addr in addresses:
        z = addr.get('zip5_std') or addr.get('zip5') or 'XXXXX'
        by_zip5[z].append(addr)

    # Build trays: 5-digit (150+), 3-digit (150+), else mixed
    TRAY_MIN = 150
    BUNDLE_SIZE = 50

    tray_assignments = []  # list of (tray_type, zip_key, [addr_ids])
    leftover = []

    for zip5, addrs in sorted(by_zip5.items()):
        if len(addrs) >= TRAY_MIN:
            tray_assignments.append(('5-digit', zip5, addrs))
        else:
            leftover.extend(addrs)

    # Group leftover by 3-digit prefix
    by_3digit = defaultdict(list)
    for addr in leftover:
        z = addr.get('zip5_std') or addr.get('zip5') or 'XXX'
        prefix = z[:3]
        by_3digit[prefix].append(addr)

    leftover2 = []
    for prefix, addrs in sorted(by_3digit.items()):
        if len(addrs) >= TRAY_MIN:
            tray_assignments.append(('3-digit', prefix, addrs))
        else:
            leftover2.extend(addrs)

    # Remaining go in mixed/ADC tray(s)
    if leftover2:
        # Chunk into trays of max ~1000 pieces (standard flat tray limit)
        chunk_size = 1000
        for i in range(0, len(leftover2), chunk_size):
            tray_assignments.append(('mixed', 'ADC', leftover2[i:i + chunk_size]))

    # Assign tray/bundle/sequence numbers and build sort_key
    tray_summary = []
    updates = []  # (tray_number, bundle_number, sequence_number, sort_key, addr_id)

    for tray_idx, (tray_type, zip_key, addrs) in enumerate(tray_assignments, start=1):
        seq = 0
        for addr in addrs:
            seq += 1
            bundle = ((seq - 1) // BUNDLE_SIZE) + 1
            z5 = addr.get('zip5_std') or addr.get('zip5') or ''
            z4 = addr.get('zip4_std') or addr.get('zip4') or ''
            a = addr.get('address_std') or addr.get('address') or ''
            sort_key = f"{z5}{z4}{a}"
            updates.append((tray_idx, bundle, seq, sort_key, addr['id']))
        tray_summary.append({
            'tray_number': tray_idx,
            'tray_type': tray_type,
            'zip': zip_key,
            'piece_count': len(addrs),
            'bundles': ((len(addrs) - 1) // BUNDLE_SIZE) + 1,
        })

    # Write updates to DB
    with get_db() as db:
        for tray_number, bundle_number, sequence_number, sort_key, addr_id in updates:
            if db_type == 'postgres':
                with db.cursor() as cur:
                    cur.execute(f"""
                        UPDATE production_job_addresses
                        SET tray_number={ph}, bundle_number={ph}, sequence_number={ph}, sort_key={ph}
                        WHERE id={ph}
                    """, (tray_number, bundle_number, sequence_number, sort_key, addr_id))
            else:
                db.execute(f"""
                    UPDATE production_job_addresses
                    SET tray_number={ph}, bundle_number={ph}, sequence_number={ph}, sort_key={ph}
                    WHERE id={ph}
                """, (tray_number, bundle_number, sequence_number, sort_key, addr_id))

        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"UPDATE production_jobs SET presorted=TRUE WHERE id={ph}", (job_id,))
        else:
            db.execute(f"UPDATE production_jobs SET presorted=1 WHERE id={ph}", (job_id,))
        db.commit()

    return jsonify({
        'success': True,
        'tray_count': len(tray_assignments),
        'piece_count': len(addresses),
        'trays': tray_summary,
    })


@admin_bp.route('/production/<int:job_id>/generate-pdf', methods=['POST'])
@login_required
@admin_required
def production_generate_pdf(job_id):
    from app.utils.database import get_db, get_db_type
    from collections import defaultdict
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'

    try:
        from reportlab.lib.pagesizes import landscape
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors
    except ImportError:
        return jsonify({'success': False, 'error': 'ReportLab not installed. Run: pip install reportlab'}), 500

    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"SELECT * FROM production_jobs WHERE id = {ph}", (job_id,))
                job = dict(cur.fetchone())
                cur.execute(f"""
                    SELECT * FROM production_job_addresses
                    WHERE job_id = {ph}
                    ORDER BY tray_number ASC NULLS LAST, sequence_number ASC NULLS LAST
                """, (job_id,))
                addresses = [dict(r) for r in cur.fetchall()]
        else:
            job = dict(db.execute(f"SELECT * FROM production_jobs WHERE id = {ph}", (job_id,)).fetchone())
            addresses = [dict(r) for r in db.execute(f"""
                SELECT * FROM production_job_addresses
                WHERE job_id = {ph}
                ORDER BY tray_number ASC, sequence_number ASC
            """, (job_id,)).fetchall()]

    # Build exports dir
    exports_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'exports')
    os.makedirs(exports_dir, exist_ok=True)

    # Postcard size: 6.5" wide × 9" tall (portrait)
    PAGE_W = 6.5 * inch
    PAGE_H = 9.0 * inch

    permit_number = job.get('permit_number') or 'PERMIT #15'
    permit_city   = job.get('permit_city') or 'NEWNAN'
    permit_state  = job.get('permit_state') or 'GA'

    # ── Main PDF ──────────────────────────────────────────────────────────────
    pdf_path = os.path.join(exports_dir, f'production_job_{job_id}.pdf')
    c = canvas.Canvas(pdf_path, pagesize=(PAGE_W, PAGE_H))

    for addr in addresses:
        # Use standardized fields if available
        addr_line = addr.get('address_std') or addr.get('address') or ''
        city      = addr.get('city_std') or addr.get('city') or ''
        state     = addr.get('state_std') or addr.get('state') or 'GA'
        zip5      = addr.get('zip5_std') or addr.get('zip5') or ''
        zip4      = addr.get('zip4_std') or addr.get('zip4') or ''
        tray_num  = addr.get('tray_number') or ''
        seq_num   = addr.get('sequence_number') or ''

        zip_display = f"{zip5}-{zip4}" if zip4 else zip5

        # ── Indicia box (top-right, 2"×1") ───────────────────────────────────
        indicia_x = PAGE_W - 2.2 * inch
        indicia_y = PAGE_H - 1.2 * inch
        indicia_w = 2.0 * inch
        indicia_h = 1.0 * inch

        c.setStrokeColor(colors.black)
        c.setLineWidth(1)
        c.rect(indicia_x, indicia_y, indicia_w, indicia_h)

        c.setFont('Helvetica-Bold', 8)
        line_h = 11
        lines = [
            'PRSRT STD',
            'US POSTAGE PAID',
            f'{permit_city}, {permit_state}',
            f'PERMIT NO. {permit_number}',
        ]
        text_y = indicia_y + indicia_h - 14
        for line in lines:
            c.drawCentredString(indicia_x + indicia_w / 2, text_y, line)
            text_y -= line_h

        # ── Return address (top-left) ─────────────────────────────────────────
        c.setFont('Helvetica', 8)
        ra_x = 0.35 * inch
        ra_y = PAGE_H - 0.45 * inch
        for ra_line in ['Pinpoint Direct', '35 Andrew St', 'Newnan, GA 30263']:
            c.drawString(ra_x, ra_y, ra_line)
            ra_y -= 11

        # ── Delivery address (center, 14pt bold) ──────────────────────────────
        c.setFont('Helvetica-Bold', 14)
        cx = PAGE_W / 2
        cy = PAGE_H / 2 + 0.3 * inch

        # Address line
        c.drawCentredString(cx, cy, addr_line)
        # City, State ZIP
        c.drawCentredString(cx, cy - 20, f'{city}, {state}  {zip_display}')

        # ── IMb barcode placeholder (bottom strip) ────────────────────────────
        bar_y = 0.25 * inch
        bar_h = 0.35 * inch
        c.setFillColor(colors.Color(0.85, 0.85, 0.85))
        c.rect(0.35 * inch, bar_y, PAGE_W - 0.7 * inch, bar_h, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont('Helvetica', 7)
        c.drawCentredString(cx, bar_y + bar_h / 2 - 3,
                            f'IMb Barcode — {zip5}')

        # ── Tray/seq reference (bottom-right corner) ──────────────────────────
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.Color(0.6, 0.6, 0.6))
        c.drawRightString(PAGE_W - 0.2 * inch, 0.12 * inch,
                          f'Tray {tray_num}  Seq {seq_num}')
        c.setFillColor(colors.black)

        c.showPage()

    c.save()
    page_count = len(addresses)

    # ── Tray Labels PDF ───────────────────────────────────────────────────────
    tray_labels_path = os.path.join(exports_dir, f'production_job_{job_id}_trays.pdf')

    # Group addresses by tray
    trays = defaultdict(list)
    for addr in addresses:
        tn = addr.get('tray_number') or 0
        trays[tn].append(addr)

    from reportlab.lib.pagesizes import letter
    tc = canvas.Canvas(tray_labels_path, pagesize=letter)
    LW, LH = letter

    from datetime import date
    today_str = date.today().strftime('%B %d, %Y')
    job_name = job.get('name', f'Job {job_id}')

    for tray_num in sorted(trays.keys()):
        addrs_in_tray = trays[tray_num]
        piece_count = len(addrs_in_tray)

        # Determine tray type from sort patterns
        zips_in_tray = [a.get('zip5_std') or a.get('zip5') or '' for a in addrs_in_tray]
        unique_5 = set(zips_in_tray)
        unique_3 = set(z[:3] for z in zips_in_tray)
        if len(unique_5) == 1:
            tray_type = '5-Digit'
            zip_label = list(unique_5)[0]
        elif len(unique_3) == 1:
            tray_type = '3-Digit'
            zip_label = list(unique_3)[0] + 'XX'
        else:
            tray_type = 'Mixed / ADC'
            zip_label = 'MIXED'

        # Draw label page
        tc.setFont('Helvetica-Bold', 28)
        tc.drawCentredString(LW / 2, LH - 1.5 * inch, f'TRAY {tray_num}')

        tc.setFont('Helvetica-Bold', 20)
        tc.drawCentredString(LW / 2, LH - 2.2 * inch, tray_type)
        tc.drawCentredString(LW / 2, LH - 2.8 * inch, zip_label)

        tc.setFont('Helvetica', 16)
        tc.drawCentredString(LW / 2, LH - 3.6 * inch, f'{piece_count} pieces')

        tc.setStrokeColor(colors.black)
        tc.setLineWidth(1)
        tc.line(1 * inch, LH - 4.0 * inch, LW - 1 * inch, LH - 4.0 * inch)

        tc.setFont('Helvetica', 12)
        tc.drawCentredString(LW / 2, LH - 4.5 * inch, job_name)
        tc.drawCentredString(LW / 2, LH - 4.9 * inch, today_str)
        tc.drawCentredString(LW / 2, LH - 5.3 * inch, 'Marketing Mail — PRSRT STD')

        tc.showPage()

    tc.save()

    # Update job record
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"""
                    UPDATE production_jobs SET pdf_path={ph}, tray_labels_path={ph}, status='ready_to_print'
                    WHERE id={ph}
                """, (pdf_path, tray_labels_path, job_id))
        else:
            db.execute(f"""
                UPDATE production_jobs SET pdf_path={ph}, tray_labels_path={ph}, status='ready_to_print'
                WHERE id={ph}
            """, (pdf_path, tray_labels_path, job_id))
        db.commit()

    return jsonify({
        'success': True,
        'pdf_path': pdf_path,
        'tray_labels_path': tray_labels_path,
        'page_count': page_count,
        'tray_count': len(trays),
    })


@admin_bp.route('/production/<int:job_id>/download-pdf')
@login_required
@admin_required
def production_download_pdf(job_id):
    from app.utils.database import get_db, get_db_type
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"SELECT pdf_path, name FROM production_jobs WHERE id = {ph}", (job_id,))
                row = dict(cur.fetchone())
        else:
            row = dict(db.execute(f"SELECT pdf_path, name FROM production_jobs WHERE id = {ph}", (job_id,)).fetchone())

    if not row.get('pdf_path') or not os.path.exists(row['pdf_path']):
        flash('PDF not yet generated.', 'error')
        return redirect(url_for('admin.production_detail', job_id=job_id))

    safe_name = (row.get('name') or f'job_{job_id}').replace(' ', '_')
    return send_file(row['pdf_path'], as_attachment=True,
                     download_name=f'{safe_name}_postcards.pdf',
                     mimetype='application/pdf')


@admin_bp.route('/production/<int:job_id>/download-trays')
@login_required
@admin_required
def production_download_trays(job_id):
    from app.utils.database import get_db, get_db_type
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"SELECT tray_labels_path, name FROM production_jobs WHERE id = {ph}", (job_id,))
                row = dict(cur.fetchone())
        else:
            row = dict(db.execute(f"SELECT tray_labels_path, name FROM production_jobs WHERE id = {ph}",
                                  (job_id,)).fetchone())

    if not row.get('tray_labels_path') or not os.path.exists(row['tray_labels_path']):
        flash('Tray labels not yet generated.', 'error')
        return redirect(url_for('admin.production_detail', job_id=job_id))

    safe_name = (row.get('name') or f'job_{job_id}').replace(' ', '_')
    return send_file(row['tray_labels_path'], as_attachment=True,
                     download_name=f'{safe_name}_tray_labels.pdf',
                     mimetype='application/pdf')


@admin_bp.route('/production/<int:job_id>/mark-mailed', methods=['POST'])
@login_required
@admin_required
def production_mark_mailed(job_id):
    from app.utils.database import get_db, get_db_type
    from datetime import datetime
    db_type = get_db_type()
    ph = '%s' if db_type == 'postgres' else '?'
    now = datetime.utcnow()
    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"UPDATE production_jobs SET status='mailed', mailed_at={ph} WHERE id={ph}",
                            (now, job_id))
        else:
            db.execute(f"UPDATE production_jobs SET status='mailed', mailed_at={ph} WHERE id={ph}",
                       (now.isoformat(), job_id))
        db.commit()
    return jsonify({'success': True, 'status': 'mailed', 'mailed_at': now.isoformat()})


# ── Invoices action (keep at end) ─────────────────────────────────────────────

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


# ── Mailing Operations ────────────────────────────────────────────────────────

MAILING_STATUS_ORDER = [
    'Address Processing',
    'Presort Ready',
    'Print Queue',
    'Printing',
    'Tray Assembly',
    'Ready to Drop',
    'Mailed',
]


@admin_bp.route('/mailing-jobs')
@login_required
@admin_required
def mailing_jobs():
    jobs = get_records('mailing_jobs')
    return render_template('admin/mailing_jobs.html', jobs=jobs)


@admin_bp.route('/mailing-jobs/new', methods=['GET', 'POST'])
@login_required
@admin_required
def mailing_job_new():
    clients = get_records('clients')
    campaigns = get_records('campaigns')
    if request.method == 'POST':
        job_name = request.form.get('job_name', '').strip()
        client_id = request.form.get('client_id') or None
        campaign_id = request.form.get('campaign_id') or None
        mail_class = request.form.get('mail_class', 'USPS Marketing Mail')
        piece_count = request.form.get('piece_count', 0)
        notes = request.form.get('notes', '')
        if not job_name:
            flash('Job name is required.', 'error')
            return render_template('admin/mailing_job_new.html', clients=clients, campaigns=campaigns)
        from app.utils.database import get_db, get_db_type
        ph = '%s' if get_db_type() == 'postgres' else '?'
        with get_db() as db:
            if get_db_type() == 'postgres':
                with db.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO mailing_jobs (job_name, client_id, campaign_id, mail_class, piece_count, notes) "
                        f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph}) RETURNING id",
                        (job_name, client_id or None, campaign_id or None, mail_class, piece_count or 0, notes)
                    )
                    new_id = cur.fetchone()['id']
            else:
                cur = db.execute(
                    f"INSERT INTO mailing_jobs (job_name, client_id, campaign_id, mail_class, piece_count, notes) "
                    f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph})",
                    (job_name, client_id or None, campaign_id or None, mail_class, piece_count or 0, notes)
                )
                new_id = cur.lastrowid
            db.commit()
        flash('Mailing job created.', 'success')
        return redirect(url_for('admin.mailing_job_detail', job_id=new_id))
    return render_template('admin/mailing_job_new.html', clients=clients, campaigns=campaigns)


@admin_bp.route('/mailing-jobs/<int:job_id>')
@login_required
@admin_required
def mailing_job_detail(job_id):
    job = get_record('mailing_jobs', job_id)
    # Get trays for this job
    from app.utils.database import get_db, get_db_type
    ph = '%s' if get_db_type() == 'postgres' else '?'
    with get_db() as db:
        if get_db_type() == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"SELECT * FROM mailing_trays WHERE mailing_job_id = {ph} ORDER BY tray_number", (job_id,))
                trays = [dict(r) for r in cur.fetchall()]
        else:
            trays = [dict(r) for r in db.execute(
                f"SELECT * FROM mailing_trays WHERE mailing_job_id = {ph} ORDER BY tray_number", (job_id,)
            ).fetchall()]
    return render_template('admin/mailing_job_detail.html',
                           job=job, trays=trays,
                           status_order=MAILING_STATUS_ORDER)


@admin_bp.route('/mailing-jobs/<int:job_id>/update-cass', methods=['POST'])
@login_required
@admin_required
def mailing_job_update_cass(job_id):
    cass_status = request.form.get('cass_status', 'Pending')
    cass_notes = request.form.get('cass_notes', '')
    from app.utils.database import get_db, get_db_type
    ph = '%s' if get_db_type() == 'postgres' else '?'
    with get_db() as db:
        if get_db_type() == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"UPDATE mailing_jobs SET cass_status={ph}, cass_notes={ph} WHERE id={ph}",
                            (cass_status, cass_notes, job_id))
        else:
            db.execute(f"UPDATE mailing_jobs SET cass_status={ph}, cass_notes={ph} WHERE id={ph}",
                       (cass_status, cass_notes, job_id))
        db.commit()
    flash('CASS status updated.', 'success')
    return redirect(url_for('admin.mailing_job_detail', job_id=job_id))


@admin_bp.route('/mailing-jobs/<int:job_id>/update-print', methods=['POST'])
@login_required
@admin_required
def mailing_job_update_print(job_id):
    from datetime import datetime
    from app.utils.database import get_db, get_db_type
    ph = '%s' if get_db_type() == 'postgres' else '?'
    print_file_url = request.form.get('print_file_url', '')
    sheet_count = request.form.get('sheet_count') or None
    action = request.form.get('action', '')
    now = datetime.utcnow()
    with get_db() as db:
        if action == 'start_print':
            if get_db_type() == 'postgres':
                with db.cursor() as cur:
                    cur.execute(f"UPDATE mailing_jobs SET status='Printing', print_started_at={ph} WHERE id={ph}", (now, job_id))
            else:
                db.execute(f"UPDATE mailing_jobs SET status='Printing', print_started_at={ph} WHERE id={ph}", (now.isoformat(), job_id))
        elif action == 'complete_print':
            if get_db_type() == 'postgres':
                with db.cursor() as cur:
                    cur.execute(f"UPDATE mailing_jobs SET status='Tray Assembly', print_completed_at={ph} WHERE id={ph}", (now, job_id))
            else:
                db.execute(f"UPDATE mailing_jobs SET status='Tray Assembly', print_completed_at={ph} WHERE id={ph}", (now.isoformat(), job_id))
        else:
            updates = "print_file_url={ph}".replace('{ph}', ph)
            params = [print_file_url]
            if sheet_count:
                updates += f", sheet_count={ph}"
                params.append(int(sheet_count))
            params.append(job_id)
            if get_db_type() == 'postgres':
                with db.cursor() as cur:
                    cur.execute(f"UPDATE mailing_jobs SET {updates} WHERE id={ph}", params)
            else:
                db.execute(f"UPDATE mailing_jobs SET {updates} WHERE id={ph}", params)
        db.commit()
    flash('Print info updated.', 'success')
    return redirect(url_for('admin.mailing_job_detail', job_id=job_id))


@admin_bp.route('/mailing-jobs/<int:job_id>/add-tray', methods=['POST'])
@login_required
@admin_required
def mailing_job_add_tray(job_id):
    from app.utils.database import get_db, get_db_type
    ph = '%s' if get_db_type() == 'postgres' else '?'
    tray_number = request.form.get('tray_number') or None
    piece_count = request.form.get('piece_count') or None
    zip_range = request.form.get('zip_range', '')
    tray_label = request.form.get('tray_label', '')
    with get_db() as db:
        if get_db_type() == 'postgres':
            with db.cursor() as cur:
                cur.execute(
                    f"INSERT INTO mailing_trays (mailing_job_id, tray_number, piece_count, zip_range, tray_label) "
                    f"VALUES ({ph},{ph},{ph},{ph},{ph})",
                    (job_id, tray_number, piece_count, zip_range, tray_label)
                )
                cur.execute(f"UPDATE mailing_jobs SET tray_count = (SELECT COUNT(*) FROM mailing_trays WHERE mailing_job_id={ph}) WHERE id={ph}", (job_id, job_id))
        else:
            db.execute(
                f"INSERT INTO mailing_trays (mailing_job_id, tray_number, piece_count, zip_range, tray_label) "
                f"VALUES ({ph},{ph},{ph},{ph},{ph})",
                (job_id, tray_number, piece_count, zip_range, tray_label)
            )
            db.execute(f"UPDATE mailing_jobs SET tray_count = (SELECT COUNT(*) FROM mailing_trays WHERE mailing_job_id={ph}) WHERE id={ph}", (job_id, job_id))
        db.commit()
    flash('Tray added.', 'success')
    return redirect(url_for('admin.mailing_job_detail', job_id=job_id))


@admin_bp.route('/mailing-jobs/<int:job_id>/update-drop', methods=['POST'])
@login_required
@admin_required
def mailing_job_update_drop(job_id):
    from app.utils.database import get_db, get_db_type
    ph = '%s' if get_db_type() == 'postgres' else '?'
    drop_date = request.form.get('drop_date') or None
    bmeu_location = request.form.get('bmeu_location', '')
    form_3602_ref = request.form.get('form_3602_ref', '')
    postage_paid = request.form.get('postage_paid') or None
    with get_db() as db:
        if get_db_type() == 'postgres':
            with db.cursor() as cur:
                cur.execute(
                    f"UPDATE mailing_jobs SET drop_date={ph}, bmeu_location={ph}, form_3602_ref={ph}, postage_paid={ph} WHERE id={ph}",
                    (drop_date, bmeu_location, form_3602_ref, postage_paid, job_id)
                )
        else:
            db.execute(
                f"UPDATE mailing_jobs SET drop_date={ph}, bmeu_location={ph}, form_3602_ref={ph}, postage_paid={ph} WHERE id={ph}",
                (drop_date, bmeu_location, form_3602_ref, postage_paid, job_id)
            )
        db.commit()
    flash('Drop info saved.', 'success')
    return redirect(url_for('admin.mailing_job_detail', job_id=job_id))


@admin_bp.route('/mailing-jobs/<int:job_id>/advance', methods=['POST'])
@login_required
@admin_required
def mailing_job_advance(job_id):
    from app.utils.database import get_db, get_db_type
    ph = '%s' if get_db_type() == 'postgres' else '?'
    with get_db() as db:
        if get_db_type() == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"SELECT status FROM mailing_jobs WHERE id={ph}", (job_id,))
                row = cur.fetchone()
        else:
            row = db.execute(f"SELECT status FROM mailing_jobs WHERE id={ph}", (job_id,)).fetchone()
        if row:
            current_status = row['status']
            idx = MAILING_STATUS_ORDER.index(current_status) if current_status in MAILING_STATUS_ORDER else -1
            if idx >= 0 and idx < len(MAILING_STATUS_ORDER) - 1:
                next_status = MAILING_STATUS_ORDER[idx + 1]
                if get_db_type() == 'postgres':
                    with db.cursor() as cur:
                        cur.execute(f"UPDATE mailing_jobs SET status={ph} WHERE id={ph}", (next_status, job_id))
                else:
                    db.execute(f"UPDATE mailing_jobs SET status={ph} WHERE id={ph}", (next_status, job_id))
                db.commit()
                flash(f'Status advanced to {next_status}.', 'success')
            else:
                flash('Already at final status.', 'info')
    return redirect(url_for('admin.mailing_job_detail', job_id=job_id))


@admin_bp.route('/mailing-jobs/<int:job_id>/complete', methods=['POST'])
@login_required
@admin_required
def mailing_job_complete(job_id):
    from app.utils.database import get_db, get_db_type
    ph = '%s' if get_db_type() == 'postgres' else '?'
    with get_db() as db:
        if get_db_type() == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"UPDATE mailing_jobs SET status='Mailed' WHERE id={ph}", (job_id,))
        else:
            db.execute(f"UPDATE mailing_jobs SET status='Mailed' WHERE id={ph}", (job_id,))
        db.commit()
    flash('Job marked as Mailed! ✅', 'success')
    return redirect(url_for('admin.mailing_job_detail', job_id=job_id))


# ── Design Requests ───────────────────────────────────────────────────────────

DR_STATUS_ORDER = ['Draft', 'Submitted', 'In Review', 'Proof Sent', 'Revision Requested', 'Final Approved']

ALLOWED_PROOF_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf', '.tif', '.tiff'}


def _allowed_proof_file(filename):
    ext = os.path.splitext(filename.lower())[1]
    return ext in ALLOWED_PROOF_EXTENSIONS


@admin_bp.route('/design-requests')
@login_required
@admin_required
def design_requests():
    from app.utils.database import get_db, get_db_type
    try:
        drs = get_records('design_requests')
        drs = sorted(drs, key=lambda x: x.get('createdTime', ''), reverse=True)
    except Exception:
        drs = []
    return render_template('admin/design_requests.html', design_requests=drs)


@admin_bp.route('/design-requests/<int:dr_id>')
@login_required
@admin_required
def design_request_detail(dr_id):
    from app.utils.r2 import get_presigned_url
    try:
        dr = get_record('design_requests', dr_id)
    except Exception:
        flash('Design request not found.', 'error')
        return redirect(url_for('admin.design_requests'))

    # Generate presigned URLs for all files (1 hour expiry)
    def make_urls(keys_str):
        if not keys_str:
            return []
        urls = []
        for key in keys_str.split(','):
            key = key.strip()
            if key:
                try:
                    url = get_presigned_url(key, expires_in=3600)
                    urls.append({'key': key, 'url': url, 'name': key.split('/')[-1]})
                except Exception:
                    urls.append({'key': key, 'url': None, 'name': key.split('/')[-1]})
        return urls

    f = dr['fields']
    logo_urls = make_urls(f.get('Logo Files', ''))
    product_urls = make_urls(f.get('Product Files', ''))
    inspiration_urls = make_urls(f.get('Inspiration Files', ''))
    proof_url = None
    if f.get('Proof File'):
        try:
            proof_url = get_presigned_url(f['Proof File'], expires_in=3600)
        except Exception:
            pass

    return render_template('admin/design_request_detail.html',
                           dr=dr,
                           status_order=DR_STATUS_ORDER,
                           logo_urls=logo_urls,
                           product_urls=product_urls,
                           inspiration_urls=inspiration_urls,
                           proof_url=proof_url)


@admin_bp.route('/design-requests/<int:dr_id>/upload-proof', methods=['POST'])
@login_required
@admin_required
def design_request_upload_proof(dr_id):
    from app.utils.database import get_db, get_db_type
    ph = '%s' if get_db_type() == 'postgres' else '?'

    proof = request.files.get('proof_file')
    if not proof or not proof.filename:
        flash('No file selected.', 'error')
        return redirect(url_for('admin.design_request_detail', dr_id=dr_id))

    if not _allowed_proof_file(proof.filename):
        flash('Invalid file type. Allowed: JPG, PNG, PDF, TIFF.', 'error')
        return redirect(url_for('admin.design_request_detail', dr_id=dr_id))

    from app.utils.r2 import upload_file
    try:
        rel_path = upload_file(proof.stream, proof.filename, folder=f"proofs/{dr_id}")
    except Exception as e:
        flash(f'Upload failed: {e}', 'error')
        return redirect(url_for('admin.design_request_detail', dr_id=dr_id))

    now = datetime.utcnow()
    with get_db() as db:
        if get_db_type() == 'postgres':
            with db.cursor() as cur:
                cur.execute(
                    f"UPDATE design_requests SET proof_file={ph}, proof_uploaded_at={ph}, status='Proof Sent' WHERE id={ph}",
                    (rel_path, now, dr_id)
                )
        else:
            db.execute(
                f"UPDATE design_requests SET proof_file={ph}, proof_uploaded_at={ph}, status='Proof Sent' WHERE id={ph}",
                (rel_path, now, dr_id)
            )
        db.commit()

    flash('Proof uploaded and status set to "Proof Sent". Client can now review.', 'success')
    return redirect(url_for('admin.design_request_detail', dr_id=dr_id))


@admin_bp.route('/design-requests/<int:dr_id>/update-admin', methods=['POST'])
@login_required
@admin_required
def design_request_update_admin(dr_id):
    from app.utils.database import get_db, get_db_type
    ph = '%s' if get_db_type() == 'postgres' else '?'

    admin_notes = request.form.get('admin_notes', '').strip()
    fiverr_ref = request.form.get('fiverr_order_ref', '').strip()

    with get_db() as db:
        if get_db_type() == 'postgres':
            with db.cursor() as cur:
                cur.execute(
                    f"UPDATE design_requests SET admin_notes={ph}, fiverr_order_ref={ph} WHERE id={ph}",
                    (admin_notes, fiverr_ref, dr_id)
                )
        else:
            db.execute(
                f"UPDATE design_requests SET admin_notes={ph}, fiverr_order_ref={ph} WHERE id={ph}",
                (admin_notes, fiverr_ref, dr_id)
            )
        db.commit()

    flash('Admin notes saved.', 'success')
    return redirect(url_for('admin.design_request_detail', dr_id=dr_id))


@admin_bp.route('/design-requests/<int:dr_id>/advance', methods=['POST'])
@login_required
@admin_required
def design_request_advance(dr_id):
    from app.utils.database import get_db, get_db_type
    ph = '%s' if get_db_type() == 'postgres' else '?'

    with get_db() as db:
        if get_db_type() == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"SELECT status FROM design_requests WHERE id={ph}", (dr_id,))
                row = cur.fetchone()
        else:
            row = db.execute(f"SELECT status FROM design_requests WHERE id={ph}", (dr_id,)).fetchone()

        if row:
            current_status = row['status']
            # Skip 'Revision Requested' when manually advancing
            advanceable = ['Draft', 'Submitted', 'In Review', 'Proof Sent', 'Final Approved']
            idx = advanceable.index(current_status) if current_status in advanceable else -1
            if idx >= 0 and idx < len(advanceable) - 1:
                next_status = advanceable[idx + 1]
                if get_db_type() == 'postgres':
                    with db.cursor() as cur:
                        cur.execute(f"UPDATE design_requests SET status={ph} WHERE id={ph}", (next_status, dr_id))
                else:
                    db.execute(f"UPDATE design_requests SET status={ph} WHERE id={ph}", (next_status, dr_id))
                db.commit()
                flash(f'Status advanced to "{next_status}".', 'success')
            else:
                flash('Already at final status or cannot auto-advance from this state.', 'info')

    return redirect(url_for('admin.design_request_detail', dr_id=dr_id))


# ── One-time test client setup ────────────────────────────────────────────────
@admin_bp.route('/setup-test-client')
@login_required
@admin_required
def setup_test_client():
    from app.utils.database import get_db, get_db_type
    from werkzeug.security import generate_password_hash
    ph = '%s' if get_db_type() == 'postgres' else '?'
    with get_db() as db:
        if get_db_type() == 'postgres':
            with db.cursor() as cur:
                cur.execute(f"SELECT id FROM clients WHERE company_name = {ph}", ('Blue Alpha Test',))
                existing = cur.fetchone()
                if existing:
                    return f"Test client already exists (ID: {existing['id']}). <a href='/admin/'>Back</a>"
                cur.execute(
                    f"INSERT INTO clients (company_name, contact_name, contact_email, status) VALUES ({ph},{ph},{ph},{ph}) RETURNING id",
                    ('Blue Alpha Test', 'Jesse Frei', 'jesse@bluealpha.us', 'Active')
                )
                client_id = cur.fetchone()['id']
                pw = generate_password_hash('TestClient2026!')
                cur.execute(
                    f"INSERT INTO users (name, email, password_hash, role, client_id) VALUES ({ph},{ph},{ph},{ph},{ph}) RETURNING id",
                    ('Jesse (Test Client)', 'testclient@pinpointdirect.io', pw, 'Client', client_id)
                )
                user_id = cur.fetchone()['id']
            db.commit()
            return f"""<h2>✅ Test client created!</h2>
            <p>Client ID: {client_id} | User ID: {user_id}</p>
            <p><strong>Email:</strong> testclient@pinpointdirect.io</p>
            <p><strong>Password:</strong> TestClient2026!</p>
            <p><a href='/admin/'>Back to admin</a></p>"""
        return "Only works on PostgreSQL (Railway)."


# ─────────────────────────────────────────────
# MASTER ADDRESS LIST MANAGEMENT
# ─────────────────────────────────────────────


@admin_bp.route('/master-list/delete/<int:record_id>', methods=['POST'])
@login_required
def master_list_delete(record_id):
    """Delete a single master_addresses record."""
    from app.utils.database import get_db, db_exec
    db = get_db()
    try:
        db_exec(db, 'DELETE FROM master_addresses WHERE id = ?', (record_id,))
        db.commit()
        if hasattr(db, 'close'):
            db.close()
        flash('Record deleted.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'error')
    # Redirect back preserving filters
    return redirect(request.referrer or url_for('admin.master_list'))


@admin_bp.route('/master-list/wipe', methods=['POST'])
@login_required
def master_list_wipe():
    """Wipe all master_addresses records for a fresh start."""
    from app.utils.database import get_db, db_exec
    db = get_db()
    try:
        db_exec(db, 'DELETE FROM master_addresses', ())
        db.commit()
        if hasattr(db, 'close'):
            db.close()
        flash('✅ Master list cleared — ready for fresh upload.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'error')
    return redirect(url_for('admin.master_list'))


@admin_bp.route('/master-list/delete-batch', methods=['POST'])
@login_required
def master_list_delete_batch():
    """Delete all master_addresses records belonging to a specific upload batch."""
    from app.utils.database import get_db, db_exec, db_fetchone
    batch = request.form.get('batch', '').strip()
    if not batch:
        flash('No batch specified.', 'error')
        return redirect(url_for('admin.master_list'))
    db = get_db()
    try:
        count_row = db_fetchone(db, 'SELECT COUNT(*) as cnt FROM master_addresses WHERE upload_batch = ?', (batch,))
        cnt = count_row['cnt'] if count_row else 0
        db_exec(db, 'DELETE FROM master_addresses WHERE upload_batch = ?', (batch,))
        db.commit()
        if hasattr(db, 'close'):
            db.close()
        flash(f'✅ Deleted {cnt:,} records from batch "{batch}".', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'error')
    return redirect(url_for('admin.master_list'))


@admin_bp.route('/master-list/save-as-list', methods=['POST'])
@login_required
def master_list_save_as_list():
    """
    Save the current filtered master list selection as a mailing list.
    Accepts the same filter params as master_list() view, plus a list_name.
    """
    from app.utils.database import get_db, db_fetchall, db_exec, db_insert

    list_name   = request.form.get('list_name', '').strip()
    county      = request.form.get('county', '')
    list_type   = request.form.get('list_type', '')
    permit_cat  = request.form.get('permit_category', '')
    upload_batch= request.form.get('upload_batch', '')
    tier        = request.form.get('tier', '')
    neighborhood= request.form.get('neighborhood', '')
    year_built_max = request.form.get('year_built_max', '')
    notes       = request.form.get('notes', '').strip()

    if not list_name:
        flash('Please enter a name for the mailing list.', 'error')
        return redirect(url_for('admin.master_list'))

    # Build the same WHERE clause as master_list()
    where = ['1=1']
    params = []
    if county:
        where.append('county = ?'); params.append(county)
    if list_type:
        where.append('list_type = ?'); params.append(list_type)
    if permit_cat:
        where.append('permit_category = ?'); params.append(permit_cat)
    if upload_batch:
        where.append('upload_batch = ?'); params.append(upload_batch)
    if tier:
        where.append('tier = ?'); params.append(tier)
    if neighborhood:
        where.append('neighborhood = ?'); params.append(neighborhood)
    if year_built_max:
        try:
            where.append('year_built <= ?'); params.append(int(year_built_max))
        except ValueError:
            pass

    where_sql = ' AND '.join(where)

    db = get_db()
    try:
        rows = db_fetchall(db,
            f'SELECT * FROM master_addresses WHERE {where_sql} ORDER BY created_at DESC',
            tuple(params)
        )

        if not rows:
            flash('No records match the current filters — nothing to save.', 'error')
            if hasattr(db, 'close'): db.close()
            return redirect(url_for('admin.master_list'))

        # Build a description of what filters were applied
        filter_parts = []
        if county: filter_parts.append(f'County: {county}')
        if list_type: filter_parts.append(f'Type: {list_type}')
        if permit_cat: filter_parts.append(f'Category: {permit_cat}')
        if upload_batch: filter_parts.append(f'Batch: {upload_batch}')
        if tier: filter_parts.append(f'Tier: {tier}')
        if neighborhood: filter_parts.append(f'Neighborhood: {neighborhood}')
        if year_built_max: filter_parts.append(f'Built ≤ {year_built_max}')
        auto_notes = ('Filters: ' + ', '.join(filter_parts)) if filter_parts else 'All master list records'
        final_notes = notes or auto_notes

        # Create the mailing list record
        list_id = db_insert(db,
            'INSERT INTO mailing_lists (name, total, notes) VALUES (?,?,?)',
            (list_name, len(rows), final_notes)
        )

        # Insert all matching addresses as list_records
        ph = '%s' if hasattr(db, 'cursor') else '?'
        insert_sql = f"""
            INSERT INTO list_records
            (list_id, first_name, last_name, address1, address2, city, state, zip)
            VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
        """
        from app.utils.database import db_executemany
        db_executemany(db, insert_sql, [
            (list_id,
             r.get('first_name') or '', r.get('last_name') or '',
             r.get('address1') or '', r.get('address2') or '',
             r.get('city') or '', r.get('state') or 'GA', r.get('zip') or '')
            for r in rows
        ])
        db.commit()
        if hasattr(db, 'close'): db.close()

        flash(f'✅ Saved "{list_name}" — {len(rows):,} addresses added to mailing lists.', 'success')
        return redirect(url_for('admin.list_detail', list_id=list_id))

    except Exception as e:
        if hasattr(db, 'close'): db.close()
        flash(f'Error saving list: {e}', 'error')
        return redirect(url_for('admin.master_list'))


@admin_bp.route('/master-list/search')
@login_required
def master_list_search():
    """Real-time address search — returns JSON rows matching query."""
    from app.utils.database import get_db, db_fetchall, get_db_type
    import json as _json

    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify({'results': [], 'total': 0})

    db = get_db()
    like = f'%{q}%'
    is_pg = get_db_type() == 'postgres'
    ph = '%s' if is_pg else '?'

    like_op = 'ILIKE' if is_pg else 'LIKE'
    sql = f"""
        SELECT id, first_name, last_name, address1, address2, city, state, zip,
               county, list_type, tier, permit_category, sale_price, permit_value,
               sale_date, permit_date, year_built, square_ft, neighborhood,
               permit_status, added_date, permit_description
        FROM master_addresses
        WHERE address1 {like_op} {ph}
           OR first_name {like_op} {ph}
           OR last_name {like_op} {ph}
           OR city {like_op} {ph}
           OR zip {like_op} {ph}
           OR neighborhood {like_op} {ph}
           OR permit_number {like_op} {ph}
           OR permit_description {like_op} {ph}
        ORDER BY added_date DESC
        LIMIT 50
    """

    rows = db_fetchall(db, sql, (like,) * 8)
    if hasattr(db, 'close'):
        db.close()

    results = []
    for r in rows:
        results.append({
            'id': r['id'],
            'name': f"{r.get('first_name') or ''} {r.get('last_name') or ''}".strip() or None,
            'address1': r.get('address1'),
            'address2': r.get('address2'),
            'city': r.get('city'),
            'state': r.get('state'),
            'zip': r.get('zip'),
            'county': r.get('county'),
            'list_type': r.get('list_type'),
            'tier': r.get('tier'),
            'permit_category': r.get('permit_category'),
            'sale_price': float(r['sale_price']) if r.get('sale_price') else None,
            'permit_value': float(r['permit_value']) if r.get('permit_value') else None,
            'sale_date': r.get('sale_date'),
            'permit_date': r.get('permit_date'),
            'year_built': r.get('year_built'),
            'square_ft': r.get('square_ft'),
            'neighborhood': r.get('neighborhood'),
            'permit_status': r.get('permit_status'),
            'added_date': r.get('added_date'),
            'permit_description': r.get('permit_description'),
        })

    return jsonify({'results': results, 'total': len(results)})


@admin_bp.route('/master-list/enrich-zips', methods=['POST'])
@login_required
def master_list_enrich_zips():
    """Enrich master_addresses records missing zip codes. Processes 25 at a time."""
    import requests as req_lib
    from app.utils.database import get_db, db_fetchall, db_exec

    db = get_db()
    ph = '%s' if str(type(db)).find('psycopg') != -1 else '?'

    # Get true total count of records missing zip
    from app.utils.database import db_fetchone
    total_row = db_fetchone(db, "SELECT COUNT(*) as cnt FROM master_addresses WHERE (zip IS NULL OR zip = '')")
    total_missing = total_row['cnt'] if total_row else 0

    # Fetch a batch to process
    missing = db_fetchall(db,
        "SELECT id, address1, city, county, state, neighborhood FROM master_addresses WHERE (zip IS NULL OR zip = '') LIMIT 25"
    )

    if not missing:
        if hasattr(db, 'close'): db.close()
        return jsonify({'done': True, 'message': 'All ZIP codes enriched!', 'updated': 0, 'remaining': 0, 'total': 0})

    batch = missing[:25]
    session = req_lib.Session()
    session.headers.update({'User-Agent': 'PinpointDirect/1.0'})

    updated = 0
    failed = 0

    for r in batch:
        address   = (r['address1'] or '').strip()
        county    = r['county'] or 'Coweta County GA'
        state     = r['state'] or 'GA'
        neighborhood = (r['neighborhood'] or '').strip()
        city      = r['city'] or COUNTY_CITIES.get(county, [''])[0]

        if not address:
            failed += 1
            continue

        zip_code = None

        # 1) Neighborhood → zip map (instant)
        zip_code = _zip_from_neighborhood(neighborhood)

        # 2) Census geocoder
        if not zip_code:
            for try_city in COUNTY_CITIES.get(county, [city])[:2]:
                try:
                    resp = session.get(
                        'https://geocoding.geo.census.gov/geocoder/locations/onelineaddress',
                        params={'address': f"{address}, {try_city}, {state}",
                                'benchmark': 'Public_AR_Current', 'format': 'json'},
                        timeout=5
                    )
                    matches = resp.json().get('result', {}).get('addressMatches', [])
                    if matches:
                        comps = matches[0].get('addressComponents', {})
                        zip_code = comps.get('zip', '')
                        found_city = comps.get('city', try_city).title()
                        if zip_code:
                            city = found_city
                            break
                except Exception:
                    pass

        # 3) SerpAPI fallback
        if not zip_code:
            try:
                import re as _re, json as _j, os as _os
                serp_key = None
                try:
                    cfg = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), 'config', 'agency_scraper.json')
                    serp_key = _j.load(open(cfg)).get('serpapi_key') if _os.path.exists(cfg) else None
                except Exception:
                    pass
                serp_key = serp_key or _os.getenv('SERPAPI_KEY')

                COUNTY_LL = {
                    'Coweta County GA':  '@33.3812,-84.7600,12z',
                    'Fayette County GA': '@33.4300,-84.5000,12z',
                    'Fulton County GA':  '@33.7490,-84.3880,12z',
                }
                ll = COUNTY_LL.get(county, '@33.3812,-84.7600,12z')
                try_city = COUNTY_CITIES.get(county, [city])[0]

                if serp_key:
                    sresp = session.get(
                        'https://serpapi.com/search.json',
                        params={'engine': 'google_maps', 'q': f'{address}, {try_city}, {state}',
                                'll': ll, 'type': 'search', 'api_key': serp_key},
                        timeout=8
                    )
                    sdata = sresp.json()
                    addr_str = sdata.get('place_results', {}).get('address', '')
                    if not addr_str:
                        results = sdata.get('local_results', [])
                        addr_str = results[0].get('address', '') if results else ''
                    if addr_str:
                        zm = _re.search(r'\b(\d{5})\b', addr_str)
                        if zm:
                            zip_code = zm.group(1)
            except Exception:
                pass

        if zip_code:
            db_exec(db, f'UPDATE master_addresses SET zip = {ph}, city = {ph} WHERE id = {ph}',
                    (zip_code, city, r['id']))
            updated += 1
        else:
            failed += 1

    db.commit()
    if hasattr(db, 'close'): db.close()

    remaining = max(0, total_missing - len(batch))
    return jsonify({
        'done':      remaining == 0,
        'updated':   updated,
        'failed':    failed,
        'remaining': remaining,
        'total':     total_missing,
        'message':   'All ZIP codes enriched!' if remaining == 0 else f'{remaining:,} remaining…'
    })


@admin_bp.route('/master-list')
@login_required
def master_list():
    """Master address list overview — filterable by county, list type, permit category."""
    from app.utils.database import get_db, db_fetchall, db_fetchone
    db = get_db()

    # Filters from query params
    county = request.args.get('county', '')
    list_type = request.args.get('list_type', '')
    permit_category = request.args.get('permit_category', '')
    upload_batch = request.args.get('upload_batch', '')
    tier = request.args.get('tier', '')
    neighborhood = request.args.get('neighborhood', '')
    year_built_max = request.args.get('year_built_max', '')

    page = int(request.args.get('page', 1))
    per_page = 100
    offset = (page - 1) * per_page

    # Build filter clauses
    where = ['1=1']
    params = []
    if county:
        where.append('county = ?')
        params.append(county)
    if list_type:
        where.append('list_type = ?')
        params.append(list_type)
    if permit_category:
        where.append('permit_category = ?')
        params.append(permit_category)
    if upload_batch:
        where.append('upload_batch = ?')
        params.append(upload_batch)
    if tier:
        where.append('tier = ?')
        params.append(tier)
    if neighborhood:
        where.append('neighborhood = ?')
        params.append(neighborhood)
    if year_built_max:
        try:
            where.append('year_built <= ?')
            params.append(int(year_built_max))
        except ValueError:
            pass

    where_sql = ' AND '.join(where)

    total_row = db_fetchone(db, f'SELECT COUNT(*) as cnt FROM master_addresses WHERE {where_sql}', tuple(params))
    total = total_row['cnt'] if total_row else 0

    records = db_fetchall(db,
        f'SELECT * FROM master_addresses WHERE {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?',
        tuple(params + [per_page, offset])
    )

    # For filter dropdowns
    counties = db_fetchall(db, 'SELECT DISTINCT county FROM master_addresses WHERE county IS NOT NULL ORDER BY county')
    batches = db_fetchall(db, 'SELECT DISTINCT upload_batch FROM master_addresses WHERE upload_batch IS NOT NULL ORDER BY upload_batch DESC')
    categories = db_fetchall(db, 'SELECT DISTINCT permit_category FROM master_addresses WHERE permit_category IS NOT NULL ORDER BY permit_category')
    neighborhoods = db_fetchall(db, 'SELECT DISTINCT neighborhood FROM master_addresses WHERE neighborhood IS NOT NULL AND neighborhood != \'\' ORDER BY neighborhood')

    # Stats summary
    stats = db_fetchall(db, '''
        SELECT list_type, COUNT(*) as cnt
        FROM master_addresses
        GROUP BY list_type ORDER BY cnt DESC
    ''')

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    if hasattr(db, 'close'):
        db.close()

    return render_template('admin/master_list.html',
        records=records,
        total=total,
        page=page,
        total_pages=total_pages,
        counties=[r['county'] for r in counties],
        batches=[r['upload_batch'] for r in batches],
        categories=[r['permit_category'] for r in categories],
        neighborhoods=[r['neighborhood'] for r in neighborhoods],
        stats=stats,
        filters={'county': county, 'list_type': list_type, 'permit_category': permit_category,
                 'upload_batch': upload_batch, 'tier': tier, 'neighborhood': neighborhood, 'year_built_max': year_built_max}
    )


@admin_bp.route('/master-list/upload', methods=['GET', 'POST'])
@login_required
def master_list_upload():
    """Upload new addresses to the master list. Supports multiple files in one go."""
    from app.utils.database import get_db, db_fetchall, db_exec, DATABASE_URL
    from app.utils.master_list_parser import parse_master_list_file

    KNOWN_COUNTIES = [
        'Coweta County GA',
        'Fayette County GA',
        'Fulton County GA',
    ]

    if request.method == 'GET':
        db = get_db()
        existing_counties = db_fetchall(db, 'SELECT DISTINCT county FROM master_addresses WHERE county IS NOT NULL ORDER BY county')
        existing_counties = [r['county'] for r in existing_counties]
        if hasattr(db, 'close'):
            db.close()
        # Merge known counties with any already in DB (deduped, sorted)
        all_counties = sorted(set(KNOWN_COUNTIES) | set(existing_counties))
        return render_template('admin/master_list_upload.html', known_counties=KNOWN_COUNTIES, existing_counties=all_counties)

    # POST — process one or more files
    files = request.files.getlist('file')
    county = request.form.get('county', '').strip()
    list_type_override = request.form.get('list_type', '') or None
    batch_label = request.form.get('batch_label', '').strip() or None

    files = [f for f in files if f and f.filename]
    if not files:
        flash('No file selected.', 'error')
        return redirect(url_for('admin.master_list_upload'))
    if not county:
        flash('Please specify a county.', 'error')
        return redirect(url_for('admin.master_list_upload'))

    # Parse all files, collect records
    all_records = []
    all_warnings = []
    total_skipped = 0

    for file in files:
        try:
            records, detected_type, category_summary, warnings, skipped = parse_master_list_file(
                file, county, list_type_override, batch_label
            )
            all_records.extend(records)
            all_warnings.extend(warnings)
            total_skipped += skipped
        except ValueError as e:
            flash(f'{file.filename}: {e}', 'error')

    if not all_records:
        flash('No valid records found in the uploaded file(s).', 'error')
        return redirect(url_for('admin.master_list_upload'))

    # Priority ranking — higher number wins
    TYPE_PRIORITY = {'generic': 1, 'permit': 2, 'new_mover': 3}

    # Insert with smart upsert logic:
    # - New record with no existing match → INSERT
    # - New record beats existing by priority → UPDATE (new_mover/permit > generic)
    # - New_mover vs permit → most recent sale/permit date wins
    # - Generic never overwrites anything
    db = get_db()
    try:
        existing = db_fetchall(db, """
            SELECT id, address_hash, list_type, sale_date, permit_date,
                   first_name, last_name, neighborhood, tier, year_built, square_ft,
                   permit_category, permit_description, permit_value, permit_number,
                   sale_price, parcel_class, city, state, zip, county
            FROM master_addresses
        """)
        existing_map = {r['address_hash']: r for r in existing}

        # Fields that can be filled in from any source (field-level merge).
        # If existing record has a null/blank value and incoming has it filled,
        # always patch it in — regardless of priority direction.
        FILLABLE_FIELDS = [
            'first_name', 'last_name', 'neighborhood', 'tier',
            'year_built', 'square_ft', 'parcel_class',
            'permit_category', 'permit_description', 'permit_value',
            'permit_date', 'permit_number', 'permit_status',
            'sale_price', 'sale_date',
            'city', 'state', 'zip', 'county',
        ]

        def _val(v):
            """Return None if value is empty/None, else the value."""
            if v is None:
                return None
            if isinstance(v, str) and not v.strip():
                return None
            return v

        def _build_fill_patch(incoming, existing_rec):
            """
            Return a dict of {field: new_value} for any field that is blank
            in the existing record but has a value in the incoming record.
            """
            patch = {}
            for field in FILLABLE_FIELDS:
                if _val(existing_rec.get(field)) is None and _val(incoming.get(field)) is not None:
                    patch[field] = incoming[field]
            return patch

        seen = set()
        to_insert = []
        to_update = []        # list of (record, existing_id) — full upsert wins
        to_fill = []          # list of (patch_dict, existing_id) — gap-fill only
        skipped_lower_priority = 0

        for r in all_records:
            h = r['address_hash']
            if h in seen:
                continue
            seen.add(h)

            if h not in existing_map:
                to_insert.append(r)
            else:
                existing_rec = existing_map[h]
                incoming_priority = TYPE_PRIORITY.get(r['list_type'], 0)
                existing_priority = TYPE_PRIORITY.get(existing_rec['list_type'] or 'generic', 0)

                if incoming_priority < existing_priority:
                    # Incoming is lower priority — don't overwrite core fields,
                    # but still fill in any gaps the existing record is missing.
                    patch = _build_fill_patch(r, existing_rec)
                    if patch:
                        to_fill.append((patch, existing_rec['id']))
                    else:
                        skipped_lower_priority += 1
                    continue
                elif incoming_priority == existing_priority:
                    # Same type — compare dates, keep most recent
                    incoming_date = r.get('sale_date') or r.get('permit_date') or ''
                    existing_date = existing_rec.get('sale_date') or existing_rec.get('permit_date') or ''
                    if incoming_date and existing_date and incoming_date <= existing_date:
                        # Older — still gap-fill
                        patch = _build_fill_patch(r, existing_rec)
                        if patch:
                            to_fill.append((patch, existing_rec['id']))
                        else:
                            skipped_lower_priority += 1
                        continue
                    to_update.append((r, existing_rec['id']))
                else:
                    # Incoming is higher priority — full update, but preserve
                    # existing values in fields the incoming record leaves blank.
                    # Merge: incoming wins for its fields, existing fills gaps.
                    merged = dict(existing_rec)
                    merged.update({k: v for k, v in r.items() if _val(v) is not None})
                    to_update.append((merged, existing_rec['id']))

        dupes = len(all_records) - len(to_insert) - len(to_update) - len(to_fill) - skipped_lower_priority

        for r in to_insert:
            sql = """INSERT INTO master_addresses
                (first_name, last_name, address1, address2, city, state, zip, county,
                 list_type, permit_category, permit_description, permit_value, permit_date, permit_number, permit_status,
                 sale_price, sale_date, tier, year_built, square_ft, neighborhood, parcel_class,
                 upload_batch, source_file, added_date, address_hash)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
            params = (
                r['first_name'], r['last_name'], r['address1'], r['address2'],
                r['city'], r['state'], r['zip'], r['county'],
                r['list_type'], r.get('permit_category'), r.get('permit_description'),
                r.get('permit_value'), r.get('permit_date'), r.get('permit_number'), r.get('permit_status'),
                r.get('sale_price'), r.get('sale_date'), r.get('tier'),
                r.get('year_built'), r.get('square_ft'), r.get('neighborhood'), r.get('parcel_class'),
                r['upload_batch'], r['source_file'], r['added_date'], r['address_hash']
            )
            db_exec(db, sql, params)

        for r, existing_id in to_update:
            sql = """UPDATE master_addresses SET
                first_name=?, last_name=?, list_type=?,
                permit_category=?, permit_description=?, permit_value=?, permit_date=?, permit_number=?, permit_status=?,
                sale_price=?, sale_date=?, tier=?, neighborhood=?, year_built=?, square_ft=?, parcel_class=?,
                upload_batch=?, source_file=?, added_date=?
                WHERE id=?"""
            params = (
                r['first_name'], r['last_name'], r['list_type'],
                r.get('permit_category'), r.get('permit_description'),
                r.get('permit_value'), r.get('permit_date'), r.get('permit_number'), r.get('permit_status'),
                r.get('sale_price'), r.get('sale_date'), r.get('tier'),
                r.get('neighborhood'), r.get('year_built'), r.get('square_ft'), r.get('parcel_class'),
                r['upload_batch'], r['source_file'], r['added_date'],
                existing_id
            )
            db_exec(db, sql, params)

        # Gap-fill patches — only update blank fields, never overwrite existing data
        for patch, existing_id in to_fill:
            set_clauses = ', '.join(f'{col}=?' for col in patch)
            vals = list(patch.values()) + [existing_id]
            db_exec(db, f'UPDATE master_addresses SET {set_clauses} WHERE id=?', vals)

        db.commit()
        if hasattr(db, 'close'):
            db.close()

        msg = f"✅ {len(to_insert):,} new addresses added, {len(to_update):,} updated"
        if to_fill:
            msg += f", {len(to_fill):,} existing records gap-filled"
        if skipped_lower_priority:
            msg += f" ({skipped_lower_priority:,} already complete — no new info)"
        if total_skipped:
            msg += f", {total_skipped:,} blank rows skipped"
        for w in all_warnings:
            flash(w, 'info')
        flash(msg, 'success')
        return redirect(url_for('admin.master_list'))

    except Exception as e:
        flash(f'Database error: {e}', 'error')
        if hasattr(db, 'close'):
            db.close()
        return redirect(url_for('admin.master_list_upload'))
