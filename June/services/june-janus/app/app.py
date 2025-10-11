from flask import Flask, request, jsonify
from flask_cors import CORS
import socketio
import eventlet
import json
import uuid
import requests
import logging
from config.settings import Config
from handlers.webrtc_handler import WebRTCHandler
from routes.webrtc_routes import webrtc_bp
from routes.health import health_bp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)
CORS(app)

# Register blueprints on the main app
app.register_blueprint(webrtc_bp, url_prefix='/api/webrtc')
app.register_blueprint(health_bp, url_prefix='/api')

# Add simple health route on root app too
@app.route('/health')
def simple_health():
    return {'status': 'healthy', 'service': 'june-janus-signaling'}, 200

# Initialize SocketIO
sio = socketio.Server(cors_allowed_origins="*", logger=True)

# Initialize WebRTC handler
webrtc_handler = WebRTCHandler()

# SocketIO event handlers
@sio.event
def connect(sid, environ):
    logger.info(f"Client {sid} connected")
    return True

@sio.event
def disconnect(sid):
    logger.info(f"Client {sid} disconnected")
    webrtc_handler.cleanup_session(sid)

@sio.event
def join_room(sid, data):
    """Handle room join requests"""
    room_id = data.get('room_id')
    user_id = data.get('user_id')
    
    if not room_id or not user_id:
        sio.emit('error', {'message': 'Missing room_id or user_id'}, room=sid)
        return
    
    # Create or join session (without Janus for now)
    session_info = webrtc_handler.create_session(sid, room_id, user_id)
    
    if session_info:
        sio.enter_room(sid, room_id)
        sio.emit('joined_room', {
            'room_id': room_id,
            'session_id': session_info['session_id'],
            'ice_servers': webrtc_handler.get_ice_servers()
        }, room=sid)
        
        # Notify other participants
        sio.emit('user_joined', {
            'user_id': user_id,
            'session_id': session_info['session_id']
        }, room=room_id, skip_sid=sid)
    else:
        sio.emit('error', {'message': 'Failed to create session'}, room=sid)

@sio.event
def leave_room(sid, data):
    """Handle room leave requests"""
    room_id = data.get('room_id')
    user_id = data.get('user_id')
    
    if room_id:
        sio.leave_room(sid, room_id)
        webrtc_handler.cleanup_session(sid)
        
        # Notify other participants
        sio.emit('user_left', {'user_id': user_id}, room=room_id, skip_sid=sid)

@sio.event
def webrtc_message(sid, data):
    """Handle WebRTC signaling messages"""
    message_type = data.get('type')
    room_id = data.get('room_id')
    target_id = data.get('target_id')
    
    if message_type in ['offer', 'answer', 'ice_candidate']:
        if target_id:
            # Send to specific participant
            sio.emit('webrtc_message', data, room=target_id)
        else:
            # Broadcast to room
            sio.emit('webrtc_message', data, room=room_id, skip_sid=sid)

if __name__ == '__main__':
    # Combine Flask and SocketIO
    wsgi_app = socketio.WSGIApp(sio, app)
    logger.info("Starting June WebRTC Signaling Server on port 8080...")
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', 8080)), wsgi_app)