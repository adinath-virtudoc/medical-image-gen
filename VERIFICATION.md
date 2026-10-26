# Verification report (brief section 10)

- Verified commit: `4ced0a0` (HEAD of `main` at verification time), on Adinath's Mac:
  Apple M2 Pro, 16 GB RAM, macOS (Darwin 27.0.0), uv 0.11.29, uv-managed CPython 3.12.13.
- Date: 2026-10-26. Verifier: Opus (fresh context).
- Model weights: `filipstrand/Z-Image-Turbo-mflux-4bit` @ `b3a8f31…` were already in the local
  Hugging Face cache. Setup reused them; nothing was downloaded (`Disk check: ✔ already done`).

## Summary

| # | Criterion | Result |
|---|---|---|
| 1 | Fresh clone: setup → start → upload sample → real image, sidecar, sheet row done | **FAIL** (setup crashes at the smoke step; the rest passes after a scratch-only workaround) |
| 2 | assess report + `device_profile.json`, UI per-size estimates, estimate within ±30% | **PASS** (1024x1024 @ 9: estimate 224.6 s vs measured 174.3 s = +28.9%; marginal) |
| 3 | Mixed sheet: correct counts and per-row reasons; only pending valid rows generate | **PASS** |
| 4 | Handoff: A does 2 of 5, B on a fresh root sees 2 done / 3 pending, only 3 generate | **PASS** |
| 5 | Cancel leaves finished rows done and current row pending; kill + restart resumes | **PASS** |
| 6 | Adults-only gate blocks in batch, single and regenerate | **PASS** |
| 7 | All tests pass locally; CI workflow valid | **PASS** |
| 8 | diffusers engine imports and passes mocked contract tests; docs say unverified | **PASS** |
| 9 | `git ls-files` has no images, weights, profiles or real sheets | **PASS** |
| 10 | README quick start followed word for word, each step worked | **FAIL** (step 2 fails as written) |

### Blocking defect (criteria 1 and 10)

`./setup.command` stops at step 4/6 with:

```
  File ".../mflux/utils/exif_orientation.py", line 11, in <module>
    from PIL._typing import StrOrBytesPath
  File ".../site-packages/PIL/_typing.py", line 8, in <module>
    from numbers import _IntegralLike as IntegralLike
ImportError: cannot import name '_IntegralLike' from 'numbers'
  (/Users/adinath/.local/share/uv/python/cpython-3.12.13-macos-aarch64-none/lib/python3.12/numbers.py)
```

- Cause: `uv.lock` pins `pillow==13.0.0` (uploaded 2026-10-16). Its `PIL/_typing.py` imports
  `numbers._IntegralLike`, which CPython 3.12.13 does not have. mflux imports `PIL._typing` when it
  loads, so every real-model path on a Mac (setup smoke, assess benchmark, serve) fails.
- The same failure reproduces in the main repo's own `.venv`:
  `.venv/bin/python -c "import PIL._typing"` → the same `ImportError`.
- The 415 tests do not catch it: mflux is stubbed, and `from PIL import Image` still works.
- Suggested fix (not applied; the verifier does not change product code): add `"pillow>=12.3,<13"`
  to the base `dependencies` in `pyproject.toml` (mflux needs `>=12.3.0`), run `uv lock`, and add a
  test that imports `PIL._typing` so CI catches this kind of break.
- Workaround used to verify everything else, in the scratch clone only:
  `uv pip install "pillow>=12.3,<13"` (installed 12.3.0), then `uv run --no-sync …` /
  `UV_NO_SYNC=1 ./start.command`, so that `uv run` did not reinstall 13.0.0.

### How the run was isolated

- Scratch clone: `git clone /Users/adinath/Documents/VirtuDoc/medical-image-gen medical-image-gen`
  in the scratchpad. The clone was deleted afterwards.
- `HOME` pointed at a scratch folder, so the default output root (`~/medical-image-gen-output`) and
  `~/.medical-image-gen/config.json` were created in scratch, not in the real home folder.
  `HF_HOME`, `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR` pointed at the real caches, so the model and
  Python were reused, not downloaded again. After the run, `~/.medical-image-gen` and
  `~/medical-image-gen-output` still do not exist.
- The browser was replaced by `curl` against the same HTTP API the page calls (`X-Medimg: 1`
  header, as `static/app.js` sends). `start` was given `--no-browser`.
- FakeEngine checks (criteria 3–6) used a scratch launcher that calls the product's
  `medimg.server.create_app()` with `FakeEngine(step_s=…)`. Only the step delay was slowed so that
  cancel and kill could land mid-batch. Profile and settings paths pointed at scratch.
- Every server was stopped at the end: `pgrep -fl "medimg|fake_server"` → `no servers running`;
  ports 8750–8752 free.

