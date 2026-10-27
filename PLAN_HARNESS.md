# PLAN_HARNESS.md — fix the 10 review findings, and build a real-hardware test harness

Branch `feat/sdcpp-engine` (base commit `6508d28`). Planner: Opus. Workers: Sonnet. Verifier: Sonnet.
Original brief rules still apply: 127.0.0.1 only, no network at run time (only `setup` downloads),
adults-only gate server-side on every generation path, docs for non-developers, no LLM or paid API in
the product.

**Why this run exists.** Today a real-hardware test is a manual loop: Adinath edits a `.bat`, the intern
runs it, sends `result.txt`, Adinath edits again. This plan replaces that loop with three things that
produce the same evidence without a human in the middle:

1. `python -m medimg selftest` (double-click `selftest.command` / `selftest.bat`): one tiny real image
   per engine and tier on this computer, one plain-text + JSON report.
2. A GitHub Actions **real run** (`real-run.yml`): weekly + on demand, Windows and Ubuntu, sd.cpp on
   the processor, low tier, full end-to-end through the HTTP API, then the self-test.
3. A **self-hosted** job in the same workflow that runs the same checks on a real intern laptop that
   has been registered as a runner (documented, not registered by us).

---

## 0. Hard rules for every worker

- **Git:** never run `git stash`, `git checkout`, `git reset`, `git restore`, `git clean` or
  `git commit`. Read-only git (`status`, `diff`, `log`, `show`, `archive`) is fine. Only the Commit
  phase commits.
- **Ownership:** edit only the files your task owns (section 5). Never touch `agent workflows/`.
  Never modify anything outside the repo except scratch/tmp and the app's own model/output folders.
  If you need a change in a file you do not own, stop and report it; do not edit it.
- **No downloads over 1 GB.** The sd.cpp `mid` tier, the `mac-arm64` sd-cli and the mflux weights are
  already on this Mac. Do not push, do not open PRs, do not register runners.
- **Tests:** `uv run --no-sync pytest -q` must stay green (599 passed at base). Every finding fix comes
  with a regression test that fails on the base code and passes after (the Verifier proves this with
  `git archive 6508d28`, see 7.2).
