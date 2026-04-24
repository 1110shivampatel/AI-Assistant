"""
Nova Assistant — Browser Tools
Launches Chrome with specific profiles and URLs.
"""

import logging
import subprocess
from typing import Optional, Tuple

logger = logging.getLogger("nova.tools.browser")


class BrowserLauncher:
    """
    Launches Google Chrome with a specific user profile and optional URLs.

    Uses the Chrome --profile-directory flag to select which
    logged-in profile to use (e.g. "Profile 2" for Shivam's daily profile).
    """

    def __init__(self, config: dict, safety_policy):
        self._config = config
        self._policy = safety_policy

        chrome_cfg = config.get("chrome", {})
        self._chrome_exe = chrome_cfg.get(
            "executable",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
        self._profiles = chrome_cfg.get("profiles", {})

        logger.info(
            f"Browser launcher ready — {len(self._profiles)} profiles configured"
        )

    def launch_profile(
        self, profile_key: str, urls: Optional[list] = None
    ) -> Tuple[bool, str]:
        """
        Open Chrome with a specific profile.

        Args:
            profile_key: Key from settings.yaml (e.g. "shivam", "vedixapp").
            urls: Optional list of URLs to open as tabs.

        Returns:
            (success, message)
        """
        # Safety check
        allowed, reason = self._policy.validate_chrome_profile(
            profile_key, self._config.get("chrome", {})
        )
        if not allowed:
            return False, reason

        profile_info = self._profiles.get(profile_key.lower())
        if not profile_info:
            return False, f"Chrome profile '{profile_key}' not found."

        profile_dir = profile_info["directory"]
        description = profile_info.get("description", profile_key)

        cmd = [
            self._chrome_exe,
            f"--profile-directory={profile_dir}",
        ]
        if urls:
            cmd.extend(urls)

        try:
            subprocess.Popen(
                cmd,
                creationflags=subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NO_WINDOW,
            )
            url_str = f" with {len(urls)} tabs" if urls else ""
            logger.info(f"Chrome launched: {description} ({profile_dir}){url_str}")
            return True, f"Opened Chrome {description} profile{url_str}."
        except FileNotFoundError:
            msg = f"Chrome not found at: {self._chrome_exe}"
            logger.error(msg)
            return False, msg
        except Exception as e:
            msg = f"Failed to launch Chrome: {e}"
            logger.error(msg)
            return False, msg

    def search(self, query: str, profile_key: str = "shivam") -> Tuple[bool, str]:
        """
        Open a Google search in Chrome with a specific profile.

        Args:
            query: The search query.
            profile_key: Which Chrome profile to use (defaults to Shivam's).

        Returns:
            (success, message)
        """
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        return self.launch_profile(profile_key, urls=[search_url])
