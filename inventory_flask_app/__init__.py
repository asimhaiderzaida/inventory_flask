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

login_manager = LoginManager()

def create_app():
    app = Flask(__name__)

    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SECRET_KEY'] = 'your-secret-key'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'instance', 'inventory.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    CORS(app, supports_credentials=True)
    db.init_app(app)
    from flask_migrate import Migrate
    migrate = Migrate(app, db)

    login_manager.login_view = 'auth_bp.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ✅ Register blueprints with relative imports
    from .routes.auth import auth_bp
    from .routes.dashboard import dashboard_bp
    from .routes.instances import instances_bp
    from .routes.stock import stock_bp
    from .routes.vendors import vendors_bp
    from .routes.customers import customers_bp
    from .routes.order_tracking_routes import order_bp
    from .routes.sales import sales_bp
    from .routes.invoices import invoices_bp
    from .routes.import_excel import import_excel_bp
    from .routes.exports import exports_bp
    from .routes.parts import parts_bp

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

    from .routes.reports import reports_bp
    app.register_blueprint(reports_bp)

    from .utils.utils import get_instance_id
    app.jinja_env.globals.update(get_instance_id=get_instance_id)

    print("Flask app is using DB:", app.config['SQLALCHEMY_DATABASE_URI'])
    return app
