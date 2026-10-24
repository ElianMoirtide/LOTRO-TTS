#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOTRO-TTS Setup Script
1. Enables site-packages for embedded Python by activating 'import site' in *._pth.
2. Installs pip into embedded Python if not present (via get-pip.py).
3. Installs PyTorch (GPU / CUDA 12.6 or CPU) and required audio/TTS libraries.
"""

import argparse
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WIN64_DIR = BASE_DIR / "python" / "win64"
PYTHON_EXE = WIN64_DIR / "python.exe"

PYTORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu126"


def enable_site_packages():
    """Uncomments 'import site' in python3*._pth so site-packages works."""
    pth_files = list(WIN64_DIR.glob("*._pth"))
    for pth in pth_files:
        content = pth.read_text(encoding="utf-8")
        lines = content.splitlines()
        modified = False
        new_lines = []
        for line in lines:
            if line.strip() == "#import site":
                new_lines.append("import site")
                modified = True
            else:
                new_lines.append(line)
        if modified:
            pth.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            print(f"Enabled site-packages in {pth.name}")


def install_pip():
    """Downloads get-pip.py and installs pip into embedded python."""
    res = subprocess.run([str(PYTHON_EXE), "-c", "import pip"], capture_output=True)
    if res.returncode == 0:
        print("Pip is already installed.")
        return

    print("Downloading get-pip.py...")
    get_pip_url = "https://bootstrap.pypa.io/get-pip.py"
    get_pip_path = WIN64_DIR / "get-pip.py"
    urllib.request.urlretrieve(get_pip_url, str(get_pip_path))

    print("Installing pip into embedded Python...")
    subprocess.run([str(PYTHON_EXE), str(get_pip_path), "--no-warn-script-location"], check=True)
    if get_pip_path.exists():
        get_pip_path.unlink()
    print("Pip installation successful!")


def install_pytorch(mode: str):
    """Installs PyTorch and TorchAudio with CUDA or CPU."""
    mode = mode.lower().strip()
    print(f"\nInstalling PyTorch in mode: {mode.upper()}...")

    if mode == "gpu":
        print(f"Using CUDA index: {PYTORCH_CUDA_INDEX}")
        cmd = [
            str(PYTHON_EXE), "-m", "pip", "install",
            "--upgrade", "--no-warn-script-location",
            "torch", "torchaudio",
            "--index-url", PYTORCH_CUDA_INDEX
        ]
    else:
        cmd = [
            str(PYTHON_EXE), "-m", "pip", "install",
            "--upgrade", "--no-warn-script-location",
            "torch", "torchaudio"
        ]

    subprocess.run(cmd, check=True)

    # Additional audio processing packages
    extra_packages = ["soundfile", "numpy", "transformers", "scipy"]
    print(f"\nInstalling audio support packages: {', '.join(extra_packages)}...")
    cmd_extra = [str(PYTHON_EXE), "-m", "pip", "install", "--upgrade", "--no-warn-script-location"] + extra_packages
    subprocess.run(cmd_extra, check=True)

    # Verify installation and CUDA availability
    verify_cmd = [
        str(PYTHON_EXE), "-c",
        "import torch; print(f'PyTorch: {torch.__version__} | CUDA available: {torch.cuda.is_available()} | Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"CPU\"}')"
    ]
    print("\nVerifying PyTorch configuration:")
    subprocess.run(verify_cmd)


def main():
    parser = argparse.ArgumentParser(description="LOTRO-TTS Setup")
    parser.add_argument("--mode", choices=["gpu", "cpu"], default="gpu", help="Compute mode: gpu (NVIDIA/CUDA) or cpu")
    args = parser.parse_args()

    print("=" * 60)
    print("LOTRO-TTS Audio & AI Environment Setup")
    print(f"Target Mode: {args.mode.upper()}")
    print("=" * 60)

    enable_site_packages()
    install_pip()
    install_pytorch(args.mode)
    print("\nLOTRO-TTS environment is ready!")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()

