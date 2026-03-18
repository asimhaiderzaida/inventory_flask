import logging
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from inventory_flask_app.models import TenantSettings, ProcessStage, CustomField, CustomFieldValue, db
from flask_wtf.csrf import CSRFError
from werkzeug.utils import secure_filename

admin_bp = Blueprint('admin_bp', __name__)

@admin_bp.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    if not current_user or not current_user.tenant_id:
        flash("Your account is not linked to any tenant. Please contact support.", "danger")
        return redirect(url_for('auth.login'))

    tenant_id = current_user.tenant_id

    settings_keys = [
        'button_radius', 'column_order_instance_table', 'company_address', 'company_email',
        'company_name', 'company_phone', 'company_website', 'currency', 'custom_css_url',
        'dashboard_logo', 'dashboard_name',
        'default_terms', 'enable_export_module', 'enable_order_module',
        'enable_parts_module', 'enable_reports_module',
        'font_size',
        'invoice_accent_color', 'invoice_bank_details', 'invoice_footer', 'invoice_footer_note',
        'invoice_header_note', 'invoice_logo', 'invoice_show_bank_details', 'invoice_show_logo',
        'invoice_terms', 'invoice_title',
        'label_asset', 'label_cpu', 'label_disk1size', 'label_display', 'label_grade',
        'label_gpu1', 'label_gpu2', 'label_item_name', 'label_location', 'label_make',
        'label_model', 'label_ram', 'label_serial_number', 'primary_color',
        'show_column_action', 'show_column_asset', 'show_column_cpu', 'show_column_display',
        'show_column_disk1size', 'show_column_grade', 'show_column_gpu1', 'show_column_gpu2',
        'show_column_is_sold', 'show_column_item_name', 'show_column_label', 'show_column_location',
        'show_column_make', 'show_column_model', 'show_column_process_stage', 'show_column_ram',
        'show_column_serial', 'show_column_shelf_bin', 'show_column_status', 'show_column_team',
        'show_column_vendor', 'sidebar_color', 'support_email',
        'idle_threshold_days', 'aged_threshold_days', 'tech_delay_threshold_days', 'order_delay_threshold_days',
        'enable_email_alerts', 'enable_low_stock_alerts', 'enable_sla_alerts', 'vat_rate',
        'email_tpl_reservation', 'email_tpl_ready', 'email_tpl_invoice', 'email_tpl_low_stock',
        'label_status_unprocessed', 'label_status_under_process', 'label_status_processed',
        'label_status_idle', 'label_status_disputed', 'label_status_sold',
        'processing_teams',
    ]

    unified_column_order = [
        "asset", "serial", "item_name", "make", "model", "display",
        "cpu", "ram", "gpu1", "gpu2", "grade", "location",
        "status", "process_stage", "team", "shelf_bin",
        "is_sold", "label", "action"
    ]

    if request.method == 'POST':
        logging.info(f"SAVED COLUMN ORDER: {request.form.get('column_order_instance_table')}")
        for key in settings_keys:
            if key.startswith("enable_") or key.startswith("show_column_") or key.startswith("invoice_show_"):
                value = 'true' if key in request.form else 'false'
            else:
                value = request.form.get(key)
            if value is not None:
                setting = TenantSettings.query.filter_by(tenant_id=tenant_id, key=key).first()
                if setting:
                    setting.value = value
                else:
                    setting = TenantSettings(tenant_id=tenant_id, key=key, value=value)
                    db.session.add(setting)

        # Update tenant timezone if provided
        timezone = request.form.get('timezone')
        if timezone:
            current_user.tenant.timezone = timezone

        db.session.commit()
        flash('Settings updated successfully.', 'success')
        return redirect(url_for('admin_bp.admin_settings'))

    existing_settings = TenantSettings.query.filter(TenantSettings.tenant_id == tenant_id).all()
    settings = {s.key: s.value for s in existing_settings}
    if 'column_order_instance_table' not in settings:
        settings['column_order_instance_table'] = ",".join(unified_column_order)

    from inventory_flask_app.models import User
    page = request.args.get('page', 1, type=int)
    users = User.query.filter_by(tenant_id=tenant_id).paginate(page=page, per_page=25)
    tenant_timezone = current_user.tenant.timezone
    custom_fields = CustomField.query.filter_by(tenant_id=tenant_id).order_by(CustomField.sort_order).all()

    return render_template('admin_settings.html', settings=settings, users=users.items,
                           tenant_timezone=tenant_timezone, pagination=users,
                           custom_fields=custom_fields)

