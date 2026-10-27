# Setup on a Mac (Apple Silicon)

Works on M1 or newer with 16 GB RAM or more. Intel Macs are not supported. Total time: about 5 min if
the model is already on the Mac, 15-40 min for a first download.

## Steps

1. **Check the Mac** (1 min). Apple menu, "About This Mac": the chip must say "Apple M1" or newer and
   memory 16 GB or more. Free disk space must be at least 11 GB.
   Success: you see an M-series chip name.

2. **Open a terminal** (1 min): press Cmd+Space, type `Terminal`, press Enter.

3. **Get the code** (1 min). Paste, using the address you were given:

   ```sh
   git clone <the repo address you were given> medical-image-gen
   cd medical-image-gen
   ```

   Success: `ls` shows `README.md` and `setup.command`.

4. **Run setup** (2 min of installing, plus the model download if needed). Paste:

   ```sh
   ./setup.command
   ```

   Or double-click `setup.command` in Finder. If macOS says it cannot be opened, right-click the file,
   choose Open, then Open again.
   What it does, in order:
   - installs `uv` and Python 3.12 if missing (about 1 min, needs internet)
   - installs the packages (about 1-3 min)
   - downloads the model, 5.9 GB: 5-20 min depending on your internet. If it is already in the
     Hugging Face cache, this is skipped and shows "already done"
   - makes one 512x512 test image at 4 steps (about 30-60 s) and prints where it was saved
   - measures this Mac and writes `device_profile.json` (about 2-4 min)
   Success: the last lines show the test image path and the exact command to start the app.

   To skip the slow checks, add flags:

   ```sh
   ./setup.command --skip-smoke --skip-assess
   ```

   Setup is safe to run again; finished steps are skipped.

5. **Start the app** (10 s). Paste:

   ```sh
   ./start.command
   ```

   Success: the browser opens at `http://127.0.0.1:8750`. If it does not, open that address yourself.
   If the port is busy, run `./start.command --port 8751` and open `http://127.0.0.1:8751`.

6. **First image** (1-4 min): follow steps 4 and 5 of the README quick start.

## Memory notes

On a 16 GB Mac the app unloads the model after each image to stay safe (adds about 8 s per image).
Close other large apps while generating. If you get an out-of-memory error, use the
`768x768 low-memory` size. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Comparing with the sd.cpp engine (optional)

You can also run the Mac with the stable-diffusion.cpp engine, the one used by PCs without NVIDIA, to
compare speed and pictures. This needs **macOS 26 or newer**; on an older macOS, setup stops with a
message and nothing is downloaded. Paste:

```sh
./setup.command --engine sdcpp
```

This downloads another set of model files (about 5.6 GB). To return to the normal Mac engine, paste
`./setup.command --engine auto`. See [SETUP_WINDOWS_SDCPP.md](SETUP_WINDOWS_SDCPP.md). Your choice is
saved only after setup finishes successfully. If macOS blocks the downloaded program, run
`xattr -d com.apple.quarantine` on it as described there (the path is in that guide).

## Check the machine again

```sh
./assess.command --no-benchmark
```
