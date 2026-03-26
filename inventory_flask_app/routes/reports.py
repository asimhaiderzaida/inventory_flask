import logging
from flask import redirect, url_for, flash
from inventory_flask_app import csrf

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from inventory_flask_app.models import User, ProductProcessLog, db
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Tenant-aware time utility
from inventory_flask_app.utils import get_now_for_tenant
from inventory_flask_app.utils.utils import is_module_enabled, admin_or_supervisor_required, module_required, safe_redirect_back

import io
import csv
from flask import send_file
from sqlalchemy import or_, func
from flask_paginate import Pagination, get_page_args

reports_bp = Blueprint('reports_bp', __name__)


def _require_reports_module():
    from flask import abort
    if not is_module_enabled('enable_reports_module'):
        abort(403)


# Landing page for /reports
@reports_bp.route('/reports')
@login_required
@module_required('reports', 'view')
def reports_index():
    _require_reports_module()
    return render_template('reports_index.html')


# ─────────────────────────────────────────────────────────────────────────────
# Technician Productivity Dashboard — per-tech KPIs, charts, SLA rates
# ─────────────────────────────────────────────────────────────────────────────
@reports_bp.route('/reports/technician_dashboard')
@login_required
@module_required('reports', 'view')
def technician_dashboard():
    _require_reports_module()
    from inventory_flask_app.models import ProcessStage, ProductInstance, Product

    tid = current_user.tenant_id
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now.date()

    days = request.args.get('days', 30, type=int)
    if days not in (7, 14, 30, 60, 90):
        days = 30
    start_date = datetime.combine(today - timedelta(days=days), datetime.min.time())

    # Find all tech IDs active in the period or with assigned units
    tech_ids_from_logs = (
        db.session.query(ProductProcessLog.moved_by)
        .join(User, ProductProcessLog.moved_by == User.id)
        .filter(User.tenant_id == tid, ProductProcessLog.moved_at >= start_date)
        .distinct()
        .all()
    )
    tech_ids_from_assigned = (
        db.session.query(ProductInstance.assigned_to_user_id)
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(Product.tenant_id == tid, ProductInstance.assigned_to_user_id.isnot(None))
        .distinct()
        .all()
    )
    all_tech_ids = list({r[0] for r in tech_ids_from_logs + tech_ids_from_assigned if r[0]})

    if not all_tech_ids:
        return render_template('reports/technician_dashboard.html',
            technicians=[], days=days, chart_data={}, stages=[])

    techs = User.query.filter(
        User.id.in_(all_tech_ids), User.tenant_id == tid
    ).order_by(User.username).all()

    stages = ProcessStage.query.filter_by(tenant_id=tid).order_by(ProcessStage.order).all()
    sla_map = {s.name: s.sla_hours for s in stages if s.sla_hours and s.sla_hours > 0}

    tech_data = []
    chart_labels = []
    chart_completed = []
    chart_avg_time = []

    for tech in techs:
        total_moves = ProductProcessLog.query.filter(
            ProductProcessLog.moved_by == tech.id,
            ProductProcessLog.moved_at >= start_date,
        ).count()

        checkouts = ProductProcessLog.query.filter(
            ProductProcessLog.moved_by == tech.id,
            ProductProcessLog.moved_at >= start_date,
            ProductProcessLog.action.in_(['checkout', 'check_out', 'scanner_status_update']),
            ProductProcessLog.to_stage == 'processed',
        ).count()

        avg_duration_row = (
            db.session.query(func.avg(ProductProcessLog.duration_minutes))
            .filter(
                ProductProcessLog.moved_by == tech.id,
                ProductProcessLog.moved_at >= start_date,
                ProductProcessLog.duration_minutes.isnot(None),
                ProductProcessLog.duration_minutes > 0,
            )
            .scalar()
        )
        avg_duration = round(float(avg_duration_row), 0) if avg_duration_row else None

        sla_logs = (
            ProductProcessLog.query
            .filter(
                ProductProcessLog.moved_by == tech.id,
                ProductProcessLog.moved_at >= start_date,
                ProductProcessLog.duration_minutes.isnot(None),
                ProductProcessLog.from_stage.isnot(None),
            )
            .all()
        )
        sla_total = 0
        sla_passed = 0
        for log in sla_logs:
            stage_sla = sla_map.get((log.from_stage or '').strip(), 0)
            if stage_sla > 0:
                sla_total += 1
                if (log.duration_minutes or 0) <= stage_sla * 60:
                    sla_passed += 1
        sla_rate = round(sla_passed / sla_total * 100, 1) if sla_total > 0 else None

        assigned_count = ProductInstance.query.join(Product).filter(
            Product.tenant_id == tid,
            ProductInstance.assigned_to_user_id == tech.id,
            ProductInstance.status == 'under_process',
            ProductInstance.is_sold == False,
        ).count()

        idle_events = ProductProcessLog.query.filter(
            ProductProcessLog.moved_by == tech.id,
            ProductProcessLog.moved_at >= start_date,
            ProductProcessLog.action.in_(['mark_idle', 'scanner_status_update']),
            ProductProcessLog.to_stage == 'idle',
        ).count()

        stage_breakdown = []
        for stage in stages:
            stage_moves = ProductProcessLog.query.filter(
                ProductProcessLog.moved_by == tech.id,
                ProductProcessLog.moved_at >= start_date,
                ProductProcessLog.from_stage == stage.name,
                ProductProcessLog.duration_minutes.isnot(None),
            ).all()
            if stage_moves:
                durations = [m.duration_minutes for m in stage_moves if m.duration_minutes]
                stage_avg = round(sum(durations) / len(durations), 0) if durations else None
                stage_sla_h = sla_map.get(stage.name, 0)
                stage_passed = sum(1 for d in durations if stage_sla_h > 0 and d <= stage_sla_h * 60)
                stage_total_sla = sum(1 for _ in durations if stage_sla_h > 0)
                stage_breakdown.append({
                    'name': stage.name,
                    'color': stage.color if hasattr(stage, 'color') and stage.color else '#6B7280',
                    'count': len(stage_moves),
                    'avg_minutes': stage_avg,
                    'sla_hours': stage_sla_h,
                    'sla_pass_rate': round(stage_passed / stage_total_sla * 100, 1) if stage_total_sla else None,
                })

        daily_rows = (
            db.session.query(
                func.date(ProductProcessLog.moved_at).label('day'),
                func.count(ProductProcessLog.id).label('cnt'),
            )
            .filter(
                ProductProcessLog.moved_by == tech.id,
                ProductProcessLog.moved_at >= start_date,
            )
            .group_by(func.date(ProductProcessLog.moved_at))
            .all()
        )
        daily_map = {r.day: r.cnt for r in daily_rows}
        spark_days = min(days, 30)
        sparkline = [daily_map.get(today - timedelta(days=i), 0) for i in range(spark_days - 1, -1, -1)]

        tech_data.append({
            'user': tech,
            'total_moves': total_moves,
            'checkouts': checkouts,
            'avg_duration': avg_duration,
            'sla_rate': sla_rate,
            'assigned_count': assigned_count,
            'idle_events': idle_events,
            'stage_breakdown': stage_breakdown,
            'sparkline': sparkline,
        })
        chart_labels.append(tech.full_name or tech.username)
        chart_completed.append(checkouts)
        chart_avg_time.append(avg_duration or 0)

    tech_data.sort(key=lambda t: t['checkouts'], reverse=True)

    chart_data = {
        'labels': chart_labels,
        'completed': chart_completed,
        'avg_time': chart_avg_time,
    }

    return render_template('reports/technician_dashboard.html',
        technicians=tech_data,
        days=days,
        chart_data=chart_data,
        stages=stages,
    )


