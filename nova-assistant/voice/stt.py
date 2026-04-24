"""
Nova Assistant — Speech-to-Text Module
Uses faster-whisper for GPU-accelerated offline transcription,
with VAD-based speech segmentation for wake phrase and command detection.
"""

import logging
import threading
import time
import queue
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import sounddevice as sd

logger = logging.getLogger("nova.stt")

# Audio constants
SAMPLE_RATE = 16000      # Whisper expects 16kHz
CHANNELS = 1             # Mono
DTYPE = "float32"        # Sounddevice dtype
FRAME_DURATION_MS = 30   # VAD frame size (10, 20, or 30 ms)
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 480 samples


class NovaSTT:
    """
    Offline speech-to-text engine using faster-whisper.

    Provides:
    - Continuous microphone streaming
    - Voice Activity Detection (VAD) for speech segmentation
    - Wake phrase detection
    - Single-command transcription
    """

    def __init__(self, config: dict):
        self._config = config.get("stt", {})
        self._assistant_cfg = config.get("assistant", {})

        # STT config
        self._model_size = self._config.get("model_size", "small")
        self._device = self._config.get("device", "cuda")
        self._compute_type = self._config.get("compute_type", "float16")
        self._language = self._config.get("language", "en")
        self._beam_size = self._config.get("beam_size", 3)
        self._vad_filter = self._config.get("vad_filter", True)

        # Assistant config
        self._wake_phrase = self._assistant_cfg.get("wake_phrase", "wake up nova").lower()
        self._wake_confidence = self._assistant_cfg.get("wake_confidence", 0.6)
        self._command_timeout = self._assistant_cfg.get("command_timeout", 8)

        # State
        self._model = None
        self._vad = None
        self._is_listening = False
        self._stop_event = threading.Event()

        self._load_model()
        self._init_vad()

    def _load_model(self) -> None:
        """Load the faster-whisper model."""
        try:
            from faster_whisper import WhisperModel

            logger.info(
                f"Loading Whisper model: {self._model_size} "
                f"(device={self._device}, compute={self._compute_type})"
            )

            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )

            logger.info("Whisper model loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            # Fallback to CPU if CUDA fails
            if self._device == "cuda":
                logger.warning("Falling back to CPU...")
                self._device = "cpu"
                self._compute_type = "int8"
                try:
                    from faster_whisper import WhisperModel
                    self._model = WhisperModel(
                        self._model_size,
                        device="cpu",
                        compute_type="int8",
                    )
                    logger.info("Whisper model loaded on CPU (fallback)")
                except Exception as e2:
                    logger.error(f"CPU fallback also failed: {e2}")
                    raise

    def _init_vad(self) -> None:
        """Initialize Voice Activity Detection."""
        try:
            import webrtcvad
            self._vad = webrtcvad.Vad()
            self._vad.set_mode(1)  # 1 = less aggressive (more forgiving of quiet mics)
            logger.info("WebRTC VAD initialized (mode=1)")
        except ImportError:
            logger.warning("webrtcvad not available — using energy-based VAD fallback")
            self._vad = None

    def _vad_is_speech(self, audio_frame: np.ndarray) -> bool:
        """
        Check if an audio frame contains speech.

        Args:
            audio_frame: Float32 numpy array of audio samples.

        Returns:
            True if speech detected.
        """
        # Apply a 10x software gain boost to help quiet microphones (like AirPods)
        # clip to [-1.0, 1.0] to prevent overflow distortion
        boosted_frame = np.clip(audio_frame * 10.0, -1.0, 1.0)

        if self._vad is not None:
            # WebRTC VAD expects 16-bit PCM bytes
            pcm_data = (boosted_frame * 32767).astype(np.int16).tobytes()
            try:
                return self._vad.is_speech(pcm_data, SAMPLE_RATE)
            except Exception:
                pass

        # Energy-based fallback
        energy = np.sqrt(np.mean(boosted_frame ** 2))
        return energy > 0.005  # Lower threshold for speech

    def transcribe(self, audio: np.ndarray) -> str:
        """
        Transcribe audio data to text.

        Args:
            audio: Float32 numpy array at 16kHz.

        Returns:
            Transcribed text string.
        """
        if self._model is None:
            logger.error("Whisper model not loaded")
            return ""

        try:
            segments, info = self._model.transcribe(
                audio,
                language=self._language,
                beam_size=self._beam_size,
                vad_filter=self._vad_filter,
                word_timestamps=False,
            )

            text = " ".join(segment.text.strip() for segment in segments)
            logger.debug(f"Transcribed: '{text}' (lang={info.language}, prob={info.language_probability:.2f})")
            return text.strip()

        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return ""

    def listen_for_wake_phrase(self) -> bool:
        """
        Continuously listen for the wake phrase.

        Blocks until the wake phrase is detected or stop is called.

        Returns:
            True if wake phrase detected, False if stopped.
        """
        self._stop_event.clear()
        self._is_listening = True
        logger.info(f"Listening for wake phrase: '{self._wake_phrase}'")

        # Audio buffer for collecting speech segments
        speech_buffer = []
        silence_frames = 0
        is_speaking = False
        max_silence_frames = int(0.8 * 1000 / FRAME_DURATION_MS)  # 800ms of silence
        min_speech_frames = int(0.3 * 1000 / FRAME_DURATION_MS)   # 300ms minimum speech
        speech_frame_count = 0

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=FRAME_SIZE,
            ) as stream:

                while not self._stop_event.is_set():
                    # Read a frame from the microphone
                    audio_frame, overflowed = stream.read(FRAME_SIZE)
                    if overflowed:
                        logger.debug("Audio overflow detected")

                    frame = audio_frame.flatten()

                    # Check for speech
                    if self._vad_is_speech(frame):
                        speech_buffer.append(frame)
                        silence_frames = 0
                        speech_frame_count += 1
                        if not is_speaking:
                            is_speaking = True
                            logger.debug("Speech started")
                    else:
                        if is_speaking:
                            silence_frames += 1
                            speech_buffer.append(frame)  # Include trailing silence

                            # End of speech segment?
                            if silence_frames >= max_silence_frames:
                                # Only transcribe if we had enough speech
                                if speech_frame_count >= min_speech_frames:
                                    audio_data = np.concatenate(speech_buffer)
                                    text = self.transcribe(audio_data)

                                    if text:
                                        logger.info(f"Heard: '{text}'")

                                        # Check for wake phrase
                                        if self._check_wake_phrase(text):
                                            logger.info("Wake phrase detected!")
                                            self._is_listening = False
                                            return True

                                # Reset for next segment
                                speech_buffer.clear()
                                silence_frames = 0
                                speech_frame_count = 0
                                is_speaking = False

        except Exception as e:
            logger.error(f"Wake phrase listener error: {e}")
        finally:
            self._is_listening = False

        return False

    def listen_for_command(self, timeout: Optional[float] = None) -> str:
        """
        Listen for a single voice command.

        Waits for speech, then transcribes it when silence is detected.

        Args:
            timeout: Max seconds to wait for speech. Uses config default if None.

        Returns:
            Transcribed command text, or empty string if timeout/error.
        """
        if timeout is None:
            timeout = self._command_timeout

        self._stop_event.clear()
        self._is_listening = True
        logger.info(f"Listening for command (timeout={timeout}s)...")

        speech_buffer = []
        silence_frames = 0
        is_speaking = False
        max_silence_frames = int(1.2 * 1000 / FRAME_DURATION_MS)  # 1.2s silence = end of command
        min_speech_frames = int(0.2 * 1000 / FRAME_DURATION_MS)   # 200ms minimum speech
        speech_frame_count = 0
        start_time = time.time()
        got_any_speech = False

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=FRAME_SIZE,
            ) as stream:

                while not self._stop_event.is_set():
                    # Check timeout
                    elapsed = time.time() - start_time
                    if elapsed > timeout:
                        if got_any_speech and speech_buffer:
                            # Timeout but we have speech — transcribe what we have
                            break
                        logger.info("Command listen timeout — no speech detected")
                        self._is_listening = False
                        return ""

                    # Read audio frame
                    audio_frame, overflowed = stream.read(FRAME_SIZE)
                    frame = audio_frame.flatten()

                    if self._vad_is_speech(frame):
                        speech_buffer.append(frame)
                        silence_frames = 0
                        speech_frame_count += 1
                        got_any_speech = True
                        if not is_speaking:
                            is_speaking = True
                            logger.debug("Command speech started")
                    else:
                        if is_speaking:
                            silence_frames += 1
                            speech_buffer.append(frame)

                            # End of command?
                            if silence_frames >= max_silence_frames:
                                if speech_frame_count >= min_speech_frames:
                                    # We have enough audio, let's transcribe it
                                    audio_data = np.concatenate(speech_buffer)
                                    text = self.transcribe(audio_data)
                                    
                                    if text:
                                        logger.info(f"Command: '{text}'")
                                        self._is_listening = False
                                        return text
                                    else:
                                        logger.debug("Whisper transcribed empty text (noise). Continuing to listen.")
                                        
                                # Too short or just noise — reset and keep listening
                                speech_buffer.clear()
                                silence_frames = 0
                                speech_frame_count = 0
                                is_speaking = False

            # If we exit the loop without returning, return what we have (if it was a timeout)
            if speech_buffer and speech_frame_count >= min_speech_frames:
                audio_data = np.concatenate(speech_buffer)
                text = self.transcribe(audio_data)
                if text:
                    logger.info(f"Command: '{text}'")
                    self._is_listening = False
                    return text

        except Exception as e:
            logger.error(f"Command listen error: {e}")
        finally:
            self._is_listening = False

        return ""

    def _check_wake_phrase(self, text: str) -> bool:
        """
        Check if transcribed text contains the wake phrase.

        Uses fuzzy matching to handle transcription variations.

        Args:
            text: Transcribed text to check.

        Returns:
            True if wake phrase is detected.
        """
        text_lower = text.lower().strip()
        wake = self._wake_phrase.lower().strip()

        # Exact match
        if wake in text_lower:
            return True

        # Handle common transcription variations
        wake_words = wake.split()
        text_words = text_lower.split()

        # Check if all wake words appear in the text (in order)
        if len(wake_words) <= len(text_words):
            wi = 0
            for tw in text_words:
                if wi < len(wake_words) and self._fuzzy_word_match(tw, wake_words[wi]):
                    wi += 1
            if wi == len(wake_words):
                return True

        # Handle specific variations for "wake up nova"
        nova_variants = {"nova", "noba", "noeva", "noter", "knova", "noah", "nullah"}
        wake_variants = {"wake", "wakeup", "weight", "wait"}
        up_variants = {"up", "app", "of"}

        text_has_nova = any(
            self._fuzzy_word_match(w, nv)
            for w in text_words
            for nv in nova_variants
        )
        text_has_wake = any(
            self._fuzzy_word_match(w, wv)
            for w in text_words
            for wv in wake_variants
        )

        if text_has_nova and text_has_wake:
            return True

        return False

    def _fuzzy_word_match(self, word1: str, word2: str) -> bool:
        """
        Simple fuzzy matching between two words.

        Returns True if words are similar enough.
        """
        w1 = word1.lower().strip(".,!?;:'\"")
        w2 = word2.lower().strip(".,!?;:'\"")

        if w1 == w2:
            return True

        # One is a substring of the other
        if len(w1) > 2 and len(w2) > 2:
            if w1 in w2 or w2 in w1:
                return True

        # Simple edit distance check (allow 1 error for short words, 2 for longer)
        max_dist = 1 if len(w2) <= 4 else 2
        if self._edit_distance(w1, w2) <= max_dist:
            return True

        return False

    @staticmethod
    def _edit_distance(s1: str, s2: str) -> int:
        """Compute Levenshtein edit distance between two strings."""
        if len(s1) < len(s2):
            return NovaSTT._edit_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)

        prev_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (c1 != c2)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row

        return prev_row[-1]

    def stop(self) -> None:
        """Signal the listener to stop."""
        self._stop_event.set()
        logger.debug("STT stop requested")

    @property
    def is_listening(self) -> bool:
        """Whether STT is actively listening."""
        return self._is_listening

    def shutdown(self) -> None:
        """Clean up resources."""
        self.stop()
        self._model = None
        self._vad = None
        logger.info("STT engine shut down")


if __name__ == "__main__":
    # Quick standalone test
    import yaml

    logging.basicConfig(level=logging.DEBUG)
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    stt = NovaSTT(config)

    print("\n  Speak something (5 second recording)...")
    print("  Recording...", end="", flush=True)

    # Record 5 seconds of audio
    audio = sd.rec(
        int(5 * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
    )
    sd.wait()
    print(" done!")

    text = stt.transcribe(audio.flatten())
    print(f"  You said: '{text}'")

    stt.shutdown()
