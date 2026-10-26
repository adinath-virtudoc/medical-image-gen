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
| `medimg/engines/` | `base.py` interface, `mflux_engine.py` (Mac), `diffusers_engine.py` (NVIDIA), `fake_engine.py` (tests) |
| `medimg/assess/` | Detect the machine, choose a backend, benchmark, estimate time, write `device_profile.json` |
| `medimg/jobs.py`, `medimg/worker.py` | Job validation and the single generation thread |
| `medimg/server.py` | FastAPI app on 127.0.0.1; JSON routes under `/api`, images under `/files` |
| `medimg/static/` | The UI: status strip and four tabs (Excel batch, Single image, Gallery, Device) |
| `medimg/setup_cmd.py`, `download.py`, `smoke.py` | One-time setup, model download, real-model test image |

Only `mflux_engine.py` imports `mflux` or `mlx`; only `diffusers_engine.py` imports `torch` or
`diffusers`, and only inside methods. Tests replace both with stubs, so no GPU or weights are needed.

## Engine interface

Defined in `medimg/engines/base.py`:

```python
class Engine(Protocol):
    name: str            # "mflux" | "diffusers" | "fake"
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
