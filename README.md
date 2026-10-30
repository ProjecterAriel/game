# AeroWorld

A cross-platform flight-game foundation: FastAPI + MongoDB backend, responsive web game client, Expo Android WebView shell, and Electron Windows shell.

## Repository structure
- `main.py`: FastAPI API, auth, MongoDB persistence, AI proxy, WebSocket voice/positions
- `web/`: responsive game interface, Cesium globe and Three.js hangar scene
- `App.tsx`, `app.json`, `eas.json`: Expo Android client
- `windows/`: Electron desktop wrapper
- `render.yaml`: Render deployment blueprint

## Render
Create a Render Web Service from this repository, runtime Python:
- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health: `/health`

Set environment variables: `MONGODB_URI`, `MONGODB_DB=aeroworld`, `JWT_SECRET` (long random secret), `CESIUM_ION_TOKEN`, `OPENWEATHER_API_KEY`, `GROQ_API_KEY`, `GROQ_MODEL=llama-3.3-70b-versatile`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`. Never put secrets in the client or commit them.

## Android (Codespaces)
```bash
npm install
npx eas-cli login
npx eas-cli build:configure
```
Set `EXPO_PUBLIC_API_URL` in the EAS preview environment (replace the URL with your actual Render service URL), then:
```bash
npx eas-cli env:create --environment preview --name EXPO_PUBLIC_API_URL --value https://YOUR-RENDER-SERVICE.onrender.com --visibility plaintext\nnpx eas-cli build --platform android --profile preview
```

## Windows
```bash
cd windows
npm install
npm run dist
```
The GitHub Actions workflow also creates a Windows installer and portable build.

## Local backend
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```
Open `/preview`. Configure MongoDB and API keys before registering.

## Model credits
- Aircraft GLBs: [amvlab/aircraft-models](https://github.com/amvlab/aircraft-models), CC BY 4.0. The A320/A350/A380/B737/B787 logo-free GLBs are loaded from its public `models/` directory.
- Hangar / airport scene: [Airport Terminal and Ground Operations starter GLB](https://cdn.3dassets.dev/assets/26093/v1/model.glb), CC0 1.0; pack details: [3DAssets pack](https://3dassets.dev/packs/airport-terminal-and-ground-operations).
- S7 A320: [Sketchfab model](https://sketchfab.com/3d-models/airbus-a320-s7-airlines-3ddd1bb9dd5e4d1eb7c6e082e5e75178), CC BY; embedded as an interactive viewer and attribution is required.
- Darkstar: [SR-72 Darkstar by Cem Gürbüz](https://sketchfab.com/3d-models/lockheed-martin-sr72-darkstar-topgun-maverick-3578c297f98e403aa4c079e0c884953b), CC BY; embedded as an interactive viewer and attribution is required.
- The hangar loads the CC0 airport/ground-operations GLB scene with the A320-family models overlaid in Three.js; S7 and Darkstar use their Sketchfab interactive embeds. Their downloadable GLB files still need to be added locally before those two aircraft can be used as in-flight Cesium models.

## Current prototype scope
Authentication, settings persistence, AI text/image proxy, globe/map selection, weather tile proxy, current weather and five-day forecast cards, online position records and WebSocket audio broadcast are scaffolded. This is an initial functional foundation, not a finished flight simulator: detailed flight physics, synchronized 3D multiplayer aircraft, route navigation, full weather animation refinements, robust voice-room membership, and native microphone permission handling still require implementation and device testing.
