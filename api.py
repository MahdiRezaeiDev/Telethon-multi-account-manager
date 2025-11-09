from flask import Flask
import os
import secrets
from flask_cors import CORS
from routes.telegram_routes import telegram_bp

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))
CORS(app)

# ثبت بلوپرینت
app.register_blueprint(telegram_bp, url_prefix='/api/telegram')

if __name__ == '__main__':
    app.run(debug=True)