---

## 1. Fresh clone → setup → start → upload sample → real image — FAIL

**Step 1, clone**: `git clone /Users/adinath/Documents/VirtuDoc/medical-image-gen medical-image-gen`
→ `Cloning into 'medical-image-gen'... done.` (0.1 s)

**Step 2, setup as written**: `./setup.command`

```
[1/6] Checking this computer
  Darwin 27.0.0, Apple M2 Pro, 16 GB RAM, 27.5 GB free disk, Python 3.12.13
  Backend: mflux. Apple silicon with 16 GB (model already downloaded)
  Disk check: ✔ already done (model weights are already downloaded)
[2/6] Installing Python packages
  Installing the mac packages (uv sync --extra mac)...
[3/6] Downloading the model
  ✔ already done
[4/6] Making one test image (512x512, 4 steps)
Loading the model (mflux)...
ImportError: cannot import name '_IntegralLike' from 'numbers' (...)
Stopped with an error (code 1). Read the message above.
```

**After the scratch-only Pillow workaround**: `uv run --no-sync python -m medimg setup`

```
[4/6] Making one test image (512x512, 4 steps)
Test image done: load 12.7 s, generate 21.3 s (512x512, 4 steps).
Saved to: <scratch HOME>/medical-image-gen-output/_smoke/20261026-123154.png
[5/6] Measuring this computer's speed
Benchmark: model load 0.5s; 512x512 @ 4 steps = 19.7s; 1024x1024 @ 2 steps = 50.9s
[6/6] Done
  Setup finished. Start the app with:
      ./start.sh   (or double-click start.command)
real 1:48.77
```

Re-run (safe to re-run): steps 1–5 all print `✔ already done`, total 0.5 s.

**Step 3, start**: `UV_NO_SYNC=1 ./start.command --no-browser`

```
Uvicorn running on http://127.0.0.1:8750 (Press CTRL+C to quit)
Serving on http://127.0.0.1:8750 (local only). Press Ctrl+C to stop.
$ lsof -nP -iTCP:8750 -sTCP:LISTEN  →  TCP 127.0.0.1:8750 (LISTEN)
$ curl -s http://127.0.0.1:8750/api/status
{"version":0,"model":{"state":"not_loaded","error":null},"job":null,...,"local_only":true}
```

**Run A: 512x512 at 4 steps, real model, through the sheet.** The upload was a copy of the sample
sheet with row 2's Size set to `512x512`. The sample rows have fixed sizes of 1024x1024, 1344x768
and 768x1344.

```
$ curl -H "X-Medimg: 1" -F file=@sample_512.xlsx http://127.0.0.1:8750/api/sheet
counts {"total":3,"done":0,"pending":3,"blocked":0,"failed":0,"invalid":0}
$ curl ... /api/jobs/batch -d '{"count":1,"steps":4}'   →  {"job_id":"9efc340c8366","rows":[2]}
wall=25s, last_job outcome "done"
Anatomy/Upper limb/Hand/hand_xray_adult.png   PNG image data, 512 x 512
Anatomy/Upper limb/Hand/hand_xray_adult.json  {"seed": 178410139, "steps": 4, "width": 512,
   "time_s": 19.965, "peak_mem_gb": 7.868, "machine": "Adinaths-MacBook-Pro.local · Apple M2 Pro", ...}
PNG tEXt keys: ['medical-image-gen']
```

The image is a plausible X-ray-style hand illustration.

**Run B: the genuine `templates/image_prompts_sample.xlsx`, 1024x1024 at 9 steps.** The output
root was switched to a fresh folder through `PUT /api/settings`.

```
upload → image_prompts_sample.xlsx {'total': 3, 'done': 0, 'pending': 3, ...} []   (README: "Total 3 and Pending 3" ✔)
POST /api/jobs/batch {"count":1}  → rows [2]; status strip: phase denoising, step k/9, image 1 of 1, eta_s
wall=181s
<root>/Anatomy/Upper limb/Hand/hand_xray_adult.png   PNG image data, 1024 x 1024
<root>/Anatomy/Upper limb/Hand/hand_xray_adult.json  seed 897599269, steps 9, time_s 174.263, peak_mem_gb 8.47
Downloaded sheet row 2: Status 'done', Seed Used 897599269, Steps 9, Generated At 2026-10-26T12:37:32+05:30,
  Machine 'Adinaths-MacBook-Pro.local · Apple M2 Pro', Model 'filipstrand/Z-Image-Turbo-mflux-4bit',
  Generation Time (s) 174.26, Output Path 'Anatomy/Upper limb/Hand/hand_xray_adult.png'
Statuses: ['done', 'pending', 'pending']
GET /api/gallery/tree → {"subjects":[{"name":"Anatomy","units":[{"name":"Upper limb","lectures":[{"name":"Hand","count":1}]}]}],...}
```

