from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from flask_wtf.csrf import validate_csrf
from wtforms import ValidationError
from ..models import db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    settings = {}
    if current_user.is_authenticated and current_user.tenant_id:
        from inventory_flask_app.models import TenantSettings
        tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
        settings = {s.key: s.value for s in tenant_settings}

    if request.method == 'POST':
        try:
            validate_csrf(request.form.get('csrf_token'))
        except ValidationError:
            flash("Invalid or missing CSRF token. Please try again.", "danger")
            return render_template('login.html', settings=settings)

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        from ..models import User

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.tenant_id:
                flash("User is not assigned to any tenant. Contact administrator.", "danger")
                return redirect(url_for('auth.login'))
            login_user(user)
            flash("Logged in successfully!", "success")
            return redirect(url_for('dashboard_bp.main_dashboard'))
        else:
            flash("Invalid username or password.", "danger")

    return render_template('login.html', settings=settings)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for('auth.login'))

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

    from ..models import User

    users = User.query.filter_by(tenant_id=current_user.tenant_id).order_by(User.username).all()

    if request.method == 'POST':
        try:
            validate_csrf(request.form.get('csrf_token'))
        except ValidationError:
            flash("Invalid or missing CSRF token.", "danger")
            return render_template('register_user.html', settings=settings, users=users)

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'technician')
        full_name = request.form.get('full_name', '').strip() or None

        if not username or not password:
            flash("Username and password are required.", "warning")
            return render_template('register_user.html', settings=settings, username=username, role=role, users=users)

        if User.query.filter_by(username=username).first():
            flash("Username already taken, please choose another.", "warning")
            return render_template('register_user.html', settings=settings, username=username, role=role, users=users)

        user = User(
            username=username,
            full_name=full_name,
            role=role,
            tenant_id=current_user.tenant_id,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()

        flash(f"✅ User '{username}' created with role '{role}'.", "success")
        return redirect(url_for('auth.register_user'))

    return render_template('register_user.html', settings=settings, users=users)

@auth_bp.route('/register_tenant', methods=['GET', 'POST'])
def register_tenant():
    if request.method == 'POST':
        try:
            validate_csrf(request.form.get('csrf_token'))
        except ValidationError:
            flash("Invalid or missing CSRF token.", "danger")
            return render_template('register_tenant.html')

        tenant_name = request.form.get('tenant_name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')

        if not tenant_name or not username or not password or password != confirm:
            flash("All fields are required and passwords must match.", "danger")
            return render_template('register_tenant.html')

        from ..models import Tenant, User, TenantSettings
        from .admin import _seed_default_stages

        if User.query.filter_by(username=username).first():
            flash("Username already taken, please choose another.", "danger")
            return render_template('register_tenant.html')

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

        _seed_default_stages(tenant.id)

        flash("✅ Tenant and admin account created. You can now log in.", "success")
        return redirect(url_for('auth.login'))

    return render_template("register_tenant.html")

@auth_bp.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    if current_user.role != 'admin':
        flash("Not authorized.", "danger")
        return redirect(url_for('dashboard_bp.main_dashboard'))

    from ..models import User
    user = User.query.filter_by(id=user_id, tenant_id=current_user.tenant_id).first_or_404()

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        role = request.form.get('role', 'technician')
        full_name = request.form.get('full_name', '').strip() or None
        new_password = request.form.get('new_password', '').strip()

        if username:
            if User.query.filter(User.username == username, User.id != user.id).first():
                flash("Username already taken, please choose another.", "warning")
                return redirect(url_for('auth.edit_user', user_id=user_id))

            user.username = username
            user.role = role
            user.full_name = full_name
            if new_password:
                user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash("✅ User updated.", "success")
            return redirect(url_for('auth.register_user'))

    settings = {}
    if current_user.tenant_id:
        from inventory_flask_app.models import TenantSettings
        tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
        settings = {s.key: s.value for s in tenant_settings}

    return render_template('edit_user.html', user=user, settings=settings)

@auth_bp.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        flash("Not authorized.", "danger")
        return redirect(url_for('dashboard_bp.main_dashboard'))

    try:
        validate_csrf(request.form.get('csrf_token'))
    except ValidationError:
        flash("Invalid or missing CSRF token.", "danger")
        return redirect(url_for('auth.register_user'))

    from ..models import User
    user = User.query.filter_by(id=user_id, tenant_id=current_user.tenant_id).first_or_404()

    if user.id == current_user.id:
        flash("You cannot delete your own account.", "warning")
        return redirect(url_for('auth.register_user'))

    db.session.delete(user)
    db.session.commit()
    flash("User deleted successfully.", "success")
    return redirect(url_for('auth.register_user'))