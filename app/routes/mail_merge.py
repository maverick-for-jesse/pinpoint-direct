from flask import Blueprint, render_template, request, jsonify, send_file, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import os
import csv
import io
import json
from datetime import datetime
from functools import wraps

mail_merge_bp = Blueprint('mail_merge_bp', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'Admin':
            return jsonify({'success': False, 'error': 'Admin access required.'}), 403
        return f(*args, **kwargs)
    return decorated


ALLOWED_IMAGE_EXTS = {'png', 'jpg', 'jpeg'}
ALLOWED_CSV_EXTS = {'csv'}


def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTS


def allowed_csv(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_CSV_EXTS


@mail_merge_bp.route('/mail-merge')
@login_required
@admin_required
def mail_merge():
    return render_template('admin/mail_merge.html')


@mail_merge_bp.route('/mail-merge/upload-images', methods=['POST'])
@login_required
@admin_required
def upload_images():
    try:
        if 'front_image' not in request.files or 'back_image' not in request.files:
            return jsonify({'success': False, 'error': 'Both front_image and back_image are required.'}), 400

        front_file = request.files['front_image']
        back_file = request.files['back_image']

        if front_file.filename == '' or back_file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected.'}), 400

        if not allowed_image(front_file.filename):
            return jsonify({'success': False, 'error': 'Front image must be PNG or JPG.'}), 400
        if not allowed_image(back_file.filename):
            return jsonify({'success': False, 'error': 'Back image must be PNG or JPG.'}), 400

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)

        front_filename = f"{timestamp}_front_{secure_filename(front_file.filename)}"
        back_filename = f"{timestamp}_back_{secure_filename(back_file.filename)}"

        front_path = os.path.join(upload_folder, front_filename)
        back_path = os.path.join(upload_folder, back_filename)

        front_file.save(front_path)
        back_file.save(back_path)

        # Get back image dimensions
        from PIL import Image
        with Image.open(back_path) as img:
            back_width, back_height = img.size

        return jsonify({
            'success': True,
            'front_filename': front_filename,
            'back_filename': back_filename,
            'back_width': back_width,
            'back_height': back_height,
        })

    except Exception as e:
        import traceback
        return jsonify({'success': False, 'error': str(e), 'detail': traceback.format_exc()}), 500


@mail_merge_bp.route('/mail-merge/upload-csv', methods=['POST'])
@login_required
@admin_required
def upload_csv():
    try:
        if 'csv_file' not in request.files:
            return jsonify({'success': False, 'error': 'csv_file is required.'}), 400

        csv_file = request.files['csv_file']
        if csv_file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected.'}), 400
        if not allowed_csv(csv_file.filename):
            return jsonify({'success': False, 'error': 'File must be a CSV.'}), 400

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)

        csv_filename = f"{timestamp}_{secure_filename(csv_file.filename)}"
        csv_path = os.path.join(upload_folder, csv_filename)
        csv_file.save(csv_path)

        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames or []
            preview = []
            count = 0
            for row in reader:
                count += 1
                if count <= 3:
                    preview.append(dict(row))

        return jsonify({
            'success': True,
            'columns': list(columns),
            'preview': preview,
            'count': count,
            'csv_filename': csv_filename,
        })

    except Exception as e:
        import traceback
        return jsonify({'success': False, 'error': str(e), 'detail': traceback.format_exc()}), 500


@mail_merge_bp.route('/mail-merge/generate', methods=['POST'])
@login_required
@admin_required
def generate():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'JSON body required.'}), 400

        front_filename = data.get('front_filename')
        back_filename = data.get('back_filename')
        csv_filename = data.get('csv_filename')
        address_zone = data.get('address_zone')  # {x_pct, y_pct, w_pct, h_pct}
        column_map = data.get('column_map')  # {name, title, org, address, city, state, zip, plus4}

        if not all([front_filename, back_filename, csv_filename, address_zone, column_map]):
            return jsonify({'success': False, 'error': 'Missing required fields.'}), 400

        upload_folder = current_app.config['UPLOAD_FOLDER']
        export_folder = current_app.config['EXPORT_FOLDER']
        os.makedirs(export_folder, exist_ok=True)

        front_path = os.path.join(upload_folder, secure_filename(front_filename))
        back_path = os.path.join(upload_folder, secure_filename(back_filename))
        csv_path = os.path.join(upload_folder, secure_filename(csv_filename))

        for path, label in [(front_path, 'Front image'), (back_path, 'Back image'), (csv_path, 'CSV file')]:
            if not os.path.exists(path):
                return jsonify({'success': False, 'error': f'{label} not found.'}), 400

        # Load records from CSV
        records = []
        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(dict(row))

        if not records:
            return jsonify({'success': False, 'error': 'CSV has no records.'}), 400

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        output_filename = f"mail_merge_{timestamp}.pdf"
        output_path = os.path.join(export_folder, output_filename)

        from app.utils.mail_merge_pdf import generate_mail_merge_pdf
        generate_mail_merge_pdf(
            front_image_path=front_path,
            back_image_path=back_path,
            records=records,
            address_zone=address_zone,
            column_map=column_map,
            output_path=output_path,
        )

        import math
        sheet_count = math.ceil(len(records) / 2)
        page_count = sheet_count * 2

        return jsonify({
            'success': True,
            'download_url': f'/admin/mail-merge/download/{output_filename}',
            'filename': output_filename,
            'sheet_count': sheet_count,
            'page_count': page_count,
            'record_count': len(records),
        })

    except Exception as e:
        import traceback
        return jsonify({'success': False, 'error': str(e), 'detail': traceback.format_exc()}), 500


@mail_merge_bp.route('/mail-merge/download/<filename>')
@login_required
@admin_required
def download(filename):
    export_folder = current_app.config['EXPORT_FOLDER']
    safe_name = secure_filename(filename)
    file_path = os.path.join(export_folder, safe_name)

    if not os.path.exists(file_path):
        return jsonify({'success': False, 'error': 'File not found.'}), 404

    return send_file(file_path, as_attachment=True, download_name=safe_name, mimetype='application/pdf')


@mail_merge_bp.route('/mail-merge/preview-image/<filename>')
@login_required
@admin_required
def preview_image(filename):
    """Serve an uploaded image file for the zone picker preview."""
    upload_folder = current_app.config['UPLOAD_FOLDER']
    safe_name = secure_filename(filename)
    file_path = os.path.join(upload_folder, safe_name)

    if not os.path.exists(file_path):
        return jsonify({'success': False, 'error': 'Image not found.'}), 404

    ext = safe_name.rsplit('.', 1)[-1].lower()
    mime = 'image/jpeg' if ext in ('jpg', 'jpeg') else 'image/png'
    return send_file(file_path, mimetype=mime)
