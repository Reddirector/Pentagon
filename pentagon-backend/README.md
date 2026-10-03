# Pentagon Backend

Backend phases 1 through 7 for Pentagon, a bring-your-own-key NVIDIA NIM chat
workspace. NVIDIA keys are encrypted before they are stored. Chat is
orchestrated by LangGraph, can understand images and video, retrieve
conversation-scoped documents, search the web through Tavily, and handle
speech input/output. The `desktop/` folder contains the React + TypeScript UI
and Electron packaging shell.

## Requirements

- Python 3.11 or newer
- Node.js 22.12 or newer for the desktop app
- `ffmpeg` and `ffprobe` on `PATH` for video uploads
- An NVIDIA NIM API key beginning with `nvapi-` for chat
- A Tavily API key for live web search

The workspace virtual environment is named `pentagon` and lives next to this
project folder.

## Run locally

From `/home/aditya/Desktop/Pentagon`:

```bash
source pentagon/bin/activate
cd pentagon-backend
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put the generated Fernet value in `.env` as `KEY_ENCRYPTION_SECRET`. Set
`TAVILY_API_KEY` for web search. Keep the Fernet value private and back it up:
stored NVIDIA keys cannot be decrypted without it. The default SQLite database
is `pentagon.db`; persistent Chroma data is stored in `chroma_data/`.

Install packages and start the server:

```bash
python -m pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python -m piper.download_voices en_US-lessac-medium --download-dir ./speech_models
uvicorn app.main:app --reload
```

The API is at `http://127.0.0.1:8000`; interactive API docs are at
`http://127.0.0.1:8000/docs`.

## Run Dev Server

From `/home/aditya/Desktop/Pentagon/pentagon-backend`, activate the workspace
environment and start Uvicorn with reload enabled:

```bash
source ../pentagon/bin/activate
uvicorn app.main:app --reload
```