- Python via `uv run --no-sync` from `/Users/adinath/Documents/VirtuDoc/medical-image-gen`.
- Plain language in every user-facing message and doc ("graphics chip", "processor", not "GPU
  backend" or "ggml").

---

## 1. Part A — verdicts on the 10 review findings

Every finding was read in the code at `6508d28`; 1, 2, 3 and 5 were also reproduced by running code
(scratch script and a scratch test reusing `tests/test_assess_run_sdcpp.py`'s `env` fixture).

| # | Verdict | Evidence | Fix (task) |
|---|---|---|---|
| 1 | **Confirmed** | `decide.py:118-127` falls back to `_sdcpp(m)` for any unsupported Windows/Linux machine; `_sdcpp` (`:84`) never asks `pins.build_for`. Reproduced: `decide(Machine(os_name="Linux", arch="aarch64", gpu=None, ram=16))` → `supported=True, backend="sdcpp"` while `pins.build_for("Linux","aarch64") is None`; same for `Windows/arm64`. Every later `make_engine` raises `ModelUnavailable`. | `_sdcpp` returns unsupported, `reason_code="no_build"`, when `pins.build_for(os, arch)` is None (H1). |
| 2 | **Confirmed** (one sub-claim refuted) | `assess/__init__.py:119-121` keeps the old benchmark only if `prev device == settings.sdcpp_device or decision.device`. After a Vulkan→CPU fallback the saved device is `cpu`, the decided one `vulkan0`, so `keep` is False forever. Reproduced: `assess` (Vulkan fails) → profile `cpu` + benchmark; then `assess --no-benchmark` → profile `device="vulkan0"`, `benchmark=None`, `actuals=[]`. The server then spawns sd-cli on the GPU that already failed. **Refuted sub-claim:** "setup's `_assess_done` always False" — `_assess_done` does not compare the device with the decision (only with `settings.sdcpp_device`), so after a plain fallback it returns True; it only goes False after `--no-benchmark` wiped the benchmark. | Match the previous sd.cpp record by cpu+tier+build+release, not by the wanted device; remember failed graphics devices; persist only the device actually proven (H2). |
| 3 | **Confirmed** | `_run_sdcpp:100` calls `bench_on("cpu")` unguarded; the exception escapes to `run():131-137`, which rebuilds `sdcpp` with `vulkan_tried=False, vulkan_error=None`, `device = settings.sdcpp_device or decision.device` (`vulkan0`), and the inner notes list is lost. Reproduced: profile `device="vulkan0"`, `sdcpp.vulkan_tried=False`, notes `["Benchmark failed: ErrorOutOfDeviceMemory"]`. | `_run_sdcpp` never raises for a benchmark failure; it returns the full state with `device="cpu"`, `device_proven=False` (H2). |
| 4 | **Confirmed, and worse than reported** | `server.py:746` `profile = {**(profile or {}), "backend": be}` keeps the other engine's `benchmark`/`actuals`; `current_profile()` (`:164-166`) reloads the file profile (diffusers) on every request. Worse: `worker.py:232` reloads the file profile before each job and `worker.py:364` **saves sd.cpp actual times into the diffusers profile**, poisoning the NVIDIA estimates too. | `assess.profile_matches(profile, engine_name)`; server and worker read/write the file only when it belongs to the running engine; `main()` strips foreign benchmark/actuals (H2 helper, H7). |
| 5 | **Confirmed** | `progress.py:144` `_NT_OOM = {0xC0000017, 0xC00000FD, 0xC000012D}`; `0xC00000FD` is `STATUS_STACK_OVERFLOW`. Reproduced: `classify_failure(0xC00000FD, ParseState())[0] == "ram_oom"`, and `sdcpp_engine.py:109` skips the CPU retry for `ram_oom`. | Remove it from the OOM set; name known NT crash codes in the cause; class stays `unknown` so the engine retries on the processor (H3). |
| 6 | **Confirmed** (impact narrower) | `sdcpp_engine.py:169` decodes each 4096-byte chunk alone with `errors="replace"`; a multi-byte character split across chunks becomes `U+FFFD`. Impact: log lines, the `[E]` text shown to the user, and `ParseState.saved_path` (not used to read the image — the engine reads its own `out` path, so images are not affected). The intern's profile path (`C:\Users\<name>\…`) can contain non-ASCII letters. | `codecs.getincrementaldecoder("utf-8")(errors="replace")`, flushed at end of stream (H6). |
| 7 | **Confirmed** (low probability, real) | `procs.py:115` passes `preexec_fn=_pdeathsig` on Linux. Python documents `preexec_fn` as unsafe when threads exist; the server spawns sd-cli from the worker thread while uvicorn threads run. A child that deadlocks before `exec` hangs the job until Cancel (the engine waits on the pipe with no timeout). | Drop `preexec_fn` and `_pdeathsig`. Parent death is already covered: `start_new_session` + `atexit kill_all_live` + server lifespan `abort()`, and if the parent is SIGKILLed the stdout pipe closes so sd-cli dies of SIGPIPE at its next log line (it logs every step). Windows keeps the Job Object (H4). |
| 8 | **Confirmed** (cleanup; no user-visible bug today) | `server._sdcpp_table` (`:140`) copies `estimates_table` and drops the `has_basis` guard (exceptions are caught, so output is the same `[]`); `install.health_check` (`:240`) re-implements the `--list-devices` subprocess call of `list_devices` (`:213`); `decide._sdcpp_cached` re-implements the model half of `download.sdcpp_cached`. | `estimates_table(..., presets=)` (H2), `health_check` calls `list_devices` (H5), one cache helper `download.sdcpp_cached(tier, build=None)` (H5) that `decide._sdcpp_cached` delegates to (H1). |
| 9 | **Confirmed** | `decide.py:123` `"Not enough disk space" not in d.reason`. Rewording that sentence silently routes disk-short NVIDIA machines to sd.cpp (which then fails the same disk check or downloads into a full disk). | `Decision.reason_code`; the fallback tests `d.reason_code != "disk"` (H1). |
| 10 | **Confirmed** | `_run_sdcpp(machine, decision, settings, no_benchmark, previous, keep_ok)` never reads `previous` or `keep_ok`. Behaviour is consistent with the other engines (a plain `assess` always measures; only `--no-benchmark` reuses), so the right fix is to remove the dead parameters and make the one real use of history explicit (failed devices, kept proven record). | New signature `_run_sdcpp(machine, decision, settings, *, no_benchmark, prior, retry_gpu)`; `prior` is used (H2). |

**Extra problems found while planning (fixed in this run):**

- **E1 (part of 4):** the worker saves actual times into a profile that belongs to another engine. Fixed by `profile_matches` (H7).
- **E2:** the benchmark prompt `"a simple anatomical line drawing of a human hand, white background"` would be **blocked** by the adults-only gate (no adult stated) — it bypasses the gate today. Change it to state an adult and make `benchmark()` and `smoke` call `rules.check_prompt` first (H2, H8). Same rule for the self-test prompt (H9).
- **E3:** the fallback note reads "…; using the processor.; using the processor" when the engine already fell back (seen in the scratch repro). Do not append the suffix twice (H2).
- **E4:** `render_report` for an sd.cpp profile shows the six old sizes at 9 steps; it should show the sd.cpp presets at 8 steps like the server (H2).
- **E5:** on Windows, `print("✔ …")` crashes with `UnicodeEncodeError` when output is redirected (cp1252) — this would break CI logs. The workflow sets `PYTHONUTF8=1`; `selftest.bat` sets it too (H10, H12).
- **E6:** `--engine sdcpp` with no saved tier picks `mid` on a 16 GB GitHub runner; CI must force `low`. New `--tier` flag threaded through setup → smoke → assess, and `make_engine(..., tier=)` (H6, H8).

---

## 2. Decisions (with reasons)

| # | Decision | Reason |
|---|---|---|
| D1 | `Decision.reason_code: str = "ok"` added **last** in the dataclass. Codes for unsupported: `intel_mac`, `ram`, `disk`, `amd`, `no_nvidia`, `no_smi`, `driver`, `vram`, `no_build`. | Positional construction in existing tests keeps working; logic never parses human text. |
| D2 | `decide(m, *, engine=None, tier=None)`; `tier` beats `settings.sdcpp_tier` beats RAM. | CI and self-test must force a tier without editing the user's settings file. |
| D3 | The sd.cpp profile record gains `sdcpp.device_proven: bool` and `sdcpp.failed_devices: list[str]`. A previous record is reused only when `machine.cpu`, `sdcpp.tier`, `sdcpp.build` and `sdcpp.release` all match ("prior"). A device in `prior.failed_devices` is never picked again unless `assess --retry-gpu` or an explicit `settings.sdcpp_device`. | Fixes 2 and 10; "never re-select a failed GPU"; a driver update can still be retried on purpose. |
| D4 | `assess` (with benchmark) always measures; `assess --no-benchmark` keeps the prior record (benchmark, actuals, device, proof) when the prior device equals the device it would use now; otherwise writes `benchmark=None`, `actuals=[]`, `device_proven=False`. | Same semantics as mflux/diffusers; `--no-benchmark` never writes an unproven GPU over a proven CPU result. |
| D5 | One sd.cpp profile file per repo stays; a running engine uses the file only when `profile_matches(file, engine.name)`. Otherwise the server works from an in-memory profile (machine + backend, no benchmark, no actuals) and **never writes** the file. | Fixes 4 without destroying the other engine's measurements. `setup --engine sdcpp` (which runs assess) is the way to make sd.cpp permanent. |
| D6 | Drop `preexec_fn`; rely on SIGPIPE + atexit + lifespan abort (POSIX) and the Job Object (Windows). | Fork-safe; no new wrapper process; same practical guarantee because sd-cli writes progress every step. |
| D7 | NT crash codes keep class `unknown` (so the engine retries on the processor) and get a name in the cause text: `0xC0000005` access violation, `0xC00000FD` stack overflow, `0xC0000409` stack buffer overrun, `0xC000001D` illegal instruction, `0xC0000135` missing DLL, `0xC000007B` bad program file. OOM set = `{0xC0000017, 0xC000012D}` + POSIX `-9`. | Correct names; crash on the graphics chip still finishes on the processor. |
| D8 | Self-test is a **CLI command plus double-click launchers**, not a server feature. The Device tab gets a one-line hint (`d-selftest`) pointing to the launcher. No "Run self-test" button. | A button would load a second copy of the model while the server's worker may hold one (out of memory on 8–16 GB machines) and needs a new job kind; the launcher gives the same report safely. Logged in FUTURE.md. |
| D9 | Self-test never downloads. Anything not installed is listed as `skipped` with "run setup first". It does not write `device_profile.json`. | "No network except setup"; the self-test must not change what the app does next. |
| D10 | Per-run hard timeout: sd.cpp via `should_cancel` (the engine kills the process tree within 0.25 s); in-process engines (mflux/diffusers) run in a daemon thread — if the thread is still alive at `timeout + 30 s`, the report is written with `status="timeout"` and the process exits with code 1. | sd.cpp is the risky path and gets a true kill; in-process engines cannot be killed safely, so the self-test stops instead of hanging. |
| D11 | `tools/e2e_check.py` is stdlib + `openpyxl` + `Pillow` (both base deps), talks HTTP with `urllib`, and starts the server as a subprocess. It uploads a **copy** of `templates/image_prompts_sample.xlsx` with every row's `Size` set to `--size` (default `512x512`), because the sample's rows carry `1024x1024`/`1344x768`/`768x1344`, which take 20+ min each on a CI processor. | Real HTTP path, runs the same locally and in CI, fast enough. |
| D12 | `MEDIMG_PROFILE_PATH` environment variable overrides `config.PROFILE_PATH`. `e2e_check.py --fake-engine` points it at a file in the artifacts folder. | Otherwise a fake e2e run writes fake actual times into the developer's real `device_profile.json`. |
| D13 | CI caches `~/.medical-image-gen/tools` and `~/.cache/huggingface/hub` with `actions/cache/restore` + `actions/cache/save`, key `${{ runner.os }}-sdcpp-<16 hex>` where the hex is a SHA256 over the pinned build-asset SHA256s and the `low` tier model SHA256s (`tools/ci_cache_key.py`). Save only when setup succeeded and the restore missed. | "Keyed on the pinned SHA256s"; never saves a half-downloaded cache under the final key. Two OS × ~5.1 GB fits the 10 GiB repo cache limit, barely (risk R3). |
| D14 | Action versions pinned to full commit SHAs (resolved with `gh api` on 2026-10-27, all releases ≥ 18 days old): `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1), `astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884` (v10.3.0), `actions/cache/restore@55cc8345863c7cc4c66a329aec7e433d2d1c52a9` and `actions/cache/save@55cc…52a9` (v6.1.0), `actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9` (v7.0.2). The existing `tests.yml` is left alone. | Supply-chain safety; a self-hosted runner executes these actions on a real laptop. |
| D15 | `real-run.yml` has **no** `push`/`pull_request` triggers: only `workflow_dispatch` and a weekly `schedule`. The self-hosted job runs only on `workflow_dispatch`. | Nobody can run code on the intern's laptop by opening a PR. |
| D16 | Self-hosted steps use only `${{ }}` expressions, no shell variables and no `shell:` override, so they work under bash, PowerShell 5.1 or pwsh. The GitHub-hosted job uses `shell: bash` (present on both hosted images). | Intern laptops do not have Git Bash or pwsh guaranteed. |
| D17 | GPU testing (NVIDIA/diffusers path) is **not built**. TEST_MACHINES.md lays out the options for Adinath to decide: GitHub GPU larger runners (paid, per minute), renting a GPU cloud machine and registering it as a self-hosted runner, or registering a borrowed NVIDIA PC. | Costs money and needs an account decision. |
| D18 | H1 is judged on `tests/test_assess_decide.py` plus "no new full-suite failures in files H1 owns". `tests/test_assess_profile.py::test_profile_has_schema_v1_keys` failing on the extra `backend.reason_code` key is **H2's** fix (H2 owns `profile.py` and that test; §3.2 already pins the new key): H2 adds `"reason_code"` to the expected backend key set. H1 never edits H2 files. | 2026-10-27 re-plan after H1 reported the cross-file failure; the key is intended, the stale test is the bug. |
| D19 | **Per-task gate in wave 1 = the task's own test files + no new failures caused by its files**, not a fully green suite. The final green-suite gate moves to the end of each wave (Manager runs `uv run --no-sync pytest -q` after all wave workers finish). H5 is accepted on that basis (2026-10-27 replan: H5 code matches 3.5, `tests/test_sdcpp_install.py tests/test_download.py` 46 passed). Remaining failures at replan time were H2-owned (`test_assess_profile.py::test_profile_has_schema_v1_keys` needs `reason_code` in the backend key set; `test_assess_run_sdcpp.py` x8 for the new `_run_sdcpp` signature) — H2 fixes them in its own files. | Parallel workers edit shared modules mid-run, so one worker's full-suite run sees another's half-done work. |
| D20 | `tests/test_sdcpp_engine.py::temp_dirs` scans the global temp folder, so concurrent test runs by parallel workers make `test_happy_path`/`test_cancel_kills_child` flaky. Fix (H6-owned file, applied by whoever next owns it, before the Verifier): an autouse fixture `monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))` so `mkdtemp` and `temp_dirs()` use the per-test folder. No product code change. | Removes a false failure that blocked H5; the leak check keeps its meaning. |
| D21 | H6 re-dispatched (2026-10-27): the code in `sdcpp_engine.py`/`engines/__init__.py` already matches 3.6; the fresh worker only adds the D20 autouse fixture, proves `test_utf8_split_across_chunks` fails on base `6508d28` and passes now, and is judged by D19 (H2-owned `test_assess_*` failures do not block H6). | H6's blocker was other tasks' in-flight failures plus the temp-dir flake, not an H6 defect. |

---

## 3. Pinned interfaces

### 3.1 `medimg/assess/decide.py` (H1)

```python
@dataclass
class Decision:
    backend: str | None; supported: bool; reason: str; fix: str
    offload_mode: str | None; unload_after_job: bool; model_id: str | None
    download_gb: float | None; min_disk_gb: float | None
    device: str | None = None
    tier: str | None = None
    reason_code: str = "ok"          # NEW, always last

