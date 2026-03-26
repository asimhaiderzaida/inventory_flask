"""Mail utility functions: low-stock alerts, SLA alerts, reservation emails."""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Communication log helper
# ─────────────────────────────────────────────────────────────

def _log_communication(customer_id, tenant_id, comm_type, subject, sent_by_id=None):
    """Record a sent email in CustomerCommunication. Never raises."""
    try:
        from ..models import db, CustomerCommunication
        entry = CustomerCommunication(
            tenant_id=tenant_id,
            customer_id=customer_id,
            type=comm_type,
            subject=subject,
            sent_by=sent_by_id,
            sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        logger.warning("Failed to log communication for customer %s: %s", customer_id, e)


# ─────────────────────────────────────────────────────────────
# Email template helper
# ─────────────────────────────────────────────────────────────

def _render_email_template(tenant_id, key, placeholders):
    """Return a custom email body from TenantSettings with placeholders substituted.

    placeholders — dict of {name: value}.  Missing keys are silently replaced
    with an empty string so a partially-filled template never raises KeyError.

    Returns None if no custom template is stored, so callers can fall back to
    their built-in default body.
    """
    from ..models import TenantSettings
    setting = TenantSettings.query.filter_by(tenant_id=tenant_id, key=key).first()
    if not setting or not (setting.value or '').strip():
        return None
    safe = defaultdict(str, placeholders)
    try:
        return setting.value.format_map(safe)
    except Exception:
        # Malformed template — return raw value rather than crashing
        return setting.value


# ─────────────────────────────────────────────────────────────
# Reservation email helpers
# ─────────────────────────────────────────────────────────────

def _get_reservation_settings(tenant_id):
    """Return (enabled, company_name, contact_line) for reservation emails."""
    from ..models import TenantSettings
    rows = TenantSettings.query.filter_by(tenant_id=tenant_id).all()
    s = {r.key: r.value for r in rows}
    enabled = s.get('enable_email_alerts') == 'true'
    company = s.get('company_name') or s.get('invoice_title') or s.get('dashboard_name') or 'Us'
    contact_parts = []
    if s.get('support_email'):
        contact_parts.append(s['support_email'])
    if s.get('company_address'):
        contact_parts.append(s['company_address'])
    contact = '  |  '.join(contact_parts) if contact_parts else ''
    return enabled, company, contact


def _format_unit_lines(units):
    """Format a list of unit dicts into readable text lines."""
    lines = []
    for u in units:
        parts = [u.get('model') or '']
        specs = []
        if u.get('cpu'):
            specs.append(u['cpu'])
        if u.get('ram'):
            specs.append(u['ram'])
        if u.get('disk1size'):
            specs.append(u['disk1size'])
        if specs:
            parts.append(', '.join(specs))
        desc = ' — '.join(p for p in parts if p)
        lines.append(f"  • Serial: {u.get('serial') or '—'}   {desc}")
    return '\n'.join(lines)


def send_reservation_confirmation(customer, units, tenant_id):
    """Email the customer confirming their reservation.

    units — list of dicts with keys: serial, model, cpu, ram, disk1size
    Silently skips if enable_email_alerts is off or customer has no email.
    Wraps all errors so caller is never affected.
    """
    from .. import mail
    from flask_mail import Message

    if not customer.email:
        logger.debug("Reservation confirmation skipped: no email for customer %s", customer.id)
        return False

    enabled, company, contact = _get_reservation_settings(tenant_id)
    if not enabled:
        logger.debug("Reservation email skipped: enable_email_alerts off for tenant %s", tenant_id)
        return False

    try:
        unit_lines = _format_unit_lines(units)
        placeholders = {
            'customer_name': customer.name,
            'company_name': company,
            'unit_details': unit_lines,
            'portal_link': '',
        }
        body = _render_email_template(tenant_id, 'email_tpl_reservation', placeholders)
        if body is None:
            body = (
                f"Dear {customer.name},\n\n"
                f"Your reservation has been confirmed for {len(units)} unit(s):\n\n"
                f"{unit_lines}\n\n"
                f"Reserved on: {datetime.now(timezone.utc).replace(tzinfo=None).strftime('%d %b %Y')}\n\n"
                f"We will notify you when your unit(s) are ready for pickup. "
                f"If you have any questions, please contact us.\n"
            )
            if contact:
                body += f"\nContact: {contact}\n"
            body += f"\nBest regards,\n{company}\n"

        msg = Message(
            subject=f"Your reservation is confirmed — {company}",
            recipients=[customer.email],
            body=body,
        )
        mail.send(msg)
        logger.info("Reservation confirmation sent to %s (customer %s)", customer.email, customer.id)
        _log_communication(
            customer_id=customer.id, tenant_id=tenant_id,
            comm_type='reservation_confirmation',
            subject=f"Your reservation is confirmed — {company}",
        )
        return True

    except Exception as e:
        logger.error("Failed to send reservation confirmation to %s: %s", customer.email, e)
        return False


def send_reservation_ready(customer, units, tenant_id):
    """Email the customer that their unit(s) are ready for pickup.

    units — list of dicts with keys: serial, model, cpu, ram, disk1size
    Silently skips if enable_email_alerts is off or customer has no email.
    Wraps all errors so caller is never affected.
    """
    from .. import mail
    from flask_mail import Message

    if not customer.email:
        logger.debug("Reservation ready email skipped: no email for customer %s", customer.id)
        return False

    enabled, company, contact = _get_reservation_settings(tenant_id)
    if not enabled:
        logger.debug("Reservation ready email skipped: enable_email_alerts off for tenant %s", tenant_id)
        return False

    try:
        unit_lines = _format_unit_lines(units)
        placeholders = {
            'customer_name': customer.name,
            'company_name': company,
            'unit_details': unit_lines,
            'portal_link': '',
        }
        body = _render_email_template(tenant_id, 'email_tpl_ready', placeholders)
        if body is None:
            body = (
                f"Dear {customer.name},\n\n"
                f"Great news! Your reserved unit(s) are now ready for pickup:\n\n"
                f"{unit_lines}\n\n"
                f"Please contact us to arrange collection at your earliest convenience.\n"
            )
            if contact:
                body += f"\nContact: {contact}\n"
            body += f"\nBest regards,\n{company}\n"

        msg = Message(
            subject=f"Your unit is ready for pickup — {company}",
            recipients=[customer.email],
            body=body,
        )
        mail.send(msg)
        logger.info("Reservation ready email sent to %s (customer %s)", customer.email, customer.id)
        _log_communication(
            customer_id=customer.id, tenant_id=tenant_id,
            comm_type='ready_pickup',
            subject=f"Your unit is ready for pickup — {company}",
        )
        return True

    except Exception as e:
        logger.error("Failed to send reservation ready email to %s: %s", customer.email, e)
        return False


def get_low_stock_parts(tenant_id):
    """Return Part objects whose total stock across all locations is below min_stock.

    Each returned part has a ``_current_stock`` attribute attached for use in
    templates without a second DB hit.
    """
    from ..models import Part, PartStock, db
    from sqlalchemy import func

    # Single aggregation query — no N+1
    stock_totals = dict(
        db.session.query(PartStock.part_id, func.sum(PartStock.quantity))
        .join(Part, Part.id == PartStock.part_id)
        .filter(Part.tenant_id == tenant_id)
        .group_by(PartStock.part_id)
        .all()
    )

    parts = Part.query.filter_by(tenant_id=tenant_id).all()
    low = []
    for part in parts:
        total = stock_totals.get(part.id, 0) or 0
        if total < (part.min_stock or 1):
            part._current_stock = total
            low.append(part)
    return low


def maybe_send_low_stock_email(tenant_id):
    """Send a low-stock summary email to the tenant's support_email.

    Respects a 24-hour cooldown stored in TenantSettings so the admin is not
    flooded on every page load.
    """
    from ..models import TenantSettings, db
    from .. import mail
    from flask_mail import Message
    from flask import current_app

    # Check the feature flag
    enabled_setting = TenantSettings.query.filter_by(
        tenant_id=tenant_id, key='enable_low_stock_alerts'
    ).first()
    if not enabled_setting or enabled_setting.value != 'true':
        logger.debug("Low-stock alerts disabled for tenant %s", tenant_id)
        return

    # Get recipient from tenant settings
    recipient_setting = TenantSettings.query.filter_by(
        tenant_id=tenant_id, key='support_email'
    ).first()
    admin_email = recipient_setting.value if recipient_setting else None

    if not admin_email:
        logger.debug("Low-stock email skipped: no support_email configured for tenant %s", tenant_id)
        return

    # Check 24-hour cooldown
    notif_setting = TenantSettings.query.filter_by(
        tenant_id=tenant_id, key='low_stock_last_notified'
    ).first()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if notif_setting and notif_setting.value:
        try:
            last_sent = datetime.fromisoformat(notif_setting.value)
            if now - last_sent < timedelta(hours=24):
                return
        except (ValueError, TypeError):
            pass

    low_stock = get_low_stock_parts(tenant_id)
    if not low_stock:
        return

    try:
        lines = "\n".join(
            f"  • {p.name} ({p.part_number}): "
            f"{p._current_stock} in stock (minimum: {p.min_stock})"
            for p in low_stock
        )

        # Resolve company name for placeholders
        from ..models import TenantSettings as _TS
        _settings = {s.key: s.value for s in _TS.query.filter_by(tenant_id=tenant_id).all()}
        company = _settings.get('company_name') or _settings.get('dashboard_name') or ''

        placeholders = {'company_name': company, 'unit_details': lines}
        body = _render_email_template(tenant_id, 'email_tpl_low_stock', placeholders)
        if body is None:
            body = (
                "Low Stock Alert\n"
                "===============\n\n"
                f"The following {len(low_stock)} part(s) are below their minimum stock level:\n\n"
                f"{lines}\n\n"
                "Please reorder these items at your earliest convenience.\n"
            )

        msg = Message(
            subject=f"⚠ Low Stock Alert — {len(low_stock)} part(s) need restocking",
            recipients=[admin_email],
            body=body,
        )
        mail.send(msg)
        logger.info("Low-stock alert sent to %s for tenant %s", admin_email, tenant_id)

        # Record send time
        if not notif_setting:
            notif_setting = TenantSettings(
                tenant_id=tenant_id,
                key='low_stock_last_notified',
                value=now.isoformat()
            )
            db.session.add(notif_setting)
        else:
            notif_setting.value = now.isoformat()
        db.session.commit()

    except Exception as e:
        logger.error("Failed to send low-stock email for tenant %s: %s", tenant_id, e)


# ─────────────────────────────────────────────────────────────
# SLA Overdue Alerts
# ─────────────────────────────────────────────────────────────

def get_overdue_units(tenant_id):
    """Return a list of dicts for every unit currently past its stage SLA.

    Each dict has: instance, serial, stage, sla_hours, hours_in_stage, hours_over, assignee.
    Only units with status='under_process', a set entered_stage_at, and a stage
    whose SLA > 0 are considered.
    """
    from ..models import ProcessStage, ProductInstance, Product

    stages = ProcessStage.query.filter_by(tenant_id=tenant_id).all()
    sla_map = {s.name: s.sla_hours for s in stages if s.sla_hours and s.sla_hours > 0}
    if not sla_map:
        return []

    units = (
        ProductInstance.query.join(Product)
        .filter(
            Product.tenant_id == tenant_id,
            ProductInstance.status == 'under_process',
            ProductInstance.entered_stage_at != None,
            ProductInstance.process_stage != None,
        )
        .all()
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    overdue = []
    for unit in units:
        stage = (unit.process_stage or '').strip()
        sla_h = sla_map.get(stage, 0)
        if sla_h <= 0:
            continue

        since = unit.entered_stage_at
        # Normalize to naive UTC for arithmetic
        if hasattr(since, 'utcoffset') and since.utcoffset() is not None:
            since = since.replace(tzinfo=None) - since.utcoffset()

        hours_in_stage = (now - since).total_seconds() / 3600
        if hours_in_stage > sla_h:
            overdue.append({
                'instance': unit,
                'serial': unit.serial,
                'stage': stage,
                'sla_hours': sla_h,
                'hours_in_stage': round(hours_in_stage, 1),
                'hours_over': round(hours_in_stage - sla_h, 1),
                'assignee': unit.assigned_user.username if unit.assigned_user else 'unassigned',
            })

    # Sort worst offenders first
    overdue.sort(key=lambda x: x['hours_over'], reverse=True)
    return overdue


def maybe_send_sla_alert(tenant_id):
    """Send a SLA-overdue summary email to the tenant's support_email.

    Uses the same enable_low_stock_alerts feature flag and support_email as the
    low-stock alert.  Respects a 24-hour cooldown stored as sla_alert_last_sent_at
    in TenantSettings.
    """
    from ..models import TenantSettings, db
    from .. import mail
    from flask_mail import Message

    # Feature flag — dedicated enable_sla_alerts toggle
    enabled = TenantSettings.query.filter_by(
        tenant_id=tenant_id, key='enable_sla_alerts'
    ).first()
    if not enabled or enabled.value != 'true':
        logger.debug("SLA alerts disabled for tenant %s", tenant_id)
        return

    # Recipient
    rec = TenantSettings.query.filter_by(tenant_id=tenant_id, key='support_email').first()
    admin_email = rec.value if rec else None
    if not admin_email:
        logger.debug("SLA alert skipped: no support_email for tenant %s", tenant_id)
        return

    # 24-hour cooldown
    cooldown = TenantSettings.query.filter_by(
        tenant_id=tenant_id, key='sla_alert_last_sent_at'
    ).first()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if cooldown and cooldown.value:
        try:
            last = datetime.fromisoformat(cooldown.value)
            if now - last < timedelta(hours=24):
                return
        except (ValueError, TypeError):
            pass

    overdue = get_overdue_units(tenant_id)
    if not overdue:
        return

    try:
        lines = "\n".join(
            f"  • {u['serial']} — Stage: {u['stage']} — "
            f"{u['hours_over']}h over SLA ({u['sla_hours']}h limit) — Assigned to: {u['assignee']}"
            for u in overdue
        )
        body = (
            "SLA Overdue Alert\n"
            "=================\n\n"
            f"{len(overdue)} unit(s) have exceeded their processing stage SLA:\n\n"
            f"{lines}\n\n"
            "Please review the Processing Pipeline to resolve overdue units.\n"
        )
        msg = Message(
            subject=f"⚠ SLA Alert — {len(overdue)} unit(s) overdue in processing",
            recipients=[admin_email],
            body=body,
        )
        mail.send(msg)
        logger.info("SLA alert sent to %s for tenant %s", admin_email, tenant_id)

        # Update cooldown
        if not cooldown:
            cooldown = TenantSettings(
                tenant_id=tenant_id,
                key='sla_alert_last_sent_at',
                value=now.isoformat()
            )
            db.session.add(cooldown)
        else:
            cooldown.value = now.isoformat()
        db.session.commit()

    except Exception as e:
        logger.error("Failed to send SLA alert for tenant %s: %s", tenant_id, e)
