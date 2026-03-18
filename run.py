# run.py  (or wsgi.py / main.py — your choice)
import os
import sys
import logging
from flask_migrate import Migrate

# ── 1. Import your app factory ──
from inventory_flask_app import create_app
from inventory_flask_app.models import db

# ── 2. Setup logging EARLY (before anything else) ──
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)7s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ── 3. Create the actual Flask app ──
app = create_app()
migrate = Migrate(app, db)

def print_routes():
    """Helper to show all registered routes (very useful!)"""
    print("\nRegistered routes:")
    print("-" * 60)
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
        methods = ','.join(sorted(rule.methods - {'OPTIONS', 'HEAD'}))
        if methods:
            print(f"{rule:45} → {rule.endpoint:30}  ({methods})")
    print("-" * 60 + "\n")


if __name__ == '__main__':
    # ── Safety: don't run app.run() if someone uses "flask run" ──
    if 'flask' in sys.modules.get('__main__', '') or 'flask' in sys.argv:
        logger.warning("Detected 'flask run' command → skipping app.run()")
    else:
        with app.app_context():
            # NEVER do db.create_all() in production code!
            # Use migrations instead → flask db upgrade
            if os.getenv("FLASK_ENV") == "development":
                logger.info("Development mode → creating tables if missing (migrations preferred!)")
                db.create_all()           # only in dev!
            else:
                logger.info("Production mode → assuming migrations already applied")

        # Decide debug mode (more modern way)
        debug = os.getenv("FLASK_DEBUG", "0") == "1"

        # Get port (command line > env > default)
        try:
            port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv("PORT", 5000))
        except (ValueError, TypeError):
            port = 5000
            logger.warning("Invalid port → falling back to 5000")

        logger.info(f"Starting Flask app → http://localhost:{port}")
        logger.info(f"Debug mode: {debug}")

        # Print nice route list
        print_routes()

        try:
            app.run(
                host="0.0.0.0" if debug else "127.0.0.1",    # safer for local dev
                port=port,
                debug=debug,
                use_reloader=debug,                         # auto-reload only in debug
                threaded=True,                              # better for small apps
            )
        except Exception as e:
            logger.exception("Failed to start Flask server")
            sys.exit(1)