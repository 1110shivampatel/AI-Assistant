"""
Nova Assistant — Safety Policy
Centralized permission checks for all tool operations.
"""

import os
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger("nova.safety")


class SafetyPolicy:
    """
    Enforces security constraints on all tool actions.

    Rules:
    - File operations: READ/OPEN only within allowed root folders
    - No delete, move, rename, or write operations
    - App launches: only from the registered app registry
    - Chrome: only via profile launch (no arbitrary command injection)
    - Work mode: requires two-factor confirmation
    """

    # Absolutely blocked operations — never allowed
    BLOCKED_OPERATIONS = frozenset({
        "delete", "remove", "rm", "rmdir",
        "move", "mv", "rename",
        "write", "overwrite", "modify",
        "format", "shutdown", "reboot",
    })

    # Allowed file operations
    ALLOWED_FILE_OPS = frozenset({
        "list", "search", "index", "read", "open", "stat", "metadata",
    })

    def __init__(self, config: dict):
        self._config = config
        file_cfg = config.get("file_access", {})
        self._allowed_roots = [
            Path(p).resolve()
            for p in file_cfg.get("allowed_roots", [])
        ]
        self._max_results = file_cfg.get("max_results", 20)

    def is_path_allowed(self, target_path: str) -> bool:
        """Check if a file/folder path falls within allowed roots."""
        try:
            resolved = Path(target_path).resolve()
            for root in self._allowed_roots:
                if resolved == root or root in resolved.parents:
                    return True
            logger.warning(f"Path denied (outside allowed roots): {target_path}")
            return False
        except (ValueError, OSError) as e:
            logger.error(f"Path validation error for '{target_path}': {e}")
            return False

    def is_file_operation_allowed(self, operation: str) -> bool:
        """Check if a file operation type is permitted."""
        op = operation.lower().strip()
        if op in self.BLOCKED_OPERATIONS:
            logger.warning(f"Blocked operation attempted: {operation}")
            return False
        if op in self.ALLOWED_FILE_OPS:
            return True
        logger.warning(f"Unknown file operation denied: {operation}")
        return False

    def validate_file_action(
        self, operation: str, target_path: str
    ) -> tuple[bool, Optional[str]]:
        """
        Full validation of a file action.

        Returns:
            (allowed: bool, reason: Optional[str])
        """
        if not self.is_file_operation_allowed(operation):
            return False, f"Operation '{operation}' is not allowed"
        if not self.is_path_allowed(target_path):
            return False, f"Path '{target_path}' is outside allowed folders"
        return True, None

    def validate_app_launch(
        self, app_name: str, app_registry: dict
    ) -> tuple[bool, Optional[str]]:
        """
        Validate that an app is in the known registry before launching.

        Returns:
            (allowed: bool, reason: Optional[str])
        """
        import re
        # Strip punctuation and filler words (same as AppLauncher.resolve_app)
        name_clean = re.sub(r'[.,!?;:\'"]+', '', app_name).strip()
        filler_words = {"the", "a", "an", "my", "this", "that", "please", "open", "launch", "start"}
        words = [w for w in name_clean.lower().split() if w not in filler_words]
        name_lower = " ".join(words) if words else name_clean.lower()

        apps = app_registry.get("apps", {})
        # Check by key
        if name_lower in apps:
            return True, None
        # Check by alias
        for key, info in apps.items():
            aliases = [a.lower() for a in info.get("aliases", [])]
            if name_lower in aliases:
                return True, None
        # Fuzzy substring match
        for key, info in apps.items():
            aliases = [a.lower() for a in info.get("aliases", [])]
            if any(name_lower in a or a in name_lower for a in aliases):
                return True, None
        # Single-word match
        for word in name_lower.split():
            for key, info in apps.items():
                aliases = [a.lower() for a in info.get("aliases", [])]
                if word in aliases or word == key:
                    return True, None

        logger.warning(f"App not in registry: {app_name} (cleaned: {name_lower})")
        return False, f"App '{app_name}' is not in the allowed app registry"

    def validate_chrome_profile(
        self, profile_key: str, chrome_config: dict
    ) -> tuple[bool, Optional[str]]:
        """Validate a Chrome profile key exists in config."""
        profiles = chrome_config.get("profiles", {})
        if profile_key.lower() in profiles:
            return True, None
        return False, f"Chrome profile '{profile_key}' not found in config"

    def check_intent_safety(self, intent: dict) -> tuple[bool, Optional[str]]:
        """
        High-level safety gate for parsed intents from the LLM.

        Returns:
            (safe: bool, reason: Optional[str])
        """
        intent_type = intent.get("intent", "").lower()

        # Always block dangerous-sounding intents
        dangerous_words = {"delete", "remove", "format", "shutdown", "reboot", "kill"}
        if any(word in intent_type for word in dangerous_words):
            return False, f"Intent '{intent_type}' contains blocked keywords"

        # Known safe intents
        safe_intents = {
            "open_app", "search_file", "open_file", "chrome_search",
            "start_work_mode", "sleep", "chat", "greeting", "help", "time",
            "weather_local", "list_files", "unknown",
        }
        if intent_type in safe_intents:
            return True, None

        logger.warning(f"Unknown intent type: {intent_type}")
        return False, f"Unknown intent type '{intent_type}' — blocked for safety"
