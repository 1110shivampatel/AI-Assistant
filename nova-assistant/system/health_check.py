"""
Nova Assistant — Health Check Module
Validates all prerequisites are available before starting.
"""

import shutil
import subprocess
import sys
import importlib
from pathlib import Path
from typing import Tuple

# ANSI color codes (via colorama on Windows)
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
except ImportError:
    # Fallback: no colors
    class Fore:
        GREEN = RED = YELLOW = CYAN = ""
    class Style:
        RESET_ALL = BRIGHT = ""


def _check_pass(label: str) -> None:
    print(f"  {Fore.GREEN}✓{Style.RESET_ALL} {label}")


def _check_fail(label: str, hint: str = "") -> None:
    msg = f"  {Fore.RED}✗{Style.RESET_ALL} {label}"
    if hint:
        msg += f"  {Fore.YELLOW}→ {hint}{Style.RESET_ALL}"
    print(msg)


def _check_warn(label: str, hint: str = "") -> None:
    msg = f"  {Fore.YELLOW}⚠{Style.RESET_ALL} {label}"
    if hint:
        msg += f"  {Fore.YELLOW}→ {hint}{Style.RESET_ALL}"
    print(msg)


def check_python_version(min_major: int = 3, min_minor: int = 10) -> bool:
    """Verify Python version meets minimum requirements."""
    v = sys.version_info
    ok = v.major >= min_major and v.minor >= min_minor
    label = f"Python {v.major}.{v.minor}.{v.micro}"
    if ok:
        _check_pass(label)
    else:
        _check_fail(label, f"Need Python {min_major}.{min_minor}+")
    return ok


def check_ffmpeg() -> bool:
    """Verify FFmpeg is on PATH (required by faster-whisper)."""
    found = shutil.which("ffmpeg") is not None
    if found:
        _check_pass("FFmpeg found on PATH")
    else:
        _check_fail("FFmpeg not found", "Install from https://ffmpeg.org or: winget install ffmpeg")
    return found


def check_ollama() -> bool:
    """Verify Ollama is installed and running."""
    if shutil.which("ollama") is None:
        _check_fail("Ollama not found", "Install from https://ollama.com/download")
        return False

    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            _check_pass("Ollama is installed and running")
            return True
        else:
            _check_fail("Ollama installed but not responding", "Run: ollama serve")
            return False
    except subprocess.TimeoutExpired:
        _check_fail("Ollama timed out", "Run: ollama serve")
        return False
    except Exception as e:
        _check_fail(f"Ollama error: {e}")
        return False


def check_ollama_model(model_name: str) -> bool:
    """Check if a specific Ollama model is pulled."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if model_name.split(":")[0] in result.stdout:
            _check_pass(f"Model '{model_name}' is available")
            return True
        else:
            _check_warn(
                f"Model '{model_name}' not found",
                f"Run: ollama pull {model_name}"
            )
            return False
    except Exception:
        _check_warn(f"Could not verify model '{model_name}'")
        return False


def check_nvidia_gpu() -> bool:
    """Check for NVIDIA GPU with CUDA support."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            gpu_info = result.stdout.strip()
            _check_pass(f"NVIDIA GPU: {gpu_info}")
            return True
        else:
            _check_warn("No NVIDIA GPU detected — will use CPU (slower)")
            return False
    except FileNotFoundError:
        _check_warn("nvidia-smi not found — will use CPU")
        return False


