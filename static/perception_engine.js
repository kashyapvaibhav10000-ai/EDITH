/**
 * EDITH Perception Engine
 * Replaces MediaRecorder with AudioWorklet + rolling buffer
 * Drop-in replacement for startListeningLoop()
 */

class PerceptionEngine {
    constructor(options = {}) {
        this.sampleRate = options.sampleRate || 16000;
        this.bufferSeconds = options.bufferSeconds || 3;
        this.silenceThreshold = options.silenceThreshold || 20;
        this.silenceDuration = options.silenceDuration || 800;
        this.maxDuration = options.maxDuration || 15000;
        this.onTranscript = options.onTranscript || (() => {});
        this.onStateChange = options.onStateChange || (() => {});
        
        // Rolling circular buffer
        this.bufferSize = this.sampleRate * this.bufferSeconds;
        this.circularBuffer = new Float32Array(this.bufferSize);
        this.bufferIdx = 0;
        
        this.audioCtx = null;
        this.workletNode = null;
        this.stream = null;
        this.isRunning = false;
        this.hasSpeech = false;
        this.silenceStart = null;
        this.speechStart = null;
        this.recordedFrames = [];
    }

    async start(stream) {
        this.stream = stream;
        this.isRunning = true;
        
        this.audioCtx = new AudioContext({ sampleRate: this.sampleRate });
        const source = this.audioCtx.createMediaStreamSource(stream);
        
        // Try AudioWorklet first, fall back to ScriptProcessor
        try {
            await this.audioCtx.audioWorklet.addModule(
                '/static/audio_processor.js'
            );
            this.workletNode = new AudioWorkletNode(
                this.audioCtx, 'audio-processor'
            );
            this.workletNode.port.onmessage = (e) => {
                this._processFrame(e.data.samples);
            };
            source.connect(this.workletNode);
            this.workletNode.connect(this.audioCtx.destination);
        } catch(e) {
            console.warn('AudioWorklet unavailable, using ScriptProcessor');
            const processor = this.audioCtx.createScriptProcessor(
                512, 1, 1
            );
            processor.onaudioprocess = (e) => {
                this._processFrame(
                    e.inputBuffer.getChannelData(0)
                );
            };
            source.connect(processor);
            processor.connect(this.audioCtx.destination);
        }
        
        // M2: Auto-calibrate VAD threshold during first 1s of listening environment
        this.onStateChange('calibrating');
        try {
            const calibratedThreshold = await this.calibrate(1000);
            this.onStateChange('ready');
        } catch(e) {
            console.warn('Calibration failed, using default threshold');
            this.onStateChange('ready');
        }
    }

    _processFrame(samples) {
        if (!this.isRunning) return;
        
        // Push to circular buffer
        for (let i = 0; i < samples.length; i++) {
            this.circularBuffer[this.bufferIdx] = samples[i];
            this.bufferIdx = (this.bufferIdx + 1) % this.bufferSize;
        }
        
        // Calculate RMS energy
        let sum = 0;
        for (let i = 0; i < samples.length; i++) {
            sum += samples[i] * samples[i];
        }
        const rms = Math.sqrt(sum / samples.length);
        const level = rms * 255;
        
        if (level >= this.silenceThreshold) {
            // Speech detected
            if (!this.hasSpeech) {
                this.hasSpeech = true;
                this.speechStart = Date.now();
                // Prepend 1.5s from rolling buffer
                this.recordedFrames = [
                    this._getLastSeconds(1.5)
                ];
                this.onStateChange('listening');
            }
            this.silenceStart = null;
            this.recordedFrames.push(new Float32Array(samples));
        } else if (this.hasSpeech) {
            // Silence after speech
            if (!this.silenceStart) {
                this.silenceStart = Date.now();
            }
            this.recordedFrames.push(new Float32Array(samples));
            
            const silenceMs = Date.now() - this.silenceStart;
            const speechMs = Date.now() - this.speechStart;
            
            // Dynamic timeout based on speech length
            const timeout = speechMs < 2000 ? 800 : 1500;
            
            if (silenceMs >= timeout) {
                this._finalizeSegment();
            }
        }
        
        // Max duration safety
        if (this.hasSpeech && 
            Date.now() - this.speechStart > this.maxDuration) {
            this._finalizeSegment();
        }
    }

