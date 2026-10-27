# VERIFICATION_SDCPP.md — stable-diffusion.cpp engine (branch `feat/sdcpp-engine`)

Verifier (Opus), 2026-10-27, second pass (re-verification after the F1/F2 fixes). Machine: Apple M2 Pro,
16 GB RAM, macOS 27.0.1, 17.3 GB free disk. Each check below gives the exact command and an output
excerpt. No product code was changed and nothing was committed.

**Overall: PASS. All 9 criteria in PLAN_SDCPP.md section 6 pass.** The two failures from the first pass
are fixed:
- 7.6 Return to mflux now works on the first `setup --engine auto` run.
- The step bar now shows each step when it happens (F2).

One 512x512 image at 8 steps takes **about 70-75 s** on Metal through the app. 5 minor findings remain
(below); none blocks the merge.

## Summary

| # | Criterion (PLAN_SDCPP.md section 6) | Result |
|---|---|---|
| 1 | Contract tests (argv, parser on field logs, cancel, failure texts, fallback) | PASS (92 passed) |
| 2 | Routing: field laptop → sdcpp/cpu/low/5.0; RTX 4070, M2 Pro, Intel Mac unchanged | PASS |
| 3 | Setup can resume (World tests + real second run prints "already done") | PASS |
| 4 | API flow with the fake sd-cli; CI workflow valid; `uv run pytest -q` green | PASS locally (windows-latest not run here) |
| 5 | All tests green (≥ 417 + new); no binaries/models tracked | PASS (599 passed) |
| 6 | Docs accurate; README table; licence rows | PASS |
| 7.1 | Real `./setup.command --engine sdcpp` | PASS |
| 7.2 | UI: local only, device label, Steps 8, first preset 512x512 draft | PASS (checked over HTTP, not in a browser) |
| 7.3 | Sheet upload → 1 image at 512x512 → PNG + sidecar + row done + gallery + actuals; step bar moves | PASS (**F2 fixed**) |
| 7.4 | Cancel mid-image → row pending, no file, sd-cli gone < 5 s | PASS (0.15 s) |
| 7.5 | Timings, peak RSS, device, 1024 warning | PASS (recorded below) |
| 7.6 | Switch back to mflux | **PASS on the first run (F1 fixed)** |
| 8 | No network at runtime | PASS (server run in a macOS sandbox that blocks all internet traffic) |
| 9 | Adults-only gate does not depend on the engine | PASS |
| — | Downloads ≤ 6 GB | PASS: 0 bytes this pass (reused); 5.59 GB in the first pass |
| — | mflux and diffusers paths unchanged | PASS |

## Status of earlier findings

| ID | First pass | Now |
|---|---|---|
| F1 `setup --engine auto` kept sdcpp | BUG | **Fixed.** Smoke and assess now receive `"auto"` (`medimg/setup_cmd.py:118`). New test `tests/test_setup_cmd.py::test_auto_engine_passed_to_smoke_and_assess`. On the real run, the first `--engine auto` gave mflux (7.6). |
| F2 step bar one step late | BUG | **Fixed.** The parser now treats `ESC[K` as the end of a line (`medimg/sdcpp/progress.py:75-80`). New test `test_bar_reported_without_waiting_for_next_cr`. Live `/api/status` showed steps 1 to 7 about 6.3 s apart (7.3). |
| F3 a SHA256 check that was stopped is never repeated | minor | Unchanged (not re-tested; nothing was interrupted). |
| F4 `setup.command`'s plain `uv sync` removes the mac extra | minor | Unchanged. Seen again: the sdcpp setup removed 39 packages, and `--engine auto` put them back (`Installed 39 packages in 823ms`). |
| F5 assess report says "9 steps" and uses the mflux size table for sdcpp | minor | Unchanged (see 7.1 output). |
| F6 `.gitignore` does not cover `sd-cli`, `*.zip`, `*.dll`, `*.dylib` | minor | Unchanged. Low risk: the program is installed outside the repo. |
| F7 setup does not print the `sd-cli --version` line when the download is skipped | minor | Unchanged. Checked by hand: `stable-diffusion.cpp version unknown, commit e41fbcf`. |
| F8 (new) test image counted as done for the wrong engine | minor | After the switch to mflux, step 4 printed `✔ already done` because `_smoke_done` only checks for any PNG in `_smoke/` (`medimg/setup_cmd.py:70-72`). So no mflux test image was made. The mflux benchmark in step 5 did run (20.5 s for 512x512 at 4 steps), so mflux was still exercised. |
| F9 (new) empty temp folders left behind | minor | Two empty folders, `$TMPDIR/medimg-sdcpp-1cuz33f0` (06:33) and `medimg-sdcpp-ui3u4gkp` (06:04), are left from the **first** pass. That pass was stopped by hand during setup. This pass left none, including after the cancel. |

