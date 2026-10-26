# medical-image-gen

Generates medical illustration images on your own computer from an Excel sheet of prompts. It runs
open models with no safety filter, needs no account and no paid service, and sends nothing over the
network once it is set up.

## Requirements

| | Mac (Apple Silicon) | Windows 10/11 or Linux with NVIDIA |
|---|---|---|
| Chip / GPU | M1 or newer (Intel Macs are not supported) | NVIDIA card with 8 GB VRAM or more (16 GB or more recommended); AMD is not supported |
| Memory | 16 GB RAM or more | 32 GB RAM recommended for 8-16 GB cards |
| Free disk | 11 GB (5.9 GB model + 5 GB margin) | 38 GB (32.9 GB model + 5 GB margin); about 18 GB in the small-GPU modes |
| Driver | none | NVIDIA driver 570 or newer (check with `nvidia-smi`) |
| Status | Tested | **Unverified on real hardware** (built and tested with mocks only) |
| Speed (9 steps) | about 1-4 min per image at 1024x1024 or 768x1344 on an M2 Pro | not measured yet; run `assess` to get an estimate |
| Internet | only during setup | only during setup |

You do not need to install Python yourself; setup installs everything it needs.

## Quick start (5 steps)

1. **Clone** the repo (about 1 min). In a terminal:

   ```sh
   git clone <the repo address you were given> medical-image-gen
   cd medical-image-gen
   ```

2. **Set up** once (Mac with the model already downloaded: about 5 min; first download: 10-30 min).
   Mac: double-click `setup.command` in Finder, or paste:

   ```sh
   ./setup.command
   ```

   Linux: `./setup.sh`. Windows: double-click `setup.bat`. Success looks like a final message that
   prints the exact command to start the app. See your system guide for details.

3. **Start** the app (about 10 seconds). Mac: double-click `start.command`, or paste:

   ```sh
   ./start.command
   ```

   Linux: `./start.sh`. Windows: double-click `start.bat`. Your browser opens at
   `http://127.0.0.1:8750`. The top strip says "local only" and the model state.

4. **Upload the sample sheet.** In the browser open the "Excel batch" tab, click the upload button
   and choose `templates/image_prompts_sample.xlsx` from this folder. Cards show Total 3 and
   Pending 3. Press **Generate**.

5. **See the image.** Open the "Gallery" tab. Each image appears under Subject, Unit, Lecture as it
   finishes (about 1-4 min each). Images are saved in `medical-image-gen-output` in your home folder.

Stop the app with Ctrl+C in its terminal window, or by closing that window.

## Other Windows hardware (researched, not built yet)

Today Windows needs an NVIDIA card and a 32.9 GB model download. Research on 2026-10-26 found
smaller options, similar to the 5.9 GB 4-bit model the Mac uses. **None of these is built into
this tool yet, and none has been tested on real hardware.**

| Windows machine | Best option found | Download | Status |
|---|---|---|---|
| NVIDIA 8-12 GB | Z-Image Turbo GGUF Q4_K_M (12 GB: Q6_K) from `unsloth/Z-Image-Turbo-GGUF`, with CPU offload | 5.0 / 5.9 GB model file | Planned for v1.1. Works with the current diffusers engine |
| NVIDIA 16 GB | Z-Image Turbo GGUF Q8_0 (close to full quality) | 7.2 GB instead of 32.9 GB | Planned for v1.1 |
| NVIDIA, fastest | Nunchaku int4 (`nunchaku-ai/nunchaku-z-image-turbo`) | about 3-4 GB (estimate) | On hold until Windows install support is confirmed |
| AMD or Intel GPU, laptop graphics | stable-diffusion.cpp (Vulkan build) with `leejet/Z-Image-Turbo-GGUF` | about 6-9 GB in total | Candidate for v2. Needs a new engine |
| No GPU (CPU only) | stable-diffusion.cpp (CPU build) | about 6-9 GB in total | Candidate for v2. Expect several minutes per image |

Full findings, the other models compared, and sources:
[docs/HARDWARE_ALTERNATIVES.md](docs/HARDWARE_ALTERNATIVES.md).

## Guides

| Guide | Read it when |
|---|---|
| [docs/SETUP_MAC.md](docs/SETUP_MAC.md) | Setting up an Apple Silicon Mac |
| [docs/SETUP_WINDOWS_NVIDIA.md](docs/SETUP_WINDOWS_NVIDIA.md) | Setting up Windows with an NVIDIA card (unverified) |
| [docs/SETUP_LINUX_NVIDIA.md](docs/SETUP_LINUX_NVIDIA.md) | Setting up Linux with an NVIDIA card (unverified) |
| [docs/USING_THE_SHEET.md](docs/USING_THE_SHEET.md) | Filling in the Excel sheet |
| [docs/HANDOFF.md](docs/HANDOFF.md) | Passing a half-finished sheet to the next person |
| [docs/PROMPTING_GUIDE.md](docs/PROMPTING_GUIDE.md) | Writing prompts that work |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Something went wrong |
| [docs/SAFETY_AND_LICENCES.md](docs/SAFETY_AND_LICENCES.md) | Rules, review duty, model licences |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it is built; adding a model |
| [docs/FUTURE.md](docs/FUTURE.md) | Ideas that are not built |
| [docs/HARDWARE_ALTERNATIVES.md](docs/HARDWARE_ALTERNATIVES.md) | Smaller models and non-NVIDIA options (research) |

**Adults only.** Every prompt must state an adult. Prompts that mention a minor are blocked and
never generated. A clinician must review every image before use.
