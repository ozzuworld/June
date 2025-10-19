┌─────────────────────────────────────────────────────┐
│           LiveKit Room: "ozzu-main"                 │
│                                                     │
│  Participant 1: Client (user)                      │
│      - Publishes: microphone audio                 │
│      - Subscribes: TTS audio responses             │
│                                                     │
│  Participant 2: STT Service                        │
│      - Subscribes: ALL audio tracks                │
│      - Processing: Transcribe → Webhook            │
│                                                     │
│  Participant 3: TTS Service                        │
│      - Publishes: AI response audio                │
│      - Triggered by: Orchestrator via API          │
│                                                     │
└─────────────────────────────────────────────────────┘
                        ↓
                  Orchestrator
              (webhook receiver + AI)