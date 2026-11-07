#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOTRO-TTS Setup Script
1. Enables site-packages for embedded Python by activating 'import site' in *._pth.
2. Installs pip into embedded Python if not present (via get-pip.py).
3. Installs PyTorch (GPU / CUDA 12.6 or CPU).
4. Installs OmniVoice (k2-fsa/OmniVoice) and all required AI/Audio dependencies:
   - omnivoice
   - openai-whisper
   - soundfile
   - scipy
   - librosa
   - transformers
"""

import argparse
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WIN64_DIR = BASE_DIR / "python" / "win64"
LINUX64_DIR = BASE_DIR / "python" / "linux64"

if sys.platform.startswith("linux"):
    if (LINUX64_DIR / "bin" / "python3").exists():
        PYTHON_EXE = LINUX64_DIR / "bin" / "python3"
    else:
        PYTHON_EXE = Path(sys.executable)
else:
    PYTHON_EXE = WIN64_DIR / "python.exe"

PYTORCH_CUDA12_INDEX = "https://download.pytorch.org/whl/cu126"
PYTORCH_CUDA13_INDEX = "https://download.pytorch.org/whl/cu130"
PYTORCH_ROCM_INDEX = (
    "https://download.pytorch.org/whl/rocm6.2"
    if sys.platform.startswith("linux")
    else "https://stable.repo.amd.com/rocm/whl-next/"
)


def detect_nvidia_gpu() -> dict:
    """
    Detects NVIDIA GPU model, compute capability, and driver version.
    Determines whether the GPU uses Blackwell architecture (sm_120+, e.g. RTX 5070 / 5070 Ti / 5080 / 5090)
    which requires CUDA 13.0 (cu130), or older architectures (sm_75 - sm_90) which use CUDA 12.6 (cu126).
    """
    gpu_name = ""
    compute_cap = 0.0
    driver_version = ""

    # 1. Primary query via nvidia-smi
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,compute_cap,driver_version", "--format=csv,noheader"],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
        lines = [l for l in out.splitlines() if l.strip()]
        if lines:
            parts = [p.strip() for p in lines[0].split(",")]
            if len(parts) >= 1:
                gpu_name = parts[0]
            if len(parts) >= 2:
                try:
                    compute_cap = float(parts[1])
                except ValueError:
                    pass
            if len(parts) >= 3:
                driver_version = parts[2]
    except Exception:
        pass

    # 2. Secondary fallback via general nvidia-smi
    if not gpu_name:
        try:
            out = subprocess.check_output(["nvidia-smi"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if any(k in line for k in ["GeForce", "RTX", "GTX", "Quadro", "Tesla"]):
                    gpu_name = line.split("|")[1].strip() if "|" in line else line.strip()
                    break
        except Exception:
            pass

    # 3. Tertiary fallback via WMI / PowerShell on Windows
    if not gpu_name and sys.platform.startswith("win"):
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"],
                text=True, stderr=subprocess.DEVNULL
            )
            for line in out.splitlines():
                if any(k in line.lower() for k in ["nvidia", "geforce", "rtx", "gtx"]):
                    gpu_name = line.strip()
                    break
        except Exception:
            pass

    # 4. Quaternary fallback via lspci on Linux
    if not gpu_name and sys.platform.startswith("linux"):
        try:
            out = subprocess.check_output(["lspci"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if ("VGA" in line or "3D" in line) and "nvidia" in line.lower():
                    gpu_name = line.strip()
                    break
        except Exception:
            pass

    # Architecture evaluation:
    # Blackwell / RTX 5000 Series (RTX 5070, 5070 Ti, 5080, 5090, 5060, B200) has compute capability >= 12.0 (sm_120)
    # PyTorch cu126 throws "no kernel image is available for execution on the device" on sm_120.
    # cu130 (CUDA 13.0) provides native sm_120 kernels.
    is_blackwell = compute_cap >= 12.0 or bool(re.search(r"RTX\s*50\d\d", gpu_name, re.IGNORECASE)) or "blackwell" in gpu_name.lower()

    if is_blackwell:
        cuda_tag = "cu130"
        cuda_label = "CUDA 13.0 (cu130 - Blackwell sm_120)"
        index_url = PYTORCH_CUDA13_INDEX
    else:
        cuda_tag = "cu126"
        cuda_label = "CUDA 12.6 (cu126)"
        index_url = PYTORCH_CUDA12_INDEX

    return {
        "gpu_name": gpu_name,
        "compute_cap": compute_cap,
        "driver_version": driver_version,
        "is_blackwell": is_blackwell,
        "cuda_tag": cuda_tag,
        "cuda_label": cuda_label,
        "index_url": index_url
    }


def detect_amd_gpu() -> str:
    """Detects whether an AMD Radeon GPU is installed (Windows or Linux)."""
    # 1. Linux tools
    if sys.platform.startswith("linux"):
        for tool in ("rocminfo", "rocm-smi"):
            try:
                out = subprocess.check_output([tool], text=True, stderr=subprocess.DEVNULL)
                if out:
                    return "AMD Radeon GPU (ROCm)"
            except Exception:
                pass
        try:
            out = subprocess.check_output(["lspci"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if ("VGA" in line or "3D" in line) and any(k in line.lower() for k in ["amd", "radeon", "advanced micro devices"]):
                    return line.strip()
        except Exception:
            pass

    # 2. Windows WMI / PowerShell
    if sys.platform.startswith("win"):
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"],
                text=True, stderr=subprocess.DEVNULL
            )
            for line in out.splitlines():
                if any(k in line.lower() for k in ["radeon", "amd"]):
                    return line.strip()
        except Exception:
            pass

    return ""


def detect_compute_mode() -> str:
    """Automatically detects hardware: NVIDIA -> AMD -> CPU."""
    nvidia_info = detect_nvidia_gpu()
    if nvidia_info.get("gpu_name"):
        return "nvidia"

    amd_gpu = detect_amd_gpu()
    if amd_gpu:
        return "amd"

    return "cpu"


def enable_site_packages():
    """Uncomments 'import site' in python3*._pth so site-packages works."""
    target_dirs = [WIN64_DIR]
    if LINUX64_DIR.exists():
        target_dirs.append(LINUX64_DIR)

    for pdir in target_dirs:
        for pth in pdir.glob("*._pth"):
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


def install_packages(mode: str):
    """Installs PyTorch, OmniVoice, Whisper and all audio support packages."""
    mode = mode.lower().strip()
    if mode == "auto":
        detected = detect_compute_mode()
        print(f"\n[AUTO-DETECTION] Detected hardware backend: {detected.upper()}")
        mode = detected

    cuda_tag = None

    if mode in ["nvidia", "cuda", "gpu", "cu126", "cu128", "cu130"]:
        if mode == "cu130":
            cuda_tag = "cu130"
            mode_label = "NVIDIA GPU (CUDA 13.0 - Manual Override)"
            torch_index = PYTORCH_CUDA13_INDEX
        elif mode == "cu128":
            cuda_tag = "cu128"
            mode_label = "NVIDIA GPU (CUDA 12.8 - Manual Override)"
            torch_index = "https://download.pytorch.org/whl/cu128"
        elif mode == "cu126":
            cuda_tag = "cu126"
            mode_label = "NVIDIA GPU (CUDA 12.6 - Manual Override)"
            torch_index = PYTORCH_CUDA12_INDEX
        else:
            gpu_info = detect_nvidia_gpu()
            cuda_tag = gpu_info["cuda_tag"]
            torch_index = gpu_info["index_url"]
            if gpu_info.get("gpu_name"):
                mode_label = f"NVIDIA GPU ({gpu_info['cuda_label']} -> {gpu_info['gpu_name']})"
            else:
                mode_label = f"NVIDIA GPU ({gpu_info['cuda_label']})"

            if gpu_info.get("is_blackwell"):
                print(f"[NVIDIA ARCHITECTURE] Detected Blackwell / sm_120 GPU: {gpu_info.get('gpu_name')}")
                print(f"  -> Automatically selected PyTorch CUDA 13.0 ({cuda_tag}) build for native sm_120 support.")
            elif gpu_info.get("gpu_name"):
                print(f"[NVIDIA ARCHITECTURE] Detected GPU: {gpu_info.get('gpu_name')} (Compute Cap: {gpu_info.get('compute_cap')})")
                print(f"  -> Automatically selected PyTorch CUDA 12.6 ({cuda_tag}) build.")
    elif mode in ["amd", "rocm"]:
        mode_label = "AMD GPU (ROCm 6.x / 10.x - RDNA 3/4)"
        torch_index = PYTORCH_ROCM_INDEX
    else:
        mode_label = "CPU ONLY"
        torch_index = "https://download.pytorch.org/whl/cpu"

    print(f"\n========================================================")
    print(f"Installing PyTorch & TorchAudio in mode: {mode_label}...")
    print(f"========================================================")
    print(f"Using PyTorch wheel index: {torch_index}", flush=True)

    cmd_torch = [
        str(PYTHON_EXE), "-m", "pip", "install",
        "--upgrade", "--force-reinstall", "--no-input", "--disable-pip-version-check", "--no-warn-script-location",
        "torch", "torchaudio",
        "--index-url", torch_index
    ]
    subprocess.run(cmd_torch, check=True)

    # Core Audio, Speech, Zero-Shot Voice Cloning, Translation & Screenreader packages
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
        "Pillow",
    ]
    print(f"\n========================================================", flush=True)
    print(f"Installing Voice Cloning, Screenreader & Dependencies:", flush=True)
    print(f"  {', '.join(extra_packages)}", flush=True)
    print(f"========================================================", flush=True)
    cmd_extra = [
        str(PYTHON_EXE), "-m", "pip", "install",
        "--upgrade", "--no-input", "--disable-pip-version-check", "--no-warn-script-location"
    ] + extra_packages
    subprocess.run(cmd_extra, check=True)

    if cuda_tag:
        # Install onnxruntime-gpu matching the CUDA generation after rapidocr
        # so CPU onnxruntime does not shadow CUDAExecutionProvider
        print(f"\nConfiguring ONNX Runtime GPU for {cuda_tag.upper()}...", flush=True)
        if cuda_tag == "cu130":
            # CUDA 13.0 / Blackwell uses modern onnxruntime-gpu
            cmd_ort_gpu = [
                str(PYTHON_EXE), "-m", "pip", "install",
                "onnxruntime-gpu", "--upgrade", "--no-deps",
                "--no-input", "--disable-pip-version-check", "--no-warn-script-location"
            ]
        else:
            # CUDA 12.6 uses pinned onnxruntime-gpu 1.20.0
            cmd_ort_gpu = [
                str(PYTHON_EXE), "-m", "pip", "install",
                "onnxruntime-gpu==1.20.0", "--force-reinstall", "--no-deps",
                "--no-input", "--disable-pip-version-check", "--no-warn-script-location"
            ]
        try:
            subprocess.run(cmd_ort_gpu, check=False)
        except Exception as e:
            print(f"Notice: ONNX Runtime GPU installation notice: {e}", flush=True)

    # Verification
    verify_code = (
        "import torch, soundfile, omnivoice, whisper; "
        "is_rocm = hasattr(torch.version, 'hip') and torch.version.hip is not None; "
        "is_cuda = torch.cuda.is_available(); "
        "hw = 'ROCm (AMD)' if is_rocm else ('CUDA (NVIDIA)' if is_cuda else 'CPU'); "
        "dev = torch.cuda.get_device_name(0) if is_cuda else 'CPU'; "
        "print(f'PyTorch: {torch.__version__} | Acceleration: {hw} | Device: {dev}'); "
        "if is_cuda or is_rocm: "
        "    for idx in range(torch.cuda.device_count()): "
        "        d = torch.device(f'cuda:{idx}'); "
        "        test = torch.randn(16, 16, device=d); "
        "        res = test @ test; "
        "        print(f'  [GPU {idx}] {torch.cuda.get_device_name(idx)}: Tensor computation test OK'); "
        "print('OmniVoice & Whisper: Successfully loaded!')"
    )
    verify_cmd = [str(PYTHON_EXE), "-c", verify_code]
    print("\n========================================================", flush=True)
    print("Verifying Installation:", flush=True)
    print("========================================================", flush=True)
    subprocess.run(verify_cmd, check=True)


def main():
    parser = argparse.ArgumentParser(description="LOTRO-TTS Setup")
    parser.add_argument(
        "--mode",
        choices=["auto", "gpu", "nvidia", "cuda", "cu126", "cu128", "cu130", "amd", "rocm", "cpu"],
        default="auto",
        help="Compute mode: auto (default: auto-detects NVIDIA/Blackwell vs AMD ROCm vs CPU), nvidia, cu130, cu126, amd, or cpu"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("LOTRO-TTS Audio & AI Environment Setup")
    print(f"Target Mode: {args.mode.upper()}")
    print("=" * 60)

    enable_site_packages()
    install_pip()
    install_packages(args.mode)
    print("\nLOTRO-TTS environment is ready!")


if __name__ == "__main__":
    main()