---

## Evidence

### 1. Contract tests — PASS
```
$ uv run --no-sync pytest -q tests/test_sdcpp_*.py tests/test_api_sdcpp.py
92 passed, 1 warning in 3.14s
```
The fixtures are verbatim copies of the field logs. Every line was found in `result*.txt`:
```
cpu_success_512_8steps.log 75 lines; not found verbatim in field logs: 0
vulkan_oom_diffusion_te_cpu.log 78 lines; not found verbatim in field logs: 0
vulkan_oom_text_encoder.log 76 lines; not found verbatim in field logs: 0
```

### 2. Routing — PASS
`uv run --no-sync python /tmp/medimg-verify2/scripts/route.py`:
```
field laptop: backend=sdcpp supported=True device=cpu tier=low download_gb=5.0 unload=False | No NVIDIA GPU found. Using stable-diffusion.cpp (sd.cpp) instead: on the processor, tier low (under 12 GB RAM)
RTX 4070: backend=diffusers supported=True ... | NVIDIA NVIDIA GeForce RTX 4070 with 12 GB VRAM: gguf_q8_offload mode (experimental, quantized model)
M2 Pro: backend=mflux supported=True ... | Apple silicon with 16 GB (model already downloaded)
Intel Mac: backend=None supported=False ... | Intel Mac: Apple-silicon only.
M2 Pro engine=sdcpp: ('sdcpp', 'metal', 'mid', 5.56)
RTX 4070 engine=sdcpp: ('sdcpp', 'vulkan0', 'high')
```

### 3. Setup can resume — PASS
The fake-machine tests are in `tests/test_setup_cmd.py` and `tests/test_download.py`:
`uv run --no-sync pytest -q tests/test_docs_commands.py tests/test_ci_workflow.py tests/test_assess_decide.py tests/test_setup_cmd.py tests/test_download.py`
→ `125 passed`. Real second run, `yes | ./setup.command --engine sdcpp` → rc=0:
```
  Disk check: ✔ already done (model weights are already downloaded)
[2/6] ✔ already done (no extra Python packages needed)
[3/6] ✔ already done
[4/6] ✔ already done
[5/6] ✔ already done
[6/6] Done
```

### 4. CI workflow and tests without the mac extra — PASS locally
```
$ uv run --no-sync python -c "import yaml; ... .github/workflows/tests.yml"
['pytest'] {'fail-fast': False, 'matrix': {'os': ['ubuntu-latest', 'windows-latest']}} ['actions/checkout@v4', 'astral-sh/setup-uv@v5', 'uv sync', 'uv run pytest -q']
```
`tests/test_ci_workflow.py` passes. The fake-`sd-cli` API flow, including `test_cancel_mid_batch_kills_child`,
is in `tests/test_api_sdcpp.py`, which runs in the CI matrix. The windows-latest job was not run on this Mac.

### 5. Full suite and git hygiene — PASS
```
$ uv run pytest -q            → 599 passed, 1 warning in 8.12s    (before the real run)
$ uv run --no-sync pytest -q  → 599 passed, 1 warning in 8.20s    (after, mac extra reinstalled)
$ git ls-files | grep -E '\.(gguf|safetensors|png|xlsx|zip|exe|dll|dylib)$|device_profile|sd-cli'
templates/image_prompts_sample.xlsx
templates/image_prompts_template.xlsx
$ git status --porcelain --untracked-files=all | grep -E '\.(gguf|safetensors|png|jpg|xlsx|zip|exe|dll|dylib|json)$|sd-cli'
(nothing)
$ git check-ignore -v device_profile.json x.gguf x.safetensors x.png out.xlsx "agent workflows/x"
.gitignore:5:device_profile.json   .gitignore:14:*.gguf   .gitignore:13:*.safetensors
.gitignore:6:*.png   .gitignore:10:*.xlsx   .gitignore:46:/agent workflows/
NOT IGNORED: sd-cli sd-cli.exe x.zip x.dll x.dylib   (F6)
$ git status --porcelain | grep -v -E "^( M|\?\?) "   → nothing staged
```
The only `.gitignore` change is `!tests/fixtures/sdcpp/*.log`, which keeps the field-log fixtures.

