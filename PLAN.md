# PLAN.md — medical-image-gen

Written by the Advisor (brief section 0) on 2026-10-26. Source of truth for the Manager and the
workers. The brief is `~/Documents/VirtuDoc/medical-image-gen_build_prompt.md`; where this plan and
the brief disagree, the brief wins and the Manager tells the Advisor.

Build rules repeated for every worker:

- Never modify `~/Documents/VirtuDoc/patient-imagegen/` (read-only reference) or anything outside
  `~/Documents/VirtuDoc/medical-image-gen/` (scratch/tmp excepted).
- No `git push`, no `gh repo create` (the Verifier/Push step does that, section 11 of the brief).
- Never download more than 6 GB. The Mac weights `filipstrand/Z-Image-Turbo-mflux-4bit`
  (snapshot `b3a8f31115a11f2f9e2fa0bfbc8d78dcc3e6568b`, 5.9 GB) are already in
  `~/.cache/huggingface/hub/`; never re-download them.
- Disk on this Mac is ~27 GB free. Never install `diffusers`, `accelerate` or a CUDA torch here.
  (`torch` itself is installed on the Mac only because `mflux==0.22.0` declares
  `torch>=2.13.0` as a hard dependency; the darwin PyPI wheel is CPU/MPS, ~70 MB.)
- No worker runs a real generation except the one named in T12 (smoke) and the Verifier.
- Tests never import `mflux`, `mlx`, `torch` or `diffusers`; they install stub modules into
  `sys.modules` (section 4.3).

---

## 1. Decisions (with reasons)

| # | Decision | Reason |
|---|---|---|
| D1 | **Python 3.12**, pinned in `.python-version` and `requires-python = ">=3.12,<3.13"`. | `diffusers==0.42.0` requires Python ≥3.11 and `pillow` 13 requires ≥3.11; `mflux==0.22.0` supports 3.10–3.14; `mlx 0.32.4` ships cp312 arm64 wheels; CUDA torch wheels exist for cp312 on Windows and Linux. 3.12 is the newest version every pinned dependency has prebuilt wheels for. uv downloads `cpython-3.12.13` (~30 MB) if missing. |
| D2 | **Test runner: `uv run pytest`** (also the CI command). `.venv/bin/python -m pytest` works on Mac/Linux but not on Windows (`.venv\Scripts\python`), so docs and the Manager use `uv run pytest` only. | One command on three OSes. |
| D3 | **Engine deps live in extras**, not base deps: `--extra mac` (`mflux==0.22.0`), `--extra nvidia` (`torch==2.9.1` from the cu128 index, `diffusers==0.41.0`, `transformers`, `accelerate`, `gguf`, `sentencepiece`, `protobuf`). Base deps are only FastAPI, uvicorn, python-multipart, openpyxl, pillow, psutil, huggingface-hub. The two extras are declared conflicting (`[tool.uv] conflicts`). | CI on ubuntu/windows runs `uv sync` with no extra, so no 2.5 GB torch download and no GPU. Setup picks the extra from the platform. The extras cannot be co-installed because mflux pins `torch>=2.13` while the NVIDIA stack pins `torch==2.9.1`. |
| D4 | **mflux stays at 0.22.0.** `mflux 0.23.0` (2026-10-16) exists but was not verified; callback signatures below were read from the installed 0.22.0 source. | Brief section 4: upgrade only if verified. Nobody verified 0.23.0. |
| D5 | **diffusers pinned at 0.41.0** (2026-10-06), **torch 2.9.1+cu128**, `transformers>=5.5,<6`, `accelerate>=1.0`. | Z-Image support landed in 0.36.0; the Turbo CFG-threshold fix is in 0.37.0; 0.41.0 is three weeks old and still accepts Python 3.10+. 0.42.0 (2026-10-23) is three days old. torch 2.9.1+cu128 is the newest torch that the cu128 index ships for **both** Windows and Linux cp312 (the Windows cu128 line stops at 2.9.1; newer Windows builds are cu126 or cu130). cu128 covers RTX 20–50 series (Blackwell needs ≥ cu128) and needs driver ≥ 570.26 Linux / ≥ 570.65 Windows. |
| D6 | **NVIDIA mode is chosen by VRAM** (section 5.3): ≥ 22 GB resident; 15–22 GB `enable_model_cpu_offload()`; 10–15 GB GGUF Q8_0 transformer + model offload (experimental); 7.5–10 GB GGUF Q4_K_M + `enable_sequential_cpu_offload()` (experimental); < 7.5 GB unsupported. | Weight arithmetic from the official repo file sizes: transformer 24.6 GB fp32 → 12.3 GB bf16, text encoder 8.05 GB bf16, VAE 0.17 GB. All resident ≈ 20.6 GB + activations → a 24 GB card. With model offload the peak is one component at a time (transformer 12.3 GB + activations) → fits 16 GB, which matches the model card's "fits within 16G VRAM". Below that the bf16 transformer does not fit, so a quantized transformer is the only route. |
| D7 | **Cancel on diffusers = set `pipe._interrupt = True` from `callback_on_step_end`**, then raise `Cancelled` after `pipe()` returns. Not an exception from inside the callback. | Verified in the 0.41.0 source: the loop does `if self.interrupt: continue` (line 506), so the remaining steps are skipped, the (garbage) latents are decoded, and `maybe_free_model_hooks()` (line 595) still runs, which matters with CPU offload. An exception would skip the hook cleanup. Cost: one VAE decode. |
| D8 | **Cancel on mflux = raise `StopImageGenerationException` inside `call_in_loop`.** | Verified in 0.22.0 `z_image.py`: the loop catches only `KeyboardInterrupt`, so the exception leaves `generate_image`. Same as patient-imagegen. |
| D9 | **One `GenerationWorker` thread, one job at a time, polling at 500 ms** (`GET /api/status`). No SSE/WebSocket. | Simplest thing that works offline in vanilla JS; same pattern as the reference UI. |
| D10 | **Statuses on upload:** `done` is never recomputed (trust the sheet). `failed` is kept unless "Retry failed rows" is on. `pending`/blank/`blocked`/`invalid` are recomputed on every upload (missing fields, size, rules, collisions, file-exists → done). Recomputed statuses and their `Error` text are written into the working copy at upload time. | Brief 6.2. Re-evaluating blocked/invalid lets an intern fix a row and re-upload. Writing at upload time means the downloaded sheet always carries the reasons. |
| D11 | **Image id = first 16 hex chars of sha1 of the forward-slash relative path** (`Subject/Unit/Lecture/Name.png`, or `_single/Name.png`). File routes resolve ids through the gallery index, never through user-supplied paths. | Stable across restarts, no path traversal surface. |
| D12 | **`device_profile.json` lives at the repo root**, gitignored. User settings live at `~/.medical-image-gen/config.json`. The output root defaults to `~/medical-image-gen-output/`. | The brief lists `device_profile.json` as a never-commit file in the repo. Settings must survive a `git pull`. |
| D13 | **Server auto-loads the last working sheet on start** (`<root>/_sheets/current.json` pointer) so a crashed batch resumes after restart without re-upload. Upload replaces it. | Acceptance 5 (kill + restart resumes). |
| D14 | **Write order per image: PNG → sidecar → sheet row.** | If the process dies between PNG and row update, the file-exists rule (6.2) marks the row done on the next validation. Never the reverse. |
| D15 | **Seed written back to both `Seed` and `Seed Used`** when the Seed cell was blank. Regenerate writes the new seed to both. | Brief 6.1: "a blank cell gets a random seed, which is written back". |
| D16 | **Regenerate** overwrites the PNG and sidecar, then updates the row in the currently loaded working sheet whose (Subject, Unit, Lecture, Image Name) match; if no sheet is loaded or no row matches, only the files change and the response says so. | A sidecar may come from a previous intern's sheet. |
| D17 | **`unload_after_job` default = True when total RAM ≤ 16 GB (mflux), False otherwise;** settable in the UI. | patient-imagegen measured 6–8 GB idle with the model resident on a 16 GB Mac; reloading costs ~8 s on a ~220 s job. |
| D18 | **Sizes are rounded down to multiples of 16, then validated:** each side 256–1536, pixels ≤ 1,048,576. | Brief 5.2 says round down (the reference rejected instead). 1344×768 = 1,032,192 fits. |
| D19 | **No `MemorySaver`, no `CallbackManager`**; tiling + 1 GB cache limit set by hand. | Brief 2.2; MemorySaver drops the text encoder on single-seed runs so the next job fails. |
| D20 | **`HF_HUB_OFFLINE=1` is set by `medimg/__main__.py` for `serve`, `smoke` and `assess`, never for `setup`.** Engine modules never touch the environment. | Brief 2.8: no network at runtime. Setup is the only downloader. |
| D21 | **Collisions are compared case-insensitively** on the sanitised relative path. | macOS and Windows file systems are case-insensitive. |
| D22 | **Sheet download reads the working file into memory under the sheet lock** and returns bytes, not a `FileResponse`. | On Windows, `os.replace` fails while another handle holds the file open. |
| D23 | **Thumbnails** are 256 px JPEGs under `<root>/_thumbs/<id>.jpg`, made lazily by `store`. | Gallery grids of hundreds of 1024² PNGs are too slow otherwise. |
| D24 | **ETA model:** per-step seconds scale with pixel count as a power law fitted from the two benchmark points; overhead (load/encode/decode) is the measured total minus steps × per-step. Real runs are appended to `actuals`; when ≥ 1 actual exists at a size, its rolling mean (last 10) wins for that size; with ≥ 2 distinct sizes in actuals the curve is refitted from actuals. | Brief 5.3. ±30 % acceptance is checked by the Verifier after the real run. |
| D25 | **Steps semantic:** `steps` is passed straight through as `num_inference_steps` to both engines. mflux runs `steps` denoising passes; diffusers runs `steps − 1` DiT forwards for Turbo (model card: "num_inference_steps=9 … results in 8 DiT forwards"). The UI label stays "8–9 recommended". | Matches both upstream defaults without translating between them. |

