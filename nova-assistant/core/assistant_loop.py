"""
Nova Assistant — Main Loop
Orchestrates wake phrase detection, command capture, and response.
"""

import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nova.loop")


class AssistantLoop:
    """
    Main runtime loop for Nova assistant.

    State machine:
        IDLE → (wake phrase) → LISTENING → (command) → PROCESSING → SPEAKING → IDLE
    """

    # States
    STATE_IDLE = "IDLE"             # Waiting for wake phrase
    STATE_LISTENING = "LISTENING"   # Capturing command
    STATE_PROCESSING = "PROCESSING" # Processing command (Phase 2+)
    STATE_SPEAKING = "SPEAKING"     # Playing TTS response

    def __init__(self, config: dict):
        self._config = config
        self._state = self.STATE_IDLE
        self._running = False
        self._assistant_name = config.get("assistant", {}).get("name", "Nova")
        self._command_cooldown = config.get("assistant", {}).get("command_cooldown", 2)

        # Initialize voice engines
        self._tts = None
        self._stt = None
        self._init_engines()

        # Register graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _init_engines(self) -> None:
        """Initialize TTS, STT engines, Intent Router, and Phase 3 tools."""
        logger.info("Initializing engines...")

        # Safety Policy (needed by tools)
        try:
            from safety.policy import SafetyPolicy
            self._policy = SafetyPolicy(self._config)
            logger.info("Safety policy loaded")
        except Exception as e:
            logger.error(f"Failed to initialize Safety Policy: {e}")
            raise

        # Intent Router
        try:
            from core.intent_router import IntentRouter
            self._router = IntentRouter(self._config)
            logger.info("Intent router ready")
        except Exception as e:
            logger.error(f"Failed to initialize Intent Router: {e}")
            raise

        # TTS first (faster to load, gives immediate feedback)
        try:
            from voice.tts import NovaTTS
            self._tts = NovaTTS(self._config)
            logger.info("TTS engine ready")
        except Exception as e:
            logger.error(f"Failed to initialize TTS: {e}")
            raise

        # STT (loads Whisper model — takes a moment)
        try:
            from voice.stt import NovaSTT
            self._stt = NovaSTT(self._config)
            logger.info("STT engine ready")
        except Exception as e:
            logger.error(f"Failed to initialize STT: {e}")
            raise
            
        # Preload LLM model synchronously after GPU is free
        self._router.preload_model()

        # Phase 3 Tools
        try:
            from tools.app_tools import AppLauncher
            self._app_launcher = AppLauncher(self._config, self._policy)
            logger.info("App launcher ready")
        except Exception as e:
            logger.error(f"Failed to initialize App Launcher: {e}")
            raise

        try:
            from tools.browser_tools import BrowserLauncher
            self._browser = BrowserLauncher(self._config, self._policy)
            logger.info("Browser launcher ready")
        except Exception as e:
            logger.error(f"Failed to initialize Browser Launcher: {e}")
            raise

        try:
            from tools.file_tools import FileTools
            self._file_tools = FileTools(self._config, self._policy)
            logger.info("File tools ready")
        except Exception as e:
            logger.error(f"Failed to initialize File Tools: {e}")
            raise

        # Phase 4 Tools
        try:
            from system.virtual_desktop import VirtualDesktopManager
            self._desktop_manager = VirtualDesktopManager()
        except Exception as e:
            logger.error(f"Failed to initialize Virtual Desktop Manager: {e}")
            raise
            
        try:
            from system.hotkey_listener import HotkeyListener
            self._hotkeys = HotkeyListener(self._config)
            self._hotkeys.register("work_mode", self._hotkey_work_mode)
            self._hotkeys.register("toggle_listen", self._hotkey_toggle_listen)
            self._hotkeys.register("stop_speaking", self._hotkey_stop_speaking)
        except Exception as e:
            logger.error(f"Failed to initialize Hotkey Listener: {e}")
            raise

    def _hotkey_work_mode(self):
        logger.info("Hotkey triggered: Work Mode")
        self._current_command = "start work mode"
        self._state = self.STATE_PROCESSING
        if self._stt:
            self._stt.stop()
        if self._tts:
            self._tts.stop()

    def _hotkey_toggle_listen(self):
        logger.info("Hotkey triggered: Toggle Listen")
        if self._state == self.STATE_IDLE:
            self._state = self.STATE_LISTENING
            if self._tts:
                self._tts.play_chime()
            if self._stt:
                self._stt.stop()
        elif self._state == self.STATE_LISTENING:
            self._state = self.STATE_IDLE
            if self._stt:
                self._stt.stop()

    def _hotkey_stop_speaking(self):
        logger.info("Hotkey triggered: Stop Speaking")
        if self._tts:
            self._tts.stop()

    def run(self) -> None:
        """
        Start the main assistant loop.

        Blocks until shutdown is called.
        """
        self._running = True
        logger.info(f"{self._assistant_name} is starting up...")

        # Start background listeners
        if hasattr(self, "_hotkeys"):
            self._hotkeys.start()

        # Startup greeting
        self._tts.play_chime()
        self._tts.speak(
            f"Hello! {self._assistant_name} is ready. "
            f"Say 'wake up {self._assistant_name}' to get my attention."
        )

        print(f"\n  {self._assistant_name} is now listening.")
        print(f"  Say 'wake up {self._assistant_name.lower()}' to activate.")
        print(f"  Press Ctrl+C to quit.\n")

        try:
            while self._running:
                if self._state == self.STATE_IDLE:
                    self._handle_idle()
                elif self._state == self.STATE_LISTENING:
                    self._handle_listening()
                elif self._state == self.STATE_PROCESSING:
                    self._handle_processing()
                elif self._state == self.STATE_SPEAKING:
                    self._handle_speaking()

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            self.shutdown()

    def _handle_idle(self) -> None:
        """IDLE state: listen for wake phrase."""
        logger.debug("Entering IDLE state — listening for wake phrase")

        detected = self._stt.listen_for_wake_phrase()

        if detected and self._running:
            logger.info("Wake phrase detected — transitioning to LISTENING")
            self._tts.play_chime()
            self._state = self.STATE_LISTENING

    def _handle_listening(self) -> None:
        """LISTENING state: capture a voice command."""
        logger.debug("Entering LISTENING state — capturing command")

        # Capture command (no chime on subsequent loops to make it feel natural)
        command_text = self._stt.listen_for_command()

        if command_text:
            current_time = time.time()
            
            # Command debouncing
            last_time = getattr(self, '_last_command_time', 0)
            last_text = getattr(self, '_last_command_text', "")
            
            # Ignore exact same command if it happens within 5 seconds (prevent bounce)
            if command_text == last_text and (current_time - last_time) < 5.0:
                logger.info(f"Duplicate command ignored (debounced): '{command_text}'")
                self._state = self.STATE_IDLE
                return
                
            # Enforce general cooldown between commands
            if (current_time - last_time) < self._command_cooldown:
                logger.info("Command ignored (general cooldown active)")
                self._state = self.STATE_IDLE
                return

            self._last_command_time = current_time
            self._last_command_text = command_text

            logger.info(f"Command received: '{command_text}'")
            self._current_command = command_text
            self._state = self.STATE_PROCESSING
        else:
            logger.info("No command detected — returning to IDLE")
            self._state = self.STATE_IDLE

    def _handle_processing(self) -> None:
        """
        PROCESSING state: parse and execute the command.
        
        Uses IntentRouter to parse, then dispatches to the appropriate tool.
        """
        command = getattr(self, "_current_command", "")
        logger.info(f"Processing command: '{command}'")

        # Parse the intent
        intent = self._router.parse_intent(command)
        logger.info(f"Parsed intent: {intent}")
        
        # Safety gate
        safe, reason = self._policy.check_intent_safety(intent)
        if not safe:
            logger.warning(f"Intent blocked by safety policy: {reason}")
            self._current_response = f"I can't do that. {reason}"
            self._next_state = self.STATE_LISTENING
            self._state = self.STATE_SPEAKING
            return

        intent_type = intent.get("intent", "unknown")
        
        if intent_type == "sleep":
            response = "Going back to sleep. Wake me if you need me!"
            self._next_state = self.STATE_IDLE

        elif intent_type == "chat":
            response = intent.get("message", "Hello!")
            self._next_state = self.STATE_LISTENING

        elif intent_type == "open_app":
            app = intent.get("app", "")
            success, response = self._app_launcher.launch(app)
            self._next_state = self.STATE_LISTENING

        elif intent_type == "chrome_search":
            query = intent.get("query", "")
            success, response = self._browser.search(query)
            self._next_state = self.STATE_LISTENING

        elif intent_type == "search_file":
            query = intent.get("query", "")
            success, response, _ = self._file_tools.search(query)
            self._next_state = self.STATE_LISTENING

        elif intent_type == "open_file":
            filename = intent.get("filename", "")
            success, response = self._file_tools.open_file(filename)
            self._next_state = self.STATE_LISTENING

        elif intent_type == "start_work_mode":
            workspace = intent.get("workspace", "default")
            response = self._execute_workspace(workspace)
            self._next_state = self.STATE_LISTENING

        else:
            response = intent.get("message", "I didn't understand that command.")
            self._next_state = self.STATE_LISTENING

        self._current_response = response
        self._state = self.STATE_SPEAKING

    def _execute_workspace(self, workspace_key: str) -> str:
        """
        Execute a workspace routine from workspaces.json.

        Opens all configured apps and Chrome profiles for the workspace.
        """
        import json

        ws_path = Path(__file__).parent.parent / "data" / "workspaces.json"
        try:
            with open(ws_path, "r") as f:
                ws_data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load workspaces config: {e}")
            return f"Failed to load workspaces config: {e}"

        workspaces = ws_data.get("workspaces", {})
        workspace = workspaces.get(workspace_key)

        if not workspace:
            available = ", ".join(workspaces.keys())
            return f"Workspace '{workspace_key}' not found. Available: {available}"

        ws_name = workspace.get("name", workspace_key)
        logger.info(f"Starting workspace routine: {ws_name}")
        results = []
        import time

        # 1. Virtual Desktop
        if workspace.get("create_virtual_desktop", False):
            if self._desktop_manager.create_and_switch():
                results.append("Created new virtual desktop.")
            else:
                results.append("Could not create virtual desktop.")

        # 2. Launch Apps and Chrome Profiles
        for step in workspace.get("apps", []):
            step_type = step.get("type")

            if step_type == "app":
                app_name = step.get("app", "")
                success, msg = self._app_launcher.launch(app_name)
                results.append(msg)
                time.sleep(1)  # Give the app a moment to start

            elif step_type == "chrome_profile":
                profile = step.get("profile", "")
                urls = step.get("urls", [])
                success, msg = self._browser.launch_profile(profile, urls or None)
                results.append(msg)
                time.sleep(1)

        # 3. Play Music
        music = workspace.get("music", {})
        if music.get("enabled") and music.get("url"):
            success, msg = self._browser.launch_profile(
                music.get("profile", "default"), 
                [music.get("url")]
            )
            if success:
                results.append("Started music.")
            else:
                results.append("Failed to start music.")

        summary = f"Started {ws_name}. " + " ".join(results)
        logger.info(f"Workspace routine complete: {summary}")
        return summary

    def _handle_speaking(self) -> None:
        """SPEAKING state: play TTS response."""
        response = getattr(self, "_current_response", "")
        logger.debug(f"Speaking response: '{response[:80]}...'")

        if response:
            self._tts.speak(response, block=True)

        next_state = getattr(self, "_next_state", self.STATE_LISTENING)
        self._state = next_state
        logger.debug(f"Response complete — transitioning to {next_state}")

    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals gracefully."""
        logger.info(f"Signal {signum} received — shutting down")
        self._running = False
        if self._stt:
            self._stt.stop()
        if self._tts:
            self._tts.stop()

    def shutdown(self) -> None:
        """Clean up all resources."""
        self._running = False
        logger.info(f"{self._assistant_name} shutting down...")

        # Say goodbye
        if self._tts:
            try:
                self._tts.speak("Shutting down. Goodbye!", block=True)
            except Exception:
                pass

        # Clean up engines
        if hasattr(self, "_hotkeys") and self._hotkeys:
            self._hotkeys.stop()
        if self._stt:
            self._stt.shutdown()
        if self._tts:
            self._tts.shutdown()

        logger.info(f"{self._assistant_name} shut down complete.")