def check_microphone() -> bool:
    """Check if a microphone is available."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_devices = [d for d in devices if d['max_input_channels'] > 0]
        if input_devices:
            default = sd.query_devices(kind='input')
            _check_pass(f"Microphone: {default['name']}")
            return True
        else:
            _check_fail("No input audio devices found")
            return False
    except ImportError:
        _check_warn("sounddevice not installed — cannot check microphone")
        return False
    except Exception as e:
        _check_warn(f"Microphone check error: {e}")
        return False


def check_chrome(chrome_path: str) -> bool:
    """Verify Chrome executable exists."""
    if Path(chrome_path).exists():
        _check_pass(f"Chrome found at {chrome_path}")
        return True
    else:
        _check_warn(
            "Chrome not found at configured path",
            f"Update chrome.executable in settings.yaml"
        )
        return False


def check_allowed_folders(folders: list[str]) -> bool:
    """Verify allowlisted folders exist."""
    all_ok = True
    for folder in folders:
        if Path(folder).exists():
            _check_pass(f"Folder accessible: {folder}")
        else:
            _check_warn(f"Folder not found: {folder}")
            all_ok = False
    return all_ok


def check_python_packages() -> dict[str, bool]:
    """Check that required Python packages are importable."""
    required = {
        "ollama": "ollama",
        "faster_whisper": "faster-whisper",
        "piper": "piper-tts",
        "sounddevice": "sounddevice",
        "numpy": "numpy",
        "keyboard": "keyboard",
        "pyautogui": "pyautogui",
        "yaml": "pyyaml",
    }
    results = {}
    for import_name, pip_name in required.items():
        try:
            importlib.import_module(import_name)
            _check_pass(f"Package: {pip_name}")
            results[pip_name] = True
        except ImportError:
            _check_fail(f"Package: {pip_name}", f"pip install {pip_name}")
            results[pip_name] = False
    return results


def run_full_health_check(config: dict) -> Tuple[bool, dict]:
    """
    Run all health checks and return (all_critical_pass, detailed_results).

    Critical checks (must pass): Python, FFmpeg, Ollama
    Advisory checks (nice to have): GPU, microphone, packages
    """
    print(f"\n{Fore.CYAN}{'='*50}")
    print(f"  Nova Assistant — Health Check")
    print(f"{'='*50}{Style.RESET_ALL}\n")

    results = {}
    critical_ok = True

    # --- Critical checks ---
    print(f"{Fore.CYAN}[Critical Prerequisites]{Style.RESET_ALL}")
    results["python"] = check_python_version()
    results["ffmpeg"] = check_ffmpeg()
    results["ollama"] = check_ollama()

    if results["ollama"]:
        llm_cfg = config.get("llm", {})
        results["model_primary"] = check_ollama_model(
            llm_cfg.get("primary_model", "qwen2.5:7b-instruct")
        )

    for key in ["python", "ffmpeg", "ollama"]:
        if not results.get(key, False):
            critical_ok = False

    # --- Hardware checks ---
    print(f"\n{Fore.CYAN}[Hardware]{Style.RESET_ALL}")
    results["gpu"] = check_nvidia_gpu()
    results["microphone"] = check_microphone()

    # --- Software checks ---
    print(f"\n{Fore.CYAN}[Chrome]{Style.RESET_ALL}")
    chrome_cfg = config.get("chrome", {})
    results["chrome"] = check_chrome(
        chrome_cfg.get("executable", "")
    )

    # --- Folder checks ---
    print(f"\n{Fore.CYAN}[File Access Folders]{Style.RESET_ALL}")
    file_cfg = config.get("file_access", {})
    results["folders"] = check_allowed_folders(
        file_cfg.get("allowed_roots", [])
    )

    # --- Python packages ---
    print(f"\n{Fore.CYAN}[Python Packages]{Style.RESET_ALL}")
    pkg_results = check_python_packages()
    results["packages"] = pkg_results

    # --- Summary ---
    print(f"\n{Fore.CYAN}{'='*50}{Style.RESET_ALL}")
    if critical_ok:
        print(f"  {Fore.GREEN}All critical checks passed!{Style.RESET_ALL}")
    else:
        print(f"  {Fore.RED}Some critical checks failed. Fix them before running Nova.{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*50}{Style.RESET_ALL}\n")

    return critical_ok, results


if __name__ == "__main__":
    # Quick standalone test
    import yaml

    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    if config_path.exists():
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
    else:
        config = {}

    ok, _ = run_full_health_check(config)
    sys.exit(0 if ok else 1)