REASON_CODES = ("ok", "intel_mac", "ram", "disk", "amd", "no_nvidia", "no_smi", "driver", "vram", "no_build")

def _no(reason: str, fix: str = "", code: str = "unsupported") -> Decision   # every caller passes a code from REASON_CODES
def _sdcpp_cached(tier: str) -> bool:  return download.sdcpp_cached(tier, None)   # one-line delegate, test seam kept
def _sdcpp(m, prefix: str = "", tier: str | None = None) -> Decision
def decide(m, *, engine: str | None = None, tier: str | None = None) -> Decision
```

- `_sdcpp` order: Intel Mac (`intel_mac`, message unchanged) → **no build** (`pins.build_for(m.os_name, m.arch) is None` →
  `_no(f"{prefix}There is no stable-diffusion.cpp program for {m.os_name} on this processor type ({m.arch}).",
  "Use a 64-bit Intel or AMD (x86-64) Windows or Linux PC, or an Apple-silicon Mac.", "no_build")`) → RAM (`ram`) →
  tier (`tier or settings.sdcpp_tier or pins.tier_for_ram(ram)`) → disk (`disk`) → supported.
- `decide`: `engine == "sdcpp"` → `_sdcpp(m, tier=tier)`. Auto fallback condition becomes
  `not d.supported and engine in (None, "auto") and m.os_name in ("Windows", "Linux") and d.reason_code != "disk"`.
- Native codes: Intel Mac `intel_mac`; Mac RAM `ram`; Mac/NVIDIA disk `disk`; AMD `amd`; no NVIDIA `no_nvidia`;
  no smi `no_smi`; old driver `driver`; low VRAM `vram`; all supported decisions `ok`.

### 3.2 `medimg/assess/` package (H2)

```python
# profile.py
def profile_matches(profile: dict | None, engine_name: str) -> bool:
    """False for None. True when engine_name == "fake", when profile["backend"]["name"] is missing/None,
    or when it equals engine_name. Otherwise False."""
def build_profile(machine, decision, benchmark=None, *, actuals=None, notes=None, engine_version=None,
                  device=None, sdcpp=None) -> dict      # backend dict gains "reason_code": getattr(decision, "reason_code", None)

# estimate.py
def estimates_table(profile: dict, steps: int = DEFAULT_STEPS,
                    presets: Sequence[tuple[str, int, int]] = SIZE_PRESETS) -> list[dict]   # same row keys as today

# report.py — render_report(profile): when backend.name == "sdcpp" use config.SDCPP_SIZE_PRESETS and
# config.SDCPP_DEFAULT_STEPS; otherwise unchanged.

# bench.py
BENCH_PROMPT = "a simple anatomical line drawing of an adult human hand, white background"
# benchmark(...) raises medimg.errors.Blocked(reason, rules.HINT) if rules.check_prompt(BENCH_PROMPT) is not None.

# __init__.py
SDCPP_BENCH_SIZES = ((512, 512, 4), (768, 768, 2))      # unchanged
def _sdcpp_prior(previous: dict | None, machine, decision, build: str | None) -> dict | None
    # previous if backend.name=="sdcpp" and machine.cpu, sdcpp.tier==decision.tier, sdcpp.build==build,
    # sdcpp.release==config.SDCPP_RELEASE_TAG all match; else None
def _run_sdcpp(machine, decision, settings, *, no_benchmark: bool, prior: dict | None,
               retry_gpu: bool = False) -> tuple[dict | None, list[str], dict, str]
    # returns (bench or None, notes, sdcpp_dict, device). Never raises for a benchmark failure.