    _getLastSeconds(seconds) {
        const n = Math.floor(seconds * this.sampleRate);
        const result = new Float32Array(n);
        for (let i = 0; i < n; i++) {
            const idx = (this.bufferIdx - n + i + this.bufferSize) 
                        % this.bufferSize;
            result[i] = this.circularBuffer[idx];
        }
        return result;
    }

    async _finalizeSegment() {
        if (!this.hasSpeech || this.recordedFrames.length === 0) return;
        
        this.hasSpeech = false;
        this.silenceStart = null;
        this.onStateChange('processing');
        
        // Combine all frames
        const totalLength = this.recordedFrames.reduce(
            (sum, f) => sum + f.length, 0
        );
        const combined = new Float32Array(totalLength);
        let offset = 0;
        for (const frame of this.recordedFrames) {
            combined.set(frame, offset);
            offset += frame.length;
        }
        this.recordedFrames = [];
        
        // Convert Float32 PCM to WAV blob
        const wav = this._float32ToWav(combined, this.sampleRate);
        this.onTranscript(wav);
        this.onStateChange('transcribing');
    }

    _float32ToWav(samples, sampleRate) {
        const buffer = new ArrayBuffer(44 + samples.length * 2);
        const view = new DataView(buffer);
        const writeStr = (offset, str) => {
            for (let i = 0; i < str.length; i++) {
                view.setUint8(offset + i, str.charCodeAt(i));
            }
        };
        writeStr(0, 'RIFF');
        view.setUint32(4, 36 + samples.length * 2, true);
        writeStr(8, 'WAVE');
        writeStr(12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, 1, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        writeStr(36, 'data');
        view.setUint32(40, samples.length * 2, true);
        const pcm = new Int16Array(buffer, 44);
        for (let i = 0; i < samples.length; i++) {
            pcm[i] = Math.max(-32768, Math.min(32767,
                samples[i] * 32768
            ));
        }
        return new Blob([buffer], { type: 'audio/wav' });
    }

    calibrate(durationMs = 1000) {
        return new Promise((resolve) => {
            const samples = [];
            const startTime = Date.now();
            const origProcess = this._processFrame.bind(this);
            
            this._processFrame = (frame) => {
                // Push to circular buffer still
                for (let i = 0; i < frame.length; i++) {
                    this.circularBuffer[this.bufferIdx] = frame[i];
                    this.bufferIdx = (this.bufferIdx + 1) % this.bufferSize;
                }
                let sum = 0;
                for (let i = 0; i < frame.length; i++) {
                    sum += frame[i] * frame[i];
                }
                samples.push(Math.sqrt(sum / frame.length) * 255);
                
                if (Date.now() - startTime >= durationMs) {
                    this._processFrame = origProcess;
                    const avg = samples.reduce((a,b)=>a+b,0)/samples.length;
                    const newThreshold = Math.min(
                        Math.max(avg * 3, 15), 60
                    );
                    this.silenceThreshold = newThreshold;
                    console.log(
                        `VAD calibrated: ambient=${avg.toFixed(1)},` +
                        ` threshold=${newThreshold.toFixed(1)}`
                    );
                    resolve(newThreshold);
                }
            };
        });
    }

    stop() {
        this.isRunning = false;
        this.hasSpeech = false;
        this.recordedFrames = [];
        if (this.workletNode) {
            this.workletNode.disconnect();
        }
        if (this.audioCtx) {
            this.audioCtx.close();
        }
    }
}

// Export for dashboard use
window.PerceptionEngine = PerceptionEngine;
