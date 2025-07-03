from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from ..models import db, User
from inventory_flask_app.models import TenantSettings
from flask_wtf.csrf import generate_csrf

auth_bp = Blueprint('auth_bp', __name__)

@auth_bp.route('/', methods=['GET', 'POST'])
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    settings = {}

    if current_user.is_authenticated and current_user.tenant_id:
        tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
        settings = {s.key: s.value for s in tenant_settings}

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            if not user.tenant_id:
                flash("User is not assigned to any tenant. Contact administrator.", "danger")
                return redirect(url_for('auth_bp.login'))
            login_user(user)
            return redirect(url_for('dashboard_bp.main_dashboard'))
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('login.html', settings=settings)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth_bp.login'))

from werkzeug.security import generate_password_hash

@auth_bp.route('/register_user', methods=['GET', 'POST'])
@login_required
def register_user():
    if current_user.role != 'admin':
        flash("Not authorized to create users.", "danger")
        return redirect(url_for('dashboard_bp.main_dashboard'))

    settings = {}
    if current_user.tenant_id:
        from inventory_flask_app.models import TenantSettings
        tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
        settings = {s.key: s.value for s in tenant_settings}

    users = User.query.filter_by(tenant_id=current_user.tenant_id).order_by(User.username).all()

    if request.method == 'POST':
        from flask_wtf.csrf import validate_csrf
        from wtforms import ValidationError

        try:
            validate_csrf(request.form.get('csrf_token'))
        except ValidationError:
            flash("Invalid or missing CSRF token.", "danger")
            return render_template('register_user.html', settings=settings, username=request.form.get('username', '').strip(), role=request.form.get('role', 'technician'), users=users)

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'technician')

        if not username or not password:
            flash("Username and password are required.", "warning")
            return render_template('register_user.html', settings=settings, username=username, role=role, users=users)

        if User.query.filter_by(username=username, tenant_id=current_user.tenant_id).first():
            flash("A user with that username already exists.", "warning")
            return render_template('register_user.html', settings=settings, username=username, role=role, users=users)

        user = User(
            username=username,
            role=role,
            tenant_id=current_user.tenant_id,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        flash(f"✅ User '{username}' created with role '{role}'.", "success")
        return redirect(url_for('auth_bp.register_user'))

    return render_template('register_user.html', settings=settings, users=users)


# Tenant onboarding route
@auth_bp.route('/register_tenant', methods=['GET', 'POST'])
def register_tenant():
    from inventory_flask_app.models import Tenant, TenantSettings
    from werkzeug.security import generate_password_hash
    from flask_wtf.csrf import validate_csrf
    from wtforms import ValidationError

    if request.method == 'POST':
        try:
            validate_csrf(request.form.get('csrf_token'))
        except ValidationError:
            flash("Invalid or missing CSRF token.", "danger")
            return redirect(url_for('auth_bp.register_tenant'))

        tenant_name = request.form.get('tenant_name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password')
        confirm = request.form.get('confirm')

        if not tenant_name or not username or not password or password != confirm:
            flash("All fields are required and passwords must match.", "danger")
            return render_template('register_tenant.html', settings={})

        # Create tenant and admin user
        tenant = Tenant(name=tenant_name)
        db.session.add(tenant)
        db.session.flush()

        db.session.add_all([
            TenantSettings(tenant_id=tenant.id, key='dashboard_name', value=f"{tenant_name} Dashboard"),
            TenantSettings(tenant_id=tenant.id, key='dashboard_logo', value='/static/img/default_logo.png')
        ])

        user = User(
            username=username,
            role='admin',
            tenant_id=tenant.id,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()

        flash("✅ Tenant and admin account created successfully. You can now log in.", "success")
        return redirect(url_for('auth_bp.login'))

    return render_template("register_tenant.html", settings={})


# Edit user route (admin only)
@auth_bp.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    if current_user.role != 'admin':
        flash("Not authorized.", "danger")
        return redirect(url_for('dashboard_bp.main_dashboard'))

    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        role = request.form.get('role', 'technician')
        if username:
            user.username = username
            user.role = role
            db.session.commit()
            flash("✅ User updated.", "success")
            return redirect(url_for('auth_bp.register_user'))

    settings = {}
    if current_user.tenant_id:
        tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
        settings = {s.key: s.value for s in tenant_settings}

    return render_template('edit_user.html', user=user, settings=settings)

@auth_bp.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        flash("Not authorized.", "danger")
        return redirect(url_for('dashboard_bp.main_dashboard'))

    user = User.query.get_or_404(user_id)

    # Prevent deleting own account
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "warning")
        return redirect(url_for('auth_bp.register_user'))

    db.session.delete(user)
    db.session.commit()
    flash("User deleted successfully.", "success")
    return redirect(url_for('auth_bp.register_user'))