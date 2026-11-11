"""Build a versioned, one-file Windows executable without overwriting prior builds."""

from __future__ import annotations

import os
from pathlib import Path

import PyInstaller.__main__

from apply_assistant import __version__


PROJECT_ROOT = Path(__file__).resolve().parent
VERSION_FOLDER = PROJECT_ROOT / "dist" / f"v{__version__}"
BUILD_FOLDER = PROJECT_ROOT / "build" / "pyinstaller" / f"v{__version__}"
EXECUTABLE = VERSION_FOLDER / "ApplyAssistant.exe"


def main() -> None:
    if os.name != "nt":
        raise SystemExit("Build the Windows executable on Windows.")
    if VERSION_FOLDER.exists() and any(VERSION_FOLDER.iterdir()):
        raise SystemExit(f"Refusing to overwrite the existing version folder: {VERSION_FOLDER}")

    VERSION_FOLDER.mkdir(parents=True, exist_ok=True)
    BUILD_FOLDER.mkdir(parents=True, exist_ok=True)
    resource_argument = (
        f"{PROJECT_ROOT / 'resources'}{os.pathsep}resources"
    )
    os.chdir(PROJECT_ROOT)
    PyInstaller.__main__.run([
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name",
        "ApplyAssistant",
        "--distpath",
        str(VERSION_FOLDER),
        "--workpath",
        str(BUILD_FOLDER),
        "--specpath",
        str(BUILD_FOLDER),
        "--add-data",
        resource_argument,
        str(PROJECT_ROOT / "run_app.py"),
    ])
    if not EXECUTABLE.is_file():
        raise SystemExit(f"PyInstaller did not create the expected executable: {EXECUTABLE}")
    print(f"Built Apply Assistant {__version__}: {EXECUTABLE}")


if __name__ == "__main__":
    main()
