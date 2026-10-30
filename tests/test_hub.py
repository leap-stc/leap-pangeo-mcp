import subprocess

import pytest

from leap_pangeo_mcp.core import hub

HUB_VARS = ["JUPYTERHUB_USER", "JUPYTER_IMAGE_SPEC", "MEM_LIMIT", "CPU_LIMIT"]


@pytest.fixture
def no_gpu(monkeypatch):
    monkeypatch.setattr(hub.shutil, "which", lambda name: None)


@pytest.fixture
def fake_nvidia_smi(monkeypatch):
    def install(stdout="", error=None):
        def run(args, **kwargs):
            if error:
                raise error
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

        monkeypatch.setattr(hub.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
        monkeypatch.setattr(hub.subprocess, "run", run)

    return install


def test_on_the_hub(monkeypatch, fake_nvidia_smi):
    monkeypatch.setenv("JUPYTERHUB_USER", "jdoe")
    monkeypatch.setenv("JUPYTER_IMAGE_SPEC", "quay.io/leap-stc/pangeo-jupyter-ai:2026.10.1")
    monkeypatch.setenv("MEM_LIMIT", str(32 * 1024**3))
    monkeypatch.setenv("CPU_LIMIT", "4.0")
    fake_nvidia_smi("Tesla T4\n")

    text = hub.get_my_environment()
    assert "- User (JUPYTERHUB_USER): jdoe" in text
    assert "- Image (JUPYTER_IMAGE_SPEC): quay.io/leap-stc/pangeo-jupyter-ai:2026.10.1" in text
    assert "- Memory limit (MEM_LIMIT): 32.0 GiB (34359738368 bytes)" in text
    assert "- CPU limit (CPU_LIMIT): 4.0" in text
    assert "- GPU: Tesla T4" in text
    assert "gs://leap-scratch/jdoe/" in text
    assert "gs://leap-persistent/jdoe/" in text
    assert hub.NOT_SET not in text


def test_off_the_hub_reports_unset_values(monkeypatch, no_gpu):
    for name in HUB_VARS:
        monkeypatch.delenv(name, raising=False)
    text = hub.get_my_environment()
    for label in ["User (JUPYTERHUB_USER)", "Image (JUPYTER_IMAGE_SPEC)", "Memory limit (MEM_LIMIT)", "CPU limit (CPU_LIMIT)"]:
        assert f"- {label}: not set (not on the LEAP hub?)" in text
    assert "- GPU: none (nvidia-smi not found)" in text
    assert "gs://leap-scratch/<github-username>/" in text


def test_blank_values_count_as_unset(monkeypatch, no_gpu):
    monkeypatch.setenv("JUPYTERHUB_USER", "  ")
    assert "- User (JUPYTERHUB_USER): not set (not on the LEAP hub?)" in hub.get_my_environment()


def test_unusual_memory_value_is_shown_as_is(monkeypatch, no_gpu):
    monkeypatch.setenv("MEM_LIMIT", "8G")
    assert "- Memory limit (MEM_LIMIT): 8G" in hub.get_my_environment()


def test_gpu_detection_edge_cases(fake_nvidia_smi):
    fake_nvidia_smi("NVIDIA A100-SXM4-40GB\nNVIDIA A100-SXM4-40GB\n")
    assert hub.gpu_name() == "NVIDIA A100-SXM4-40GB, NVIDIA A100-SXM4-40GB"
    fake_nvidia_smi("")
    assert hub.gpu_name() == "none (nvidia-smi found no GPU)"
    fake_nvidia_smi(error=subprocess.TimeoutExpired("nvidia-smi", 10))
    assert hub.gpu_name() == "unknown (nvidia-smi failed)"
