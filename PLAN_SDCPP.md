# PLAN_SDCPP.md — stable-diffusion.cpp engine for machines without an NVIDIA GPU

Written by the Planner on 2026-10-27 on branch `feat/sdcpp-engine`. Source of truth for the
Manager, the workers and the Verifier for this run. Where this plan and the original brief
(`~/Documents/VirtuDoc/medical-image-gen_build_prompt.md`) or `PLAN.md` disagree on a boundary
(adults-only gate, 127.0.0.1 only, no runtime network, no LLM/paid API, non-developer docs, test
rules), the brief wins.

**Feasible: yes.** Every fact below was read from the pinned release (`master-1015-e41fbcf`,
published 2026-10-25T19:00:22Z) or from the field logs, and the macOS release binary was run on this
Mac (`sd-cli --version` → `stable-diffusion.cpp version unknown, commit e41fbcf`, exit 0;
`--list-devices` → `MTL0\tApple M2 Pro`, `BLAS\tAccelerate`, `CPU\tApple M2 Pro`). Nothing found
makes the engine infeasible.

Run rules for every worker (repeat of the task's hard rules):

- Modify nothing outside `/Users/adinath/Documents/VirtuDoc/medical-image-gen` (scratch/tmp, the HF
  cache and `~/.medical-image-gen/` excepted). Never touch `patient-imagegen/`, `FjordCampus/` or
  the repo's `agent workflows/` folder.
- No push, no PR, no `git commit` outside the Commit phase.
- Downloads this run ≤ 6 GB total. The Verifier's Mac set (section 2, tier `mid`) is 5.56 GB.
  Do not download tier `high` (6.70 GB) on any machine this run.
- No torch/CUDA install. No real generation except the Verifier's (section 6) and the smoke
  step inside the Verifier's `setup --engine sdcpp`.
- All 417 existing tests stay green; mflux and diffusers behaviour unchanged.
- Python runs via `uv run` (tests: `uv run --no-sync pytest -q`) in the repo.
- Downloaded archives and model files are untrusted data: setup extracts each archive into its
  own empty folder, verifies SHA256 before extraction, and never runs anything from the download
  folder except the pinned `sd-cli` binary itself.

---

## 1. What this engine is (plain language)

Today the app makes images two ways: on a Mac it uses `mflux` (Apple's MLX library), and on a PC it
uses PyTorch with an NVIDIA card. Both are Python libraries that need the model loaded inside the
app. A PC with Intel or AMD graphics, or no graphics card at all, cannot run either, so `assess`
currently says "unsupported".

**stable-diffusion.cpp** ("sd.cpp") is a separate, small program written in C++ by the same kind of
people who made `llama.cpp`. It is one executable file, `sd-cli` (`sd-cli.exe` on Windows), about
30 MB, with no Python and no installer. You give it the model files and a prompt on the command
line; it writes a PNG and exits. It can run on:

- the **processor only** (any PC; slow but it works; this is what the intern's laptop did), or
- the **graphics chip through Vulkan** (a standard graphics interface that Intel, AMD and NVIDIA
  drivers all provide), or
- **Metal** on a Mac (Apple's graphics interface).

It reads **GGUF** files, the same compressed model format `llama.cpp` uses. Compression ("Q2_K",
"Q3_K", "Q4_K"...) trades picture quality for memory: Q2_K of Z-Image Turbo is 2.6 GB, Q4_K is 3.9 GB,
the uncompressed model is 12.3 GB. Same model (Z-Image Turbo), same prompts, same adults-only
rule; only the program that does the arithmetic changes.

**What we are adding:** a fourth engine, `sdcpp`, that the app drives like this: for each image it
starts `sd-cli` as a child process with the right flags, reads its progress bar from the output to
move the step bar in the UI, picks up the PNG when it finishes, and kills the process if you press
Cancel. `setup` downloads the pinned `sd-cli` build and three model files (image model, text model,
image decoder), and `assess` routes a PC without NVIDIA to it instead of saying "unsupported".

**What it costs:** on the intern's laptop (i5-1135G7, 7.7 GB RAM, Intel Iris Xe) one 512x512 image
at 8 steps took **5.7 minutes** on the processor (prompt 3 s, 8 steps at 34 s each, decode 69 s).
A 1024x1024 image is estimated at 20–25 minutes there, so the UI will warn and default to
512x512 drafts on processor-only machines. The Iris Xe graphics chip itself ran out of memory
every time (three runs), so on that class of machine the plan uses the processor and does not try
the graphics chip. Quality at Q2_K is fine for drafts; skin can look blotchy. Machines with more RAM
get a less compressed model (section 2.3).

**What it does not change:** the sheet, the gallery, the sidecars, the adults-only gate (which
runs in the server before any engine), the 127.0.0.1-only server, and "no network after setup".

---

## 2. Decisions (with reasons)

| # | Decision | Reason / evidence |
|---|---|---|
| S1 | **One `sd-cli` process per image, not `sd-server`.** | `sd-server` exists (`examples/server/`, binds `127.0.0.1:1234` by default: `runtime.h:23-24`, `--listen-ip` flag at `runtime.cpp:348`) and has an async job API with cancel (`/sdcpp/v1/img_gen`, `/sdcpp/v1/jobs/{id}`, `/sdcpp/v1/jobs/{id}/cancel`, `api.md`). But its step progress is only exposed through `preview` (base64 PNG per step; `preview: "none"` gives no step info at all, `api.md` "Preview Interval Semantics"), it needs a second long-lived process, a port, an HTTP client, base64 transfer and model-load (recipe) handling, and it keeps ~5 GB resident between images on 8 GB laptops. With `--mmap` the per-image model load is 0.2 s (field log: "memory-mapped 386 tensors ... taking 0.00s", "loading tensors completed, taking 0.20s"), so the saving from keeping the model loaded is a few seconds on a 5-minute image. A child process per image is crash-isolated (an OOM kills the child, not the app), cancel is "kill the process", and progress comes free from stdout. `sd-server` is recorded in FUTURE.md as the upgrade path if per-image overhead matters on fast GPUs. |
| S2 | **Pinned release `master-1015-e41fbcf`**, assets fetched from GitHub at setup, SHA256-verified against the values in section 2.1, extracted to `~/.medical-image-gen/tools/sdcpp/master-1015-e41fbcf/<build>/`. Never committed, never inside the repo. | The project warns "API and command-line option may change frequently" (README). Releases are cut per commit (1014, 1015, 1016, 1017 within two days), so only an exact tag is stable. The GitHub release API returns a `digest` (sha256) per asset, which section 2.1 copies. `~/.medical-image-gen/` already holds the user settings (`config.SETTINGS_PATH`), so tools go next to it; it survives `git pull` and reclones. |
| S3 | **Builds:** Windows → `win-vulkan-x64` zip; Linux → `Linux-Ubuntu-24.04-x86_64-vulkan` zip; macOS arm64 (override only) → `Darwin-macOS-26.6.2-arm64` zip. The CPU-only zips are a fallback downloaded **only** if the Vulkan build's `--list-devices` health check fails to run (missing `vulkan-1.dll`, crash). Each build lives in its own folder. | The win-vulkan zip contains the CPU backend DLLs too (`ggml-cpu-*.dll` for 9 CPU levels plus `ggml-vulkan.dll`, listing in 2.1), and `--backend cpu` with that build is what produced the working field image (result (2).txt, try 2). ggml loads backend DLLs from the executable's folder and the current directory (`ggml-backend-reg.cpp:486-501`), which is why the intern's "CPU zip" still picked up `ggml-vulkan.dll` from the shared folder. Separate folders plus `cwd = the build folder` removes that trap. The macOS release binary links Metal (`otool -L`: Metal.framework, MetalKit.framework) because leejet/ggml turns `GGML_METAL_DEFAULT` on for Apple (`ggml/CMakeLists.txt:95-96`), and `--list-devices` on this Mac lists `MTL0`. CUDA/ROCm zips (343 MB + 563 MB cudart, 265 MB) are not used: NVIDIA keeps the diffusers path. |
| S4 | **Model files by RAM tier** (all Apache-2.0, all ungated; sizes and SHA256 in 2.2): `low` (RAM < 12 GB): Q2_K + Qwen3 Q3_K_M + ae = **5.00 GB**; `mid` (12 ≤ RAM < 24): Q3_K + Qwen3 Q3_K_M + ae = **5.56 GB**; `high` (RAM ≥ 24): Q4_K + Qwen3 Q4_K_M + ae = **6.70 GB**. Minimum RAM 7 GB; below that → unsupported with the reason. | `low` is the exact set that worked on the 7.7 GB laptop ("total params memory size = 4606 MB"). The sd.cpp Z-Image doc's quantisation comparison shows q2_K visibly worse than q3_K and q4_K; q3_K is the doc's own example. `mid` stays under the 6 GB run budget so the Verifier's Mac (16 GB → `mid`) can do the real run. The text encoder's quant matters less than the image model's, so Q3_K_M Qwen is kept for `low` and `mid`. Peak RAM ≈ params + 0.2–0.6 GB compute at 512², more at 1024² (field: compute buffers 172 MB sampling + 416 MB VAE at 512² with tiling). |
| S5 | **Model files come through `huggingface_hub.hf_hub_download`** into the normal HF cache (like the existing GGUF mode), then setup verifies SHA256 of each file against 2.2. Binaries come through `urllib` with `.part` + HTTP Range resume + SHA256. | Reuses the existing resumable download and `local_files_only=True` offline checks (`download.py` pattern). `hf_hub_download` resumes partial files; the explicit SHA256 pass (≈20 s for 5.5 GB) catches a corrupt file before the smoke test. |
| S6 | **Device policy:** default `cpu`. `vulkan0` is a *candidate* only when the GPU vendor is `amd`, or `intel` with ≥ 16 GB RAM, or `nvidia` (override case), and `sd-cli --list-devices` lists a Vulkan device. `assess` benchmarks the candidate first; if the run fails (non-zero exit, or the log contains `ErrorOutOfDeviceMemory` / `failed to allocate Vulkan`), it records the failure in `notes`, benchmarks on `cpu`, and writes `backend.device = "cpu"`. Intel iGPU with < 16 GB RAM → `cpu` directly, no try. Mac override → `metal` when listed, else `cpu`. The engine also falls back to `cpu` once at generation time on a GPU OOM (section 2.6). | Field evidence: Iris Xe on 7.7 GB failed three times with `vk::Device::allocateMemory: ErrorOutOfDeviceMemory` (text encoder, 1.07 GB buffer; then the diffusion model, 475 MB, even with `--backend te=cpu,vae=cpu`). Integrated graphics shares the 7.7 GB, so trying it only costs minutes. AMD discrete cards and Intel Arc have their own memory; a 16 GB+ Intel iGPU machine has enough shared memory to be worth one try. `--list-devices` prints `name<TAB>description` per line to stdout (`common.cpp:600-603`, `util.cpp:1155-1176`), e.g. `Vulkan0`, `CPU`, `MTL0`; `--backend` matches names case-insensitively by unique prefix (`docs/backend.md` "Backend names": `cpu`, `vulkan0`, `metal`). |
| S7 | **Fixed sd-cli flags:** `--diffusion-model <gguf> --llm <gguf> --vae <ae> -p <prompt> --cfg-scale 1.0 --steps N -W w -H h -s seed -o <tmp.png> --backend <device> --offload-to-cpu --mmap --vae-tiling --log-level info`. No `--threads` unless the user sets one. No `--diffusion-fa` (deprecated at this release: `common.cpp:785-788`, replaced by `--flash-attn`, whose default `auto` chose "on" for CPU in the field log). No `-v` in production runs. | This is the field-proven set (`sdcpp_laptop_test.bat` ARGS plus `--backend cpu`) minus `-v`. `--cfg-scale 1.0` is what the Z-Image doc uses for Turbo (`docs/z_image.md`). `--threads` default `-1` = physical cores (`common.cpp:588-591`, `stable-diffusion.cpp:332`). `--log-level info` keeps the `[I]` phase markers the parser needs (listed in 2.5) and drops the `[V]` tokeniser lines; the progress bars print regardless of log level (`util.cpp:597` `pretty_progress` is not gated by level). `--offload-to-cpu` and `--mmap` are harmless on CPU and required on small GPUs (doc example). |
| S8 | **Defaults for this engine:** steps **8**; size presets with `512x512 draft` first, then `768x768`, `1024x1024`, `768x1344 portrait`, `1344x768 landscape`, `832x1216`, `1216x832`; the UI shows a warning line whenever the estimate for the chosen size exceeds **15 minutes** (`warn_over_s = 900`, from `/api/config`), and the batch suggestion already uses the estimate. The Steps slider label becomes "8 recommended for this engine". | 8 steps is the sd.cpp Z-Image example and the field run. 1024² on the field laptop ≈ 8 × 34 s × 4 + decode ≈ 20–25 min, so the first preset must be a draft size and the warning must fire before someone starts a 50-image batch. The existing 4–15 step limits stay. |
| S9 | **`assess` routing:** Windows/Linux with an NVIDIA card that qualifies → `diffusers` (unchanged). Windows/Linux otherwise (no GPU, Intel, AMD, NVIDIA with no driver / old driver / < 7.5 GB VRAM) → `sdcpp` with a reason naming why not CUDA. Intel Mac → unsupported (unchanged). Apple silicon → `mflux` (unchanged). RAM < 7 GB → unsupported. Disk < tier GB + 5 GB → unsupported with the numbers. Override: `--engine sdcpp` (or `--engine auto`) on `setup`, `assess`, `serve`, `smoke`; `setup --engine` persists it in settings (`engine` key), the other commands use it for that run. | Keeps every existing decision table row identical for the machines it covers (existing `test_assess_decide.py` cases stay valid except `test_no_gpu`, `test_amd`, `test_intel_igpu_only_is_unsupported`, `test_nvidia_without_smi`, `test_6gb_unsupported`, `test_driver_check` old-driver case, which now expect `sdcpp`; S4 updates them). The override is what the Verifier uses on this Mac and what an NVIDIA box uses to compare engines. |
| S10 | **`device_profile.json` stays schema 1** and gains additive keys under `backend`: `"device"` (`"cpu"`, `"vulkan0"`, `"metal"`, or `null` for other engines), `"sdcpp": {"release", "build", "tier", "vulkan_tried", "vulkan_error"}` (or `null`), and `engine_version = "sdcpp master-1015-e41fbcf"`. `offload_mode` stays `null`, `unload_after_job` is `false` (nothing stays loaded). | Additive keys keep every existing reader working; a future catalogue lookup (FUTURE.md) gets the build and tier. |
| S11 | **Progress parsing** is a small state machine over `sd-cli`'s merged stdout+stderr, split on `\r` and `\n` with `\033[K` stripped. Phase markers are `[I]` log lines; step bars are `  |====>  | k/n - 34.12s/it - ETA 03:58`. Full regex set in 2.5. | Bars are written with `printf("\r%s %*i/%i - %10s%s%s\033[K%s", ...)` and `fflush(stdout)` (`util.cpp:580-591`); the newline comes only on the last step. Log lines go `[I] msg --- file:line` to **stdout** for D/V/I/W and to **stderr** for E (`log.cpp:85,119-121`). Tensor-loading bars use `#` and `MB/s` (`pretty_bytes_progress`) and VAE tile bars use the same `=` format inside the decoding phase, so the parser keys on phase, not just on the bar. Verified against all three field logs. |
| S12 | **Cancel = kill the process tree.** POSIX: `Popen(start_new_session=True)`, `os.killpg(SIGTERM)`, 3 s grace, `SIGKILL`. Windows: `creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`, `taskkill /F /T /PID`, then `proc.kill()`. `should_cancel()` is polled every 250 ms in the reader loop (not only per step, because a CPU step is 34 s). | `sd-cli` installs no signal handler (no `signal`/`SIGINT`/`SetConsoleCtrlHandler` in `main.cpp`, `common.cpp` or `stable-diffusion.cpp`), so SIGTERM ends it at once. The PNG is written only after generation finishes (`save_results` runs at the end of `main`, `main.cpp:441,986`), so a killed run leaves no partial image; the engine writes to a per-job temp folder anyway and deletes it. |
| S13 | **Peak memory** = max RSS of the child (plus its children) sampled every 500 ms with `psutil.Process(pid).memory_info().rss`, reported in `GenResult.peak_mem_gb`. | The brief asks every engine to measure peak memory. mmap'd model pages count in RSS, so the number is "peak resident including mapped weights", which is what matters on an 8 GB laptop. `psutil` is already a base dependency. |
| S14 | **Failure classes → plain-language errors** (section 2.6). GPU OOM on a non-CPU device triggers one automatic retry on `cpu` inside the same `generate()`; the result's `engine` string becomes `sdcpp master-1015-e41fbcf (cpu, fallback)` and the engine's `notes` list records "The graphics chip ran out of memory; using the processor." | The task's required mapping. The worker only surfaces failures, so the fallback note is visible in the sidecar `engine` field and the terminal, not as a UI error. |
| S15 | **Offline at runtime.** `sdcpp` needs no `huggingface_hub` network call: model paths are resolved with `local_files_only=True`; binaries are plain files. `HF_HUB_OFFLINE=1` stays set by `__main__` for `serve`/`smoke`/`assess`. `sd-cli` itself makes no network calls. | Brief 2.8. |
| S16 | **Licences:** sd.cpp and ggml are MIT (`LICENSE`, release zips ship `stable-diffusion.cpp.txt` and `ggml.txt`); `leejet/Z-Image-Turbo-GGUF` apache-2.0; `unsloth/Qwen3-4B-Instruct-2507-GGUF` apache-2.0; `Comfy-Org/z_image_turbo` apache-2.0 (its `split_files/vae/ae.safetensors` is the FLUX.1 autoencoder, upstream `black-forest-labs/FLUX.1-schnell` is Apache-2.0 but gated → 401, so the Comfy-Org copy is used). SAFETY_AND_LICENCES.md gets these rows. | HF API `cardData.license` for each repo read 2026-10-27 (section 2.2). |
| S17 | **No new Python dependency.** Base deps already include `psutil`, `huggingface-hub`, `pillow`. | Keeps CI (`uv sync` with no extra) unchanged. |
| S18 | **Benchmark sizes for sdcpp:** `((512, 512, 4), (768, 768, 2))` instead of the 1024² second point. `bench.py` takes a `sizes` argument already; `assess.run` passes the sdcpp set when the backend is `sdcpp`. | 1024²@2 on the field laptop ≈ 2×136 s + ~280 s decode ≈ 9 min; the 768² point ≈ 4.5 min and still gives the alpha fit. Estimates for 1024² on CPU will be rough (overhead is fixed from the small point, but VAE decode scales with pixels); actuals override after the first real image (D24) and the 15-minute warning fires either way (risk R5). |
| S19 | **S-G2 blocker resolution (manager, 2026-10-27):** the 6 `test_docs_commands.py` failures S-G2 reported were transient: S-G1 was still editing `SETUP_WINDOWS_SDCPP.md` / `SETUP_WINDOWS_NVIDIA.md`. Re-run after S-G1 finished: full suite 577 passed. No ownership change. One S-G2 claim was wrong and must be fixed: the sheet's Machine column is `machine_string()` = `"<hostname> · <chip>"` (`medimg/worker.py:30-38`), not the engine. Only the image sidecar `.json` (`ImageRecord.engine`, `worker.py:327`) records the engine. `docs/HANDOFF.md` must say so. | Verified by running `uv run pytest -q` and reading `worker.py`. `config.SETTINGS_PATH` = `~/.medical-image-gen/config.json` and key `sdcpp_device` confirmed (`config.py:35,58,90`). The 1024x1024 20-25 min figure is a plan estimate (S8) and docs must label it "estimated" (SETUP_WINDOWS_SDCPP.md:32 already does). |

### 2.1 Pinned release assets (GitHub API, read 2026-10-27)

Release: https://github.com/leejet/stable-diffusion.cpp/releases/tag/master-1015-e41fbcf
(API: `gh api repos/leejet/stable-diffusion.cpp/releases/tags/master-1015-e41fbcf`; the `digest`
field is `sha256:<hex>`). Base URL for every asset:
`https://github.com/leejet/stable-diffusion.cpp/releases/download/master-1015-e41fbcf/<name>`.

| Build key | Asset name | Bytes | SHA256 | Used |
|---|---|---|---|---|
| `win-vulkan-x64` | `sd-master-e41fbcf-bin-win-vulkan-x64.zip` | 29,744,345 | `259ceeb62f1069190d24c85ea1c4549d2d61deb0ef712510dbe98d79ce93a38b` | Windows (primary) — verified by download on this Mac |
| `win-cpu-x64` | `sd-master-e41fbcf-bin-win-cpu-x64.zip` | 18,080,790 | `bfc02f16df7744296ecc7720503a2b633575490dd7d8b448aee035c1fc836bec` | Windows fallback |
| `linux-vulkan-x64` | `sd-master-e41fbcf-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip` | 37,644,143 | `0ae9ef34eea1ff6a229b892144a65ed8c00b6438c5ba783cdeca77024b2fc697` | Linux (primary) |
| `linux-cpu-x64` | `sd-master-e41fbcf-bin-Linux-Ubuntu-24.04-x86_64.zip` | 27,320,021 | `422bc495ca647d95e9bd88b04d3eaae52e641d89497ea0dda7335f44c46e9109` | Linux fallback |
| `mac-arm64` | `sd-master-e41fbcf-bin-Darwin-macOS-26.6.2-arm64.zip` | 37,584,335 | `933fb5b622b578df7a0d22c41f39bc83791d40b876648a084fe1c4cbff2ef36c` | macOS override — verified by download and run on this Mac |
| (not used) | `sd-master-e41fbcf-bin-win-cuda12-x64.zip` 343,503,038; `cudart-sd-bin-win-cu12-x64.zip` 563,452,046; `sd-master-e41fbcf-bin-win-rocm-10.1.0-x64.zip` 264,571,662; `sd-master-e41fbcf-bin-Linux-Ubuntu-24.04-x86_64-rocm-10.1.0.zip` 296,445,187 | | | NVIDIA stays on diffusers; ROCm needs a driver stack an intern cannot install |

Zip contents (win-vulkan, verified): `sd-cli.exe`, `sd-server.exe`, `stable-diffusion.dll`,
`ggml.dll`, `ggml-base.dll`, `ggml-vulkan.dll`, `ggml-cpu-{x64,sse42,sandybridge,haswell,skylakex,
cannonlake,icelake,cascadelake,alderlake}.dll`, `libwebp*.dll`, `webm.dll`, `ggml.txt`,
`stable-diffusion.cpp.txt`, `start-server.{bat,sh}`. macOS zip: `sd-cli`, `sd-server`,
`libstable-diffusion.dylib` (universal arm64+x86_64), the two licence texts and the launchers.
The executable is `sd-cli` / `sd-cli.exe` at the zip root in every build (`build.yml`
`zip -j` / `7z a` of `bin/*`).

### 2.2 Pinned model files (HF API `?blobs=true`, read 2026-10-27)

| Repo (licence, revision) | File | GB | SHA256 (LFS) |
|---|---|---|---|
| `leejet/Z-Image-Turbo-GGUF` (apache-2.0, `c61c0e422dc8b541b7548cf33a4ef8302b0f8085`) | `z_image_turbo-Q2_K.gguf` | 2.592 | `a9cf1b0368e24c2f9d542d2951c01f6f7fc85ed8c9ed39b5b37b15375508d58a` |
| | `z_image_turbo-Q3_K.gguf` | 3.144 | `4b44bdaa7814f20d7cf144e3939bd93aa32f50660204dd0c2aea5c5376232980` |
| | `z_image_turbo-Q4_K.gguf` | 3.864 | `14b375ab4f226bc5378f68f37e899ef3c2242b8541e61e2bc1aff40976086fbd` |
| `unsloth/Qwen3-4B-Instruct-2507-GGUF` (apache-2.0, `a06e946bb6b655725eafa393f4a9745d460374c9`) | `Qwen3-4B-Instruct-2507-Q3_K_M.gguf` | 2.076 | `9c6e0763577125a994a9bea0bbd7a737ac4498b8a6a4e0f788727553af1806c9` |
| | `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` | 2.497 | `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597` |
| `Comfy-Org/z_image_turbo` (apache-2.0, `6fc90a3b1b653e935a0d175e260736de25b84df5`) | `split_files/vae/ae.safetensors` | 0.335 | `afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38` |

Tiers: `low` = Q2_K + Q3_K_M + ae (5.00 GB); `mid` = Q3_K + Q3_K_M + ae (5.56 GB);
`high` = Q4_K + Q4_K_M + ae (6.70 GB). The other quants in `leejet/Z-Image-Turbo-GGUF`
(Q4_0 3.683, Q5_0 4.543, Q6_K 5.263, Q8_0 6.577) are listed in HARDWARE_ALTERNATIVES.md only.

Sources: https://huggingface.co/leejet/Z-Image-Turbo-GGUF ·
https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF ·
https://huggingface.co/Comfy-Org/z_image_turbo ·
https://github.com/leejet/stable-diffusion.cpp/blob/e41fbcf/docs/z_image.md

### 2.3 Verified sd-cli behaviour (source at commit e41fbcf unless noted)

| Fact | Value | Source |
|---|---|---|
| Exit codes | `0` success; `1` for bad flags/usage, `--list-devices` failure, model load failure (`new_sd_ctx_t failed`), `generate failed`, save failure. `--version` and `--help` exit 0. No other codes. A crash (OOM, access violation) gives a negative/large code on Windows (`0xC0000005`, `0xC0000409`) or a signal number on POSIX. | `examples/cli/main.cpp:292,299,312,662,669,743-997`; run on this Mac: missing model → rc 1, bad flag → rc 1 |
| `--version` | prints `stable-diffusion.cpp version unknown, commit e41fbcf` to stdout, exit 0 | `main.cpp:637-640`; run on this Mac |
| `--list-devices` | one `name<TAB>description\n` per device on stdout, exit 0; Metal/Vulkan init chatter goes to stderr. Mac: `MTL0\tApple M2 Pro`, `BLAS\tAccelerate`, `CPU\tApple M2 Pro`. Field laptop (from the log): `Vulkan0`, `CPU`. | `common.cpp:600-603, 836-845`; `src/core/util.cpp:1155-1176`; run on this Mac |
| Backend names | case-insensitive, unique-prefix match against the device list: `cpu`, `vulkan0`, `metal` (matches `MTL0`), `cuda0`; `gpu`/`auto` specials; per-module form `te=cpu,vae=cpu` | `docs/backend.md` "Backend names" |
| Progress line | `printf("\r%s %*i/%i - %10s%s%s\033[K%s")` → `  |=====>   | 1/8 -  34.12s/it - ETA 03:58`, newline only on the last step; speed unit `s/it` or `it/s`; ETA hidden when the whole run is under 15 s. Written to **stdout**, flushed. | `src/core/util.cpp:566-623` |
| Log line | `[I] text --- file.cpp:line` (`D`/`V`/`I`/`W` to stdout, `E` to stderr); `--color` adds ANSI codes (never passed) | `examples/common/log.cpp:82-125` |
| Phase markers (info level) | `[I] get_learned_condition completed, taking 2.98s` · `[I] generating image: 1/1 - seed 42` · `[I] sampling completed, taking 269.75s` · `[I] decoding 1 latents` · `[I] latent 1 decoded, taking 69.28s` · `[I] generate_image completed in 342.29s` · `[I] save result image 0 to 'x.png' (success)` · `[I] 1/1 images saved` | field log `result (2).txt` try 2 |
| GPU OOM signature | `ggml_vulkan: vk::Device::allocateMemory: ErrorOutOfDeviceMemory` then `[E] ggml: ggml_backend_buft_alloc_buffer_n_default: failed to allocate Vulkan0 buffer of size N` … `[E] generate failed`, exit 1 | all three field logs |
| Missing model file | `[W] loading diffusion model from 'x' failed` + `[I] new_sd_ctx_t failed`, exit 1 | run on this Mac |
| Output | `-o path` written only in `save_results` after generation; parent folders are created; PNG by extension | `main.cpp:65-69, 441-500` |
| Seed | `-s/--seed` int, default 42, negative = random (never passed negative) | `common.cpp:1759-1762` |
| Threads | `-t/--threads`, default -1 = physical cores | `common.cpp:586-591` |
| Flags confirmed present | `--diffusion-model`, `--llm`, `--vae`, `-p`, `--cfg-scale`, `--steps`, `-W`, `-H`, `-o`, `--backend`, `--params-backend`, `--list-devices`, `--offload-to-cpu`, `--mmap`, `--vae-tiling`, `--log-level`, `-v` | `common.cpp` (lines 243-255, 426-471, 558-627, 1211-1285, 1406) |
| Deprecated (do not pass) | `--diffusion-fa` (→ `--flash-attn`), `--fa`, `--clip-on-cpu`, `--vae-on-cpu` | `common.cpp:630-638, 777-788` |
| Signals | no handler installed; SIGTERM/`taskkill` ends the process immediately | grep of `main.cpp`, `common.cpp`, `stable-diffusion.cpp` |
| Backend DLL discovery | executable folder, then current directory, then `GGML_BACKEND_PATH` | leejet/ggml `src/ggml-backend-reg.cpp:486-501` (submodule `a5915eb`) |
| sd-server | exists; default `listen_ip = "127.0.0.1"`, port 1234; async jobs with cancel; not used (S1) | `examples/server/runtime.h:23-24`, `runtime.cpp:348-353`, `api.md` |
| Metal first run | compiles ~36 embedded Metal libraries once (~5 s, messages on stderr) | run on this Mac |

### 2.4 Field evidence used as fixtures

Copy verbatim into `tests/fixtures/sdcpp/`:

| Fixture | From | Covers |
|---|---|---|
| `cpu_success_512_8steps.log` | `result (2).txt`, "Last 80 lines of the try 2 log" | happy path: markers, 8 denoise bars, 9 VAE tile bars, save line |
| `vulkan_oom_text_encoder.log` | `result (1).txt`, graphics-chip log | OOM during text-encoder weight prep |
| `vulkan_oom_diffusion_te_cpu.log` | `result (2).txt`, try 1 log | OOM in the diffusion model even with `--backend te=cpu,vae=cpu` |
| `list_devices_mac.txt` | this Mac | `MTL0\tApple M2 Pro\nBLAS\tAccelerate\nCPU\tApple M2 Pro\n` |
| `list_devices_win_iris.txt` | synthesised from the field log device names | `Vulkan0\tIntel(R) Iris(R) Xe Graphics\nCPU\t11th Gen Intel(R) Core(TM) i5-1135G7\n` |
| `missing_model.log` | this Mac | `[W] loading diffusion model from '/nonexistent.gguf' failed`, `[I] new_sd_ctx_t failed` |

The reference image `~/Documents/VirtuDoc/test_cpu.png` (512x512, 401,944 bytes) is not copied
into the repo (images are never committed).

### 2.5 Progress parser specification

Input: the child's merged stdout+stderr (`stderr=STDOUT`), read in binary chunks, decoded UTF-8
with `errors="replace"`, split on `\r` and `\n`, each piece with `\x1b[K` removed and trailing
spaces stripped. Empty pieces are ignored.

```
BAR     = r"^\|[=> #]*\|\s+(?P<k>\d+)/(?P<n>\d+) - +(?P<speed>[\d.]+)(?P<unit>s/it|it/s)(?: - ETA (?P<eta>[\d:]+))?$"
LOADBAR = r"^\|#*\s*\|\s+\d+/\d+ - .*B/s$"                         # tensor loading: ignore
ENCODED = r"^\[I\] get_learned_condition completed, taking (?P<s>[\d.]+)s"
GENSTART= r"^\[I\] generating image: \d+/\d+ - seed (?P<seed>\d+)"
SAMPLED = r"^\[I\] sampling completed, taking (?P<s>[\d.]+)s"
DECODE  = r"^\[I\] decoding \d+ latents"
DECODED = r"^\[I\] latent \d+ decoded, taking (?P<s>[\d.]+)s"
DONE    = r"^\[I\] generate_image completed in (?P<s>[\d.]+)s"
SAVED   = r"^\[I\] save result image \d+ to '(?P<path>.*)' \((?P<ok>success|failure)\)"
GPU_OOM = r"ErrorOutOfDeviceMemory|failed to allocate (Vulkan|CUDA|Metal|MTL)\d* buffer"
RAM_OOM = r"std::bad_alloc|failed to allocate CPU buffer|ggml_aligned_malloc: insufficient memory"
NOMODEL = r"^\[W\] loading (diffusion model|llm|vae) from '.*' failed"
```

State: `phase ∈ {start, encoding, denoising, decoding, done}`. Events emitted:

- on start → `("encoding", 0, 0)` (emitted by the engine before spawning, contract item 2);
- `GENSTART` → phase `denoising`;
- `BAR` while `denoising` → `("denoising", k, n)`; `n` is the step count sd-cli actually ran;
- `SAMPLED` → `("decoding", steps, steps)`, phase `decoding`;
- `BAR` while `decoding` → ignored (VAE tiles; the UI has no sub-phase);
- `DONE`/`SAVED` → phase `done`, `saved_path`, `saved_ok`;
- any line matching `GPU_OOM` / `RAM_OOM` / `NOMODEL` → remembered as `failure_class`;
- the last 60 lines are kept as `tail` for error messages and the terminal log.

`ProgressParser` is pure (no I/O) so it is tested on the fixtures alone.

### 2.6 Failure classification (plain-language errors)

`classify_failure(returncode, parser) -> tuple[cause, fix]`, used only when the run did not produce
a PNG:

| Class | Trigger | cause | fix |
|---|---|---|---|
| `gpu_oom` | `GPU_OOM` match | "The graphics chip ran out of memory." | "Using the processor instead; this is slower but works." (engine retries on cpu once, S14; if the device was already cpu this class cannot occur) |
| `ram_oom` | `RAM_OOM` match, or rc < 0 / rc ≥ 0xC0000000 with no other class | "The computer ran out of memory while making the image." | "Close other programs (browser, Teams), pick the 512x512 draft size, then try again." |
| `no_model` | `NOMODEL` match | "A model file is missing or damaged." | "Run setup again; it re-downloads only what is missing." |
| `no_binary` | `FileNotFoundError` / `PermissionError` on spawn | "The image program (sd-cli) is not installed." | "Run setup again." |
| `cancelled` | killed by us | raises `Cancelled` | — |
| `unknown` | anything else | "The image program stopped with code N." + last `[E]` line | "Try again; if it repeats, run `assess --json` and send the output to the project owner." |

Every cause/fix pair is a `MedimgError` (`Invalid`/`ModelUnavailable`), so `/api/status` errors and
the sheet's `Error` column carry the text unchanged.

---

## 3. Pinned interface

Workers implement exactly these names. Anything not pinned is the worker's choice.

### 3.1 `medimg/config.py` additions (S-A)

```python
SDCPP_RELEASE_TAG = "master-1015-e41fbcf"
SDCPP_MODEL_ID = "leejet/Z-Image-Turbo-GGUF"
SDCPP_DEFAULT_STEPS = 8
SDCPP_SIZE_PRESETS = [("512x512 draft", 512, 512), ("768x768", 768, 768), ("1024x1024", 1024, 1024),
                      ("768x1344 portrait", 768, 1344), ("1344x768 landscape", 1344, 768),
                      ("832x1216", 832, 1216), ("1216x832", 1216, 832)]
SDCPP_WARN_OVER_S = 900
SDCPP_MIN_RAM_GB = 7.0
TOOLS_DIR = Path.home() / ".medical-image-gen" / "tools"       # binaries; never in the repo
ENGINE_CHOICES = ("auto", "sdcpp")                              # --engine values

@dataclass
class Settings:                      # four new optional fields, all default None
    ...
    engine: str | None = None        # "sdcpp" or None (= auto); set by `setup --engine`
    sdcpp_device: str | None = None  # "cpu" | "vulkan0" | "metal"; None = from the profile
    sdcpp_tier: str | None = None    # "low" | "mid" | "high"; None = from RAM
    sdcpp_threads: int | None = None # None = sd-cli default (physical cores)
```

`load_settings` accepts the new keys with the same validation style (unknown values → default);
`save_settings` writes them.

### 3.2 `medimg/sdcpp/` package

```python
# medimg/sdcpp/pins.py  (S-A) — data only, no I/O
@dataclass(frozen=True)
class Asset: key: str; name: str; url: str; size: int; sha256: str; exe: str   # exe = "sd-cli" | "sd-cli.exe"
ASSETS: dict[str, Asset]            # keys: win-vulkan-x64, win-cpu-x64, linux-vulkan-x64, linux-cpu-x64, mac-arm64 (section 2.1)
@dataclass(frozen=True)
class ModelFile: repo: str; revision: str; filename: str; gb: float; sha256: str
TIERS: dict[str, dict[str, ModelFile]]   # tier -> {"diffusion", "llm", "vae"} (section 2.2)
TIER_GB: dict[str, float]           # {"low": 5.0, "mid": 5.56, "high": 6.7}
def tier_for_ram(ram_total_gb: float) -> str          # <12 low, <24 mid, else high
def build_for(os_name: str, arch: str, *, cpu_fallback: bool = False) -> str | None
        # ("Windows","x86_64") -> "win-vulkan-x64" / "win-cpu-x64"; ("Linux","x86_64") -> linux-*; ("Darwin","arm64") -> "mac-arm64"; else None
def binary_dir(build: str, tools_dir: Path = TOOLS_DIR) -> Path   # tools_dir / "sdcpp" / SDCPP_RELEASE_TAG / build

# medimg/sdcpp/install.py  (S-A) — the only module that downloads binaries
@dataclass
class SdcppPaths:
    sd_cli: tuple[str, ...]          # command prefix, e.g. ("/path/sd-cli",) or (sys.executable, "-I", "fake.py")
    cwd: Path                        # the build folder (ggml backend DLL discovery, S3)
    diffusion: Path; llm: Path; vae: Path
    build: str; tier: str; release: str = SDCPP_RELEASE_TAG
def binary_cached(build: str, tools_dir: Path = TOOLS_DIR) -> Path | None     # exe path when present and executable
def install_binary(build: str, progress=print, *, tools_dir: Path = TOOLS_DIR, opener=urllib.request.urlopen) -> Path
        # .part + Range resume, SHA256 check (raise ModelUnavailable on mismatch, delete the file), extract into an EMPTY folder, chmod +x on POSIX
def models_cached(tier: str) -> dict[str, Path] | None          # hf_hub_download(local_files_only=True) for the three files, else None
def download_models(tier: str, progress=print) -> dict[str, Path]   # hf_hub_download each; then verify_sha256 each (raise ModelUnavailable + delete on mismatch)
def verify_sha256(path: Path, expected: str, progress=None) -> None
def list_devices(sd_cli: tuple[str, ...], cwd: Path, run=subprocess.run) -> list[tuple[str, str]]
        # runs [*sd_cli, "--list-devices"], parses "name\tdesc" lines from stdout; raises ModelUnavailable on non-zero/timeout(60 s)
def health_check(sd_cli, cwd, run=subprocess.run) -> str          # returns the --version line; raises ModelUnavailable
def resolve_paths(build: str, tier: str, *, tools_dir: Path = TOOLS_DIR) -> SdcppPaths   # raises ModelUnavailable("run setup") if anything is missing

# medimg/sdcpp/progress.py  (S-B) — pure
@dataclass
class ParseState: phase: str; step: int; step_total: int; failure_class: str | None; saved_path: str | None; saved_ok: bool | None;
                  encode_s: float | None; sample_s: float | None; decode_s: float | None; total_s: float | None; tail: list[str]
class ProgressParser:
    def __init__(self): ...
    def feed(self, text: str) -> list[tuple[str, int, int]]      # returns progress events (phase, k, n) in order
    @property
    def state(self) -> ParseState
def split_lines(chunk: str) -> list[str]                           # \r and \n, strip \x1b[K
def classify_failure(returncode: int | None, state: ParseState) -> tuple[str, str, str]   # (class, cause, fix) per 2.6

# medimg/sdcpp/procs.py  (S-C)
def popen_group(argv: list[str], cwd: Path, *, env: dict | None = None) -> subprocess.Popen
        # stdout=PIPE, stderr=STDOUT, stdin=DEVNULL; POSIX start_new_session=True; Windows CREATE_NEW_PROCESS_GROUP|CREATE_NO_WINDOW
def kill_tree(proc: subprocess.Popen, grace_s: float = 3.0) -> None   # S12; idempotent; never raises
class MemSampler:                                                   # thread; S13
    def __init__(self, pid: int, interval_s: float = 0.5): ...
    def start(self) -> None; def stop(self) -> float               # returns peak bytes (0.0 if the process vanished first)
```

### 3.3 `medimg/engines/sdcpp_engine.py` (S-C) — implements `Engine` exactly

```python
class SdcppEngine:
    name = "sdcpp"
    model_id: str                 # f"{SDCPP_MODEL_ID}/{paths.diffusion.name}", e.g. "leejet/Z-Image-Turbo-GGUF/z_image_turbo-Q3_K.gguf"
    loaded: bool
    def __init__(self, paths: SdcppPaths, device: str = "cpu", *, threads: int | None = None,
                 popen=popen_group, mem_sampler=MemSampler, poll_s: float = 0.25): ...
    def load(self, on_progress: ProgressFn | None = None) -> None    # checks the files exist (ModelUnavailable otherwise); on_progress("loading",0,0)/("loading",1,1); no process
    def unload(self) -> None                                         # loaded=False; nothing else to free
    def generate(self, prompt, seed, steps, width, height, on_progress, should_cancel) -> GenResult
    device: str                   # may change to "cpu" after a GPU-OOM fallback (S14)
    notes: list[str]              # fallback messages, newest last

def build_argv(paths: SdcppPaths, device: str, prompt: str, seed: int, steps: int, width: int, height: int,
               out_path: Path, threads: int | None = None) -> list[str]
```

`build_argv` returns exactly:

```
[*paths.sd_cli,
 "--diffusion-model", str(paths.diffusion), "--llm", str(paths.llm), "--vae", str(paths.vae),
 "-p", prompt, "--cfg-scale", "1.0", "--steps", str(steps), "-W", str(width), "-H", str(height),
 "-s", str(seed), "-o", str(out_path), "--backend", device,
 "--offload-to-cpu", "--mmap", "--vae-tiling", "--log-level", "info"]
+ (["--threads", str(threads)] if threads else [])
```

A prompt that starts with `-` is passed as `" " + prompt` (sd-cli's parser would read it as a flag).

`generate` contract (the existing six rules plus):

1. `RuntimeError("engine not loaded")` when not loaded.
2. `on_progress("encoding", 0, 0)` before spawning; then the parser's events; `("decoding", steps, steps)` comes from `SAMPLED`.
3. Reader loop: `select`-free blocking reads on a helper thread feeding a queue; the main loop wakes every `poll_s` to check `should_cancel()`; on True → `kill_tree`, remove the temp folder, raise `Cancelled`.
4. Temp output: `tempfile.mkdtemp(prefix="medimg-sdcpp-")` / `out.png`; after exit 0 and `saved_ok`, the PNG is opened with PIL, `.load()`ed and copied (`image.copy()`), then the folder is deleted in `finally`.
5. `peak_mem_gb = MemSampler.stop() / 1e9`; `time_s` = wall time of `generate()`.
6. On failure: `classify_failure`; if class is `gpu_oom` and `self.device != "cpu"` and this is the first attempt → `self.device = "cpu"`, append the note, rerun once from step 2 (`on_progress("encoding", 0, 0)` again); else raise the `MedimgError`.
7. `GenResult.engine = f"sdcpp {paths.release}"` + `" (cpu, fallback)"` when a fallback happened in this call; `steps` = the `n` seen in the denoising bars if any, else `steps`.
8. Never imports anything heavy; `subprocess`, `psutil`, `PIL` only. Stdout is also mirrored to `logging.getLogger("medimg.sdcpp")` at DEBUG so the terminal log keeps the sd-cli tail on failure (INFO for `[E]` lines).

`make_engine("sdcpp", profile)` (S-C, in `engines/__init__.py`): reads `profile["backend"]["device"]`
(default `"cpu"`), `profile["backend"]["sdcpp"]["tier"]` / `["build"]` (defaults: tier from
`load_settings().sdcpp_tier` or `tier_for_ram(profile.machine.ram_total_gb)`, build from
`build_for(platform.system(), platform.machine())`), settings overrides `sdcpp_device` and
`sdcpp_threads`, then `resolve_paths(build, tier)` → `SdcppEngine(paths, device, threads=...)`.

### 3.4 Assess changes (S-D)

```python
# medimg/assess/decide.py
@dataclass
class Decision:                       # two appended fields, defaults keep positional callers valid
    ...existing nine fields...
    device: str | None = None         # sdcpp: "cpu" | "vulkan0" | "metal"
    tier: str | None = None           # sdcpp tier

def decide(m: Machine, *, engine: str | None = None) -> Decision
```

Rules added, evaluated after the existing Darwin/NVIDIA rules (unchanged for the machines they
accept):

- `engine == "sdcpp"` → skip straight to the sdcpp rules (any OS; Intel Mac still unsupported).
- `engine in (None, "auto")`, OS Windows/Linux, and the NVIDIA rule did **not** return a supported
  decision (no GPU, AMD, Intel, NVIDIA without smi, old driver, VRAM < 7.5) → sdcpp rules with
  `reason` prefixed by the NVIDIA reason ("No NVIDIA GPU found. Using the processor/graphics chip
  through stable-diffusion.cpp." / "NVIDIA driver 560 is older than 570.65 … using sd.cpp instead").
- sdcpp rules: `ram < SDCPP_MIN_RAM_GB` → unsupported ("… has 6 GB RAM; at least 8 GB is needed",
  fix "use a computer with 8 GB or more"); `tier = tier_for_ram(ram)`; `device` per S6
  (`vulkan0` candidate for amd, intel with ram ≥ 16, nvidia; `metal` on Darwin/arm64; else `cpu`);
  `download_gb = TIER_GB[tier]` minus files already cached (`models_cached`), binary size ignored
  (< 0.05 GB); `min_disk_gb = download + DISK_MARGIN_GB`; disk check as the other backends;
  `unload_after_job = False`; `model_id = SDCPP_MODEL_ID`; `offload_mode = None`;
  `backend = "sdcpp"`, `supported = True`, reason e.g. "Windows without an NVIDIA GPU: sd.cpp on the
  processor, tier mid (12-24 GB RAM)".

```python
# medimg/assess/__init__.py  run(args)
```
- new arg `engine` (from `--engine`; `None` → `load_settings().engine`).
- for `decision.backend == "sdcpp"`: before benchmarking, `install.list_devices(...)` (skipped with
  `--no-benchmark`); if the candidate device is not listed → `device = "cpu"` with a note. Benchmark
  with `sizes=SDCPP_BENCH_SIZES = ((512, 512, 4), (768, 768, 2))`; if the candidate device fails
  (any exception) → note `f"Graphics chip benchmark failed on {dev}: {cause}; using the processor"`,
  rebuild the engine with `device="cpu"`, benchmark again. The final device goes into the profile.
- `_engine_version` returns `f"sdcpp {SDCPP_RELEASE_TAG}"` for sdcpp (no Python package to ask).

```python
# medimg/assess/profile.py build_profile(..., device: str | None = None, sdcpp: dict | None = None)
```
writes `backend.device` and `backend.sdcpp = {"release", "build", "tier", "vulkan_tried": bool,
"vulkan_error": str | None}` (or `None` for other backends). `report.py` prints
"Backend sdcpp on cpu (tier mid: Q3_K image model)" and the sdcpp notes.

### 3.5 Setup, download, smoke, CLI (S-E)

- `__main__.py`: `--engine {auto,sdcpp}` on `setup`, `assess`, `serve`, `smoke` (default `None`).
  `setup --engine X` saves `Settings.engine` (`"sdcpp"` or `None` for auto) before step 1.
- `download.py`: `sdcpp_cached(tier, build) -> bool` and `download_sdcpp(tier, build, progress) ->
  SdcppPaths` wrapping `install.*` (binary first — 30 MB, fast feedback — then models, then SHA256
  pass, then `health_check`). On a failed health check of a Vulkan build: download the CPU build
  (`build_for(..., cpu_fallback=True)`) and return it; the chosen build is printed and goes to the profile.
- `setup_cmd.py`: step 1 passes `engine` into `decide`; step 2 for sdcpp prints
  `✔ already done (no extra Python packages needed)`; step 3 uses `download.sdcpp_cached` /
  `download_sdcpp` with the tier's GB in the confirmation; steps 4–6 unchanged (smoke runs
  `512x512 @ 4 steps` through `make_engine("sdcpp", …)`; `_assess_done` also compares
  `backend.device`). Re-running setup after a crash skips every finished download (HF cache hit +
  binary present) — this is the "resumable" acceptance test.
- `smoke.py`: `_make_engine` passes `engine` to `decide`; prints "Loading the model (sdcpp on cpu)…".
- Launchers (`setup.*`, `start.*`, `assess.*`): unchanged — they already forward `"$@"` / `%*`, so
  `./setup.sh --engine sdcpp` works.

### 3.6 Server and UI (S-F)

JSON changes are **additive only**:

- `GET /api/config`: `defaults.steps` = `SDCPP_DEFAULT_STEPS` when `engine.name == "sdcpp"` and the
  user has not saved a `steps` setting (`settings.steps == DEFAULT_STEPS` and the settings file has
  no `steps` key — `load_settings` gains a `steps_explicit: bool` attribute, not a field);
  `size_presets` = `SDCPP_SIZE_PRESETS` for sdcpp; new keys `"warn_over_s": 900 | null` and
  `"device": "cpu" | "vulkan0" | "metal" | null`; `nvidia_unverified` unchanged.
- `GET /api/device`: `unverified` additionally true when `engine.name == "sdcpp"` and the profile
  has no `actuals` (banner text generic: "This engine has no real-run record on this computer yet";
  the current NVIDIA sentence moves to a condition on `backend == "diffusers"`).
- `serve`: `--engine` honoured when no profile exists (same path as today's auto-decide).
- UI (`static/`): status strip shows `device` after the model state ("ready · cpu"); Single tab
  shows "≈ X min on this machine" under the size preset (uses `/api/device` estimates it already
  fetches) and a warning line when `seconds > warn_over_s`; batch tab shows the same warning when
  the per-image estimate exceeds it; Steps label text from `/api/config` (`"8 recommended"` for
  sdcpp). No new routes.

### 3.7 Fake sd-cli (S-C owns; S-F and CI use it)

`tests/stubs/fake_sd_cli.py`, run as `(sys.executable, "-I", path)`:

- `--version` → prints the version line, exit 0; `--list-devices` → `Vulkan0\tFake GPU\nCPU\tFake CPU\n`, exit 0.
- generation: parses the exact flags from `build_argv` (unknown flag → exit 1 with a usage line);
  prints the fixture-shaped lines (`[I] get_learned_condition completed…`, `[I] generating image:
  1/1 - seed S`, one `\r` bar per step with `s/it` and ETA, `[I] sampling completed…`, `[I]
  decoding 1 latents`, 3 VAE tile bars, `[I] latent 1 decoded…`, `[I] generate_image completed…`,
  `[I] save result image 0 to '<out>' (success)`), sleeping `FAKE_SD_CLI_STEP_S` (default 0.02)
  per step, writes a `WxH` RGB PNG whose colour derives from the seed, exit 0.
- `FAKE_SD_CLI_FAIL=gpu_oom` and `--backend` ≠ `cpu` → prints the `vulkan_oom_text_encoder.log`
  tail, exit 1 (fallback test); `FAKE_SD_CLI_FAIL=ram_oom` → `std::bad_alloc` line, exit 1;
  `FAKE_SD_CLI_FAIL=no_model` → the missing-model lines, exit 1.
- `FAKE_SD_CLI_HANG=1` → after step 1 sleeps 600 s (cancel/kill test; must die on both OSes).
- `FAKE_SD_CLI_BAD_FLAGS=1` → exit 1 if `--log-level info` or `--cfg-scale 1.0` is missing (argv regression guard).

---

## 4. Task breakdown and file ownership

Every file is owned by exactly one task in this run. A worker that needs a change elsewhere asks the
Manager. Tests run with `uv run --no-sync pytest -q`; "done" = the task's tests pass and the full
suite passes.

| # | Task | Deps | Owns | Acceptance tests | Est. |
|---|---|---|---|---|---|
| S-A | **Pins, config, install.** `medimg/sdcpp/__init__.py`, `pins.py`, `install.py`; `config.py` additions (3.1); `tests/test_sdcpp_pins.py`, `tests/test_sdcpp_install.py`, `tests/test_config.py` (extend), `tests/fixtures/sdcpp/list_devices_*.txt`. | none | as listed | `ASSETS` has the five keys with the exact names, sizes and SHA256 of 2.1; `TIERS` matches 2.2 and `TIER_GB` within 0.01; `tier_for_ram(7.7)=="low"`, `(16)=="mid"`, `(32)=="high"`; `build_for` table incl. `None` for Intel Mac / arm Linux; `install_binary` with a fake `opener` serving a zip: writes `.part`, resumes with a `Range` header when a `.part` exists, rejects a wrong SHA256 with `ModelUnavailable` and deletes the file, extracts into an empty folder and `chmod`s `sd-cli` (POSIX); `binary_cached` None/Path; `models_cached` uses `local_files_only=True` and the pinned `revision` (monkeypatched `hf_hub_download` records kwargs); `download_models` verifies SHA256 and deletes a mismatching file; `list_devices` parses `list_devices_mac.txt` into 3 tuples and raises on rc 1; `Settings` round-trips the four new keys and ignores bad values. No network in tests. | 90 min |
| S-B | **Progress parser + failure classifier.** `medimg/sdcpp/progress.py`; `tests/test_sdcpp_progress.py`; `tests/fixtures/sdcpp/*.log` (2.4). | none | as listed | Feeding `cpu_success_512_8steps.log` in random chunk sizes (1, 7, 4096 bytes) yields exactly `[("denoising",1,8)…("denoising",8,8),("decoding",8,8)]`, `sample_s==269.75`, `decode_s==69.28`, `total_s==342.29`, `saved_ok` True, `saved_path=="test_cpu.png"`; the 9 VAE tile bars and the `#` loading bars produce no events; `vulkan_oom_text_encoder.log` → `failure_class=="gpu_oom"` and `classify_failure(1, state)` returns the exact cause "The graphics chip ran out of memory."; `vulkan_oom_diffusion_te_cpu.log` same; `missing_model.log` → `no_model`; rc `-9`/`0xC0000005` with no class → `ram_oom`; unknown rc 1 → `unknown` with the last `[E]` line in the cause; `split_lines` strips `\x1b[K` and handles a `\r` split across chunks; `tail` keeps ≤ 60 lines. | 60 min |
| S-C | **Process control, engine, fake sd-cli, factory.** `medimg/sdcpp/procs.py`, `medimg/engines/sdcpp_engine.py`, `medimg/engines/__init__.py`, `tests/stubs/fake_sd_cli.py`, `tests/test_sdcpp_procs.py`, `tests/test_sdcpp_engine.py`. | S-A, S-B | as listed | `build_argv` equals the list in 3.3 token for token (incl. `--threads` case and the leading-dash prompt); `import medimg.engines.sdcpp_engine` imports no `torch`/`mflux`; generate before load raises `RuntimeError("engine not loaded")`; `load` raises `ModelUnavailable` with fix "run setup" when a file is missing; with the fake sd-cli: progress sequence `encoding → denoising 1..n → decoding`, a `GenResult` with a `W×H` PIL image, `seed`, `steps`, `engine=="sdcpp master-1015-e41fbcf"`, `model_id` ends with the gguf name, `peak_mem_gb > 0`, temp folder removed; cancel with `FAKE_SD_CLI_HANG=1`: `should_cancel` flips after the first denoising event → `Cancelled` within 5 s, the child is gone (`psutil.pid_exists` False after `kill_tree`), temp folder removed — this test runs on ubuntu and windows CI; `FAKE_SD_CLI_FAIL=gpu_oom` with `device="vulkan0"`: second attempt on `cpu`, image returned, `engine` ends with "(cpu, fallback)", `engine.device=="cpu"`, `notes[-1]` contains "graphics chip ran out of memory"; same with `device="cpu"` → raises with the `gpu_oom` text never used, `ram_oom`/`no_model` texts exact; `make_engine("sdcpp", profile)` builds the engine from the profile's device/tier/build and from settings overrides (monkeypatched `resolve_paths`). `kill_tree` on an already-exited process does not raise. `MemSampler` on the current process returns > 0. | 150 min |
| S-D | **Assess routing, Vulkan try, profile, report.** `medimg/assess/decide.py`, `assess/__init__.py`, `assess/profile.py`, `assess/report.py`; `tests/test_assess_decide.py` (modify), `tests/test_assess_profile.py` (modify), `tests/test_assess_run_sdcpp.py` (new), `tests/fixtures/assess/*` additions (e.g. a `wmic_gpu_iris.txt`, `lspci_amd.txt`). | S-A | as listed | Decision table: Windows i5-1135G7/Iris Xe/7.7 GB (the field laptop) → `sdcpp`, `device=="cpu"`, `tier=="low"`, `download_gb==5.0`, `unload_after_job` False; Windows no GPU 16 GB → `sdcpp`/`cpu`/`mid`; Windows Intel iGPU 16 GB → `device=="vulkan0"`; Windows AMD 8 GB RAM → `vulkan0`, `low`; Linux no GPU 32 GB → `cpu`, `high`; Windows NVIDIA driver 560 → `sdcpp` with "570.65" in the reason; NVIDIA 6 GB → `sdcpp`; NVIDIA without smi → `sdcpp`; 6 GB RAM → unsupported with "8 GB"; disk short → unsupported with numbers; Intel Mac → unsupported (unchanged); M2 Pro → `mflux` (unchanged) and with `engine="sdcpp"` → `sdcpp`/`metal`/`mid`; NVIDIA RTX 4070 → `diffusers` (unchanged) and with `engine="sdcpp"` → `sdcpp`/`vulkan0`. `run()` with a stub engine whose first (vulkan) benchmark raises → profile `backend.device=="cpu"`, `sdcpp.vulkan_tried` True, `vulkan_error` set, a note present, benchmark points from the cpu run, `sizes` passed == `SDCPP_BENCH_SIZES`; candidate not in `list_devices` → cpu without a benchmark attempt. `build_profile` writes `backend.device`/`backend.sdcpp`; existing profile tests unchanged; `render_report` mentions the device and tier. | 120 min |
| S-E | **Setup, download, smoke, CLI.** `medimg/setup_cmd.py`, `medimg/download.py`, `medimg/smoke.py`, `medimg/__main__.py`; `tests/test_setup_cmd.py`, `tests/test_download.py`, `tests/test_smoke.py`, `tests/test_cli.py` (all modify). | S-A, S-C, S-D | as listed | `python -m medimg setup --engine sdcpp --help` parses on all four commands; `setup --engine sdcpp` saves `engine="sdcpp"` and `--engine auto` clears it; with the `World` fake extended for sdcpp: first run calls binary install → models → sha pass → health check → smoke → assess in that order; second run prints `✔ already done` for steps 2–5 and downloads nothing; a run interrupted after the binary (models missing) re-runs only the model step; wrong-SHA model → plain message and exit 1; health-check failure on the Vulkan build → CPU build downloaded and used; disk check uses the tier GB; `smoke --engine sdcpp --fake-engine` still uses FakeEngine; `download_sdcpp` is never called when `HF_HUB_OFFLINE` would block (setup does not set it). | 90 min |
| S-F | **Server + UI.** `medimg/server.py`, `medimg/static/*`; `tests/test_api_sdcpp.py` (new), `tests/test_api_misc.py`, `tests/test_static_ui.py` (modify). | S-C, S-D | as listed | Full flow with `create_app(SdcppEngine(fake paths), …)`: upload sample sheet → counts → `POST /api/jobs/batch count=2` → poll → 2 images in `/api/gallery/images` with sidecars whose `engine` starts with `sdcpp`, sheet rows `done` with seed/time/machine; single image; regenerate; cancel mid-batch with `FAKE_SD_CLI_HANG=1` → finished row done, current row pending, child gone; blocked prompt → 422 before any process starts (assert the fake was never invoked); `/api/config` for sdcpp: `defaults.steps==8` (and the saved-steps case keeps the user value), `size_presets[0].label=="512x512 draft"`, `warn_over_s==900`, `device=="cpu"`; for mflux/fake: `warn_over_s is None`, presets unchanged, every existing key present. `/api/device.unverified` true for sdcpp without actuals, false after one actual. Static: `grep -E "https?://"` finds nothing; the warning element and device label exist in `index.html` with ids listed in its header comment. This file runs on ubuntu + windows CI. | 150 min |
| S-G | **Docs + CI + licences.** `README.md`, `docs/SETUP_WINDOWS_SDCPP.md` (new, Windows and Linux without NVIDIA; Linux section inside), `docs/SETUP_MAC.md` (one paragraph on `--engine sdcpp`), `docs/ARCHITECTURE.md`, `docs/HARDWARE_ALTERNATIVES.md`, `docs/SAFETY_AND_LICENCES.md`, `docs/TROUBLESHOOTING.md`, `docs/FUTURE.md`, `.github/workflows/tests.yml` (only if S-C/S-F need a change; expected none), `tests/test_docs_commands.py`, `tests/test_ci_workflow.py`. | S-E, S-F | as listed | `EXPECTED_DOCS` includes `SETUP_WINDOWS_SDCPP`; every fenced command parses (incl. `--engine sdcpp`); README requirements table has a third column "Windows/Linux without NVIDIA: 8 GB RAM, 11 GB disk, slow (5-6 min per 512x512 draft on a 2021 laptop CPU)"; SAFETY_AND_LICENCES lists sd.cpp MIT, ggml MIT, and the three Apache-2.0 model repos with the "check before commercial use" sentence; TROUBLESHOOTING adds rows: "graphics chip ran out of memory", "image program not installed", "very slow (processor-only)", "Windows SmartScreen / macOS Gatekeeper blocks sd-cli"; HARDWARE_ALTERNATIVES section 2 marked "built in v0.2 (sdcpp engine)"; ARCHITECTURE lists the fourth engine and the `medimg/sdcpp/` package; FUTURE adds sd-server. No developer vocabulary in the setup doc (reviewer reads it as the intern). | 120 min |
| S-H | **Verifier: real run on this Mac** (not a worker). | all | `VERIFICATION_SDCPP.md` | Section 6. | 60 min |

Sequence: {S-A, S-B} in parallel → S-C → {S-D, S-E, S-F} in parallel (S-E waits for S-D's
`decide` signature; S-F waits for S-D's profile keys) → S-G → Reviewer → Fixers → S-H.
Critical path ≈ 90 + 150 + 150 + 120 ≈ 8.5 h worker time.

`.gitignore` already ignores `*.gguf`, `*.safetensors`, `*.png`, `device_profile.json`; the tools
folder is outside the repo. S-A adds `/tools-cache/` only if it introduces a repo-local cache
(it must not).

---

## 5. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Vulkan DLL present but no usable Vulkan driver** (old Intel driver, VM, RDP session) crashes `sd-cli` at startup instead of falling back. | Setup's `health_check` + `list_devices` on the Vulkan build; on failure download the CPU build (S-E). At run time `--backend cpu` still loads `ggml-vulkan.dll` (field log) — if that crashes, the CPU build is the fix, documented in TROUBLESHOOTING. |
| R2 | **Windows SmartScreen / antivirus** quarantines `sd-cli.exe`; **macOS Gatekeeper** blocks it when the zip came through a browser. | We download with `urllib` (no quarantine attribute) and run from `~/.medical-image-gen/`; the doc has the "More info → Run anyway" and `xattr -d com.apple.quarantine` steps. Verified: the Mac binary ran from a curl download without prompts. |
| R3 | **RAM OOM on 8 GB laptops at 768² or larger**, or when a browser is open. | Tier `low`, `--vae-tiling`, `--mmap`, draft preset first, the `ram_oom` message names the fix, docs say "close other apps". The field laptop finished with 3.7 GB free. |
| R4 | **Intern-grade speed:** 5.7 min per 512² draft, ~20+ min per 1024² on the field laptop. | 15-minute warning, batch suggestion from the estimate, docs set expectations ("overnight batches"). Not a correctness risk. |
| R5 | **Estimates for large sizes on CPU are rough** (VAE decode scales with pixels but the overhead term is fixed from the 512² point). | Actuals override after one image (D24). The Verifier checks the warning fires for 1024² on CPU, not ±30 % at 1024². If the Manager wants better curves, the only change is in `bench.py` (use the parser's `decode_s` as overhead per point) — out of scope this run. |
| R6 | **Release asset removal/rename upstream** (releases are per commit; old tags can be pruned). | Pinned SHA256; if the URL dies, change `SDCPP_RELEASE_TAG` and re-pin (one file, S-A). Docs tell the intern to ask for a newer zip link. |
| R7 | **`sd-cli` output format changes** in a future release break the parser. | Parser tests on verbatim fixtures; any tag bump re-runs the Verifier's real run and updates fixtures. |
| R8 | **Universal macOS binary minimum OS**: built on macOS 26.6.2; older macOS may refuse it. | Mac is an override path only; documented. |
| R9 | **`--backend metal` on this Mac** could fail on some op; CPU fallback exists (`device="cpu"` via `sdcpp_device` setting or the automatic OOM fallback). | Verifier records which device ran; if Metal fails for a non-OOM reason, set `sdcpp_device: "cpu"` and note it. |
| R10 | **Windows cancel leaves orphans** if `taskkill` is missing from PATH (hardened images). | `kill_tree` falls back to `proc.kill()` on the group leader plus `psutil` children iteration. Tested on windows CI with the hanging fake. |
| R11 | **Two `uv run` processes** (assess benchmark + serve) could run `sd-cli` concurrently on an 8 GB machine. | Unchanged from today (the worker already serialises jobs inside one server); setup runs assess before serve. |
| R12 | **Q2_K anatomy quality** may be too low for clinical drafts. | Tier `mid` on ≥ 12 GB machines; HARDWARE_ALTERNATIVES notes Q4_0/Q6_K/Q8_0 sizes for a future tier; clinician review rule unchanged. |

---

## 6. Acceptance criteria for the Verifier (evidence = command + output)

1. **Contract tests pass** (`uv run --no-sync pytest -q tests/test_sdcpp_*.py tests/test_api_sdcpp.py`):
   argv built exactly (3.3), progress parsed from all three field fixtures, cancel kills the child
   (`pid_exists` False), each failure class yields its plain-language text, `gpu_oom` on `vulkan0`
   falls back to `cpu` with the "(cpu, fallback)" engine string and the note "The graphics chip ran
   out of memory; using the processor".
2. **Routing:** `decide()` on the field laptop's `Machine` (Windows, `11th Gen Intel(R) Core(TM)
   i5-1135G7`, Iris Xe, 7.7 GB, no nvidia-smi) returns `backend="sdcpp"`, `device="cpu"`,
   `tier="low"`, `download_gb==5.0`; NVIDIA RTX 4070 and M2 Pro cases unchanged; Intel Mac still
   unsupported.
3. **Setup is resumable:** the `World` tests show a second run downloading nothing, and a run with
   the binary present but models missing fetches only the models. On this Mac the real second
   `./setup.command --engine sdcpp` prints `✔ already done` for steps 2–5.
4. **Full API flow with the fake sd-cli** passes on ubuntu-latest and windows-latest (CI workflow
   valid; `uv run pytest -q` green with no GPU, no weights, no extra). The cancel test is in that
   file and runs on both.
5. **All existing tests green**: total count ≥ 417 + new, zero failures; `git ls-files` shows no
   `.gguf`, `.safetensors`, `.png`, `.xlsx` (except templates), `device_profile.json`, nothing under
   `~/.medical-image-gen/`.
6. **Docs accurate:** `tests/test_docs_commands.py` green; the Verifier follows
   `docs/SETUP_WINDOWS_SDCPP.md` step by step on this Mac where the step is OS-neutral and reads the
   Windows-only steps for developer vocabulary; README table updated; licences rows present.
7. **One real end-to-end run on this Mac** (downloads: tier `mid` = 5.56 GB + 37.6 MB binary;
   budget 6 GB; disk 22 GB free; mflux cache untouched):
   1. `./setup.command --engine sdcpp` → binary at
      `~/.medical-image-gen/tools/sdcpp/master-1015-e41fbcf/mac-arm64/sd-cli`, `--version` line
      printed, three model files with matching SHA256, smoke image `512x512 @ 4 steps` in
      `<root>/_smoke/`, assess with `backend.device` = `metal` (or `cpu` with the reason in `notes`)
      and `backend.sdcpp.tier == "mid"`, `device_profile.json` written.
   2. `./start.command` → UI shows "local only", model state, device label, Steps default 8,
      first preset `512x512 draft`.
   3. Upload `templates/image_prompts_sample.xlsx`, set size `512x512`, steps 4–8, Generate 1 →
      image at `<root>/<Subject>/<Unit>/<Lecture>/<Image Name>.png` with the `.json` sidecar whose
      `engine` is `sdcpp master-1015-e41fbcf` and `model_id` ends with `z_image_turbo-Q3_K.gguf`;
      sheet row `done` with seed, time, machine; `actuals` appended to the profile; the step bar
      moved during the run (observe `/api/status.job.step` changing).
   4. Press Cancel during a second image → row stays `pending`, no file, `pgrep sd-cli` empty
      within 5 s.
   5. Record load/encode/sample/decode seconds, peak RSS, device, and whether the 1024x1024
      estimate shows the 15-minute warning in the Single tab (expected: no on Metal, yes on CPU).
   6. Switch `start.command` back (`setup --engine auto` or delete `device_profile.json` and run
      `assess`) and confirm the Mac returns to `mflux` — existing behaviour untouched.
8. **No network at runtime:** with `HF_HUB_OFFLINE=1` already set by `serve`, run step 7.3 with
   Wi-Fi off (or `--no-browser` and `sudo pfctl` is not required: turning Wi-Fi off is enough) and
   confirm generation still works.
9. **Adults-only gate engine-agnostic:** a minor-term row in the sheet is `blocked` and the fake
   sd-cli is never invoked for it (test asserts call count); on the real run, a `Single` prompt
   without an age returns 422 before any process starts (`pgrep sd-cli` empty).

Write `VERIFICATION_SDCPP.md` with the evidence, then hand to the Commit phase.

---

## 7. Next action for the Manager

Dispatch S-A and S-B in parallel. S-A's first check: `uv run --no-sync python -c "from
medimg.sdcpp.pins import ASSETS; print(ASSETS['win-vulkan-x64'].sha256)"` prints
`259ceeb62f1069190d24c85ea1c4549d2d61deb0ef712510dbe98d79ce93a38b`. S-B's first check: the parser
reproduces the eight denoising events from `cpu_success_512_8steps.log`.
