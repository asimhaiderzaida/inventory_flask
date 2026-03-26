import csv
import io
import logging
import os
import time
import zipfile
from datetime import datetime
from io import BytesIO

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file
from flask_login import login_required, current_user
from inventory_flask_app.models import (
    TenantSettings, ProcessStage, CustomField, CustomFieldValue,
    db, UserPermission, MODULES,
    ProductInstance, Product,
    SaleTransaction, SaleItem, Invoice, Order,
    Customer, CustomerOrderTracking,
    Vendor,
    Part, PartUsage, PartSale, PartSaleTransaction, PartSaleItem,
    PurchaseOrder,
    Expense, AccountReceivable, ARPayment, OtherIncome, CreditNote,
    ProductProcessLog, Return, User,
)
from flask_wtf.csrf import CSRFError
from werkzeug.utils import secure_filename
from inventory_flask_app import csrf
from inventory_flask_app.utils.utils import admin_required

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin_bp', __name__)

@admin_bp.route('/admin/settings', methods=['GET', 'POST'])
@login_required
@admin_required
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
        'company_trn',
        'invoice_accent_color', 'invoice_bank_details', 'invoice_footer', 'invoice_footer_note',
        'invoice_header_note', 'invoice_logo', 'invoice_show_bank_details', 'invoice_show_logo',
        'invoice_terms', 'invoice_title',
        'invoice_type_label', 'invoice_layout', 'invoice_logo_position',
        'invoice_show_buyer_trn', 'invoice_show_po_reference', 'invoice_show_supply_date',
        'invoice_show_due_date', 'invoice_show_delivery_address', 'invoice_show_serial',
        'invoice_show_asset', 'invoice_show_specs', 'invoice_show_grade', 'invoice_show_qty_column',
        'invoice_show_discount', 'invoice_show_payment_method', 'invoice_show_qr',
        'invoice_signature_line', 'invoice_signature_labels', 'invoice_watermark',
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
        'enable_email_alerts', 'enable_low_stock_alerts', 'enable_sla_alerts',
        'enable_automated_alerts', 'enable_aged_inventory_alerts', 'enable_ar_overdue_alerts', 'vat_rate',
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


ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB


@admin_bp.route('/admin/upload_logo', methods=['POST'])
@login_required
@admin_required
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


@admin_bp.route('/admin/label_template', methods=['GET', 'POST'])
@login_required
@admin_required
def label_template():
    """Configure barcode/QR label layout."""
    tid = current_user.tenant_id

    defaults = {
        'label_format': 'qr',
        'label_width_mm': '50',
        'label_height_mm': '30',
        'label_show_logo': 'false',
        'label_show_serial': 'true',
        'label_show_asset': 'true',
        'label_show_model': 'true',
        'label_show_make': 'false',
        'label_show_cpu': 'false',
        'label_show_ram': 'false',
        'label_show_grade': 'false',
        'label_show_location': 'false',
        'label_show_company_name': 'true',
        'label_font_size': '9',
        'label_code_size': '120',
        'label_title_text': '',
    }

    rows = TenantSettings.query.filter(
        TenantSettings.tenant_id == tid,
        TenantSettings.key.like('label_%')
    ).all()
    current_cfg = {r.key: r.value for r in rows}
    config = {**defaults, **current_cfg}

    if request.method == 'POST':
        for key in defaults:
            if key.startswith('label_show_'):
                val = 'true' if request.form.get(key) else 'false'
            else:
                val = request.form.get(key, '').strip()
            setting = TenantSettings.query.filter_by(tenant_id=tid, key=key).first()
            if setting:
                setting.value = val
            else:
                db.session.add(TenantSettings(tenant_id=tid, key=key, value=val))
        db.session.commit()
        flash('Label template saved.', 'success')
        return redirect(url_for('admin_bp.label_template'))

    # Retrieve logo path for preview
    logo_row = TenantSettings.query.filter_by(tenant_id=tid, key='dashboard_logo').first()
    logo_path = logo_row.value if logo_row else None
    company_row = TenantSettings.query.filter_by(tenant_id=tid, key='company_name').first()
    company_name = company_row.value if company_row else ''

    return render_template('admin_label_template.html',
                           config=config, logo_path=logo_path, company_name=company_name)


