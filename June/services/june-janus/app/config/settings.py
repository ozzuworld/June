import os

class Config:
    # Janus Gateway Configuration
    JANUS_URL = os.getenv('JANUS_URL', 'http://localhost:8088/janus')
    JANUS_ADMIN_KEY = os.getenv('JANUS_ADMIN_KEY', 'janusoverlord')
    JANUS_API_SECRET = os.getenv('JANUS_API_SECRET', 'janusrocks')
    
    # TURN/STUN Configuration (using STUNner in K8s)
    STUN_SERVER = os.getenv('STUN_SERVER', 'june-stunner-gateway-udp.stunner.svc.cluster.local:3478')
    TURN_SERVER = os.getenv('TURN_SERVER', 'june-stunner-gateway-udp.stunner.svc.cluster.local:3478')
    TURN_USERNAME = os.getenv('TURN_USERNAME', 'june-user')
    TURN_PASSWORD = os.getenv('TURN_PASSWORD', 'Pokemon123!')
    
    # Application Configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-here')
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    
    # Signaling Server Configuration
    SIGNALING_PORT = int(os.getenv('PORT', '8080'))
    
    # TLS Configuration (K8s mounted certs)
    TLS_CERT_PATH = os.getenv('TLS_CERT_PATH', '/etc/certs/tls.crt')
    TLS_KEY_PATH = os.getenv('TLS_KEY_PATH', '/etc/certs/tls.key')
    
    # Database Configuration (if needed)
    DATABASE_URL = os.getenv('DATABASE_URL')
    
    @classmethod
    def get_ice_servers(cls):
        """Return ICE servers configuration for WebRTC clients"""
        return [
            {
                "urls": [f"stun:{cls.STUN_SERVER}"]
            },
            {
                "urls": [f"turn:{cls.TURN_SERVER}"],
                "username": cls.TURN_USERNAME,
                "credential": cls.TURN_PASSWORD
            }
        ]