# Scheduled Alerts Setup

## Cron (recommended)

Add to crontab (`crontab -e`):

```
# PCMart alerts — runs every 30 min, each alert has 24h cooldown built-in
*/30 * * * * cd /home/pcmart/inventory_flask && /home/pcmart/inventory_flask/venv/bin/flask alerts send >> /var/log/pcmart_alerts.log 2>&1
```

## What it does

`flask alerts send` iterates every tenant and, for each:

1. Checks the **master switch** (`enable_automated_alerts = true` in TenantSettings) — skips tenant if off
2. Checks that `support_email` is configured — skips tenant if missing
3. Runs four alert checks, each with its own per-alert toggle and 24-hour cooldown:

| Alert | TenantSettings toggle | Cooldown key |
|---|---|---|
| Low-stock parts | `enable_low_stock_alerts` | `low_stock_last_notified` |
| SLA overdue units | `enable_sla_alerts` | `sla_alert_last_sent_at` |
| Aged inventory | `enable_aged_inventory_alerts` | `aged_alert_last_sent_at` |
| AR overdue invoices | `enable_ar_overdue_alerts` | `ar_alert_last_sent_at` |

Because each alert stores a timestamp when it was last sent, running the cron every 30 minutes is safe — at most one email per alert per 24 hours.

## Admin configuration

Go to **Settings → Notifications & Alerts**:

- Turn on **"Enable automated scheduled alerts"** (master switch)
- Enable whichever individual alert types you want
- Make sure **Support Email** is set (Settings → Company section)
- Configure SMTP in `.env`: `MAIL_SERVER`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_PORT`, `MAIL_USE_TLS`

## Manual test

```bash
cd /home/pcmart/inventory_flask
source venv/bin/activate
flask alerts send
```

## Log rotation

```
# /etc/logrotate.d/pcmart_alerts
/var/log/pcmart_alerts.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
}
```
