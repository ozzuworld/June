from flask import Blueprint, request, jsonify
from handlers.webrtc_handler import WebRTCHandler

webrtc_bp = Blueprint('webrtc', __name__)
webrtc_handler = WebRTCHandler()

@webrtc_bp.route('/ice-servers', methods=['GET'])
def get_ice_servers():
    """Get ICE servers configuration"""
    try:
        ice_servers = webrtc_handler.get_ice_servers()
        return jsonify({
            'success': True,
            'ice_servers': ice_servers
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@webrtc_bp.route('/create-room', methods=['POST'])
def create_room():
    """Create a new WebRTC room"""
    try:
        data = request.get_json()
        room_id = data.get('room_id')
        
        if not room_id:
            return jsonify({
                'success': False,
                'error': 'Missing room_id'
            }), 400
        
        # Room creation is handled in the socket handler
        # This endpoint just validates the request
        return jsonify({
            'success': True,
            'room_id': room_id,
            'message': 'Room created successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@webrtc_bp.route('/rooms/<room_id>/participants', methods=['GET'])
def get_room_participants(room_id):
    """Get list of participants in a room"""
    try:
        # This would query Janus for room participants
        # Implementation depends on your specific needs
        return jsonify({
            'success': True,
            'room_id': room_id,
            'participants': []
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