@admin_bp.app_errorhandler(CSRFError)
def handle_csrf_error(e):
    flash('The form session expired or CSRF token is missing.', 'danger')
    return redirect(url_for('admin_bp.admin_settings'))


ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB


@admin_bp.route('/admin/upload_logo', methods=['POST'])
@login_required
def upload_logo():
    """Accept a logo image upload, save it, and store the path in TenantSettings."""
    tenant_id = current_user.tenant_id
    if not tenant_id:
        return jsonify({'error': 'No tenant'}), 400

    file = request.files.get('logo_file')
    if not file or file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('admin_bp.admin_settings'))

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_LOGO_EXTENSIONS:
        flash('Invalid file type. Allowed: PNG, JPG, GIF, WEBP, SVG.', 'danger')
        return redirect(url_for('admin_bp.admin_settings'))

    # Read into memory to check size before saving
    file_data = file.read()
    if len(file_data) > MAX_LOGO_SIZE:
        flash('File too large. Maximum size is 2 MB.', 'danger')
        return redirect(url_for('admin_bp.admin_settings'))

    logos_dir = os.path.join(current_app.root_path, 'static', 'img', 'logos')
    os.makedirs(logos_dir, exist_ok=True)

    filename = f"{tenant_id}_logo.{ext}"
    save_path = os.path.join(logos_dir, filename)
    with open(save_path, 'wb') as f:
        f.write(file_data)

    rel_path = f"/static/img/logos/{filename}"

    # Save to TenantSettings
    setting = TenantSettings.query.filter_by(tenant_id=tenant_id, key='dashboard_logo').first()
    if setting:
        setting.value = rel_path
    else:
        db.session.add(TenantSettings(tenant_id=tenant_id, key='dashboard_logo', value=rel_path))
    db.session.commit()

    flash('Logo uploaded successfully.', 'success')
    return redirect(url_for('admin_bp.admin_settings'))


import time

