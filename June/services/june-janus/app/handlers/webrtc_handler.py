import requests
import json
import uuid
import logging
from config.settings import Config

logger = logging.getLogger(__name__)

class WebRTCHandler:
    def __init__(self):
        self.janus_url = Config.JANUS_URL
        self.admin_key = Config.JANUS_ADMIN_KEY
        self.api_secret = Config.JANUS_API_SECRET
        self.sessions = {}  # Track active sessions
    
    def create_session(self, socket_id, room_id, user_id):
        """Create a new Janus session for WebRTC"""
        try:
            # Create Janus session
            session_response = self._janus_request('', {
                'janus': 'create',
                'transaction': str(uuid.uuid4())
            })
            
            if session_response and 'data' in session_response:
                session_id = session_response['data']['id']
                
                # Attach to VideoRoom plugin
                handle_response = self._janus_request(f'/{session_id}', {
                    'janus': 'attach',
                    'plugin': 'janus.plugin.videoroom',
                    'transaction': str(uuid.uuid4())
                })
                
                if handle_response and 'data' in handle_response:
                    handle_id = handle_response['data']['id']
                    
                    # Join or create room
                    room_response = self._join_or_create_room(session_id, handle_id, room_id, user_id)
                    
                    if room_response:
                        session_info = {
                            'session_id': session_id,
                            'handle_id': handle_id,
                            'room_id': room_id,
                            'user_id': user_id,
                            'socket_id': socket_id
                        }
                        
                        self.sessions[socket_id] = session_info
                        return session_info
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to create Janus session: {e}")
            return None
    
    def _join_or_create_room(self, session_id, handle_id, room_id, user_id):
        """Join existing room or create new one"""
        try:
            # First, try to join existing room
            join_response = self._janus_request(f'/{session_id}/{handle_id}', {
                'janus': 'message',
                'transaction': str(uuid.uuid4()),
                'body': {
                    'request': 'join',
                    'room': int(room_id),
                    'ptype': 'publisher',
                    'display': user_id
                }
            })
            
            # If room doesn't exist, create it
            if not join_response or join_response.get('janus') == 'error':
                create_response = self._janus_request(f'/{session_id}/{handle_id}', {
                    'janus': 'message',
                    'transaction': str(uuid.uuid4()),
                    'body': {
                        'request': 'create',
                        'room': int(room_id),
                        'publishers': 10,
                        'bitrate': 128000,
                        'fir_freq': 10,
                        'audiocodec': 'opus',
                        'videocodec': 'vp8'
                    }
                })
                
                if create_response:
                    # Now join the created room
                    return self._janus_request(f'/{session_id}/{handle_id}', {
                        'janus': 'message',
                        'transaction': str(uuid.uuid4()),
                        'body': {
                            'request': 'join',
                            'room': int(room_id),
                            'ptype': 'publisher',
                            'display': user_id
                        }
                    })
            
            return join_response
            
        except Exception as e:
            logger.error(f"Failed to join/create room: {e}")
            return None
    
    def cleanup_session(self, socket_id):
        """Clean up Janus session when client disconnects"""
        if socket_id in self.sessions:
            session_info = self.sessions[socket_id]
            
            try:
                # Leave room
                self._janus_request(f"/{session_info['session_id']}/{session_info['handle_id']}", {
                    'janus': 'message',
                    'transaction': str(uuid.uuid4()),
                    'body': {
                        'request': 'leave'
                    }
                })
                
                # Detach from plugin
                self._janus_request(f"/{session_info['session_id']}/{session_info['handle_id']}", {
                    'janus': 'detach',
                    'transaction': str(uuid.uuid4())
                })
                
                # Destroy session
                self._janus_request(f"/{session_info['session_id']}", {
                    'janus': 'destroy',
                    'transaction': str(uuid.uuid4())
                })
                
            except Exception as e:
                logger.error(f"Error cleaning up session: {e}")
            
            del self.sessions[socket_id]
    
    def get_ice_servers(self):
        """Get ICE servers configuration for client"""
        return [
            {
                'urls': Config.STUN_SERVER
            },
            {
                'urls': Config.TURN_SERVER,
                'username': Config.TURN_USERNAME,
                'credential': Config.TURN_PASSWORD
            }
        ]
    
    def _janus_request(self, path, data):
        """Make HTTP request to Janus Gateway"""
        try:
            url = f"{self.janus_url}{path}"
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            if self.api_secret:
                data['apisecret'] = self.api_secret
            
            response = requests.post(url, json=data, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Janus request failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to make Janus request: {e}")
            return None