def run(args) -> int     # reads args.no_benchmark, args.json, args.output_root, args.engine,
                         # args.tier ("auto"/None = no override), args.retry_gpu (default False via getattr)
```

`sdcpp` dict written to the profile (all keys always present):
`{"release", "build", "tier", "vulkan_tried": bool, "vulkan_error": str|None, "device_proven": bool, "failed_devices": [str]}`.

`_run_sdcpp` algorithm (pinned):

1. `build = install.chosen_build(machine.os_name, machine.arch)`; `tier = decision.tier`;
   `wanted = settings.sdcpp_device or decision.device or "cpu"`;
   `failed = list(prior.backend.sdcpp.failed_devices or [])` if prior else `[]`;
   carry `vulkan_tried`/`vulkan_error` from prior when skipping.
2. If `wanted != "cpu"` and `wanted in failed` and not `settings.sdcpp_device` and not `retry_gpu`:
   note `f"The graphics chip ({wanted}) failed on this computer before; using the processor. Run assess --retry-gpu to try it again."`, `wanted = "cpu"`.
   `retry_gpu` removes `wanted` from `failed` before trying.
3. `no_benchmark`: if `prior` and `prior.backend.device == wanted` → return `(None, notes, prior_sdcpp_with_current_release_build_tier, wanted)` and `run()` keeps the prior benchmark and actuals; else `device_proven=False` and `run()` writes `benchmark=None, actuals=[]`.
4. Benchmark: if `wanted != "cpu"` list devices exactly as today (unlisted → note + `cpu`). Try `bench_on(wanted)`;
   success → `device_proven=True`, remove `wanted` from `failed`. Failure → note
   `f"Graphics chip benchmark failed on {wanted}: {cause}"` + (`"; using the processor"` unless the cause already ends with
   "using the processor" or "using the processor.") , `vulkan_tried=True`, `vulkan_error=cause`, `failed.append(wanted)` (no duplicates), `dev="cpu"`.
5. If no benchmark yet: try `bench_on("cpu")`; success → `device_proven=True`; failure → note
   `f"Benchmark failed on the processor: {cause}"`, `bench=None`, `device_proven=False`, device stays `"cpu"`.
6. `mk(device)` passes `tier=tier` to `make_engine` (keyword, see 3.6).

`run()`: `prior = _sdcpp_prior(...)`; benchmark = new one, else (prior benchmark if prior device == final device), else None;
actuals = prior actuals if prior device == final device else []. The outer `except` (only for unexpected errors outside
benchmarking) writes `device="cpu"`, `device_proven=False`, `failed_devices` from prior, and keeps notes collected so far.

### 3.3 `medimg/sdcpp/progress.py` (H3)

```python
_NT_OOM = {0xC0000017, 0xC000012D}          # STATUS_NO_MEMORY, STATUS_COMMITMENT_LIMIT
NT_CRASH_NAMES = {0xC0000005: "access violation", 0xC00000FD: "stack overflow",
                  0xC0000409: "stack buffer overrun", 0xC000001D: "illegal instruction",
                  0xC0000135: "a required program library (DLL) was not found",
                  0xC000007B: "a program file is damaged or for the wrong system"}
# classify_failure: crash cause becomes "The image program crashed (code 0xC00000FD, stack overflow)."
# (name appended only when known); class stays "unknown"; everything else unchanged.
```

### 3.4 `medimg/sdcpp/procs.py` and `medimg/osutil.py` (H4)

- `_pdeathsig` deleted; `popen_group` on POSIX passes only `start_new_session=True` (never `preexec_fn`).
  Module docstring states the parent-death guarantee (SIGPIPE, atexit, lifespan abort, Job Object).
- New `medimg/osutil.py`: `def open_folder(folder: Path) -> bool` — the body of today's `server._open_folder`
  (`open` / `explorer` / `xdg-open`, `subprocess.Popen`, `OSError` → False). Stdlib only.

### 3.5 `medimg/sdcpp/install.py`, `medimg/download.py` (H5)

```python
def _run_list_devices(sd_cli, cwd, run) -> subprocess.CompletedProcess
    # the ONE place that runs `sd-cli --list-devices` (timeout 60, text, capture). Raises ModelUnavailable:
    # timeout → "sd-cli did not answer in time."; OSError → f"Could not run sd-cli: {e}"; rc != 0 → the
    # Visual C++ message on Windows DLL codes, else f"sd-cli could not start (exit code {shown})" + first output line.
def list_devices(sd_cli, cwd, run=subprocess.run) -> list[tuple[str, str]]     # parses tab lines
def health_check(sd_cli, cwd, run=subprocess.run) -> str                        # = list_devices + "CPU listed" check
# download.py
def sdcpp_cached(tier: str, build: str | None = None) -> bool   # build None → model files only. Never raises.
```

### 3.6 `medimg/engines/` (H6)

```python
def make_engine(backend: str, profile: dict | None, *, fake: bool = False, tier: str | None = None) -> Engine
# sdcpp tier precedence: tier kwarg > settings.sdcpp_tier > profile backend.sdcpp.tier > RAM.

class SdcppEngine:  # new attributes, reset at the start of every generate()
    last_failure: dict | None   # {"class": "gpu_oom"|"ram_oom"|"no_model"|"unknown", "cause", "fix", "returncode"}
                                # of the LAST failed attempt (also set when a GPU attempt failed and the CPU retry worked)
    last_log_tail: list[str]    # parser.state.tail of the last attempt (≤ 60 lines), success or failure
    last_phases: dict | None    # {"encode_s", "sample_s", "decode_s", "total_s"} from sd-cli's own timings
# Raised MedimgError from a failed run carries attribute failure_class (same value as last_failure["class"]).
# stdout decoding: one codecs incremental UTF-8 decoder per attempt, errors="replace", final flush at EOF
# fed to the parser and the log.
```

### 3.7 Server and worker (H7)

```python
# server.py
def _profile_for_engine(saved: dict | None, be: dict) -> dict:
    """{**saved, "backend": be} when saved's backend name equals be["name"]; otherwise
    {**saved, "backend": be, "benchmark": None, "actuals": [], "notes": []}."""
# _sdcpp_table deleted; /api/device uses estimates_table(p, steps, presets=config.SDCPP_SIZE_PRESETS) for sdcpp.
# current_profile(): file profile only if profile_matches(file, engine.name), else the in-memory profile.
# _open_folder delegates to medimg.osutil.open_folder (name kept).
# worker.py: _run_job reloads the file only if profile_matches(file, engine.name);
# _record_actual and _run_benchmark call save_profile only when the file is missing or matches.
# static/index.html: <p id="d-selftest" class="muted"> in the Device tab, id listed in the header comment.
```

### 3.8 CLI (H8)

```
python -m medimg setup    [--skip-smoke] [--skip-assess] [--yes] [--engine {auto,sdcpp}]
                          [--tier {auto,low,mid,high}] [--output-root P]           # --tier, --output-root NEW
python -m medimg assess   [--no-benchmark] [--json] [--output-root P] [--engine …]
                          [--tier {auto,low,mid,high}] [--retry-gpu]               # NEW flags
python -m medimg smoke    [--size WxH] [--steps N] [--fake-engine] [--engine …] [--tier {auto,low,mid,high}]
python -m medimg serve    (unchanged)
python -m medimg selftest [--quick] [--all-tiers] [--engine {auto,sdcpp}] [--tier {low,mid,high}]
                          [--size WxH (512x512)] [--steps N (4)] [--timeout SECONDS (1800)]
                          [--output-root P] [--no-open] [--json] [--fake-engine]
