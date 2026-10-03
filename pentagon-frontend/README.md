# Pentagon Frontend

React, TypeScript, Vite, and Tailwind frontend for the sibling
`pentagon-backend` service. The backend owns NVIDIA credentials and all
conversation, model, document, media, and speech operations.

Requires Node.js 22.12 or newer.

## Run the development preview

Start FastAPI in one terminal from `pentagon-backend`:

```bash
source ../pentagon/bin/activate
uvicorn app.main:app --reload
```

In a second terminal, from `pentagon-frontend`:

```bash
cp .env.example .env
npm ci
npm run dev
```

Open the Vite URL printed in the terminal, normally <http://127.0.0.1:5173>.
Set `VITE_API_BASE_URL` in `.env` to point to another backend; it defaults to
`http://127.0.0.1:8000`.

FastAPI does not currently enable browser CORS. Vite therefore forwards only
`/api/*` requests to the configured Python backend during development. This
is a transport proxy with no application logic; chat, keys, and persistence
remain in FastAPI. The packaged Electron app uses the same small static-file
and `/api` proxy for that CORS boundary.

## Desktop packaging

Use `npm run electron:dev` to open the running Vite preview in Electron. Build
the installer for the current platform with `npm run package`, or use
`npm run package:linux`, `npm run package:mac`, or `npm run package:win` on a
matching build host. Keep the FastAPI backend running while the app is open.
For `npm run dev` and `npm run electron:dev`, set `VITE_API_BASE_URL` in
`.env`. For a packaged Electron app, set `PENTAGON_API_URL` in its launch
environment to use a backend other than `http://127.0.0.1:8000`.

## Product notes

- The context indicator reports message history loaded from the backend; the
  API does not currently return token-usage totals.
- There is no reasoning-depth field on the chat endpoint, so the composer
  leaves out a Deep Reasoning control rather than sending an unsupported flag.
- New threads stay client-side until the first message. Files queued on a new
  thread are uploaded after the thread is created and before that first chat.
- Porting the shared interface to React Native later will need native file
  picking, microphone recording and permissions, playback for returned PCM
  audio, and a mobile-compatible backend transport.
