from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from inventory_flask_app.models import TenantSettings, db
from flask_wtf.csrf import CSRFError

admin_bp = Blueprint('admin_bp', __name__)

@admin_bp.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    if not current_user or not current_user.tenant_id:
        flash("Your account is not linked to any tenant. Please contact support.", "danger")
        return redirect(url_for('auth_bp.login'))

    tenant_id = current_user.tenant_id

    settings_keys = [
        'button_radius', 'column_order_instance_table', 'company_website', 'dashboard_logo',
        'dashboard_name', 'default_terms', 'enable_export_module', 'enable_order_module',
        'enable_parts_module', 'enable_reports_module', 'enable_csrf_protection',
        'label_disk1size', 'primary_color',
        'show_column_action', 'show_column_asset', 'show_column_cpu', 'show_column_display',
        'show_column_disk1size', 'show_column_grade', 'show_column_gpu1', 'show_column_gpu2',
        'show_column_is_sold', 'show_column_item_name', 'show_column_label', 'show_column_location',
        'show_column_make', 'show_column_model', 'show_column_process_stage', 'show_column_ram',
        'show_column_serial', 'show_column_shelf_bin', 'show_column_status', 'show_column_team',
        'show_column_vendor', 'sidebar_color', 'support_email', 'text_color',
        'idle_threshold_days', 'aged_threshold_days', 'tech_delay_threshold_days', 'order_delay_threshold_days'
    ]

    unified_column_order = [
        "asset", "serial", "item_name", "make", "model", "display",
        "cpu", "ram", "gpu1", "gpu2", "grade", "location",
        "status", "process_stage", "team", "shelf_bin",
        "is_sold", "label", "action"
    ]

    if request.method == 'POST':
        print("SAVED COLUMN ORDER:", request.form.get("column_order_instance_table"))
        for key in settings_keys:
            if key.startswith("enable_") or key.startswith("show_column_"):
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

    return render_template('admin_settings.html', settings=settings, users=users.items, tenant_timezone=tenant_timezone, pagination=users)

@admin_bp.app_errorhandler(CSRFError)
def handle_csrf_error(e):
    flash('The form session expired or CSRF token is missing.', 'danger')
    return redirect(url_for('admin_bp.admin_settings'))