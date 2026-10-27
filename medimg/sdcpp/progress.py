"""Parse stable-diffusion.cpp `sd-cli` console output into progress events and
plain-language failure messages. Pure: stdlib only, no I/O."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

BAR = re.compile(
    r"^\|[=> #]*\|\s+(?P<k>\d+)/(?P<n>\d+) - +(?P<speed>[\d.]+)(?P<unit>s/it|it/s)"
    r"(?: - ETA (?P<eta>[\d:]+))?$"
)
LOADBAR = re.compile(r"^\|#*\s*\|\s+\d+/\d+ - .*B/s$")
ENCODED = re.compile(r"^\[I\] get_learned_condition completed, taking (?P<s>[\d.]+)s")
GENSTART = re.compile(r"^\[I\] generating image: \d+/\d+ - seed (?P<seed>\d+)")
SAMPLED = re.compile(r"^\[I\] sampling completed, taking (?P<s>[\d.]+)s")
DECODE = re.compile(r"^\[I\] decoding \d+ latents")
DECODED = re.compile(r"^\[I\] latent \d+ decoded, taking (?P<s>[\d.]+)s")
DONE = re.compile(r"^\[I\] generate_image completed in (?P<s>[\d.]+)s")
SAVED = re.compile(r"^\[I\] save result image \d+ to '(?P<path>.*)' \((?P<ok>success|failure)\)")
GPU_OOM = re.compile(r"ErrorOutOfDeviceMemory|failed to allocate (Vulkan|CUDA|Metal|MTL)\d* buffer")
RAM_OOM = re.compile(r"std::bad_alloc|failed to allocate CPU buffer|ggml_aligned_malloc: insufficient memory")
NOMODEL = re.compile(r"^\[W\] loading (diffusion model|llm|vae) from '.*' failed")
_ERRLINE = re.compile(r"^\[E\] (?P<msg>.*?)(?: --- \S+:\d+)?$")

NO_BINARY_CAUSE = "The image program (sd-cli) is not installed."
NO_BINARY_FIX = "Run setup again."

TAIL_MAX = 60


@dataclass
class ParseState:
    phase: str = "start"
    step: int = 0
    step_total: int = 0
    failure_class: str | None = None
    saved_path: str | None = None
    saved_ok: bool | None = None
    encode_s: float | None = None
    sample_s: float | None = None
    decode_s: float | None = None
    total_s: float | None = None
    tail: list[str] = field(default_factory=list)


def _clean(piece: str) -> str:
    piece = piece.replace("\x1b[K", "")
    # ESC replaced by U+FFFD (or dropped) leaves a literal "[K" at the end
    if piece.endswith("[K") and re.search(r"(�|\|\s|s/it|B/s)\[K$", piece):
        piece = piece[:-2].rstrip("�")
    return piece.rstrip()


def split_lines(chunk: str) -> list[str]:
    out = []
    for piece in re.split(r"[\r\n]", chunk):
        piece = _clean(piece)
        if piece:
            out.append(piece)
    return out


class ProgressParser:
    def __init__(self) -> None:
        self._buf = ""
        self._s = ParseState()
        self._seen_gpu = False
        self._last_k = 0

    @property
    def state(self) -> ParseState:
        return self._s

    def feed(self, text: str) -> list[tuple[str, int, int]]:
        data = self._buf + text
        # keep the incomplete trailing piece (after the last \r or \n) for the next call
        cut = max(data.rfind("\r"), data.rfind("\n"))
        # sd-cli ends each progress bar with ESC[K and no newline: that is a complete line
        k = data.rfind("\x1b[K")
        if k >= 0 and k + 3 > cut + 1:
            cut = k + 2
        if cut < 0:
            self._buf = data
            return []
        self._buf = data[cut + 1:]
        events: list[tuple[str, int, int]] = []
        for line in split_lines(data[: cut + 1]):
            self._line(line, events)
        return events

    def _flag(self, cls: str) -> None:
        s = self._s
        if cls == "gpu_oom":
            s.failure_class = "gpu_oom"
        elif s.failure_class is None:
            s.failure_class = cls

    def _line(self, raw: str, events: list) -> None:
        s = self._s
        line = raw.lstrip(" ")
        s.tail.append(raw)
        if len(s.tail) > TAIL_MAX:
            del s.tail[: len(s.tail) - TAIL_MAX]

        if GPU_OOM.search(line):
            self._flag("gpu_oom")
        elif RAM_OOM.search(line):
            self._flag("ram_oom")
        elif NOMODEL.search(line):
            self._flag("no_model")

        if LOADBAR.match(line):
            return
        m = BAR.match(line)
        if m:
            if s.phase == "denoising":
                k, n = int(m["k"]), int(m["n"])
                if k != self._last_k:
                    self._last_k = k
                    s.step, s.step_total = k, n
                    events.append(("denoising", k, n))
            return
        if GENSTART.match(line):
            s.phase = "denoising"
            self._last_k = 0
            return
        if (m := ENCODED.match(line)):
            s.encode_s = float(m["s"])
        elif (m := SAMPLED.match(line)):
            s.sample_s = float(m["s"])
            s.phase = "decoding"
            events.append(("decoding", s.step_total, s.step_total))
        elif (m := DECODED.match(line)):
            s.decode_s = float(m["s"])
        elif (m := DONE.match(line)):
            s.total_s = float(m["s"])
        elif (m := SAVED.match(line)):
            s.saved_path = m["path"]
            s.saved_ok = m["ok"] == "success"
            s.phase = "done"


# NT statuses that mean memory exhaustion
_NT_OOM = {0xC0000017, 0xC000012D}  # STATUS_NO_MEMORY, STATUS_COMMITMENT_LIMIT

# Known NT crash statuses, named for the plain-language message
NT_CRASH_NAMES = {0xC0000005: "access violation", 0xC00000FD: "stack overflow",
                  0xC0000409: "stack buffer overrun", 0xC000001D: "illegal instruction",
                  0xC0000135: "a required program library (DLL) was not found",
                  0xC000007B: "a program file is damaged or for the wrong system"}


def classify_failure(returncode: int | None, state: ParseState) -> tuple[str, str, str]:
    cls = state.failure_class
    if cls is None and returncode is not None and (
            returncode == -9 or (returncode & 0xFFFFFFFF) in _NT_OOM):
        cls = "ram_oom"  # POSIX SIGKILL (the OOM killer) or a known out-of-memory NT status
    if cls == "gpu_oom":
        return (cls, "The graphics chip ran out of memory.",
                "Using the processor instead; this is slower but works.")
    if cls == "ram_oom":
        return (cls, "The computer ran out of memory while making the image.",
                "Close other programs (browser, Teams), pick the 512x512 draft size, then try again.")
    if cls == "no_model":
        return (cls, "A model file is missing or damaged.",
                "Run setup again; it re-downloads only what is missing.")
    cause = f"The image program stopped with code {returncode}."
    if returncode is not None and (returncode < 0 or returncode >= 0xC0000000):
        code = returncode & 0xFFFFFFFF
        name = NT_CRASH_NAMES.get(code)
        cause = f"The image program crashed (code 0x{code:08X}" + (f", {name})." if name else ")."
)
    for line in reversed(state.tail):
        m = _ERRLINE.match(line)
        if m:
            cause += " " + m["msg"].rstrip()
            break
    return ("unknown", cause,
            "Try again; if it repeats, run `assess --json` and send the output to the project owner.")
