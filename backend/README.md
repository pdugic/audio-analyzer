# Audio Analyzer — Backend

✅ **What this repository contains**

- Python backend tools that generate I/Q audio and analyze it in real-time:
  - `audio_iq_generator.py` — a configurable I/Q data generator and Socket.IO server (default port **8000**).
  - `audio_filter_analyzer.py` — connects to an I/Q generator, applies filters, produces amplitude/spectrum JSON (`audio_frame`) (default port **8080**).

---

## Prerequisites ⚙️

- macOS / Linux / Windows
- Python 3.10+ (recommended)
- ffmpeg (required for `pydub` to read audio files). Install via Homebrew on macOS:

```bash
brew install ffmpeg
```

---

## Setup (virtual environment + deps) 🛠️

1. Create and activate a virtualenv (recommended):

```bash
python3 -m venv .venv
source .venv/bin/activate  # macOS / Linux
# .venv\Scripts\activate  # Windows (PowerShell)
```

2. Install Python dependencies:

```bash
pip install -r requirements.txt
```

---

## `audio_iq_generator.py` — generator / Socket.IO server 🔊

Purpose: produce audio segments (noise / sines / mp3 variants) and emit `iq_data_segment` Socket.IO messages.

Defaults
- Port: `8000`
- Auto-start streams: `true`

CLI options (CLI has priority over env vars):
- `--port <int>` — port to listen on (env var `IQ_GENERATOR_PORT`).
- `--auto-start-stream true|false` — whether streams start automatically on server start (env var `IQ_GENERATOR_AUTO_START_STREAM`).

Examples

- Start server with defaults:

```bash
python3 audio_iq_generator.py
```

- Start server on port 9000 and do NOT auto-start streams:

```bash
python3 audio_iq_generator.py --port 9000 --auto-start-stream false
```

- Same via environment variables:

```bash
export IQ_GENERATOR_PORT=9000
export IQ_GENERATOR_AUTO_START_STREAM=false
python3 iq_generator.py
```

Available Socket.IO events (from generator):
- `iq_data_segment` — binary segments with `[segment_nr, bytes]`.

HTTP endpoints
- `POST /start` — request generator to start streaming (if not auto-started).
- `POST /stop` — stop streaming.

Notes
- The generator uses a 100 ms chunk period to emit `iq_data_segment` messages in realtime.

---

## `audio_filter_analyzer.py` — filter & analyzer service 📈

Purpose: connect to an I/Q generator server, apply configurable filters, compute:
- `audio_frame` JSON containing: `sample_rate`, `time_pos`, `amplitude` (downsampled), and `spectrum` (freqs + magnitude)
- a WAV streaming endpoint (GET `/audio-stream`) that yields reconstructed audio
- `POST /set-filter?low_cut_in=<>&high_cut_in=<>` to set filter parameters and reset state
- `GET /filters` to read current filter values

Configuration
- CLI `--generator-url <url>` (overrides env var `IQ_GENERATOR_URL`)
- Default generator URL: `http://localhost:8000`

Examples

- Start analyzer and connect to default generator:

```bash
python3 audio_filter_analyzer.py
```

- Use a remote generator:

```bash
python3 audio_filter_analyzer.py --generator-url http://192.168.1.10:8000
```

- Query or update filters:

```bash
# Read
curl http://localhost:8080/filters

# Update
curl -X POST "http://localhost:8080/set-filter?low_cut_in=3000&high_cut_in=20"
```

Socket events
- `audio_frame` — analyzer emits structured JSON (see above) to connected clients via Socket.IO when a new chunk is processed.

---

## Example integration / quick test 🧪

1. Start generator:

```bash
python3 audio_iq_generator.py
```

2. Start filter/analyzer (connects to `http://localhost:8000` by default):

```bash
python3 audio_filter_analyzer.py
```

3. Use `test_stream.py` to drive filter changes or to start/stop the generator from the CLI.

4. Use a small client (Socket.IO, browser, or an Angular app) to listen to `audio_frame` events and render amplitude/spectrum.

---

## Docker

A minimal set of Dockerfiles and a `docker-compose.yml` are included to build and run the services inside containers.

### Build images

From the repository root (recommended, so Docker build context includes `requirements.txt`):

```bash
# Build generator image
docker build -f backend/Dockerfile.iq_generator -t audio-iq-generator .

# Build analyzer image
docker build -f backend/Dockerfile.iq_filter_analyzer -t audio-iq-analyzer .
```

### Run with docker-compose (recommended)

The included `docker-compose.yml` defines a `custom_bridge` network and maps ports so the services are reachable from the host.

```bash
# Build and run both services
docker compose up --build

# Run in background
docker compose up --build -d
```

By default these will expose:
- Generator: `localhost:8000` (and container address 178.1.1.1 if using the compose network)
- Analyzer: `localhost:8080` (and container address 178.1.1.2 if using the compose network)

### Direct `docker run` examples

If you prefer to run a single container:

```bash
# generator (override envs as needed)
docker run -p 8000:8000 -e IQ_GENERATOR_AUTO_START_STREAM=true audio-iq-generator

# analyzer connecting to a generator at host IP
docker run -p 8080:8080 -e IQ_GENERATOR_URL=http://host-ip:8000 audio-iq-analyzer
```

Notes:
- The Dockerfiles install `ffmpeg` to support `pydub`.
- If you prefer the containers to use a different subnet or to appear directly on your LAN, consider a `macvlan` configuration (advanced networking).

---

## Notes & Tips 💡

- CORS: the backend allows cross-origin requests (`*`) so a local Angular/React app can fetch endpoints directly.
- Timestamps: server logs use ISO8601 UTC timestamps with sub-second precision.
- If you change filter parameters frequently, consider debounce logic on the UI to avoid overwhelming the analyzer.

---

## Contributing / Developer hints

- Linting and formatting are not enforced in the repo — feel free to run `black` / `isort` locally.
- Tests: there are no automated tests yet; adding UTs around the filter math and JSON payloads is recommended.

---
