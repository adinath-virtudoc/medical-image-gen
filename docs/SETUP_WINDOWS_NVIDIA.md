# Setup on Windows 10/11 with an NVIDIA card

> No NVIDIA card (or an old or small one)? Setup now picks the sd.cpp engine automatically; see [SETUP_WINDOWS_SDCPP.md](SETUP_WINDOWS_SDCPP.md).

> **Unverified on real hardware.** This path was built and tested with mock libraries only. Nobody
> has yet run a real image on Windows with it. Expect to report problems. Times below are estimates.

Needs an NVIDIA card with 8 GB VRAM or more (16 GB or more recommended), 32 GB RAM recommended, and
38 GB free disk (about 18 GB for the small-GPU modes). AMD and Intel graphics are not supported.

## Steps

1. **Check the NVIDIA driver** (1 min). Open PowerShell (Start menu, type `PowerShell`) and paste:

   ```sh
   nvidia-smi
   ```

   Success: a table lists your card and a "Driver Version". It must be **570.65 or higher** (570 or
   newer). If the command is not found or the version is lower, install the latest driver from
   nvidia.com/drivers, restart, and check again (10-15 min).

2. **Turn on long paths** (2 min, one time). Open PowerShell as Administrator (right-click, Run as
   administrator) and paste both lines, then restart the computer:

   ```sh
   git config --system core.longpaths true
   New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force
   ```

   Also keep the repo in a short folder such as `C:\medimg`. Windows stops paths over 260 characters
   without this setting; this is the usual cause of "path too long" errors.

3. **Install Git** (3 min) from git-scm.com if `git --version` fails. Accept the defaults.

4. **Get the code** (1 min). In PowerShell:

   ```sh
   cd C:\
   git clone <the repo address you were given> medimg
   cd medimg
   ```

   Success: `dir` shows `README.md` and `setup.bat`.

5. **Run setup** (about 10 min of installing, plus the model download). Double-click `setup.bat`, or
   in PowerShell:

   ```sh
   .\setup.bat
   ```

   What it does:
   - installs `uv` if missing (1 min). You do not need to install Python; `uv` fetches Python 3.12.
     To install `uv` yourself:

     ```sh
     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
     ```

   - installs PyTorch and the other packages, about 3 GB: 5-15 min
   - downloads the model, **32.9 GB** in the full mode: 30-120 min depending on internet. Small cards
     (under 15 GB VRAM) use a smaller quantized model, about 13 GB: 10-40 min
   - makes one 512x512 test image at 4 steps (1-3 min the first time) and prints where it was saved
   - measures the machine and writes `device_profile.json` (3-6 min)
   Success: the last lines print the exact command to start the app.

   If you see "path too long" or the download stops, go back to step 2, then run `.\setup.bat` again.
   Finished steps are skipped.

6. **Start the app** (10 s). Double-click `start.bat`, or:

   ```sh
   .\start.bat
   ```

   Success: the browser opens at `http://127.0.0.1:8750`. If the port is busy, use
   `.\start.bat --port 8751`.

7. **First image**: follow steps 4 and 5 of the README quick start.

## Which mode will I get?

The app chooses by VRAM. 22 GB or more: everything on the card. 15-22 GB: parts move to RAM between
steps. 10-15 GB and 7.5-10 GB: smaller quantized models (experimental). Under 7.5 GB: not supported.
Run `.\assess.bat --no-benchmark` to see the decision for your machine.

```sh
.\assess.bat --no-benchmark
```

Problems: see [TROUBLESHOOTING.md](TROUBLESHOOTING.md) (CUDA not available, out of memory, path too long).