```

- `DISPATCH["selftest"] = ("medimg.selftest", "run", True)` (offline: `HF_HUB_OFFLINE=1`). Subcommand metavar
  becomes `{setup,assess,serve,smoke,selftest}`.
- `setup --tier X` passes `tier` to `decide`, to the smoke `Namespace` and to the assess `Namespace`; on success it saves
  `settings.sdcpp_tier = None if X == "auto" else X` together with the engine (same "saved only after success" rule).
- `smoke._make_engine(fake, engine=None, tier=None)`: reuse the saved profile only if it matches the engine **and** (tier is
  None or its sdcpp tier == tier); otherwise `decide(..., engine=, tier=)` and `make_engine(..., tier=decision.tier)`.
  `smoke.run` checks `rules.check_prompt(SMOKE_PROMPT)` before loading (raise `Blocked`).
- `setup._assess_done` additionally returns False when `backend.sdcpp.device_proven is False` (missing key = proven, for old profiles).

### 3.9 Self-test (H9): `medimg/selftest.py`

```python
SELFTEST_PROMPT = ("Clinical medical illustration of an adult human hand, neutral grey background, "
                   "sharp detail")
SELFTEST_SEED = 12345
SCHEMA = "medimg-selftest/1"
DEFAULT_TIMEOUT_S = 1800
GRACE_S = 30

@dataclass
class Candidate:
    engine: str              # "sdcpp" | "mflux" | "diffusers" | "fake"
    tier: str | None         # sdcpp only
    device: str | None       # sdcpp: requested device; others None
    build: str | None        # sdcpp only
    offload_mode: str | None # diffusers only
    ready: bool
    skip_reason: str | None  # plain language, e.g. "The 'high' model files are not downloaded. Run setup first."
    label: str               # e.g. "sd.cpp, tier low, on the processor"

def plan_candidates(machine, settings, profile: dict | None, *, quick=False, all_tiers=False,
                    engine: str | None = None, tier: str | None = None, fake=False) -> list[Candidate]
def run_candidate(c: Candidate, *, width: int, height: int, steps: int, seed: int, timeout_s: float,
                  out_dir: Path, stem: str, index: int, engine_factory=None) -> dict      # one "runs[]" entry
def build_report(...) -> dict
def render_text(report: dict) -> str
def write_report(report: dict, out_dir: Path, stem: str) -> tuple[Path, Path]            # (.txt, .json)
def run(args) -> int
```

**Candidate rules.** Native: `decide(machine)` (auto). If it is supported and its backend is `mflux`/`diffusers`, add it;
ready iff the Python module imports (`mflux`; `diffusers` and `torch`) and the weights are cached
(`download.mflux_cached()`, `download.diffusers_cached(mode)`). sd.cpp: `build = install.chosen_build(os, arch)`; if None,
add nothing and put a note "This computer has no stable-diffusion.cpp program (processor type …)". Tiers: `[tier]` if given;
else every tier in `pins.TIERS` whose models are cached when `all_tiers`; else the tier from `decide(machine, engine="sdcpp", tier=tier)`.
Device: the prior proven device (profile backend sdcpp, same build+tier, `device_proven` not False); else
`settings.sdcpp_device or decision.device`, never one in `failed_devices`, confirmed with `smoke._confirmed_device`.
Ready iff `install.binary_cached(build)` and `install.models_cached(tier)`. Order: the engine the app uses now
(matching profile backend, else the auto decision) first. `engine="sdcpp"` keeps only sd.cpp candidates; `engine="auto"`
keeps only the auto backend. `quick` keeps the first **ready** candidate. `fake=True` → exactly one `fake` candidate.

**Gate.** Before any engine work `rules.check_prompt(SELFTEST_PROMPT)` must be None; otherwise every candidate gets
`status="blocked"` and no engine is built (tested by monkeypatching the constant).

**Per run.** Free RAM before; `MemSampler(os.getpid())` for the whole run; deadline; build engine via factory
(default: `make_engine(c.engine, profile_like, tier=c.tier, fake=c.engine=="fake")`); `load` + `generate` in a daemon
thread with `should_cancel = lambda: time.monotonic() > deadline`; save PNG as `<stem>_<index>_<engine>[_<tier>].png`;
`engine.unload()`, `gc.collect()`. Console prints `Test i of N: <label>` and `  step k/n`.

**Report JSON (pinned; all keys always present, null when unknown):**

```json
{
  "schema": "medimg-selftest/1",
  "app_version": "0.1.0", "git_commit": "6508d28…|null",
  "started_at": "ISO-8601 with offset", "finished_at": "…",
  "host": "hostname", "command": ["python", "-m", "medimg", "selftest", "…"],
  "options": {"quick": false, "all_tiers": false, "engine": null, "tier": null,
              "size": "512x512", "steps": 4, "timeout_s": 1800, "fake_engine": false},
  "machine": { "...": "dataclasses.asdict(Machine)" },
  "decision": {"backend": "…", "supported": true, "reason": "…", "reason_code": "ok", "device": "…", "tier": "…"},
  "profile_summary": {"backend": "…", "device": "…", "device_proven": true, "tier": "…"} ,
  "notes": ["…"],
  "runs": [{
    "index": 1, "label": "sd.cpp, tier low, on the processor",
    "engine": "sdcpp", "tier": "low", "build": "win-cpu-x64", "model_id": "…|null",
    "device_requested": "cpu", "device_used": "cpu", "fell_back": false,
    "width": 512, "height": 512, "steps": 4, "seed": 12345,
    "status": "ok|failed|timeout|skipped|blocked",
    "failure_class": "null|gpu_oom|ram_oom|no_model|crash|not_installed|timeout|blocked|error",
    "cause": "…|null", "fix": "…|null",
    "load_s": 0.0, "total_s": 0.0, "per_step_s": 0.0, "per_step_source": "engine|wallclock|null",
    "phases": {"encode_s": 0.0, "sample_s": 0.0, "decode_s": 0.0} ,
    "peak_mem_gb": 0.0, "ram_free_gb_before": 0.0, "ram_free_gb_after": 0.0,
    "image_path": "…|null", "log_tail": ["≤ 40 lines"], "notes": ["engine notes, e.g. fallback"]
  }],
  "summary": {"ok": 1, "failed": 0, "timeout": 0, "skipped": 0, "blocked": 0,
              "verdict": "pass|fail|nothing_to_test"},
  "report_txt": "…/selftest_<host>_<YYYYmmdd-HHMMSS>.txt", "report_json": "…/….json"
}
```

Mapping: `Cancelled` after the deadline → `timeout`; sd.cpp `last_failure.class` `unknown` → `crash`, other classes as
is; `ModelUnavailable` → `no_model`; `Blocked` → `blocked`; `MemoryError` → `ram_oom`; anything else → `error`;
not ready → `skipped` + `not_installed`. `per_step_s` = `last_timing.sample_s / steps` (`engine`) else
`total_s / steps` (`wallclock`). `device_used` = `engine.device` for sd.cpp, `"metal (MLX)"` for mflux, `"cuda"` for
diffusers, `"none"` for fake. `phases` from `last_phases` (sd.cpp) else null.

**Files:** `<output root>/_selftest/selftest_<host>_<YYYYmmdd-HHMMSS>.txt` and `.json` (`host` through
`names.safe_component`, empty → `computer`), PNGs next to them. Then `osutil.open_folder` unless `--no-open` or the
environment has `CI` set. `--json` prints the JSON to stdout instead of the text report (files are still written).

**Exit codes:** 0 = verdict `pass` (≥ 1 ok, 0 failed/timeout/blocked); 1 = `fail`; 2 = `nothing_to_test`
(prints "Nothing is installed to test yet. Run setup first, then run the self-test again."). An abandoned in-process
run (D10) exits 1 after writing the report.

**Text report (shape):**

```
SELF-TEST REPORT — medical-image-gen 0.1.0
Computer : Windows 11 (x86_64), 11th Gen Intel(R) Core(TM) i5-1135G7, 7.7 GB RAM, Intel(R) Iris(R) Xe Graphics
Date     : 2026-10-27 14:03 (+05:30)
Result   : PASS — 1 of 1 test images made

