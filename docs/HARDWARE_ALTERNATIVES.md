# Hardware alternatives

This page records research done on 2026-10-26 into smaller models for Windows and Linux machines,
similar to the 5.9 GB 4-bit model the Mac uses. **Section 2 (stable-diffusion.cpp) is built in v0.2 as the
`sdcpp` engine. The other sections are research only and untested on real hardware.**

How to read it:
- File sizes come from Hugging Face file listings.
- Memory and speed figures are estimates or community reports unless a source is given.
- Before building any option, measure peak VRAM and seconds per image at 1024x1024 on a real
  machine.

## 1. NVIDIA cards with less memory (same model, smaller files)

The official `Tongyi-MAI/Z-Image-Turbo` download is 32.9 GB, because its main model file is stored
at full precision. Compressed versions of the same model already exist.

| Option | Hugging Face repo | Size | Licence | Fit with this tool |
|---|---|---|---|---|
| GGUF (recommended) | `unsloth/Z-Image-Turbo-GGUF` | Q3_K_M 4.19 GB, Q4_K_M 5.02 GB, Q5_K_M 5.57 GB, Q6_K 5.91 GB, Q8_0 7.22 GB | Apache-2.0 | The diffusers engine already has an experimental GGUF mode |
| GGUF (alternative) | `jayn7/Z-Image-Turbo-GGUF` | Q4_K_M 4.98 GB, Q6_K 5.91 GB, Q8_0 7.22 GB | Apache-2.0 | Made for ComfyUI; the files load the same way |
| SDNQ int8 | `Disty0/Z-Image-Turbo-SDNQ-int8` | 6.2 GB | Apache-2.0 | Full diffusers repo; needs the extra `sdnq` package; small project |
| Nunchaku int4 / fp4 | `nunchaku-ai/nunchaku-z-image-turbo` | not listed (about 3-4 GB, estimate) | Apache-2.0 | Fastest on RTX cards; Windows install support not confirmed |
| FP8 | `drbaph/Z-Image-fp8` | about half the size | Apache-2.0 | Made for ComfyUI; diffusers loading not confirmed |

The Qwen3-4B text encoder takes about 8 GB at bf16, which makes it the largest single use of
memory. Smaller copies exist in `unsloth/Qwen3-4B-GGUF` (Q4_K_M 2.50 GB, Q8_0 4.28 GB).
Whether diffusers can load these copies for Z-Image has not been confirmed. With CPU offload, the
encoder already leaves the GPU after it has read the prompt.

**Suggested picks (all with CPU offload):**

| Card | First choice | Second choice |
|---|---|---|
| 8 GB | unsloth Q4_K_M (or Q3_K_M) | Nunchaku int4 r32, if it installs on Windows |
| 12 GB | unsloth Q6_K or Q5_K_M | Nunchaku int4 r128 |
| 16 GB | unsloth Q8_0 | the current bf16 mode |

## 2. Windows without NVIDIA: built in v0.2 (sdcpp engine)

The stable-diffusion.cpp path below is now the `sdcpp` engine. Setup guide:
[SETUP_WINDOWS_SDCPP.md](SETUP_WINDOWS_SDCPP.md). How it works: [ARCHITECTURE.md](ARCHITECTURE.md).

**Model files by memory tier** (all Apache-2.0, ungated, SHA256-pinned):

| Tier | Computer RAM | Image model | Text model | Decoder | Download |
|---|---|---|---|---|---|
| low | under 12 GB | Z-Image Turbo Q2_K (2.59 GB) | Qwen3-4B Q3_K_M (2.08 GB) | ae.safetensors (0.34 GB) | 5.00 GB |
| mid | 12 to 24 GB | Z-Image Turbo Q3_K (3.14 GB) | Qwen3-4B Q3_K_M (2.08 GB) | ae.safetensors (0.34 GB) | 5.56 GB |
| high | 24 GB or more | Z-Image Turbo Q4_K (3.86 GB) | Qwen3-4B Q4_K_M (2.50 GB) | ae.safetensors (0.34 GB) | 6.70 GB |

Below 7 GB of RAM the machine is unsupported. Other quantisations of the image model in
`leejet/Z-Image-Turbo-GGUF` are possible future tiers, not built: Q4_0 3.683 GB, Q5_0 4.543 GB,
Q6_K 5.263 GB, Q8_0 6.577 GB.

**Field result.** The `sd-cli` program alone (run by hand, not through this app, which is not yet
verified on real hardware) was tested on one real laptop (Windows 11, Core i5-1135G7, 7.7 GB RAM, Intel Iris Xe graphics),
tier low, 512x512, 8 steps, on the processor: 342 s per image (prompt 3 s, sampling 270 s, about 34 s per
step, decoding 69 s). Quality is fine for drafts; skin can look blotchy at Q2_K. The Iris Xe graphics
chip ran out of memory in all three tries, even with the text model and decoder moved to the processor.
A 1024x1024 image is estimated at 20 to 25 minutes on that machine (an estimate, not measured).

