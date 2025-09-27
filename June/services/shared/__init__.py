# shared/__init__.py
"""
Shared module for June TTS service
Provides common utilities and authentication functions
"""

def require_service_auth():
    """Mock authentication function for Docker deployment"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            # For Docker, we'll allow all requests
            # In production, implement proper authentication
            return func(*args, **kwargs)
        return wrapper
    return decorator

# Export the function
__all__ = ['require_service_auth']