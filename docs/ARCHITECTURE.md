# Architecture

For developers. One Python package (`medimg`) with a FastAPI server, one worker thread and a
vanilla-JS page. No database, no build step, no network at run time.

## Components

| Module | Job |
|---|---|
| `medimg/__main__.py` | Command line: `setup`, `assess`, `serve`, `smoke`. Sets `HF_HUB_OFFLINE=1` for everything except `setup` |
| `medimg/config.py` | Defaults (steps 9, 1024x1024, port 8750), size limits, model ids, settings file |
| `medimg/rules.py` | Adults-only check, `check_prompt(prompt)`. No configuration |
| `medimg/sheet/` | Read, validate and write the Excel sheet (openpyxl), status logic, batch selection |
| `medimg/names.py`, `medimg/store.py` | Safe file names, output folders, PNG plus sidecar JSON, gallery index, thumbnails |
| `medimg/engines/` | `base.py` interface, `mflux_engine.py` (Mac), `diffusers_engine.py` (NVIDIA), `sdcpp_engine.py` (everything else, runs `sd-cli`), `fake_engine.py` (tests) |
| `medimg/sdcpp/` | `pins.py` (release, asset and model SHA256 pins, tiers), `install.py` (download and check the program and models), `progress.py` (parse `sd-cli` output, name failures), `procs.py` (start, kill and measure a child process) |
| `medimg/assess/` | Detect the machine, choose a backend, benchmark, estimate time, write `device_profile.json` |
| `medimg/jobs.py`, `medimg/worker.py` | Job validation and the single generation thread |
| `medimg/server.py` | FastAPI app on 127.0.0.1; JSON routes under `/api`, images under `/files` |
| `medimg/static/` | The UI: status strip and four tabs (Excel batch, Single image, Gallery, Device) |
| `medimg/setup_cmd.py`, `download.py`, `smoke.py` | One-time setup, model download, real-model test image |

Only `mflux_engine.py` imports `mflux` or `mlx`; only `diffusers_engine.py` imports `torch` or
`diffusers`, and only inside methods. Tests replace both with stubs, so no GPU or weights are needed.
`sdcpp_engine.py` imports nothing heavy (`subprocess`, `psutil`, `PIL`); tests drive it with a fake
`sd-cli` script.

## The four engines

```
assess -> decide() -> backend
  Apple silicon Mac ............. mflux      (MLX, in the app process)
  Windows/Linux, NVIDIA >= 7.5 GB  diffusers  (PyTorch + CUDA, in the app process)
  Windows/Linux, anything else .. sdcpp      (sd-cli, one child process per image)
  tests ......................... fake
```

`--engine sdcpp` (on `setup`, `assess`, `serve`, `smoke`) forces the third row on any machine except
an Intel Mac; `setup --engine sdcpp` also saves it in `~/.medical-image-gen/config.json`.

## The sdcpp engine

[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) is a separate C++ program.
The app starts its `sd-cli` executable with the model files and prompt, reads the progress it
prints, and picks up the PNG. Plan and reasons: `PLAN_SDCPP.md` in the repo root.

- **One process per image (S1).** An out-of-memory kill takes down the child, not the app; cancel is
  "kill the process"; progress comes from its output. With `--mmap` a model load takes about 0.2 s,
  so keeping a server process alive would save seconds on a multi-minute image. `sd-server` is the
  upgrade path (see [FUTURE.md](FUTURE.md)).
- **Command line.** `build_argv` in `sdcpp_engine.py` builds it: `--diffusion-model`, `--llm`, `--vae`,
  `--cfg-scale 1.0`, `--steps`, `-W`, `-H`, `-s`, `-o`, `--backend <device>`, `--offload-to-cpu`,
  `--mmap`, `--vae-tiling`, `--log-level info`, plus `--threads` only if the setting is set.
- **Progress (S11).** `ProgressParser` in `progress.py` is pure: it splits output on carriage return
  and newline, follows the phase markers (`generating image`, `sampling completed`, `latent decoded`)
  and reads the `k/n` step bars only while denoising. It emits the same `encoding`, `denoising`,
  `decoding` events as the other engines.
- **Cancel (S12).** `should_cancel()` is checked every 0.25 s, not once per step, because a processor
  step can take 34 s. Cancel kills the whole process tree (`killpg` on Linux and Mac, `taskkill /F /T`
  on Windows). No partial image is left; the engine writes to a temp folder and deletes it.
- **Peak memory (S13).** `MemSampler` reads the child's resident memory every 0.5 s and reports the
  maximum as `peak_mem_gb`. Memory-mapped model pages count, which is what matters on an 8 GB laptop.
- **Graphics-chip out of memory (S14).** If the output shows `ErrorOutOfDeviceMemory` on a non-cpu
  device, the engine switches to `cpu` and runs the image once more. The sidecar `engine` field then
  reads `sdcpp master-1015-e41fbcf (cpu, fallback)`. Other failures become plain-language errors
  (`classify_failure`), shown unchanged in the UI and the sheet's Error column.
