"""
Nova Assistant — File Tools
Read-only file search and open operations within allowed folders.
"""

import fnmatch
import logging
import os
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("nova.tools.file")


class FileTools:
    """
    Provides safe, read-only file search and open operations.

    All paths are validated against the SafetyPolicy before access.
    Only files within allowed_roots can be searched or opened.
    """

    def __init__(self, config: dict, safety_policy):
        self._config = config
        self._policy = safety_policy

        file_cfg = config.get("file_access", {})
        self._allowed_roots = [
            Path(p) for p in file_cfg.get("allowed_roots", [])
        ]
        self._max_results = file_cfg.get("max_results", 20)
        self._index_extensions = set(
            file_cfg.get("index_extensions", [".pdf", ".docx", ".txt", ".py"])
        )

        logger.info(
            f"File tools ready — {len(self._allowed_roots)} search roots, "
            f"{len(self._index_extensions)} indexed extensions"
        )

    def search(self, query: str) -> Tuple[bool, str, List[str]]:
        """
        Search for files matching a query across allowed folders.

        Uses case-insensitive substring matching on filenames.

        Args:
            query: The search term (e.g. "resume", "budget").

        Returns:
            (success, message, list_of_matching_paths)
        """
        query_lower = query.lower().strip()
        if not query_lower:
            return False, "Empty search query.", []

        matches = []

        for root in self._allowed_roots:
            if not root.exists():
                continue

            try:
                for dirpath, dirnames, filenames in os.walk(root):
                    # Skip hidden and system directories
                    dirnames[:] = [
                        d for d in dirnames
                        if not d.startswith(".") and d not in {"node_modules", "__pycache__", "venv", ".git"}
                    ]

                    for fname in filenames:
                        # Check extension filter
                        ext = Path(fname).suffix.lower()
                        if ext not in self._index_extensions:
                            continue

                        # Case-insensitive substring match
                        if query_lower in fname.lower():
                            full_path = os.path.join(dirpath, fname)
                            matches.append(full_path)

                            if len(matches) >= self._max_results:
                                break

                    if len(matches) >= self._max_results:
                        break

            except PermissionError:
                logger.debug(f"Permission denied scanning: {root}")
                continue

        if matches:
            file_list = "\n".join(f"  • {Path(m).name}" for m in matches[:5])
            extra = f" and {len(matches) - 5} more" if len(matches) > 5 else ""
            msg = f"Found {len(matches)} file(s) matching '{query}':\n{file_list}{extra}"
            return True, msg, matches
        else:
            return True, f"No files found matching '{query}'.", []

    def open_file(self, filename: str) -> Tuple[bool, str]:
        """
        Open a file using the system default application.

        The file is first searched across allowed roots if no absolute path is given.

        Args:
            filename: Name or path of the file to open.

        Returns:
            (success, message)
        """
        # If it looks like an absolute path, validate and open directly
        target = Path(filename)
        if target.is_absolute():
            return self._open_path(target)

        # Otherwise, search for it
        _, _, matches = self.search(filename)

        if not matches:
            return False, f"Could not find a file called '{filename}'."

        if len(matches) == 1:
            return self._open_path(Path(matches[0]))

        # Multiple matches — open the first and inform the user
        success, msg = self._open_path(Path(matches[0]))
        if success:
            msg += f" (Note: {len(matches)} files matched — I opened the first one.)"
        return success, msg

    def _open_path(self, path: Path) -> Tuple[bool, str]:
        """Open a specific file path after safety validation."""
        # Safety check
        allowed, reason = self._policy.validate_file_action("open", str(path))
        if not allowed:
            return False, reason

        if not path.exists():
            return False, f"File not found: {path.name}"

        try:
            os.startfile(str(path))
            logger.info(f"Opened file: {path}")
            return True, f"Opened {path.name}."
        except Exception as e:
            msg = f"Failed to open {path.name}: {e}"
            logger.error(msg)
            return False, msg
