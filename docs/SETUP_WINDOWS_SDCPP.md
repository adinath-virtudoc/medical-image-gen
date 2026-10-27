# Setup on Windows or Linux without an NVIDIA card

This guide is for a laptop or PC with Intel or AMD graphics, or no graphics card at all. If you have a
recent NVIDIA card, use [SETUP_WINDOWS_NVIDIA.md](SETUP_WINDOWS_NVIDIA.md) or
[SETUP_LINUX_NVIDIA.md](SETUP_LINUX_NVIDIA.md) instead. Setup chooses for you, so you can also just
run it and read what it prints.

## What this is

The app normally needs a Mac or an NVIDIA card. This guide uses a small separate program called
stable-diffusion.cpp ("sd.cpp"). It is one file of about 30-40 MB. It needs no Python and no
installer, and it can run on the computer's main processor. Setup downloads it for you. It makes the
same pictures from the same model (Z-Image Turbo) with the same prompts, the same Excel sheet and the
same adults-only rule. The difference is speed: a processor is much slower than an NVIDIA card.

## What you need

- Windows 10 or 11 (64-bit), or Linux (64-bit, Ubuntu 24.04 or newer; older versions such as Ubuntu 22.04 or Debian 12 cannot run
  the image program, and setup stops early with a message before it downloads the models).
- At least 8 GB of RAM. With more RAM, setup picks a better-looking model file.
- 10 to 12 GB of free disk space (up to 11.7 GB with 24 GB of RAM or more): 5 to 6.7 GB for the model
  files (the amount depends on your RAM), plus 5 GB of spare room.
- Internet only during setup. After that the app works offline.
- No graphics driver is needed for the processor path.
- Windows only: the Microsoft Visual C++ Redistributable (x64). Most PCs already have it. If setup says a
  Windows system library is missing, install it from https://aka.ms/vs/17/release/vc_redist.x64.exe and run setup again.

## How long it takes

| Part | Time |
|---|---|
| Setup, once | 20-60 minutes, mostly the download of about 5 GB of model files |
| Starting the app | about 10 seconds |
| One 512x512 draft image | about 5-6 minutes on a 2021 laptop processor |
| One 1024x1024 image | estimated 20-25 minutes on the same laptop |

These numbers come from one real test: a 2021 laptop (Windows 11, Intel i5-1135G7, Intel Iris Xe
graphics, 7.7 GB RAM) made a 512x512 image at 8 steps in 342 seconds (about 5.7 minutes). That was
3 seconds to read the prompt, about 34 seconds for each of the 8 steps, and 69 seconds to turn the
result into a picture. A newer or faster processor will be quicker.

## Windows steps

1. **Get the code** (1 min). Download the project as a zip from the address you were given and unzip
   it, or in PowerShell paste, using that address:

   ```sh
   git clone <the repo address you were given> medical-image-gen
   cd medical-image-gen
   ```

   Success: the folder contains `README.md` and a file named `setup` with the type "Windows Batch File".

2. **Run setup** (20-60 min). Double-click `setup.bat`. A black window opens. It prints numbered
   steps. In order, it:
   - checks the computer (it prints your processor, RAM and free disk)
   - prints "already done (no extra Python packages needed)" for the package step
   - downloads the image program (about 30-40 MB) and about 5 GB of model files
   - makes one test image (several minutes; this is normal)
   - measures how fast this computer is (a few more minutes)

   Success: the last lines say "Setup finished" and show the command to start the app, and the window
   then closes by itself a moment later. If it closes, setup worked; double-click `start.bat` next. If
   something goes wrong, the window stays open and says "Stopped with an error"; read that message, then
   double-click `setup.bat` again (finished parts are skipped). You can leave the window and do
   something else while it downloads.

3. **Start the app** (10 s). Double-click `start.bat`. Your browser opens at
   `http://127.0.0.1:8750`. If it does not, open that address yourself.

4. **Make the first image.** Follow steps 4 and 5 of the quick start in the
   [README](../README.md). Start with the 512x512 draft size.

5. **Run the self-test** (a few minutes, up to about 5 minutes per image). Double-click `selftest.bat`.
   It makes one small test image and writes a report into the `_selftest` folder. Send both report
   files to the project owner. More in [TEST_MACHINES.md](TEST_MACHINES.md).

If Windows shows a blue "Windows protected your PC" box (SmartScreen) when you run the program,
click **More info**, then **Run anyway**. This is normal for a file downloaded from the internet.

## Linux steps

1. **Get the code** (1 min). In a terminal paste, using the address you were given:

   ```sh
   git clone <the repo address you were given> medical-image-gen
   cd medical-image-gen
   ```

2. **Run setup** (20-60 min). Paste:

   ```sh
   ./setup.sh
   ```

   Success: the last lines say "Setup finished" and show the command to start the app.

3. **Start the app** (10 s). Paste:

   ```sh
   ./start.sh
   ```

   Success: your browser opens at `http://127.0.0.1:8750`.

On Linux, run the self-test too (a few minutes): paste `./selftest.sh`. It writes a report into the
`_selftest` folder; send both report files to the project owner.

Linux note: the processor path needs no graphics driver. If you want the app to try your graphics chip,
it needs the Vulkan driver of your distribution (on Ubuntu, the package `mesa-vulkan-drivers` for
Intel and AMD). If the graphics chip does not work, the app uses the processor on its own.

## What to expect

- **Speed.** About 5-6 minutes for one 512x512 draft on a 2021 laptop processor. Pictures made at the
  draft size are good for checking a prompt. Skin can look a little blotchy because the model file is
  compressed to fit in 8 GB of RAM.
- **Batches.** Fill the sheet, press Generate, and leave the computer running overnight. Keep it plugged
  in and turn off sleep. Ten drafts take about an hour.
- **The default size** in the app is the 512x512 draft, and Steps is set to 8, which is the
  recommended value for this engine.
- **The 15-minute warning.** If the app estimates that one image will take more than 15 minutes, a
  yellow warning appears under the size. Pick a smaller size before you start a big batch.
- **The device label.** The top strip of the app shows the model state followed by the device in use,
  for example "cpu". Many Intel laptops show "cpu" because their graphics chip shares the computer's
  memory and runs out of it. This is expected, not a fault.
- **Memory.** Close other large programs (browser tabs, video calls) while generating.

## Forcing this engine on any computer

To use this engine on a computer that would normally pick another one (for example a Mac with macOS 26 or newer, or a PC with
an NVIDIA card, to compare), run setup with `--engine sdcpp`.

Linux (or Mac):

```sh
./setup.sh --engine sdcpp
```

Windows (PowerShell):

```sh
.\setup.bat --engine sdcpp
```

To go back to the normal choice for your computer:

```sh
./setup.sh --engine auto
```

Windows (PowerShell):

```sh
.\setup.bat --engine auto
```

Your choice is remembered until you change it.

## If your Mac blocks the program

This is only needed if you force this engine on a Mac, which must run **macOS 26 or newer**. If macOS says the downloaded program cannot be
opened because it is from an unidentified developer, run this in the Terminal:

```sh
xattr -d com.apple.quarantine ~/.medical-image-gen/tools/sdcpp/master-1015-e41fbcf/mac-arm64/sd-cli
```

## More help

- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for error messages and slow images.
- [HARDWARE_ALTERNATIVES.md](HARDWARE_ALTERNATIVES.md) for the research behind this engine and other
  options.
- [USING_THE_SHEET.md](USING_THE_SHEET.md) for filling in the Excel sheet.