@admin_bp.route('/admin/self_test', methods=['GET'])
@login_required
def admin_self_test():
    """
    Comprehensive health check and smoke test.
    - Config sanity (CSRF/SECRET/DEBUG)
    - Core routes (inventory, sales, dashboard, etc.)
    - Grouped inventory vs. detail count consistency (top groups)
    - Sold/reserved exclusion consistency
    - Slow checks timing
    NOTE: Read-only. Does not modify data.
    """
    from sqlalchemy import func, or_
    from sqlalchemy.orm import aliased
    from inventory_flask_app.models import (
        db, Product, ProductInstance, Location, CustomerOrderTracking
    )

    app = current_app
    now_str = time.strftime('%Y-%m-%d %H:%M:%S')

    results = {
        'meta': {
            'tenant_id': getattr(current_user, 'tenant_id', None),
            'time': now_str,
        },
        'config': {},
        'routes': [],
        'assets': [],
        'problems': [],
        'group_checks': {
            'samples': [],
            'ok': True
        },
        'timing': []
    }

    # ---------------- Config checks ----------------
    csrf_enabled = bool(app.config.get('WTF_CSRF_ENABLED', False))
    secret_ok = bool(app.config.get('SECRET_KEY'))
    debug_mode = bool(app.config.get('DEBUG', False))

    results['config'] = {
        'csrf_enabled': csrf_enabled,
        'secret_key_present': secret_ok,
        'debug_mode': debug_mode,
    }
    if not csrf_enabled:
        results['problems'].append('CSRF protection is DISABLED')
    if not secret_ok:
        results['problems'].append('SECRET_KEY is missing')

    # ---------------- Asset checks (non-fatal) ----------------
    logo_rel = 'static/img/default_logo.png'
    logo_abs = os.path.join(app.root_path, logo_rel)
    results['assets'].append({'path': '/' + logo_rel, 'exists': os.path.exists(logo_abs)})
    if not os.path.exists(logo_abs):
        results['problems'].append(f'Missing asset: /{logo_rel}')

    # ---------------- Route smoke tests ----------------
    # Expand set but keep harmless if a route doesn't exist; we only report it.
    client = app.test_client()
    test_urls = [
        ('GET', '/'),
        ('GET', '/main_dashboard'),
        ('GET', '/stock/under_process?status=all'),
        ('GET', '/api/dashboard_stats'),
        # Best-effort extras (may not exist in every tenant/app flavor)
        ('GET', '/sales'),
        ('GET', '/sales/sold_units'),
        ('GET', '/customers/center'),
        ('GET', '/orders'),
        ('GET', '/reports'),
    ]
    for method, url in test_urls:
        t0 = time.perf_counter()
        try:
            resp = client.open(path=url, method=method)
            ok = (200 <= resp.status_code < 400)
            dt = (time.perf_counter() - t0) * 1000.0
            results['routes'].append({'url': url, 'method': method, 'status': resp.status_code, 'ok': ok, 'ms': round(dt, 1)})
            if not ok:
                results['problems'].append(f'{method} {url} returned {resp.status_code}')
        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000.0
            results['routes'].append({'url': url, 'method': method, 'status': 'ERR', 'ok': False, 'error': str(e), 'ms': round(dt, 1)})
            results['problems'].append(f'{method} {url} raised: {e}')

    # ---------------- Group vs Detail consistency ----------------
    # Match the same filters your "Under Process" table uses:
    #   - tenant scoped
    #   - exclude sold
    #   - exclude reserved
    #   - group by (model, cpu)
    tenant_id = getattr(current_user, 'tenant_id', None)
    if tenant_id:
        try:
            t0 = time.perf_counter()

            reserved = aliased(CustomerOrderTracking)

            base_q = (
                db.session.query(
                    Product.model.label('model'),
                    Product.cpu.label('cpu'),
                    func.count(ProductInstance.id).label('count')
                )
                .join(ProductInstance, ProductInstance.product_id == Product.id)
                .outerjoin(reserved, reserved.product_instance_id == ProductInstance.id)
                .filter(
                    Product.tenant_id == tenant_id,
                    ProductInstance.is_sold == False,
                    or_(reserved.id == None, reserved.status != 'reserved')
                )
                .group_by(Product.model, Product.cpu)
                .order_by(func.count(ProductInstance.id).desc(), Product.model.asc())
            )

            top_groups = base_q.limit(5).all()
            dt_group_query = (time.perf_counter() - t0) * 1000.0
            results['timing'].append({'name': 'group_query_top5', 'ms': round(dt_group_query, 1)})

            samples = []
            for g in top_groups:
                # Count again using the "detail" route logic (same filters) to compare
                t1 = time.perf_counter()
                detail_q = (
                    ProductInstance.query
                    .join(Product, Product.id == ProductInstance.product_id)
                    .outerjoin(reserved, reserved.product_instance_id == ProductInstance.id)
                    .filter(
                        Product.tenant_id == tenant_id,
                        Product.model == g.model,
                        Product.cpu == g.cpu,
                        ProductInstance.is_sold == False,
                        or_(reserved.id == None, reserved.status != 'reserved')
                    )
                )
                detail_count = detail_q.count()
                dt_detail = (time.perf_counter() - t1) * 1000.0

                match = (int(g.count or 0) == int(detail_count or 0))
                if not match:
                    results['problems'].append(
                        f'Group mismatch for [{g.model} / {g.cpu}] → grouped={g.count}, detail={detail_count}'
                    )
                    results['group_checks']['ok'] = False

                samples.append({
                    'model': g.model,
                    'cpu': g.cpu,
                    'group_count': int(g.count or 0),
                    'detail_count': int(detail_count or 0),
                    'ms_detail': round(dt_detail, 1)
                })

            results['group_checks']['samples'] = samples

        except Exception as e:
            results['problems'].append(f'Group vs detail check failed: {e}')

    # ---------------- Template sanity ----------------
    try:
        render_template('base.html')
    except Exception as e:
        results['problems'].append(f"Template base.html error: {e}")
    try:
        render_template('instance_table.html')
    except Exception as e:
        results['problems'].append(f"Template instance_table.html render warning: {e}")

    # JSON toggle (also if Accept: application/json)
    if request.args.get('json') == '1' or 'application/json' in (request.headers.get('Accept') or ''):
        return jsonify(results)

    return render_template('admin_self_test.html', results=results)


