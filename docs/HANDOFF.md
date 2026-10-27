# Handing a sheet to the next person

The Excel sheet carries all progress. Pass it on and the next person continues from the pending rows.

**Rule: only one person works on a sheet at a time.** If two people generate from copies of the same
sheet, they will make the same images twice and the sheets will not merge. Wait for the handoff.

## The 5 steps

1. **Stop the batch** (about 1 min). In the app's "Excel batch" tab press **Cancel**. It stops after
   the current step. The row being made stays pending; finished rows stay done.
   Success: the status strip shows no running job.

2. **Download the updated sheet** (about 1 min). Press **Download updated sheet**. Save it with a
   clear name, for example `anatomy_prompts_after_alex.xlsx`.
   Success: opening it shows `done` on the finished rows with Seed Used, Machine and Output Path.

3. **Upload the output folder to the shared Google Drive** (5-30 min depending on the number of
   images). The folder is `medical-image-gen-output` in your home folder (or the folder shown in the
   app's settings). Upload the whole folder, including the subfolders and the `.json` files next to
   the images. Do not upload the `_sheets` or `_thumbs` folders unless asked.
   Success: the Drive folder shows the same Subject folders as your computer.

4. **Send the sheet to the next person** (1 min), by email or chat. Tell them how many rows are done.

5. **The next person sets up and uploads** (setup 15-60 min the first time, none after that). They run
   setup on their computer (see the setup guide for their system), start the app, open "Excel batch",
   upload the sheet, and check the cards. Done rows from the previous person show as Done even though
   their disk has no images. Pending rows are what they generate.

## Good habits

- Download the sheet again at the end of every session, even if you do not hand off.
- Do not edit the sheet in Excel while a batch is running; edit the downloaded copy afterwards.
- Images go back to the project owner by hand through Drive. There is no zip or export feature.

## Which engine made the images

Each image's sidecar `.json` file (saved next to the image) has an `engine` field that names the engine that made it. The sheet's Machine column shows the computer's name and its chip, which also tells you which computer made the image. A computer without an
NVIDIA card uses the stable-diffusion.cpp engine (`sdcpp`); it is slower, and the same prompts and
8 steps by default apply. Technical background: `PLAN_SDCPP.md` in the repo root.