Deviation: the README says to press Generate, and the default count is `suggested_batch` = 3. The
count was set to 1, as the task asked for one 1024x1024 image.

Verdict: FAIL, because the step as written (`./setup.command`) does not complete. With the Pillow
pin fixed, every other part of the criterion passes (path, sidecar, PNG metadata, sheet row with
seed, time and machine).

## 2. assess, profile, UI estimates, ±30% — PASS

`UV_NO_SYNC=1 ./assess.command --no-benchmark` (rc=0; the benchmark had already run inside setup):

```
DEVICE REPORT
Computer : Darwin 27.0.0 (arm64)   CPU : Apple M2 Pro   Memory : 16.0 GB total
Supported: yes. Backend mflux. Apple silicon with 16 GB (model already downloaded)
Benchmark: model load 0.5s; 512x512 @ 4 steps = 19.7s; 1024x1024 @ 2 steps = 50.9s
Estimated time at 9 steps
Size                     1 image   10 images   25 images   50 images
1024x1024                 3m 45s     37m 26s      1h 33m      3h 07m
768x1344 portrait         3m 40s     ...
768x768 low-memory        1m 54s     18m 56s     47m 20s      1h 34m
```

`device_profile.json` was written with keys `schema_version, created_at, app_version, machine,
backend, benchmark, actuals, notes`.

UI: `GET /api/device` returns `estimates` for all six presets (1024x1024 224.6 s … 768x768 113.6 s).
`static/app.js` `loadDevice()` renders them into `d-table-body`.

Accuracy after the real runs:

| Run | Estimate before the run | Measured (`time_s`) | Error |
|---|---|---|---|
| 512x512 @ 4 | 19.69 s (`/api/sheet/estimate`) | 19.97 s | −1.4% |
| 1024x1024 @ 9 | 224.6 s | 174.3 s (wall 181 s incl. load) | +28.9% (+24% vs wall) |

Both are within ±30%, but the 1024 case is close to the limit. The 1024x1024 @ 2-step benchmark
point (first step 27.6 s) inflates the curve. Rolling accuracy works: after the run, `actuals` holds
both runs, and the 1024x1024 estimate becomes 174.3 s.

## 3. Mixed sheet — PASS

Sheet: 1 done, 2 valid pending, `teen` (minor term), missing prompt, two rows with the same output
path, bad size `abcxdef`, and `9-year-old child`. Uploaded to the FakeEngine server.

```
counts {"total": 9, "done": 1, "pending": 2, "blocked": 2, "failed": 0, "invalid": 4}
row 4  blocked  Blocked: 'teen' suggests a minor. Images are adults only; rephrase.
row 5  invalid  Missing Image Prompt. Fix: fill the cell.
row 6  invalid  Same output path as row 7. Fix: change Image Name.
row 7  invalid  Same output path as row 6. Fix: change Image Name.
row 8  invalid  Size must look like 768x1344
row 10 blocked  Blocked: the prompt states an age under 18. Images are adults only.
POST /api/jobs/batch {"count":10} → {"rows":[3,9]}
PNGs written: Derm/Skin/Burns/pending_ok2.png, Derm/Skin/Rash/pending_ok.png (only these two)
Final counts {'total': 9, 'done': 3, 'pending': 0, 'blocked': 2, 'failed': 0, 'invalid': 4}
```

## 4. Handoff simulation — PASS

```
USER A (root userA): upload 5-row sheet → pending 5; batch count 2 → rows [2,3]; download sheet
  userA/Cardio/Heart/Exam/img_1.png, img_2.png
USER B (fresh root userB, a new server): upload A's sheet →
  {'total': 5, 'done': 2, 'pending': 3, ...} []
  batch count 10 → rows [4,5,6]; PNGs only img_3, img_4, img_5 in userB
  sheet: img_1..img_5 all done; img_1/img_2 keep A's seeds and timestamps
```

## 5. Cancel and kill/restart — PASS

```
CANCEL (FakeEngine 0.3 s/step): batch of 5; at "image 2 of 5 step 3 / 9 img_2"
  second POST /api/jobs/batch → {"error":{"cause":"A job is already running.",...}}   (409)
  POST /api/jobs/cancel → {"cancelled":true}; last_job outcome 'cancelled'
  PNGs: img_1 only. Sheet: img_1 done; img_2..img_5 Status blank (= pending)
KILL -9 during "image 3 img_3 step 3": PNGs img_1, img_2
  restart on the same root, no re-upload: GET /api/sheet → handoff5.xlsx {'done': 2, 'pending': 3}
  batch count 10 → rows [4,5,6]; final sheet: all 5 done
FILE-EXISTS RESUME: img_1.png pre-placed, all-pending sheet uploaded → {'done': 1, 'pending': 4}
PORT IN USE: `python -m medimg serve --fake-engine --port 8751` while 8751 busy →
  "port 8751 in use; run start --port 8752", rc=1
```

