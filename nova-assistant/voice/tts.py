"""
Nova Assistant — Text-to-Speech Module
Uses Piper TTS for high-quality offline speech synthesis.
"""

import io
import json
import wave
import logging
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger("nova.tts")

# Directory where voice models are stored
VOICES_DIR = Path(__file__).parent.parent / "voices"

# HuggingFace repo for Piper voice models
PIPER_VOICES_REPO = "rhasspy/piper-voices"

# Mapping of voice names to HuggingFace file paths
VOICE_FILES = {
    "en_US-lessac-medium": {
        "onnx": "en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "json": "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    },
    "en_US-lessac-low": {
        "onnx": "en/en_US/lessac/low/en_US-lessac-low.onnx",
        "json": "en/en_US/lessac/low/en_US-lessac-low.onnx.json",
    },
    "en_US-lessac-high": {
        "onnx": "en/en_US/lessac/high/en_US-lessac-high.onnx",
        "json": "en/en_US/lessac/high/en_US-lessac-high.onnx.json",
    },
    "en_US-amy-medium": {
        "onnx": "en/en_US/amy/medium/en_US-amy-medium.onnx",
        "json": "en/en_US/amy/medium/en_US-amy-medium.onnx.json",
    },
    "en_US-ryan-medium": {
        "onnx": "en/en_US/ryan/medium/en_US-ryan-medium.onnx",
        "json": "en/en_US/ryan/medium/en_US-ryan-medium.onnx.json",
    },
}