- **Where the program lives (S2).** `~/.medical-image-gen/tools/sdcpp/<tag>/<build>/`, for example
  `master-1015-e41fbcf/win-vulkan-x64/`. Never in the repo. Setup downloads the pinned GitHub release
  zip, checks its SHA256 against `pins.py`, and extracts it into an empty folder. `chosen_build.txt`
  in the `<tag>` folder records which build setup settled on (the Vulkan build, or the processor-only
  build when the Vulkan one failed its start-up check). `sd-cli` runs with its build folder as the
  working directory so it loads the right backend DLLs.
- **Models (S5).** Three files by memory tier (low, mid, high; see
  [HARDWARE_ALTERNATIVES.md](HARDWARE_ALTERNATIVES.md)) come through `huggingface_hub` into the normal
  cache, then setup checks each SHA256.
- **Assess routing (S6, S9).** `decide()` sends Windows and Linux machines without a qualifying NVIDIA
  card to `sdcpp`. The device is `cpu` by default; `vulkan0` is only tried first on AMD, on Intel with
  16 GB RAM or more, and on NVIDIA when forced. `assess` benchmarks the candidate device and falls back
  to `cpu` if it fails. Below 7 GB RAM the machine is unsupported.
- **Profile keys (S10).** `device_profile.json` stays schema 1. `backend` gains `device` (`cpu`,
  `vulkan0`, `metal` or null), `sdcpp` (`release`, `build`, `tier`, `vulkan_tried`, `vulkan_error`, or
  null), and `engine_version` reads `sdcpp <tag>`.
- **Offline at run time (S15).** Model paths resolve with `local_files_only=True`, the binary is a
  plain file, and `sd-cli` makes no network calls. Only setup downloads.
- **Adults-only gate unchanged.** `rules.check_prompt` runs in the server and worker before any engine
  is called, so `sdcpp` gets exactly the same protection as the others. It does not depend on the engine.

## Engine interface

Defined in `medimg/engines/base.py`:

```python
class Engine(Protocol):
    name: str            # "mflux" | "diffusers" | "sdcpp" | "fake"
    model_id: str
    loaded: bool
    def load(self, on_progress=None) -> None: ...
    def unload(self) -> None: ...
    def generate(self, prompt, seed, steps, width, height,
                 on_progress, should_cancel) -> GenResult: ...
```

`GenResult` holds the PIL image, seed, wall time, peak memory (GB), steps, engine string and model id.
Rules every engine follows:

1. `generate` raises `RuntimeError("engine not loaded")` if not loaded.
2. Progress calls: `("encoding", 0, 0)`, then `("denoising", k, steps)` for each step, then `("decoding", steps, steps)`.
3. `should_cancel()` is polled at least once per step; if true, raise `Cancelled` and return no image.
4. Width and height arrive already rounded to multiples of 16 and are passed through unchanged.
5. Scratch memory is released after every call, success or failure.
6. `load` and `unload` can be called twice safely.

Always pass `num_inference_steps` explicitly. Z-Image Turbo uses guidance 0 and no negative prompt.

## Data flow

1. **Upload**: the server copies the `.xlsx` into `<output root>/_sheets/`, reads the rows, and
   validates each one: required cells, size, path length, adults-only check, duplicate output paths,
   and "image already exists" (marked done). Results are written to the copy with their reasons.
2. **Start batch**: the server picks the first N pending rows (after the optional filter) and submits
   a job. A second job while one runs returns 409.
3. **Worker**: for each row it checks the rules again, calls `engine.generate`, then saves the PNG,
   then the sidecar JSON, then updates the sheet row (atomic temp file and replace), then records the
   actual time in `device_profile.json`. A crash between PNG and sheet row is repaired on the next upload.
4. **Progress**: the page polls `GET /api/status` every 0.5 s and reloads the Gallery when the gallery
   version changes.
5. **Download**: the server returns the working sheet as bytes.

Output layout: `<root>/<Subject>/<Unit>/<Lecture>/<Image Name>.png` plus `<Image Name>.json`.
Single images without a folder go to `<root>/_single/`.

## Adding a model or engine

1. Create `medimg/engines/<name>_engine.py` with a class that follows the interface above. Import the
   heavy library inside `load` and `generate`, never at the top of the file.
2. Register it in `make_engine` in `medimg/engines/__init__.py`.
3. Teach `medimg/assess/decide.py` when to choose it (platform, memory, the model id and download size).
4. Add download logic to `medimg/download.py` and the setup step in `setup_cmd.py` if the weights differ.
5. Add stubs under `tests/stubs/` and a contract test that checks the exact call arguments, as the
   existing `tests/test_mflux_engine.py` and `tests/test_diffusers_engine.py` do.
6. Update the setup guide, [SAFETY_AND_LICENCES.md](SAFETY_AND_LICENCES.md) (licence) and this file.

Adding a new model for an existing engine usually means changing only the model id in `config.py`
and the licence table.

## Device profile

`device_profile.json` (repo root, not committed) holds the machine description, the backend decision,
the benchmark points and recent actual times. Its keys are stable so later tools can read it (see
[FUTURE.md](FUTURE.md)).

## Tests

```sh
uv run --no-sync pytest -q
```
