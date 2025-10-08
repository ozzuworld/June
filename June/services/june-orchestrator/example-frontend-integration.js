/**
 * Example Frontend Integration for June Voice Chat
 * WebSocket Audio Input/Output with the Enhanced Orchestrator
 */

class JuneVoiceChat {
    constructor(websocketUrl, options = {}) {
        this.websocketUrl = websocketUrl;
        this.options = {
            audioSampleRate: 16000,
            audioBitDepth: 16,
            audioChannels: 1,
            chunkSize: 4096,
            ...options
        };
        
        this.ws = null;
        this.mediaRecorder = null;
        this.audioContext = null;
        this.microphone = null;
        this.isRecording = false;
        this.audioChunks = [];
        this.sessionId = null;
        
        this.audioQueue = [];
        this.isPlayingAudio = false;
    }

    async connect(token = null) {
        try {
            // Construct WebSocket URL with optional token
            const wsUrl = token ? `${this.websocketUrl}?token=${encodeURIComponent(token)}` : this.websocketUrl;
            
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = (event) => {
                console.log('🔌 Connected to June Orchestrator');
                this.onConnectionOpen?.(event);
            };
            
            this.ws.onmessage = (event) => {
                this.handleMessage(event);
            };
            
            this.ws.onclose = (event) => {
                console.log('🔌 Disconnected from June Orchestrator');
                this.onConnectionClose?.(event);
            };
            
            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.onConnectionError?.(error);
            };
            
        } catch (error) {
            console.error('Connection error:', error);
            throw error;
        }
    }

    async handleMessage(event) {
        try {
            // Check if it's binary audio data
            if (event.data instanceof ArrayBuffer) {
                await this.handleAudioChunk(new Uint8Array(event.data));
                return;
            }
            
            // Handle text messages
            const message = JSON.parse(event.data);
            console.log('📨 Received message:', message.type);
            
            switch (message.type) {
                case 'connected':
                    this.sessionId = message.session_id;
                    console.log('✅ Session established:', this.sessionId);
                    this.onSessionEstablished?.(message);
                    break;
                    
                case 'audio_stream_start':
                    console.log(`🎵 Starting audio stream: ${message.total_chunks} chunks`);
                    this.audioChunks = [];
                    this.expectedChunks = message.total_chunks;
                    break;
                    
                case 'audio_stream_complete':
                    console.log('✅ Audio stream complete');
                    await this.playBufferedAudio();
                    break;
                    
                case 'text_response':
                    console.log('💬 AI Response:', message.text);
                    this.onTextResponse?.(message);
                    break;
                    
                case 'transcription_result':
                    console.log('📝 Transcription:', message.text);
                    this.onTranscriptionResult?.(message);
                    break;
                    
                case 'processing_status':
                    console.log('⏳ Status:', message.status);
                    this.onProcessingStatus?.(message);
                    break;
                    
                case 'audio_chunk_received':
                    // Acknowledgment of sent audio chunk
                    break;
                    
                case 'error':
                    console.error('❌ Server error:', message.message);
                    this.onError?.(message);
                    break;
                    
                default:
                    console.log('Unknown message type:', message.type);
            }
        } catch (error) {
            console.error('Message handling error:', error);
        }
    }

    async handleAudioChunk(audioData) {
        // Buffer incoming audio chunks
        this.audioChunks.push(audioData);
    }

    async playBufferedAudio() {
        try {
            if (this.audioChunks.length === 0) return;
            
            // Concatenate all audio chunks
            const totalLength = this.audioChunks.reduce((sum, chunk) => sum + chunk.length, 0);
            const combinedAudio = new Uint8Array(totalLength);
            
            let offset = 0;
            for (const chunk of this.audioChunks) {
                combinedAudio.set(chunk, offset);
                offset += chunk.length;
            }
            
            // Create audio blob and play
            const audioBlob = new Blob([combinedAudio], { type: 'audio/wav' });
            const audioUrl = URL.createObjectURL(audioBlob);
            
            const audio = new Audio(audioUrl);
            audio.onended = () => {
                URL.revokeObjectURL(audioUrl);
                this.isPlayingAudio = false;
                this.onAudioPlaybackEnd?.();
            };
            
            this.isPlayingAudio = true;
            this.onAudioPlaybackStart?.();
            await audio.play();
            
        } catch (error) {
            console.error('Audio playback error:', error);
            this.isPlayingAudio = false;
        }
    }

    async initializeMicrophone() {
        try {
            // Request microphone access
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: this.options.audioSampleRate,
                    channelCount: this.options.audioChannels,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });
            
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
                sampleRate: this.options.audioSampleRate
            });
            
            this.microphone = this.audioContext.createMediaStreamSource(stream);
            
            // Setup MediaRecorder for capturing audio
            this.mediaRecorder = new MediaRecorder(stream, {
                mimeType: 'audio/webm;codecs=opus'
            });
            
            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0 && this.isRecording) {
                    // Convert blob to array buffer and send via WebSocket
                    event.data.arrayBuffer().then(buffer => {
                        if (this.ws?.readyState === WebSocket.OPEN) {
                            this.ws.send(buffer);
                        }
                    });
                }
            };
            
            console.log('🎤 Microphone initialized');
            this.onMicrophoneReady?.();
            
        } catch (error) {
            console.error('Microphone initialization error:', error);
            throw error;
        }
    }

    async startRecording() {
        try {
            if (!this.mediaRecorder) {
                await this.initializeMicrophone();
            }
            
            if (this.mediaRecorder.state !== 'recording') {
                // Send start recording message
                this.sendMessage({
                    type: 'start_recording',
                    audio_config: {
                        sample_rate: this.options.audioSampleRate,
                        format: 'wav',
                        channels: this.options.audioChannels
                    }
                });
                
                this.mediaRecorder.start(100); // Capture in 100ms chunks
                this.isRecording = true;
                
                console.log('🎤 Started recording');
                this.onRecordingStart?.();
            }
        } catch (error) {
            console.error('Recording start error:', error);
            this.onRecordingError?.(error);
        }
    }

    stopRecording() {
        try {
            if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
                this.mediaRecorder.stop();
                this.isRecording = false;
                
                // Send stop recording message
                this.sendMessage({
                    type: 'stop_recording'
                });
                
                console.log('🎤 Stopped recording');
                this.onRecordingStop?.();
            }
        } catch (error) {
            console.error('Recording stop error:', error);
        }
    }

    sendTextMessage(text) {
        this.sendMessage({
            type: 'text_input',
            text: text,
            source: 'text'
        });
    }

    sendMessage(message) {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        } else {
            console.warn('WebSocket not connected');
        }
    }

    disconnect() {
        if (this.isRecording) {
            this.stopRecording();
        }
        
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        
        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }
        
        this.sessionId = null;
    }

    // Event handlers (to be overridden by user)
    onConnectionOpen = null;
    onConnectionClose = null;
    onConnectionError = null;
    onSessionEstablished = null;
    onTextResponse = null;
    onTranscriptionResult = null;
    onProcessingStatus = null;
    onError = null;
    onMicrophoneReady = null;
    onRecordingStart = null;
    onRecordingStop = null;
    onRecordingError = null;
    onAudioPlaybackStart = null;
    onAudioPlaybackEnd = null;
}

// Example usage:
/*
const voiceChat = new JuneVoiceChat('ws://localhost:8080/ws');

// Setup event handlers
voiceChat.onTextResponse = (message) => {
    document.getElementById('response').textContent = message.text;
};

voiceChat.onTranscriptionResult = (message) => {
    document.getElementById('transcription').textContent = message.text;
};

voiceChat.onProcessingStatus = (message) => {
    document.getElementById('status').textContent = message.message;
};

// Connect and initialize
voiceChat.connect().then(() => {
    console.log('Connected to June voice chat');
});

// Voice chat controls
document.getElementById('start-recording').onclick = () => voiceChat.startRecording();
document.getElementById('stop-recording').onclick = () => voiceChat.stopRecording();
document.getElementById('send-text').onclick = () => {
    const text = document.getElementById('text-input').value;
    voiceChat.sendTextMessage(text);
};
*/

export default JuneVoiceChat;
