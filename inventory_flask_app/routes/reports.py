from flask import redirect, url_for
from inventory_flask_app import csrf

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from inventory_flask_app.models import User, ProductProcessLog
from datetime import datetime

# Tenant-aware time utility
from inventory_flask_app.utils import get_now_for_tenant

import io
import csv
from flask import send_file
from sqlalchemy import or_

reports_bp = Blueprint('reports_bp', __name__)


# Technician productivity report route
@csrf.exempt
@reports_bp.route('/tech_productivity', methods=['GET'])
@login_required
def tech_productivity():
    # Enforce module access via tenant settings
    tenant_settings = []
    settings = {}
    # Only admins/supervisors can view
    if current_user.role not in ['admin', 'supervisor']:
        return "Not authorized", 403

    # Optional: filter by date range
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    query = ProductProcessLog.query.filter(ProductProcessLog.action == 'check-in')
    query = query.join(User).filter(User.tenant_id == current_user.tenant_id)
    if start_date and start_date != 'None':
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(ProductProcessLog.moved_at >= start_dt)
        except ValueError:
            pass
    if end_date and end_date != 'None':
        try:
            from datetime import timedelta
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(ProductProcessLog.moved_at < end_dt)
        except ValueError:
            pass

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

    # Calculate totals row
    total_count = sum(row['count'] for row in report)

    return render_template(
        'tech_productivity.html',
        report=report,
        start_date=start_date,
        end_date=end_date,
        total_count=total_count
    )


# Technician profile route
@csrf.exempt
@reports_bp.route('/tech_profile/<username>', methods=['GET', 'POST'])
@login_required
def tech_profile(username):
    # Only admins/supervisors can view
    if current_user.role not in ['admin', 'supervisor']:
        return "Not authorized", 403

    user = User.query.filter_by(username=username).first_or_404()
    if user.tenant_id != current_user.tenant_id:
        return "Access denied", 403

    # Filters
    stage = request.args.get('stage')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    serial_query = request.args.get('serial')

    if stage == 'None':
        stage = None
    if start_date == 'None':
        start_date = None
    if end_date == 'None':
        end_date = None
    if serial_query == 'None':
        serial_query = None

    # Ensure ProductInstance and Product are available for all grouping/filtering logic
    from inventory_flask_app.models import ProductInstance, Product

    query = ProductProcessLog.query.filter_by(moved_by=user.id).join(User).filter(User.tenant_id == current_user.tenant_id)
    if stage:
        query = query.filter(ProductProcessLog.to_stage == stage)
    if start_date and start_date != 'None':
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(ProductProcessLog.moved_at >= start_dt)
        except ValueError:
            pass
    if end_date and end_date != 'None':
        try:
            from datetime import timedelta
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(ProductProcessLog.moved_at < end_dt)
        except ValueError:
            pass
    if serial_query:
        from inventory_flask_app.models import ProductInstance, Product
        logs = []
        for log in query.order_by(ProductProcessLog.moved_at.desc()).all():
            inst = ProductInstance.query.join(Product).filter(
                ProductInstance.id == log.product_instance_id,
                Product.tenant_id == current_user.tenant_id
            ).first()
            if inst and serial_query.lower() in inst.serial.lower():
                logs.append(log)
    else:
        logs = query.order_by(ProductProcessLog.moved_at.desc()).all()

    if not logs:
        print("No logs returned from query.")

    group_by = request.args.get('group_by')

    if group_by in ['stage', 'action']:
        from collections import defaultdict
        grouped_log_rows = defaultdict(list)

        for log in logs:
            inst = ProductInstance.query.join(Product).filter(
                ProductInstance.id == log.product_instance_id,
                Product.tenant_id == current_user.tenant_id
            ).first()
            row = {
                "serial": inst.serial if inst else "-",
                "model": inst.product.model if (inst and inst.product) else "-",
                "stage": log.to_stage,
                "action": log.action,
                "time": log.moved_at,
                "note": log.note,
                "team": log.to_team,
                "status": inst.status if inst else "-",
                "asset": inst.asset if inst else "-",
                "log_id": log.id
            }
            key = log.to_stage if group_by == 'stage' else log.action
            grouped_log_rows[key or "Unknown"].append(row)

        log_rows = grouped_log_rows  # now a dict of grouped lists
        print("Group By Mode:", group_by)
        print("Grouped Log Rows Keys:", list(grouped_log_rows.keys()))
    else:
        log_rows = []
        for log in logs:
            inst = ProductInstance.query.join(Product).filter(
                ProductInstance.id == log.product_instance_id,
                Product.tenant_id == current_user.tenant_id
            ).first()
            log_rows.append({
                "serial": inst.serial if inst else "-",
                "model": inst.product.model if (inst and inst.product) else "-",
                "stage": log.to_stage,
                "action": log.action,
                "time": log.moved_at,
                "note": log.note,
                "team": log.to_team,
                "status": inst.status if inst else "-",
                "asset": inst.asset if inst else "-",
                "log_id": log.id
            })

    # Unique stages for filter dropdown
    unique_stages = sorted(set(l.to_stage for l in logs if l.to_stage))

    return render_template(
        "tech_profile.html",
        user=user,
        log_rows=log_rows,
        grouped_logs=log_rows if group_by in ['stage', 'action'] else {},
        unique_stages=unique_stages,
        stage=stage,
        start_date=start_date,
        end_date=end_date,
        serial_query=serial_query
    )