1. sd.cpp, tier low, on the processor: OK
   512x512 at 4 steps in 3m 41s (34.2 s per step), model load 2.1s, peak memory 5.3 GB
   Image: C:\Users\…\_selftest\selftest_LAPTOP_20261027-140301_1_sdcpp_low.png
2. …: FAILED — The computer ran out of memory while making the image.
   Fix: Close other programs …
   Last lines from the image program:
     …

Send both report files (.txt and .json) to the project owner.
```

### 3.10 Launchers (H10)

`selftest.sh` and `selftest.command` byte-identical, executable, start `#!/bin/sh`, contain
`cd "$(dirname "$0")"`, **do not** install uv or use the network: if `uv` is missing or `.venv` is absent they print
"Setup has not been run on this computer yet. Run setup first (…), then run this again." and exit 1. They run
`uv run --no-sync python -m medimg selftest "$@"`, print a one-line pass/problem message naming the report, and always
wait for Enter when attached to a terminal. `selftest.bat`: ASCII, CRLF only, `%~dp0`, `set PYTHONUTF8=1`, same checks
(`where uv`, `if not exist .venv`), `uv run --no-sync python -m medimg selftest %*`, always `pause`.

### 3.11 End-to-end check (H11): `tools/e2e_check.py`, `tools/ci_cache_key.py`, `config.py`

```
python tools/e2e_check.py [--engine {auto,sdcpp}] [--fake-engine] [--port N (0 = pick a free one)]
                          [--output-root DIR (default: new temp folder)] [--artifacts DIR (default: e2e-artifacts)]
                          [--size WxH (512x512)] [--steps N (4)] [--timeout SECONDS (3600)]
                          [--sheet PATH (templates/image_prompts_sample.xlsx)]
exit 0 = every check passed; 1 = a check failed; 2 = the server never started or bad arguments
```

Checks, in order (names pinned; each recorded as `{"name", "ok", "detail"}`):
`server_started` (GET `/api/config` 200 within 120 s), `config_local_only` (`local_only` true),
`sheet_uploaded` (multipart POST `/api/sheet` with header `X-Medimg: 1`; counts total 3, pending 3),
`gate_blocks_minor` (POST `/api/jobs/single` prompt `"Portrait photo of a 12-year-old child"` → 422 and the cause starts
with `Blocked`), `batch_submitted` (POST `/api/jobs/batch` `{"count": 1, "default_size": size, "steps": steps}` → 202),
`job_finished` (poll `/api/status` every 2 s until `job` is None and `last_job.id` matches; outcome `done`; job errors
seen while polling must be empty), `gallery_lists_image` (`/api/gallery/images` has exactly 1), `png_written`
(file exists, PNG signature, size == `--size` unless `--fake-engine`), `sidecar_written` (`.json` next to it with keys
`engine`, `model_id`, `seed`, `steps`, `time_s`), `sheet_row_done` (GET `/api/sheet/download`, row of that Image Name has
Status `done` and Output Path == the image `rel_path`).

The server runs as `sys.executable -m medimg serve --no-browser --port P --output-root R` (+ `--engine E` or
`--fake-engine`), `cwd=REPO_ROOT`, env `PYTHONUTF8=1`, stdout+stderr → `<artifacts>/server.log`; with `--fake-engine`
also `MEDIMG_PROFILE_PATH=<artifacts>/device_profile.json`. Stop: POSIX `SIGINT`, wait 15 s, then kill; Windows
`terminate()`. Artifacts: `e2e_result.json` (`{"schema": "medimg-e2e/1", "ok", "checks": [...], "engine", "device",
"seconds", "png", "started_at", "finished_at"}`), `server.log`, `sheet_uploaded.xlsx`, `sheet_after.xlsx`, the PNG and its
sidecar.

`tools/ci_cache_key.py [--tier low]`: prints `key=sdcpp-<first 16 hex of sha256("\n".join(sorted(asset SHA256s) +
sorted(tier model SHA256s)))>`; when `GITHUB_OUTPUT` is set also appends that line to the file.

`config.py`: `PROFILE_PATH = Path(os.environ["MEDIMG_PROFILE_PATH"]).expanduser() if os.environ.get("MEDIMG_PROFILE_PATH") else REPO_ROOT / "device_profile.json"`.

### 3.12 Workflow (H12): `.github/workflows/real-run.yml`

```yaml
name: real-run
on:
  workflow_dispatch:
    inputs:
      target: {description: "Where to run", type: choice, options: [github-cpu, self-hosted, both], default: github-cpu}
      selfhosted_tier: {description: "Model tier on the lab machine", type: choice, options: [auto, low, mid, high], default: auto}
  schedule:
    - cron: "23 4 * * 1"          # Mondays 04:23 UTC, github-cpu only
permissions:
  contents: read
concurrency: {group: real-run, cancel-in-progress: false}
jobs:
  cpu-real-run:        # name: "Real run on GitHub (${{ matrix.os }}, processor, low tier)"
    if: github.event_name == 'schedule' || inputs.target != 'self-hosted'
    strategy: {fail-fast: false, matrix: {os: [windows-latest, ubuntu-24.04]}}
    runs-on: ${{ matrix.os }}
    timeout-minutes: 90
    env: {PYTHONUTF8: "1"}
    defaults: {run: {shell: bash}}
    steps: checkout → setup-uv → `uv sync` → id cachekey `uv run --no-sync python tools/ci_cache_key.py --tier low`
      → cache/restore (id restore; paths ~/.medical-image-gen/tools and ~/.cache/huggingface/hub;
        key ${{ runner.os }}-${{ steps.cachekey.outputs.key }})
      → id setup: `uv run --no-sync python -m medimg setup --engine sdcpp --tier low --yes --output-root "${{ github.workspace }}/ci-output"`
      → cache/save if: steps.setup.outcome == 'success' && steps.restore.outputs.cache-hit != 'true'
      → e2e: `uv run --no-sync python tools/e2e_check.py --engine sdcpp --output-root "${{ github.workspace }}/ci-output" --artifacts ci-artifacts --size 512x512 --steps 4 --timeout 3600`
      → selftest (if: always() && steps.setup.outcome == 'success'):
        `uv run --no-sync python -m medimg selftest --engine sdcpp --tier low --quick --no-open --output-root "${{ github.workspace }}/ci-output" --timeout 1800`
      → upload-artifact (if: always()) name real-run-${{ matrix.os }}, paths ci-artifacts/, ci-output/_selftest/,
        ci-output/_smoke/, device_profile.json; retention-days 30; if-no-files-found: warn
  self-hosted-real-run: # name: "Real run on the lab machine"
    if: github.event_name == 'workflow_dispatch' && (inputs.target == 'self-hosted' || inputs.target == 'both')
    runs-on: [self-hosted, medimg-lab]
    timeout-minutes: 240
    env: {PYTHONUTF8: "1"}
    steps: checkout → setup-uv → `uv sync` → `uv run --no-sync python -m medimg setup --yes --skip-assess --output-root "${{ github.workspace }}/ci-output"`
      → e2e (engine auto, same flags) → selftest (no --quick; `--tier ${{ inputs.selfhosted_tier }}` only when not auto,
        via two steps guarded by `if:`) → upload-artifact name real-run-lab-${{ runner.name }}
```