@admin_bp.route('/admin/invoice_designer', methods=['GET', 'POST'])
@login_required
@admin_required
def invoice_designer():
    """Configure invoice layout, fields, and FTA compliance settings."""
    tid = current_user.tenant_id

    defaults = {
        'company_trn': '',
        'invoice_type_label': 'Tax Invoice',
        'invoice_layout': 'standard',
        'invoice_logo_position': 'left',
        'invoice_accent_color': '#3B82F6',
        'invoice_show_logo': 'true',
        'invoice_show_buyer_trn': 'true',
        'invoice_show_po_reference': 'false',
        'invoice_show_supply_date': 'false',
        'invoice_show_due_date': 'false',
        'invoice_show_delivery_address': 'false',
        'invoice_show_serial': 'true',
        'invoice_show_asset': 'true',
        'invoice_show_specs': 'true',
        'invoice_show_grade': 'false',
        'invoice_show_qty_column': 'true',
        'invoice_show_discount': 'false',
        'invoice_show_payment_method': 'true',
        'invoice_show_qr': 'false',
        'invoice_show_bank_details': 'false',
        'invoice_signature_line': 'false',
        'invoice_signature_labels': 'Authorized Signature,Customer Signature',
        'invoice_watermark': '',
        'invoice_header_note': '',
        'invoice_footer': '',
        'invoice_footer_note': '',
        'invoice_terms': '',
        'invoice_bank_details': '',
        'vat_rate': '5',
    }

    all_rows = TenantSettings.query.filter_by(tenant_id=tid).all()
    current_cfg = {r.key: r.value for r in all_rows}
    extra_keys = ('company_name', 'company_address', 'company_phone', 'company_email',
                  'company_website', 'currency', 'dashboard_logo', 'invoice_logo', 'invoice_title')
    config = {**defaults, **{k: v for k, v in current_cfg.items() if k in defaults or k in extra_keys}}

    if request.method == 'POST':
        for key in defaults:
            checkbox_keys = {k for k in defaults if k.startswith('invoice_show_')} | {'invoice_signature_line'}
            if key in checkbox_keys:
                val = 'true' if request.form.get(key) else 'false'
            else:
                val = request.form.get(key, '').strip()
            setting = TenantSettings.query.filter_by(tenant_id=tid, key=key).first()
            if setting:
                setting.value = val
            else:
                db.session.add(TenantSettings(tenant_id=tid, key=key, value=val))
        db.session.commit()
        flash('Invoice template saved.', 'success')
        return redirect(url_for('admin_bp.invoice_designer'))

    return render_template('admin_invoice_designer.html', config=config)


@admin_bp.route('/admin/self_test', methods=['GET'])
@login_required
@admin_required
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
    csrf_enabled = bool(app.config.get('WTF_CSRF_ENABLED', True))
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
@admin_required
def admin_stages():
    stages = ProcessStage.query.filter_by(tenant_id=current_user.tenant_id).order_by(ProcessStage.order).all()
    if not stages:
        _seed_default_stages(current_user.tenant_id)
        stages = ProcessStage.query.filter_by(tenant_id=current_user.tenant_id).order_by(ProcessStage.order).all()
    return render_template('admin_stages.html', stages=stages)


@admin_bp.route('/admin/stages/add', methods=['POST'])
@login_required
@admin_required
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
@admin_required
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
@admin_required
def delete_stage(stage_id):
    stage = ProcessStage.query.filter_by(id=stage_id, tenant_id=current_user.tenant_id).first_or_404()
    name = stage.name
    db.session.delete(stage)
    db.session.commit()
    flash(f'Stage "{name}" deleted.', 'success')
    return redirect(url_for('admin_bp.admin_stages'))


@admin_bp.route('/admin/stages/reorder', methods=['POST'])
@login_required
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
def delete_custom_field(field_id):
    cf = CustomField.query.filter_by(id=field_id, tenant_id=current_user.tenant_id).first_or_404()
    label = cf.field_label
    db.session.delete(cf)
    db.session.commit()
    flash(f'Field "{label}" deleted.', 'success')
    return redirect(url_for('admin_bp.admin_settings') + '#collapseCustomFields')


@admin_bp.route('/admin/custom_fields/reorder', methods=['POST'])
@login_required
@admin_required
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


# ─────────────────────────────────────────────────────────────
# Per-User Permission Editor
# ─────────────────────────────────────────────────────────────

