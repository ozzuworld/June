#!/bin/bash

# Replace placeholders with environment variables
sed -i "s/STUN_SERVER_PLACEHOLDER/${STUN_SERVER}/g" /opt/janus/etc/janus/janus.jcfg
sed -i "s/TURN_SERVER_PLACEHOLDER/${TURN_SERVER}/g" /opt/janus/etc/janus/janus.jcfg  
sed -i "s/TURN_USERNAME_PLACEHOLDER/${TURN_USERNAME}/g" /opt/janus/etc/janus/janus.jcfg
sed -i "s/TURN_CREDENTIAL_PLACEHOLDER/${TURN_CREDENTIAL}/g" /opt/janus/etc/janus/janus.jcfg

# Start Janus
exec /opt/janus/bin/janus