Tests that cover the case of a crash between writing the PNG and saving the sheet:
`tests/test_api_resume.py::test_startup_revalidates_after_crash_between_png_and_sheet_write` (passes).

## 6. Adults-only gate — PASS

```
batch:  rows 4 ('teen') and 10 ('9-year-old child') blocked and never generated (see 3)
single: "Photo of a teenage girl ..." → {"error":{"cause":"Blocked: 'teenage' suggests a minor. ..."}}
single: "Photo of a 16-year-old ..."  → "Blocked: the prompt states an age under 18. ..."
single: "Paediatric ward photo ..."    → "Blocked: 'paediatric' suggests a minor. ..."
single: adult control                 → 202 {"job_id":...}
regenerate: a sidecar edited to "Photo of a 12-year-old boy with eczema" →
  {"error":{"cause":"Blocked: the prompt states an age under 18. Images are adults only.",...}}
regenerate: adult control → 202, sheet row 3 updated (done, new seed 2095767793)
```

`medimg/rules.py` imports only `re`. It has no config, environment or file reads, so the rule
cannot be configured.

## 7. Tests and CI — PASS

```
$ uv run --no-sync python -m pytest -q          (main repo)
415 passed, 1 warning in 4.84s
$ git clone … ci-clone && uv sync && uv run pytest -q   (same steps as CI: base deps only)
mflux None torch None diffusers None
415 passed, 1 warning in 5.99s
$ python -c "import yaml; yaml.safe_load(open('.github/workflows/tests.yml'))"
jobs: pytest, matrix os [ubuntu-latest, windows-latest], steps checkout@v4, setup-uv@v5, uv sync, uv run pytest -q
```

`actionlint` is not installed, so the workflow was checked by YAML parse and structure only. The
suite passes even though the real Mac path is broken (see criterion 1).

## 8. diffusers engine — PASS

```
$ python -c "import medimg.engines.diffusers_engine as d, sys; ..."
imported <class 'medimg.engines.diffusers_engine.DiffusersEngine'> torch loaded: False diffusers loaded: False
$ pytest tests/test_diffusers_engine.py tests/test_mflux_engine.py -q  →  27 passed
Only medimg/engines/diffusers_engine.py imports torch/diffusers; only mflux_engine.py imports mflux/mlx.
README.md:15  | Status | Tested | **Unverified on real hardware** (built and tested with mocks only) |
docs/SETUP_WINDOWS_NVIDIA.md:3  > **Unverified on real hardware.** ...
docs/SETUP_LINUX_NVIDIA.md:3    > **Unverified on real hardware.** ...
```

## 9. Repo hygiene — PASS

```
$ git ls-files | grep -Ei '\.(png|jpe?g|webp|gif|bmp|tiff?|safetensors|gguf|ckpt|pt|pth|bin|onnx|npz|xlsx|xlsm)$|device_profile|\.venv|egg-info'
templates/image_prompts_sample.xlsx
templates/image_prompts_template.xlsx
```

Only the two allowed templates match. The template has a header row only; the sample has 3 neutral,
clothed adult rows; both have a "How to fill" sheet. The largest tracked file is `uv.lock` (184 KB).
`.gitignore` covers venvs, `device_profile.json`, images, `*.xlsx` (except the two templates),
weight formats and `.env`.

## 10. README quick start followed word for word — FAIL

| README step | Result |
|---|---|
| 1. Clone | Worked. |
| 2. `./setup.command` | **Failed** at "[4/6] Making one test image" with the Pillow `ImportError` above. The time claim is untested as written; with the workaround, setup took 1 min 49 s (README: "about 5 min"). |
| 3. `./start.command` | Worked (with `UV_NO_SYNC=1` to keep the workaround, and `--no-browser`). Bound to 127.0.0.1:8750; the page contains "local only". |
| 4. Upload sample sheet, Generate | Worked: Total 3, Pending 3, as the README says. |
| 5. Gallery | Worked: the image appears under Anatomy › Upper limb › Hand, saved in `medical-image-gen-output` in the home folder (Run A). 1024x1024 took 2 min 54 s, within the "about 1-4 min" claim. |

---

Note for the orchestrator: during this run `.gitignore` in the main repo was changed by another
process (it gained `/agent workflows/`, mtime 12:39). The verifier did not make that change and did
not commit it.
