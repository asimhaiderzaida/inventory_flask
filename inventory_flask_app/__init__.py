import sys
print("LOADING __init__.py from", __file__)
print("sys.path =", sys.path)
print("LOADING __init__.py!")
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_cors import CORS
from .models import db, User  # ✅ Relative import
from flask_wtf import CSRFProtect
from .utils.utils import get_now_for_tenant

csrf = CSRFProtect()

login_manager = LoginManager()

def create_app():
    app = Flask(__name__)

    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SECRET_KEY'] = 'your-secret-key'
    app.config['MAX_CONTENT_LENGTH'] = 300 * 1024 * 1024  # Allow up to 300 MB uploads
    from dotenv import load_dotenv
    load_dotenv()
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    print("Flask app is using DB:", app.config['SQLALCHEMY_DATABASE_URI'])
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    from flask_migrate import Migrate
    migrate = Migrate(app, db)

    # --- CSRF protection logic based on DB setting ---
    from inventory_flask_app.models import TenantSettings
    enable_csrf = True
    try:
        from flask_login import current_user
        with app.app_context():
            tenant_settings = TenantSettings.query.all()
            setting_map = {s.key: s.value for s in tenant_settings}
            enable_csrf = setting_map.get("enable_csrf_protection", "true") == "true"
    except Exception as e:
        print("Could not determine CSRF setting:", e)
    if enable_csrf:
        csrf.init_app(app)
        print("✅ CSRF Protection is ENABLED")
    else:
        print("⚠️ CSRF Protection is DISABLED")

    CORS(app, supports_credentials=True)

    login_manager.login_view = 'auth_bp.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ✅ Register blueprints with relative imports
    from .routes.stock import stock_bp
    from .routes.auth import auth_bp
    from .routes.dashboard import dashboard_bp
    from .routes.instances import instances_bp
    from .routes.vendors import vendors_bp
    from .routes.customers import customers_bp
    from .routes.order_tracking_routes import order_bp
    from .routes.sales import sales_bp
    from .routes.invoices import invoices_bp
    from .routes.import_excel import import_excel_bp
    from .routes.exports import exports_bp
    from .routes.parts import parts_bp
    from .routes.returns import returns_bp

    app.register_blueprint(parts_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(instances_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(vendors_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(order_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(import_excel_bp)
    app.register_blueprint(exports_bp)
    app.register_blueprint(returns_bp)

    from .routes.reports import reports_bp
    app.register_blueprint(reports_bp)

    from .routes.admin import admin_bp
    app.register_blueprint(admin_bp)

    from .utils.utils import get_instance_id, get_now_for_tenant
    app.jinja_env.globals.update(get_instance_id=get_instance_id, get_now_for_tenant=get_now_for_tenant)

    @app.context_processor
    def inject_settings():
        from flask_login import current_user
        from inventory_flask_app.models import TenantSettings
        if not current_user.is_authenticated:
            return {}
        try:
            tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
            settings = {s.key: s.value for s in tenant_settings}
            if not settings.get("column_order_instance_table"):
                settings["column_order_instance_table"] = "asset,serial,model,product,vendor,status,process_stage,team,shelf_bin,screen_size,resolution,video_card,ram,processor,storage,is_sold,label,action"
            print("LOADED COLUMN ORDER:", settings.get("column_order_instance_table"))
            return {'settings': settings}
        except:
            return {}

    print("Flask app is using DB:", app.config['SQLALCHEMY_DATABASE_URI'])
    @app.context_processor
    def inject_csrf_token():
        from flask_wtf.csrf import generate_csrf
        return dict(csrf_token=generate_csrf)


    return app
