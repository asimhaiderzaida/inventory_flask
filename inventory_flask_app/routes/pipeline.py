from flask import Blueprint, render_template, request, jsonify, url_for
from flask_login import login_required, current_user
from inventory_flask_app import csrf
from inventory_flask_app.models import db, Product, ProductInstance, ProductProcessLog, ProcessStage
from inventory_flask_app.utils.utils import calc_duration_minutes, create_notification
from inventory_flask_app.utils import get_now_for_tenant

pipeline_bp = Blueprint('pipeline_bp', __name__, url_prefix='/stock')


# ─────────────────────────────────────────────────────────────
# Kanban Pipeline View
# ─────────────────────────────────────────────────────────────
@pipeline_bp.route('/pipeline')
@login_required
def pipeline():
    stages = ProcessStage.query.filter_by(
        tenant_id=current_user.tenant_id
    ).order_by(ProcessStage.order).all()

    stage_names = {s.name for s in stages}

    # Units actively being processed
    under_process = (
        ProductInstance.query.join(Product)
        .filter(
            Product.tenant_id == current_user.tenant_id,
            ProductInstance.is_sold == False,
            ProductInstance.status == 'under_process',
        )
        .order_by(ProductInstance.entered_stage_at.asc().nulls_last())
        .all()
    )

    # Unprocessed units — all of them (Load More in template handles UX)
    unprocessed = (
        ProductInstance.query.join(Product)
        .filter(
            Product.tenant_id == current_user.tenant_id,
            ProductInstance.is_sold == False,
            ProductInstance.status == 'unprocessed',
        )
        .order_by(ProductInstance.created_at.desc())
        .all()
    )

    # Group under_process units by stage; stage not in config → unassigned
    stage_buckets = {s.name: [] for s in stages}
    orphans = []  # under_process but stage not in configured list
    for unit in under_process:
        stage = (unit.process_stage or '').strip()
        if stage in stage_names:
            stage_buckets[stage].append(unit)
        else:
            orphans.append(unit)

    columns = {'': list(unprocessed) + orphans}
    for s in stages:
        columns[s.name] = stage_buckets[s.name]

    return render_template(
        'pipeline.html',
        stages=stages,
        columns=columns,
        total_in_process=len(under_process),
        total_unprocessed=len(unprocessed),
        unassigned_initial=30,
    )


@pipeline_bp.route('/pipeline/move', methods=['POST'])
@login_required
def pipeline_move():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data'}), 400

    try:
        instance_id = int(data['instance_id'])
    except (KeyError, ValueError, TypeError):
        return jsonify({'error': 'Bad instance_id'}), 400

    to_stage = (data.get('to_stage') or '').strip()

    # Validate to_stage against configured stages for this tenant
    if to_stage:
        valid_stages = {s.name for s in ProcessStage.query.filter_by(tenant_id=current_user.tenant_id).all()}
        if valid_stages and to_stage not in valid_stages:
            return jsonify({'success': False, 'error': f'Invalid stage: {to_stage}'}), 400

    instance = ProductInstance.query.join(Product).filter(
        ProductInstance.id == instance_id,
        Product.tenant_id == current_user.tenant_id,
    ).first()
    if not instance:
        return jsonify({'error': 'Not found'}), 404

    prev_stage = instance.process_stage
    duration = calc_duration_minutes(instance.entered_stage_at)
    now_ts = get_now_for_tenant()

    if not to_stage:
        instance.status = 'unprocessed'
        instance.process_stage = None
        instance.entered_stage_at = None
        instance.assigned_to_user_id = None
    else:
        instance.status = 'under_process'
        instance.process_stage = to_stage
        instance.entered_stage_at = now_ts

    instance.updated_at = now_ts

    db.session.add(ProductProcessLog(
        product_instance_id=instance.id,
        from_stage=prev_stage,
        to_stage=to_stage or None,
        from_team=instance.team_assigned,
        to_team=instance.team_assigned,
        moved_by=current_user.id,
        moved_at=now_ts,
        action='pipeline_move',
        duration_minutes=duration,
    ))
    # Notify assigned user when their unit is moved by someone else
    if to_stage and instance.assigned_to_user_id and instance.assigned_to_user_id != current_user.id:
        create_notification(
            user_id=instance.assigned_to_user_id,
            notif_type='stage_move',
            title='Unit Stage Updated',
            message=f'{instance.serial} moved to {to_stage} by {current_user.username}',
            link=url_for('stock_bp.process_stage_update', tab='under_process'),
        )
    db.session.commit()

    return jsonify({
        'ok': True,
        'serial': instance.serial,
        'to_stage': to_stage,
        'dur': calc_duration_minutes(instance.entered_stage_at),
    })
