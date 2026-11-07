
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOTRO-TTS Setup Script

1. Enables site-packages for embedded Python.
2. Installs pip if missing.
3. Automatically detects NVIDIA, AMD ROCm or CPU.
4. Selects the appropriate PyTorch CUDA build based on NVIDIA
   compute capability:
      - CUDA 13.0: Compute capability 7.5+
      - CUDA 12.6: Older NVIDIA architectures
5. Installs OmniVoice, Whisper and required dependencies.
6. Verifies the installation and GPU acceleration.
"""

import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
WIN64_DIR = BASE_DIR / "python" / "win64"
LINUX64_DIR = BASE_DIR / "python" / "linux64"

if sys.platform.startswith("linux"):
    PYTHON_DIR = LINUX64_DIR
    PYTHON_EXE = (
        LINUX64_DIR / "bin" / "python3"
        if (LINUX64_DIR / "bin" / "python3").exists()
        else Path(sys.executable)
    )
else:
    PYTHON_DIR = WIN64_DIR
    PYTHON_EXE = WIN64_DIR / "python.exe"


# PyTorch versions
PYTORCH_VERSION = "2.14.1"
TORCHAUDIO_VERSION = "2.11.0"

# PyTorch package indexes
PYTORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu130"
PYTORCH_CUDA_LEGACY_INDEX = "https://download.pytorch.org/whl/cu126"
PYTORCH_ROCM_INDEX = "https://download.pytorch.org/whl/rocm7.2"
PYTORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def run_command(command):
    """Runs a command and stops if it fails."""
    subprocess.run(command, check=True)


def enable_site_packages():
    """Uncomments 'import site' in embedded Python configuration."""

    target_dirs = [WIN64_DIR, LINUX64_DIR]

    for pdir in target_dirs:
        if not pdir.exists():
            continue

        for pth in pdir.glob("*._pth"):
            content = pth.read_text(encoding="utf-8")
            lines = content.splitlines()
            modified = False

            for index, line in enumerate(lines):
                if line.strip() == "#import site":
                    lines[index] = "import site"
                    modified = True

            if modified:
                pth.write_text(
                    "\n".join(lines) + "\n",
                    encoding="utf-8"
                )
                print(f"Enabled site-packages in {pth.name}")


def install_pip():
    """Downloads and installs pip into embedded Python if necessary."""

    result = subprocess.run(
        [str(PYTHON_EXE), "-c", "import pip"],
        capture_output=True
    )

    if result.returncode == 0:
        print("Pip is already installed.")
        return

    print("Downloading get-pip.py...")

    PYTHON_DIR.mkdir(parents=True, exist_ok=True)

    get_pip_path = PYTHON_DIR / "get-pip.py"
    get_pip_url = "https://bootstrap.pypa.io/get-pip.py"

    urllib.request.urlretrieve(get_pip_url, str(get_pip_path))

    print("Installing pip into embedded Python...")

    try:
        run_command([
            str(PYTHON_EXE),
            str(get_pip_path),
            "--no-warn-script-location"
        ])
    finally:
        if get_pip_path.exists():
            get_pip_path.unlink()

    print("Pip installation successful!")


def detect_nvidia_cuda_index():
    """
    Selects CUDA 12.6 or CUDA 13.0 based on NVIDIA GPU architecture.

    CUDA 13.0: Compute capability >= 7.5
    CUDA 12.6: Compute capability < 7.5

    All detected NVIDIA GPUs must be supported by the same build.
    """

    if not shutil.which("nvidia-smi"):
        raise RuntimeError(
            "nvidia-smi was not found. Check your NVIDIA driver installation."
        )

    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=compute_cap",
            "--format=csv,noheader"
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Could not detect NVIDIA GPU compute capability.\n"
            f"{result.stderr.strip()}"
        )

    capabilities = []

    for line in result.stdout.splitlines():
        line = line.strip()

        if line:
            try:
                capabilities.append(float(line))
            except ValueError:
                raise RuntimeError(
                    f"Unexpected NVIDIA compute capability: {line}"
                )

    if not capabilities:
        raise RuntimeError("No NVIDIA GPUs were detected.")

    legacy = [cap for cap in capabilities if cap < 7.5]
    modern = [cap for cap in capabilities if cap >= 7.5]

    if legacy and modern:
        raise RuntimeError(
            f"Incompatible NVIDIA GPU architectures detected: {capabilities}\n"
            "CUDA 12.6 and CUDA 13.0 cannot support both architecture groups "
            "with a single PyTorch installation."
        )

    if legacy:
        print(f"Older NVIDIA architecture detected: {capabilities}")
        print("Selected PyTorch CUDA 12.6.")
        return PYTORCH_CUDA_LEGACY_INDEX

    print(f"Modern NVIDIA architecture detected: {capabilities}")
    print("Selected PyTorch CUDA 13.0.")
    return PYTORCH_CUDA_INDEX


def detect_compute_mode():
    """Automatically detects NVIDIA, AMD ROCm (Linux), or CPU."""

    # NVIDIA
    if shutil.which("nvidia-smi"):
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0 and "GPU" in result.stdout:
            return "nvidia"

    # AMD ROCm (Linux only)
    if sys.platform.startswith("linux"):
        for tool in ("rocminfo", "rocm-smi"):
            if shutil.which(tool):
                result = subprocess.run(
                    [tool],
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    return "amd"

    return "cpu"


def install_packages(mode: str):
    """Installs PyTorch, OmniVoice, Whisper and audio dependencies."""

    mode = mode.lower().strip()

    if mode == "auto":
        mode = detect_compute_mode()
        print(f"\nAutomatically detected hardware: {mode.upper()}")

    if mode in ["nvidia", "cuda", "gpu"]:
        mode = "nvidia"
        pytorch_index = detect_nvidia_cuda_index()

        mode_label = (
            "NVIDIA GPU (CUDA 13.0)"
            if pytorch_index == PYTORCH_CUDA_INDEX
            else "NVIDIA GPU (CUDA 12.6)"
        )

    elif mode in ["amd", "rocm"]:
        if not sys.platform.startswith("linux"):
            raise RuntimeError(
                "AMD ROCm is only supported on Linux."
            )

        mode = "amd"
        mode_label = "AMD GPU (ROCm 7.2)"
        pytorch_index = PYTORCH_ROCM_INDEX

    else:
        mode = "cpu"
        mode_label = "CPU ONLY"
        pytorch_index = PYTORCH_CPU_INDEX

    print("\n" + "=" * 60)
    print(f"Installing PyTorch & TorchAudio: {mode_label}")
    print("=" * 60)

    # Install matching PyTorch and TorchAudio builds.
    # TorchAudio 2.11 uses the stable ABI and supports PyTorch 2.11+.
    cmd_torch = [
        str(PYTHON_EXE), "-m", "pip", "install",
        "--upgrade",
        "--force-reinstall",
        "--no-input",
        "--disable-pip-version-check",
        "--no-warn-script-location",
        f"torch=={PYTORCH_VERSION}",
        f"torchaudio=={TORCHAUDIO_VERSION}",
        "--index-url", pytorch_index
    ]

    run_command(cmd_torch)

    # Core Audio, Speech, Voice Cloning and Screenreader packages.
    extra_packages = [
        "omnivoice",
        "openai-whisper",
        "soundfile",
        "sounddevice",
        "scipy",
        "librosa",
        "transformers",
        "sentencepiece",
        "numpy",
        "rapidocr_onnxruntime",
        "mss",
        "psutil",
        "pynput",
        "Pillow>=8,<13",
    ]

    print("\n" + "=" * 60)
    print("Installing Voice Cloning, Screenreader & Dependencies:")
    print(", ".join(extra_packages))
    print("=" * 60)

    cmd_extra = [
        str(PYTHON_EXE), "-m", "pip", "install",
        "--upgrade",
        "--no-input",
        "--disable-pip-version-check",
        "--no-warn-script-location"
    ] + extra_packages

    run_command(cmd_extra)

    # NVIDIA ONNX Runtime.
    if mode == "nvidia":
        # CUDA 12.x: ORT 1.20
        # CUDA 13.x: ORT 1.27+
        ort_version = (
            "onnxruntime-gpu==1.20.0"
            if pytorch_index == PYTORCH_CUDA_LEGACY_INDEX
            else "onnxruntime-gpu>=1.27,<1.31"
        )

        print(f"\nInstalling {ort_version}...")

        cmd_ort_gpu = [
            str(PYTHON_EXE), "-m", "pip", "install",
            ort_version,
            "--force-reinstall",
            "--no-deps",
            "--no-input",
            "--disable-pip-version-check",
            "--no-warn-script-location"
        ]

        run_command(cmd_ort_gpu)

    verify_installation()


def verify_installation():
    """Verifies PyTorch, TorchAudio, OmniVoice and GPU acceleration."""

    verify_script = """
