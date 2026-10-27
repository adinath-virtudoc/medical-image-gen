# VERIFICATION_HARNESS.md (re-verification, Sonnet verifier, 2026-10-27)

Overall: all 11 criteria PASS. Criterion 8 (previously FAIL) now PASS: `tests.yml` is pinned. No product code was changed.

| # | Criterion | Result |
|---|---|---|
| 1 | Suite green, git status clean of binaries | PASS |
| 2 | Fail-before / pass-after for all 10 findings | PASS |
| 3 | Field-laptop replay | PASS |
| 4 | Crash code 0xC00000FD retried on CPU | PASS |
| 5 | Real self-test on this Mac, no downloads | PASS |
| 6 | Gate on self-test path | PASS |
| 7 | E2E fake + real sd.cpp | PASS |
| 8 | Workflows valid | PASS (was FAIL) |
| 9 | Docs | PASS (jargon notes) |
| 10 | No runtime network | PASS |
| 11 | 127.0.0.1 only | PASS |

## 1. Suite and git
`uv run --no-sync pytest -q` -> `694 passed, 1 warning in 16.01s`.
`git ls-files -o --exclude-standard` lists only source/docs/tests/launchers/workflow files; no `.png/.gguf/.safetensors/device_profile.json/ci-output/e2e-artifacts`. `git check-ignore -v` confirms rules for `device_profile.json`, `*.png`, `*.gguf`, `*.safetensors`, `ci-output/`, `ci-artifacts/`, `e2e-artifacts/`. `agent workflows/` is ignored (`!!`), untouched. No `device_profile.json` in repo before or after any run.

## 2. Findings: fail on base 6508d28, pass on branch
Method: `git archive 6508d28` into `/tmp/harness_base`, copied the 9 branch test files in, ran each test alone with `PYTHONPATH=/tmp/harness_base`.
Branch (all 14 ids): `16 passed` (two are parametrised). Base:
```
F1 test_arm64_linux_and_windows_not_supported_without_build => 2 failed
F2 test_no_benchmark_after_fallback_keeps_proven_cpu => 1 failed; test_failed_gpu_not_reselected => 1 failed
F3 test_cpu_benchmark_failure_keeps_full_state => 1 failed
F4 test_foreign_profile_not_used_or_written => 1 failed; test_worker_does_not_write_foreign_profile => 1 failed
F5 test_stack_overflow_is_crash_not_oom => 2 failed
F6 test_utf8_split_across_chunks => 1 failed
F7 test_popen_group_never_uses_preexec_fn => 1 failed
F8 test_estimates_table_presets, test_health_check_calls_list_devices, test_sdcpp_cached_delegates_to_download => 1 failed each
F9 test_disk_fallback_uses_reason_code_not_text => 1 failed
F10 test_run_sdcpp_signature_has_no_dead_params => 1 failed
```
Fixed code read: `decide.py` (reason_code, `no_build`, `d.reason_code != "disk"` at :132, `_sdcpp_cached` delegates to `download.sdcpp_cached`); `assess/__init__.py:70` `_run_sdcpp(machine, decision, settings, *, no_benchmark, prior, retry_gpu)` with `failed_devices`; `progress.py:144` `_NT_OOM = {0xC0000017, 0xC000012D}` plus `NT_CRASH_NAMES`; `procs.py:110` `start_new_session` only, no `preexec_fn`; `sdcpp_engine.py:169` incremental UTF-8 decoder flushed at EOF; `server.py:156` and `worker.py:233/260/370` use `profile_matches`; `install.py:263` `health_check` calls `list_devices`; `estimate.py:83` `presets=` parameter.

## 3. Field-laptop replay
```
field (i5-1135G7, Iris Xe, 7.7 GB): sdcpp cpu low 5.0 ok True
Linux aarch64   -> False no_build | No NVIDIA GPU found. There is no stable-diffusion.cpp program for Linux on this processor type (aarch64).
Windows arm64   -> False no_build | ... for Windows on this processor type (arm64).
NVIDIA, 2 GB disk -> supported False, backend None, reason_code disk
```

## 4. Crash-code integration
Scratch script `/tmp/vh/crash.py`, injectable `popen`, first attempt on `vulkan0` exits 0xC00000FD:
```
devices tried: ['vulkan0', 'cpu'] image: (64, 48) engine: sdcpp master-1015-e41fbcf (cpu, fallback)
last_failure: {'class': 'unknown', 'cause': 'The image program crashed (code 0xC00000FD, stack overflow).', ... 'returncode': 3221225725}
```

