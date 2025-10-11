import os

class Config:
    # Janus Gateway Configuration
    JANUS_URL = os.getenv('JANUS_URL', 'http://localhost:8088/janus')
    JANUS_ADMIN_KEY = os.getenv('JANUS_ADMIN_KEY', 'janusoverlord')
    JANUS_API_SECRET = os.getenv('JANUS_API_SECRET', 'janusrocks')
    
    # TURN/STUN Configuration (using your existing STUNner)
    STUN_SERVER = os.getenv('STUN_SERVER', 'stun:stunner-gateway.stunner-system.svc.cluster.local:3478')
    TURN_SERVER = os.getenv('TURN_SERVER', 'turn:stunner-gateway.stunner-system.svc.cluster.local:3478')
    TURN_USERNAME = os.getenv('TURN_USERNAME', 'user-1')
    TURN_PASSWORD = os.getenv('TURN_PASSWORD', 'pass-1')
    
    # Application Configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-here')
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    
    # Database Configuration (if needed)
    DATABASE_URL = os.getenv('DATABASE_URL')
