"""
Nova Assistant — Virtual Desktop Manager
Creates and switches Windows virtual desktops using pyvda.
"""

import logging
import time

logger = logging.getLogger("nova.desktop")


class VirtualDesktopManager:
    """
    Manages Windows 10/11 virtual desktops.

    Uses the pyvda library which wraps the native Windows
    IVirtualDesktopManager COM interface.
    """

    def __init__(self):
        self._available = False
        try:
            import pyvda
            self._pyvda = pyvda
            self._available = True
            count = len(pyvda.get_virtual_desktops())
            logger.info(f"Virtual desktop manager ready — {count} desktops detected")
        except Exception as e:
            logger.warning(f"Virtual desktops unavailable: {e}")
            logger.warning("Workspace routines will still work, but without a new desktop.")

    @property
    def available(self) -> bool:
        """Whether the virtual desktop API is available."""
        return self._available

    def create_and_switch(self) -> bool:
        """
        Create a new virtual desktop and switch to it.

        Returns:
            True if successful, False otherwise.
        """
        if not self._available:
            logger.warning("Cannot create desktop — pyvda not available")
            return False

        try:
            # Get current desktop count
            desktops_before = self._pyvda.get_virtual_desktops()
            count_before = len(desktops_before)

            # Create a new desktop
            new_desktop = self._pyvda.VirtualDesktop.create()
            time.sleep(0.5)  # Let Windows settle

            # Switch to the new desktop
            new_desktop.go()
            time.sleep(0.5)

            desktops_after = self._pyvda.get_virtual_desktops()
            logger.info(
                f"Created and switched to new virtual desktop "
                f"(was {count_before}, now {len(desktops_after)})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to create virtual desktop: {e}")
            return False

    def get_desktop_count(self) -> int:
        """Return the current number of virtual desktops."""
        if not self._available:
            return -1
        try:
            return len(self._pyvda.get_virtual_desktops())
        except Exception:
            return -1
