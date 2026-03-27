"""Flask CLI commands for scheduled tasks."""
import logging
import click
from flask.cli import with_appcontext

logger = logging.getLogger(__name__)


@click.group('alerts')
def alerts_cli():
    """Scheduled alert commands."""
    pass


@alerts_cli.command('send')
@with_appcontext
def send_alerts():
    """Send all pending alerts for every tenant.

    Run via cron:
      */30 * * * * cd /home/pcmart/inventory_flask && venv/bin/flask alerts send >> /var/log/pcmart_alerts.log 2>&1
    """
    from inventory_flask_app.models import Tenant, TenantSettings
    from inventory_flask_app.utils.mail_utils import (
        maybe_send_low_stock_email,
        maybe_send_sla_alert,
        get_overdue_units,
        get_low_stock_parts,
    )

    tenants = Tenant.query.all()
    logger.info("Running scheduled alerts for %d tenant(s)", len(tenants))

    for tenant in tenants:
        tid = tenant.id

        # Check master switch first
        master = TenantSettings.query.filter_by(tenant_id=tid, key='enable_automated_alerts').first()
        if not master or master.value != 'true':
            logger.debug("Tenant %s (%s): automated alerts disabled (master switch off)", tid, tenant.name)
            continue

        # Check if tenant has email configured
        support_email = TenantSettings.query.filter_by(tenant_id=tid, key='support_email').first()
        if not support_email or not support_email.value:
            logger.debug("Tenant %s (%s): no support_email configured, skipping", tid, tenant.name)
            continue

        try:
            # Low stock alerts (respects enable_low_stock_alerts toggle + 24h cooldown)
            low_parts = get_low_stock_parts(tid)
            if low_parts:
                maybe_send_low_stock_email(tid)
                logger.info("Tenant %s: %d low-stock parts checked", tid, len(low_parts))

            # SLA overdue alerts (respects enable_sla_alerts toggle + 24h cooldown)
            overdue = get_overdue_units(tid)
            if overdue:
                maybe_send_sla_alert(tid)
                logger.info("Tenant %s: %d SLA-overdue units checked", tid, len(overdue))

            # Aged inventory alert
            _send_aged_inventory_alert(tid)

            # AR overdue alert
            _send_ar_overdue_alert(tid)

        except Exception as e:
            logger.error("Alert processing failed for tenant %s: %s", tid, e)

    logger.info("Scheduled alerts complete")


def _send_aged_inventory_alert(tenant_id):
    """Send alert if units aged beyond threshold. Respects own toggle + 24h cooldown."""
    from inventory_flask_app.models import TenantSettings, ProductInstance, Product, db
    from datetime import datetime, timedelta, timezone

    enabled = TenantSettings.query.filter_by(
        tenant_id=tenant_id, key='enable_aged_inventory_alerts'
    ).first()
    if not enabled or enabled.value != 'true':
        return

    cooldown = TenantSettings.query.filter_by(
        tenant_id=tenant_id, key='aged_alert_last_sent_at'
    ).first()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if cooldown and cooldown.value:
        try:
            last = datetime.fromisoformat(cooldown.value)
            if now - last < timedelta(hours=24):
                return
        except (ValueError, TypeError):
            pass

    threshold_setting = TenantSettings.query.filter_by(
        tenant_id=tenant_id, key='aged_threshold_days'
    ).first()
    threshold_days = int(threshold_setting.value if threshold_setting and threshold_setting.value else 60)
    cutoff = now - timedelta(days=threshold_days)

    count = (
        ProductInstance.query.join(Product)
        .filter(
            Product.tenant_id == tenant_id,
            ProductInstance.is_sold == False,
            ProductInstance.created_at < cutoff,
        )
        .count()
    )
    if count == 0:
        return

    recipient = TenantSettings.query.filter_by(tenant_id=tenant_id, key='support_email').first()
    if not recipient or not recipient.value:
        return

    try:
        from inventory_flask_app import mail
        from flask_mail import Message

        body = (
            f"Aged Inventory Alert\n"
            f"====================\n\n"
            f"{count} unit(s) have been in inventory for more than {threshold_days} days.\n\n"
            f"These units may need price reduction, promotion, or liquidation.\n\n"
            f"Review them in the Aged Inventory report.\n"
        )
        msg = Message(
            subject=f"\u26a0 Aged Inventory \u2014 {count} unit(s) over {threshold_days} days",
            recipients=[recipient.value],
            body=body,
        )
        mail.send(msg)
        logger.info("Aged inventory alert sent for tenant %s: %d units", tenant_id, count)

        if not cooldown:
            cooldown = TenantSettings(
                tenant_id=tenant_id,
                key='aged_alert_last_sent_at',
                value=now.isoformat(),
            )
            db.session.add(cooldown)
        else:
            cooldown.value = now.isoformat()
        db.session.commit()
    except Exception as e:
        logger.error("Aged inventory alert failed for tenant %s: %s", tenant_id, e)


