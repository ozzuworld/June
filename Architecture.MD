┌─────────────────────────────────────────────────────────────────────────┐
│                         USER (LiveKit Client)                            │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                        ┌─────────▼──────────┐
                        │   LiveKit Room     │
                        │   (WebRTC/UDP)     │
                        │                    │
                        │ • Audio Streaming  │
                        │ • Data Channels    │
                        │ • Track Management │
                        └─────────┬──────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
  ┌─────▼─────┐          ┌───────▼────────┐      ┌────────▼────────┐
  │ STT       │          │ Turn Detector  │      │ Conversation    │
  │ Webhook   │◄─────────┤                │      │ Manager         │
  │           │          │ • VAD          │      │                 │
  │ • Partial │          │ • Semantic     │      │ • Participant   │
  │ • Final   │          │ • Timeout      │      │   Tracking      │
  │ • Audio   │          └────────────────┘      │ • Room State    │
  └─────┬─────┘                                  │ • Audio Tracks  │
        │                                        └────────┬────────┘
        │                                                 │
        └─────────────────────┬───────────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │ Enhanced Voice    │
                    │ Assistant Core    │
                    │                   │
                    │ ┌───────────────┐ │
                    │ │ Dialogue State│ │◄──┐
                    │ │ Tracker (DST) │ │   │
                    │ └───────┬───────┘ │   │
                    │         │         │   │
                    │ ┌───────▼───────┐ │   │
                    │ │ Intent        │ │   │
                    │ │ Classifier    │ │   │
                    │ └───────┬───────┘ │   │
                    │         │         │   │
                    │ ┌───────▼───────┐ │   │
                    │ │ Slot          │ │   │
                    │ │ Extractor     │ │   │
                    │ └───────┬───────┘ │   │
                    │         │         │   │
                    │ ┌───────▼───────┐ │   │
                    │ │ Context       │ │   │
                    │ │ Window Mgr    │ │   │
                    │ └───────┬───────┘ │   │
                    │         │         │   │
                    │ ┌───────▼───────┐ │   │
                    │ │ Personalization│ │  │
                    │ │ Engine        │ │   │
                    │ └───────┬───────┘ │   │
                    └─────────┼─────────┘   │
                              │             │
                    ┌─────────▼─────────┐   │
                    │ Redis Cache       │───┘
                    │                   │
                    │ • Conversation    │
                    │   History         │
                    │ • User Profiles   │
                    │ • Session State   │
                    │ • Summaries       │
                    └─────────┬─────────┘
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                 │
      ┌─────▼─────┐   ┌──────▼──────┐   ┌─────▼─────┐
      │ Gemini    │   │ Interruption│   │ Metrics   │
      │ LLM       │   │ Manager     │   │ Collector │
      │           │   │             │   │           │
      │ • Tools   │   │ • TTS Stop  │   │ • Latency │
      │ • Stream  │   │ • Queue     │   │ • Quality │
      │           │   │   Clear     │   │ • UX      │
      └─────┬─────┘   └─────────────┘   └─────┬─────┘
            │                                  │
            └───────────────┬──────────────────┘
                            │
                   ┌────────▼────────┐
                   │ TTS Service     │
                   │ (XTTS v2)       │
                   │                 │
                   │ • Voice Cloning │
                   │ • Streaming     │
                   │ • Queue Mgmt    │
                   └────────┬────────┘
                            │
                   ┌────────▼────────┐
                   │ LiveKit Audio   │
                   │ Publishing      │
                   └─────────────────┘
                            │
                   ┌────────▼────────┐
                   │ Observability   │
                   │                 │
                   │ • Prometheus    │
                   │ • Grafana       │
                   │ • Analytics     │
                   └─────────────────┘

ENHANCEMENTS:
✅ Dialogue State Tracking (DST)
✅ Intent recognition with confidence
✅ Semantic turn detection
✅ Advanced interruption handling
✅ User personalization
✅ Redis-backed persistence
✅ Context window management
✅ Comprehensive metrics
✅ Conversation analytics
✅ Error recovery strategies