from flask import redirect, url_for


from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from inventory_flask_app.models import User, ProductProcessLog
from datetime import datetime

import io
import csv
from flask import send_file

reports_bp = Blueprint('reports_bp', __name__)


# Technician productivity report route
@reports_bp.route('/tech_productivity', methods=['GET'])
@login_required
def tech_productivity():
    # Only admins/supervisors can view
    if current_user.role not in ['admin', 'supervisor']:
        return "Not authorized", 403

    # Optional: filter by date range
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    query = ProductProcessLog.query.filter(ProductProcessLog.action == 'check-in')
    if start_date:
        query = query.filter(ProductProcessLog.moved_at >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        from datetime import timedelta
        end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(ProductProcessLog.moved_at < end_dt)

    # Group by technician and stage
    logs = query.all()
    summary = {}
    for log in logs:
        tech = log.user.username if log.user else 'Unknown'
        stage = log.to_stage or 'Unknown'
        key = (tech, stage)
        if key not in summary:
            summary[key] = {
                'tech': tech,
                'stage': stage,
                'count': 0,
                'last': log.moved_at
            }
        summary[key]['count'] += 1
        if log.moved_at > summary[key]['last']:
            summary[key]['last'] = log.moved_at

    report = list(summary.values())
    report.sort(key=lambda x: (x['tech'], x['stage']))


    return render_template('tech_productivity.html', report=report, start_date=start_date, end_date=end_date)


# Technician profile route
@reports_bp.route('/tech_profile/<username>', methods=['GET', 'POST'])
@login_required
def tech_profile(username):
    # Only admins/supervisors can view
    if current_user.role not in ['admin', 'supervisor']:
        return "Not authorized", 403

    user = User.query.filter_by(username=username).first_or_404()

    # Filters
    stage = request.args.get('stage')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    serial_query = request.args.get('serial')

    query = ProductProcessLog.query.filter_by(moved_by=user.id)
    if stage:
        query = query.filter(ProductProcessLog.to_stage == stage)
    if start_date:
        query = query.filter(ProductProcessLog.moved_at >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        from datetime import timedelta
        end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(ProductProcessLog.moved_at < end_dt)
    if serial_query:
        from inventory_flask_app.models import ProductInstance
        logs = []
        for log in query.order_by(ProductProcessLog.moved_at.desc()).all():
            inst = ProductInstance.query.get(log.product_instance_id)
            if inst and serial_query.lower() in inst.serial_number.lower():
                logs.append(log)
    else:
        logs = query.order_by(ProductProcessLog.moved_at.desc()).all()

    # Unique stages for filter dropdown
    unique_stages = sorted(set(l.to_stage for l in logs if l.to_stage))

    from inventory_flask_app.models import ProductInstance
    log_rows = []
    for log in logs:
        inst = ProductInstance.query.get(log.product_instance_id)
        log_rows.append({
            "serial": inst.serial_number if inst else "-",
            "model": inst.product.model_number if (inst and inst.product) else "-",
            "stage": log.to_stage,
            "action": log.action,
            "time": log.moved_at,
            "note": log.note,
            "team": log.to_team,
            "status": inst.status if inst else "-",
            "log_id": log.id
        })

    return render_template(
        "tech_profile.html",
        user=user,
        log_rows=log_rows,
        unique_stages=unique_stages,
        stage=stage,
        start_date=start_date,
        end_date=end_date,
        serial_query=serial_query
    )


# Export technician profile with filters as CSV
@reports_bp.route('/tech_profile_export/<username>', methods=['GET'])
@login_required
def tech_profile_export(username):
    if current_user.role not in ['admin', 'supervisor']:
        return "Not authorized", 403

    user = User.query.filter_by(username=username).first_or_404()
    # Apply same filters as profile page
    stage = request.args.get('stage')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    serial_query = request.args.get('serial')

    query = ProductProcessLog.query.filter_by(moved_by=user.id)
    if stage:
        query = query.filter(ProductProcessLog.to_stage == stage)
    if start_date:
        query = query.filter(ProductProcessLog.moved_at >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        from datetime import timedelta
        end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(ProductProcessLog.moved_at < end_dt)
    if serial_query:
        from inventory_flask_app.models import ProductInstance
        logs = []
        for log in query.order_by(ProductProcessLog.moved_at.desc()).all():
            inst = ProductInstance.query.get(log.product_instance_id)
            if inst and serial_query.lower() in inst.serial_number.lower():
                logs.append(log)
    else:
        logs = query.order_by(ProductProcessLog.moved_at.desc()).all()

    # Prepare CSV rows
    from inventory_flask_app.models import ProductInstance
    csv_rows = []
    for log in logs:
        inst = ProductInstance.query.get(log.product_instance_id)
        csv_rows.append([
            inst.serial_number if inst else "-",
            inst.product.model_number if (inst and inst.product) else "-",
            log.to_stage or "-",
            log.action,
            log.moved_at.strftime('%Y-%m-%d %H:%M'),
            log.note or "",
            log.to_team or "-",
            inst.status if inst else "-"
        ])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Serial', 'Model', 'Stage', 'Action', 'Time', 'Note', 'Team', 'Status'])
    writer.writerows(csv_rows)
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'{username}_report.csv'
    )


# Idle Units report route
@reports_bp.route('/idle_units', methods=['GET'])
@login_required
def idle_units():
    if current_user.role not in ['admin', 'supervisor']:
        return "Not authorized", 403

    # Default threshold: 48 hours (can be changed to a request param)
    from datetime import datetime, timedelta
    threshold_hours = int(request.args.get('hours', 48))
    idle_since = datetime.utcnow() - timedelta(hours=threshold_hours)

    from inventory_flask_app.models import ProductInstance, ProductProcessLog, User
    instances = ProductInstance.query.filter(
        ProductInstance.status == 'under_process',
        ProductInstance.assigned_to_user_id.isnot(None)
    ).all()

    idle_units = []
    for inst in instances:
        # Get latest check-in
        logs = ProductProcessLog.query.filter_by(product_instance_id=inst.id, action='check-in')\
            .order_by(ProductProcessLog.moved_at.desc()).all()
        if logs and logs[0].moved_at < idle_since:
            idle_units.append({
                "serial": inst.serial_number,
                "model": inst.product.model_number if inst.product else "-",
                "stage": inst.process_stage,
                "technician": inst.assigned_user.username if inst.assigned_user else "-",
                "team": inst.team_assigned or "-",
                "checkin_time": logs[0].moved_at,
                "idle_hours": int((datetime.utcnow() - logs[0].moved_at).total_seconds() // 3600)
            })

    idle_units.sort(key=lambda x: x['idle_hours'], reverse=True)
    return render_template(
        "idle_units.html",
        idle_units=idle_units,
        threshold_hours=threshold_hours
    )


# Route to update idle reason for a unit from the idle units table
@reports_bp.route('/update_idle_reason', methods=['POST'])
@login_required
def update_idle_reason():
    if current_user.role not in ['admin', 'supervisor']:
        return "Not authorized", 403

    serial = request.form.get('serial')
    idle_reason = request.form.get('idle_reason', '').strip()

    from inventory_flask_app.models import ProductInstance
    instance = ProductInstance.query.filter_by(serial_number=serial).first()
    if instance:
        instance.idle_reason = idle_reason
        from inventory_flask_app import db
        db.session.commit()
    # Redirect back to idle units page, preserving filters if possible
    return_url = request.referrer or url_for('reports_bp.idle_units')
    return redirect(return_url)