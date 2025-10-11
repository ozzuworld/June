FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    libmicrohttpd-dev \
    libjansson-dev \
    libssl-dev \
    libsofia-sip-ua-dev \
    libglib2.0-dev \
    libopus-dev \
    libogg-dev \
    libcurl4-openssl-dev \
    liblua5.3-dev \
    libconfig-dev \
    pkg-config \
    libtool \
    automake \
    build-essential \
    wget \
    git \
    cmake \
    python3 \
    python3-pip \
    python3-dev \
    # Add runtime dependencies
    libmicrohttpd12 \
    libjansson4 \
    libsofia-sip-ua0 \
    libglib2.0-0 \
    libopus0 \
    libogg0 \
    libssl3 \
    libconfig9

# Install libnice
RUN git clone https://gitlab.freedesktop.org/libnice/libnice && \
    cd libnice && \
    ./autogen.sh && \
    make && make install

# Install libsrtp
RUN wget https://github.com/cisco/libsrtp/archive/v2.4.2.tar.gz && \
    tar xfv v2.4.2.tar.gz && \
    cd libsrtp-2.4.2 && \
    ./configure --prefix=/usr --enable-openssl && \
    make shared_library && make install

# Install Janus WebRTC Server
RUN git clone https://github.com/meetecho/janus-gateway.git && \
    cd janus-gateway && \
    sh autogen.sh && \
    ./configure --prefix=/opt/janus --enable-websockets --enable-post-processing && \
    make && make install && \
    # Update library cache
    ldconfig

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip3 install -r /app/requirements.txt

# Copy application code
COPY app/ /app/
COPY app/janus-config/ /opt/janus/etc/janus/

# Set working directory
WORKDIR /app

# Expose ports (add 7088 for admin, 8188 for WebSocket)
EXPOSE 8080 8088 8188 7088 7188 20000-40000/udp

# Start script
COPY start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"]
