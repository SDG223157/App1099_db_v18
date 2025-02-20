from flask import Flask, request, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from datetime import datetime
import logging
from app.config import Config
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_migrate import Migrate  # Import Migrate
# from app.models import NewsArticle, ArticleMetric, ArticleSymbol, User  # Import models after db is initialized
import markdown

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

db = SQLAlchemy()  # Define SQLAlchemy instance
migrate = Migrate()  # Initialize Migrate instance
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'error'

def markdown_to_html(text):
    return markdown.markdown(text or '', extensions=['fenced_code', 'tables'])

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Add ProxyFix middleware for HTTPS handling
    app.wsgi_app = ProxyFix(
        app.wsgi_app, 
        x_for=1,
        x_proto=1,
        x_host=1,
        x_port=1
    )

    # Initialize extensions
    
    db.init_app(app)  # Link the db with the app
    migrate.init_app(app, db)  # Link Flask-Migrate with the app and db
   
    login_manager.init_app(app)
    # from app.models import NewsArticle, ArticleMetric, ArticleSymbol, User  # Import models after db is initialized
   

    # Force HTTPS
    @app.before_request
    def before_request():
        if not request.is_secure and not app.debug:
            url = request.url.replace('http://', 'https://', 1)
            return redirect(url, code=301)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))

    with app.app_context():
        try:
            # No need to call db.create_all() because Flask-Migrate will handle migrations
            # db.create_all()
            logger.info("Database tables created successfully")

            logger.info("Database initialized using Flask-Migrate")
            from app.models import NewsArticle, ArticleMetric, ArticleSymbol, User  # Import models after db is initialized
            db.create_all()

            # Check if admin user exists, if not create one
            admin_user = User.query.filter_by(email='admin@cfa187260.com').first()
            if not admin_user:
                admin = User(
                    email='admin@cfa187260.com',
                    username='admin',
                    first_name='Jiang',
                    last_name='Chen',
                    is_admin=True,
                    role='admin',
                    is_active=True
                )
                admin.set_password('Gern@8280')  # Set your desired password
                db.session.add(admin)
                db.session.commit()
                logger.info("Admin user created successfully!")
        except Exception as e:
            logger.error(f"Error during database initialization: {str(e)}")

        # Register blueprints
        from app.routes import bp as main_bp
        logger.debug(f"Registering main blueprint: {main_bp.name}")
        app.register_blueprint(main_bp)

        try:
            from app.auth.routes import bp as auth_bp
            logger.debug(f"Registering auth blueprint: {auth_bp.name}")
            app.register_blueprint(auth_bp, url_prefix='/auth')
        except Exception as e:
            logger.error(f"Error registering auth blueprint: {str(e)}")
            raise

        from app.user.routes import bp as user_bp
        logger.debug(f"Registering user blueprint: {user_bp.name}")
        app.register_blueprint(user_bp, url_prefix='/user')

        # Register news blueprint
        try:
            from app.news.routes import bp as news_bp
            logger.debug(f"Registering news blueprint: {news_bp.name}")
            app.register_blueprint(news_bp, url_prefix='/news')
        except Exception as e:
            logger.error(f"Error registering news blueprint: {str(e)}")
            raise

        @app.context_processor
        def utility_processor():
            return {
                'now': datetime.now()
            }

        # Debug: Print all registered endpoints
        logger.debug("Registered URLs:")
        for rule in app.url_map.iter_rules():
            logger.debug(f"{rule.endpoint}: {rule.rule}")

        # Error handlers
        @app.errorhandler(404)
        def not_found_error(error):
            return 'Page not found', 404

        @app.errorhandler(500)
        def internal_error(error):
            db.session.rollback()
            return 'Internal server error', 500

        # Add Markdown filter to Jinja2 environment
        app.jinja_env.filters['markdown'] = markdown_to_html

    return app

# Add global exception handler
@db.event.listens_for(db.session, 'after_rollback')
def handle_after_rollback(session):
    logger.warning("Database session rollback occurred")