**Device policy.** The default device is the processor (`cpu`). The graphics chip (`vulkan0`) is tried
first only on AMD, on Intel with 16 GB RAM or more, and on NVIDIA when `--engine sdcpp` is forced; if
that fails, the app records why and uses the processor. Intel graphics with under 16 GB RAM goes
straight to the processor. On an Apple silicon Mac, `--engine sdcpp` uses Metal. To force a device, set
`sdcpp_device` to `cpu`, `vulkan0` or `metal` in `~/.medical-image-gen/config.json`.

Original research notes:

| Path | Supports Z-Image? | Verdict |
|---|---|---|
| stable-diffusion.cpp, Vulkan build (AMD, Intel Arc, laptop graphics) | Yes (added December 2025) | **Built in v0.2.** It is a standalone program with no Python. It uses `leejet/Z-Image-Turbo-GGUF` (Q4_0 3.68 GB, Q8_0 6.58 GB), a FLUX VAE and a Qwen3-4B GGUF. Its docs say it runs on GPUs with 4 GB of VRAM. MIT licence |
| stable-diffusion.cpp, CPU build | Yes | Fallback for any machine. Measured: about 5.7 minutes per 512x512 draft on a 2021 laptop |
| PyTorch ROCm on Windows (AMD Radeon 7000/9000) | Not shown | Preview only. It would reuse the diffusers engine, but driver and Python setup is too hard for an intern |
| Intel XPU PyTorch | Not shown | Check again later |
| OpenVINO, DirectML, ONNX, ZLUDA | No | Skip |

Done for the build: release `master-1015-e41fbcf` is pinned, the asset names are in `medimg/sdcpp/pins.py`,
and the seed flag is `-s`.

## 3. Other model families (if Z-Image is ever not enough)

| Model | Licence | Notes |
|---|---|---|
| Chroma1-HD (`lodestones/Chroma1-HD`) | Apache-2.0 | Its model card says it has no safety filter. Needs 40 steps, so it is slower. Community GGUF copies fit 8-12 GB |
| FLUX.1-schnell GGUF (`city96/FLUX.1-schnell-gguf`) | Apache-2.0 | 4 steps. Q4_K_S is 6.8 GB. Community reports say it is weak on anatomy |
| SDXL photoreal fine-tunes (+ Lightning/Hyper) | CreativeML Open RAIL++-M | Runs on 6 GB cards. Each fine-tune has its own licence |
| Sana-Sprint 1.6B | Apache-2.0 (code licence separate) | Very small and fast; weak photorealism |
| Qwen-Image Q4 GGUF | Apache-2.0 | About 12 GB, so 16 GB cards only |

Not recommended:
- FLUX.1-dev: non-commercial licence.
- SD 3.5: licence limited by revenue, and filtered training data.
- HiDream-I1: too large for this hardware.

Community comparisons rate Z-Image Turbo above FLUX.1-dev on anatomy. Test any new model on about
20 clinical prompts and have a clinician review the results before switching.

## Sources

- https://huggingface.co/unsloth/Z-Image-Turbo-GGUF
- https://huggingface.co/jayn7/Z-Image-Turbo-GGUF
- https://huggingface.co/leejet/Z-Image-Turbo-GGUF
- https://huggingface.co/nunchaku-ai/nunchaku-z-image-turbo
- https://github.com/nunchaku-ai/nunchaku
- https://huggingface.co/Disty0/Z-Image-Turbo-SDNQ-int8
- https://huggingface.co/drbaph/Z-Image-fp8
- https://huggingface.co/unsloth/Qwen3-4B-GGUF
- https://huggingface.co/docs/diffusers/main/en/api/pipelines/z_image
- https://github.com/leejet/stable-diffusion.cpp
- https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/z_image.md
- https://github.com/leejet/stable-diffusion.cpp/wiki/How-to-Use-Z%E2%80%90Image-on-a-GPU-with-Only-4GB-VRAM
- https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/windows/install-pytorch.html
- https://docs.pytorch.org/docs/stable/notes/get_start_xpu.html
- https://huggingface.co/lodestones/Chroma1-HD
- https://huggingface.co/city96/FLUX.1-schnell-gguf
- https://huggingface.co/black-forest-labs/FLUX.1-schnell
- https://huggingface.co/black-forest-labs/FLUX.1-dev
- https://huggingface.co/stabilityai/stable-diffusion-3.5-medium
- https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0
- https://huggingface.co/Efficient-Large-Model/Sana_Sprint_1.6B_1024px
- https://huggingface.co/Qwen/Qwen-Image