def _send_ar_overdue_alert(tenant_id):
    """Send alert for overdue accounts receivable. Respects own toggle + 24h cooldown."""
    from inventory_flask_app.models import TenantSettings, AccountReceivable, Customer, db
    from datetime import datetime, timedelta, timezone, date

    enabled = TenantSettings.query.filter_by(
        tenant_id=tenant_id, key='enable_ar_overdue_alerts'
    ).first()
    if not enabled or enabled.value != 'true':
        return

    cooldown = TenantSettings.query.filter_by(
        tenant_id=tenant_id, key='ar_alert_last_sent_at'
    ).first()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if cooldown and cooldown.value:
        try:
            last = datetime.fromisoformat(cooldown.value)
            if now - last < timedelta(hours=24):
                return
        except (ValueError, TypeError):
            pass

    today = date.today()
    overdue_ars = (
        AccountReceivable.query
        .filter(
            AccountReceivable.tenant_id == tenant_id,
            AccountReceivable.status.in_(('open', 'partial')),
            AccountReceivable.due_date < today,
        )
        .join(Customer, AccountReceivable.customer_id == Customer.id)
        .all()
    )
    if not overdue_ars:
        return

    recipient = TenantSettings.query.filter_by(tenant_id=tenant_id, key='support_email').first()
    if not recipient or not recipient.value:
        return

    try:
        from inventory_flask_app import mail
        from flask_mail import Message

        total_overdue = sum(
            float(ar.amount_due or 0) - float(ar.amount_paid or 0)
            for ar in overdue_ars
        )
        lines = "\n".join(
            f"  \u2022 {ar.customer.name}: {float(ar.amount_due - ar.amount_paid):.2f} "
            f"(due {ar.due_date.isoformat()}, {(today - ar.due_date).days}d overdue)"
            for ar in overdue_ars[:20]
        )
        if len(overdue_ars) > 20:
            lines += f"\n  ... and {len(overdue_ars) - 20} more"

        body = (
            f"Accounts Receivable Overdue Alert\n"
            f"=================================\n\n"
            f"{len(overdue_ars)} invoice(s) are past due, totaling {total_overdue:,.2f}:\n\n"
            f"{lines}\n\n"
            f"Please follow up with these customers.\n"
        )
        msg = Message(
            subject=f"\u26a0 AR Overdue \u2014 {len(overdue_ars)} invoice(s) past due",
            recipients=[recipient.value],
            body=body,
        )
        mail.send(msg)
        logger.info("AR overdue alert sent for tenant %s: %d invoices", tenant_id, len(overdue_ars))

        if not cooldown:
            cooldown = TenantSettings(
                tenant_id=tenant_id,
                key='ar_alert_last_sent_at',
                value=now.isoformat(),
            )
            db.session.add(cooldown)
        else:
            cooldown.value = now.isoformat()
        db.session.commit()
    except Exception as e:
        logger.error("AR overdue alert failed for tenant %s: %s", tenant_id, e)


# ── Super Admin CLI ──────────────────────────────────────────────────────────

@click.group('superadmin')
def superadmin_cli():
    """Super admin management commands."""
    pass


@superadmin_cli.command('create')
@click.argument('username')
@click.argument('password')
@with_appcontext
def create_superadmin(username, password):
    """Create a super admin user.

    Usage: flask superadmin create <username> <password>

    Super admins exist above all tenants and can manage the entire platform.
    They are stored under a hidden '__system__' tenant.
    """
    from inventory_flask_app.models import db, User, Tenant
    from werkzeug.security import generate_password_hash

    existing = User.query.filter_by(username=username).first()
    if existing:
        if existing.is_superadmin:
            click.echo(f"Super admin '{username}' already exists.")
        else:
            existing.is_superadmin = True
            db.session.commit()
            click.echo(f"Existing user '{username}' promoted to super admin.")
        return

    system_tenant = Tenant.query.filter_by(name='__system__').first()
    if not system_tenant:
        system_tenant = Tenant(name='__system__', is_active=False)
        db.session.add(system_tenant)
        db.session.flush()

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        role='admin',
        tenant_id=system_tenant.id,
        is_superadmin=True,
    )
    db.session.add(user)
    db.session.commit()
    click.echo(f"Super admin '{username}' created successfully.")


@superadmin_cli.command('list')
@with_appcontext
def list_superadmins():
    """List all super admin users."""
    from inventory_flask_app.models import User
    admins = User.query.filter_by(is_superadmin=True).all()
    if not admins:
        click.echo("No super admins found. Create one with: flask superadmin create <username> <password>")
        return
    for u in admins:
        click.echo(f"  {u.username} (id={u.id}, tenant_id={u.tenant_id})")