### 6. Docs — PASS
- `tests/test_docs_commands.py` passes.
- The README requirements table has the column "Windows/Linux without NVIDIA": 8 GB RAM minimum,
  10-12 GB disk, "slow: 5-6 min per 512x512 draft on a 2021 laptop CPU".
- SAFETY_AND_LICENCES lists:
  - sd.cpp (MIT) and ggml (MIT);
  - `leejet/Z-Image-Turbo-GGUF`, `unsloth/Qwen3-4B-Instruct-2507-GGUF` and `Comfy-Org/z_image_turbo` (Apache-2.0);
  - the "check ... before commercial use" sentence.
- TROUBLESHOOTING has rows for: the graphics chip running out of memory, sd-cli not installed, very
  slow (processor-only), and SmartScreen/Gatekeeper.
- HARDWARE_ALTERNATIVES section 2 says "built in v0.2 (sdcpp engine)".
- ARCHITECTURE lists `sdcpp_engine.py` and `medimg/sdcpp/`. FUTURE covers sd-server.
- Jargon check:
  `grep -i -w -E "subprocess|argv|regex|parser|DLL|stdout|stderr|JSON|API|CLI" docs/SETUP_WINDOWS_SDCPP.md`
  finds only the ordinary word "path". The setup output on this Mac matched the doc's description of
  the steps that are the same on every system.

### 7. Real end-to-end run on this Mac
Scratch output root: `~/.medical-image-gen/config.json` = `{"output_root": "/tmp/medimg-verify2/out"}`.
The file was deleted afterwards, as was `device_profile.json`; neither existed before this pass.
The program and models from the first pass were reused, so nothing was downloaded.

**7.1 Setup — PASS.** `yes | ./setup.command --engine sdcpp` → rc=0:
```
[1/6] Darwin 27.0.0, Apple M2 Pro, 16 GB RAM, 17.3 GB free disk, Python 3.12.13
  Backend: sdcpp. Darwin: sd.cpp on the Apple graphics chip (Metal), tier mid (12-24 GB RAM)
  Engine: sdcpp (mac-arm64), model size tier 'mid'.
[2/6] ✔ already done (no extra Python packages needed)
[3/6] ✔ already done
[4/6] Loading the model (sdcpp on metal)... step 1/4 .. step 4/4
      Test image done: load 0.0 s, generate 51.9 s (512x512, 4 steps).
      Saved to: /tmp/medimg-verify2/out/_smoke/20261027-065946.png
[5/6] Supported: yes. Backend sdcpp on metal (tier mid: Q3_K image model).
      Benchmark: model load 0.0s; 512x512 @ 4 steps = 47.0s; 768x768 @ 2 steps = 63.8s
      Estimated time at 9 steps / 1024x1024 5m 38s ...     ← F5
[6/6] Setup finished.
```
- `device_profile.json` backend: `{"name": "sdcpp", "device": "metal", "engine_version": "sdcpp master-1015-e41fbcf", "sdcpp": {"release": "master-1015-e41fbcf", "build": "mac-arm64", "tier": "mid", ...}}`.
- `~/.medical-image-gen/tools/sdcpp/master-1015-e41fbcf/mac-arm64/sd-cli --version` → `stable-diffusion.cpp version unknown, commit e41fbcf`.
- The model SHA256 values were checked in the first pass and match PLAN 2.2. The HF cache blob names are those SHA256 values:
  - `4b44bdaa…232980` z_image_turbo-Q3_K.gguf
  - `9c6e0763…1806c9` Qwen3-4B-Instruct-2507-Q3_K_M.gguf
  - `afc8e282…529e38` ae.safetensors

**7.2 UI — PASS (over HTTP).** `./start.command --no-browser`.
- Server log: `Serving on http://127.0.0.1:8750 (local only)`.
- `lsof -nP -iTCP:8750 -sTCP:LISTEN` → `TCP 127.0.0.1:8750 (LISTEN)` only.
- `/api/config`: `{'backend': 'sdcpp', 'model_id': 'leejet/Z-Image-Turbo-GGUF/z_image_turbo-Q3_K.gguf',
  'local_only': True, 'warn_over_s': 900, 'device': 'metal', 'steps_hint': '8 recommended for this engine'}`;
  `defaults.steps 8`; `size_presets[0] {'label': '512x512 draft', 'width': 512, 'height': 512}`.
- Page `/`: contains "local only" and the ids `st-device`, `s-warn`, `b-warn` and `s-steps-hint`.
- `/api/status` model `{'state': 'not_loaded'}` at start.
- `/api/device.unverified` was `True` before the first image and `False` after it.

