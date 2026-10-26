"""Deterministic fake engine for tests and --fake-engine UI work."""
from __future__ import annotations

import random
import time
from typing import Iterable

from PIL import Image, ImageDraw

from medimg.engines.base import CancelFn, GenResult, ProgressFn
from medimg.errors import Cancelled


class FakeEngine:
    name = "fake"
    model_id = "fake/fake-model"

    def __init__(self, step_s: float = 0.01, fail_on: Iterable[int] = (), image_size_divisor: int = 8):
        self.step_s = step_s
        self.fail_on = set(fail_on)
        self.image_size_divisor = max(1, int(image_size_divisor))
        self.loaded = False
        self.calls = 0  # generate() calls so far (1-based n-th for fail_on)

    def load(self, on_progress: ProgressFn | None = None) -> None:
        if self.loaded:
            return
        if on_progress:
            on_progress("loading", 0, 0)
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def generate(self, prompt: str, seed: int, steps: int, width: int, height: int,
                 on_progress: ProgressFn, should_cancel: CancelFn) -> GenResult:
        if not self.loaded:
            raise RuntimeError("engine not loaded")
        self.calls += 1
        t0 = time.perf_counter()
        try:
            if self.calls in self.fail_on:
                raise RuntimeError("fake failure")
            on_progress("encoding", 0, 0)
            for k in range(1, steps + 1):
                if self.step_s > 0:
                    time.sleep(self.step_s)
                on_progress("denoising", k, steps)
                if should_cancel():
                    raise Cancelled()
            on_progress("decoding", steps, steps)
            div = self.image_size_divisor
            w, h = max(1, width // div), max(1, height // div)
            rng = random.Random(seed)
            colour = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            img = Image.new("RGB", (w, h), colour)
            ImageDraw.Draw(img).rectangle([0, 0, w // 2, h // 2], fill=tuple(255 - c for c in colour))
            return GenResult(image=img, seed=seed, time_s=time.perf_counter() - t0, peak_mem_gb=0.0,
                             steps=steps, engine="fake", model_id=self.model_id)
        finally:
            pass  # nothing to release
