#!/bin/bash

# Start Janus Gateway
/opt/janus/bin/janus --daemon --pid-file=/var/run/janus.pid --log-file=/var/log/janus.log

# Wait for Janus to start
sleep 5

# Start Python WebRTC signaling server
python3 app.py