# Export technician profile with filters as CSV
@csrf.exempt
@reports_bp.route('/tech_profile_export/<username>', methods=['GET'])
@login_required
def tech_profile_export(username):
    if current_user.role not in ['admin', 'supervisor']:
        return "Not authorized", 403

    user = User.query.filter_by(username=username).first_or_404()
    if user.tenant_id != current_user.tenant_id:
        return "Access denied", 403
    # Apply same filters as profile page
    stage = request.args.get('stage')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    serial_query = request.args.get('serial')

    query = ProductProcessLog.query.filter_by(moved_by=user.id).join(User).filter(User.tenant_id == current_user.tenant_id)
    if stage:
        query = query.filter(ProductProcessLog.to_stage == stage)
    if start_date:
        query = query.filter(ProductProcessLog.moved_at >= get_now_for_tenant().strptime(start_date, '%Y-%m-%d'))
    if end_date:
        from datetime import timedelta
        end_dt = get_now_for_tenant().strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(ProductProcessLog.moved_at < end_dt)
    if serial_query:
        from inventory_flask_app.models import ProductInstance, Product
        logs = []
        for log in query.order_by(ProductProcessLog.moved_at.desc()).all():
            inst = ProductInstance.query.join(Product).filter(
                ProductInstance.id == log.product_instance_id,
                Product.tenant_id == current_user.tenant_id
            ).first()
            if inst and serial_query.lower() in inst.serial.lower():
                logs.append(log)
    else:
        logs = query.order_by(ProductProcessLog.moved_at.desc()).all()

    # Prepare CSV rows
    from inventory_flask_app.models import ProductInstance, Product
    csv_rows = []
    for log in logs:
        inst = ProductInstance.query.join(Product).filter(
            ProductInstance.id == log.product_instance_id,
            Product.tenant_id == current_user.tenant_id
        ).first()
        csv_rows.append([
            inst.serial if inst else "-",
            inst.product.model if (inst and inst.product) else "-",
            log.to_stage or "-",
            log.action,
            log.moved_at.strftime('%Y-%m-%d %H:%M'),
            log.note or "",
            log.to_team or "-",
            inst.status if inst else "-",
            inst.asset if inst else "-"
        ])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Serial', 'Model', 'Stage', 'Action', 'Time', 'Note', 'Team', 'Status', 'Asset'])
    writer.writerows(csv_rows)
    writer.writerow([])
    writer.writerow(['Total Records', len(csv_rows)])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'{username}_report.csv'
    )


