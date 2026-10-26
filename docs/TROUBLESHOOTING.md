# Troubleshooting

Find the symptom, check the cause, apply the fix. The app's own error messages also state a cause and a fix.

| Symptom | Cause | Fix |
|---|---|---|
| Out of memory: the job fails, the model state shows an error, or the Mac becomes very slow | The picture is too large for this machine's memory, or other apps are using it | Choose the `768x768 low-memory` size, close other apps (browsers with many tabs, video calls), keep "unload model after each image" on, then generate again. On NVIDIA run `assess` to see the mode; a card under 15 GB uses a smaller model |
| Port in use: "port 8750 in use; run start --port N" | Another copy of the app, or another program, already uses port 8750 | Close the other copy, or start on another port, for example `./start.sh --port 8751`, then open `http://127.0.0.1:8751` |
| Model not found offline: "model unavailable" or a message that files are not in the cache | Setup never finished the download, or the Hugging Face cache was moved or deleted. The app never downloads at run time | Run setup again with internet (`./setup.sh`, `./setup.command` or `.\setup.bat`); it resumes the download |
| Sheet rejected: upload says the file cannot be read or no worksheet has the right headers | Not an `.xlsx` file, over 20 MB, password-protected, or the header row lacks Subject, Unit, Lecture, Image Prompt, Image Name, Status | Save as `.xlsx`, remove the password, and start from `templates/image_prompts_template.xlsx`. The "Problems" list names the row and the fix |
| CUDA not available: the app or `assess` says no usable NVIDIA GPU, or torch reports CUDA false | Driver older than 570 (Linux 570.26, Windows 570.65), no NVIDIA card, a CPU-only PyTorch installed, or a driver that needs a restart | Run `nvidia-smi`; update the driver and restart; then run setup again so the CUDA build of PyTorch installs. AMD and Intel graphics are not supported |
| Slow generation: an image takes far longer than the estimate | Large size, many steps, other apps competing, the machine on battery power or a laptop card running hot, or on 16 GB Macs the model reloads for each image | Use 9 steps or fewer, a smaller size, plug in the power, close other apps. Check the Device tab; the estimate improves after a few images. On NVIDIA the offload modes are slower than a big card |
| Windows path too long: setup or the download stops with a path or "filename too long" error | Windows limits paths to 260 characters and the repo or cache sits in a deep folder | Enable long paths (steps in [SETUP_WINDOWS_NVIDIA.md](SETUP_WINDOWS_NVIDIA.md)), keep the repo at `C:\medimg`, then run `.\setup.bat` again |
| A prompt is blocked: status `blocked` | The adults-only check found a minor term or no stated adult age | Add an age such as `45-year-old` or the word `adult` and remove words about children; upload again |
| A row is invalid: status `invalid` | Missing cell, bad Size, or two rows with the same output path | Read the Error cell, fix it, upload again |
| macOS says `setup.command` cannot be opened | The file came from a download and is not yet approved | Right-click the file, choose Open, then Open again; or run `./setup.command` in a terminal |
| A done image is missing from the Gallery | The sheet says done but this computer never made the image (it came from a previous person) | Nothing is wrong; the image is in the shared Drive folder |

## Still stuck

Run `./assess.sh --json` (Mac: `./assess.command --json`, Windows: `.\assess.bat --json`) and send the
output, plus the text of the error, to the project owner.