import torch
import torchaudio
import soundfile
import omnivoice
import whisper

is_rocm = torch.version.hip is not None
is_cuda = torch.cuda.is_available()

if is_rocm:
    acceleration = "ROCm (AMD)"
elif is_cuda:
    acceleration = "CUDA (NVIDIA)"
else:
    acceleration = "CPU"

print(f"PyTorch: {torch.__version__}")
print(f"TorchAudio: {torchaudio.__version__}")
print(f"Acceleration: {acceleration}")

if is_cuda:
    for index in range(torch.cuda.device_count()):
        device = torch.device(f"cuda:{index}")
        name = torch.cuda.get_device_name(index)
        capability = torch.cuda.get_device_capability(index)

        # Actual CUDA operation to verify architecture support.
        test = torch.randn(16, 16, device=device)
        result = test @ test

        print(
            f"GPU {index}: {name} | "
            f"Compute capability: {capability} | "
            f"CUDA test: OK"
        )

print("OmniVoice, Whisper and audio dependencies: Successfully loaded!")
"""

    print("\n" + "=" * 60)
    print("Verifying Installation:")
    print("=" * 60)

    run_command([
        str(PYTHON_EXE),
        "-c",
        verify_script
    ])


def main():
    parser = argparse.ArgumentParser(
        description="LOTRO-TTS Setup"
    )

    parser.add_argument(
        "--mode",
        choices=[
            "auto",
            "gpu",
            "nvidia",
            "cuda",
            "amd",
            "rocm",
            "cpu"
        ],
        default="auto",
        help=(
            "Compute mode: auto (default), nvidia, "
            "amd (Linux ROCm), or cpu."
        )
    )

    args = parser.parse_args()

    print("=" * 60)
    print("LOTRO-TTS Audio & AI Environment Setup")
    print(f"Target Mode: {args.mode.upper()}")
    print(f"Python: {PYTHON_EXE}")
    print("=" * 60)

    if not PYTHON_EXE.exists():
        raise FileNotFoundError(
            f"Embedded Python was not found: {PYTHON_EXE}"
        )

    enable_site_packages()
    install_pip()
    install_packages(args.mode)

    print("\nLOTRO-TTS environment is ready!")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(
            f"\nERROR: Installation command failed "
            f"(exit code {error.returncode}).",
            file=sys.stderr
        )
        sys.exit(error.returncode)
    except Exception as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        sys.exit(1)
