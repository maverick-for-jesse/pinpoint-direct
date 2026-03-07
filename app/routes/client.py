from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.utils.airtable import get_records, get_record, update_record
from functools import wraps

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

    active_statuses = ('Artwork Pending','Artwork Approved','Mailing Approval Pending',
                       'Mailing Approved','In Production')
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
        if c['fields'].get('Status') in ('Artwork Pending','Mailing Approval Pending')
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
                           unpaid_invoices=unpaid_invoices[:3])


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

    # Campaigns needing mailing approval
    mailing_pending = [c for c in campaigns
                       if c['fields'].get('Status') == 'Mailing Approval Pending']

    return render_template('client/approvals.html',
                           artwork_pending=artwork_pending,
                           mailing_pending=mailing_pending)


@client_bp.route('/approvals/artwork/<record_id>', methods=['POST'])
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


@client_bp.route('/approvals/mailing/<record_id>', methods=['POST'])
@login_required
@client_required
def mailing_approve(record_id):
    decision = request.form.get('decision', 'approve')

    if decision == 'approve':
        update_record('campaigns', record_id, {'Status': 'Mailing Approved'})
        # Auto-create print job
        campaign = get_record('campaigns', record_id)
        f = campaign['fields']
        from app.utils.airtable import create_record
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


# ── Invoices ──────────────────────────────────────────────────────────────────

@client_bp.route('/invoices')
@login_required
@client_required
def invoices():
    invoices = get_client_invoices()
    return render_template('client/invoices.html', invoices=invoices)


@client_bp.route('/invoices/<record_id>')
@login_required
@client_required
def invoice_detail(record_id):
    invoice = get_record('invoices', record_id)
    # Security: make sure this invoice belongs to this client
    if invoice['fields'].get('Client') != client_name():
        flash('Invoice not found.', 'error')
        return redirect(url_for('client.invoices'))
    return render_template('client/invoice_detail.html', invoice=invoice)
