"""
Nova Assistant — App Launcher Tool
Launches desktop applications from a registered app registry.
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("nova.tools.app")


class AppLauncher:
    """
    Launches desktop applications using the app registry.

    The registry maps friendly names/aliases to executable paths,
    and the SafetyPolicy validates every launch request.
    """

    def __init__(self, config: dict, safety_policy):
        self._config = config
        self._policy = safety_policy

        # Load app registry
        registry_path = Path(__file__).parent.parent / "data" / "app_registry.json"
        with open(registry_path, "r") as f:
            self._registry = json.load(f)

        self._apps = self._registry.get("apps", {})
        logger.info(f"App launcher loaded {len(self._apps)} registered apps")

    def resolve_app(self, name: str) -> Optional[dict]:
        """
        Resolve an app name or alias to its registry entry.

        Args:
            name: The app name or alias spoken by the user.

        Returns:
            The registry entry dict, or None if not found.
        """
        import re
        # Strip punctuation and common filler words that Whisper adds
        name_clean = re.sub(r'[.,!?;:\'"]+', '', name).strip()
        filler_words = {"the", "a", "an", "my", "this", "that", "please", "open", "launch", "start"}
        words = [w for w in name_clean.lower().split() if w not in filler_words]
        name_lower = " ".join(words) if words else name_clean.lower()

        # Direct key match
        if name_lower in self._apps:
            return self._apps[name_lower]

        # Alias match
        for key, info in self._apps.items():
            aliases = [a.lower() for a in info.get("aliases", [])]
            if name_lower in aliases:
                return info

        # Fuzzy substring match (e.g., "the calculator" -> "calculator")
        for key, info in self._apps.items():
            aliases = [a.lower() for a in info.get("aliases", [])]
            if any(name_lower in a or a in name_lower for a in aliases):
                return info

        # Single-word match against any alias word
        for word in name_lower.split():
            for key, info in self._apps.items():
                aliases = [a.lower() for a in info.get("aliases", [])]
                if word in aliases or word == key:
                    return info

        return None

    def launch(self, app_name: str) -> Tuple[bool, str]:
        """
        Launch an application by name.

        Args:
            app_name: The user-spoken name of the app.

        Returns:
            (success: bool, message: str)
        """
        # Safety check
        allowed, reason = self._policy.validate_app_launch(app_name, self._registry)
        if not allowed:
            logger.warning(f"App launch blocked: {reason}")
            return False, reason

        # Resolve
        app_info = self.resolve_app(app_name)
        if not app_info:
            return False, f"I couldn't find an app called '{app_name}' in my registry."

        executable = app_info["executable"]
        friendly_name = app_info.get("name", app_name)

        try:
            # Windows URI-style launchers (ms-settings:, calc.exe, etc.)
            if ":" in executable and not executable.startswith("C:") and not executable.startswith("D:"):
                os.startfile(executable)
            elif Path(executable).suffix == ".exe" and Path(executable).is_absolute():
                subprocess.Popen(
                    [executable],
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                )
            else:
                # System-path executables (notepad.exe, calc.exe, etc.)
                subprocess.Popen(
                    executable,
                    shell=True,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                )

            logger.info(f"Launched: {friendly_name} ({executable})")
            return True, f"Opened {friendly_name}."

        except FileNotFoundError:
            msg = f"Could not find the executable for {friendly_name} at: {executable}"
            logger.error(msg)
            return False, msg
        except Exception as e:
            msg = f"Failed to launch {friendly_name}: {e}"
            logger.error(msg)
            return False, msg
