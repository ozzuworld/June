from flask import Blueprint, jsonify
import requests
from config.settings import Config

health_bp = Blueprint('health', __name__)

@health_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Check if Janus is running
        janus_response = requests.get(f"{Config.JANUS_URL}/info", timeout=5)
        janus_healthy = janus_response.status_code == 200
        
        return jsonify({
            'status': 'healthy' if janus_healthy else 'unhealthy',
            'janus_gateway': 'running' if janus_healthy else 'down',
            'timestamp': None
        }), 200 if janus_healthy else 503
        
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
    return jsonify({'status': 'alive'}), 200
