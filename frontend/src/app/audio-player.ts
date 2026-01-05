export class AudioPlayer {
  private audioCtx: AudioContext;
  private lastScheduledTime: number;
  private sampleRate = 44100; 

  constructor(sampleRate = 44100) {
    this.sampleRate = sampleRate;
    this.audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: this.sampleRate });
    this.lastScheduledTime = this.audioCtx.currentTime;
  }

  /**
   * Resume audio context (must be called after a user gesture in many browsers)
   */
  async play(): Promise<void> {
    if (this.audioCtx.state === 'suspended') {
      try {
        await this.audioCtx.resume();
      } catch (e) {
        // ignore
      }
    }
  }

    /**
   * Resume audio context (must be called after a user gesture in many browsers)
   */
  async pause(): Promise<void> {
    if (this.audioCtx.state !== 'suspended') {
      try {
        await this.audioCtx.suspend();
      } catch (e) {
        // ignore
      }
    }
  }

  /**
   * Close the audio context and stop playback
   */
  async close(): Promise<void> {
    try {
      await this.audioCtx.close();
    } catch (e) {
      // ignore
    }
  }

  /**
   * Enqueue raw chunk coming from server. Accepts ArrayBuffer, typed arrays or base64 string containing WAV or PCM16 data.
   */
  async enqueueChunk(chunk: ArrayBuffer | ArrayBufferView | string): Promise<void> {
    if (this.audioCtx.state === 'suspended') {
      return;
    }
    
    const arr = this.toArrayBuffer(chunk) as ArrayBuffer;

    // detect WAV by 'RIFF' header
    if (this.isWav(arr)) {
      try {
        const audioBuffer = await this.audioCtx.decodeAudioData(arr.slice(0));
        this.scheduleBuffer(audioBuffer);
        return;
      } catch (err) {
        console.error('Failed to decode WAV chunk', err);
        return;
      }
    }

    // if looks like PCM16 (no WAV header), interpret as Int16 LE and create AudioBuffer
    if (arr.byteLength >= 2) {
      const int16 = new Int16Array(arr.byteLength / 2);
      const view = new DataView(arr);
      for (let i = 0; i < int16.length; i++) {
        int16[i] = view.getInt16(i * 2, true);
      }
      const float32 = this.int16ToFloat32(int16);
      const audioBuffer = this.audioCtx.createBuffer(1, float32.length, this.sampleRate);
      audioBuffer.getChannelData(0).set(float32);
      this.scheduleBuffer(audioBuffer);
      return;
    }

    console.warn('Received unknown audio chunk format, ignoring');
  }

  private scheduleBuffer(buffer: AudioBuffer) {
    const ctx = this.audioCtx;
    // small safety offset
    const startAt = Math.max(this.lastScheduledTime, ctx.currentTime + 0.05);
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);
    src.start(startAt);
    this.lastScheduledTime = startAt + buffer.duration;
  }

  private isWav(ab: ArrayBuffer): boolean {
    if (ab.byteLength < 12) return false;
    const dv = new DataView(ab);
    // 'RIFF' and 'WAVE' at offset 8
    const riff = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
    const wave = String.fromCharCode(dv.getUint8(8), dv.getUint8(9), dv.getUint8(10), dv.getUint8(11));
    return riff === 'RIFF' && wave === 'WAVE';
  }

  private toArrayBuffer(chunk: ArrayBuffer | ArrayBufferView | string): ArrayBuffer | SharedArrayBuffer {
    if (typeof chunk === 'string') {
      // assume base64
      const binary = atob(chunk);
      const len = binary.length;
      const u8 = new Uint8Array(len);
      for (let i = 0; i < len; i++) u8[i] = binary.charCodeAt(i);
      return u8.buffer;
    }

    if (chunk instanceof ArrayBuffer) return chunk;
    if (ArrayBuffer.isView(chunk)) {
      // typed array view
      const view = chunk as ArrayBufferView;
      // if view.byteOffset === 0 and full length, we can return view.buffer directly
      if (view.byteOffset === 0 && view.byteLength === view.buffer.byteLength) return view.buffer;
      // otherwise copy
      return view.buffer.slice(view.byteOffset, view.byteOffset + view.byteLength);
    }

    throw new Error('Unsupported chunk type');
  }

  private int16ToFloat32(int16: Int16Array): Float32Array {
    const f32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      f32[i] = Math.max(-1, int16[i] / 32768);
    }
    return f32;
  }
}
