from inventory_flask_app import create_app
from werkzeug.middleware.proxy_fix import ProxyFix

app = create_app()

# Trust Nginx's X-Forwarded-* headers so url_for(_external=True)
# generates the correct public URL instead of http://127.0.0.1:5000/...
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