FastAPI's interactive Swagger UI is at <http://127.0.0.1:8000/docs> and its
ReDoc UI is at <http://127.0.0.1:8000/redoc>. Both use FastAPI's defaults and
remain enabled. The REST Client collection in [`requests.http`](requests.http)
has clickable examples for the API routes; install the [VS Code REST Client
extension](https://marketplace.visualstudio.com/items?itemName=humao.rest-client),
store a key, fetch models, and create a conversation before running the
dependent requests. Key requests prompt for the secret instead of embedding it
in the collection.

## Endpoints

- `POST /api/keys/validate` checks a key against NVIDIA without storing it.
- `POST /api/keys` validates and stores an encrypted key for a `user_id`.
- `GET /api/models?user_id=...` lists that user's models, cached for five
  minutes.
- `POST /api/conversations` creates an empty conversation.
- `GET /api/conversations?user_id=...` lists a user's conversations.
- `GET /api/conversations/{conversation_id}` returns its message history.
- `POST /api/chat` accepts JSON or multipart form data (including optional
  image or video attachments), streams text, then a
  `metadata` SSE event with `sources_used` and `execution_trace`.
- `POST /api/documents/upload` accepts PDF, DOCX, and TXT multipart uploads.
- `GET /api/documents?user_id=...&conversation_id=...` lists active documents.
- `DELETE /api/documents/{document_id}?user_id=...` removes a document.
- `POST /api/voice/transcribe` accepts a webm, wav, or mp3 recording and returns
  its transcript with transcription timing.
- `POST /api/voice/synthesize` streams raw PCM audio for JSON text input.

Each conversation has its own Chroma collection. The server checks the user's
NVIDIA model list for an embedding model and uses NVIDIA's `/v1/embeddings`
when available; otherwise it uses local `all-MiniLM-L6-v2` embeddings. Tavily
search is optional at startup; if it is not configured or a search fails, the
chat continues without web results and reports the outcome in its trace.

Chat image attachments accept jpg, png, and webp files smaller than 10 MB, or
base64 data URIs in JSON. Uploaded image bytes are stored under
`image_uploads/<conversation_id>/<message_id>.<extension>`; the message row
stores only that path. Vision analysis uses
`meta/llama-3.2-11b-vision-instruct`, selected after checking the stored key's
live NVIDIA model catalog. When an image is analyzed, the response metadata
includes the model and a short description under `sources_used.image`, and the
vision branch's status and duration appear in `execution_trace`.

Video attachments use the multipart `video` field. Files must be 50 MB or
smaller and no longer than 60 seconds. The server normalizes supported video
files through ffmpeg at `VIDEO_SAMPLING_FPS` (default 1 frame per second),
scales frames to at most one megapixel, and removes its temporary files after
preparation. It sends the resulting MP4 directly as a video data URI to
`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`; the trace reports the native
model path and exact frame count. NVIDIA currently lists this model as a free
hosted endpoint and documents video input support. The generated video summary
joins image/RAG/web context before the chat model responds.

Conversations persist their active model. Set it with
`PATCH /api/conversations/{conversation_id}` and a JSON `model` field. On a
switch, the destination model summarizes the saved conversation once; the
backend stores that summary and supplies it as a system message followed by
the latest six raw messages on later turns. Chat requests using a different
model are rejected until the conversation is switched. `GET /api/models`
includes `supports_vision` for each model, and the chat trace reports when a
stored conversation summary was used.

Example:

```bash
curl -N http://127.0.0.1:8000/api/chat \
  -F 'user_id=local-user' \
  -F 'conversation_id=CONVERSATION_ID' \
  -F 'model=nvidia/nemotron-3-super-120b-a12b' \
  -F 'message=Describe the distinct moments with timestamps.' \
  -F 'video=@clip.mp4'
```

## Voice

The current key's `/v1/models` response contains NVIDIA translation models but
no ASR or TTS model. NVIDIA lists Riva ASR as downloadable rather than a free
hosted endpoint, and its free Magpie zero-shot TTS endpoint requires separate
access approval. This workspace therefore uses local faster-whisper `base`
transcription and Piper `en_US-lessac-medium` speech synthesis. The Whisper
model downloads on its first transcription request; the Piper voice can be
preloaded with the setup command above. Voice timing is logged and included in
chat `execution_trace`.

If you later have an accessible NVIDIA Speech NIM deployment, set
`NVIDIA_RIVA_ASR_URL` and/or `NVIDIA_RIVA_TTS_URL` to its HTTP base URL. The
backend tries those providers first with the user's saved NVIDIA key, then
falls back locally if they fail.

Transcribe a short recording:

```bash
curl -sS http://127.0.0.1:8000/api/voice/transcribe \
  -F 'user_id=local-user' \
  -F 'file=@question.webm'
```

Send the returned transcript to chat and request audio in the same SSE stream:

```bash
curl -N http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"local-user","conversation_id":"CONVERSATION_ID","model":"nvidia/nemotron-3-super-120b-a12b","message":"YOUR_TRANSCRIPT","respond_with_audio":true,"transcription_duration_ms":25.0,"transcription_provider":"faster-whisper:base"}'
```

The stream sends text `token` events first, then base64 `audio_chunk` events
with PCM format metadata, followed by `audio_end`, `metadata`, and `done`. The
chat trace records transcription, LLM time-to-first-token, and synthesis
time-to-first-audio. The standalone synthesis endpoint streams signed 16-bit
little-endian PCM with `X-Audio-*` format headers; clients can play it through
Web Audio or wrap it in a WAV header.

The API never returns the plaintext NVIDIA key. Request validation errors omit
rejected input values.

## Validate and store a key

Use a shell variable so the key is not placed in command history:

```bash
read -s NVIDIA_API_KEY
curl -sS http://127.0.0.1:8000/api/keys/validate \
  -H 'Content-Type: application/json' \
  -d "{\"api_key\":\"${NVIDIA_API_KEY}\"}"
curl -sS http://127.0.0.1:8000/api/keys \
  -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"local-user\",\"api_key\":\"${NVIDIA_API_KEY}\"}"
```

The store response includes only a masked key. The same `user_id` identifies
the key and conversations.

## Desktop app

The React + TypeScript interface calls the FastAPI endpoints directly through
the Vite development proxy. Packaged Electron builds use a small Express
server to serve the static UI and forward `/api/*` requests unchanged to
FastAPI; it contains no model or business logic. Keep the Python backend
running separately while using the desktop app.

Terminal 1, from `/home/aditya/Desktop/Pentagon`:

```bash
source pentagon/bin/activate
cd pentagon-backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd /home/aditya/Desktop/Pentagon/pentagon-backend/desktop
npm ci
npm run electron:dev
```

The app validates an NVIDIA key while it is typed, stores it only through the
encrypted backend endpoint, restores conversation history on load, and streams
chat SSE events into the message view. Model changes call the conversation
PATCH endpoint; image/video uploads, voice transcription, spoken replies,
document uploads, and web/document references use the Python API. Only the
generated `user_id` is kept in browser storage. To point to another backend,
set `PENTAGON_API_URL` before starting Vite or Electron.

Build a desktop package for the current operating system with:

```bash
npm run package
```

The Electron shell uses isolated, sandboxed renderer content. Build Windows,
macOS, and Linux installers on their matching operating systems. Adapting the
shared React interface to React Native for iOS and Android is a follow-up; it
will need native file picking, microphone permissions and recording, PCM audio
playback, and a mobile-compatible API transport.

## Create a conversation and chat

```bash
curl -sS http://127.0.0.1:8000/api/conversations \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"local-user","title":"Research"}'
```

Use the returned ID in the chat request. `use_web_search` can be `true` to
force search, `false` to skip it, or omitted to let the intent router detect
current-information questions.

```bash
curl -N http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"local-user","conversation_id":"CONVERSATION_ID","model":"meta/llama-3.1-70b-instruct","message":"What is the latest news about NVIDIA?"}'
```

The stream has a `conversation` event, token events, a trailing `metadata`
event containing web/document sources and per-node execution timings, then a
`done` event.

Send an image with a question using multipart form data:

```bash
curl -N http://127.0.0.1:8000/api/chat \
  -F 'user_id=local-user' \
  -F 'conversation_id=CONVERSATION_ID' \
  -F 'model=nvidia/nemotron-3-super-120b-a12b' \
  -F 'message=What is in this picture?' \
  -F 'image=@picture.png'
```

JSON clients can instead send an `image` string such as
`data:image/png;base64,<base64-data>` alongside the regular chat fields.
The message history exposes the saved image path; raw image bytes are not
stored in SQLite.

Switch an existing conversation to another model:

```bash
curl -sS -X PATCH http://127.0.0.1:8000/api/conversations/CONVERSATION_ID \
  -H 'Content-Type: application/json' \
  -d '{"model":"nvidia/nemotron-3-super-120b-a12b"}'
```

## Upload a document

```bash
curl -sS http://127.0.0.1:8000/api/documents/upload \
  -F 'user_id=local-user' \
  -F 'conversation_id=CONVERSATION_ID' \
  -F 'file=@report.pdf'
```

Chunks use a 2,000-character target (about 500 English tokens) with a
200-character overlap. Their text, embeddings, and source metadata live in the
conversation's persistent Chroma collection; the relational database stores
document ownership and filenames. The
conversation's collection is checked during every chat and retrieved chunks
are limited to the four closest matches.

## Verify encrypted storage

Inspect `api_keys.encrypted_key` in `pentagon.db`: it should be Fernet
ciphertext. `masked_key` is safe to display. Do not put `.env`, the database,
or `chroma_data/` in source control.

## Known limitations

- Live Tavily search requires setting `TAVILY_API_KEY`; the key is currently
  unset in this workspace.
- Scanned PDFs without an embedded text layer need OCR before document
  retrieval can use their contents.