Note `uv sync` is plain (no extras): on a Mac lab machine `setup` installs the `mac` extra itself; on an NVIDIA lab
machine it installs `nvidia`. The self-hosted job never passes `--engine`/`--tier` to `setup` so it never changes the
lab machine's saved settings.

---

## 4. Test strategy (goes into ARCHITECTURE.md and TEST_MACHINES.md)

| Layer | Runs where / when | What it proves | What it cannot prove |
|---|---|---|---|
| Fake-engine unit and API tests (`uv run pytest`) | Every push, Ubuntu + Windows (`tests.yml`), and locally | Sheet rules, adults-only gate, API, progress parsing on real sd-cli logs, process kill/cancel with the fake `sd-cli`, profile/estimate math, failure messages | That a real model loads, fits in memory, or is fast enough |
| `tools/e2e_check.py --fake-engine` | Every push (inside pytest) | The whole HTTP path: server start, upload, gate, batch, PNG + sidecar + sheet row | Real generation |
| Real runs on the Mac (Verifier, `selftest`, `e2e_check --engine sdcpp`) | Each build of this plan | mflux and sd.cpp (Metal) really generate on Apple silicon | Windows/Linux behaviour, low-RAM behaviour |
| GitHub real CPU run (`real-run.yml`, `cpu-real-run`) | Weekly + on demand | sd.cpp on the processor on real Windows Server and Ubuntu: download with pinned SHA256, Vulkan-build health check and CPU-build fallback, smoke, benchmark, e2e, self-test | Graphics-chip paths (no GPU), 8 GB laptops, Intel Iris drivers, antivirus, intern behaviour |
| Self-hosted real-hardware run (`self-hosted-real-run`) and the intern's `selftest` | On demand | The exact intern laptop: its RAM, its graphics driver, Vulkan out-of-memory and fallback, real speed | Other laptops; anything the laptop cannot run |
| Clinician review | Every image before use | Anatomy and clinical correctness | — |

**Not provable automatically:** whether the anatomy in an image is correct or clinically useful. No test in this repo
judges image content; a clinician must review every image (SAFETY_AND_LICENCES.md). The NVIDIA/diffusers path stays
"unverified on real hardware" until a GPU machine runs `real-run` (D17).

---

## 5. Task breakdown (waves, exclusive ownership)

Every file below is owned by exactly one task in this run. Tests: `uv run --no-sync pytest -q <files>`; "done" = the
task's tests pass. The full suite is run by the Manager after each wave (all waves must end green).

### Wave 1 (parallel)

| ID | Title | Owns | Est. |
|---|---|---|---|
| H1 | decide: architecture check, reason_code, tier kwarg, one cache helper | `medimg/assess/decide.py`, `tests/test_assess_decide.py` | 45 min |
| H2 | assess run: proven device, failed devices, CPU-failure state, presets, profile_matches, gated bench prompt | `medimg/assess/__init__.py`, `medimg/assess/profile.py`, `medimg/assess/estimate.py`, `medimg/assess/report.py`, `medimg/assess/bench.py`, `tests/test_assess_run_sdcpp.py`, `tests/test_assess_profile.py`, `tests/test_assess_estimate.py`, `tests/test_assess_bench.py` | 120 min |
| H3 | NT status codes | `medimg/sdcpp/progress.py`, `tests/test_sdcpp_progress.py` | 30 min |
| H4 | fork-safe spawn + osutil | `medimg/sdcpp/procs.py`, `medimg/osutil.py` (new), `tests/test_sdcpp_procs.py`, `tests/test_osutil.py` (new) | 60 min |
| H5 | health_check via list_devices; one cache helper | `medimg/sdcpp/install.py`, `medimg/download.py`, `tests/test_sdcpp_install.py`, `tests/test_download.py` | 45 min |
| H6 | engine: incremental UTF-8, failure details, make_engine tier | `medimg/engines/sdcpp_engine.py`, `medimg/engines/__init__.py`, `tests/test_sdcpp_engine.py` | 75 min |

### Wave 2 (parallel; needs wave 1)

| ID | Title | Owns | Est. |
|---|---|---|---|
| H7 | server/worker: engine-matched profile, shared estimates table, self-test hint | `medimg/server.py`, `medimg/worker.py`, `medimg/static/index.html`, `medimg/static/app.js`, `medimg/static/app.css`, `tests/test_api_sdcpp.py`, `tests/test_worker.py`, `tests/test_static_ui.py`, `tests/test_api_misc.py` | 90 min |
| H8 | CLI: --tier, --retry-gpu, setup --output-root, selftest subcommand; setup/smoke threading | `medimg/__main__.py`, `medimg/setup_cmd.py`, `medimg/smoke.py`, `tests/test_cli.py`, `tests/test_setup_cmd.py`, `tests/test_smoke.py` | 75 min |
| H9 | self-test module | `medimg/selftest.py` (new), `tests/test_selftest.py` (new) | 180 min |
| H10 | self-test launchers | `selftest.sh`, `selftest.command`, `selftest.bat` (new), `tests/test_launchers.py` | 30 min |

### Wave 3 (parallel; needs wave 2)

| ID | Title | Owns | Est. |
|---|---|---|---|
| H11 | end-to-end check script, cache key, profile path override | `tools/e2e_check.py` (new), `tools/ci_cache_key.py` (new), `medimg/config.py`, `tests/test_e2e_check.py` (new) | 120 min |
| H12 | real-run workflow | `.github/workflows/real-run.yml` (new), `.gitignore`, `tests/test_real_run_workflow.py` (new), `tests/test_gitignore.py` | 60 min |
| H13 | docs | `README.md`, `docs/ARCHITECTURE.md`, `docs/TROUBLESHOOTING.md`, `docs/TEST_MACHINES.md` (new), `docs/SETUP_WINDOWS_SDCPP.md`, `docs/SETUP_MAC.md`, `docs/FUTURE.md`, `tests/test_docs_commands.py` | 120 min |

Then: Verifier (Sonnet) writes `VERIFICATION_HARNESS.md` (section 7) → Commit phase.

Critical path ≈ 120 (H2) + 180 (H9) + 120 (H11/H13) ≈ 7 h worker time.

The full task instructions are in the workflow output (`waves`); each is self-contained and references the pinned
interfaces in section 3.

---

