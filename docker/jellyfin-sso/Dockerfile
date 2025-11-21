# Jellyfin with SSO Plugin Pre-installed
# Based on official Jellyfin image with SSO-Auth plugin
FROM jellyfin/jellyfin:latest

# Install dependencies for plugin download
USER root
RUN apt-get update && \
    apt-get install -y curl jq unzip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Download and install SSO plugin
# Using the latest release from the manifest
RUN mkdir -p /config/data/plugins/SSO-Auth && \
    cd /tmp && \
    curl -L https://github.com/9p4/jellyfin-plugin-sso/releases/download/v4.0.0.3/sso-authentication_4.0.0.3.zip -o sso-plugin.zip && \
    unzip sso-plugin.zip -d /config/data/plugins/SSO-Auth/ && \
    rm sso-plugin.zip

# Jellyfin will set proper permissions at runtime
# No need to chown here as jellyfin user doesn't exist during build

# Plugin is now pre-installed and will be available on first boot
LABEL org.opencontainers.image.description="Jellyfin with SSO-Auth plugin pre-installed"
LABEL org.opencontainers.image.source="https://github.com/ozzuworld/June"
