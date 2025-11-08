from flask import Flask
from flask_cors import CORS
from routes.telegram_routes import telegram_bp

app = Flask(__name__)
app.secret_key = 'your_secret_key'
CORS(app)

# ثبت بلوپرینت
app.register_blueprint(telegram_bp, url_prefix='/api/telegram')

if __name__ == '__main__':
    app.run(debug=True)
