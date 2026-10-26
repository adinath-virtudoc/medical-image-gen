"""Engine interface. No heavy imports anywhere in this file."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from PIL import Image

from medimg.errors import Cancelled

ProgressFn = Callable[[str, int, int], None]  # (phase, step_done, step_total)
CancelFn = Callable[[], bool]
PHASES = ("loading", "encoding", "denoising", "decoding")


@dataclass
class GenResult:
    image: Image.Image
    seed: int
    time_s: float          # wall time of generate() including encode and decode
    peak_mem_gb: float     # mflux: mx.get_peak_memory(); diffusers: cuda max alloc; fake: 0.0
    steps: int             # value passed as num_inference_steps
    engine: str            # e.g. "mflux 0.22.0", "diffusers 0.41.0", "fake"
    model_id: str


class Engine(Protocol):
    name: str
    model_id: str
    loaded: bool

    def load(self, on_progress: ProgressFn | None = None) -> None: ...
    def unload(self) -> None: ...
    def generate(self, prompt: str, seed: int, steps: int, width: int, height: int,
                 on_progress: ProgressFn, should_cancel: CancelFn) -> GenResult: ...


__all__ = ["ProgressFn", "CancelFn", "PHASES", "GenResult", "Engine", "Cancelled"]
