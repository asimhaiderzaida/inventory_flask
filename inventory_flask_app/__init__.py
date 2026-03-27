# inventory_flask_app/__init__.py
import os
import logging
from dotenv import load_dotenv

load_dotenv()

from datetime import timedelta, datetime, timezone
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail

db = SQLAlchemy()
migrate = Migrate()
mail = Mail()
limiter = Limiter(key_func=get_remote_address, default_limits=[], storage_uri="memory://")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)7s | %(name)-20s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)
logger.info(f"Loading __init__.py from {__file__}")

login_manager = LoginManager()
csrf = CSRFProtect()

def create_app():
    app = Flask(__name__,
                instance_relative_config=False,
                template_folder='templates',
                static_folder='static')
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    if not app.config['SECRET_KEY']:
        raise ValueError("SECRET_KEY is missing! Set it in .env file.")

    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    if not app.config['SQLALCHEMY_DATABASE_URI']:
        raise ValueError("DATABASE_URL is missing! Set it in .env file.")

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
        'max_overflow': 20,
    }

    # Session & CSRF lifetime — keep tokens valid for a full work day
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
    app.config['WTF_CSRF_TIME_LIMIT'] = 3600 * 8  # 8 hours (default is 3600 = 1 hour)

    # Session cookie security
    app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_HTTPONLY'] = True

    # Shopify Integration
    app.config['SHOPIFY_CLIENT_ID']      = os.environ.get('SHOPIFY_CLIENT_ID', '')
    app.config['SHOPIFY_CLIENT_SECRET']  = os.environ.get('SHOPIFY_CLIENT_SECRET', '')
    app.config['SHOPIFY_API_VERSION']    = os.environ.get('SHOPIFY_API_VERSION', '2024-01')
    app.config['SHOPIFY_WEBHOOK_SECRET'] = os.environ.get('SHOPIFY_WEBHOOK_SECRET', '')
    app.config['SHOPIFY_STORE_URL']      = os.environ.get('SHOPIFY_STORE_URL', '')
    app.config['SHOPIFY_REDIRECT_URI']   = os.environ.get('SHOPIFY_REDIRECT_URI', '')

    # Flask-Mail
    app.config['MAIL_SERVER']         = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT']           = int(os.getenv('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS']        = os.getenv('MAIL_USE_TLS', 'true').lower() == 'true'
    app.config['MAIL_USERNAME']       = os.getenv('MAIL_USERNAME', '')
    app.config['MAIL_PASSWORD']       = os.getenv('MAIL_PASSWORD', '')
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER') or os.getenv('MAIL_USERNAME', '')
    mail.init_app(app)

    logger.info(f"Using database: {app.config['SQLALCHEMY_DATABASE_URI']}")

    # === CRITICAL: Init the ONE shared db early ===
    db.init_app(app)

    # Migrations
    migrate.init_app(app, db)

    # Login Manager
    login_manager.login_view = 'auth.login'
    login_manager.login_message = "Please log in to access this page."
    login_manager.init_app(app)

    # CSRF
    csrf.init_app(app)
    logger.info("CSRF protection is ENABLED")

    # Rate limiting
    limiter.init_app(app)

    # CORS — restrict to same-origin; update CORS_ORIGINS in .env for cross-origin deployments
    allowed_origins = os.getenv('CORS_ORIGINS', '').split(',')
    allowed_origins = [o.strip() for o in allowed_origins if o.strip()]
    CORS(app, supports_credentials=True, origins=allowed_origins if allowed_origins else [])

    # User loader - import AFTER db.init_app
    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register blueprints
    from .routes import (
        auth, dashboard, stock, vendors, customers,
        order_tracking_routes, sales, invoices, import_excel,
        exports, parts, returns, reports, admin,
        pipeline, scanner, accounting, notifications, shopify_routes,
        orders, pricing,
    )

    app.register_blueprint(auth.auth_bp)
    app.register_blueprint(dashboard.dashboard_bp)
    app.register_blueprint(stock.stock_bp)
    app.register_blueprint(pipeline.pipeline_bp)
    app.register_blueprint(scanner.scanner_bp)
    app.register_blueprint(vendors.vendors_bp)
    app.register_blueprint(customers.customers_bp)
    app.register_blueprint(order_tracking_routes.order_bp)
    app.register_blueprint(sales.sales_bp)
    app.register_blueprint(invoices.invoices_bp)
    app.register_blueprint(import_excel.import_excel_bp)
    app.register_blueprint(exports.exports_bp)
    app.register_blueprint(parts.parts_bp)
    app.register_blueprint(returns.returns_bp)
    app.register_blueprint(reports.reports_bp)
    app.register_blueprint(admin.admin_bp)
    app.register_blueprint(accounting.accounting_bp)
    app.register_blueprint(notifications.notifications_bp)
    app.register_blueprint(shopify_routes.shopify_bp)
    app.register_blueprint(orders.orders_bp)
    app.register_blueprint(pricing.pricing_bp)

    # Jinja globals
    from .utils.utils import get_instance_id, get_now_for_tenant, format_duration, calc_duration_minutes

    _STATUS_DEFAULTS = {
        'unprocessed':  'Unprocessed',
        'under_process': 'In Processing',
        'processed':    'Processed',
        'idle':         'Idle',
        'disputed':     'Disputed',
        'sold':         'Sold',
    }

    def get_status_label(status_key):
        """Return the tenant-customised label for a unit status key.

        Reads from g._tenant_settings (populated by inject_settings context
        processor once per request — zero extra DB queries).
        Falls back to built-in defaults, then to title-cased key.
        """
        from flask import g, has_request_context
        if not status_key:
            return ''
        default = _STATUS_DEFAULTS.get(status_key,
                                       (status_key or '').replace('_', ' ').title())
        if not has_request_context():
            return default
        settings = getattr(g, '_tenant_settings', {})
        return settings.get(f'label_status_{status_key}') or default

    app.jinja_env.globals.update(
        get_instance_id=get_instance_id,
        get_now_for_tenant=get_now_for_tenant,
        format_duration=format_duration,
        calc_duration_minutes=calc_duration_minutes,
        get_status_label=get_status_label,
    )  # now_utc is injected per-request by inject_now_utc context processor

    # Jinja filter: replace None / 'nan' / empty string with an em-dash
    def _nonan(val):
        if val is None:
            return '—'
        s = str(val).strip()
        if s == '' or s.lower() == 'nan':
            return '—'
        return val
    app.jinja_env.filters['nonan'] = _nonan

    import json as _json
    def _fromjson(val):
        if not val:
            return []
        try:
            return _json.loads(val)
        except Exception:
            return []
    app.jinja_env.filters['fromjson'] = _fromjson

    # Context processors
    @app.context_processor
    def inject_settings():
        from flask import g
        from flask_login import current_user
        from .models import TenantSettings
        if not current_user.is_authenticated:
            g._tenant_settings = {}
            return dict(settings={})
        try:
            settings_query = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
            settings = {s.key: s.value for s in settings_query}
            if "column_order_instance_table" not in settings:
                # Must match unified_column_order in admin.py
                settings["column_order_instance_table"] = (
                    "asset,serial,item_name,make,model,display,cpu,ram,"
                    "gpu1,gpu2,grade,location,status,process_stage,team,"
                    "shelf_bin,is_sold,label,action"
                )
            g._tenant_settings = settings   # cache for get_status_label
            return dict(settings=settings)
        except Exception as e:
            from sqlalchemy.exc import SQLAlchemyError
            if isinstance(e, SQLAlchemyError):
                logger.error(f"DB error loading tenant settings: {e}")
            else:
                logger.exception(f"Unexpected error loading tenant settings: {e}")
            g._tenant_settings = {}
            return dict(settings={})

    @app.context_processor
    def inject_process_stages():
        from flask_login import current_user
        from .models import ProcessStage
        if not current_user.is_authenticated:
            return dict(process_stages=[])
        try:
            stages = ProcessStage.query.filter_by(
                tenant_id=current_user.tenant_id
            ).order_by(ProcessStage.order).all()
            return dict(process_stages=stages)
        except Exception:
            return dict(process_stages=[])

    @app.context_processor
    def inject_csrf_token():
        from flask_wtf.csrf import generate_csrf
        return dict(csrf_token=generate_csrf)

    @app.context_processor
    def inject_parts_low_stock_count():
        from flask_login import current_user
        from sqlalchemy import text
        if not current_user.is_authenticated:
            return dict(parts_low_stock_count=0)
        try:
            result = db.session.execute(
                text("""
                    SELECT COUNT(DISTINCT p.id)
                    FROM part p
                    WHERE p.tenant_id = :tid
                      AND (SELECT COALESCE(SUM(ps.quantity), 0)
                           FROM part_stock ps
                           WHERE ps.part_id = p.id) < p.min_stock
                """),
                {'tid': current_user.tenant_id}
            ).scalar()
            low_stock_count = result or 0
            return dict(parts_low_stock_count=low_stock_count)
        except Exception:
            return dict(parts_low_stock_count=0)

    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(e):
        from flask import render_template
        db.session.rollback()
        return render_template('errors/500.html', settings={}), 500

    @app.errorhandler(410)
    def gone_error(e):
        from flask import render_template
        return render_template('errors/410.html', settings={}), 410

    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    @app.context_processor
    def inject_now_utc():
        return {'now_utc': datetime.now(timezone.utc)}

    @app.context_processor
    def inject_notifications():
        from flask_login import current_user
        if not current_user.is_authenticated:
            return dict(notifications=[], unread_notification_count=0)
        try:
            from .models import Notification
            # Per-user DB notifications (unread only, last 20)
            db_notifs = (
                Notification.query
                .filter_by(user_id=current_user.id, is_read=False)
                .order_by(Notification.created_at.desc())
                .limit(20)
                .all()
            )
            unread_count = len(db_notifs)
            # Also include legacy inventory system notifications for admins
            system_notifs = []  # legacy — DB notifications replaced this
            return dict(
                notifications=db_notifs,
                system_notifications=system_notifs,
                unread_notification_count=unread_count,
            )
        except Exception:
            return dict(notifications=[], system_notifications=[], unread_notification_count=0)

    from .cli import alerts_cli
    app.cli.add_command(alerts_cli)

    return app