# Technician productivity report route
@reports_bp.route('/tech_productivity', methods=['GET'])
@login_required
@module_required('reports', 'view')
def tech_productivity():
    _require_reports_module()

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
            flash("Invalid start date format. Use YYYY-MM-DD.", "danger")
    if end_date and end_date != 'None':
        try:
            from datetime import timedelta
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(ProductProcessLog.moved_at < end_dt)
        except ValueError:
            flash("Invalid end date format. Use YYYY-MM-DD.", "danger")

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
@reports_bp.route('/tech_profile/<username>', methods=['GET', 'POST'])
@login_required
@module_required('reports', 'view')
def tech_profile(username):
    _require_reports_module()

    user = User.query.filter_by(username=username).first_or_404()
    if user.tenant_id != current_user.tenant_id:
        return "Access denied", 403

    stage = request.args.get('stage')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    serial_query = request.args.get('serial')
    group_by = request.args.get('group_by')

    if stage == 'None': stage = None
    if start_date == 'None': start_date = None
    if end_date == 'None': end_date = None
    if serial_query == 'None': serial_query = None

    from inventory_flask_app.models import ProductInstance, Product

    query = ProductProcessLog.query.filter_by(moved_by=user.id).join(User).filter(User.tenant_id == current_user.tenant_id)
    if stage:
        query = query.filter(ProductProcessLog.to_stage == stage)
    if start_date:
        try:
            query = query.filter(ProductProcessLog.moved_at >= datetime.strptime(start_date, '%Y-%m-%d'))
        except ValueError:
            flash("Invalid start date format. Use YYYY-MM-DD.", "danger")
    if end_date:
        try:
            query = query.filter(ProductProcessLog.moved_at < datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
        except ValueError:
            flash("Invalid end date format. Use YYYY-MM-DD.", "danger")

    all_logs = query.order_by(ProductProcessLog.moved_at.desc()).all()

    # Bulk-load all referenced instances in one query (eliminates N+1)
    instance_ids = [l.product_instance_id for l in all_logs if l.product_instance_id]
    inst_map = {}
    if instance_ids:
        inst_map = {
            i.id: i
            for i in ProductInstance.query.join(Product).filter(
                ProductInstance.id.in_(instance_ids),
                Product.tenant_id == current_user.tenant_id
            ).all()
        }

    if serial_query:
        logs = [
            l for l in all_logs
            if (inst_map.get(l.product_instance_id) and
                inst_map[l.product_instance_id].serial and
                serial_query.lower() in inst_map[l.product_instance_id].serial.lower())
        ]
    else:
        logs = all_logs

    if not logs:
        logger.debug("No logs returned from query for user %s", username)

    def _make_row(log):
        inst = inst_map.get(log.product_instance_id)
        return {
            "serial": inst.serial if inst else "-",
            "model": inst.product.model if (inst and inst.product) else "-",
            "stage": log.to_stage,
            "action": log.action,
            "time": log.moved_at,
            "note": log.note,
            "team": log.to_team,
            "status": inst.status if inst else "-",
            "asset": inst.asset if inst else "-",
            "log_id": log.id,
        }

    if group_by in ['stage', 'action']:
        from collections import defaultdict
        grouped_log_rows = defaultdict(list)
        for log in logs:
            key = log.to_stage if group_by == 'stage' else log.action
            grouped_log_rows[key or "Unknown"].append(_make_row(log))
        log_rows = grouped_log_rows
        logger.debug("Group By Mode: %s, Keys: %s", group_by, list(grouped_log_rows.keys()))
    else:
        log_rows = [_make_row(log) for log in logs]

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
@reports_bp.route('/tech_profile_export/<username>', methods=['GET'])
@login_required
@module_required('reports', 'view')
def tech_profile_export(username):
    _require_reports_module()

    user = User.query.filter_by(username=username).first_or_404()
    if user.tenant_id != current_user.tenant_id:
        return "Access denied", 403
    # Apply same filters as profile page
    stage = request.args.get('stage')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    serial_query = request.args.get('serial')

    from inventory_flask_app.models import ProductInstance, Product
    query = ProductProcessLog.query.filter_by(moved_by=user.id).join(User).filter(User.tenant_id == current_user.tenant_id)
    if stage:
        query = query.filter(ProductProcessLog.to_stage == stage)
    if start_date:
        try:
            query = query.filter(ProductProcessLog.moved_at >= datetime.strptime(start_date, '%Y-%m-%d'))
        except ValueError:
            pass
    if end_date:
        try:
            query = query.filter(ProductProcessLog.moved_at < datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
        except ValueError:
            pass

    all_logs = query.order_by(ProductProcessLog.moved_at.desc()).all()

    instance_ids = [l.product_instance_id for l in all_logs if l.product_instance_id]
    inst_map = {}
    if instance_ids:
        inst_map = {
            i.id: i
            for i in ProductInstance.query.join(Product).filter(
                ProductInstance.id.in_(instance_ids),
                Product.tenant_id == current_user.tenant_id
            ).all()
        }

    if serial_query:
        logs = [
            l for l in all_logs
            if (inst_map.get(l.product_instance_id) and
                inst_map[l.product_instance_id].serial and
                serial_query.lower() in inst_map[l.product_instance_id].serial.lower())
        ]
    else:
        logs = all_logs

    csv_rows = []
    for log in logs:
        inst = inst_map.get(log.product_instance_id)
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
# ?threshold=1 narrows to units idle longer than the tenant-configured idle_threshold_days
@reports_bp.route('/idle_units', methods=['GET'])
@login_required
@module_required('reports', 'view')
def idle_units():
    _require_reports_module()

    from inventory_flask_app.models import ProductInstance, Product, TenantSettings
    from datetime import timedelta

    search = request.args.get('search', '').strip()
    model = request.args.get('model', '').strip()
    cpu = request.args.get('cpu', '').strip()
    show_threshold = request.args.get('threshold', '') == '1'

    settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings_dict = {s.key: s.value for s in settings}
    idle_threshold_days = int(settings_dict.get("idle_threshold_days", 7))

    query = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id,
        ProductInstance.status == 'idle'
    )

    if show_threshold:
        threshold_date = get_now_for_tenant() - timedelta(days=idle_threshold_days)
        query = query.filter(
            ProductInstance.updated_at < threshold_date,
            ProductInstance.is_sold == False
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

    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page')
    per_page = 50
    total = query.count()
    instances = query.offset(offset).limit(per_page).all()
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')

    rows = []
    for inst in instances:
        rows.append({
            "id": inst.id,
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

    return render_template(
        "idle_units.html",
        rows=rows,
        search=search,
        model=model,
        cpu=cpu,
        total_count=total,
        pagination=pagination,
        show_threshold=show_threshold,
        threshold_days=idle_threshold_days,
    )


@reports_bp.route('/update_idle_reason', methods=['POST'])
@login_required
@module_required('reports', 'full')
def update_idle_reason():

    serial = request.form.get('serial')
    idle_reason = request.form.get('idle_reason', '').strip()

    if not serial:
        flash("Serial is required to update idle reason.", "danger")
        return safe_redirect_back('reports_bp.idle_units')

    from inventory_flask_app.models import ProductInstance, Product
    instance = ProductInstance.query.join(Product).filter(
        ProductInstance.serial == serial,
        Product.tenant_id == current_user.tenant_id
    ).first()
    if not instance:
        flash(f"No unit found with serial {serial}.", "warning")
        return safe_redirect_back('reports_bp.idle_units')

    instance.idle_reason = idle_reason
    from inventory_flask_app import db
    db.session.commit()
    flash("Idle reason updated successfully.", "success")
    return safe_redirect_back('reports_bp.idle_units')
# Route to show technicians with slow processing units based on tenant-configured delay threshold
@reports_bp.route('/report/slow_technicians')
@login_required
@module_required('reports', 'view')
def slow_technicians():
    _require_reports_module()
    from inventory_flask_app.models import TenantSettings, ProductInstance, Product
    settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings_dict = {s.key: s.value for s in settings}
    delay_days = int(settings_dict.get("tech_delay_threshold_days", 3))

    now = get_now_for_tenant()
    delay_threshold = now - timedelta(days=delay_days)

    instances = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id,
        ProductInstance.entered_stage_at.isnot(None),
        ProductInstance.entered_stage_at < delay_threshold,
        ProductInstance.team_assigned.isnot(None),
        ProductInstance.is_sold == False
    ).all()

    return render_template(
        "slow_technicians.html",
        instances=instances,
        threshold_days=delay_days
    )


# ─────────────────────────────────────────────────────────────
# Stage Processing Time Report
# ─────────────────────────────────────────────────────────────
@reports_bp.route('/stage_times')
@login_required
@module_required('reports', 'view')
def stage_times():
    _require_reports_module()
    """Average time spent per processing stage, based on ProductProcessLog.duration_minutes."""
    from inventory_flask_app.models import ProductProcessLog, User, ProcessStage
    from sqlalchemy import func

    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    base_filter = [
        User.tenant_id == current_user.tenant_id,
        ProductProcessLog.duration_minutes != None,
        ProductProcessLog.to_stage != None,
    ]

    if start_date:
        try:
            base_filter.append(
                ProductProcessLog.moved_at >= datetime.strptime(start_date, '%Y-%m-%d')
            )
        except ValueError:
            start_date = ''
    if end_date:
        try:
            from datetime import timedelta as _td
            base_filter.append(
                ProductProcessLog.moved_at < datetime.strptime(end_date, '%Y-%m-%d') + _td(days=1)
            )
        except ValueError:
            end_date = ''

    rows = (
        db.session.query(
            ProductProcessLog.to_stage.label('stage'),
            func.avg(ProductProcessLog.duration_minutes).label('avg_minutes'),
            func.min(ProductProcessLog.duration_minutes).label('min_minutes'),
            func.max(ProductProcessLog.duration_minutes).label('max_minutes'),
            func.count(ProductProcessLog.id).label('total_moves'),
        )
        .join(User, ProductProcessLog.moved_by == User.id)
        .filter(*base_filter)
        .group_by(ProductProcessLog.to_stage)
        .order_by(func.avg(ProductProcessLog.duration_minutes).desc())
        .all()
    )

    from inventory_flask_app.utils.utils import format_duration

    stage_data = []
    for r in rows:
        avg_m = int(r.avg_minutes) if r.avg_minutes is not None else None
        stage_data.append({
            'stage': r.stage,
            'avg_minutes': avg_m,
            'avg_label': format_duration(avg_m),
            'min_label': format_duration(r.min_minutes),
            'max_label': format_duration(r.max_minutes),
            'total_moves': r.total_moves,
        })

    configured = {s.name: s for s in ProcessStage.query.filter_by(
        tenant_id=current_user.tenant_id).order_by(ProcessStage.order).all()}

    return render_template(
        'stage_times.html',
        stage_data=stage_data,
        configured=configured,
        start_date=start_date,
        end_date=end_date,
    )


@reports_bp.route('/stage_times/export')
@login_required
@module_required('reports', 'view')
def stage_times_export():
    _require_reports_module()
    from inventory_flask_app.models import ProcessStage

    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    base_filter = [
        User.tenant_id == current_user.tenant_id,
        ProductProcessLog.duration_minutes != None,
        ProductProcessLog.to_stage != None,
    ]
    if start_date:
        try:
            base_filter.append(ProductProcessLog.moved_at >= datetime.strptime(start_date, '%Y-%m-%d'))
        except ValueError:
            pass
    if end_date:
        try:
            base_filter.append(ProductProcessLog.moved_at < datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
        except ValueError:
            pass

    rows = (
        db.session.query(
            ProductProcessLog.to_stage.label('stage'),
            func.avg(ProductProcessLog.duration_minutes).label('avg_minutes'),
            func.min(ProductProcessLog.duration_minutes).label('min_minutes'),
            func.max(ProductProcessLog.duration_minutes).label('max_minutes'),
            func.count(ProductProcessLog.id).label('total_moves'),
        )
        .join(User, ProductProcessLog.moved_by == User.id)
        .filter(*base_filter)
        .group_by(ProductProcessLog.to_stage)
        .order_by(func.avg(ProductProcessLog.duration_minutes).desc())
        .all()
    )

    from inventory_flask_app.utils.utils import format_duration
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Stage', 'Avg Time', 'Min Time', 'Max Time', 'Total Moves'])
    for r in rows:
        avg_m = int(r.avg_minutes) if r.avg_minutes is not None else None
        writer.writerow([r.stage, format_duration(avg_m), format_duration(r.min_minutes), format_duration(r.max_minutes), r.total_moves])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='stage_times.csv'
    )


@reports_bp.route('/idle_units/export')
@login_required
@module_required('reports', 'view')
def idle_units_export():
    _require_reports_module()
    from inventory_flask_app.models import ProductInstance, Product

    instances = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id,
        ProductInstance.status == 'idle',
        ProductInstance.is_sold == False
    ).order_by(ProductInstance.updated_at.asc()).yield_per(200)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Serial', 'Asset', 'Item Name', 'Model', 'CPU', 'RAM', 'Grade', 'Technician', 'Idle Reason', 'Last Updated'])
    for inst in instances:
        writer.writerow([
            inst.serial or '',
            inst.asset or '',
            inst.product.item_name if inst.product else '',
            inst.product.model if inst.product else '',
            inst.product.cpu if inst.product else '',
            inst.product.ram if inst.product else '',
            inst.product.grade if inst.product else '',
            inst.assigned_user.username if inst.assigned_user else '',
            inst.note or inst.idle_reason or '',
            inst.updated_at.strftime('%Y-%m-%d %H:%M') if inst.updated_at else '',
        ])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='idle_units.csv'
    )


@reports_bp.route('/tech_productivity/export')
@login_required
@module_required('reports', 'view')
def tech_productivity_export():
    _require_reports_module()

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = ProductProcessLog.query.filter(ProductProcessLog.action == 'check-in')
    query = query.join(User).filter(User.tenant_id == current_user.tenant_id)
    if start_date and start_date != 'None':
        try:
            query = query.filter(ProductProcessLog.moved_at >= datetime.strptime(start_date, '%Y-%m-%d'))
        except ValueError:
            pass
    if end_date and end_date != 'None':
        try:
            query = query.filter(ProductProcessLog.moved_at < datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
        except ValueError:
            pass

    logs = query.all()
    summary = {}
    for log in logs:
        tech = log.user.username if log.user else 'Unknown'
        stage = log.to_stage or 'Unknown'
        key = (tech, stage)
        if key not in summary:
            summary[key] = {'tech': tech, 'stage': stage, 'count': 0, 'last': log.moved_at}
        summary[key]['count'] += 1
        if log.moved_at > summary[key]['last']:
            summary[key]['last'] = log.moved_at

    report = sorted(summary.values(), key=lambda x: (x['tech'], x['stage']))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Technician', 'Stage', 'Count', 'Last Activity'])
    for row in report:
        writer.writerow([row['tech'], row['stage'], row['count'],
                         row['last'].strftime('%Y-%m-%d %H:%M') if row['last'] else ''])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='tech_productivity.csv'
    )


@reports_bp.route('/report/slow_technicians/export')
@login_required
@module_required('reports', 'view')
def slow_technicians_export():
    _require_reports_module()
    from inventory_flask_app.models import TenantSettings, ProductInstance, Product

    settings_dict = {s.key: s.value for s in TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()}
    delay_days = int(settings_dict.get('tech_delay_threshold_days', 3) or 3)
    delay_threshold = get_now_for_tenant() - timedelta(days=delay_days)

    instances = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id,
        ProductInstance.entered_stage_at.isnot(None),
        ProductInstance.entered_stage_at < delay_threshold,
        ProductInstance.team_assigned.isnot(None),
        ProductInstance.is_sold == False
    ).yield_per(200)

    now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Serial', 'Asset', 'Model', 'Stage', 'Team', 'Last Updated', 'Days Delayed'])
    for inst in instances:
        days_delayed = (now_dt - inst.updated_at).days if inst.updated_at else ''
        writer.writerow([
            inst.serial or '',
            inst.asset or '',
            inst.product.model if inst.product else '',
            inst.process_stage or '',
            inst.team_assigned or '',
            inst.updated_at.strftime('%Y-%m-%d %H:%M') if inst.updated_at else '',
            days_delayed,
        ])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='slow_technicians.csv'
    )