MODULE_DESCRIPTIONS = {
    'dashboard':    'Overview, KPIs, and sales charts',
    'sales':        'Create sales, view sold items, invoices',
    'parts':        'Parts inventory, stock levels, sales',
    'stock':        'Intake, scanning, bin locations',
    'processing':   'Process pipeline, stage assignments',
    'customers':    'Customer records and profiles',
    'vendors':      'Vendor records and profiles',
    'accounting':   'Expenses, receivables, P&L, cash flow',
    'reports':      'All reports and data exports',
    'returns':      'Return processing and credit notes',
    'locations':    'Warehouse locations and bin management',
    'orders':       'Customer orders and tracking',
    'reservations': 'Unit reservations and delivery',
    'shopify':      'Shopify listings, sync, and orders',
    'admin':        'Tenant settings and user management',
}


@admin_bp.route('/admin/users/<int:user_id>/permissions', methods=['GET', 'POST'])
@login_required
@admin_required
def user_permissions(user_id):
    from inventory_flask_app.models import User
    user = User.query.filter_by(id=user_id, tenant_id=current_user.tenant_id).first_or_404()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'reset':
            # Clear all custom permissions — revert to role defaults
            UserPermission.query.filter_by(
                user_id=user.id, tenant_id=current_user.tenant_id
            ).delete()
            db.session.commit()
            flash(f'Permissions for {user.username} reset to role defaults.', 'success')
        else:
            # Save each module's access level
            for module_key, _ in MODULES:
                level = request.form.get(f'perm_{module_key}', 'none')
                if level not in ('none', 'view', 'full'):
                    level = 'none'
                perm = UserPermission.query.filter_by(
                    user_id=user.id, module=module_key
                ).first()
                if perm:
                    perm.access_level = level
                else:
                    db.session.add(UserPermission(
                        user_id=user.id,
                        tenant_id=current_user.tenant_id,
                        module=module_key,
                        access_level=level,
                    ))
            db.session.commit()
            flash(f'Permissions saved for {user.username}.', 'success')
        return redirect(url_for('admin_bp.user_permissions', user_id=user.id))

    return render_template(
        'user_permissions.html',
        user=user,
        MODULES=MODULES,
        module_descriptions=MODULE_DESCRIPTIONS,
    )


# ─────────────────────────────────────────────────────────────
# Backup & Factory Reset
# ─────────────────────────────────────────────────────────────