# ─────────────────────────────────────────────────────────────
# Processing Stages CRUD
# ─────────────────────────────────────────────────────────────

DEFAULT_STAGES = [
    ("Intake Check",   "#3b82f6", 48),
    ("Data Wipe",      "#8b5cf6", 24),
    ("Repair",         "#f59e0b", 72),
    ("QC Check",       "#10b981", 24),
    ("Packaging",      "#06b6d4", 8),
    ("Ready for Sale", "#22c55e", 0),
]


def _seed_default_stages(tenant_id):
    """Insert default stages for a tenant that has none."""
    for i, (name, color, sla) in enumerate(DEFAULT_STAGES):
        db.session.add(ProcessStage(name=name, order=i, color=color, sla_hours=sla, tenant_id=tenant_id))
    db.session.commit()


@admin_bp.route('/admin/stages')
@login_required
def admin_stages():
    stages = ProcessStage.query.filter_by(tenant_id=current_user.tenant_id).order_by(ProcessStage.order).all()
    if not stages:
        _seed_default_stages(current_user.tenant_id)
        stages = ProcessStage.query.filter_by(tenant_id=current_user.tenant_id).order_by(ProcessStage.order).all()
    return render_template('admin_stages.html', stages=stages)


@admin_bp.route('/admin/stages/add', methods=['POST'])
@login_required
def add_stage():
    name = (request.form.get('name') or '').strip()
    color = (request.form.get('color') or '#6b7280').strip()
    sla_hours = int(request.form.get('sla_hours') or 24)
    if not name:
        flash('Stage name is required.', 'danger')
        return redirect(url_for('admin_bp.admin_stages'))
    max_order = db.session.query(db.func.max(ProcessStage.order)).filter_by(tenant_id=current_user.tenant_id).scalar() or -1
    db.session.add(ProcessStage(name=name, color=color, sla_hours=sla_hours, order=max_order + 1, tenant_id=current_user.tenant_id))
    db.session.commit()
    flash(f'Stage "{name}" added.', 'success')
    return redirect(url_for('admin_bp.admin_stages'))


@admin_bp.route('/admin/stages/<int:stage_id>/edit', methods=['POST'])
@login_required
def edit_stage(stage_id):
    stage = ProcessStage.query.filter_by(id=stage_id, tenant_id=current_user.tenant_id).first_or_404()
    stage.name      = (request.form.get('name') or stage.name).strip()
    stage.color     = (request.form.get('color') or stage.color).strip()
    stage.sla_hours = int(request.form.get('sla_hours') or stage.sla_hours)
    db.session.commit()
    flash(f'Stage "{stage.name}" updated.', 'success')
    return redirect(url_for('admin_bp.admin_stages'))


@admin_bp.route('/admin/stages/<int:stage_id>/delete', methods=['POST'])
@login_required
def delete_stage(stage_id):
    stage = ProcessStage.query.filter_by(id=stage_id, tenant_id=current_user.tenant_id).first_or_404()
    name = stage.name
    db.session.delete(stage)
    db.session.commit()
    flash(f'Stage "{name}" deleted.', 'success')
    return redirect(url_for('admin_bp.admin_stages'))


