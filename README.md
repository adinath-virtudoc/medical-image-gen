# medical-image-gen

Generates medical illustration images on your own computer from an Excel sheet of prompts. It runs
open models with no safety filter, needs no account and no paid service, and sends nothing over the
network once it is set up.

## Requirements

| | Mac (Apple Silicon) | Windows 10/11 or Linux with NVIDIA | Windows/Linux without NVIDIA |
|---|---|---|---|
| Chip / GPU | M1 or newer (Intel Macs are not supported) | NVIDIA card with 8 GB VRAM or more (16 GB or more recommended) | Intel/AMD graphics or none |
| Memory | 16 GB RAM or more | 32 GB RAM recommended for 8-16 GB cards | 8 GB RAM minimum |
| Free disk | 11 GB (5.9 GB model + 5 GB margin) | 38 GB (32.9 GB model + 5 GB margin); about 18 GB in the small-GPU modes | 10-12 GB (up to 11.7 GB for computers with 24 GB RAM or more) |
| Driver | none | NVIDIA driver 570 or newer (check with `nvidia-smi`) | no driver needed for the processor path |
| Status | Tested | **Unverified on real hardware** (built and tested with mocks only) | **App path not yet verified on real hardware.** The `sd-cli` program alone was tested by hand on one 2021 Intel laptop (processor only) |
| Speed | about 3 min per 1024x1024 image and about 20 s per 512x512 draft (measured on an M2 Pro with 16 GB, 9 and 4 steps) | not measured yet; run `assess` to get an estimate | slow: 5-6 min per 512x512 draft on a 2021 laptop CPU |
| Internet | only during setup | only during setup | only during setup |

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

   Linux: `./setup.sh`. Windows: double-click `setup.bat`. A PC without an NVIDIA card is detected
   automatically: the same setup file (double-click `setup.bat`, or run `./setup.sh`) picks the slower processor engine (allow 20-60
   min for the download). Success looks like a final message that prints the exact command to start
   the app. See your system guide for details.

3. **Start** the app (about 10 seconds). Mac: double-click `start.command`, or paste:

   ```sh
   ./start.command
   ```

   Linux: `./start.sh`. Windows: double-click `start.bat`. Your browser opens at
   `http://127.0.0.1:8750`. The top strip says "local only" and the model state.
   "Model: not loaded" is normal at this point: the model loads when you press **Generate**, so the
   first image takes a few seconds longer.

4. **Upload the sample sheet.** In the browser open the "Excel batch" tab, click the upload button
   and choose `templates/image_prompts_sample.xlsx` from this folder. Cards show Total 3 and
   Pending 3. Press **Generate**.

5. **See the image.** Open the "Gallery" tab. Each image appears under Subject, Unit, Lecture as it
   finishes (about 3 min each at 1024x1024 on an M2 Pro; much longer without an NVIDIA card or a
   Mac). Images are saved in `medical-image-gen-output` in your home folder.

Stop the app with Ctrl+C in its terminal window, or by closing that window.

**Check the speed of this computer.** Open the "Device" tab. It shows the computer (chip, memory,
graphics), whether it is supported, and how long 1, 10, 25 and 50 images take at each size. Press
**Re-run benchmark** once after setup (about 1 minute) so the estimates match this computer; they
get more accurate as you generate real images.

## New computer? Run the self-test

After setup, double-click `selftest.command` (Mac) or double-click `selftest.bat` (Windows), or run
`./selftest.sh` (Linux). It makes one small test image per engine, takes a few minutes (up to about
5 minutes per image on a slow laptop), and writes a report into the `_selftest` folder inside the output
folder. Send both report files (the `.txt` and the `.json`) to the project owner. More ways to test on
real computers: [docs/TEST_MACHINES.md](docs/TEST_MACHINES.md).

## Windows/Linux without NVIDIA

A PC with Intel or AMD graphics, or no graphics card, uses the stable-diffusion.cpp engine. Setup
picks it automatically. It runs on the processor, so it is slow (5-6 minutes for a 512x512 draft on a
2021 laptop), but it needs only 8 GB of RAM and 10-12 GB of disk. Leave batches running overnight.
Step by step: [docs/SETUP_WINDOWS_SDCPP.md](docs/SETUP_WINDOWS_SDCPP.md). Research on other options:
[docs/HARDWARE_ALTERNATIVES.md](docs/HARDWARE_ALTERNATIVES.md).

## Guides

| Guide | Read it when |
|---|---|
| [docs/SETUP_MAC.md](docs/SETUP_MAC.md) | Setting up an Apple Silicon Mac |
| [docs/SETUP_WINDOWS_NVIDIA.md](docs/SETUP_WINDOWS_NVIDIA.md) | Setting up Windows with an NVIDIA card (unverified) |
| [docs/SETUP_LINUX_NVIDIA.md](docs/SETUP_LINUX_NVIDIA.md) | Setting up Linux with an NVIDIA card (unverified) |
| [docs/SETUP_WINDOWS_SDCPP.md](docs/SETUP_WINDOWS_SDCPP.md) | Setting up Windows or Linux without an NVIDIA card (slow, needs only 8 GB RAM) |
| [docs/USING_THE_SHEET.md](docs/USING_THE_SHEET.md) | Filling in the Excel sheet |
| [docs/HANDOFF.md](docs/HANDOFF.md) | Passing a half-finished sheet to the next person |
| [docs/PROMPTING_GUIDE.md](docs/PROMPTING_GUIDE.md) | Writing prompts that work |
| [docs/TEST_MACHINES.md](docs/TEST_MACHINES.md) | Testing on a real computer: self-test, GitHub real run, lab laptop |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Something went wrong |
| [docs/SAFETY_AND_LICENCES.md](docs/SAFETY_AND_LICENCES.md) | Rules, review duty, model licences |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it is built; adding a model |
| [docs/FUTURE.md](docs/FUTURE.md) | Ideas that are not built |
| [docs/HARDWARE_ALTERNATIVES.md](docs/HARDWARE_ALTERNATIVES.md) | Smaller models and non-NVIDIA options (research) |

**Adults only.** Every prompt must state an adult. Prompts that mention a minor are blocked and
never generated. A clinician must review every image before use.
