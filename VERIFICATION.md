# Verification report (brief section 10)

- Verified commit: `f7bd659` ("Pin pillow<13 so setup smoke test imports on CPython 3.12.13"),
  HEAD of `main` at verification time. This is a full re-verification of criteria 1–10; the
  previous run (at `4ced0a0`) failed 1 and 10 on the Pillow 13 `ImportError`.
- Machine: Adinath's Mac, Apple M2 Pro, 16 GB RAM, Darwin 27.0.0, uv 0.11.29, uv-managed
  CPython 3.12.13. Date: 2026-10-26. Verifier: Opus (fresh context).
- Model weights: `filipstrand/Z-Image-Turbo-mflux-4bit` @ `b3a8f31…` were already in the local
  Hugging Face cache. Setup reused them and downloaded nothing (`[3/6] Downloading the model ✔ already
  done`; the cache's newest blob is still dated Oct 12).

## Summary

| # | Criterion | Result |
|---|---|---|
| 1 | Fresh clone: setup → start → upload sample → real image, sidecar, sheet row done | **PASS** |
| 2 | assess report + `device_profile.json`, UI per-size estimates, estimate within ±30% | **PASS** (1024x1024 @ 9: estimate 185.1 s vs measured 172.6 s = +7.3%) |
| 3 | Mixed sheet: correct counts and per-row reasons; only pending valid rows generate | **PASS** |
| 4 | Handoff: A does 2 of 5, B on a fresh root sees 2 done / 3 pending, only 3 generate | **PASS** |
| 5 | Cancel leaves finished rows done and current row pending; kill + restart resumes | **PASS** |
| 6 | Adults-only gate blocks in batch, single and regenerate | **PASS** |
| 7 | All tests pass locally; CI workflow valid | **PASS** (417 passed; workflow checked by YAML parse, `actionlint` not installed) |
| 8 | diffusers engine imports and passes mocked contract tests; docs say unverified | **PASS** |
| 9 | `git ls-files` has no images, weights, profiles or real sheets | **PASS** |
| 10 | README quick start followed word for word, each step worked | **PASS** (two harness deviations, listed below) |

### How the run was isolated

- Scratch clone: `git clone /Users/adinath/Documents/VirtuDoc/medical-image-gen medical-image-gen`
  in the session scratchpad. A second scratch clone (`ci-clone`, base deps only) ran the CI steps and
  the FakeEngine servers. Both clones were deleted afterwards.
- `HOME` pointed at a scratch folder, so the default output root (`~/medical-image-gen-output`) and
  `~/.medical-image-gen/config.json` were created in scratch. `HF_HOME`, `UV_CACHE_DIR` and
  `UV_PYTHON_INSTALL_DIR` pointed at the real caches, so the model and Python were reused.
  After the run, `/Users/adinath/.medical-image-gen` and `/Users/adinath/medical-image-gen-output`
  do not exist.
- The browser was replaced by `curl` against the same HTTP API the page calls (with the
  `X-Medimg: 1` header that `static/app.js` sends).
- FakeEngine checks (criteria 3–6) used a scratch launcher that calls the product's
  `medimg.server.create_app()` with `FakeEngine(step_s=…)` (0.02–0.3 s per step, so cancel and
  kill could land mid-batch), a scratch output root and a scratch `PROFILE_PATH`.
- Every server was stopped at the end: `pgrep -fl "medimg|fake_server"` → `no servers running`;
  ports 8750–8757 free.

### Deviations from the README (harness only, not product behaviour)

1. `./start.command --no-browser`: the README's `./start.command` opens the default browser; the
   flag stops a real browser tab opening on this Mac, and curl drove the same API instead.
2. Run A (512x512 @ 4 steps) used a copy of the sample sheet with row 2's Size set to `512x512`,
   because the sample rows carry fixed sizes (1024x1024, 1344x768, 768x1344). Run B used the
   genuine `templates/image_prompts_sample.xlsx`. Both runs set the batch count to 1 instead of the
   default suggestion of 3, as the task asked for one image per size.

---

## 1. Fresh clone → setup → start → upload sample → real image — PASS

**Step 1, clone**: `git clone /Users/adinath/Documents/VirtuDoc/medical-image-gen medical-image-gen`

```
Cloning into 'medical-image-gen'...
done.     (0.13 s)
f7bd659 Pin pillow<13 so setup smoke test imports on CPython 3.12.13
```

**Step 2, setup as written**: `./setup.command` (exit code 0, 1 min 39 s)

```
Creating virtual environment at: .venv
 + pillow==12.3.0  ...  + mflux==0.22.0  + mlx==0.32.4 ...
[1/6] Checking this computer
  Darwin 27.0.0, Apple M2 Pro, 16 GB RAM, 25.2 GB free disk, Python 3.12.13
  Backend: mflux. Apple silicon with 16 GB (model already downloaded)
  Disk check: ✔ already done (model weights are already downloaded)
[2/6] Installing Python packages
  Installing the mac packages (uv sync --extra mac)...
[3/6] Downloading the model
  ✔ already done
[4/6] Making one test image (512x512, 4 steps)
Loading the model (mflux)...
100%|██████████| 4/4 [00:18<00:00,  4.67s/it]
Test image done: load 12.5 s, generate 19.9 s (512x512, 4 steps).
Saved to: <scratch HOME>/medical-image-gen-output/_smoke/20261026-124410.png   (PNG 512 x 512)
[5/6] Measuring this computer's speed
DEVICE REPORT ... Benchmark: model load 0.6s; 512x512 @ 4 steps = 18.9s; 1024x1024 @ 2 steps = 42.1s
[6/6] Done
  Setup finished. Start the app with:
      ./start.sh   (or double-click start.command)
./setup.command  7.62s user 18.80s system 26% cpu 1:39.33 total
rc=0
```

The Pillow `ImportError` from the previous run is gone: `.venv/bin/python -c "import mflux, PIL,
PIL._typing"` → `mflux ok, pillow 12.3.0`.

Re-run (safe to re-run): `./setup.command` again → steps 3, 4 and 5 print `✔ already done`;
total 2.9 s.

**Step 3, start**: `./start.command --no-browser`

```
INFO:     Uvicorn running on http://127.0.0.1:8750 (Press CTRL+C to quit)
Serving on http://127.0.0.1:8750 (local only). Press Ctrl+C to stop.
$ lsof -nP -iTCP:8750 -sTCP:LISTEN  →  python3.1 77744 ... TCP 127.0.0.1:8750 (LISTEN)
$ curl -s http://127.0.0.1:8750/api/status
{"version":0,"model":{"state":"not_loaded","error":null},"job":null,"last_job":null,"gallery_version":0,"local_only":true}
$ curl -s http://127.0.0.1:8750/ | grep -io "local only"  →  local only
```

The server was up about 2 s after launch (README: "about 10 seconds").

**Run A: real model, 512x512 at 4 steps, through the sheet**

```
$ curl -H "X-Medimg: 1" -F file=@sample_512.xlsx http://127.0.0.1:8750/api/sheet
{'original_name': 'sample_512.xlsx', 'counts': {'total': 3, 'done': 0, 'pending': 3, 'blocked': 0, 'failed': 0, 'invalid': 0}, 'problems': [], 'suggested_batch': 3}
$ POST /api/sheet/estimate {"count":1,"steps":4}  →  {"count":1,"seconds":18.887328,...}
$ POST /api/jobs/batch {"count":1,"steps":4}       →  {"job_id":"393909c0c57d","rows":[2]}
status strip during the run: model "loading" → "ready"; phase "denoising", step 1..4 / 4,
  image_index 1, image_count 1, eta_s 14.2 → 0.0, current hand_xray_adult row 2
wall=33s; last_job outcome "done"
<root>/Anatomy/Upper limb/Hand/hand_xray_adult.png   PNG image data, 512 x 512, 8-bit/color RGB
<root>/Anatomy/Upper limb/Hand/hand_xray_adult.json  {"seed": 105339243, "steps": 4, "width": 512,
   "height": 512, "model_id": "filipstrand/Z-Image-Turbo-mflux-4bit", "engine": "mflux 0.22.0",
   "time_s": 19.449, "peak_mem_gb": 7.867, "machine": "Adinaths-MacBook-Pro.local · Apple M2 Pro",
   "source": "batch", "sheet": {"name": "sample_512.xlsx", "row": 2}, ...}
PNG tEXt keys ['medical-image-gen']
Downloaded sheet row 2: Status 'done', Seed 105339243 (written back), Seed Used 105339243, Steps 4,
  Generated At 2026-10-26T12:46:35+05:30, Machine 'Adinaths-MacBook-Pro.local · Apple M2 Pro',
  Model 'filipstrand/Z-Image-Turbo-mflux-4bit', Generation Time (s) 19.45,
  Output Path 'Anatomy/Upper limb/Hand/hand_xray_adult.png'; rows 3–4 still 'pending'
```

**Run B: genuine `templates/image_prompts_sample.xlsx`, 1024x1024 at 9 steps (the default).**
The output root was switched to a fresh scratch folder through `PUT /api/settings`.

```
upload → {'original_name': 'image_prompts_sample.xlsx', 'counts': {'total': 3, 'done': 0, 'pending': 3, ...}, 'problems': [], 'suggested_batch': 3}
POST /api/sheet/estimate {"count":1}  →  {"seconds":185.11995757939678}
POST /api/jobs/batch {"count":1}      →  {"job_id":"63a68d44a215","rows":[2]}
status strip: phase denoising, step 1 → 8 / 9, image 1 of 1, eta_s 164.6 → 20.6
wall=174s; last_job outcome "done"
<rootB>/Anatomy/Upper limb/Hand/hand_xray_adult.png   PNG image data, 1024 x 1024, 8-bit/color RGB
<rootB>/Anatomy/Upper limb/Hand/hand_xray_adult.json  seed 2114939414, steps 9, 1024x1024,
   time_s 172.589, peak_mem_gb 8.47, machine 'Adinaths-MacBook-Pro.local · Apple M2 Pro'
Downloaded sheet row 2: Status 'done', Seed Used 2114939414, Steps 9, Generated At 2026-10-26T12:49:47+05:30,
  Machine 'Adinaths-MacBook-Pro.local · Apple M2 Pro', Model 'filipstrand/Z-Image-Turbo-mflux-4bit',
  Generation Time (s) 172.59, Output Path 'Anatomy/Upper limb/Hand/hand_xray_adult.png'
GET /api/gallery/tree → {"subjects":[{"name":"Anatomy","units":[{"name":"Upper limb","lectures":[{"name":"Hand","count":1}]}]}],"single_count":0}
GET /files/<id>.png → 200 image/png;  GET /files/<id>/thumb.jpg → 200 image/jpeg
```

The 1024x1024 image was inspected: a clean X-ray-style illustration of the bones of an adult right
hand and forearm on a white background, as prompted.

## 2. assess, profile, UI estimates, ±30% — PASS

`./assess.command --no-benchmark` (rc=0; the benchmark had already run inside setup), after the
real runs:

```
DEVICE REPORT
Computer : Darwin 27.0.0 (arm64)   CPU : Apple M2 Pro   Memory : 16.0 GB total, 8.3 GB free
GPU      : Apple M2 Pro   Disk : 21.9 GB free at <rootB>   Python : 3.12.13   uv: 0.11.29
Supported: yes. Backend mflux. Apple silicon with 16 GB (model already downloaded)
Benchmark: model load 0.6s; 512x512 @ 4 steps = 18.9s; 1024x1024 @ 2 steps = 42.1s
Actual runs recorded: 2 (the last 10 per size drive the estimates)
Estimated time at 9 steps
Size                     1 image   10 images   25 images   50 images
1024x1024                 2m 53s     28m 46s      1h 11m      2h 23m
768x1344 portrait         2m 50s     28m 19s      1h 10m      2h 21m
...
768x768 low-memory        1m 37s     16m 09s     40m 22s      1h 20m
device_profile.json mtime 12:49:47 → 12:50:08 (rewritten)
```

`device_profile.json` keys: `schema_version, created_at, app_version, machine, backend, benchmark,
actuals, notes`.

UI: `GET /api/device` returns keys `profile, report, estimates, unverified`; `estimates` has all six
presets with `seconds, for_10, for_25, for_50` (before the real runs: 1024x1024 185.1 s,
768x1344 182.0 s, …, 768x768 99.7 s). `static/app.js` `loadDevice()` renders them into
`d-table-body` (lines 411–413).

Accuracy against the real runs:

| Run | Estimate before the run | Measured `time_s` | Error |
|---|---|---|---|
| 512x512 @ 4 | 18.89 s (`/api/sheet/estimate`) | 19.45 s | −2.9% |
| 1024x1024 @ 9 | 185.12 s | 172.59 s (wall 174 s incl. load) | +7.3% (+6.4% vs wall) |

Rolling accuracy: after the runs, `actuals` holds both records
(`{"width": 1024, "height": 1024, "steps": 9, "time_s": 172.589}`, …) and `/api/device` now gives
1024x1024 = 172.6 s.

## 3. Mixed sheet — PASS

Sheet (FakeEngine server): row 2 done, rows 3 and 9 valid pending (row 9 with a blank Status),
row 4 `teen`, row 5 missing prompt, rows 6–7 the same output path, row 8 size `abcxdef`,
row 10 `9-year-old child`.

```
$ curl -H "X-Medimg: 1" -F file=@mixed.xlsx http://127.0.0.1:8751/api/sheet
counts {"total": 9, "done": 1, "pending": 2, "blocked": 2, "failed": 0, "invalid": 4}
row 4  blocked  Blocked: 'teen' suggests a minor. Images are adults only; rephrase.  | fix: Rephrase the prompt to describe an adult.
row 5  invalid  Missing Image Prompt. Fix: fill the cell.
row 6  invalid  Same output path as row 7. Fix: change Image Name.
row 7  invalid  Same output path as row 6. Fix: change Image Name.
row 8  invalid  Size must look like 768x1344
row 10 blocked  Blocked: the prompt states an age under 18. Images are adults only.
$ POST /api/jobs/batch {"count":10}  →  {"job_id":"66cc79ac0c1a","rows":[3,9]}
PNGs written: Derm/Skin/Burns/pending_ok2.png, Derm/Skin/Rash/pending_ok.png (only these two)
Final counts {'total': 9, 'done': 3, 'pending': 0, 'blocked': 2, 'failed': 0, 'invalid': 4}
Downloaded sheet: Error column holds each reason; blocked/invalid statuses written back.
```

## 4. Handoff simulation — PASS

```
USER A (server :8752, root userA): upload handoff5.xlsx → {'total': 5, 'pending': 5, ...}
  POST /api/jobs/batch {"count":2} → rows [2,3]; download sheet
  PNGs: userA/Cardio/Heart/Exam/img_1.png, img_2.png
USER B (new server :8753, fresh root userB): upload A's downloaded sheet →
  {'total': 5, 'done': 2, 'pending': 3, 'blocked': 0, 'failed': 0, 'invalid': 0} []
  POST /api/jobs/batch {"count":10} → rows [4,5,6]
  PNGs: userB/Cardio/Heart/Exam/img_3.png, img_4.png, img_5.png (only these)
  final sheet: img_1..img_5 all done; img_1/img_2 keep A's seeds (225461465, 2055886847) and timestamps
```

## 5. Cancel and kill/restart — PASS

```
CANCEL (FakeEngine 0.3 s/step, batch of 5)
  status at cancel time: job 2 of 5, step 3 / 9, img_2
  second POST /api/jobs/batch → {"error":{"cause":"A job is already running.","fix":"Wait for it to finish or press Cancel."}} HTTP 409
  POST /api/jobs/single while busy → HTTP 409
  POST /api/jobs/cancel → {"cancelled":true}; last_job outcome 'cancelled'
  PNGs: img_1 only. Sheet: img_1 'done'; img_2..img_5 Status blank (= pending)
KILL -9 (status: job 3 of 5, step 4 / 9, img_3) → PNGs img_1, img_2
  restart on the same root, no re-upload: GET /api/sheet → handoff5.xlsx {'total': 5, 'done': 2, 'pending': 3, ...}
  POST /api/jobs/batch {"count":10} → rows [4,5,6]; final sheet: all 5 'done'
FILE-EXISTS RESUME: img_1.png pre-placed at its path, all-pending sheet uploaded → {'done': 1, 'pending': 4}
PORT IN USE: `python -m medimg serve --fake-engine --no-browser --port 8757` with 8757 held →
  rc 1, "port 8757 in use; run start --port 8758"
```

## 6. Adults-only gate — PASS

```
batch:  rows 4 ('teen') and 10 ('9-year-old child') blocked and never generated (see 3)
single: "Photo of a teenage girl with acne"          → 422 Blocked: 'teenage' suggests a minor. ...
single: "Photo of a 16-year-old with a sprained ankle" → 422 Blocked: the prompt states an age under 18. ...
single: "Paediatric ward photo of a rash"            → 422 Blocked: 'paediatric' suggests a minor. ...
single: "Photo of a toddler with a burn"             → 422 Blocked: 'toddler' suggests a minor. ...
single: "Photo of an 18-year-old adult with a sprained ankle" → 202 {"job_id":"f084989cd3cc","rel_path":"_single/..."}
regenerate: sidecar of pending_ok edited to "Photo of a 12-year-old boy with eczema" →
  {"error":{"cause":"Blocked: the prompt states an age under 18. Images are adults only.",...}}
  (sheet row stays done with its old seed 1593220477; no new job)
regenerate: adult control (pending_ok2) → 202 {"seed":478443268,"sheet_row":9}; sheet row 9 Seed Used 478443268
```

`medimg/rules.py` imports only `re` (`grep -n "^import\|^from\|environ\|open(" medimg/rules.py` →
`from __future__ import annotations`, `import re`). It reads no config, environment or file, so the
UI and the sheet cannot change the rule.

## 7. Tests and CI — PASS

```
$ uv run --no-sync python -m pytest -q          (main repo)
417 passed, 1 warning in 4.27s
$ git clone … ci-clone && uv sync && uv run pytest -q   (the CI steps: base deps only)
417 passed, 1 warning in 6.42s
{'mflux': False, 'torch': False, 'diffusers': False, 'mlx': False}   (none installed in ci-clone)
$ python -c "import yaml; yaml.safe_load(open('.github/workflows/tests.yml'))"
name tests; on push + pull_request; jobs.pytest: matrix os [ubuntu-latest, windows-latest],
fail-fast false, steps actions/checkout@v4, astral-sh/setup-uv@v5, `uv sync`, `uv run pytest -q`
```

The suite grew from 415 to 417 with `tests/test_pillow_pin.py` (pyproject and lock pin Pillow < 13).
`actionlint` is not installed, so the workflow was checked by YAML parse and structure only.

## 8. diffusers engine — PASS

```
$ python -c "import sys, medimg.engines.diffusers_engine as d; ..."   (ci-clone, no torch installed)
imported <class 'medimg.engines.diffusers_engine.DiffusersEngine'> torch loaded: False diffusers loaded: False
$ pytest tests/test_diffusers_engine.py tests/test_mflux_engine.py -q  →  27 passed in 0.18s
$ grep -rlE "^\s*(import|from) (torch|diffusers)\b" medimg  →  medimg/engines/diffusers_engine.py
$ grep -rlE "^\s*(import|from) (mflux|mlx)\b" medimg       →  medimg/engines/mflux_engine.py
diffusers_engine.py: ZImagePipeline.from_pretrained(...), guidance_scale=0.0,
  callback_on_step_end=cb, pipe._interrupt = True for cancel
README.md:15  | Status | Tested | **Unverified on real hardware** (built and tested with mocks only) |
docs/SETUP_WINDOWS_NVIDIA.md:3  > **Unverified on real hardware.** This path was built and tested with mock libraries only.
docs/SETUP_LINUX_NVIDIA.md:3    > **Unverified on real hardware.** This path was built and tested with mock libraries only.
```

## 9. Repo hygiene — PASS

```
$ git ls-files | grep -Ei '\.(png|jpe?g|webp|gif|bmp|tiff?|safetensors|gguf|ckpt|pt|pth|bin|onnx|npz|xlsx|xlsm)$|device_profile|\.venv|egg-info|agent workflows'
templates/image_prompts_sample.xlsx
templates/image_prompts_template.xlsx
$ git ls-files | wc -l  →  125;  largest tracked files: uv.lock 165309, PLAN.md 67338, medimg/server.py 31004
```

Only the two allowed templates match. The template has the header row only; the sample has 3
neutral, clothed adult rows (hand X-ray illustration, 52-year-old woman's knee exam in shorts and
t-shirt, 35-year-old man's shoulder diagram in a sleeveless top); both have a "How to fill" sheet.
`.gitignore` covers `.venv/`, `device_profile.json`, `*.png`, `*.xlsx` (except the two templates),
`*.safetensors`, output folders and `.env`.

## 10. README quick start followed word for word — PASS

| README step | Result |
|---|---|
| 1. `git clone … medical-image-gen` then `cd medical-image-gen` | Worked (0.13 s). |
| 2. `./setup.command` | Worked, rc 0, 1 min 39 s (README: "about 5 min" with the model already downloaded). Final message prints the start command. Re-run skips every completed step. |
| 3. `./start.command` | Worked (with `--no-browser`, see Deviations). Bound to `127.0.0.1:8750`; the page contains "local only"; model state `not_loaded` shown in the status API. |
| 4. Upload `templates/image_prompts_sample.xlsx`, press Generate | Worked: Total 3 and Pending 3, exactly as the README says; Generate (`POST /api/jobs/batch`) started the real model. |
| 5. Gallery | Worked: the image appears under Anatomy › Upper limb › Hand in `/api/gallery/tree`, and its PNG and thumbnail are served. Saved under `medical-image-gen-output` in the home folder (Run A). 1024x1024 at 9 steps took 2 min 53 s, inside the README's "about 1-4 min each". |

Minor wording note (not a failure): setup's final message says `./start.sh   (or double-click
start.command)`, while README step 3 says `./start.command`. Both files exist and are identical, so
either command works on a Mac.

---

Notes for the orchestrator:

- The main repo's working tree has an uncommitted `.gitignore` change (adds `/agent workflows/`)
  made by another process before this run. The verifier did not make it and did not commit it.
- `uv sync --extra mac` installs `torch==2.14.1` (CPU wheel) into the clone's venv as a dependency
  of `mflux==0.22.0`. No CUDA build was installed. The clone's venv (1.2 GB) was deleted with the
  clone.
