# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('config', 'config'), ('data', 'data'), ('voices', 'voices'), ('C:\\Users\\Shivam Patel\\Desktop\\AI-Assistant\\nova-assistant\\venv\\lib\\site-packages\\nvidia\\cublas\\bin', 'nvidia_bins'), ('C:\\Users\\Shivam Patel\\Desktop\\AI-Assistant\\nova-assistant\\venv\\lib\\site-packages\\nvidia\\cuda_nvrtc\\bin', 'nvidia_bins'), ('C:\\Users\\Shivam Patel\\Desktop\\AI-Assistant\\nova-assistant\\venv\\lib\\site-packages\\nvidia\\cudnn\\bin', 'nvidia_bins')],
    hiddenimports=['webrtcvad', 'sounddevice', 'yaml', 'colorama', 'keyboard', 'pyautogui', 'ollama', 'faster_whisper', 'piper', 'core.intent_router', 'safety.policy', 'voice.tts', 'voice.stt', 'tools.app_tools', 'tools.browser_tools', 'tools.file_tools', 'system.virtual_desktop', 'system.hotkey_listener'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NovaAssistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NovaAssistant',
)