## 5. Real self-test on this Mac
`./selftest.command --no-open --output-root /tmp/vh/out` -> "Self-test passed.", exit 0 (script's own message; wall 1:12).
```
Result: PASS - 2 of 2 test images made
1. mflux: OK 512x512 at 4 steps in 18.6s (4.66 s per step), peak 7.87 GB
2. sd.cpp, tier mid, graphics chip (metal): OK 512x512 at 4 steps in 48.5s (8.44 s per step), peak 8.61 GB
```
`.txt` and `.json` written under `/tmp/vh/out/_selftest/`. JSON top-level keys present: schema, app_version, git_commit, started_at, finished_at, host, command, options, machine, decision, profile_summary, notes, runs, summary, report_txt, report_json; every per-run key of plan 3.9 present (checked programmatically, none missing). Both PNGs open as 512x512. `device_used` is `metal`; summary `verdict: pass`.
`selftest --quick --engine sdcpp --json` -> exit 0, 1 run (sdcpp ok).
`selftest --tier high --engine sdcpp` -> `SKIPPED - The 'high' model files are not downloaded. Run setup first...`, exit 2.
No download: `du -sk ~/.cache/huggingface/hub` = 11449360 before and after; `~/.medical-image-gen` = 99768 before and after.

## 6. Gate on self-test path
`grep -n check_prompt`: `medimg/selftest.py:265`, `medimg/smoke.py:76`, `medimg/assess/bench.py:19`. `test_blocked_prompt_never_builds_engine` passes (inside the suite).
`pytest -k "gate or minor or blocked or adult or regenerate"` -> `76 passed`.
Live fake-engine server on 127.0.0.1:8771 (stopped afterwards, `pgrep` empty):
```
POST /api/jobs/single  "x-ray of a 9 year old child hand" -> 422 "Blocked: the prompt states an age under 18. Images are adults only."
POST /api/jobs/single  "x-ray of an adult hand"           -> 202
sidecar prompt edited to a minor term, POST /api/jobs/regenerate -> 422 same Blocked message
```
Batch: e2e step `gate_blocks_minor` -> `HTTP 422, cause 'Blocked: the prompt states an age under 18...'`; `test_batch_rows_blocked_by_server_gate` passes.

## 7. End-to-end
Fake: `tools/e2e_check.py --fake-engine --artifacts /tmp/vh/e2e-fake` -> `OK: 10/10 checks passed in 2.9 s`.
Real: `MEDIMG_PROFILE_PATH=/tmp/vh/prof.json tools/e2e_check.py --engine sdcpp --output-root /tmp/vh/e2eroot --artifacts /tmp/vh/e2e-sdcpp --size 512x512 --steps 4` -> `OK: 10/10 checks passed in 43.6 s`; `png_written ... PNG 512x512`; `sheet_row_done: Status 'done'`; sidecar `engine` = `sdcpp master-1015-e41fbcf`; server stopped. Repo `device_profile.json` absent before/after both runs.

## 8. Workflows
`yaml.safe_load` on both: `real-run.yml` triggers `['workflow_dispatch','schedule']` (no push/pull_request), jobs `cpu-real-run`, `self-hosted-real-run`; `tests.yml` triggers `push`, `pull_request`, job `pytest`.
Pinning: regex check, all 8 `uses:` in real-run.yml and both in tests.yml end in a 40-hex SHA (output: `all pinned`). `tests.yml` diff: tags `@v4`/`@v5` replaced by SHAs `3d3c42e5...` (checkout v7.0.1) and `1c37ad07...` (setup-uv v10.3.0), plus `permissions: contents: read`. It runs the fake-engine unit tests on push/PR, which is intended; the real-run job does not.
real-run: `cpu-real-run` `if: schedule || inputs.target != 'self-hosted'`, timeout 90, setup `--engine sdcpp --tier low`, cache save guarded by `steps.setup.outcome == 'success' && cache-hit != 'true'`; `self-hosted-real-run` `if: github.event_name == 'workflow_dispatch' && (target == 'self-hosted' || 'both')`, `runs-on: [self-hosted, medimg-lab]`, timeout 240, never on schedule. `tests/test_real_run_workflow.py` + `tests/test_docs_commands.py` -> `52 passed`.
`actionlint`: not installed (`which actionlint` empty), not run. SHAs not checked against GitHub (no network).

## 9. Docs
`test_docs_commands.py` passes. README line 60 "New computer? Run the self-test" (after setup) links `docs/TEST_MACHINES.md`. TEST_MACHINES.md has the three-ways table, what a self-hosted runner is, security trade-off, numbered Windows and Mac steps with label `medimg-lab`, how to trigger and read results, removal, GPU decision. Facts checked against reality: exit codes 0/1/2, `_selftest` folder, default output `~/medical-image-gen-output` (`config.py:37`), selftest never downloads (verified). ARCHITECTURE.md has the test-strategy table and "Anatomy correctness cannot be tested automatically."
Jargon an intern may meet (minor): "exit code", "checksums", "tier"/`low`, "pull request", "workflow", "artifact zip". Self-hosted steps do not say the laptop must already have uv; the job installs dependencies with `uv sync` and its setup step downloads about 5 GB (doc mentions the download).

## 10. No runtime network
Grep for `urlopen|hf_hub_download(|snapshot_download(|install_binary|download_models` in `selftest.py`, `e2e_check.py`: only `tools/e2e_check.py:65` `urlopen` against the local 127.0.0.1 server. `selftest` in DISPATCH: `("medimg.selftest", "run", True)` (offline).

## 11. Loopback only
`grep -n "host=" medimg/server.py tools/e2e_check.py` -> only `server.py:745 uvicorn.run(app, host="127.0.0.1", ...)`.

## Notes for the owner
1. Scratch files only in `/tmp/vh` and `/tmp/harness_base`; no processes left running.
2. Remaining limit: actionlint not run; SHA validity unchecked offline.
