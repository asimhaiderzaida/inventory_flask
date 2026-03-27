import logging
import secrets
from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from flask_wtf.csrf import validate_csrf
from wtforms import ValidationError
from ..models import db
from inventory_flask_app import limiter

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
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

        login_input = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        from ..models import User

        # Accept username or email
        user = User.query.filter_by(username=login_input).first()
        if not user:
            user = User.query.filter(db.func.lower(User.email) == login_input.lower()).first()

        if user and user.check_password(password):
            if not user.tenant_id:
                flash("User is not assigned to any tenant. Contact administrator.", "danger")
                return redirect(url_for('auth.login'))
            # Block login if tenant is disabled (super admins are always allowed)
            if not user.is_superadmin and user.tenant and not user.tenant.is_active:
                flash("This account has been disabled. Please contact the administrator.", "danger")
                return render_template('login.html', settings=settings)
            login_user(user)
            from datetime import datetime, timezone
            user.last_login_at = datetime.now(timezone.utc)
            user.failed_login_attempts = 0
            db.session.commit()
            flash("Logged in successfully!", "success")
            return redirect(url_for('dashboard_bp.main_dashboard'))
        else:
            if user:
                user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
                db.session.commit()
            flash("Invalid username or password.", "danger")

    from ..models import TenantSettings
    public_reg = TenantSettings.query.filter_by(key='allow_public_registration').first()
    registration_disabled = public_reg is not None and public_reg.value == 'false'
    return render_template('login.html', settings=settings, registration_disabled=registration_disabled)

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
        email = request.form.get('email', '').strip().lower() or None

        if not username or not password:
            flash("Username and password are required.", "warning")
            return render_template('register_user.html', settings=settings, username=username, role=role, users=users)

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "warning")
            return render_template('register_user.html', settings=settings, username=username, role=role, users=users)

        if User.query.filter_by(username=username).first():
            flash("Username already taken, please choose another.", "warning")
            return render_template('register_user.html', settings=settings, username=username, role=role, users=users)

        if email and User.query.filter(db.func.lower(User.email) == email).first():
            flash("A user with that email already exists.", "warning")
            return render_template('register_user.html', settings=settings, username=username, role=role, users=users)

        user = User(
            username=username,
            full_name=full_name,
            email=email,
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
@limiter.limit("3/hour", methods=["POST"])
def register_tenant():
    from ..models import TenantSettings
    public_reg = TenantSettings.query.filter_by(key='allow_public_registration').first()
    if public_reg and public_reg.value == 'false':
        flash("Registration is disabled. Please contact the administrator.", "warning")
        return redirect(url_for('auth.login'))

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
        email = request.form.get('email', '').strip().lower()

        if not tenant_name or not username or not password or not email or password != confirm:
            flash("All fields are required and passwords must match.", "danger")
            return render_template('register_tenant.html')

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template('register_tenant.html')

        from ..models import Tenant, User, TenantSettings
        from .admin import _seed_default_stages

        if User.query.filter_by(username=username).first():
            flash("Username already taken, please choose another.", "danger")
            return render_template('register_tenant.html')

        if User.query.filter(db.func.lower(User.email) == email).first():
            flash("An account with that email already exists.", "danger")
            return render_template('register_tenant.html')

        try:
            tenant = Tenant(name=tenant_name)
            db.session.add(tenant)
            db.session.flush()

            db.session.add_all([
                TenantSettings(tenant_id=tenant.id, key='dashboard_name', value=f"{tenant_name} Dashboard"),
                TenantSettings(tenant_id=tenant.id, key='dashboard_logo', value='/static/img/default_logo.png')
            ])

            user = User(
                username=username,
                email=email,
                role='admin',
                tenant_id=tenant.id,
                password_hash=generate_password_hash(password)
            )
            db.session.add(user)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Failed to create tenant '%s'", tenant_name)
            flash("An error occurred while creating the account. Please try again.", "danger")
            return render_template('register_tenant.html')

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
        email = request.form.get('email', '').strip().lower() or None

        if username:
            if User.query.filter(User.username == username, User.id != user.id).first():
                flash("Username already taken, please choose another.", "warning")
                return redirect(url_for('auth.edit_user', user_id=user_id))

            if email and User.query.filter(db.func.lower(User.email) == email, User.id != user.id).first():
                flash("A user with that email already exists.", "warning")
                return redirect(url_for('auth.edit_user', user_id=user_id))

            user.username = username
            user.role = role
            user.full_name = full_name
            user.email = email
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


@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
@limiter.limit("5 per hour", methods=["POST"])
def forgot_password():
    """Request a password reset link sent to the user's email."""
    if request.method == 'POST':
        email_input = request.form.get('email', '').strip().lower()
        if not email_input:
            flash("Please enter your email address.", "warning")
            return render_template('forgot_password.html')

        from ..models import User, TenantSettings

        user = User.query.filter(db.func.lower(User.email) == email_input).first()

        if user and user.email:
            token = secrets.token_urlsafe(48)
            user.reset_token = token
            user.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
            db.session.commit()

            try:
                from inventory_flask_app import mail
                from flask_mail import Message

                _ts = TenantSettings.query.filter_by(tenant_id=user.tenant_id).all()
                settings = {s.key: s.value for s in _ts}
                company = settings.get('company_name') or settings.get('dashboard_name') or 'PCMart ERP'
                reset_url = url_for('auth.reset_password', token=token, _external=True)

                html_body = f"""
<div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;">
  <div style="background:#3B82F6;padding:1.5rem;border-radius:8px 8px 0 0;text-align:center;">
    <h2 style="color:#fff;margin:0;font-size:1.2rem;">Password Reset Request</h2>
  </div>
  <div style="background:#fff;padding:1.75rem;border:1px solid #E5E7EB;border-top:none;border-radius:0 0 8px 8px;">
    <p style="color:#374151;font-size:0.9rem;">Hi <strong>{user.username}</strong>,</p>
    <p style="color:#374151;font-size:0.9rem;">We received a request to reset your password for <strong>{company}</strong>. Click the button below to choose a new password:</p>
    <div style="text-align:center;margin:2rem 0;">
      <a href="{reset_url}" style="background:#3B82F6;color:#fff;padding:0.85rem 2.25rem;border-radius:6px;text-decoration:none;font-weight:600;font-size:0.95rem;display:inline-block;">Reset My Password</a>
    </div>
    <p style="color:#6B7280;font-size:0.82rem;">This link expires in <strong>1 hour</strong>. If you didn't request this, you can safely ignore this email — your password won't change.</p>
    <hr style="border:none;border-top:1px solid #E5E7EB;margin:1.25rem 0;">
    <p style="color:#9CA3AF;font-size:0.75rem;text-align:center;margin:0;">{company}</p>
  </div>
</div>
"""
                msg = Message(
                    subject=f"Password Reset — {company}",
                    recipients=[user.email],
                    html=html_body,
                    body=(
                        f"Password Reset\n\n"
                        f"Hi {user.username},\n\n"
                        f"Click here to reset your password:\n{reset_url}\n\n"
                        f"This link expires in 1 hour.\n\n"
                        f"— {company}"
                    ),
                )
                mail.send(msg)
                logger.info("Password reset email sent to %s (user: %s)", user.email, user.username)
            except Exception as e:
                logger.error("Failed to send reset email to %s: %s", email_input, e)

        # Always show the same message — don't reveal whether the email exists
        flash("If an account with that email exists, a password reset link has been sent.", "info")
        return redirect(url_for('auth.login'))

    return render_template('forgot_password.html')


@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Reset password using a valid time-limited token."""
    from ..models import User

    user = User.query.filter_by(reset_token=token).first()
    now = datetime.now(timezone.utc)

    expires = user.reset_token_expires_at if user else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if not user or not expires or expires < now:
        flash("This reset link is invalid or has expired. Please request a new one.", "danger")
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')

        if not password or len(password) < 8:
            flash("Password must be at least 8 characters.", "warning")
            return render_template('reset_password.html', token=token)

        if password != confirm:
            flash("Passwords do not match.", "warning")
            return render_template('reset_password.html', token=token)

        user.password_hash = generate_password_hash(password)
        user.reset_token = None
        user.reset_token_expires_at = None
        user.failed_login_attempts = 0
        db.session.commit()

        logger.info("Password reset completed for user %s", user.username)
        flash("Your password has been reset. You can now sign in.", "success")
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html', token=token)