# ─────────────────────────────────────────────────────────────
# Aged Inventory Report
# ─────────────────────────────────────────────────────────────
@reports_bp.route('/reports/aged_inventory')
@login_required
@module_required('reports', 'view')
def aged_inventory():
    _require_reports_module()
    from inventory_flask_app.models import ProductInstance, Product, TenantSettings

    settings_dict = {s.key: s.value for s in TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()}
    threshold_days = int(settings_dict.get('aged_threshold_days', 60) or 60)
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=threshold_days)

    rows = (
        db.session.query(
            Product.item_name.label('model'),
            Product.cpu.label('cpu'),
            Product.id.label('product_id'),
            func.count(ProductInstance.id).label('count'),
        )
        .join(ProductInstance, ProductInstance.product_id == Product.id)
        .filter(
            Product.tenant_id == current_user.tenant_id,
            ProductInstance.is_sold == False,
            ProductInstance.created_at < cutoff,
        )
        .group_by(Product.id, Product.item_name, Product.cpu)
        .order_by(func.count(ProductInstance.id).desc())
        .all()
    )

    grouped_instances = [
        {'item_name': r.model, 'cpu': r.cpu, 'product_id': r.product_id, 'count': r.count}
        for r in rows
    ]
    total_count = sum(g['count'] for g in grouped_instances)

    return render_template(
        'aged_inventory.html',
        grouped_instances=grouped_instances,
        threshold_days=threshold_days,
        total_count=total_count,
    )


