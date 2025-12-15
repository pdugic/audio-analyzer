# backend/main.py
import asyncio
import numpy as np
import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydub import AudioSegment

# Socket.IO server
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=["*"], cors_allowed_methods=["*"])
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Socket.IO app
app = socketio.ASGIApp(sio, app)

AUDIO_PATH = "a110.mp3"
CHUNK_SIZE = 4096
DOWNSAMPLE_AMPLITUDE = 512

stopped_sids = set()

def load_mp3(path: str):
    audio = AudioSegment.from_file(path)
    if audio.channels > 1:
        audio = audio.set_channels(1)
    audio = audio.set_sample_width(2)
    sr = audio.frame_rate
    samples = np.frombuffer(audio.raw_data, dtype=np.int16).astype(np.float32)
    samples /= 32768.0
    return samples, sr


@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")

async def stream_data(sid):
    samples, sr = load_mp3(AUDIO_PATH)

    pos = 0
    total = len(samples)
    while pos < total:
        if sid in stopped_sids:
            print(f"Streaming stopped for: {sid}")
            stopped_sids.remove(sid)
            break

        end = min(pos + CHUNK_SIZE, total)
        frame = samples[pos:end]
        if len(frame) == 0:
            break

        # Amplitude (time domain)
        padded = frame
        if len(padded) < DOWNSAMPLE_AMPLITUDE:
            padded = np.pad(padded, (0, DOWNSAMPLE_AMPLITUDE - len(padded)))
        idx = np.linspace(0, len(padded) - 1, DOWNSAMPLE_AMPLITUDE).astype(int)
        amplitude = padded[idx]

        # Spectrum (frequency domain)
        win = np.hanning(len(frame))
        fft = np.fft.rfft(frame * win)
        mag = np.abs(fft)
        freqs = np.fft.rfftfreq(len(frame), d=1.0 / sr)

        bins = 256
        if len(mag) > bins:
            di = np.linspace(0, len(mag) - 1, bins).astype(int)
            mag = mag[di]
            freqs = freqs[di]

        await sio.emit(
            "audio_frame",
            {
                "sample_rate": sr,
                "time_pos": pos / sr,
                "amplitude": amplitude.tolist(),
                "spectrum": {
                    "freqs": freqs.tolist(),
                    "magnitude": mag.tolist(),
                },
            },
            to=sid,
        )
        await asyncio.sleep(max(0.01, (end - pos) / sr))
        print(f"Sending loop end: {pos / sr}")
        pos = end

    await sio.emit("finished", {}, to=sid)

@sio.event
async def start_stream(sid, data):
    print(f"Start stream from {sid}: {data}")
    asyncio.create_task(stream_data(sid))

@sio.event
def disconnect(sid, reason):
    stopped_sids.add(sid)
    if reason == sio.reason.CLIENT_DISCONNECT:
        print('the client disconnected')
    elif reason == sio.reason.SERVER_DISCONNECT:
        print('the server disconnected the client')
    else:
        print('disconnect reason:', reason)

@sio.on('*')
def any_event(event, sid, data):
    print(f"Received event '{event}' from {sid} with data: {data}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)