@admin_bp.route('/admin/backup/download')
@login_required
@admin_required
def download_backup():
    tid = current_user.tenant_id
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:

        # 1. inventory_units.csv
        rows = (db.session.query(ProductInstance, Product)
                .join(Product, ProductInstance.product_id == Product.id)
                .filter(ProductInstance.tenant_id == tid).all())
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['Serial', 'Asset Tag', 'Make', 'Model', 'Item Name',
                    'CPU', 'RAM', 'Disk', 'Display', 'GPU1', 'Grade',
                    'Status', 'Location', 'Asking Price', 'Is Sold',
                    'Created At', 'PO Number'])
        for inst, prod in rows:
            w.writerow([
                inst.serial, inst.asset, prod.make, prod.model,
                prod.item_name, prod.cpu, prod.ram, prod.disk1size,
                prod.display, prod.gpu1, prod.grade, inst.status,
                inst.location.name if inst.location else '',
                inst.asking_price, inst.is_sold,
                inst.created_at.strftime('%Y-%m-%d') if inst.created_at else '',
                inst.po.po_number if inst.po else '',
            ])
        zf.writestr('inventory_units.csv', buf.getvalue())

        # 2. sales_invoices.csv
        sales = (SaleTransaction.query
                 .join(Invoice, SaleTransaction.invoice_id == Invoice.id)
                 .filter(Invoice.tenant_id == tid).all())
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['Invoice #', 'Date', 'Customer', 'Serial', 'Model',
                    'Sale Price', 'Payment Method', 'Status'])
        for s in sales:
            w.writerow([
                s.invoice.invoice_number if s.invoice else '',
                s.date_sold.strftime('%Y-%m-%d') if s.date_sold else '',
                s.customer.name if s.customer else '',
                s.product_instance.serial if s.product_instance else '',
                (s.product_instance.product.model
                 if s.product_instance and s.product_instance.product else ''),
                s.price_at_sale, s.payment_method, s.payment_status,
            ])
        zf.writestr('sales_invoices.csv', buf.getvalue())

        # 3. customers.csv
        customers = Customer.query.filter_by(tenant_id=tid).all()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['Name', 'Email', 'Phone', 'Company', 'Address',
                    'City', 'Country', 'Created At'])
        for c in customers:
            w.writerow([c.name, c.email, c.phone, c.company,
                        c.address, c.city, c.country,
                        c.created_at.strftime('%Y-%m-%d') if c.created_at else ''])
        zf.writestr('customers.csv', buf.getvalue())

        # 4. vendors.csv
        vendors = Vendor.query.filter_by(tenant_id=tid).all()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['Name', 'Email', 'Phone', 'Website', 'City',
                    'Country', 'Payment Terms', 'Notes'])
        for v in vendors:
            w.writerow([v.name, v.email, v.phone, v.website,
                        v.city, v.country, v.payment_terms, v.notes])
        zf.writestr('vendors.csv', buf.getvalue())

        # 5. parts.csv
        parts = Part.query.filter_by(tenant_id=tid).all()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['Part Number', 'Name', 'Type', 'Vendor',
                    'Description', 'Total Stock', 'Min Stock', 'Price', 'Barcode'])
        for p in parts:
            stock_total = sum(s.quantity for s in p.stocks)
            w.writerow([p.part_number, p.name, p.part_type, p.vendor,
                        p.description, stock_total, p.min_stock,
                        p.price, p.barcode])
        zf.writestr('parts.csv', buf.getvalue())

        # 6. purchase_orders.csv
        pos = PurchaseOrder.query.filter_by(tenant_id=tid).all()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['PO Number', 'Vendor', 'Status', 'Location',
                    'Units Expected', 'Units Received', 'Created At', 'Notes'])
        for po in pos:
            total    = po.items.count()
            received = po.items.filter_by(status='received').count()
            w.writerow([
                po.po_number,
                po.vendor.name if po.vendor else '',
                po.status,
                po.location.name if po.location else '',
                total, received,
                po.created_at.strftime('%Y-%m-%d') if po.created_at else '',
                po.notes,
            ])
        zf.writestr('purchase_orders.csv', buf.getvalue())

        # 7. accounting_expenses.csv
        expenses = Expense.query.filter_by(tenant_id=tid).all()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['Date', 'Category', 'Description', 'Amount',
                    'Payment Method', 'Reference'])
        for e in expenses:
            w.writerow([
                e.expense_date.strftime('%Y-%m-%d') if e.expense_date else '',
                e.category.name if e.category else '',
                e.description, e.amount,
                e.payment_method, e.reference,
            ])
        zf.writestr('accounting_expenses.csv', buf.getvalue())

        # 8. accounting_ar.csv
        ars = AccountReceivable.query.filter_by(tenant_id=tid).all()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['Customer', 'Invoice #', 'Amount Due', 'Amount Paid',
                    'Balance', 'Due Date', 'Status'])
        for ar in ars:
            w.writerow([
                ar.customer.name if ar.customer else '',
                ar.invoice.invoice_number if ar.invoice else '',
                ar.amount_due, ar.amount_paid, ar.balance,
                ar.due_date.strftime('%Y-%m-%d') if ar.due_date else '',
                ar.status,
            ])
        zf.writestr('accounting_ar.csv', buf.getvalue())

        # 9. backup_info.txt
        zf.writestr('backup_info.txt', (
            f"Backup\n"
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Tenant: {current_user.tenant.name}\n\n"
            f"Record Counts:\n"
            f"- Inventory Units: {len(rows)}\n"
            f"- Sales: {len(sales)}\n"
            f"- Customers: {len(customers)}\n"
            f"- Vendors: {len(vendors)}\n"
            f"- Parts: {len(parts)}\n"
            f"- Purchase Orders: {len(pos)}\n"
            f"- Expenses: {len(expenses)}\n"
            f"- AR Records: {len(ars)}\n"
        ))

    zip_buffer.seek(0)
    filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return send_file(zip_buffer, mimetype='application/zip',
                     as_attachment=True, download_name=filename)


@admin_bp.route('/admin/reset/confirm', methods=['POST'])
@login_required
@admin_required
def confirm_reset():
    csrf.protect()
    if request.form.get('confirm_text', '').strip() != 'RESET':
        flash('You must type RESET exactly to confirm.', 'danger')
        return redirect(url_for('admin_bp.admin_settings') + '#sec-data')

    sel = {
        'inventory':  'reset_inventory'  in request.form,
        'sales':      'reset_sales'      in request.form,
        'customers':  'reset_customers'  in request.form,
        'vendors':    'reset_vendors'    in request.form,
        'parts':      'reset_parts'      in request.form,
        'pos':        'reset_pos'        in request.form,
        'accounting': 'reset_accounting' in request.form,
        'processing': 'reset_processing' in request.form,
        'users':      'reset_users'      in request.form,
        'settings':   'reset_settings'   in request.form,
    }

    if not any(sel.values()):
        flash('Select at least one category to reset.', 'warning')
        return redirect(url_for('admin_bp.admin_settings') + '#sec-data')

    try:
        _execute_reset(current_user.tenant_id, current_user.id, sel)
        labels = [k.replace('_', ' ').title() for k, v in sel.items() if v]
        flash(f'Factory reset complete. Cleared: {", ".join(labels)}.', 'success')
        logger.warning(
            'Factory reset by user %s (tenant %s): %s',
            current_user.username, current_user.tenant_id, ', '.join(labels)
        )
    except Exception as e:
        db.session.rollback()
        logger.error('Factory reset error tenant %s: %s', current_user.tenant_id, e)
        flash(f'Reset failed: {e}', 'danger')

    return redirect(url_for('dashboard_bp.main_dashboard'))


