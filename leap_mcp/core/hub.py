"""The researcher's hub server: user, image, resource limits, GPU and personal folders."""

import os
import shutil
import subprocess

from .common import human_bytes

NOT_SET = "not set (not on the LEAP hub?)"
NVIDIA_SMI_TIMEOUT_SECONDS = 10


def _env(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


def _memory(value: str | None) -> str:
    if value is None:
        return NOT_SET
    try:
        return f"{human_bytes(float(value))} ({value} bytes)"
    except ValueError:
        return value


def gpu_name() -> str:
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return "none (nvidia-smi not found)"
    try:
        result = subprocess.run(
            [exe, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=NVIDIA_SMI_TIMEOUT_SECONDS,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown (nvidia-smi failed)"
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return ", ".join(names) or "none (nvidia-smi found no GPU)"


def get_my_environment() -> str:
    user = _env("JUPYTERHUB_USER")
    folder = user or "<github-username>"
    lines = [
        "# Your LEAP hub environment",
        f"- User (JUPYTERHUB_USER): {user or NOT_SET}",
        f"- Image (JUPYTER_IMAGE_SPEC): {_env('JUPYTER_IMAGE_SPEC') or NOT_SET}",
        f"- Memory limit (MEM_LIMIT): {_memory(_env('MEM_LIMIT'))}",
        f"- CPU limit (CPU_LIMIT): {_env('CPU_LIMIT') or NOT_SET}",
        f"- GPU: {gpu_name()}",
        "",
        "## Your folders (write only here)",
        f"- gs://leap-scratch/{folder}/ (deleted after 7 days)",
        f"- gs://leap-persistent/{folder}/ (kept until you delete it)",
    ]
    if user is None:
        lines.append("JUPYTERHUB_USER is not set, so replace <github-username> with your GitHub username.")
    return "\n".join(lines)
