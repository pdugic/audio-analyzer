import asyncio
from typing import Callable, Iterator, Dict
import numpy as np
from pydub.utils import ratio_to_db
import socketio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from pydub import AudioSegment
from pydub.generators import WhiteNoise, Sine
from pydub.effects import normalize
from scipy.signal import hilbert
import datetime
import time

def utc_now_iso() -> str:
    ns = time.time_ns()
    s = ns // 1_000_000_000
    n = ns % 1_000_000_000
    dt = datetime.datetime.fromtimestamp(s, tz=datetime.timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S') + f'.{n:06d}Z'

AUDIO_SEGMENT_DURATION_MS = 10000  # Duration of each audio segment in milliseconds
SILENCE_SEGMENT_DURATION_MS = 100  # Duration of each audio segment in milliseconds
CHUNK_PERIOD_MS = 100  # Length of the audio chunk which will be sent to clients

# --- CORE GENERATORS (As requested) ---
def get_audio_chunks(filepath: str = "./input.mp3"):
    return AudioSegment.from_file(filepath).set_channels(1).set_sample_width(2)

def get_white_noise(duration_ms=AUDIO_SEGMENT_DURATION_MS):
    noise = WhiteNoise().to_audio_segment(duration=duration_ms)
    normalize(noise)
    return noise

def get_multiple_sines(duration_ms=AUDIO_SEGMENT_DURATION_MS):
    half_amplitude_ratio = .1
    gain_in_db = ratio_to_db(half_amplitude_ratio)
    sines = []
    for freq in [60,
                 500, 
                 1000,3000, 5000,
                 7000,
                 9000, 11000,
                 13000, 15000,
                 17000, 19000,
                 21000
                 ]:
        sines.append(Sine(freq, sample_rate=44100).to_audio_segment(duration=duration_ms).apply_gain(gain_in_db))

    combined = sines[0]
    for sine in sines[1:]:
        combined = combined.overlay(sine)
    normalize(combined);
    return combined

def get_silence(duration_ms=SILENCE_SEGMENT_DURATION_MS):
    return AudioSegment.silent(duration=duration_ms, frame_rate=44100)

# type alias for generator factory
GeneratorFactory = Callable[[], AudioSegment]

modes: Dict[str, GeneratorFactory] = {
    "noise": get_white_noise,
    "sines": get_multiple_sines,
}

# --- FASTAPI & SOCKET.IO SETUP ---
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
socket_app = socketio.ASGIApp(sio, app)

class StreamManager:
    def __init__(self):
        self.state = "idle"  # idle, running, paused
        self.task = None
        self.mode = "noise"  # noise, sines
        self.nr = 0

    def get_chunks_from_segment(self, segment: AudioSegment, chunk_ms=CHUNK_PERIOD_MS):
        for i in range(0, len(segment), chunk_ms):
            yield segment[i : i + chunk_ms]

    def to_iq_stream(self, audio_generator):
        for segment in audio_generator:
            samples = np.array(segment.get_array_of_samples(), dtype=np.float32)
            analytic_signal = hilbert(samples)
            yield analytic_signal, segment.frame_rate, segment

    async def send_data_timed(self, generator:Iterator, period_ms: int = CHUNK_PERIOD_MS):
        """Send generator items and ensure each iteration ends exactly `period` milliseconds
        after the previous one (as precisely as asyncio allows) using the loop's
        monotonic clock.
        """
        loop = asyncio.get_running_loop()
        next_end = loop.time()

        for iq_data, fs, _ in generator:
            if self.state == "idle":
                break
            self.nr += 1

            # Schedule the next target end time (strict increments)
            next_end += period_ms / 1000.0

            # Emit as binary data to group of clients listening to this mode (room)
            await sio.emit('iq_data_segment', room=self.mode, data=[self.nr, iq_data.astype(np.complex64).tobytes()])

            # Sleep until the target end time (if still in future)
            sleep_time = next_end - loop.time()
            if sleep_time > 0:
                # Small sleeps are fine; asyncio uses the loop's monotonic clock
                await asyncio.sleep(sleep_time)
            else:
                # We missed the deadline; continue immediately
                pass

    async def stream_worker(self):
        # Select source
        factory = modes.get(self.mode)
        if factory is None:
            raise ValueError(f"unknown mode: {self.mode}")
        
        seqment = factory()
        iq_gen_signal = self.to_iq_stream(self.get_chunks_from_segment(seqment))

        while True:
            print(f"{utc_now_iso()} Start sending next segment in mode {self.mode}") 

            # Send segment to client, and prepare next segment AND next silence segment in background
            _, next_segment, silence_segment = await asyncio.gather (
                self.send_data_timed(iq_gen_signal),
                asyncio.to_thread(factory),
                asyncio.to_thread(get_silence))

            silence_signal = self.to_iq_stream(self.get_chunks_from_segment(silence_segment))
            await self.send_data_timed(silence_signal)
            iq_gen_signal = self.to_iq_stream(self.get_chunks_from_segment(next_segment))
            if self.state == "idle":
                break
        self.state = "idle"

sm_noise = StreamManager()
sm_noise.mode = "noise"
sm_sines = StreamManager()
sm_sines.mode = "sines"

async def start_streams():
    if sm_noise.state != "idle" or sm_sines.state != "idle":
        raise RuntimeError("Streams already running")
    sm_noise.state = "running"
    sm_sines.state = "running"
    sm_noise.task = asyncio.create_task(sm_noise.stream_worker())
    sm_sines.task = asyncio.create_task(sm_sines.stream_worker())

@sio.event
async def connect(sid, environ):
    print(f"{utc_now_iso()} Client connected: {sid}")

@sio.event
async def set_mode(sid, mode: str = "noise"):
    if mode not in ["noise", "sines"]:
        return
    socket_in_rooms = sio.rooms(sid)
    for room in socket_in_rooms:
        await sio.leave_room(sid, room)
    await sio.enter_room(sid,mode)


@app.post("/start")
async def start():
    await start_streams()
    return {"status": "started"}

@app.post("/stop")
async def stop():
    sm_noise.state = "idle"
    sm_sines.state = "idle"
    return {"status": "stopped"}

async def start_server(port: int = 8000, auto_start: bool = True):
    import uvicorn

    print(f"{utc_now_iso()} Starting IQ generator on port {port}, auto_start_stream={auto_start}")
    config = uvicorn.Config(socket_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)

    tasks = [server.serve()]
    if auto_start:
        tasks.append(start_streams())

    # Run server and optionally streams concurrently in the same event loop
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description='IQ data generator server, generates audio IQ data streams over Socket.IO.')
    parser.add_argument('--port', type=int, default=None, help='Port to listen on (overrides IQ_GENERATOR_PORT env var)')
    parser.add_argument('--auto-start-stream', type=str, choices=['true', 'false'], default=None, help='Set to "true" or "false" to control whether streams are auto-started (overrides IQ_GENERATOR_AUTO_START_STREAM). If omitted, env var or default True is used.')
    args = parser.parse_args()

    # Resolve port: CLI > ENV > default
    port = args.port if args.port is not None else int(os.getenv('IQ_GENERATOR_PORT', '8000'))

    # Resolve auto_start_stream: CLI (if provided) > ENV > default True
    env_auto = os.getenv('IQ_GENERATOR_AUTO_START_STREAM')
    if args.auto_start_stream is not None:
        auto_start = args.auto_start_stream.lower() in ('1', 'true', 'yes', 'y')
    elif env_auto is not None:
        auto_start = env_auto.lower() in ('1', 'true', 'yes', 'y')
    else:
        auto_start = True

    asyncio.run(start_server(port=port, auto_start=auto_start))