@reports_bp.route('/reports/aged_inventory/export')
@login_required
@module_required('reports', 'view')
def aged_inventory_export():
    _require_reports_module()
    from inventory_flask_app.models import ProductInstance, Product, TenantSettings

    settings_dict = {s.key: s.value for s in TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()}
    threshold_days = int(settings_dict.get('aged_threshold_days', 60) or 60)
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=threshold_days)

    instances = (
        ProductInstance.query.join(Product)
        .filter(
            Product.tenant_id == current_user.tenant_id,
            ProductInstance.is_sold == False,
            ProductInstance.created_at < cutoff,
        )
        .order_by(ProductInstance.created_at.asc())
        .all()
    )

    now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Serial', 'Asset', 'Item Name', 'Model', 'CPU', 'RAM', 'Grade', 'Days In Stock', 'Status'])
    for inst in instances:
        days_in = (now_dt - inst.created_at).days if inst.created_at else ''
        writer.writerow([
            inst.serial or '',
            inst.asset or '',
            inst.product.item_name if inst.product else '',
            inst.product.model if inst.product else '',
            inst.product.cpu if inst.product else '',
            inst.product.ram if inst.product else '',
            inst.product.grade if inst.product else '',
            days_in,
            inst.status or '',
        ])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'aged_inventory_{threshold_days}days.csv'
    )


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _parse_date_range(default_days=30):
    """Return (start_dt, end_dt, start_str, end_str) from request args."""
    start_str = request.args.get('start_date', '').strip()
    end_str = request.args.get('end_date', '').strip()
    try:
        start_dt = datetime.strptime(start_str, '%Y-%m-%d') if start_str else \
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=default_days)
    except ValueError:
        start_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=default_days)
        start_str = ''
    try:
        end_dt = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1) if end_str else \
            datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
    except ValueError:
        end_dt = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
        end_str = ''
    return start_dt, end_dt, start_str, end_str