**7.3 Sheet → 1 image at 512x512 — PASS.**
1. Uploaded `templates/image_prompts_sample.xlsx` over HTTP with the `X-Medimg: 1` header:
   `200 counts {total 3, pending 3, blocked 0} suggested_batch 3`.
2. Every sample row sets its own size (1024x1024, 1344x768, 768x1344), and a row's own size overrides the
   default. To get 512x512, I uploaded a scratch copy (`/tmp/medimg-verify2/sheet512/`) with the Size
   column cleared. The repo template was not changed.
```
POST /api/jobs/batch {"count":1,"default_size":"512x512","steps":8} → 202 rows [2]
(0.0 encoding 0/8) (21.9 denoising 1/8) (28.2 2/8) (34.8 3/8) (41.1 4/8) (47.7 5/8) (54.0 6/8) (60.7 7/8) (67.0 decoding 8/8)
wall 75.6 s; last_job outcome "done"
```
Before the fix, 1/8 showed at 72 s on a 1024 run, and 7/8 and 8/8 never showed. Now each step shows
6.3-6.6 s after the one before. The step-8 bar and "sampling completed" come out of `sd-cli` at the same
moment, so the status goes straight from 7/8 to "decoding 8/8".
The same holds when real `sd-cli` output is replayed into the parser one bar at a time: each `k/8`
event fires on its own bar, not the next one.

- File: `/tmp/medimg-verify2/out/Anatomy/Upper limb/Hand/hand_xray_adult.png`, 512x512 RGB, plus a `.json` file.
  It is a recognisable X-ray-style hand. The labels are nonsense text and the anatomy is a draft, as expected.
- Sidecar: `engine "sdcpp master-1015-e41fbcf"`, `model_id "leejet/Z-Image-Turbo-GGUF/z_image_turbo-Q3_K.gguf"`,
  `512x512`, `steps 8`, `seed 545689545`, `time_s 75.234`, `peak_mem_gb 6.694`.
- Sheet row: `hand_xray_adult | done | 545689545 | 8 | 2026-10-27T07:05:48 | Adinaths-MacBook-Pro.local · Apple M2 Pro | …Q3_K.gguf | 75.23 | Anatomy/Upper limb/Hand/hand_xray_adult.png`.
- `/api/gallery/images` lists `Anatomy/Upper limb/Hand/hand_xray_adult.png`.
- The profile `actuals` is `[{width 512, height 512, steps 8, time_s 75.234}]`.

**7.4 Cancel — PASS.**
```
POST /api/jobs/batch count 1 → rows [3] (knee_exam_adult); denoising 1/8 seen at 22.1 s; pgrep -x sd-cli: ['43167']
POST /api/jobs/cancel → {'cancelled': True};  sd-cli gone after 0.15 s;  last_job outcome "cancelled"
sheet row 3: knee_exam_adult | pending | (no seed/time/path);  find out -name 'knee*' → nothing
```
This pass created no new `medimg-sdcpp-*` temp folder (F9 covers the old ones).

**7.5 Timings: 512x512 at 8 steps takes 70-75 s per image on Metal.**

| Run | Size, steps | Time | Breakdown (`sd-cli` log) | Peak RSS |
|---|---|---|---|---|
| Sheet row (batch) | 512x512, 8 | **75.2 s** (sidecar) | — | 6.69 GB |
| Single tab, network blocked (8) | 512x512, 8 | **70.4 s** (sidecar) | — | 6.72 GB |
| Direct `sd-cli`, same flags as the app (`--backend metal --offload-to-cpu --mmap --vae-tiling`) | 512x512, 8 | 71.7 s wall | encode 2.76 s · sample 59.59 s (first step 16.1 s, then 6.20 s/step) · decode 8.50 s · total 70.86 s | — |
| Setup test image | 512x512, 4 | 51.9 s | — | — |

- Device: metal, with no fallback.
- `/api/device` estimates 1024x1024 at **301.8 s**. That is under `warn_over_s = 900`, so the
  15-minute warning correctly does not show on Metal. The processor-only case was not run on real
  hardware. It is covered by the API tests and the warning logic in `app.js`.