## 6. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | GitHub CPU runs are slow: ~34 s per step at 512² on a 4-core laptop; runners are similar. Setup smoke + assess benchmark + e2e + self-test ≈ 20–30 min. | 512², 4 steps everywhere; `timeout-minutes: 90`; `--quick` self-test. |
| R2 | The Vulkan sd-cli build on a GPU-less runner may crash at start (Windows) or miss `libvulkan.so.1` (Ubuntu). | Expected: setup's health check falls back to the CPU build — the run proves that path. |
| R3 | Cache size: 2 × ~5.06 GB is just under the 10 GiB repo cache limit; other caches can evict one OS. | A miss costs only a 2–5 min download; key is stable; documented in TEST_MACHINES.md. |
| R4 | Self-hosted runner security: workflow code runs on a real laptop with that user's rights. | Dispatch-only job, no PR triggers, private repo, trusted collaborators only, run the runner interactively (`run.cmd`) only while testing, prefer a separate Windows account; all in TEST_MACHINES.md. |
| R5 | In-process engines (mflux/diffusers) cannot be killed on timeout. | D10: write the report and exit 1. |
| R6 | Windows console encoding. | `PYTHONUTF8=1` in workflow and `selftest.bat`. |
| R7 | Action SHAs drift. | Pinned SHAs with tag comments; updating is a one-line change. |

---

## 7. Acceptance criteria for the Verifier (evidence = command + output in `VERIFICATION_HARNESS.md`)

1. **Suite green:** `uv run --no-sync pytest -q` → 0 failures, count ≥ 599 + new tests. `git status --short` shows only
   files owned in section 5 plus `PLAN_HARNESS.md`/`VERIFICATION_HARNESS.md`; nothing under `agent workflows/`;
   `git ls-files -o --exclude-standard` shows no `.png`, `.gguf`, `.safetensors`, `device_profile.json`, `ci-output/`,
   `e2e-artifacts/`.
2. **Fail-before / pass-after for every finding:** `mkdir -p /tmp/harness_base && git archive 6508d28 | tar -x -C /tmp/harness_base`,
   copy the new/changed regression tests listed below into it, run them there with
   `cd /tmp/harness_base && uv run --project /Users/adinath/Documents/VirtuDoc/medical-image-gen --no-sync pytest -q <tests>`
   (or `PYTHONPATH=/tmp/harness_base` with the repo venv's python) → each FAILS (or errors on a missing name); in the
   repo → each PASSES. Regression tests (one or more per finding):
   F1 `tests/test_assess_decide.py::test_arm64_linux_and_windows_not_supported_without_build`,
   F2 `tests/test_assess_run_sdcpp.py::test_no_benchmark_after_fallback_keeps_proven_cpu` and `::test_failed_gpu_not_reselected`,
   F3 `tests/test_assess_run_sdcpp.py::test_cpu_benchmark_failure_keeps_full_state`,
   F4 `tests/test_api_sdcpp.py::test_foreign_profile_not_used_or_written` and `tests/test_worker.py::test_worker_does_not_write_foreign_profile`,
   F5 `tests/test_sdcpp_progress.py::test_stack_overflow_is_crash_not_oom`,
   F6 `tests/test_sdcpp_engine.py::test_utf8_split_across_chunks`,
   F7 `tests/test_sdcpp_procs.py::test_popen_group_never_uses_preexec_fn`,
   F8 `tests/test_assess_estimate.py::test_estimates_table_presets`, `tests/test_sdcpp_install.py::test_health_check_calls_list_devices`, `tests/test_assess_decide.py::test_sdcpp_cached_delegates_to_download`,
   F9 `tests/test_assess_decide.py::test_disk_fallback_uses_reason_code_not_text`,
   F10 `tests/test_assess_run_sdcpp.py::test_run_sdcpp_signature_has_no_dead_params`.
3. **Field-laptop replay:** `decide()` on the i5-1135G7 / Iris Xe / 7.7 GB Machine still → `sdcpp`, `cpu`, `low`,
   `download_gb == 5.0`, `reason_code == "ok"`; aarch64 Linux and arm64 Windows → unsupported with `reason_code == "no_build"`
   and the plain message; disk-short NVIDIA stays native-unsupported (`reason_code == "disk"`).
4. **Crash code integration:** with the engine's injectable `popen`, a first attempt on `vulkan0` exiting `0xC00000FD`
   is retried on `cpu` and returns an image (Verifier runs a short scratch script; paste output).
5. **Real self-test on this Mac:** `uv run --no-sync python -m medimg selftest --no-open` → exit 0; report `.txt` and
   `.json` exist under `<output root>/_selftest/`; JSON has every key of 3.9; runs include `mflux` and `sdcpp` tier
   `mid` (device `metal`, or `cpu` with a note) with `status == "ok"`, `per_step_s > 0`, `peak_mem_gb > 0`, PNGs open as
   512×512. Then `selftest --quick --engine sdcpp --json` → one run. Then `selftest --tier high --engine sdcpp`
   → exit 2 (or `skipped` with "Run setup first"), and no network download happened (HF cache size unchanged:
   `du -sk ~/.cache/huggingface/hub` before/after).
6. **Gate on the self-test path:** `tests/test_selftest.py::test_blocked_prompt_never_builds_engine` passes; `grep -n
   "check_prompt" medimg/selftest.py medimg/smoke.py medimg/assess/bench.py` shows the gate in all three.
7. **E2E locally:** `uv run --no-sync python tools/e2e_check.py --fake-engine` → exit 0, `e2e_result.json` all checks ok,
   and the repo's `device_profile.json` is unchanged (`shasum` before/after). Real:
   `uv run --no-sync python tools/e2e_check.py --engine sdcpp --artifacts /tmp/e2e-sdcpp` → exit 0, 512×512 PNG, sidecar
   `engine` starts with `sdcpp`, sheet row `done`; and the mflux `device_profile.json` was not modified by the sd.cpp server
   (finding 4 live check: `shasum` before/after).
8. **Workflow statically valid:** `tests/test_real_run_workflow.py` passes; YAML has exactly the triggers
   `workflow_dispatch` + `schedule`, no `push`/`pull_request`; both job ids; every `uses:` is a 40-hex SHA from D14;
   `timeout-minutes` 90 and 240; the self-hosted job has `runs-on: [self-hosted, medimg-lab]` and runs only on dispatch;
   `--tier low` and `--engine sdcpp` on the hosted setup; cache save guarded by setup success. If `actionlint` is
   installed, run it; otherwise say so.
9. **Docs:** `tests/test_docs_commands.py` green; README shows the self-test as the first thing to run on a new
   computer (after setup) and links `docs/TEST_MACHINES.md`; TEST_MACHINES.md has: what a self-hosted runner is, the
   security trade-off, numbered Windows and Mac registration steps with the label `medimg-lab`, how Adinath triggers and
   reads results, the GPU decision; ARCHITECTURE.md has the test-strategy table including "anatomy correctness cannot be
   tested automatically". Read TEST_MACHINES.md and SETUP docs as the intern would: flag developer jargon.
10. **No product network at run time:** `grep -nE "urlopen|hf_hub_download\(|snapshot_download\(|install_binary|download_models" medimg/selftest.py tools/e2e_check.py`
    → nothing except `*_cached`/`local_files_only` uses; `selftest` is in `DISPATCH` with offline=True.
11. **Server binds only 127.0.0.1:** `grep -n "host=" medimg/server.py tools/e2e_check.py` shows only `127.0.0.1`.

---

## 8. Next action for the Manager

Dispatch wave 1 (H1–H6) in parallel. H1's first check: `uv run --no-sync pytest -q tests/test_assess_decide.py -k arm64`
fails before the change and passes after.
