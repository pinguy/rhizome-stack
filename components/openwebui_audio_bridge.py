#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from threading import Lock, Timer

import requests
from flask import Flask, Response, jsonify, request

app = Flask(__name__)

CHATTERBOX_BASE = os.environ.get('CHATTERBOX_BASE', 'http://127.0.0.1:8020')
TTS_SST_DIR = Path(os.environ.get("VOICE_COMPONENT_DIR", str(Path.home() / ".local/share/rhizome-stack/components")))
WHISPER_PYTHON = os.environ.get(
    'WHISPER_PYTHON',
    str(Path.home() / ".local/share/rhizome-stack/venvs/voice/bin/python"),
)
WHISPER_MODEL = os.environ.get(
    'WHISPER_MODEL',
    str(Path.home() / ".local/share/rhizome-stack/models/faster-whisper-large-v3-turbo"),
)
TRANSCRIBE_SH = os.environ.get('TRANSCRIBE_SH', str(TTS_SST_DIR / 'transcribe.sh'))
TRANSCRIPT_TXT = os.environ.get('TRANSCRIPT_TXT', str(TTS_SST_DIR / 'transcript.txt'))
BRIDGE_API_KEY = os.environ.get('BRIDGE_API_KEY', 'local-dev-key')
CHATTERBOX_SERVICE = os.environ.get('CHATTERBOX_SERVICE', 'chatterbox-nano.service')
# Optional GPU twin of the Chatterbox backend. It is a *separate* service on its
# own port so the CPU instance Open WebUI uses (CHATTERBOX_BASE) is never
# touched. A request only reaches it when the caller explicitly asks for the GPU
# device (JSON body "device" or X-Chatterbox-Device header). Open WebUI sends no
# such hint, so its path stays on CPU 8020 unchanged.
CHATTERBOX_GPU_BASE = os.environ.get('CHATTERBOX_GPU_BASE', 'http://127.0.0.1:8021')
CHATTERBOX_GPU_SERVICE = os.environ.get('CHATTERBOX_GPU_SERVICE', 'chatterbox-nano-gpu.service')
STARTUP_WAIT_SECONDS = float(os.environ.get('CHATTERBOX_STARTUP_WAIT_SECONDS', '45'))
HEALTH_POLL_INTERVAL = float(os.environ.get('CHATTERBOX_HEALTH_POLL_INTERVAL', '0.4'))
WHISPER_MODEL_IDLE_SECONDS = float(os.environ.get('WHISPER_MODEL_IDLE_SECONDS', '300'))
# Chatterbox stays warm between utterances and unloads itself after its own
# idle window (CHATTERBOX_IDLE_SECONDS in chatterbox-nano.service). The bridge
# only starts it; it never tears it down, because Voice Lab shares the service.
# Chatterbox accepts up to 4,000 characters at the HTTP layer, but Nano's
# acoustic generation becomes unreliable on prompts anywhere near that size.
# Keep synthesis segments short, then return one joined WAV to the browser.
CHATTERBOX_CHUNK_CHARS = int(os.environ.get('CHATTERBOX_CHUNK_CHARS', '500'))

_chatterbox_start_lock = Lock()
_tts_epoch_lock = Lock()
_tts_cancel_epoch = 0
_whisper_worker_lock = Lock()
_whisper_decode_lock = Lock()
_whisper_worker: subprocess.Popen[str] | None = None
_whisper_unload_timer: Timer | None = None


