# Replace livekit import with janus
from .webrtc_routes import webrtc_bp
from .health import health_bp
from .conversation_routes import conversation_bp
from .voice_routes import voice_bp

def register_routes(app):
    """Register all route blueprints"""
    app.register_blueprint(webrtc_bp, url_prefix='/api/webrtc')
    app.register_blueprint(health_bp, url_prefix='/api')
    app.register_blueprint(conversation_bp, url_prefix='/api/conversation')
    app.register_blueprint(voice_bp, url_prefix='/api/voice')