class NovaTTS:
    """
    Offline text-to-speech engine using Piper TTS.

    Handles voice model download, synthesis, and audio playback.
    """

    def __init__(self, config: dict):
        self._config = config.get("tts", {})
        self._voice_name = self._config.get("voice", "en_US-lessac-medium")
        self._rate = self._config.get("rate", 1.0)
        self._voice = None
        self._sample_rate = 22050
        self._is_speaking = False
        self._stop_event = threading.Event()
        self._playback_thread: Optional[threading.Thread] = None

        # Ensure voices directory exists
        VOICES_DIR.mkdir(parents=True, exist_ok=True)

        self._load_voice()

    def _download_voice(self) -> tuple[str, str]:
        """
        Download voice model from HuggingFace if not cached.

        Returns:
            Tuple of (onnx_path, json_path).
        """
        from huggingface_hub import hf_hub_download

        voice_info = VOICE_FILES.get(self._voice_name)
        if not voice_info:
            raise ValueError(
                f"Unknown voice: {self._voice_name}. "
                f"Available: {list(VOICE_FILES.keys())}"
            )

        logger.info(f"Downloading voice model: {self._voice_name}...")

        onnx_path = hf_hub_download(
            repo_id=PIPER_VOICES_REPO,
            filename=voice_info["onnx"],
            cache_dir=str(VOICES_DIR),
        )
        json_path = hf_hub_download(
            repo_id=PIPER_VOICES_REPO,
            filename=voice_info["json"],
            cache_dir=str(VOICES_DIR),
        )

        logger.info(f"Voice model downloaded: {self._voice_name}")
        return onnx_path, json_path

    def _find_cached_voice(self) -> Optional[tuple[str, str]]:
        """
        Find a previously downloaded voice model in the cache.

        Returns:
            Tuple of (onnx_path, json_path) or None.
        """
        # Search for the ONNX file in the voices directory
        voice_filename = f"{self._voice_name}.onnx"
        for onnx_path in VOICES_DIR.rglob(voice_filename):
            json_path = Path(str(onnx_path) + ".json")
            if json_path.exists():
                return str(onnx_path), str(json_path)
        return None

    def _load_voice(self) -> None:
        """Load the Piper voice model, downloading if necessary."""
        try:
            from piper import PiperVoice

            logger.info(f"Loading Piper voice: {self._voice_name}")

            # Try to find cached voice first
            cached = self._find_cached_voice()
            if cached:
                onnx_path, json_path = cached
                logger.info(f"Using cached voice: {onnx_path}")
            else:
                # Download from HuggingFace
                onnx_path, json_path = self._download_voice()

            # Load the voice model
            self._voice = PiperVoice.load(
                onnx_path,
                config_path=json_path,
                use_cuda=False,  # Piper TTS on CPU is fast enough
            )

            self._sample_rate = self._voice.config.sample_rate

            logger.info(
                f"Piper voice loaded: {self._voice_name} "
                f"(sample_rate={self._sample_rate})"
            )

        except ImportError as e:
            logger.error(f"Piper TTS not installed: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to load Piper voice: {e}")
            raise

    def speak(self, text: str, block: bool = True) -> None:
        """
        Synthesize and play speech.

        Args:
            text: Text to speak.
            block: If True, wait until speech finishes. If False, return immediately.
        """
        if not self._voice:
            logger.error("No voice loaded — cannot speak")
            return

        if not text or not text.strip():
            return

        # Stop any current playback
        self.stop()
        self._stop_event.clear()

        if block:
            self._synthesize_and_play(text)
        else:
            self._playback_thread = threading.Thread(
                target=self._synthesize_and_play,
                args=(text,),
                daemon=True,
            )
            self._playback_thread.start()

    def _synthesize_and_play(self, text: str) -> None:
        """Internal: synthesize text to audio and play it."""
        try:
            self._is_speaking = True
            logger.debug(f"Synthesizing: '{text[:80]}...'")

            # Synthesize to WAV in memory
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wav_file:
                self._voice.synthesize_wav(text, wav_file)

            # Read WAV data as numpy array
            wav_buffer.seek(0)
            with wave.open(wav_buffer, "rb") as wav_file:
                n_frames = wav_file.getnframes()
                raw_data = wav_file.readframes(n_frames)
                sample_width = wav_file.getsampwidth()
                frame_rate = wav_file.getframerate()

            # Convert to numpy float32 array
            if sample_width == 2:
                audio = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
            elif sample_width == 4:
                audio = np.frombuffer(raw_data, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                audio = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0

            if self._stop_event.is_set():
                return

            # Play audio
            logger.debug(f"Playing audio: {len(audio)} samples at {frame_rate} Hz")
            sd.play(audio, samplerate=frame_rate, blocking=False)

            # Wait for playback to finish (or stop signal)
            duration = len(audio) / frame_rate
            elapsed = 0.0
            check_interval = 0.05  # Check stop every 50ms
            while elapsed < duration and not self._stop_event.is_set():
                sd.sleep(int(check_interval * 1000))
                elapsed += check_interval

            if self._stop_event.is_set():
                sd.stop()
                logger.debug("Playback stopped by user")

        except Exception as e:
            logger.error(f"TTS playback error: {e}")
        finally:
            self._is_speaking = False

    def play_chime(self, frequency: int = 880, duration: float = 0.15) -> None:
        """
        Play a short notification chime.

        Args:
            frequency: Tone frequency in Hz.
            duration: Duration in seconds.
        """
        try:
            sample_rate = 44100
            t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

            # Generate a pleasant two-tone chime with fade
            tone1 = 0.3 * np.sin(2 * np.pi * frequency * t)
            tone2 = 0.2 * np.sin(2 * np.pi * (frequency * 1.5) * t)
            chime = (tone1 + tone2).astype(np.float32)

            # Apply fade in/out envelope
            fade_len = int(sample_rate * 0.02)  # 20ms fade
            if fade_len > 0 and len(chime) > 2 * fade_len:
                chime[:fade_len] *= np.linspace(0, 1, fade_len).astype(np.float32)
                chime[-fade_len:] *= np.linspace(1, 0, fade_len).astype(np.float32)

            sd.play(chime, samplerate=sample_rate)
            sd.wait()
        except Exception as e:
            logger.warning(f"Chime playback failed: {e}")

    def stop(self) -> None:
        """Stop current speech playback."""
        self._stop_event.set()
        sd.stop()
        if self._playback_thread and self._playback_thread.is_alive():
            self._playback_thread.join(timeout=1.0)
        self._is_speaking = False

    @property
    def is_speaking(self) -> bool:
        """Whether TTS is currently playing audio."""
        return self._is_speaking

    def shutdown(self) -> None:
        """Clean up resources."""
        self.stop()
        self._voice = None
        logger.info("TTS engine shut down")


if __name__ == "__main__":
    # Quick standalone test
    import yaml

    logging.basicConfig(level=logging.DEBUG)
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    tts = NovaTTS(config)
    print("Testing TTS...")
    tts.play_chime()
    tts.speak("Hello! I am Nova, your local AI assistant. How can I help you today?")
    print("TTS test complete.")
    tts.shutdown()
