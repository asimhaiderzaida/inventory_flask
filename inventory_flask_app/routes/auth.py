from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from ..models import db, User

auth_bp = Blueprint('auth_bp', __name__)

@auth_bp.route('/', methods=['GET', 'POST'])
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard_bp.main_dashboard'))
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth_bp.login'))

from flask_login import current_user
from werkzeug.security import generate_password_hash

@auth_bp.route('/register_user', methods=['GET', 'POST'])
@login_required
def register_user():
    if current_user.role != 'admin':
        flash("Not authorized.", "danger")
        return redirect(url_for('dashboard_bp.main_dashboard'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        role = request.form.get('role', 'technician')
        if not username or not password:
            flash("Username and password required.", "warning")
            return render_template('register_user.html')
        if User.query.filter_by(username=username).first():
            flash("Username already exists.", "warning")
            return render_template('register_user.html')
        user = User(username=username, role=role)
        user.password_hash = generate_password_hash(password)
        db.session.add(user)
        db.session.commit()
        flash(f"User {username} created as {role}.", "success")
        return redirect(url_for('auth_bp.register_user'))

    return render_template('register_user.html')
