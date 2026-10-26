"""NVIDIA engine: diffusers ZImagePipeline. torch/diffusers are imported only inside methods."""
from __future__ import annotations

import gc
import time
import importlib.metadata
from pathlib import Path

from medimg.config import DIFFUSERS_MODEL_ID, DIFFUSERS_MODEL_REVISION
from medimg.engines.base import CancelFn, GenResult, ProgressFn
from medimg.errors import Cancelled, Invalid

OFFLOAD_MODES = ("resident", "model_cpu_offload", "gguf_q8_offload", "gguf_q4_sequential")


class _BadOffloadMode(Invalid, ValueError):
    pass


class DiffusersEngine:
    name = "diffusers"
    model_id = DIFFUSERS_MODEL_ID

    def __init__(self, offload_mode: str, gguf_path: Path | None = None):
        if offload_mode not in OFFLOAD_MODES:
            raise _BadOffloadMode(
                f"Unknown offload mode {offload_mode!r}.",
                f"Use one of: {', '.join(OFFLOAD_MODES)}.",
            )
        self.offload_mode = offload_mode
        self.gguf_path = Path(gguf_path) if gguf_path is not None else None
        self.loaded = False
        self._pipe = None

    def load(self, on_progress: ProgressFn | None = None) -> None:
        if self.loaded:
            return
        if self.offload_mode.startswith("gguf") and self.gguf_path is None:
            raise Invalid("A GGUF file is required for this offload mode.",
                          "Download the GGUF model first (run setup).")
        if on_progress:
            on_progress("loading", 0, 0)
        import torch
        from diffusers import ZImagePipeline

        kw: dict = {"torch_dtype": torch.bfloat16}
        if self.offload_mode.startswith("gguf"):
            from diffusers import GGUFQuantizationConfig, ZImageTransformer2DModel

            kw["transformer"] = ZImageTransformer2DModel.from_single_file(
                str(self.gguf_path),
                quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16),
                config=self.model_id,
                revision=DIFFUSERS_MODEL_REVISION,
                subfolder="transformer",
                torch_dtype=torch.bfloat16,
            )
        pipe = ZImagePipeline.from_pretrained(self.model_id, revision=DIFFUSERS_MODEL_REVISION, **kw)
        if self.offload_mode == "resident":
            pipe.to("cuda")
        elif self.offload_mode in ("model_cpu_offload", "gguf_q8_offload"):
            pipe.enable_model_cpu_offload()
        else:
            pipe.enable_sequential_cpu_offload()
        pipe.set_progress_bar_config(disable=True)
        self._pipe = pipe
        self.loaded = True

    def unload(self) -> None:
        if not self.loaded:
            return
        self._pipe = None
        self.loaded = False
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass

    def generate(self, prompt: str, seed: int, steps: int, width: int, height: int,
                 on_progress: ProgressFn, should_cancel: CancelFn) -> GenResult:
        if not self.loaded or self._pipe is None:
            raise RuntimeError("engine not loaded")
        import torch

        t0 = time.monotonic()
        cancelled = False

        def cb(pipe, i, t, kw):
            nonlocal cancelled
            on_progress("denoising", i + 1, steps)
            if i + 1 == steps:
                on_progress("decoding", steps, steps)
            if should_cancel():
                cancelled = True
                pipe._interrupt = True
            return kw

        try:
            torch.cuda.reset_peak_memory_stats()
            on_progress("encoding", 0, 0)
            out = self._pipe(
                prompt=prompt, height=height, width=width, num_inference_steps=steps,
                guidance_scale=0.0, generator=torch.Generator("cuda").manual_seed(seed),
                callback_on_step_end=cb, callback_on_step_end_tensor_inputs=["latents"],
            )
            if cancelled:
                raise Cancelled()
            image = out.images[0]
            peak = torch.cuda.max_memory_allocated() / 1e9
            return GenResult(image=image, seed=seed, time_s=time.monotonic() - t0,
                             peak_mem_gb=peak, steps=steps,
                             engine=f"diffusers {importlib.metadata.version('diffusers')}", model_id=self.model_id)
        finally:
            gc.collect()
            torch.cuda.empty_cache()
