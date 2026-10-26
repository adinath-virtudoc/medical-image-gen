"""mflux (Apple Silicon / MLX) engine. mflux and mlx are imported only inside methods."""
from __future__ import annotations

import gc
import importlib.metadata
import time

from medimg.config import MFLUX_MODEL_ID
from medimg.engines.base import CancelFn, GenResult, ProgressFn
from medimg.errors import Cancelled


def _noop(*_a, **_k) -> None:
    return None


class _Progress:
    """Callback object registered once; per-job state is swapped in by generate()."""

    def __init__(self) -> None:
        self.on_progress: ProgressFn = _noop
        self.should_cancel: CancelFn = lambda: False
        self.cancelled = False

    def arm(self, on_progress: ProgressFn, should_cancel: CancelFn) -> None:
        self.on_progress = on_progress
        self.should_cancel = should_cancel
        self.cancelled = False

    def disarm(self) -> None:
        self.on_progress = _noop
        self.should_cancel = lambda: False

    def call_before_loop(self, seed, prompt, latents, config,
                         canny_image=None, depth_image=None, control_images=None):
        return None

    def call_in_loop(self, t, seed, prompt, latents, config, time_steps):
        # Never touch latents: this fires before mx.eval(latents).
        start = config.init_time_step
        self.on_progress("denoising", t - start + 1, config.num_inference_steps - start)
        if self.should_cancel():
            from mflux.utils.exceptions import StopImageGenerationException
            self.cancelled = True
            raise StopImageGenerationException()

    def call_after_loop(self, seed, prompt, latents, config):
        n = config.num_inference_steps - config.init_time_step
        self.on_progress("decoding", n, n)


class MfluxEngine:
    name = "mflux"
    model_id = MFLUX_MODEL_ID

    def __init__(self, cache_limit_bytes: int = 1000**3) -> None:
        self._cache_limit = cache_limit_bytes
        self._model = None
        self._progress = _Progress()
        self.loaded = False

    def load(self, on_progress: ProgressFn | None = None) -> None:
        if self.loaded:
            return
        if on_progress:
            on_progress("loading", 0, 0)
        import mlx.core as mx
        from mflux.models.common.config.model_config import ModelConfig
        from mflux.models.common.vae.tiling_config import TilingConfig
        from mflux.models.z_image.variants.z_image import ZImage

        model = ZImage(model_path=self.model_id, model_config=ModelConfig.z_image_turbo(),
                       quantize=None)
        model.tiling_config = TilingConfig()
        mx.set_cache_limit(self._cache_limit)
        model.callbacks.register(self._progress)
        self._model = model
        self.loaded = True
        if on_progress:
            on_progress("loading", 1, 1)

    def unload(self) -> None:
        if not self.loaded:
            return
        self._model = None
        self.loaded = False
        gc.collect()
        try:
            import mlx.core as mx
            mx.clear_cache()
        except ImportError:
            pass

    def generate(self, prompt: str, seed: int, steps: int, width: int, height: int,
                 on_progress: ProgressFn, should_cancel: CancelFn) -> GenResult:
        if not self.loaded or self._model is None:
            raise RuntimeError("engine not loaded")
        import mlx.core as mx
        from mflux.utils.exceptions import StopImageGenerationException

        self._progress.arm(on_progress, should_cancel)
        mx.reset_peak_memory()
        try:
            on_progress("encoding", 0, 0)
            t0 = time.perf_counter()
            try:
                out = self._model.generate_image(seed=seed, prompt=prompt,
                                                 num_inference_steps=steps,
                                                 height=height, width=width)
            except StopImageGenerationException as exc:
                raise Cancelled() from exc
            time_s = time.perf_counter() - t0
            peak = mx.get_peak_memory() / 1e9
            return GenResult(image=out.image, seed=seed, time_s=time_s, peak_mem_gb=peak,
                             steps=steps,
                             engine=f"mflux {importlib.metadata.version('mflux')}",
                             model_id=self.model_id)
        finally:
            self._progress.disarm()
            gc.collect()
            mx.clear_cache()
