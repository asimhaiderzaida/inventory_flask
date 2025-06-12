from inventory_flask_app import create_app
from inventory_flask_app.models import db
from flask_migrate import Migrate

app = create_app()
migrate = Migrate(app, db)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
    print("ALL ROUTES IN APP:")
for rule in app.url_map.iter_rules():
    print(rule, "->", rule.endpoint)