**7.6 Back to mflux — PASS on the first run (F1 fixed).** `yes | ./setup.command --engine auto` → rc=0:
```
Installed 39 packages in 823ms
[1/6]   Backend: mflux. Apple silicon with 16 GB (model already downloaded)
[4/6]   ✔ already done          ← F8
[5/6] Supported: yes. Backend mflux. ... Benchmark: model load 13.8s; 512x512 @ 4 steps = 20.5s; 1024x1024 @ 2 steps = 44.9s
[6/6] Setup finished.
profile: mflux None filipstrand/Z-Image-Turbo-mflux-4bit mflux 0.22.0 None
config.json: "engine": null
./start.command --no-browser → /api/config: backend mflux model filipstrand/Z-Image-Turbo-mflux-4bit steps 9 preset0 1024x1024 warn_over_s None device None
```

### 8. No network at runtime — PASS
This time the network was blocked for real, not only watched. The server and its child processes ran
inside a macOS sandbox (`/tmp/medimg-verify2/nonet.sb`): `(allow default) (deny network-outbound)`, with
an exception only for `localhost` and local Unix sockets.

Control test that the sandbox works:
```
$ sandbox-exec -f nonet.sb curl https://huggingface.co/  → curl: (7) Failed to connect ... Couldn't connect to server
$ curl https://huggingface.co/  (outside)                 → 200
```
Run: `sandbox-exec -f /tmp/medimg-verify2/nonet.sb uv run --no-sync python -m medimg serve --no-browser`
(`serve` sets `HF_HUB_OFFLINE=1`).
```
POST /api/jobs/single (45-year-old adult man, 512x512, 8 steps) → 202
(0.0 encoding) (17.2 denoising 1/8) ... (55.6 7/8) (61.9 decoding 8/8)  wall 70.6 s; outcome "done"
out/Verify/sdcpp/Single/single_20261027_070731_1381248094.png + .json  (engine sdcpp master-1015-e41fbcf, time_s 70.368)
```
In addition, during the normal (not sandboxed) batch run in 7.3, `lsof -nP -a -p <pid> -i` checked the
server and `sd-cli` every second. It found **0** sockets other than 127.0.0.1.

### 9. Adults-only gate — PASS
- Fake-engine test: `test_api_sdcpp.py::test_blocked_prompts_never_start_a_process` passes. It asserts
  that the fake is never started.
- Real server, engine sdcpp on Metal, Single tab:
```
"Clinical photo of a 12-year-old child ..." → 422 "Blocked: the prompt states an age under 18. Images are adults only."  pgrep -x sd-cli: (none)
"Photo of a teenage boy ..."               → 422 "Blocked: 'teenage' suggests a minor. ..."                           pgrep: (none)
"Clinical photo of a newborn baby ..."     → 422 "Blocked: 'newborn' suggests a minor. ..."                           pgrep: (none)
"Clinical photo of a man ..." (no age)     → 422 "Blocked: the prompt does not state an adult. ..."                   pgrep: (none)
/api/status afterwards: job null, last_job still the earlier cancelled job (nothing was submitted)
```
- Sheet path, real server: uploaded a scratch one-row sheet with "Clinical photo of a 10-year-old girl ...":
  - Counts: `{pending 0, blocked 1}`, problem "Blocked: the prompt states an age under 18."
  - `POST /api/jobs/batch` → 400 "There are no pending rows to generate."; `pgrep -x sd-cli` (none).
- The gate runs in `server.py` (`rules.check_prompt`) before `worker.submit` and at sheet validation, so
  it works the same for every engine.

### mflux and diffusers paths unchanged — PASS
- `git diff --stat HEAD -- medimg/engines/` shows only `__init__.py | 31 +++`. That change adds a
  `backend == "sdcpp"` branch after the existing branches and removes nothing.
- `mflux_engine.py`, `diffusers_engine.py`, `base.py` and `fake_engine.py` are unchanged.
- `uv run --no-sync pytest -q tests/test_mflux_engine.py tests/test_diffusers_engine.py` → `27 passed`;
  these test files are unchanged against HEAD.
- The real mflux benchmark ran in 7.6.

## State left on this Mac
- All servers stopped: `lsof -iTCP:8750` shows nothing listening; `ps | grep -E "medimg serve|sd-cli"` shows none.
- `~/.medical-image-gen/config.json` and `device_profile.json` were deleted, which is how this pass found
  them. Run `./setup.command` (or `assess`) to make a profile again.
- The venv has the mac extra (mflux 0.22.0) again, and the suite gives 599 passed.
- Kept for reuse: `~/.medical-image-gen/tools/sdcpp/` (97 MB) and the tier-mid models in the HF cache
  (5.55 GB, shared-blob store under `~/.cache/huggingface/hub/blobs`).
- Scratch: `/tmp/medimg-verify2/` (outputs, logs, sandbox profile, scripts).