---

## 2. Verified NVIDIA facts (brief 5.2) — with sources

All read on 2026-10-26.

| Fact | Verified value | Source |
|---|---|---|
| Model repo | `Tongyi-MAI/Z-Image-Turbo`, licence **apache-2.0**, 6B params, revision `f332072aa78be7aecdf3ee76d5c247082da564a6` | https://huggingface.co/Tongyi-MAI/Z-Image-Turbo and `https://huggingface.co/api/models/Tongyi-MAI/Z-Image-Turbo?blobs=true` |
| Repo contents and size | **32.9 GB total**: `transformer/` 3 shards 9.97 + 9.97 + 4.67 GB (**fp32**, 6.1B params), `text_encoder/` 3.96 + 3.99 + 0.10 GB (Qwen3, `torch_dtype: bfloat16`, 36 layers, hidden 2560), `vae/` 0.17 GB, tokenizer, scheduler. `model_index.json`: `ZImagePipeline` with `FlowMatchEulerDiscreteScheduler`, `Qwen3Model` text encoder, `Qwen2Tokenizer`, `ZImageTransformer2DModel`, `AutoencoderKL`. | same API call; `text_encoder/config.json`; `model_index.json` |
| Pipeline class | `diffusers.ZImagePipeline` (`class ZImagePipeline(DiffusionPipeline, ZImageLoraLoaderMixin, FromSingleFileMixin)`, `model_cpu_offload_seq = "text_encoder->transformer->vae"`, `_callback_tensor_inputs = ["latents", "prompt_embeds"]`) | https://github.com/huggingface/diffusers/blob/v0.41.0/src/diffusers/pipelines/z_image/pipeline_z_image.py lines 141–144 |
| Minimum diffusers version | **0.36.0** (released 2025-12-08) added "Add Support for Z-Image Series (#12703)", "Support unittest for Z-image (#12715)", `ZImageImg2ImgPipeline` (#12751), `from_single_file` (#12756). **0.37.0** (2026-03-05) has "Fix wrong `do_classifier_free_guidance` threshold in ZImagePipeline" — relevant because Turbo runs at guidance 0, so pin ≥ 0.37. Pinned **0.41.0** (2026-10-06, Python ≥ 3.10). 0.42.0 (2026-10-23) requires Python ≥ 3.11. | https://github.com/huggingface/diffusers/releases/tag/v0.36.0 ; https://github.com/huggingface/diffusers/releases/tag/v0.37.0 ; https://pypi.org/pypi/diffusers/0.41.0/json |
| dtype | `torch_dtype=torch.bfloat16` (model card). In 0.41.0 `from_pretrained` accepts both `torch_dtype` and `dtype` (`pipeline_utils.py` lines 788–789 resolve the two). Use `torch_dtype=` for compatibility. | model card; https://github.com/huggingface/diffusers/blob/v0.41.0/src/diffusers/pipelines/pipeline_utils.py |
| Guidance | `guidance_scale=0.0` ("Guidance should be 0 for the Turbo models"); `__call__` default is 5.0 so it **must** be passed. `num_inference_steps` default is 50, so it must be passed too. No `negative_prompt` (ignored when guidance < 1). | model card; pipeline source lines 304–306 |
| Size rule | `vae_scale = self.vae_scale_factor * 2` → height and width **must be divisible by 16**, else `ValueError("Height must be divisible by 16 …")`. | pipeline source lines 402–410 |
| Progress | `callback_on_step_end(self, i, t, callback_kwargs)` is called once per step **after** the scheduler step; it must return a dict (the pipeline does `callback_outputs.pop("latents", latents)`). Pass `callback_on_step_end_tensor_inputs=["latents"]` (default). | pipeline source lines 573–579; https://huggingface.co/docs/diffusers/main/en/using-diffusers/callback |
| Interrupt | `self._interrupt = False` at the top of `__call__` (line 418); loop head: `for i, t in enumerate(timesteps): if self.interrupt: continue` (lines 505–506). Setting `pipeline._interrupt = True` inside the callback skips the remaining steps; the docs' "Early stopping" section shows exactly this. Modular pipelines differ (raise instead) — not used here. | pipeline source; callback docs |
| VRAM without offload | Not stated numerically by the model card. By weight size: 12.3 GB (transformer bf16) + 8.05 GB (text encoder bf16) + 0.17 GB (VAE) ≈ **20.6 GB resident** + activations → **24 GB card**. | file sizes above |
| VRAM with `enable_model_cpu_offload()` | Model card: "fits comfortably within 16G VRAM consumer devices"; offload is listed as "[Optional] CPU Offloading … for memory-constrained devices". Peak ≈ the largest single component (transformer 12.3 GB) + activations ≈ **13–14 GB at 1024²**. Needs ~21 GB system RAM to hold the offloaded pipeline → recommend **≥ 32 GB RAM** for offload modes (warn, do not block). No primary source gives a measured number; label as estimate. | model card; `enable_model_cpu_offload` at `pipeline_utils.py` line 1174, `enable_sequential_cpu_offload` line 1293 |
| Quantized variants for 8–12 GB | (a) **GGUF transformers** loadable with `ZImageTransformer2DModel.from_single_file(path, quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16), config="Tongyi-MAI/Z-Image-Turbo", subfolder="transformer", torch_dtype=torch.bfloat16)` then `ZImagePipeline.from_pretrained("Tongyi-MAI/Z-Image-Turbo", transformer=transformer, …)`. The 0.41.0 single-file loader maps `ZImageTransformer2DModel` → `convert_z_image_transformer_checkpoint_to_diffusers` (`single_file_model.py` lines 211–213). Files: `unsloth/Z-Image-Turbo-GGUF` (apache-2.0, 1.06 M downloads): Q8_0 7.22 GB, Q6_K 5.91 GB, Q5_K_M 5.57 GB, Q4_K_M 5.02 GB, Q4_0 4.59 GB, Q3_K_M 4.19 GB; `jayn7/Z-Image-Turbo-GGUF` (apache-2.0) same ladder and a README with the diffusers snippet. The diffusers GGUF page says Q4_0/Q4_1/Q5_0/Q5_1/Q8_0/Q2_K–Q6_K are supported; it does not list per-architecture support, so **GGUF for Z-Image is community-evidenced, not documented** → "experimental". (b) `unsloth/Z-Image-Turbo-FP8` (6.3 GB torchao FP8 `.pt`, validated on torch 2.12.1 + torchao 0.17) — needs torchao, not plain diffusers → not used. (c) `lightx2v/Z-Image-Turbo-Quantized` (FP8/INT8 6.17 GB, "optimized for 8GB VRAM") — needs the LightX2V runtime → not used. | https://huggingface.co/docs/diffusers/main/en/quantization/gguf ; https://huggingface.co/jayn7/Z-Image-Turbo-GGUF/blob/main/README.md ; https://huggingface.co/unsloth/Z-Image-Turbo-GGUF ; https://huggingface.co/unsloth/Z-Image-Turbo-FP8 ; https://huggingface.co/lightx2v/Z-Image-Turbo-Quantized/blob/main/README.md |
| torch version | diffusers 0.41.0 `setup.py`: `torch>=2.6`, `transformers>=4.41.2`, `accelerate>=0.31.0`, `gguf>=0.10.0`, `huggingface-hub>=1.32.0,<2.0`, `safetensors>=0.8.0`. transformers 5.20.2: `torch>=2.6`. Pinned **torch==2.9.1** (PyPI 2025-11-12) from `https://download.pytorch.org/whl/cu128` — the newest version with cp312 wheels for both `win_amd64` and `manylinux_2_28_x86_64` on that index. Community guides ran Z-Image on cu124 torch; unsloth validated torch 2.12.1. No primary source names one "known" torch version, so this pin is "within the supported range", **unverified on real hardware** until the first NVIDIA run is logged. | https://github.com/huggingface/diffusers/blob/v0.41.0/setup.py ; https://download.pytorch.org/whl/cu128/torch/ ; https://pypi.org/pypi/torch/2.9.1/json |
| Driver minimum | CUDA 12.8 GA: driver ≥ 570.26 (Linux), ≥ 570.65 (Windows). CUDA 13.x: ≥ 580. `assess` reads the driver from `nvidia-smi` and refuses below 570.26/570.65 with the message "update the NVIDIA driver". | https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html (Table 4 and the minor-version table) |
| `low_cpu_mem_usage=False` | Appears in the model card and the Z-Image GitHub README snippet with no stated reason; no diffusers issue explains it. **Do not pass it** (default True = shard-by-shard loading via accelerate, lower RAM). If the first real NVIDIA run fails at load, retry with it and log the finding in VERIFICATION.md. | https://github.com/Tongyi-MAI/Z-Image ; search found no issue |
| uv CUDA index pattern | `[tool.uv.sources] torch = [{ index = "pytorch-cu128", marker = "sys_platform == 'linux' or sys_platform == 'win32'" }]` + `[[tool.uv.index]] name = "pytorch-cu128" url = "https://download.pytorch.org/whl/cu128" explicit = true` | https://docs.astral.sh/uv/guides/integration/pytorch/ |
| uv installers | macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh`; Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` | https://docs.astral.sh/uv/getting-started/installation/ |

**Does anything change the NVIDIA plan (brief 12.3)?** No. Z-Image is supported in diffusers since 0.36.0, and the VRAM estimate with offload is ~13–14 GB, under 16 GB. Two facts the brief did not anticipate are recorded as decisions, not blockers: resident mode needs a 24 GB card (D6), and the official download is 32.9 GB because the transformer is stored in fp32 (setup requires ≥ 40 GB free disk on NVIDIA machines; GGUF modes download ~13 GB instead).

### 2.1 Verified mflux 0.22.0 facts (read from `patient-imagegen/venv/lib/python3.10/site-packages/mflux/`)

- `mflux==0.22.0`, `mlx==0.32.3` installed; `mflux` requires `mlx>=0.32.0,<0.33.0` on darwin, `torch>=2.13.0,<3.0`, `transformers>=5.5.0,<6.0`, `huggingface-hub>=1.1.6,<2.0`, `pillow>=12.3.0`, Python ≥ 3.10 (classifiers list 3.10–3.14).
- `ZImage.__init__(quantize=None, model_path=None, lora_paths=None, lora_scales=None, bake_lora=True, model_config=ModelConfig.z_image_turbo(), float32=False, compute_precision=None)`; `model_path="filipstrand/Z-Image-Turbo-mflux-4bit"` resolves to the HF cache snapshot with `HF_HUB_OFFLINE=1` (patient-imagegen claim C6, confirmed there).
- `ZImage.generate_image(seed, prompt, num_inference_steps=4, height=1024, width=1024, guidance=None, image_path=None, image_strength=None, scheduler=None, negative_prompt=None, pid_decode=False, pid_degrade_sigma=0.0) -> GeneratedImage`. **Always pass `num_inference_steps`** (default 4). Turbo config has `supports_guidance=False`, so guidance is forced to 0 and no negative prompt is encoded.
- `GeneratedImage.image` is a `PIL.Image.Image`; `.generation_time` is the tqdm loop elapsed seconds (denoising only).
- `Config` rounds width/height down to multiples of 16 with a warning (we round first, D18). `config.num_inference_steps`, `config.init_time_step` (0 for txt2img), `config.time_steps` (tqdm over `range(init_time_step, num_inference_steps)`).
- Callback registration: `model.callbacks.register(obj)` adds `obj` to each list for which it has `call_before_loop` / `call_in_loop` / `call_after_loop` / `call_interrupt`. Calls are **keyword-only** from `GenerationContext`:
  - `call_before_loop(seed, prompt, latents, config, canny_image=None, depth_image=None, control_images=None)`
  - `call_in_loop(t, seed, prompt, latents, config, time_steps)` — `t` is the absolute 0-based step; fires **before** `mx.eval(latents)`, so never read `latents`. (An optional `denoised` parameter is injected only if the signature declares it — do not declare it.)
  - `call_after_loop(seed, prompt, latents, config)`
- Order inside `generate_image`: latents → prompt encode → `before_loop` → loop (`in_loop` then `mx.eval`) → `after_loop` → VAE decode.
- Cancel: `from mflux.utils.exceptions import StopImageGenerationException` raised in `call_in_loop` propagates out of `generate_image` (the loop catches only `KeyboardInterrupt`).
- Low-RAM pieces: `from mflux.models.common.vae.tiling_config import TilingConfig; model.tiling_config = TilingConfig()`; `mx.set_cache_limit(1000**3)`; after each job `gc.collect(); mx.clear_cache()`. Peak: `mx.reset_peak_memory()` before, `mx.get_peak_memory()/1e9` after. All four `mlx.core` functions exist in 0.32.3.
- Measured on this M2 Pro 16 GB: ~24 s/step at 768×1344, ~5.5 s/step at 512², peak 7.8–8.5 GB resident txt2img, load ≈ 8 s.

---

## 3. Repo layout and file ownership

Every file is owned by exactly one task. A worker that needs a change in a file it does not own asks the Manager.

```
medical-image-gen/
  PLAN.md                               Advisor (this file)
  VERIFICATION.md                       Verifier
  README.md                             T11
  .python-version  pyproject.toml  uv.lock  .gitignore          T0
  .github/workflows/tests.yml           T0
  setup.command setup.sh setup.bat      T10
  start.command start.sh start.bat      T10
  assess.command assess.sh assess.bat   T10
  device_profile.json                   (generated, gitignored)
  medimg/
    __init__.py  config.py  __main__.py T0
    errors.py                           T0
    engines/base.py  engines/fake_engine.py  engines/__init__.py   T0
    engines/mflux_engine.py             T4
    engines/diffusers_engine.py         T5
    rules.py                            T1
    sheet/__init__.py sheet/columns.py sheet/reader.py sheet/validate.py
    sheet/writer.py sheet/select.py     T2
    store.py  names.py                  T3
    assess/__init__.py assess/detect.py assess/parse.py assess/decide.py
    assess/bench.py assess/estimate.py assess/profile.py assess/report.py   T6
    jobs.py  worker.py                  T7
    server.py                           T8
    static/index.html static/app.css static/app.js            T9
    setup_cmd.py  download.py  smoke.py T10
  tools/make_templates.py               T2
  templates/image_prompts_template.xlsx templates/image_prompts_sample.xlsx   T2 (generated by the tool)
  docs/*.md                             T11
  tests/
    conftest.py  stubs/__init__.py stubs/mflux_stub.py stubs/diffusers_stub.py   T0
    test_rules.py                       T1
    test_sheet_*.py                     T2
    test_store.py test_names.py         T3
    test_mflux_engine.py                T4
    test_diffusers_engine.py            T5
    test_assess_*.py  fixtures/assess/* T6
    test_jobs.py test_worker.py         T7
    test_api_*.py                       T8
    test_setup_cmd.py test_download.py  T10
    test_docs_commands.py               T11
```

`.gitignore` (T0) must cover: `.venv/`, `venv/`, `__pycache__/`, `*.pyc`, `device_profile.json`, `*.png`, `*.jpg`, `*.jpeg`, `*.webp`, `*.xlsx`, `!templates/image_prompts_template.xlsx`, `!templates/image_prompts_sample.xlsx`, `*.safetensors`, `*.gguf`, `models/`, `output/`, `outputs/`, `.pytest_cache/`, `.DS_Store`, `*.log`.

---

## 4. Pinned interfaces

Workers implement exactly these names and signatures. Anything not pinned here is the worker's choice.

### 4.1 `medimg/config.py` (T0)

```python
APP_NAME = "medical-image-gen"
VERSION = "0.1.0"
DEFAULT_PORT = 8750                      # verified free on this Mac (lsof) on 2026-10-26
DEFAULT_STEPS = 9
STEPS_MIN, STEPS_MAX = 4, 15
DEFAULT_WIDTH, DEFAULT_HEIGHT = 1024, 1024
SIZE_MULTIPLE = 16
SIDE_MIN, SIDE_MAX = 256, 1536
MAX_PIXELS = 1_048_576
SEED_MAX = 2_147_483_647
BATCH_TARGET_MINUTES = 30
SIZE_PRESETS = [  # label, width, height
    ("1024x1024", 1024, 1024), ("768x1344 portrait", 768, 1344), ("1344x768 landscape", 1344, 768),
    ("832x1216", 832, 1216), ("1216x832", 1216, 832), ("768x768 low-memory", 768, 768)]
MFLUX_MODEL_ID = "filipstrand/Z-Image-Turbo-mflux-4bit"
MFLUX_MODEL_REVISION = "b3a8f31115a11f2f9e2fa0bfbc8d78dcc3e6568b"
MFLUX_MODEL_GB = 5.9
DIFFUSERS_MODEL_ID = "Tongyi-MAI/Z-Image-Turbo"
DIFFUSERS_MODEL_REVISION = "f332072aa78be7aecdf3ee76d5c247082da564a6"
DIFFUSERS_MODEL_GB = 32.9
GGUF_REPO_ID = "unsloth/Z-Image-Turbo-GGUF"
GGUF_FILES = {"q8_0": ("z-image-turbo-Q8_0.gguf", 7.3), "q4_k_m": ("z-image-turbo-Q4_K_M.gguf", 5.1)}  # (file, GB)
DISK_MARGIN_GB = 5
REPO_ROOT: Path                          # parent of medimg/
PROFILE_PATH = REPO_ROOT / "device_profile.json"
SETTINGS_PATH = Path.home() / ".medical-image-gen" / "config.json"
DEFAULT_OUTPUT_ROOT = Path.home() / "medical-image-gen-output"

@dataclass
class Settings:
    output_root: Path = DEFAULT_OUTPUT_ROOT
    port: int = DEFAULT_PORT
    steps: int = DEFAULT_STEPS
    unload_after_job: bool | None = None   # None = decide from RAM (D17)
def load_settings(path: Path = SETTINGS_PATH) -> Settings      # missing/corrupt file → defaults
def save_settings(s: Settings, path: Path = SETTINGS_PATH) -> None   # atomic
```

`medimg/__main__.py` (T0): `python -m medimg <cmd>`; commands dispatch by lazy import so the module imports nothing heavy:

| Command | Flags | Calls |
|---|---|---|
| `setup` | `--skip-smoke`, `--skip-assess`, `--yes` | `medimg.setup_cmd.run(args) -> int` |
| `assess` | `--no-benchmark`, `--json`, `--output-root P` | `medimg.assess.run(args) -> int` |
| `serve` | `--port N`, `--fake-engine`, `--no-browser`, `--output-root P` | `medimg.server.main(args) -> int` |
| `smoke` | `--size WxH` (default 512x512), `--steps N` (default 4), `--fake-engine` | `medimg.smoke.run(args) -> int` |

`__main__` sets `os.environ.setdefault("HF_HUB_OFFLINE", "1")` for `serve`, `smoke`, `assess` before dispatch (D20). Exit code 0 on success, 1 on a user-facing failure (message printed, no traceback), 2 on usage error.

`medimg/errors.py` (T0): `class MedimgError(Exception)` with `.cause: str` and `.fix: str` (user-facing); subclasses `Unsupported`, `Blocked`, `Invalid`, `Busy`, `NotFound`, `ModelUnavailable`, `Cancelled`.

### 4.2 Engine (T0 base, T4 mflux, T5 diffusers)

```python
# medimg/engines/base.py — no heavy imports anywhere in this file
from dataclasses import dataclass
from typing import Callable, Protocol
from PIL import Image

ProgressFn = Callable[[str, int, int], None]      # (phase, step_done, step_total); phases below
CancelFn = Callable[[], bool]
PHASES = ("loading", "encoding", "denoising", "decoding")

@dataclass
class GenResult:
    image: Image.Image
    seed: int
    time_s: float          # wall time of generate() including encode and decode
    peak_mem_gb: float     # mflux: mx.get_peak_memory(); diffusers: torch.cuda.max_memory_allocated(); fake: 0.0
    steps: int             # value passed as num_inference_steps
    engine: str            # e.g. "mflux 0.22.0", "diffusers 0.41.0", "fake"
    model_id: str

class Engine(Protocol):
    name: str              # "mflux" | "diffusers" | "fake"
    model_id: str
    loaded: bool
    def load(self, on_progress: ProgressFn | None = None) -> None: ...
    def unload(self) -> None: ...
    def generate(self, prompt: str, seed: int, steps: int, width: int, height: int,
                 on_progress: ProgressFn, should_cancel: CancelFn) -> GenResult: ...

class Cancelled(Exception): ...          # re-exported from medimg.errors
def make_engine(backend: str, profile: dict | None, *, fake: bool = False) -> Engine   # in engines/__init__.py (T0)
```

Contract (tested against FakeEngine in T0 and both real engines in T4/T5):

1. `generate` raises `RuntimeError("engine not loaded")` if `loaded` is False. The worker calls `load()` first.
2. `on_progress("encoding", 0, 0)` before the model call; `on_progress("denoising", k, steps)` for k = 1..steps as each step finishes; `on_progress("decoding", steps, steps)` once before decode. (Diffusers has no decode hook: send "decoding" from the callback on the last step.)
3. `should_cancel()` is polled at least once per denoising step. If it returns True, `generate` raises `Cancelled` and returns no image. Cancel lands after the current step.
4. `width`/`height` arrive already rounded to multiples of 16; the engine passes them through unchanged.
5. After every call, success or not, the engine releases scratch memory (mflux: `gc.collect(); mx.clear_cache()`; diffusers: `gc.collect(); torch.cuda.empty_cache()`).
6. `load` is idempotent; `unload` after `unload` is a no-op.

`FakeEngine(step_s=0.01, fail_on: set[int] = (), image_size_divisor=8)` (T0): deterministic PIL image whose colour is derived from the seed; honours cancel; `fail_on` makes the n-th call raise `RuntimeError("fake failure")`.

**mflux engine (T4)** — `medimg/engines/mflux_engine.py`, the only module importing `mflux`/`mlx`, and only inside methods:

```python
class MfluxEngine:
    name = "mflux"; model_id = MFLUX_MODEL_ID
    def __init__(self, cache_limit_bytes: int = 1000**3): ...
    def load(self, on_progress=None):
        import mlx.core as mx
        from mflux.models.common.config.model_config import ModelConfig
        from mflux.models.common.vae.tiling_config import TilingConfig
        from mflux.models.z_image.variants.z_image import ZImage
        model = ZImage(model_path=self.model_id, model_config=ModelConfig.z_image_turbo(), quantize=None)
        model.tiling_config = TilingConfig()
        mx.set_cache_limit(self._cache_limit)
        model.callbacks.register(self._progress)      # one _Progress object, registered once
    def generate(...):
        out = self._model.generate_image(seed=seed, prompt=prompt, num_inference_steps=steps, height=height, width=width)
```

`_Progress` methods must have exactly the three signatures in section 2.1 (keyword-called). `call_in_loop` reports `t - config.init_time_step + 1` of `config.num_inference_steps - config.init_time_step` and raises `StopImageGenerationException` when `should_cancel()`; the engine converts it to `Cancelled`. `engine` string = `f"mflux {importlib.metadata.version('mflux')}"`.

**diffusers engine (T5)** — `medimg/engines/diffusers_engine.py`, the only module importing `torch`/`diffusers`, and only inside methods:

```python
OFFLOAD_MODES = ("resident", "model_cpu_offload", "gguf_q8_offload", "gguf_q4_sequential")
class DiffusersEngine:
    name = "diffusers"; model_id = DIFFUSERS_MODEL_ID
    def __init__(self, offload_mode: str, gguf_path: Path | None = None): ...
    def load(self, on_progress=None):
        import torch; from diffusers import ZImagePipeline
        kw = dict(torch_dtype=torch.bfloat16)
        if self.offload_mode.startswith("gguf"):
            from diffusers import ZImageTransformer2DModel, GGUFQuantizationConfig
            kw["transformer"] = ZImageTransformer2DModel.from_single_file(
                str(self.gguf_path), quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16),
                config=self.model_id, subfolder="transformer", torch_dtype=torch.bfloat16)
        pipe = ZImagePipeline.from_pretrained(self.model_id, **kw)
        if mode == "resident": pipe.to("cuda")
        elif mode in ("model_cpu_offload", "gguf_q8_offload"): pipe.enable_model_cpu_offload()
        else: pipe.enable_sequential_cpu_offload()
        pipe.set_progress_bar_config(disable=True)
    def generate(...):
        torch.cuda.reset_peak_memory_stats()
        def cb(pipe, i, t, kw):
            on_progress("denoising", i + 1, steps)
            if i + 1 == steps: on_progress("decoding", steps, steps)
            if should_cancel(): pipe._interrupt = True
            return kw
        out = self._pipe(prompt=prompt, height=height, width=width, num_inference_steps=steps,
                         guidance_scale=0.0, generator=torch.Generator("cuda").manual_seed(seed),
                         callback_on_step_end=cb, callback_on_step_end_tensor_inputs=["latents"])
        if cancelled: raise Cancelled()
        image = out.images[0]; peak = torch.cuda.max_memory_allocated() / 1e9
```

Never pass `negative_prompt`, `low_cpu_mem_usage`, or a non-zero guidance. `engine` string = `f"diffusers {version('diffusers')}"`.

### 4.3 Test stubs (T0, `tests/stubs/`)

`conftest.py` provides fixtures `fake_mflux` and `fake_diffusers` that `monkeypatch.setitem(sys.modules, …)` stub packages **before** the engine module's `load()` runs, and remove them after. Stubs record every constructor/call kwarg on a `calls: list[tuple[str, dict]]` attribute so T4/T5 tests can assert exact kwargs.

- `mflux_stub`: modules `mlx`, `mlx.core` (`set_cache_limit`, `clear_cache`, `reset_peak_memory`, `get_peak_memory` → 1.5e9), `mflux`, `mflux.models.common.config.model_config` (`ModelConfig.z_image_turbo()` returning a sentinel), `mflux.models.common.vae.tiling_config` (`TilingConfig` dataclass), `mflux.models.z_image.variants.z_image` (`ZImage` whose `generate_image(**kw)` asserts `num_inference_steps` present, builds a `config` object with `init_time_step=0`, `num_inference_steps`, then calls registered callbacks **with keyword arguments only** and the exact parameter names, honouring `StopImageGenerationException` propagation, and returns an object with `.image` (PIL) and `.generation_time`), `mflux.utils.exceptions` (`StopImageGenerationException`). `importlib.metadata.version("mflux")` is patched to return `"0.22.0"`.
- `diffusers_stub`: modules `torch` (`bfloat16`, `Generator(device).manual_seed(n)`, `cuda.reset_peak_memory_stats`, `cuda.max_memory_allocated` → 1.2e10, `cuda.empty_cache`, `cuda.is_available` → True), `diffusers` (`ZImagePipeline.from_pretrained(**kw)` returning a pipe whose `__call__` asserts `guidance_scale == 0.0` and `num_inference_steps` present, sets `_interrupt=False`, loops `for i in range(n): if pipe._interrupt: continue; kw = callback(pipe, i, t, {"latents": None}); assert isinstance(kw, dict)`, returns `.images=[PIL]`; records `to`, `enable_model_cpu_offload`, `enable_sequential_cpu_offload`, `set_progress_bar_config` calls), `ZImageTransformer2DModel.from_single_file(**kw)`, `GGUFQuantizationConfig`. `version("diffusers")` patched to `"0.41.0"`.

### 4.4 Rules (T1, `medimg/rules.py`)

```python
HINT = "State an adult age (for example 45-year-old) or the word adult."
def check_prompt(prompt: str) -> str | None
```

Returns `None` when the prompt passes, otherwise a reason starting with `"Blocked: "`. Order of evaluation: (1) any stated age < 18 → `"Blocked: the prompt states an age under 18. Images are adults only."`; (2) any minor term → `"Blocked: '<term>' suggests a minor. Images are adults only; rephrase."`; (3) a stated age ≥ 18 or an adult word → pass; (4) otherwise `"Blocked: the prompt does not state an adult. " + HINT`.

Age forms recognised (digits or number words up to ninety-nine): `45-year-old`, `45 year old`, `45yo`, `45 y/o`, `45 yrs`, `aged 45`, `age 45`, `age: 45`, `forty-five-year-old`. Adult words: `adult`, `adults`, `middle-aged`, `elderly`, `older man`, `older woman`. Minor terms (word-boundary, case-insensitive, plural forms): child, children, kid(s), kiddo(s), teen(s), teenager(s), teenage(d), preteen(s), tween(s), boy(s), girl(s), infant(s), baby, babies, toddler(s), minor(s), underage, newborn(s), neonate(s), adolescent(s), adolescence, juvenile(s), pediatric, paediatric, schoolchild(ren), schoolboy(s), schoolgirl(s), schoolkid(s), school, youngster(s), youth(s), childlike, highschool(er). "18-year-old" passes; "17-year-old adult" blocks; "adult teen" blocks; "boyfriend"/"girlfriend" are not matched (word boundary on the whole term). The module has no configuration hooks, reads no env and no file.

### 4.5 Sheet module (T2, `medimg/sheet/`)

```python
REQUIRED = ("subject", "unit", "lecture", "image prompt", "image name", "status")
OPTIONAL = ("size", "seed")
SYSTEM = ("Steps", "Seed Used", "Generated At", "Machine", "Model", "Generation Time (s)", "Output Path", "Error")
STATUSES = ("pending", "done", "failed", "blocked", "invalid")

@dataclass
class Row:
    idx: int                      # 1-based Excel row number
    subject: str; unit: str; lecture: str; prompt: str; image_name: str
    status: str                   # normalised; blank → "pending"
    size: tuple[int, int] | None  # parsed from "WxH"; None when blank
    seed: int | None
    error: str                    # "" when none
    rel_path: str | None          # sanitised "Subject/Unit/Lecture/Name.png", None when invalid
    system: dict[str, object]     # existing system-column values

@dataclass
class Problem: row: int; status: str; reason: str; fix: str

@dataclass
class SheetReport:
    sheet_id: str; original_name: str; working_path: Path; worksheet: str
    rows: list[Row]; counts: dict[str, int]      # keys: total, done, pending, blocked, failed, invalid
    problems: list[Problem]
    filters: dict[str, list[str]]                # subjects, units, lectures (sorted, unique)

class SheetError(MedimgError): ...               # cause + fix

def import_sheet(src: Path, output_root: Path) -> Path               # copies to <root>/_sheets/<stamp>_<name>.xlsx, writes current.json
def current_sheet(output_root: Path) -> Path | None
def find_worksheet(wb) -> Worksheet                                   # first sheet whose header row has all REQUIRED (case/space-insensitive)
def read_rows(path: Path) -> tuple[str, list[Row]]                    # (worksheet title, rows); raises SheetError
def validate(rows: list[Row], *, output_root: Path, default_size: tuple[int,int], retry_failed: bool) -> list[Row]
def build_report(path: Path, original_name: str, **validate_kwargs) -> SheetReport
def select_batch(rows: list[Row], n: int, flt: dict[str, str] | None) -> list[Row]   # first n "pending" rows in sheet order after filter
def ensure_system_columns(path: Path) -> dict[str, int]              # appends missing SYSTEM headers; returns header→column map; atomic
def write_row(path: Path, idx: int, updates: dict[str, object]) -> None   # updates by header name; temp file + os.replace
def write_rows(path: Path, updates: dict[int, dict[str, object]]) -> None # same, many rows, one save
```

`validate` rules, in order per row: missing required field → `invalid` ("Missing <column>", fix "fill the cell"); bad `Size` → `invalid` ("Size must look like 768x1344"); sanitised path over 240 chars → `invalid`; `check_prompt` fails → `blocked` with the reason; two rows with the same case-folded `rel_path` → both `invalid` ("Same output path as row N"); `pending` and `<root>/<rel_path>` exists → `done` (Output Path filled, Error cleared). `done` rows are untouched. `failed` rows become `pending` only when `retry_failed`. Size blank → `default_size`. Seed blank → `None`. `rel_path` uses `medimg.names.safe_component` from T3 (T2 depends on T3 for that one function; until T3 lands, T2 uses a local identity stub behind the same name).

Writing: openpyxl `load_workbook` → modify → `save(tmp)` in the same directory → `os.replace(tmp, path)`. Never reorder rows, never touch other sheets or columns; column widths survive because openpyxl keeps them. `Generated At` is ISO-8601 local time with offset. `Machine` is `"<hostname> · <chip or GPU>"`.

`tools/make_templates.py` (T2) writes both template files with openpyxl: the template has the header row, a data-validation list on `Status` (`pending,done,failed,blocked,invalid`), a comment on `Size` ("WxH, e.g. 768x1344; blank = UI default") and a second sheet "How to fill". The sample has three neutral clothed adult rows (e.g. Subject "Anatomy", Unit "Upper limb", Lecture "Hand", a hand X-ray-style illustration of a 40-year-old adult; an adult knee examination photo; an adult shoulder diagram), all with explicit adult ages.

### 4.6 Names and store (T3, `medimg/names.py`, `medimg/store.py`)

```python
# names.py
WINDOWS_RESERVED = {"CON","PRN","AUX","NUL","COM1".."COM9","LPT1".."LPT9"}
def safe_component(s: str) -> str     # strip <>:"/\|?* and control chars, collapse whitespace, trim trailing ". ", rename reserved → "<name>_", empty → "untitled"
def image_file_name(image_name: str) -> str     # safe_component; strips a trailing ".png" (case-insensitive) before adding one
def rel_path(subject: str, unit: str, lecture: str, image_name: str) -> str   # "S/U/L/N.png"; "_single/N.png" when all three are empty
def path_too_long(root: Path, rel: str, limit: int = 240) -> bool
def image_id(rel: str) -> str         # sha1(rel.encode()).hexdigest()[:16]

# store.py
PNG_KEY = "medical-image-gen"
@dataclass
class ImageRecord:        # the sidecar; same JSON goes into the PNG tEXt chunk
    id: str; rel_path: str; subject: str; unit: str; lecture: str; image_name: str
    prompt: str; seed: int; steps: int; width: int; height: int
    model_id: str; engine: str; time_s: float; peak_mem_gb: float
    created_at: str; machine: str; source: str          # "batch" | "single" | "regenerate"
    sheet: dict | None                                  # {"name": original_name, "row": idx} | None

class Store:
    def __init__(self, root: Path): ...                 # creates root, _sheets, _thumbs, _single
    def path_for(self, rel: str) -> Path                # raises Invalid if the resolved path escapes root
    def exists(self, rel: str) -> bool
    def save(self, image: Image.Image, record: ImageRecord, *, overwrite: bool) -> ImageRecord   # PNG (with tEXt) then .json; raises Invalid if exists and not overwrite
    def load_record(self, image_id: str) -> ImageRecord | None
    def read_png_record(self, path: Path) -> dict | None
    def tree(self) -> dict                              # {"subjects":[{"name","units":[{"name","lectures":[{"name","count"}]}]}], "single_count": int}
    def list_images(self, subject: str | None, unit: str | None, lecture: str | None) -> list[ImageRecord]   # subject "_single" lists singles; newest first
    def thumb_path(self, image_id: str) -> Path          # makes <root>/_thumbs/<id>.jpg (256 px, LANCZOS) if missing or older than the PNG
    def refresh(self) -> None                            # rescans sidecars; called after each save and on demand
    def folder_of(self, image_id: str) -> Path
```

Sidecar is the source of truth for the gallery; a PNG without a sidecar is ignored. The index is an in-memory dict rebuilt by `refresh()` (cheap: one `rglob("*.json")`).

### 4.7 Assess (T6, `medimg/assess/`)

```python
@dataclass
class Machine:
    hostname: str; os_name: str; os_version: str; cpu: str; apple_chip: str | None
    ram_total_gb: float; ram_free_gb: float
    gpu: dict | None            # {"vendor": "nvidia"|"amd"|"apple"|"intel"|"other", "name", "vram_gb", "driver", "cuda"}
    disk_free_gb: float; disk_path: str; python: str; uv: str | None; arch: str

@dataclass
class Decision:
    backend: str | None         # "mflux" | "diffusers" | None
    supported: bool; reason: str; fix: str
    offload_mode: str | None    # diffusers only, one of OFFLOAD_MODES
    unload_after_job: bool
    model_id: str | None; download_gb: float | None; min_disk_gb: float | None

def detect(run=subprocess.run, platform_mod=platform, psutil_mod=psutil) -> Machine        # injectable for tests
def parse_nvidia_smi(csv_text: str, header_text: str) -> dict | None
def parse_system_profiler(json_text: str) -> dict          # chip name, memory
def parse_sysctl(text: str) -> dict
def parse_wmic_or_powershell(text: str) -> dict
def decide(m: Machine) -> Decision
def benchmark(engine: Engine, *, sizes=((512,512,4),(1024,1024,2))) -> dict   # {"load_s", "points":[{"width","height","steps","total_s","per_step_s","overhead_s"}]}
def fit(points: list[dict]) -> dict                        # {"ref_pixels": 262144, "ref_per_step_s", "alpha", "overhead_s"}
def estimate_seconds(profile: dict, width: int, height: int, steps: int) -> float   # uses actuals first (D24)
def record_actual(profile: dict, width: int, height: int, steps: int, time_s: float) -> dict   # keeps last 50
def load_profile(path=PROFILE_PATH) -> dict | None
def save_profile(profile: dict, path=PROFILE_PATH) -> None  # atomic
def estimates_table(profile: dict, steps: int = DEFAULT_STEPS) -> list[dict]   # per preset: {"label","width","height","seconds","for_10","for_25","for_50"}
def render_report(profile: dict) -> str                    # human-readable text for terminal and UI
def run(args) -> int                                       # CLI entry
```

`decide` rules: darwin + arm64 → mflux (needs RAM ≥ 16 GB; disk ≥ 5.9 + 5 GB unless the HF cache already has the snapshot); darwin + x86_64 → unsupported "Intel Mac: Apple-silicon only"; NVIDIA GPU present (`nvidia-smi` runs) → diffusers with offload mode by VRAM (D6), driver check (≥ 570.26 Linux / ≥ 570.65 Windows), disk ≥ 32.9 + 5 GB (or ≈ 13 + 5 GB in GGUF modes), RAM < 32 GB → warning text appended, not a block; AMD → unsupported "AMD GPUs are not supported in v1"; no GPU → unsupported "no NVIDIA GPU found"; `nvidia-smi` missing on a machine with an NVIDIA device string → "install the NVIDIA driver".

**`device_profile.json` schema v1:**

```json
{
  "schema_version": 1,
  "created_at": "2026-10-26T12:00:00+01:00",
  "app_version": "0.1.0",
  "machine": { "hostname": "", "os_name": "Darwin", "os_version": "27.0.0", "arch": "arm64", "cpu": "Apple M2 Pro",
               "apple_chip": "Apple M2 Pro", "ram_total_gb": 16.0, "ram_free_gb": 3.2,
               "gpu": {"vendor": "apple", "name": "Apple M2 Pro", "vram_gb": null, "driver": null, "cuda": null},
               "disk_free_gb": 27.1, "disk_path": "/Users/x/medical-image-gen-output", "python": "3.12.13", "uv": "0.11.29" },
  "backend": { "name": "mflux", "supported": true, "reason": "Apple silicon with 16 GB", "fix": "",
               "model_id": "filipstrand/Z-Image-Turbo-mflux-4bit", "offload_mode": null, "unload_after_job": true,
               "engine_version": "mflux 0.22.0" },
  "benchmark": { "measured_at": "...", "load_s": 8.1,
                 "points": [ {"width":512,"height":512,"steps":4,"total_s":30.2,"per_step_s":5.5,"overhead_s":8.2},
                             {"width":1024,"height":1024,"steps":2,"total_s":62.0,"per_step_s":23.0,"overhead_s":16.0} ],
                 "fit": {"ref_pixels": 262144, "ref_per_step_s": 5.5, "alpha": 1.03, "overhead_s": 8.2} },
  "actuals": [ {"at": "...", "width": 768, "height": 1344, "steps": 9, "time_s": 231.0} ],
  "notes": []
}
```

Keys are stable so a future version can feed the whole object to a research agent or catalogue lookup (docs/FUTURE.md); nothing in v1 does that.

### 4.8 Jobs and worker (T7, `medimg/jobs.py`, `medimg/worker.py`)

```python
# jobs.py — pure logic, no I/O
@dataclass
class RowJob:
    prompt: str; seed: int | None; steps: int; width: int; height: int
    subject: str; unit: str; lecture: str; image_name: str
    sheet_row: int | None = None; overwrite: bool = False
@dataclass
class JobSpec:
    kind: str                      # "batch" | "single" | "regenerate" | "benchmark"
    rows: list[RowJob]
    sheet_path: Path | None = None; sheet_name: str | None = None
def normalise_size(width: int, height: int) -> tuple[int, int]      # round down to 16; raises Invalid outside limits (D18)
def validate_row_job(j: RowJob) -> RowJob                            # rules check (raises Blocked), size, steps 4–15, seed range; fills random seed
def random_seed() -> int
def parse_size(text: str) -> tuple[int, int]                         # "768x1344" / "768 x 1344" / "768×1344"; raises Invalid

# worker.py
ACTIVE = ("queued", "loading", "encoding", "denoising", "decoding", "saving")
class State:                      # lock + version counter; snapshot() returns the /api/status "job" and "model" objects
class GenerationWorker:
    def __init__(self, engine: Engine, store: Store, profile_path: Path, *, unload_after_job: bool, sheet_lock: threading.Lock): ...
    def start(self) -> None
    def submit(self, spec: JobSpec) -> str                # raises Busy (409) or ModelUnavailable (503); every RowJob already validated
    def cancel(self) -> bool
    def snapshot(self) -> dict                            # see /api/status
```

Worker loop per row: validate again (defence in depth — `check_prompt` runs here too, so no route can bypass it), `on_progress` → state, `engine.generate`, `store.save` (overwrite only for regenerate), then `sheet.write_row` if `sheet_row` is set, then `record_actual` into the profile (atomic save). Cancel between rows: rows after the current one stay pending; the current row stays pending (no file, no sheet write). Failure of one row: `failed` + Error written, batch continues. Engine exception during load: job `failed`, model state `error`.

### 4.9 Server (T8, `medimg/server.py`)

`create_app(engine: Engine, settings: Settings, profile: dict | None, *, store: Store | None = None) -> FastAPI`; `main(args) -> int` binds `uvicorn.run(app, host="127.0.0.1", port=…, workers=1, reload=False)`, exits with `"port N in use; run start --port M"` (exit 1) when `socket.connect_ex` succeeds, opens the browser unless `--no-browser`. There is **no host flag anywhere**.

Error body for every 4xx/5xx: `{"error": {"cause": str, "fix": str}}`.

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/` | | `static/index.html` |
| GET | `/api/config` | | `{"version", "backend", "model_id", "defaults": {"steps","width","height","port","output_root","unload_after_job"}, "limits": {"steps_min","steps_max","side_min","side_max","max_pixels","multiple","seed_max"}, "size_presets": [{"label","width","height"}], "local_only": true, "nvidia_unverified": bool}` |
| GET | `/api/status` | | `{"version": int, "model": {"state": "not_loaded"|"loading"|"ready"|"error", "error": str|null}, "job": null | {"id","kind","phase","step","step_total","image_index","image_count","eta_s","current": {"subject","unit","lecture","image_name","sheet_row"}|null, "done_ids": [image_id], "errors": [{"row","reason"}]}, "last_job": {"id","kind","outcome": "done"|"cancelled"|"failed","finished_at"}|null, "gallery_version": int, "local_only": true}` |
| POST | `/api/sheet` | multipart `file` (.xlsx ≤ 20 MB); form `retry_failed` (bool), `default_size` ("WxH") | 200 `SheetReport` JSON (`rows` omitted; `problems`, `counts`, `filters`, `suggested_batch`, `estimate_per_image_s`, `sheet_id`, `original_name`); 400 with cause/fix |
| GET | `/api/sheet` | `?retry_failed=&default_size=&subject=&unit=&lecture=` | same report, re-validated; 404 when none loaded |
| GET | `/api/sheet/download` | | the working xlsx bytes, `Content-Disposition: attachment; filename="<original_name>"` (D22); 404 none |
| POST | `/api/sheet/estimate` | `{"count", "filter": {...}, "steps", "default_size"}` | `{"count", "seconds", "per_image_s"}` |
| POST | `/api/jobs/batch` | `{"count", "filter": {"subject","unit","lecture"}, "retry_failed", "default_size", "steps"}` | 202 `{"job_id", "rows": [idx]}`; 400 no sheet / count 0; 409 busy; 503 model error |
| POST | `/api/jobs/single` | `{"prompt","seed"|null,"steps","width","height","subject","unit","lecture","image_name"}` (last four optional) | 202 `{"job_id", "rel_path"}`; 422 blocked `{"error":{"cause": reason,"fix": HINT}}`; 409; 400 invalid |
| POST | `/api/jobs/regenerate` | `{"image_id"}` | 202 `{"job_id","seed","sheet_row": int|null}`; 404; 422 blocked (the stored prompt is re-checked); 409 |
| POST | `/api/jobs/cancel` | | `{"cancelled": bool}` |
| GET | `/api/gallery/tree` | | `Store.tree()` |
| GET | `/api/gallery/images` | `?subject=&unit=&lecture=` | `[{"id","rel_path","image_name","url": "/files/<id>.png","thumb_url": "/files/<id>/thumb.jpg","record": ImageRecord}]` |
| GET | `/api/images/{id}` | | `ImageRecord`; 404 |
| GET | `/files/{id}.png`, `/files/{id}/thumb.jpg` | id matches `^[0-9a-f]{16}$` | FileResponse via the store index; 404 otherwise |
| POST | `/api/images/{id}/open-folder` | | `{"ok": bool}` (`open`/`explorer`/`xdg-open` on the folder; never on a user string) |
| GET | `/api/device` | | `{"profile": dict|null, "report": str, "estimates": estimates_table, "unverified": bool}` |
| POST | `/api/device/benchmark` | | 202 `{"job_id"}` (a `benchmark` JobSpec); 409 busy |
| GET/PUT | `/api/settings` | PUT `{"output_root","steps","unload_after_job"}` | `Settings` as JSON; PUT creates the root, re-points the store |

`suggested_batch = clamp(floor(1800 / per_image_s), 1, pending)` where `per_image_s = estimate_seconds(profile, default_size, steps)`; 60 s when no profile.

Static files are served from `medimg/static/` with `StaticFiles`; no CDN, no inline external URL. `app.js` polls `/api/status` every 500 ms and refreshes the gallery when `gallery_version` changes.

### 4.10 Setup, download, smoke (T10)

```python
# download.py
def mflux_cached(model_id=MFLUX_MODEL_ID, revision=MFLUX_MODEL_REVISION) -> Path | None     # snapshot_download(local_files_only=True)
def download_mflux(progress=print) -> Path
def download_diffusers(mode: str, progress=print) -> Path     # full repo for resident/model_cpu_offload; allow_patterns without transformer/*.safetensors + GGUF file for gguf modes
# setup_cmd.py
def run(args) -> int   # steps 1–6 of brief 5.1, each step idempotent, each prints "✔ already done" when skipped
# smoke.py
def run(args) -> int   # load, generate one image at --size/--steps, save to <root>/_smoke/<stamp>.png, print time and path
```

Launchers (T10): `setup.sh`/`start.sh`/`assess.sh` are POSIX sh with `cd "$(dirname "$0")"`; `*.command` are the same content made executable for double-click on macOS; `*.bat` use `%~dp0`. Each checks for `uv` (installs with the official commands from section 2 if missing), then `uv sync --extra <mac|nvidia>` (setup only) and `uv run python -m medimg <cmd> "$@"`. Setup installs Python via `uv python install 3.12` implicitly through `uv sync`.

### 4.11 UI (T9, `medimg/static/`)

Element ids are listed in a comment block at the top of `index.html` (status strip, four tabs, every control named in brief 5.4). `app.js` is a single IIFE, no modules, no fetch to anything but same-origin `/api/*` and `/files/*`. Every error shows `cause` and `fix` inline next to the control that caused it.

---

## 5. Task breakdown

Each task is one worker; estimated worker time in parentheses. "Done" means its acceptance tests pass with `uv run pytest <files>` and the whole suite still passes.

| # | Task | Deps | Owns (section 3) | Acceptance tests | Est. |
|---|---|---|---|---|---|
| T0 | **Scaffold.** pyproject (base deps + `mac`/`nvidia` extras with markers, conflicts, cu128 index, `[dependency-groups] dev = [pytest, httpx, pyyaml]`, `[tool.pytest.ini_options] testpaths = ["tests"]`), `.python-version` = 3.12, `uv.lock`, `.gitignore`, `medimg/__init__.py`, `config.py`, `errors.py`, `__main__.py`, `engines/base.py`, `engines/fake_engine.py`, `engines/__init__.py`, `tests/conftest.py`, `tests/stubs/*`, CI workflow. | none | as listed | `uv sync` (no extra) on this Mac installs neither torch nor mflux; `uv lock --check` passes; `uv run pytest tests/test_fake_engine.py tests/test_config.py` passes (FakeEngine contract items 1–6, settings round-trip); `uv run python -m medimg --help` lists four commands; `git check-ignore device_profile.json a.png b.xlsx .venv` all ignored and `templates/image_prompts_sample.xlsx` is not; `tests/test_ci_workflow.py` parses `.github/workflows/tests.yml` with `pyyaml` (in the dev group) and asserts the two runners and the `uv run pytest` step. | 60 min |
| T1 | **rules.py + tests.** | T0 | `medimg/rules.py`, `tests/test_rules.py` | Pass: "45-year-old woman", "adult male", "aged 60", "eighteen-year-old", "elderly man", "middle-aged". Block: "woman" (no age), "teen", "16 yo", "17-year-old adult", "paediatric knee", "schoolgirl", "a boy", "adult teen". Not matched: "boyfriend", "girlfriend", "schoolteacher's adult patient" passes. Mutation check: remove `teen` and show a failing test, restore. | 30 min |
| T2 | **Sheet module + templates tool.** | T0 (T3 for `safe_component`; stub allowed until T3 lands) | `medimg/sheet/*`, `tools/make_templates.py`, `templates/*.xlsx`, `tests/test_sheet_*.py` | Header matching ignores case/space and order; second worksheet found when first has no headers; blank status → pending; mixed sheet of 7 rows (1 done, 1 pending, 1 minor term, 1 missing prompt, 2 sharing one output path, 1 bad size) gives counts `{total:7, done:1, pending:1, blocked:1, failed:0, invalid:4}` and per-row reasons; file-exists → done; done row with a minor term stays done; `write_row` leaves other sheets, columns, widths and row order intact (compare with openpyxl); atomic write survives a simulated crash (temp file left, original intact); `select_batch` honours filter and N and skips blocked/invalid; template has Status validation; sample has 3 rows that all pass `check_prompt`. | 90 min |
| T3 | **names.py + store.py + tests.** | T0 | `medimg/names.py`, `medimg/store.py`, `tests/test_names.py`, `tests/test_store.py` | `CON`→`CON_`, `a<b>:c`→`abc`, trailing dots/spaces trimmed, `x.PNG`→`x.png` once; `_single` when fields empty; path-escape raises; save writes PNG with tEXt key readable via `Image.open(p).text["medical-image-gen"]`; `tree()`/`list_images` from sidecars; thumb created at 256 px; overwrite flag enforced; id stable across restarts. | 60 min |
| T4 | **mflux engine + contract tests** (stubs only; **never loads the model**). | T0 | `medimg/engines/mflux_engine.py`, `tests/test_mflux_engine.py` | `import medimg.engines.mflux_engine` works without mflux installed; with `fake_mflux`: `ZImage` ctor kwargs are exactly `{model_path, model_config, quantize=None}`; `tiling_config` set; `set_cache_limit(1000**3)` called; `generate_image` kwargs are exactly `{seed, prompt, num_inference_steps, height, width}`; the three callback methods accept the exact keyword sets (stub calls with `**kwargs` and raises `TypeError` on mismatch); progress sequence `encoding → denoising 1..n → decoding`; cancel raises `Cancelled` after step k; `clear_cache` called on both success and failure; `unload` twice is a no-op. | 45 min |
| T5 | **diffusers engine + contract tests** (stubs only). | T0 | `medimg/engines/diffusers_engine.py`, `tests/test_diffusers_engine.py` | Import works without torch; `from_pretrained` kwargs `{"torch_dtype": bfloat16}` (+ `transformer` in GGUF modes with `from_single_file` kwargs as pinned); per mode exactly one of `to("cuda")` / `enable_model_cpu_offload()` / `enable_sequential_cpu_offload()`; `__call__` kwargs include `guidance_scale=0.0`, `num_inference_steps=steps`, `callback_on_step_end`, `callback_on_step_end_tensor_inputs=["latents"]`, no `negative_prompt`; callback returns the kwargs dict; cancel sets `_interrupt` and `generate` raises `Cancelled`; `empty_cache` on both paths; `peak_mem_gb` from `max_memory_allocated`. | 45 min |
| T6 | **assess package + fixtures + tests.** | T0 | `medimg/assess/*`, `tests/test_assess_*.py`, `tests/fixtures/assess/*` | Parsers on recorded fixtures: `nvidia-smi` CSV (RTX 4070 12 GB / RTX 3090 24 GB / RTX 4060 Laptop 8 GB), `system_profiler SPHardwareDataType -json` (M2 Pro), `sysctl` lines, `wmic`/PowerShell CPU output; `decide` table: M2 Pro 16 GB → mflux + unload; Intel Mac → unsupported with reason; 24 GB → resident; 16 GB → model_cpu_offload; 12 GB → gguf_q8_offload; 8 GB → gguf_q4_sequential; 6 GB → unsupported; driver 560 → unsupported "update the NVIDIA driver"; AMD → unsupported; no GPU → unsupported; low disk → unsupported with the GB numbers. `fit` on the two reference points reproduces them; `estimate_seconds` for 768×1344@9 from the M2 Pro points is within ±30 % of 231 s; actuals override; `record_actual` keeps 50; profile JSON validates against the schema keys; `render_report` contains the estimates table. `benchmark(FakeEngine)` runs both sizes. | 90 min |
| T7 | **jobs.py + worker.py + tests.** | T0, T1, T2, T3, T6 | `medimg/jobs.py`, `medimg/worker.py`, `tests/test_jobs.py`, `tests/test_worker.py` | `normalise_size(770,1350)→(768,1344)`; 100×100 raises; `parse_size` variants; blocked prompt raises `Blocked` even when submitted directly to the worker; batch of 3 rows with FakeEngine: PNG+sidecar+sheet row (`done`, seed, time, machine) per row, actuals appended; cancel after row 1 → row 1 done, row 2 pending with no file, row 3 pending; `fail_on={2}` → row 2 `failed` with Error, row 3 done; second submit → `Busy`; `unload_after_job` calls `unload` after each job; engine load error → model `error`, job `failed`. | 90 min |
| T8 | **server.py + API tests.** | T1, T2, T3, T6, T7 | `medimg/server.py`, `tests/test_api_*.py` | Full flow with FakeEngine: upload sample → counts → `POST /api/jobs/batch count=2` → poll until done → `GET /api/gallery/images` lists 2 → download sheet → re-upload into a fresh output root → counts `{done:2,pending:1}` → batch → only 1 generated (acceptance 4). Cancel mid-batch (acceptance 5). 409 when busy. Crash-resume: file present, row pending → done on upload. 422 on blocked prompt for single, regenerate and batch rows (acceptance 6). `/files/..%2F` → 404. Port-in-use message. Server never binds a host flag (grep `host=` shows only `"127.0.0.1"`). `/api/status` shape matches 4.9 exactly. | 120 min |
| T9 | **Static UI.** | T0 (routes pinned here) | `medimg/static/*` | Opened against `python -m medimg serve --fake-engine`: all four tabs render; status strip moves during a fake batch; cards update; problems list shows row/reason/fix; filter narrows; batch input defaults to the suggestion; cancel works; gallery tree + lightbox + the three buttons; device tab shows the report and estimates; a 422 shows inline with the fix. `grep -E "https?://" medimg/static/*` finds nothing. Works at 1280 px and 900 px wide. | 150 min |
| T10 | **setup, download, smoke, launchers.** | T0, T6, T4/T5 (engine factory) | `medimg/setup_cmd.py`, `medimg/download.py`, `medimg/smoke.py`, `setup.*`, `start.*`, `assess.*`, `tests/test_setup_cmd.py`, `tests/test_download.py` | Setup steps are idempotent (second run prints skips) with `huggingface_hub` mocked; disk check aborts below model + 5 GB with a plain message; `mflux_cached()` returns the real snapshot on this Mac without network (`HF_HUB_OFFLINE=1`); `download_diffusers("gguf_q8_offload")` requests `allow_patterns` that exclude `transformer/*.safetensors` and the GGUF file name from config; launchers: `sh -n setup.sh start.sh assess.sh` pass, `.bat` files use `%~dp0` and `uv run`; `smoke --fake-engine` writes a PNG under `<root>/_smoke/` and prints time + path. | 90 min |
| T11 | **Docs.** | T8, T10 (commands final) | `README.md`, `docs/*.md`, `tests/test_docs_commands.py` | Every fenced command in README/docs that starts with `python -m medimg`, `uv run`, `./setup`, `./start`, `./assess` refers to an existing file or CLI command (test parses the docs and checks); README is a 5-step quick start; SETUP_WINDOWS_NVIDIA.md and SETUP_LINUX_NVIDIA.md carry the "unverified on real hardware" banner and the driver ≥ 570 check; SAFETY_AND_LICENCES.md states Apache-2.0 for `Tongyi-MAI/Z-Image-Turbo`, "other" for the 4-bit conversion, the EU AI Act note from RESEARCH.md §0.4, adults-only and no-likeness; TROUBLESHOOTING.md has all 7 required rows; FUTURE.md describes the four items and builds none. | 120 min |
| T12 | **Real-model smoke on this Mac** (Verifier, not a worker): `./setup.command` reuses the cache (no download), `smoke` 512×512 @ 4 steps, then one 1024×1024 @ 9 via the UI. | all | none (fixes go to owners) | Acceptance 1, 2, 10. Record peak GB and times in VERIFICATION.md. | 45 min |

Sequence: T0 → {T1, T2, T3, T4, T5, T6, T9} in parallel → T7 → {T8, T10} in parallel → T11 → Reviewer → Fixers → Verifier (T12). Critical path ≈ 60 + 90 + 90 + 120 + 120 min ≈ 8 h of worker time; wall-clock far less with parallel workers.

---

## 6. Acceptance mapping (brief section 10 → tests)

| Criterion | Proven by |
|---|---|
| 1 real run on this Mac | T12 (Verifier) |
| 2 assess + estimates ±30 % | T6 unit tests + T12 measurement |
| 3 mixed sheet counts/reasons | T2 + T8 |
| 4 handoff simulation | T8 `test_api_handoff.py` |
| 5 cancel + kill/restart | T7 cancel test, T8 crash-resume test, T12 manual kill |
| 6 gate in batch/single/regenerate | T1 + T7 (worker re-check) + T8 (routes) |
| 7 all tests + CI valid | T0 workflow + `uv run pytest` |
| 8 diffusers engine mocked + docs banner | T5 + T11 |
| 9 `git ls-files` clean | T0 `.gitignore` + Verifier |
| 10 README followed word for word | T11 + T12 |

---

## 7. Risks

1. **Universal lock with conflicting torch pins.** mflux needs `torch>=2.13`, the NVIDIA extra pins `torch==2.9.1`. `[tool.uv] conflicts = [[{extra = "mac"}, {extra = "nvidia"}]]` plus platform markers must make `uv lock` succeed. If it does not, fall back to two requirement files (`requirements-mac.txt`, `requirements-nvidia.txt`) installed by `uv pip install` from the launchers; T0 decides and records it.
2. **Python 3.12 needs new wheels on this Mac** (mlx cp312 ~30 MB, torch cp312 darwin ~70 MB, plus small packages). Disk is 27 GB free; the venv will be ~1.2 GB. Acceptable. Never add diffusers to the Mac environment.
3. **Resident memory on 16 GB Macs.** Reference measured 7.8–8.5 GB peak txt2img; `unload_after_job` defaults on at ≤ 16 GB (D17). If T12 sees peak > 11 GB or swap growth > 1 GB with the model resident, keep the default and note it.
4. **NVIDIA path is untested on hardware.** Every NVIDIA number in this plan is derived from file sizes and the model card. The docs carry the "unverified on real hardware" banner until a real run is logged. GGUF modes are doubly experimental (community evidence only).
5. **`low_cpu_mem_usage=False` in the official snippet** has no documented reason; we omit it. If loading fails on the first real NVIDIA run, add it and record why.
6. **`_interrupt` leaves a decoded garbage image** — the engine discards it; a cancel costs one VAE decode (seconds).
7. **openpyxl drops some workbook features** (charts, images, some conditional formats). Document in USING_THE_SHEET.md: keep the prompt sheet simple.
8. **Windows file locking**: the intern may have the original sheet open in Excel; we copy it first (6.3), so only the copy is written. Download returns bytes (D22).
9. **False positives in the rules regex** ("school" in "medical school") block a prompt; the reason text says how to rephrase. Accepted by the brief's design.
10. **Port 8750** is free on this Mac today; the launcher error text tells the user the `--port` fallback.
11. **Estimates after benchmark** may be off by more than ±30 % at 768×1344 on the first real run; actuals override after one image (D24), which is what the acceptance criterion measures.
12. **mflux 0.23.0 exists**; do not upgrade without re-running T4 contract tests against the new source and the smoke test.

---

## 8. Next action for the Manager

Start T0 (scaffold). Its first check is `uv sync` on this Mac installing neither torch nor mflux and `uv run pytest` running the FakeEngine contract tests. Then dispatch T1–T6 and T9 in parallel.