def _get_currency(tenant_id):
    from inventory_flask_app.models import TenantSettings
    s = TenantSettings.query.filter_by(tenant_id=tenant_id, key='currency').first()
    return s.value if s else 'AED'


# ─────────────────────────────────────────────────────────────
# Revenue Report
# ─────────────────────────────────────────────────────────────
@reports_bp.route('/reports/revenue')
@login_required
@module_required('reports', 'view')
def revenue_report():
    _require_reports_module()
    from inventory_flask_app.models import SaleTransaction, ProductInstance, Product

    start_dt, end_dt, start_str, end_str = _parse_date_range(30)
    currency = _get_currency(current_user.tenant_id)

    rows = (
        db.session.query(
            func.date(SaleTransaction.date_sold).label('sale_day'),
            func.count(SaleTransaction.id).label('units_sold'),
            func.sum(SaleTransaction.price_at_sale).label('total_revenue'),
            func.avg(SaleTransaction.price_at_sale).label('avg_price'),
        )
        .join(ProductInstance, SaleTransaction.product_instance_id == ProductInstance.id)
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(
            Product.tenant_id == current_user.tenant_id,
            SaleTransaction.date_sold >= start_dt,
            SaleTransaction.date_sold < end_dt,
        )
        .group_by(func.date(SaleTransaction.date_sold))
        .order_by(func.date(SaleTransaction.date_sold).desc())
        .all()
    )

    data = [
        {
            'date': r.sale_day,
            'units_sold': r.units_sold,
            'total_revenue': round(float(r.total_revenue or 0), 2),
            'avg_price': round(float(r.avg_price or 0), 2),
        }
        for r in rows
    ]
    total_revenue = sum(d['total_revenue'] for d in data)
    total_units = sum(d['units_sold'] for d in data)
    avg_price_overall = round(total_revenue / total_units, 2) if total_units else 0

    return render_template(
        'reports/revenue.html',
        data=data,
        total_revenue=round(total_revenue, 2),
        total_units=total_units,
        avg_price_overall=avg_price_overall,
        start_date=start_str,
        end_date=end_str,
        currency=currency,
    )


