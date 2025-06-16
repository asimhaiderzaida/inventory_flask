from inventory_flask_app import create_app
from inventory_flask_app.models import db
from flask_migrate import Migrate
import sys

app = create_app()
migrate = Migrate(app, db)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # Allow port override via command line, e.g. python run.py 5001
    port = 5000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("Invalid port provided, defaulting to 5000")

    print(f"DEBUG: About to run Flask app on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    print("ALL ROUTES IN APP:")
    for rule in app.url_map.iter_rules():
        print(rule, "->", rule.endpoint)