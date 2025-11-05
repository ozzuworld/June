"""Wire Prometheus in main.py"""
from .observability.wire import wire_prometheus

# Call wire_prometheus(app) after app creation
