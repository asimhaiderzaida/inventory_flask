"""Super Admin routes — platform management above all tenants."""
import logging
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session
from flask_login import login_required, login_user, current_user
from inventory_flask_app.models import db, Tenant, User, TenantSettings, ProductInstance, Product

logger = logging.getLogger(__name__)

superadmin_bp = Blueprint('superadmin_bp', __name__, url_prefix='/superadmin')


def superadmin_required(f):
    """Decorator: only super admin users may access."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not current_user.is_superadmin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@superadmin_bp.route('/')
@login_required
@superadmin_required
def dashboard():
    """Super admin dashboard — overview of all tenants."""
    tenants = Tenant.query.filter(Tenant.name != '__system__').order_by(Tenant.name).all()

    tenant_stats = []
    for tenant in tenants:
        user_count = User.query.filter_by(tenant_id=tenant.id, is_superadmin=False).count()
        unit_count = (
            ProductInstance.query.join(Product)
            .filter(Product.tenant_id == tenant.id)
            .count()
        )
        admin_user = User.query.filter_by(
            tenant_id=tenant.id, role='admin', is_superadmin=False
        ).first()
        last_active_user = (
            User.query
            .filter_by(tenant_id=tenant.id)
            .filter(User.last_login_at.isnot(None))
            .order_by(User.last_login_at.desc())
            .first()
        )
        tenant_stats.append({
            'tenant': tenant,
            'user_count': user_count,
            'unit_count': unit_count,
            'admin_user': admin_user,
            'last_activity': last_active_user.last_login_at if last_active_user else None,
        })

    total_tenants = len(tenants)
    total_users = User.query.filter_by(is_superadmin=False).count()
    total_units = ProductInstance.query.count()

    public_reg = TenantSettings.query.filter_by(key='allow_public_registration').first()
    registration_open = not public_reg or public_reg.value != 'false'

    return render_template('superadmin/dashboard.html',
        tenant_stats=tenant_stats,
        total_tenants=total_tenants,
        total_users=total_users,
        total_units=total_units,
        registration_open=registration_open,
    )


@superadmin_bp.route('/toggle_registration', methods=['POST'])
@login_required
@superadmin_required
def toggle_registration():
    """Enable or disable public tenant registration."""
    setting = TenantSettings.query.filter_by(key='allow_public_registration').first()
    if not setting:
        system_tenant = Tenant.query.filter_by(name='__system__').first()
        tid = system_tenant.id if system_tenant else 1
        setting = TenantSettings(tenant_id=tid, key='allow_public_registration', value='true')
        db.session.add(setting)
    setting.value = 'false' if setting.value != 'false' else 'true'
    db.session.commit()
    status = "enabled" if setting.value == 'true' else "disabled"
    flash(f"Public registration {status}.", "success")
    return redirect(url_for('superadmin_bp.dashboard'))


@superadmin_bp.route('/toggle_tenant/<int:tenant_id>', methods=['POST'])
@login_required
@superadmin_required
def toggle_tenant(tenant_id):
    """Enable or disable a tenant."""
    tenant = Tenant.query.get_or_404(tenant_id)
    if tenant.name == '__system__':
        flash("Cannot modify the system tenant.", "danger")
        return redirect(url_for('superadmin_bp.dashboard'))
    tenant.is_active = not tenant.is_active
    db.session.commit()
    status = "enabled" if tenant.is_active else "disabled"
    flash(f"Tenant '{tenant.name}' {status}.", "success")
    return redirect(url_for('superadmin_bp.dashboard'))


@superadmin_bp.route('/create_tenant', methods=['GET', 'POST'])
@login_required
@superadmin_required
def create_tenant():
    """Create a new tenant with an admin user."""
    if request.method == 'POST':
        tenant_name = request.form.get('tenant_name', '').strip()
        admin_username = request.form.get('admin_username', '').strip()
        admin_password = request.form.get('admin_password', '').strip()
        admin_email = request.form.get('admin_email', '').strip().lower()

        if not tenant_name or not admin_username or not admin_password or not admin_email:
            flash("All fields are required.", "danger")
            return render_template('superadmin/create_tenant.html')

        if len(admin_password) < 8:
            flash("Password must be at least 8 characters.", "warning")
            return render_template('superadmin/create_tenant.html')

        if Tenant.query.filter_by(name=tenant_name).first():
            flash(f"A tenant named '{tenant_name}' already exists.", "danger")
            return render_template('superadmin/create_tenant.html')

        if User.query.filter_by(username=admin_username).first():
            flash(f"Username '{admin_username}' is already taken.", "danger")
            return render_template('superadmin/create_tenant.html')

        from sqlalchemy import func as _func
        if User.query.filter(_func.lower(User.email) == admin_email).first():
            flash(f"Email '{admin_email}' is already in use.", "danger")
            return render_template('superadmin/create_tenant.html')

        try:
            from werkzeug.security import generate_password_hash
            from .admin import _seed_default_stages

            tenant = Tenant(name=tenant_name)
            db.session.add(tenant)
            db.session.flush()

            db.session.add_all([
                TenantSettings(tenant_id=tenant.id, key='dashboard_name', value=f"{tenant_name} Dashboard"),
                TenantSettings(tenant_id=tenant.id, key='dashboard_logo', value='/static/img/default_logo.png'),
            ])

            admin_user = User(
                username=admin_username,
                email=admin_email,
                password_hash=generate_password_hash(admin_password),
                role='admin',
                tenant_id=tenant.id,
            )
            db.session.add(admin_user)
            db.session.commit()
            _seed_default_stages(tenant.id)

            flash(f"Tenant '{tenant_name}' created with admin user '{admin_username}'.", "success")
            return redirect(url_for('superadmin_bp.dashboard'))
        except Exception as e:
            db.session.rollback()
            logger.error("Failed to create tenant: %s", e)
            flash(f"Failed to create tenant: {e}", "danger")
            return render_template('superadmin/create_tenant.html')

    return render_template('superadmin/create_tenant.html')


@superadmin_bp.route('/impersonate/<int:tenant_id>', methods=['POST'])
@login_required
@superadmin_required
def impersonate_tenant(tenant_id):
    """Switch to a tenant's admin account for support purposes."""
    tenant = Tenant.query.get_or_404(tenant_id)
    admin_user = User.query.filter_by(
        tenant_id=tenant.id, role='admin', is_superadmin=False
    ).first()

    if not admin_user:
        flash(f"No admin user found for tenant '{tenant.name}'.", "danger")
        return redirect(url_for('superadmin_bp.dashboard'))

    session['superadmin_original_user_id'] = current_user.id
    login_user(admin_user)
    flash(
        f"Now viewing as '{admin_user.username}' (tenant: {tenant.name}). "
        "Use the banner at the top to exit impersonation.",
        "info"
    )
    return redirect(url_for('dashboard_bp.main_dashboard'))


@superadmin_bp.route('/exit_impersonation', methods=['POST'])
@login_required
def exit_impersonation():
    """Switch back to the super admin account."""
    original_id = session.pop('superadmin_original_user_id', None)
    if not original_id:
        flash("Not currently impersonating.", "warning")
        return redirect(url_for('dashboard_bp.main_dashboard'))

    superadmin_user = User.query.get(original_id)
    if not superadmin_user or not superadmin_user.is_superadmin:
        flash("Could not restore super admin session.", "danger")
        return redirect(url_for('auth.login'))

    login_user(superadmin_user)
    flash("Returned to super admin account.", "success")
    return redirect(url_for('superadmin_bp.dashboard'))
