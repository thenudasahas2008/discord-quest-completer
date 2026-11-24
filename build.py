"""
Build script to package DiscordQuestCompleter into a single standalone portable .exe
and place it directly on the user's Desktop (supporting OneDrive Desktop).
"""

import os
import sys
import shutil
import subprocess

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_EXE_NAME = "DiscordQuestCompleter.exe"

DESKTOP_DIRS = [
    os.path.join(os.environ.get("USERPROFILE", "C:\\Users\\sahas"), "OneDrive", "Desktop"),
    os.path.join(os.environ.get("USERPROFILE", "C:\\Users\\sahas"), "Desktop"),
]

def build():
    print("==================================================")
    print("Building Discord Quest Completer Pro (Unlimited Mode)")
    print("==================================================")

    app_path = os.path.join(PROJECT_DIR, "app.py")
    icon_path = os.path.join(PROJECT_DIR, "assets", "app.ico")
    assets_dir = os.path.join(PROJECT_DIR, "assets")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name=DiscordQuestCompleter",
        f"--icon={icon_path}",
        f"--add-data={os.path.join(assets_dir, 'runner.exe')};assets",
        f"--add-data={os.path.join(assets_dir, 'gamelist.json')};assets",
        f"--add-data={os.path.join(assets_dir, 'app.ico')};assets",
        "--collect-all=customtkinter",
        "--collect-all=darkdetect",
        "--collect-all=psutil",
        app_path
    ]

    print("Running PyInstaller...")
    result = subprocess.run(cmd, cwd=PROJECT_DIR)

    if result.returncode != 0:
        print(f"[ERROR] PyInstaller failed with exit code {result.returncode}")
        sys.exit(result.returncode)

    built_exe = os.path.join(PROJECT_DIR, "dist", OUTPUT_EXE_NAME)
    if not os.path.exists(built_exe):
        print(f"[ERROR] Expected output executable not found at: {built_exe}")
        sys.exit(1)

    for desktop in DESKTOP_DIRS:
        if os.path.exists(desktop):
            target_path = os.path.join(desktop, OUTPUT_EXE_NAME)
            print(f"Deploying to: {target_path}")
            shutil.copy2(built_exe, target_path)

    # Notify Windows Shell to refresh desktop icon cache
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:
        pass

    print("\n[SUCCESS] Build and deployment complete!")

if __name__ == "__main__":
    build()
