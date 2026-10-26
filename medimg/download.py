"""Model weight downloads. Setup is the only caller that may use the network."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from medimg import config
from medimg.errors import ModelUnavailable

GGUF_MODES = {"gguf_q8_offload": "q8_0", "gguf_q4_sequential": "q4_k_m"}
# The cached mflux snapshot holds only the model folders (no README, .gitattributes), so ask for
# exactly those; newer huggingface_hub rejects a snapshot that lacks files the pattern covers.
MFLUX_PATTERNS = ["tokenizer/*", "transformer/*", "text_encoder/*", "vae/*"]
FULL_MODES = ("resident", "model_cpu_offload")
# In the GGUF modes the 6B transformer comes from the GGUF file, so skip the fp32 shards.
GGUF_IGNORE_PATTERNS = ["transformer/*.safetensors", "transformer/*.safetensors.index.json"]


def mflux_cached(model_id: str = config.MFLUX_MODEL_ID,
                 revision: str = config.MFLUX_MODEL_REVISION) -> Path | None:
    """Path of the cached snapshot, or None. Never touches the network."""
    try:
        from huggingface_hub import snapshot_download
        return Path(snapshot_download(model_id, revision=revision, allow_patterns=MFLUX_PATTERNS,
                                     local_files_only=True))
    except Exception:
        return None


def download_mflux(progress: Callable[[str], None] = print) -> Path:
    cached = mflux_cached()
    if cached is not None:
        progress(f"✔ already done: model is in the Hugging Face cache ({cached})")
        return cached
    progress(f"Downloading {config.MFLUX_MODEL_ID} (about {config.MFLUX_MODEL_GB} GB). "
             "This takes 5-20 minutes depending on your internet.")
    try:
        from huggingface_hub import snapshot_download
        path = Path(snapshot_download(config.MFLUX_MODEL_ID, revision=config.MFLUX_MODEL_REVISION,
                                     allow_patterns=MFLUX_PATTERNS))
    except Exception as e:
        raise ModelUnavailable(f"Could not download the model: {e}",
                               "Check your internet connection and run setup again; "
                               "it resumes where it stopped.") from e
    progress(f"Model ready at {path}")
    return path


def _diffusers_plan(mode: str) -> tuple[list[str] | None, str | None, float]:
    """(ignore patterns, gguf key, download GB) for an offload mode."""
    if mode in FULL_MODES:
        return None, None, config.DIFFUSERS_MODEL_GB
    if mode in GGUF_MODES:
        key = GGUF_MODES[mode]
        return list(GGUF_IGNORE_PATTERNS), key, config.GGUF_FILES[key][1] + 8.3
    raise ModelUnavailable(f"Unknown offload mode: {mode!r}.", "Run assess again to pick a mode.")


def _snapshot_kwargs(mode: str) -> dict:
    ignore, _, _ = _diffusers_plan(mode)
    kwargs: dict = {"revision": config.DIFFUSERS_MODEL_REVISION}
    if ignore is not None:
        # Equivalent to allow_patterns that exclude transformer/*.safetensors.
        kwargs["allow_patterns"] = ["*.json", "*.txt", "*.model", "text_encoder/*", "vae/*",
                                    "tokenizer/*", "scheduler/*"]
        kwargs["ignore_patterns"] = ignore
    return kwargs


def diffusers_cached(mode: str) -> bool:
    """True when everything `download_diffusers(mode)` fetches is already cached."""
    try:
        from huggingface_hub import hf_hub_download, snapshot_download
        _, key, _ = _diffusers_plan(mode)
        snapshot_download(config.DIFFUSERS_MODEL_ID, local_files_only=True, **_snapshot_kwargs(mode))
        if key:
            hf_hub_download(config.GGUF_REPO_ID, config.GGUF_FILES[key][0], local_files_only=True)
        return True
    except Exception:
        return False


def download_diffusers(mode: str, progress: Callable[[str], None] = print) -> Path:
    _, key, gb = _diffusers_plan(mode)
    if diffusers_cached(mode):
        from huggingface_hub import snapshot_download
        progress("✔ already done: model is in the Hugging Face cache")
        return Path(snapshot_download(config.DIFFUSERS_MODEL_ID, local_files_only=True,
                                      **_snapshot_kwargs(mode)))
    progress(f"Downloading {config.DIFFUSERS_MODEL_ID} for mode {mode} (about {gb:.1f} GB). "
             "This can take 10-60 minutes depending on your internet.")
    try:
        from huggingface_hub import hf_hub_download, snapshot_download
        path = Path(snapshot_download(config.DIFFUSERS_MODEL_ID, **_snapshot_kwargs(mode)))
        if key:
            name = config.GGUF_FILES[key][0]
            progress(f"Downloading {name} from {config.GGUF_REPO_ID}")
            hf_hub_download(config.GGUF_REPO_ID, name)
    except Exception as e:
        raise ModelUnavailable(f"Could not download the model: {e}",
                               "Check your internet connection and run setup again; "
                               "it resumes where it stopped.") from e
    progress(f"Model ready at {path}")
    return path