@reports_bp.route('/reports/revenue/export')
@login_required
@module_required('reports', 'view')
def revenue_export():
    _require_reports_module()
    from inventory_flask_app.models import SaleTransaction, ProductInstance, Product

    start_dt, end_dt, _, _ = _parse_date_range(30)
    currency = _get_currency(current_user.tenant_id)

    rows = (
        db.session.query(
            func.date(SaleTransaction.date_sold).label('sale_day'),
            func.count(SaleTransaction.id).label('units_sold'),
            func.sum(SaleTransaction.price_at_sale).label('total_revenue'),
            func.avg(SaleTransaction.price_at_sale).label('avg_price'),
        )
        .join(ProductInstance, SaleTransaction.product_instance_id == ProductInstance.id)
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(
            Product.tenant_id == current_user.tenant_id,
            SaleTransaction.date_sold >= start_dt,
            SaleTransaction.date_sold < end_dt,
        )
        .group_by(func.date(SaleTransaction.date_sold))
        .order_by(func.date(SaleTransaction.date_sold).desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', f'Units Sold', f'Total Revenue ({currency})', f'Avg Price ({currency})'])
    for r in rows:
        writer.writerow([r.sale_day, r.units_sold,
                         round(float(r.total_revenue or 0), 2),
                         round(float(r.avg_price or 0), 2)])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='revenue_report.csv'
    )


# ─────────────────────────────────────────────────────────────
# Sales by Model
# ─────────────────────────────────────────────────────────────
@reports_bp.route('/reports/sales_by_model')
@login_required
@module_required('reports', 'view')
def sales_by_model():
    _require_reports_module()
    from inventory_flask_app.models import SaleTransaction, ProductInstance, Product

    start_dt, end_dt, start_str, end_str = _parse_date_range(365)
    currency = _get_currency(current_user.tenant_id)

    q = (
        db.session.query(
            Product.item_name.label('model'),
            Product.make.label('make'),
            func.count(SaleTransaction.id).label('units_sold'),
            func.sum(SaleTransaction.price_at_sale).label('total_revenue'),
            func.avg(SaleTransaction.price_at_sale).label('avg_price'),
        )
        .join(ProductInstance, SaleTransaction.product_instance_id == ProductInstance.id)
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(Product.tenant_id == current_user.tenant_id)
    )
    if start_str:
        q = q.filter(SaleTransaction.date_sold >= start_dt)
    if end_str:
        q = q.filter(SaleTransaction.date_sold < end_dt)

    rows = (
        q.group_by(Product.id, Product.item_name, Product.make)
        .order_by(func.count(SaleTransaction.id).desc())
        .all()
    )

    data = [
        {
            'model': r.model or '—',
            'make': r.make or '—',
            'units_sold': r.units_sold,
            'total_revenue': round(float(r.total_revenue or 0), 2),
            'avg_price': round(float(r.avg_price or 0), 2),
        }
        for r in rows
    ]
    total_units = sum(d['units_sold'] for d in data)
    total_revenue = round(sum(d['total_revenue'] for d in data), 2)

    return render_template(
        'reports/sales_by_model.html',
        data=data,
        total_units=total_units,
        total_revenue=total_revenue,
        start_date=start_str,
        end_date=end_str,
        currency=currency,
    )


@reports_bp.route('/reports/sales_by_model/export')
@login_required
@module_required('reports', 'view')
def sales_by_model_export():
    _require_reports_module()
    from inventory_flask_app.models import SaleTransaction, ProductInstance, Product

    start_dt, end_dt, start_str, end_str = _parse_date_range(365)
    currency = _get_currency(current_user.tenant_id)

    q = (
        db.session.query(
            Product.item_name.label('model'),
            Product.make.label('make'),
            func.count(SaleTransaction.id).label('units_sold'),
            func.sum(SaleTransaction.price_at_sale).label('total_revenue'),
            func.avg(SaleTransaction.price_at_sale).label('avg_price'),
        )
        .join(ProductInstance, SaleTransaction.product_instance_id == ProductInstance.id)
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(Product.tenant_id == current_user.tenant_id)
    )
    if start_str:
        q = q.filter(SaleTransaction.date_sold >= start_dt)
    if end_str:
        q = q.filter(SaleTransaction.date_sold < end_dt)

    rows = q.group_by(Product.id, Product.item_name, Product.make).order_by(func.count(SaleTransaction.id).desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Model', 'Make', 'Units Sold', f'Total Revenue ({currency})', f'Avg Price ({currency})'])
    for r in rows:
        writer.writerow([r.model or '', r.make or '', r.units_sold,
                         round(float(r.total_revenue or 0), 2), round(float(r.avg_price or 0), 2)])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='sales_by_model.csv'
    )


# ─────────────────────────────────────────────────────────────
# Sales by Customer
# ─────────────────────────────────────────────────────────────
@reports_bp.route('/reports/sales_by_customer')
@login_required
@module_required('reports', 'view')
def sales_by_customer():
    _require_reports_module()
    from inventory_flask_app.models import SaleTransaction, ProductInstance, Product, Customer

    start_dt, end_dt, start_str, end_str = _parse_date_range(365)
    currency = _get_currency(current_user.tenant_id)

    q = (
        db.session.query(
            Customer.id.label('customer_id'),
            Customer.name.label('name'),
            Customer.phone.label('phone'),
            Customer.email.label('email'),
            func.count(SaleTransaction.id).label('units_bought'),
            func.sum(SaleTransaction.price_at_sale).label('total_spent'),
            func.max(SaleTransaction.date_sold).label('last_purchase'),
        )
        .join(SaleTransaction, SaleTransaction.customer_id == Customer.id)
        .join(ProductInstance, SaleTransaction.product_instance_id == ProductInstance.id)
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(Product.tenant_id == current_user.tenant_id)
    )
    if start_str:
        q = q.filter(SaleTransaction.date_sold >= start_dt)
    if end_str:
        q = q.filter(SaleTransaction.date_sold < end_dt)

    rows = (
        q.group_by(Customer.id, Customer.name, Customer.phone, Customer.email)
        .order_by(func.sum(SaleTransaction.price_at_sale).desc())
        .all()
    )

    data = [
        {
            'customer_id': r.customer_id,
            'name': r.name or '—',
            'phone': r.phone or '',
            'email': r.email or '',
            'units_bought': r.units_bought,
            'total_spent': round(float(r.total_spent or 0), 2),
            'last_purchase': r.last_purchase,
        }
        for r in rows
    ]
    total_customers = len(data)
    total_revenue = round(sum(d['total_spent'] for d in data), 2)

    return render_template(
        'reports/sales_by_customer.html',
        data=data,
        total_customers=total_customers,
        total_revenue=total_revenue,
        start_date=start_str,
        end_date=end_str,
        currency=currency,
    )


@reports_bp.route('/reports/sales_by_customer/export')
@login_required
@module_required('reports', 'view')
def sales_by_customer_export():
    _require_reports_module()
    from inventory_flask_app.models import SaleTransaction, ProductInstance, Product, Customer

    start_dt, end_dt, start_str, end_str = _parse_date_range(365)
    currency = _get_currency(current_user.tenant_id)

    q = (
        db.session.query(
            Customer.name.label('name'),
            Customer.phone.label('phone'),
            Customer.email.label('email'),
            func.count(SaleTransaction.id).label('units_bought'),
            func.sum(SaleTransaction.price_at_sale).label('total_spent'),
            func.max(SaleTransaction.date_sold).label('last_purchase'),
        )
        .join(SaleTransaction, SaleTransaction.customer_id == Customer.id)
        .join(ProductInstance, SaleTransaction.product_instance_id == ProductInstance.id)
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(Product.tenant_id == current_user.tenant_id)
    )
    if start_str:
        q = q.filter(SaleTransaction.date_sold >= start_dt)
    if end_str:
        q = q.filter(SaleTransaction.date_sold < end_dt)

    rows = q.group_by(Customer.id, Customer.name, Customer.phone, Customer.email).order_by(func.sum(SaleTransaction.price_at_sale).desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Customer', 'Phone', 'Email', 'Units Bought', f'Total Spent ({currency})', 'Last Purchase'])
    for r in rows:
        writer.writerow([r.name or '', r.phone or '', r.email or '', r.units_bought,
                         round(float(r.total_spent or 0), 2),
                         r.last_purchase.strftime('%Y-%m-%d') if r.last_purchase else ''])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='sales_by_customer.csv'
    )


# ─────────────────────────────────────────────────────────────
# Purchase Orders Report
# ─────────────────────────────────────────────────────────────
@reports_bp.route('/reports/purchase_orders')
@login_required
@module_required('reports', 'view')
def purchase_orders_report():
    _require_reports_module()
    from inventory_flask_app.models import PurchaseOrder, PurchaseOrderItem
    from sqlalchemy import case as sa_case

    status_filter = request.args.get('status', '').strip()

    q = (
        db.session.query(
            PurchaseOrder,
            func.count(PurchaseOrderItem.id).label('total_items'),
            func.sum(sa_case((PurchaseOrderItem.status == 'received', 1), else_=0)).label('received'),
            func.sum(sa_case((PurchaseOrderItem.status == 'missing', 1), else_=0)).label('missing'),
            func.sum(sa_case((PurchaseOrderItem.status == 'expected', 1), else_=0)).label('expected'),
        )
        .outerjoin(PurchaseOrderItem, PurchaseOrderItem.po_id == PurchaseOrder.id)
        .filter(PurchaseOrder.tenant_id == current_user.tenant_id)
    )
    if status_filter:
        q = q.filter(PurchaseOrder.status == status_filter)

    rows = (
        q.group_by(PurchaseOrder.id)
        .order_by(PurchaseOrder.created_at.desc())
        .all()
    )

    data = [
        {
            'po': r.PurchaseOrder,
            'total_items': r.total_items or 0,
            'received': r.received or 0,
            'missing': r.missing or 0,
            'expected': r.expected or 0,
        }
        for r in rows
    ]

    return render_template(
        'reports/purchase_orders.html',
        data=data,
        status_filter=status_filter,
    )


@reports_bp.route('/reports/purchase_orders/export')
@login_required
@module_required('reports', 'view')
def purchase_orders_export():
    _require_reports_module()
    from inventory_flask_app.models import PurchaseOrder, PurchaseOrderItem
    from sqlalchemy import case as sa_case

    rows = (
        db.session.query(
            PurchaseOrder,
            func.count(PurchaseOrderItem.id).label('total_items'),
            func.sum(sa_case((PurchaseOrderItem.status == 'received', 1), else_=0)).label('received'),
            func.sum(sa_case((PurchaseOrderItem.status == 'missing', 1), else_=0)).label('missing'),
        )
        .outerjoin(PurchaseOrderItem, PurchaseOrderItem.po_id == PurchaseOrder.id)
        .filter(PurchaseOrder.tenant_id == current_user.tenant_id)
        .group_by(PurchaseOrder.id)
        .order_by(PurchaseOrder.created_at.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['PO Number', 'Vendor', 'Status', 'Total Items', 'Received', 'Missing', 'Created'])
    for r in rows:
        po = r.PurchaseOrder
        writer.writerow([
            po.po_number,
            po.vendor.name if po.vendor else '',
            po.status,
            r.total_items or 0,
            r.received or 0,
            r.missing or 0,
            po.created_at.strftime('%Y-%m-%d') if po.created_at else '',
        ])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='purchase_orders.csv'
    )


# ─────────────────────────────────────────────────────────────
# Returns Report
# ─────────────────────────────────────────────────────────────
@reports_bp.route('/reports/returns')
@login_required
@module_required('reports', 'view')
def returns_report():
    _require_reports_module()
    from inventory_flask_app.models import Return, ProductInstance, Product

    start_dt, end_dt, start_str, end_str = _parse_date_range(90)

    q = (
        db.session.query(Return, ProductInstance, Product)
        .join(ProductInstance, Return.instance_id == ProductInstance.id)
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(Return.tenant_id == current_user.tenant_id)
    )
    if start_str:
        q = q.filter(Return.return_date >= start_dt)
    if end_str:
        q = q.filter(Return.return_date < end_dt)

    rows = q.order_by(Return.return_date.desc()).all()

    data = [
        {
            'id': r.Return.id,
            'return_date': r.Return.return_date,
            'serial': r.ProductInstance.serial,
            'asset': r.ProductInstance.asset,
            'model': r.Product.item_name or r.Product.model or '—',
            'reason': r.Return.reason or '',
            'condition': r.Return.condition or '',
            'action': r.Return.action or '',
            'notes': r.Return.notes or '',
        }
        for r in rows
    ]

    return render_template(
        'reports/returns.html',
        data=data,
        start_date=start_str,
        end_date=end_str,
        total=len(data),
    )


@reports_bp.route('/reports/returns/export')
@login_required
@module_required('reports', 'view')
def returns_export():
    _require_reports_module()
    from inventory_flask_app.models import Return, ProductInstance, Product

    start_dt, end_dt, start_str, end_str = _parse_date_range(90)

    q = (
        db.session.query(Return, ProductInstance, Product)
        .join(ProductInstance, Return.instance_id == ProductInstance.id)
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(Return.tenant_id == current_user.tenant_id)
    )
    if start_str:
        q = q.filter(Return.return_date >= start_dt)
    if end_str:
        q = q.filter(Return.return_date < end_dt)

    rows = q.order_by(Return.return_date.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Return Date', 'Serial', 'Asset', 'Model', 'Reason', 'Condition', 'Action', 'Notes'])
    for r in rows:
        writer.writerow([
            r.Return.return_date.strftime('%Y-%m-%d') if r.Return.return_date else '',
            r.ProductInstance.serial or '',
            r.ProductInstance.asset or '',
            r.Product.item_name or r.Product.model or '',
            r.Return.reason or '',
            r.Return.condition or '',
            r.Return.action or '',
            r.Return.notes or '',
        ])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='returns_report.csv'
    )


# ─────────────────────────────────────────────────────────────
# Parts Usage Report
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# Parts Sales Report
# ─────────────────────────────────────────────────────────────
@reports_bp.route('/reports/parts_sales')
@login_required
@module_required('reports', 'view')
def parts_sales_report():
    _require_reports_module()
    from inventory_flask_app.models import PartSaleTransaction, PartSaleItem, Part, Customer

    start_dt, end_dt, start_str, end_str = _parse_date_range(90)

    txns = (
        PartSaleTransaction.query
        .filter(PartSaleTransaction.tenant_id == current_user.tenant_id)
        .filter(PartSaleTransaction.sold_at >= start_dt)
        .filter(PartSaleTransaction.sold_at < end_dt)
        .order_by(PartSaleTransaction.sold_at.desc())
        .all()
    )

    rows = []
    for t in txns:
        customer_label = ''
        if t.customer:
            customer_label = t.customer.name
        elif t.customer_name:
            customer_label = t.customer_name
        else:
            customer_label = 'Walk-in'
        item_count = sum(i.quantity for i in t.line_items)
        rows.append({
            'id': t.id,
            'invoice': t.invoice_number,
            'date': t.sold_at,
            'customer': customer_label,
            'items': item_count,
            'total': float(t.total_amount or 0),
            'payment': t.payment_method,
            'status': t.payment_status,
            'seller': t.seller.username if t.seller else '—',
        })

    total_revenue = sum(r['total'] for r in rows)
    return render_template(
        'reports/parts_sales.html',
        rows=rows,
        start_date=start_str,
        end_date=end_str,
        total_revenue=total_revenue,
        total_txns=len(rows),
    )


@reports_bp.route('/reports/parts_sales/export')
@login_required
@module_required('reports', 'view')
def parts_sales_export():
    _require_reports_module()
    from inventory_flask_app.models import PartSaleTransaction

    start_dt, end_dt, start_str, end_str = _parse_date_range(90)

    txns = (
        PartSaleTransaction.query
        .filter(PartSaleTransaction.tenant_id == current_user.tenant_id)
        .filter(PartSaleTransaction.sold_at >= start_dt)
        .filter(PartSaleTransaction.sold_at < end_dt)
        .order_by(PartSaleTransaction.sold_at.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Invoice', 'Customer', 'Items Qty', 'Total', 'Payment', 'Status', 'Sold By'])
    for t in txns:
        customer_label = ''
        if t.customer:
            customer_label = t.customer.name
        elif t.customer_name:
            customer_label = t.customer_name
        else:
            customer_label = 'Walk-in'
        item_count = sum(i.quantity for i in t.line_items)
        writer.writerow([
            t.sold_at.strftime('%Y-%m-%d %H:%M') if t.sold_at else '',
            t.invoice_number,
            customer_label,
            item_count,
            float(t.total_amount or 0),
            t.payment_method or '',
            t.payment_status or '',
            t.seller.username if t.seller else '',
        ])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='parts_sales.csv',
    )


@reports_bp.route('/reports/parts_usage')
@login_required
@module_required('reports', 'view')
def parts_usage_report():
    _require_reports_module()
    from inventory_flask_app.models import PartUsage, Part

    start_dt, end_dt, start_str, end_str = _parse_date_range(90)

    q = (
        db.session.query(
            Part.id.label('part_id'),
            Part.name.label('part_name'),
            Part.part_number.label('part_number'),
            Part.part_type.label('part_type'),
            func.sum(PartUsage.quantity).label('total_used'),
            func.count(PartUsage.id).label('usage_events'),
        )
        .join(PartUsage, PartUsage.part_id == Part.id)
        .filter(Part.tenant_id == current_user.tenant_id)
    )
    if start_str:
        q = q.filter(PartUsage.used_at >= start_dt)
    if end_str:
        q = q.filter(PartUsage.used_at < end_dt)

    rows = (
        q.group_by(Part.id, Part.name, Part.part_number, Part.part_type)
        .order_by(func.sum(PartUsage.quantity).desc())
        .all()
    )

    data = [
        {
            'part_id': r.part_id,
            'part_name': r.part_name,
            'part_number': r.part_number,
            'part_type': r.part_type or '',
            'total_used': r.total_used or 0,
            'usage_events': r.usage_events,
        }
        for r in rows
    ]

    return render_template(
        'reports/parts_usage.html',
        data=data,
        start_date=start_str,
        end_date=end_str,
        total_parts=len(data),
        total_qty=sum(d['total_used'] for d in data),
    )


@reports_bp.route('/reports/parts_usage/export')
@login_required
@module_required('reports', 'view')
def parts_usage_export():
    _require_reports_module()
    from inventory_flask_app.models import PartUsage, Part

    start_dt, end_dt, start_str, end_str = _parse_date_range(90)

    q = (
        db.session.query(
            Part.name.label('part_name'),
            Part.part_number.label('part_number'),
            Part.part_type.label('part_type'),
            func.sum(PartUsage.quantity).label('total_used'),
            func.count(PartUsage.id).label('usage_events'),
        )
        .join(PartUsage, PartUsage.part_id == Part.id)
        .filter(Part.tenant_id == current_user.tenant_id)
    )
    if start_str:
        q = q.filter(PartUsage.used_at >= start_dt)
    if end_str:
        q = q.filter(PartUsage.used_at < end_dt)

    rows = q.group_by(Part.id, Part.name, Part.part_number, Part.part_type).order_by(func.sum(PartUsage.quantity).desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Part Name', 'Part #', 'Type', 'Total Used', 'Usage Events'])
    for r in rows:
        writer.writerow([r.part_name, r.part_number, r.part_type or '', r.total_used or 0, r.usage_events])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='parts_usage.csv'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Activity / Audit Log — full tenant-scoped browse of ProductProcessLog
# ─────────────────────────────────────────────────────────────────────────────
def _build_activity_query(tid):
    """Return a base query + applied filters from request.args for the activity log."""
    from inventory_flask_app.models import ProductProcessLog, ProductInstance, Product
    from sqlalchemy.orm import joinedload as _jl

    q_search   = request.args.get('q', '').strip()
    f_action   = request.args.get('action', '').strip()
    f_user     = request.args.get('user_id', '').strip()
    f_date_from = request.args.get('date_from', '').strip()
    f_date_to   = request.args.get('date_to', '').strip()

    query = (
        ProductProcessLog.query
        .join(ProductInstance, ProductProcessLog.product_instance_id == ProductInstance.id)
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(Product.tenant_id == tid)
        .options(
            _jl(ProductProcessLog.product_instance).joinedload(ProductInstance.product),
            _jl(ProductProcessLog.user),
        )
    )

    if q_search:
        from inventory_flask_app.utils.utils import escape_like
        esc = escape_like(q_search)
        query = query.filter(
            or_(
                ProductInstance.serial.ilike(f'%{esc}%'),
                ProductInstance.asset.ilike(f'%{esc}%'),
                ProductProcessLog.note.ilike(f'%{esc}%'),
            )
        )

    if f_action:
        query = query.filter(ProductProcessLog.action == f_action)

    if f_user:
        try:
            query = query.filter(ProductProcessLog.moved_by == int(f_user))
        except ValueError:
            pass

    if f_date_from:
        try:
            query = query.filter(ProductProcessLog.moved_at >= datetime.strptime(f_date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if f_date_to:
        try:
            query = query.filter(
                ProductProcessLog.moved_at < datetime.strptime(f_date_to, '%Y-%m-%d') + timedelta(days=1)
            )
        except ValueError:
            pass

    return query


@reports_bp.route('/reports/activity_log')
@login_required
@module_required('reports', 'view')
def activity_log():
    """Browse all ProductProcessLog entries for the tenant."""
    from inventory_flask_app.models import ProductProcessLog, ProductInstance, Product, User

    tid     = current_user.tenant_id
    page    = request.args.get('page', 1, type=int)
    per_page = 50

    query = _build_activity_query(tid)

    # Distinct action types for dropdown
    action_types = (
        db.session.query(ProductProcessLog.action)
        .join(ProductInstance, ProductProcessLog.product_instance_id == ProductInstance.id)
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(Product.tenant_id == tid, ProductProcessLog.action.isnot(None))
        .distinct()
        .order_by(ProductProcessLog.action)
        .all()
    )
    action_list = [r[0] for r in action_types if r[0]]

    # Users who appear in the log
    uid_rows = (
        db.session.query(ProductProcessLog.moved_by)
        .join(ProductInstance, ProductProcessLog.product_instance_id == ProductInstance.id)
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(Product.tenant_id == tid, ProductProcessLog.moved_by.isnot(None))
        .distinct()
        .all()
    )
    user_ids = [r[0] for r in uid_rows if r[0]]
    users = User.query.filter(User.id.in_(user_ids)).order_by(User.username).all() if user_ids else []

    total       = query.count()
    logs        = query.order_by(ProductProcessLog.moved_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template('reports/activity_log.html',
        logs=logs,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        q_search=request.args.get('q', '').strip(),
        f_action=request.args.get('action', '').strip(),
        f_user=request.args.get('user_id', '').strip(),
        f_date_from=request.args.get('date_from', '').strip(),
        f_date_to=request.args.get('date_to', '').strip(),
        action_list=action_list,
        users=users,
    )


@reports_bp.route('/reports/activity_log/export')
@login_required
@module_required('reports', 'view')
def activity_log_export():
    """CSV export of the filtered activity log (no pagination)."""
    from inventory_flask_app.models import ProductProcessLog

    tid   = current_user.tenant_id
    query = _build_activity_query(tid)
    logs  = query.order_by(ProductProcessLog.moved_at.desc()).limit(10000).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Timestamp', 'User', 'Serial', 'Asset', 'Action',
                     'From Stage', 'To Stage', 'Duration (min)', 'Note'])
    for log in logs:
        inst = log.product_instance
        writer.writerow([
            log.moved_at.strftime('%Y-%m-%d %H:%M:%S') if log.moved_at else '',
            (log.user.full_name or log.user.username) if log.user else 'System',
            inst.serial if inst else '',
            inst.asset if inst else '',
            log.action or '',
            log.from_stage or '',
            log.to_stage or '',
            log.duration_minutes if log.duration_minutes is not None else '',
            log.note or '',
        ])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='activity_log.csv',
    )
