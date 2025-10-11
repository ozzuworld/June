from flask import Blueprint, jsonify
from config.settings import Config

health_bp = Blueprint('health', __name__)

@health_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint - simplified without Janus dependency"""
    try:
        # For now, just return healthy since we're running signaling only
        return jsonify({
            'status': 'healthy',
            'service': 'june-janus-signaling',
            'janus_gateway': 'not_required',
            'signaling_server': 'running'
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 503

@health_bp.route('/readiness', methods=['GET'])
def readiness_check():
    """Readiness probe for Kubernetes"""
    return health_check()

@health_bp.route('/liveness', methods=['GET'])
def liveness_check():
    """Liveness probe for Kubernetes"""
    return jsonify({'status': 'alive', 'service': 'june-janus-signaling'}), 200