# Idle Units report route
@csrf.exempt
@reports_bp.route('/idle_units', methods=['GET'])
@login_required
def idle_units():
    if current_user.role not in ['admin', 'supervisor']:
        return "Not authorized", 403

    from inventory_flask_app.models import ProductInstance, Product

    search = request.args.get('search', '').strip()
    model = request.args.get('model', '').strip()
    cpu = request.args.get('cpu', '').strip()

    query = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id,
        ProductInstance.status == 'idle'
    )
    if search:
        query = query.filter(
            or_(
                ProductInstance.serial.ilike(f"%{search}%"),
                ProductInstance.asset.ilike(f"%{search}%"),
                Product.item_name.ilike(f"%{search}%"),
                Product.model.ilike(f"%{search}%")
            )
        )
    if model:
        query = query.filter(Product.model.ilike(f"%{model}%"))
    if cpu:
        query = query.filter(Product.cpu.ilike(f"%{cpu}%"))
    instances = query.all()

    rows = []
    for inst in instances:
        rows.append({
            "serial": inst.serial,
            "asset": inst.asset,
            "item_name": inst.product.item_name if inst.product else "",
            "make": inst.product.make if inst.product else "",
            "model": inst.product.model if inst.product else "",
            "cpu": inst.product.cpu if inst.product else "",
            "ram": inst.product.ram if inst.product else "",
            "grade": inst.product.grade if inst.product else "",
            "display": inst.product.display if inst.product else "",
            "gpu1": inst.product.gpu1 if inst.product else "",
            "gpu2": inst.product.gpu2 if inst.product else "",
            "disk1size": inst.product.disk1size if inst.product else "",
            "technician": inst.assigned_user.username if inst.assigned_user else "-",
            "idle_reason": inst.note or inst.idle_reason or "",
            "idle_timestamp": inst.updated_at
        })

    total_count = len(rows)

    return render_template("idle_units.html", rows=rows, search=search, model=model, cpu=cpu, total_count=total_count)


# Route to update idle reason for a unit from the idle units table
from flask import flash
@csrf.exempt
@reports_bp.route('/update_idle_reason', methods=['POST'])
@login_required
def update_idle_reason():
    if current_user.role not in ['admin', 'supervisor']:
        return "Not authorized", 403

    serial = request.form.get('serial')
    idle_reason = request.form.get('idle_reason', '').strip()

    if not serial:
        flash("Serial is required to update idle reason.", "danger")
        return redirect(request.referrer or url_for('reports_bp.idle_units'))

    from inventory_flask_app.models import ProductInstance, Product
    instance = ProductInstance.query.join(Product).filter(
        ProductInstance.serial == serial,
        Product.tenant_id == current_user.tenant_id
    ).first()
    if not instance:
        flash(f"No unit found with serial {serial}.", "warning")
        return redirect(request.referrer or url_for('reports_bp.idle_units'))

    instance.idle_reason = idle_reason
    from inventory_flask_app import db
    db.session.commit()
    flash("Idle reason updated successfully.", "success")
    return redirect(request.referrer or url_for('reports_bp.idle_units'))
# Idle inventory units older than tenant-configurable threshold
from datetime import timedelta


# Route for idle inventory units older than a tenant-configurable threshold
@csrf.exempt
@reports_bp.route('/inventory/idle')
@login_required
def idle_inventory_view():
    from inventory_flask_app.models import TenantSettings, ProductInstance, Product
    settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings_dict = {s.key: s.value for s in settings}
    idle_days = int(settings_dict.get("idle_threshold_days", 7))

    now = get_now_for_tenant()
    threshold_date = now - timedelta(days=idle_days)

    instances = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id,
        ProductInstance.status == 'idle',
        ProductInstance.updated_at < threshold_date,
        ProductInstance.is_sold == False
    ).all()

    return render_template(
        "idle_inventory.html",
        instances=instances,
        threshold_days=idle_days
    )


# Route to show technicians with slow processing units based on tenant-configured delay threshold
@csrf.exempt
@reports_bp.route('/report/slow_technicians')
@login_required
def slow_technicians():
    from inventory_flask_app.models import TenantSettings, ProductInstance, Product
    settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings_dict = {s.key: s.value for s in settings}
    delay_days = int(settings_dict.get("tech_delay_threshold_days", 3))

    now = get_now_for_tenant()
    delay_threshold = now - timedelta(days=delay_days)

    instances = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id,
        ProductInstance.updated_at < delay_threshold,
        ProductInstance.team_assigned.isnot(None),
        ProductInstance.is_sold == False
    ).all()

    return render_template(
        "slow_technicians.html",
        instances=instances,
        threshold_days=delay_days
    )