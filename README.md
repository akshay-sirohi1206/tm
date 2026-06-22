# BharatBot — Pipecat Edition

Multilingual voice chat (Hindi / Marathi / English) powered by AWS Bedrock,
Polly, Transcribe, Comprehend, and the **[Pipecat](https://github.com/pipecat-ai/pipecat)** real-time AI framework.

## Project layout

```
bharatbot/
├── main.py                          # FastAPI app + startup
├── requirements.txt
├── .env.example
│
├── models/
│   └── schemas.py                   # Pydantic request models
│
├── services/
│   ├── aws_clients.py               # All boto3 client singletons
│   ├── db.py                        # SQLite helpers (WAL, DDL, CRUD)
│   ├── language.py                  # Comprehend detection + AWS Translate
│   ├── audio.py                     # Polly TTS + Transcribe STT + S3
│   └── llm.py                       # Bedrock direct / KB RAG
│
├── pipelines/
│   └── bharatbot_pipeline.py        # ★ Pipecat pipeline
│
└── routers/
    ├── sessions.py                  # Session CRUD endpoints
    └── chat.py                      # Chat endpoints (delegates to pipeline)
```

## How Pipecat is integrated

Every chat request (text **or** voice) flows through a **linear Pipecat pipeline**
instead of a flat sequence of function calls:

```
BharatBotFrame
      │
      ▼
LanguageDetectionProcessor   detect_languages() + translate_to_english_mixed()
      │
      ▼
BedrockLLMProcessor          call_bedrock()  (direct or KB RAG)
      │
      ▼
TranslationProcessor         translate_from_english()
      │
      ▼
PollySynthesisProcessor      synthesise_speech()  → MP3 bytes
      │
      ▼
OutputCollectorSink          collects the finished BharatBotContext
```

For **voice** input, AWS Transcribe (STT) runs *before* the pipeline because it
is I/O-heavy and seeds the `BharatBotContext.original_text` field that the
pipeline picks up.

## API — unchanged contract

| Method | Path | Description |
|--------|------|-------------|
| POST | `/sessions` | Create session |
| GET | `/sessions` | List sessions |
| GET | `/sessions/{id}` | Get session |
| PATCH | `/sessions/{id}` | Update session |
| DELETE | `/sessions/{id}` | Soft-delete session |
| GET | `/sessions/{id}/messages` | Get messages |
| DELETE | `/sessions/{id}/messages` | Clear messages |
| POST | `/sessions/{id}/chat/text` | Session text chat |
| POST | `/sessions/{id}/chat/voice` | Session voice chat |
| POST | `/chat/text` | Stateless text chat |
| POST | `/chat/voice` | Stateless voice chat |
| POST | `/tts` | On-demand TTS — `{ text, lang }` → `{ audio_base64 }` |
| GET | `/sessions/{id}/messages/{msg_id}/audio` | Audio for a past message (presigned S3 URL or on-demand synthesis) |
| GET | `/health` | Health check |
| GET | `/ui` | HTML UI |

## Setup

```bash
cp .env.example .env   # fill in your AWS credentials
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
