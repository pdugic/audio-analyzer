import asyncio
import socketio
import time
import datetime
import io
import numpy as np
from numpy.typing import NDArray
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from scipy import signal
import uvicorn

def utc_now_iso() -> str:
    ns = time.time_ns()
    s = ns // 1_000_000_000
    n = ns % 1_000_000_000
    dt = datetime.datetime.fromtimestamp(s, tz=datetime.timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S') + f'.{n:06d}Z'

class WavStreamManager:
    def __init__(self):
        # Use an asyncio Queue for non-blocking communication
        self.queue = asyncio.Queue()

    def create_wav_header(self, sample_rate, channels, bits_per_sample) -> bytes:
        """Returns a dummy WAV header with a very large size for streaming."""
        header = io.BytesIO()
        header.write(b'RIFF')
        header.write((0xFFFFFFFF).to_bytes(4, 'little')) # Fake size
        header.write(b'WAVEfmt ')
        header.write((16).to_bytes(4, 'little'))
        header.write((1).to_bytes(2, 'little')) # PCM
        header.write((channels).to_bytes(2, 'little'))
        header.write((sample_rate).to_bytes(4, 'little'))
        header.write((sample_rate * channels * bits_per_sample // 8).to_bytes(4, 'little'))
        header.write((channels * bits_per_sample // 8).to_bytes(2, 'little'))
        header.write((bits_per_sample).to_bytes(2, 'little'))
        header.write(b'data')
        header.write((0xFFFFFFFF).to_bytes(4, 'little')) # Fake size
        return header.getvalue()

    async def add_data(self, data: bytes):
        """Method 1: Adds data to the queue."""
        await self.queue.put(data)

    async def event_generator(self):
        """Method 2: Yields data from the queue to the client."""
        yield self.create_wav_header(44100, 1, 16)
        while True:
            data = await self.queue.get()      
            if data is not None: # Optional: use None as a 'stop' signal
                yield data
            else:
                break

data_generator = socketio.AsyncClient()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sio_server = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio_server, app, socketio_path='/filter/socket.io/')

stream_manager = WavStreamManager()

last_received_time = 0
bytes_in_last_second = 0

# Processing constants/state
fs = 44100.0
DOWNSAMPLE_AMPLITUDE = 20
BINS = 512
cumulative_samples = 0

mode = "noise"

def calculate_amplitude(filtered_iq_data):
    # --- Amplitude (time domain) ---
    padded = filtered_iq_data / 32768.0
    if len(padded) < DOWNSAMPLE_AMPLITUDE:
        padded = np.pad(padded, (0, DOWNSAMPLE_AMPLITUDE - len(padded)))
    idx = np.linspace(0, len(padded) - 1, DOWNSAMPLE_AMPLITUDE).astype(int)
    return padded[idx]

def calculate_spectrum(filtered_iq_data):
    frame = filtered_iq_data / 32768.0

    # --- Spectrum (frequency domain) ---
    win = np.hanning(len(frame))
    fft = np.fft.rfft(frame * win)
    mag = np.abs(fft)
    freqs = np.fft.rfftfreq(len(frame), d=1.0 / fs)
    return freqs, mag

def calculate_amplitude_spectrum(filtered_iq_data):
    """Calculates amplitude and spectrum from I/Q data."""
    amplitude = calculate_amplitude(filtered_iq_data)
    freqs, mag = calculate_spectrum(filtered_iq_data) 

    # Build JSON payload matching requested format
    audio_frame = {
        "sample_rate": fs,
        "amplitude": amplitude.tolist(),
        "spectrum": {
            "freqs": freqs.tolist(),
            "magnitude": mag.tolist(),
        },
        "filtered_raw_data": filtered_iq_data.astype(np.int16).tobytes()
    }
    return audio_frame

@data_generator.on('iq_data_segment')
async def on_data_from_generator(data):
    global last_received_time, bytes_in_last_second, last_received_segment_nr

    last_received_time = time.time()
    last_received_segment_nr = data[0]

    iq_data = np.frombuffer(data[1], dtype=np.complex64)

    bytes_in_last_second += len(iq_data.real)

    # Apply filters -> get filtered I samples as numpy array
    filtered = get_filtered_i_component(iq_data)
    audio_frame = calculate_amplitude_spectrum(filtered)
    
    try:
        await sio_server.emit('audio_frame', audio_frame)
    except Exception:
        # Don't let emit failures break streaming
        pass

    # Prepare WAV bytes for streaming response
    wav_bytes = filtered.astype(np.int16).tobytes()
    await stream_manager.add_data(wav_bytes)

async def print_status_repeatedly():
    global bytes_in_last_second
    while True:
        await asyncio.sleep(5.0)
        if time.time() - last_received_time > 5.2 or bytes_in_last_second == 0:
            print(f"{utc_now_iso()} Status: NO DATA incoming")
        else:
            print(f"{utc_now_iso()} Status: DATA incoming ({bytes_in_last_second} bytes/sec), last segment: {last_received_segment_nr}")
        bytes_in_last_second = 0

zi_low_i = zi_low_q = None
zi_high_i = zi_high_q = None
low_cut = 20.0
high_cut = 22000.0

client_sio_connected = False

def get_filtered_i_component(iq_data: NDArray[np.complex64]) -> NDArray[np.float32]:
    """Applies stateful filters to I/Q components and returns filtered samples (numpy array).

    Returns a numpy array (float32) containing the filtered I samples. The caller will
    compute amplitude/spectrum from this filtered data and convert to bytes for streaming.
    """
    global zi_low_i, zi_low_q, zi_high_i, zi_high_q
    global low_cut, high_cut, fs

    # Design filters
    sos_low = signal.butter(4, high_cut, 'lowpass', fs=fs, output='sos')
    sos_high = signal.butter(4, low_cut, 'highpass', fs=fs, output='sos')

    # Initialize filter states on the first chunk to ensure continuity
    if zi_low_i is None:
        # SOS state shape is (n_sections, 2)
        zi_low_i = np.zeros((sos_low.shape[0], 2))
        zi_low_q = np.zeros((sos_low.shape[0], 2))
        zi_high_i = np.zeros((sos_high.shape[0], 2))
        zi_high_q = np.zeros((sos_high.shape[0], 2))

    # Filter In-phase (I)
    i_filt, zi_low_i = signal.sosfilt(sos_low, iq_data.real, zi=zi_low_i)
    i_filt, zi_high_i = signal.sosfilt(sos_high, i_filt, zi=zi_high_i)
    
    # Filter Quadrature (Q)
    q_filt, zi_low_q = signal.sosfilt(sos_low, iq_data.imag, zi=zi_low_q)
    q_filt, zi_high_q = signal.sosfilt(sos_high, q_filt, zi=zi_high_q)

    # Reconstruct audio from the filtered I component
    filtered_samples = i_filt.astype(np.float32)
    # filtered_samples = iq_data.real.astype(np.float32)
    return filtered_samples

@app.post("/set-filter")
async def set_filter(low_cut_in, high_cut_in):
    """Endpoint to set filter parameters."""
    global low_cut, high_cut, zi_low_i
    low_cut = float(low_cut_in)
    high_cut = float(high_cut_in)
    zi_low_i = None  # Reset filter states
    return {"status": "filters updated", "low_cut": low_cut, "high_cut": high_cut}

@app.get("/filters")
async def get_filter():
    """Endpoint to get current filter parameters."""
    global low_cut, high_cut
    return {"low_cut": low_cut, "high_cut": high_cut}

@app.post("/reset-filter")
async def reset_filter():
    """Endpoint to set filter parameters."""
    global low_cut, high_cut, zi_low_i
    low_cut = float(20)
    high_cut = float(22000)
    zi_low_i = None  # Reset filter states
    return {"status": "filters reseted"}

@app.post("/set-mode")
async def set_mode(mode_in: str):
    """Endpoint to set the mode."""
    global mode
    mode = mode_in
    await data_generator.emit('set_mode', mode)
    return {"status": "mode changed"}

@app.get("/mode")
async def get_mode():
    """Endpoint to get current mode."""
    global mode
    return {"mode": mode}

@data_generator.on('connect')
async def connect_to_generator():
    print(f"{utc_now_iso()} Connected to IQ data generator server")
    global mode
    await data_generator.emit('set_mode', mode)

@sio_server.event
async def connect(sid, environ):
    print(f"{utc_now_iso()} Client connected: {sid}")

@sio_server.event
def disconnect(sid, reason):
    if reason == sio_server.reason.CLIENT_DISCONNECT:
        print(f"{utc_now_iso()} the client disconnected")
    elif reason == sio_server.reason.SERVER_DISCONNECT:
        print(f"{utc_now_iso()} the server disconnected the client")
    else:
        print(f"{utc_now_iso()} disconnect reason: {reason}")

async def main(generator_url: str = 'http://localhost:8000'):
    print(f"{utc_now_iso()} Connecting to IQ data generator server at {generator_url}")
    config = uvicorn.Config(socket_app, host="0.0.0.0", port=8080, log_level="info")
    server = uvicorn.Server(config)

    connection_to_generator = asyncio.create_task(data_generator.connect(generator_url, retry=True))

    await asyncio.gather(server.serve(), print_status_repeatedly(), connection_to_generator)

if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description='IQ filter analyzer')
    parser.add_argument('--generator-url', type=str, default=None, help='URL of IQ generator server (overrides IQ_GENERATOR_URL env var)')
    args = parser.parse_args()

    # Resolve generator URL: CLI > ENV > default
    generator_url = args.generator_url if args.generator_url is not None else os.getenv('IQ_GENERATOR_URL', 'http://localhost:8000')
    print(f"{utc_now_iso()} Starting iq_filter_analyzer with generator_url={generator_url}")

    asyncio.run(main(generator_url))
