from flask import Flask
from flask_login import LoginManager
from dotenv import load_dotenv
import os

load_dotenv()

login_manager = LoginManager()


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-me')
    app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
    app.config['EXPORT_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'exports')

    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        from app.models.user import User
        return User.get(user_id)

    # Initialize database (creates all tables if not exist — safe to call every startup)
    from app.utils.database import init_db
    with app.app_context():
        try:
            init_db()
        except Exception as e:
            import traceback
            print(f"WARNING: init_db failed: {e}\n{traceback.format_exc()}")

    from app.routes.auth import auth_bp
    from app.routes.admin import admin_bp
    from app.routes.client import client_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(client_bp, url_prefix='/portal')

    @app.template_filter('format_number')
    def format_number(value):
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return value

    import traceback
    from flask import jsonify

    @app.errorhandler(500)
    def handle_500(e):
        tb = traceback.format_exc()
        return f"<pre style='padding:20px;font-size:13px;'><strong>500 Error:</strong>\n\n{tb}</pre>", 500

    return app
