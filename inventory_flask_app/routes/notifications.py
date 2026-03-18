import logging
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, abort
from flask_login import login_required, current_user
from inventory_flask_app.models import db, Notification
from inventory_flask_app import csrf

logger = logging.getLogger(__name__)

notifications_bp = Blueprint('notifications_bp', __name__, url_prefix='/notifications')


@notifications_bp.route('/')
@login_required
def notifications_list():
    """Full notifications list with type filter."""
    notif_type = request.args.get('type', '').strip()
    page = request.args.get('page', 1, type=int)

    query = Notification.query.filter_by(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    ).order_by(Notification.created_at.desc())

    if notif_type:
        query = query.filter_by(type=notif_type)

    total = query.count()
    notifs = query.paginate(page=page, per_page=30)

    return render_template(
        'notifications/list.html',
        notifs=notifs,
        total=total,
        filter_type=notif_type,
    )


@notifications_bp.route('/<int:notif_id>/read', methods=['POST', 'GET'])
@login_required
def mark_read(notif_id):
    """Mark a single notification as read and redirect to its link."""
    notif = Notification.query.filter_by(
        id=notif_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    ).first()

    if notif and not notif.is_read:
        notif.is_read = True
        db.session.commit()

    next_url = request.args.get('next') or (notif.link if notif else None) or url_for('notifications_bp.notifications_list')
    return redirect(next_url)


@notifications_bp.route('/read_all', methods=['POST'])
@login_required
def read_all():
    """Mark all unread notifications as read for the current user."""
    Notification.query.filter_by(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        is_read=False,
    ).update({'is_read': True})
    db.session.commit()
    return jsonify({'ok': True})


@notifications_bp.route('/api/unread_count')
@login_required
def unread_count():
    """Return JSON unread notification count for polling."""
    count = Notification.query.filter_by(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        is_read=False,
    ).count()
    return jsonify({'count': count})
