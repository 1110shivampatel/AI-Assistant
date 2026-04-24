"""
Nova Assistant — Hotkey Listener
Global hotkey bindings for system-wide Nova triggers.
"""

import logging
import threading
from typing import Callable, Optional

import keyboard

logger = logging.getLogger("nova.hotkey")


class HotkeyListener:
    """
    Registers global hotkeys that work even when Nova's terminal
    is not the active window.

    Runs in a daemon thread so it doesn't block the main loop.
    """

    def __init__(self, config: dict):
        self._config = config
        hotkey_cfg = config.get("hotkeys", {})

        self._work_mode_combo = hotkey_cfg.get("work_mode", "ctrl+shift+w")
        self._toggle_listen_combo = hotkey_cfg.get("toggle_listen", "ctrl+shift+n")
        self._stop_speaking_combo = hotkey_cfg.get("stop_speaking", "escape")

        self._callbacks = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None

        logger.info(
            f"Hotkey listener configured — "
            f"work_mode={self._work_mode_combo}, "
            f"toggle_listen={self._toggle_listen_combo}, "
            f"stop_speaking={self._stop_speaking_combo}"
        )

    def register(self, event_name: str, callback: Callable) -> None:
        """
        Register a callback for a hotkey event.

        Event names: 'work_mode', 'toggle_listen', 'stop_speaking'
        """
        self._callbacks[event_name] = callback
        logger.debug(f"Registered callback for hotkey event: {event_name}")

    def start(self) -> None:
        """Start listening for hotkeys in a background thread."""
        if self._running:
            return

        self._running = True

        # Register the hotkeys
        try:
            if "work_mode" in self._callbacks:
                keyboard.add_hotkey(
                    self._work_mode_combo,
                    self._callbacks["work_mode"],
                    suppress=False,
                )
                logger.info(f"Hotkey registered: {self._work_mode_combo} → work_mode")

            if "toggle_listen" in self._callbacks:
                keyboard.add_hotkey(
                    self._toggle_listen_combo,
                    self._callbacks["toggle_listen"],
                    suppress=False,
                )
                logger.info(f"Hotkey registered: {self._toggle_listen_combo} → toggle_listen")

            if "stop_speaking" in self._callbacks:
                keyboard.add_hotkey(
                    self._stop_speaking_combo,
                    self._callbacks["stop_speaking"],
                    suppress=False,
                )
                logger.info(f"Hotkey registered: {self._stop_speaking_combo} → stop_speaking")

        except Exception as e:
            logger.error(f"Failed to register hotkeys: {e}")
            logger.warning(
                "Hotkeys require administrator privileges on some Windows versions. "
                "Nova will still work via voice commands."
            )

        logger.info("Hotkey listener active")

    def stop(self) -> None:
        """Stop listening for hotkeys and clean up."""
        self._running = False
        try:
            keyboard.unhook_all_hotkeys()
            logger.info("Hotkey listener stopped")
        except Exception as e:
            logger.debug(f"Hotkey cleanup: {e}")