def _execute_reset(tid, uid, sel):
    """Delete tenant data in FK-safe order based on selections."""

    # ── 1. Accounting leaf nodes (must precede AccountReceivable/Return) ──
    if sel['accounting']:
        ARPayment.query.filter_by(tenant_id=tid).delete()
        CreditNote.query.filter_by(tenant_id=tid).delete()

    # ── 2. Return records (cross-referenced by inventory / sales / parts) ─
    if sel['inventory'] or sel['sales'] or sel['parts']:
        Return.query.filter_by(tenant_id=tid).delete()

    # ── 3. Processing history ─────────────────────────────────────────────
    if sel['processing']:
        pi_sq = db.session.query(ProductInstance.id).filter_by(tenant_id=tid).subquery()
        ProductProcessLog.query.filter(
            ProductProcessLog.product_instance_id.in_(pi_sq)
        ).delete(synchronize_session=False)

    # ── 4. Accounting parent records ──────────────────────────────────────
    if sel['accounting']:
        AccountReceivable.query.filter_by(tenant_id=tid).delete()
        Expense.query.filter_by(tenant_id=tid).delete()
        OtherIncome.query.filter_by(tenant_id=tid).delete()

    # ── 5. Parts (PartSaleTransaction cascade → PartSaleItem) ────────────
    if sel['parts']:
        PartSaleTransaction.query.filter_by(tenant_id=tid).delete()   # cascades PartSaleItem
        PartUsage.query.filter_by(tenant_id=tid).delete()
        PartSale.query.filter_by(tenant_id=tid).delete()
        Part.query.filter_by(tenant_id=tid).delete()                  # cascades PartMovement, PartStock

    # ── 6. Sales (SaleTransaction cascade → SaleItem) ────────────────────
    if sel['sales']:
        pi_sq = db.session.query(ProductInstance.id).filter_by(tenant_id=tid).subquery()
        SaleTransaction.query.filter(
            SaleTransaction.product_instance_id.in_(pi_sq)
        ).delete(synchronize_session=False)                            # cascades SaleItem
        Invoice.query.filter_by(tenant_id=tid).delete()
        Order.query.filter_by(tenant_id=tid).delete()

    # ── 7. Purchase Orders (cascade → PurchaseOrderItem, POImportLog) ────
    if sel['pos']:
        PurchaseOrder.query.filter_by(tenant_id=tid).delete()

    # ── 8. Inventory (cascade → SaleTransaction, ProductProcessLog,
    #                  CustomerOrderTracking, CustomFieldValue) ───────────
    if sel['inventory']:
        ProductInstance.query.filter_by(tenant_id=tid).delete()
        Product.query.filter_by(tenant_id=tid).delete()

    # ── 9. Customers (cascade → CustomerNote, CustomerCommunication,
    #                  CustomerOrderTracking) ────────────────────────────
    if sel['customers']:
        Customer.query.filter_by(tenant_id=tid).delete()

    # ── 10. Vendors (cascade → VendorNote) ───────────────────────────────
    if sel['vendors']:
        Vendor.query.filter_by(tenant_id=tid).delete()

    # ── 11. Users (except current admin) ─────────────────────────────────
    if sel['users']:
        UserPermission.query.filter_by(tenant_id=tid).delete()
        User.query.filter(
            User.tenant_id == tid, User.id != uid
        ).delete(synchronize_session=False)

    # ── 12. Settings ──────────────────────────────────────────────────────
    if sel['settings']:
        TenantSettings.query.filter_by(tenant_id=tid).delete()
        ProcessStage.query.filter_by(tenant_id=tid).delete()
        CustomField.query.filter_by(tenant_id=tid).delete()           # cascade → CustomFieldValue

    db.session.commit()