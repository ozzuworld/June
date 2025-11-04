# Install STT dependencies (WhisperX with its own torch stack)
RUN /venv-stt/bin/pip install --upgrade pip setuptools wheel && \
    /venv-stt/bin/pip install --no-cache-dir -r /tmp/stt-requirements.txt && \
    rm -rf /root/.cache