def split_tts_text(text: str, limit: int = CHATTERBOX_CHUNK_CHARS) -> list[str]:
    """Split long text internally while keeping one browser playback job."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[: limit + 1]
        boundaries = [m.end() for m in re.finditer(r'(?<=[.!?])\s+|\n+|\s+', window)]
        cut = max((pos for pos in boundaries if pos <= limit), default=limit)
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    return [chunk for chunk in chunks if chunk]


def normalize_tts_chunk(text: str) -> str:
    """Remove quote wrappers that can destabilise short Nano utterances."""
    text = text.strip()
    text = re.sub(r'^["“”]+\s*', '', text)
    text = re.sub(r'\s*["“”]+$', '', text)
    return text.strip()


def join_wav_parts(parts: list[bytes]) -> bytes:
    """Join compatible PCM WAV responses into one browser-playable WAV."""
    output = io.BytesIO()
    expected = None
    frames: list[bytes] = []
    for part in parts:
        with wave.open(io.BytesIO(part), 'rb') as source:
            params = (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype())
            if expected is None:
                expected = params
            elif params != expected:
                raise ValueError(f'incompatible WAV part: {params} != {expected}')
            frames.append(source.readframes(source.getnframes()))
    if expected is None:
        raise ValueError('no WAV parts to join')
    channels, sample_width, frame_rate, compression = expected
    with wave.open(output, 'wb') as target:
        target.setnchannels(channels)
        target.setsampwidth(sample_width)
        target.setframerate(frame_rate)
        target.setcomptype(compression, 'not compressed')
        for frame_block in frames:
            target.writeframesraw(frame_block)
    return output.getvalue()


def check_auth() -> tuple[bool, Response | None]:
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return False, jsonify({'error': 'missing bearer token'}), 401
    token = auth.split(' ', 1)[1].strip()
    if token != BRIDGE_API_KEY:
        return False, jsonify({'error': 'invalid api key'}), 401
    return True, None


def resolve_backend(device: object) -> tuple[str, str]:
    """Map a requested device to (base_url, systemd_service).

    Anything other than an explicit GPU request routes to the CPU backend, so
    the default (and every Open WebUI request, which sends no device) is the
    unchanged CPU path.
    """
    if str(device or '').strip().lower() in ('gpu', 'cuda'):
        return CHATTERBOX_GPU_BASE, CHATTERBOX_GPU_SERVICE
    return CHATTERBOX_BASE, CHATTERBOX_SERVICE


def wait_for_chatterbox(base: str = CHATTERBOX_BASE, timeout_s: float = STARTUP_WAIT_SECONDS) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(f'{base}/health', timeout=1.5)
            if r.ok:
                return True
        except Exception:
            pass
        time.sleep(HEALTH_POLL_INTERVAL)
    return False


def cancel_active_tts() -> int:
    """Bump the epoch so any in-flight chunk loop stops after its current chunk."""
    global _tts_cancel_epoch
    with _tts_epoch_lock:
        _tts_cancel_epoch += 1
        return _tts_cancel_epoch


def tts_cancelled(epoch: int) -> bool:
    with _tts_epoch_lock:
        return _tts_cancel_epoch != epoch


def ensure_chatterbox_running(base: str = CHATTERBOX_BASE, service: str = CHATTERBOX_SERVICE) -> bool:
    with _chatterbox_start_lock:
        if wait_for_chatterbox(base, timeout_s=1.0):
            return True

        subprocess.run(
            ['systemctl', '--user', 'start', service],
            check=False,
            capture_output=True,
            text=True,
        )

        return wait_for_chatterbox(base, timeout_s=STARTUP_WAIT_SECONDS)


def get_whisper_worker() -> subprocess.Popen[str]:
    global _whisper_worker
    if _whisper_worker is not None and _whisper_worker.poll() is None:
        return _whisper_worker
    env = os.environ.copy()
    env['WHISPER_MODEL'] = WHISPER_MODEL
    env.setdefault('WHISPER_COMPUTE_TYPE', 'int8')
    env.setdefault('WHISPER_CPU_THREADS', '16')
    _whisper_worker = subprocess.Popen(
        [WHISPER_PYTHON, str(TTS_SST_DIR / 'whisper_worker.py')],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )
    ready = _whisper_worker.stdout.readline() if _whisper_worker.stdout else ''
    if not ready or not json.loads(ready).get('ready'):
        error = _whisper_worker.stderr.read()[-1200:] if _whisper_worker.stderr else ''
        raise RuntimeError(f'Whisper worker failed to become ready: {error}')
    return _whisper_worker


def unload_whisper_model_if_idle() -> None:
    global _whisper_worker, _whisper_unload_timer
    with _whisper_worker_lock:
        worker, _whisper_worker = _whisper_worker, None
        _whisper_unload_timer = None
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)


def schedule_whisper_unload() -> None:
    global _whisper_unload_timer
    if WHISPER_MODEL_IDLE_SECONDS <= 0:
        return
    with _whisper_worker_lock:
        if _whisper_unload_timer is not None:
            _whisper_unload_timer.cancel()
        _whisper_unload_timer = Timer(WHISPER_MODEL_IDLE_SECONDS, unload_whisper_model_if_idle)
        _whisper_unload_timer.daemon = True
        _whisper_unload_timer.start()


def transcribe_whisper_audio(audio_path: Path) -> str:
    worker = get_whisper_worker()
    if worker.stdin is None or worker.stdout is None:
        raise RuntimeError('Whisper worker pipes unavailable')
    worker.stdin.write(json.dumps({'audio_path': str(audio_path)}) + '\n')
    worker.stdin.flush()
    response = json.loads(worker.stdout.readline())
    if 'error' in response:
        raise RuntimeError(response['error'])
    return response.get('text', '').strip()


@app.get('/health')
def health():
    chatterbox_ok = False
    chatterbox_idle = None
    chatterbox_idle_limit = None
    try:
        r = requests.get(f'{CHATTERBOX_BASE}/health', timeout=3)
        chatterbox_ok = r.ok
        if r.ok:
            detail = r.json()
            chatterbox_idle = detail.get('idle_seconds')
            chatterbox_idle_limit = detail.get('idle_shutdown_seconds')
    except Exception:
        chatterbox_ok = False

    return jsonify(
        {
            'ok': True,
            'tts_backend': 'chatterbox-nano',
            'chatterbox_ok': chatterbox_ok,
            'chatterbox_loaded': chatterbox_ok,
            'chatterbox_idle_seconds': chatterbox_idle,
            'chatterbox_idle_unload_seconds': chatterbox_idle_limit,
            'default_stt_backend': 'whisper',
            'whisper_model': WHISPER_MODEL,
            'whisper_model_loaded': _whisper_worker is not None and _whisper_worker.poll() is None,
            'whisper_model_idle_unload_seconds': WHISPER_MODEL_IDLE_SECONDS,
        }
    )


@app.get('/models')
@app.get('/v1/models')
def list_models():
    # OpenAI-compatible model list so Open WebUI can present selectable STT backends.
    now = int(time.time())
    return jsonify(
        {
            'object': 'list',
            'data': [
                {'id': 'whisper', 'object': 'model', 'created': now, 'owned_by': 'local'},
            ],
        }
    )


@app.post('/audio/speech')
@app.post('/v1/audio/speech')
def tts_speech():
    ok, err, *status = check_auth()
    if not ok:
        return err, status[0]

    body = request.get_json(silent=True) or {}
    text = body.get('input') or body.get('text') or ''

    if not text.strip():
        return jsonify({'error': "'input' text is required"}), 400

    # Device hint: JSON "device" or X-Chatterbox-Device header. Absent => CPU,
    # so Open WebUI (which never sends it) is unaffected.
    device = body.get('device') or request.headers.get('X-Chatterbox-Device')
    base, service = resolve_backend(device)

    if not ensure_chatterbox_running(base, service):
        return jsonify({'error': 'chatterbox not ready after startup wait'}), 502

    with _tts_epoch_lock:
        epoch = _tts_cancel_epoch

    audio_parts: list[bytes] = []
    for raw_chunk in split_tts_text(text):
        chunk = normalize_tts_chunk(raw_chunk)
        if not chunk:
            continue
        if tts_cancelled(epoch):
            # Stop was pressed: abandon the remaining chunks instead of burning
            # CPU on audio nobody will hear. The model stays loaded.
            return jsonify({'error': 'cancelled'}), 409
        payload = {'input': chunk, 'model': 'chatterbox-nano', 'voice': 'rhizome'}
        try:
            r = requests.post(f'{base}/v1/audio/speech', json=payload, headers={'Authorization': f'Bearer {BRIDGE_API_KEY}'}, timeout=300)
            r.raise_for_status()
        except Exception:
            # One retry handles a cold-start race, or an idle unload that landed
            # between chunks; restart it rather than only waiting on health.
            if not ensure_chatterbox_running(base, service):
                return jsonify({'error': 'chatterbox request failed and service is still not healthy'}), 502
            try:
                r = requests.post(f'{base}/v1/audio/speech', json=payload, headers={'Authorization': f'Bearer {BRIDGE_API_KEY}'}, timeout=300)
                r.raise_for_status()
            except Exception as exc:
                detail = r.text[:300] if 'r' in locals() else ''
                return jsonify({'error': f'chatterbox request failed: {exc}', 'detail': detail}), 502
        audio_parts.append(r.content)

    try:
        audio = audio_parts[0] if len(audio_parts) == 1 else join_wav_parts(audio_parts)
    except Exception as exc:
        return jsonify({'error': f'failed to join chatterbox audio: {exc}'}), 502
    return Response(audio, mimetype='audio/wav')


@app.post('/audio/stop')
@app.post('/v1/audio/stop')
def tts_stop():
    """Abandon any queued synthesis but keep the model loaded and warm."""
    ok, err, *status = check_auth()
    if not ok:
        return err, status[0]
    epoch = cancel_active_tts()
    return jsonify({'ok': True, 'cancelled': True, 'epoch': epoch, 'chatterbox_stopped': False})


@app.post('/audio/transcriptions')
@app.post('/v1/audio/transcriptions')
def stt_transcribe():
    ok, err, *status = check_auth()
    if not ok:
        return err, status[0]

    f = request.files.get('file')
    if not f:
        return jsonify({'error': "multipart field 'file' is required"}), 400

    if not Path(TRANSCRIBE_SH).exists():
        return jsonify({'error': f'transcribe.sh not found: {TRANSCRIBE_SH}'}), 500

    with tempfile.TemporaryDirectory(prefix='whisper_stt_') as td:
        td = Path(td)
        src = td / (f.filename or 'input_audio')
        src.write_bytes(f.read())

        started = time.monotonic()
        try:
            with _whisper_decode_lock:
                text = transcribe_whisper_audio(src)
                schedule_whisper_unload()
        except Exception as e:
            return jsonify({'error': f'whisper transcription failed: {e}'}), 500

    return jsonify({
        'text': text,
        'backend': 'whisper',
        'duration_seconds': round(time.monotonic() - started, 3),
        'whisper_model_loaded': _whisper_worker is not None and _whisper_worker.poll() is None,
    })


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8010)
