# Setup on Linux with an NVIDIA card

> No NVIDIA card (or an old or small one)? Setup now picks the sd.cpp engine automatically; see [SETUP_WINDOWS_SDCPP.md](SETUP_WINDOWS_SDCPP.md).

> **Unverified on real hardware.** This path was built and tested with mock libraries only. Nobody
> has yet run a real image on Linux with it. Expect to report problems. Times below are estimates.

Needs an NVIDIA card with 8 GB VRAM or more (16 GB or more recommended), 32 GB RAM recommended, and
38 GB free disk (about 18 GB for the small-GPU modes). AMD GPUs are not supported. Written for
Ubuntu 22.04 or newer (the no-NVIDIA sd.cpp path needs Ubuntu 24.04 or newer); other distributions work if `curl` and `git` are installed.

## Steps

1. **Check the NVIDIA driver** (1 min). In a terminal paste:

   ```sh
   nvidia-smi
   ```

   Success: a table lists your card and a "Driver Version". It must be **570.26 or higher** (570 or
   newer). If the command is missing or the version is lower, install a newer driver, for example on
   Ubuntu `sudo ubuntu-drivers install`, then restart and check again (10-15 min).

2. **Install git and curl** (1 min) if `git --version` fails. On Ubuntu:

   ```sh
   sudo apt update && sudo apt install -y git curl
   ```

3. **Get the code** (1 min):

   ```sh
   git clone <the repo address you were given> medical-image-gen
   cd medical-image-gen
   ```

   Success: `ls` shows `README.md` and `setup.sh`.

4. **Run setup** (about 10 min of installing, plus the model download). Paste:

   ```sh
   ./setup.sh
   ```

   What it does:
   - installs `uv` if missing (1 min). You do not need to install Python; `uv` fetches Python 3.12.
     To install `uv` yourself:

     ```sh
     curl -LsSf https://astral.sh/uv/install.sh | sh
     ```

   - installs PyTorch and the other packages, about 3 GB: 5-15 min
   - downloads the model, **32.9 GB** in the full mode: 30-120 min depending on internet. Small cards
     (under 15 GB VRAM) use a smaller quantized model, about 13 GB: 10-40 min
   - makes one 512x512 test image at 4 steps (1-3 min the first time) and prints where it was saved
   - measures the machine and writes `device_profile.json` (3-6 min)
   Success: the last lines print the exact command to start the app.

   If the file will not run, make it executable once with `chmod +x setup.sh start.sh assess.sh`.
   Setup is safe to run again; finished steps are skipped.

5. **Start the app** (10 s):

   ```sh
   ./start.sh
   ```

   Success: a browser opens at `http://127.0.0.1:8750`. On a server without a desktop, add
   `--no-browser` and open that address on the same machine. If the port is busy, use
   `./start.sh --port 8751`.

6. **First image**: follow steps 4 and 5 of the README quick start.

## Which mode will I get?

The app chooses by VRAM. 22 GB or more: everything on the card. 15-22 GB: parts move to RAM between
steps. 10-15 GB and 7.5-10 GB: smaller quantized models (experimental). Under 7.5 GB: not supported.

```sh
./assess.sh --no-benchmark
```

Problems: see [TROUBLESHOOTING.md](TROUBLESHOOTING.md) (CUDA not available, out of memory).