@admin_bp.route('/admin/stages/reorder', methods=['POST'])
@login_required
def reorder_stages():
    """Accepts JSON list of {id, order} and updates order values."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, list):
        return jsonify({'error': 'Invalid payload'}), 400
    for item in data:
        stage = ProcessStage.query.filter_by(id=item.get('id'), tenant_id=current_user.tenant_id).first()
        if stage:
            stage.order = int(item.get('order', 0))
    db.session.commit()
    return jsonify({'ok': True})


# ─────────────────────────────────────────────────────────────
# Custom Fields CRUD
# ─────────────────────────────────────────────────────────────

import json as _json
import re as _re


def _slug(label):
    """Turn a label into a safe field_key slug."""
    return _re.sub(r'[^a-z0-9_]', '_', label.strip().lower())[:50]


@admin_bp.route('/admin/custom_fields/add', methods=['POST'])
@login_required
def add_custom_field():
    tenant_id = current_user.tenant_id
    label = (request.form.get('field_label') or '').strip()
    if not label:
        flash('Field label is required.', 'danger')
        return redirect(url_for('admin_bp.admin_settings') + '#collapseCustomFields')

    key = _slug(label)
    # Ensure uniqueness within tenant
    existing = CustomField.query.filter_by(tenant_id=tenant_id, field_key=key).first()
    if existing:
        flash(f'A field with key "{key}" already exists. Use a different label.', 'danger')
        return redirect(url_for('admin_bp.admin_settings') + '#collapseCustomFields')

    field_type = request.form.get('field_type', 'text')
    raw_options = (request.form.get('field_options') or '').strip()
    options_json = None
    if field_type == 'select' and raw_options:
        opts = [o.strip() for o in raw_options.split(',') if o.strip()]
        options_json = _json.dumps(opts)

    max_order = db.session.query(db.func.max(CustomField.sort_order)).filter_by(tenant_id=tenant_id).scalar() or -1
    cf = CustomField(
        tenant_id=tenant_id,
        field_key=key,
        field_label=label,
        field_type=field_type,
        field_options=options_json,
        is_required='is_required' in request.form,
        show_in_list='show_in_list' in request.form,
        show_in_invoice='show_in_invoice' in request.form,
        sort_order=max_order + 1,
    )
    db.session.add(cf)
    db.session.commit()
    flash(f'Custom field "{label}" added.', 'success')
    return redirect(url_for('admin_bp.admin_settings') + '#collapseCustomFields')


@admin_bp.route('/admin/custom_fields/<int:field_id>/edit', methods=['POST'])
@login_required
def edit_custom_field(field_id):
    cf = CustomField.query.filter_by(id=field_id, tenant_id=current_user.tenant_id).first_or_404()
    label = (request.form.get('field_label') or '').strip()
    if label:
        cf.field_label = label
    cf.field_type = request.form.get('field_type', cf.field_type)
    raw_options = (request.form.get('field_options') or '').strip()
    if cf.field_type == 'select' and raw_options:
        opts = [o.strip() for o in raw_options.split(',') if o.strip()]
        cf.field_options = _json.dumps(opts)
    elif cf.field_type != 'select':
        cf.field_options = None
    cf.is_required     = 'is_required' in request.form
    cf.show_in_list    = 'show_in_list' in request.form
    cf.show_in_invoice = 'show_in_invoice' in request.form
    db.session.commit()
    flash(f'Field "{cf.field_label}" updated.', 'success')
    return redirect(url_for('admin_bp.admin_settings') + '#collapseCustomFields')


@admin_bp.route('/admin/custom_fields/<int:field_id>/delete', methods=['POST'])
@login_required
def delete_custom_field(field_id):
    cf = CustomField.query.filter_by(id=field_id, tenant_id=current_user.tenant_id).first_or_404()
    label = cf.field_label
    db.session.delete(cf)
    db.session.commit()
    flash(f'Field "{label}" deleted.', 'success')
    return redirect(url_for('admin_bp.admin_settings') + '#collapseCustomFields')


@admin_bp.route('/admin/custom_fields/reorder', methods=['POST'])
@login_required
def reorder_custom_fields():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, list):
        return jsonify({'error': 'Invalid payload'}), 400
    for item in data:
        cf = CustomField.query.filter_by(id=item.get('id'), tenant_id=current_user.tenant_id).first()
        if cf:
            cf.sort_order = int(item.get('order', 0))
    db.session.commit()
    return jsonify({'ok': True})