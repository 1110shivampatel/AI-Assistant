import os
import subprocess
import site
import glob
import sys

def build():
    print("Building Nova Assistant...")
    
    # Locate nvidia DLLs to bundle
    site_packages = site.getsitepackages()
    nvidia_bins = []
    for sp in site_packages:
        bins = glob.glob(os.path.join(sp, "nvidia", "**", "bin"), recursive=True)
        nvidia_bins.extend(bins)
    
    add_data_args = []
    # Add nvidia DLLs
    for bin_dir in nvidia_bins:
        add_data_args.extend(["--add-data", f"{bin_dir};nvidia_bins"])
        
    # We use --onedir (default when not using --onefile) because packaging large ML models
    # and CUDA DLLs into a single .exe causes incredibly slow startup times (extracting 2GB+ to temp folder).
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=NovaAssistant",
        "--onedir", 
        "--noconfirm",
        "--add-data", f"config{os.pathsep}config",
        "--add-data", f"data{os.pathsep}data",
        "--add-data", f"voices{os.pathsep}voices",
        "--hidden-import", "webrtcvad",
        "--hidden-import", "sounddevice",
        "--hidden-import", "yaml",
        "--hidden-import", "colorama",
        "--hidden-import", "keyboard",
        "--hidden-import", "pyautogui",
        "--hidden-import", "ollama",
        "--hidden-import", "faster_whisper",
        "--hidden-import", "piper",
        "--hidden-import", "core.intent_router",
        "--hidden-import", "safety.policy",
        "--hidden-import", "voice.tts",
        "--hidden-import", "voice.stt",
        "--hidden-import", "tools.app_tools",
        "--hidden-import", "tools.browser_tools",
        "--hidden-import", "tools.file_tools",
        "--hidden-import", "system.virtual_desktop",
        "--hidden-import", "system.hotkey_listener",
        "main.py"
    ] + add_data_args
    
    print(f"Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("\n✅ Build successful! The executable is located in the 'dist/NovaAssistant' folder.")
        print("To run Nova, execute 'dist/NovaAssistant/NovaAssistant.exe'.")
    else:
        print("\n❌ Build failed.")

if __name__ == "__main__":
    build()
