# Future ideas (not built)

None of this exists in version 1. These are descriptions only.

## 1. Assessment to a research prompt

Turn `device_profile.json` into a ready-made prompt that a person pastes into a research agent. The
prompt would state the machine (chip, memory, VRAM, disk) and ask for open, unfiltered image models
that fit it, with sources and licences. The profile keys are kept stable so this can be added without
changing the file.

## 2. A catalogue by machine class

A maintained list that maps a machine class (chip or GPU, RAM, VRAM) to a model and its best
settings: steps, size and sampler. Setup could look the machine up and apply the entry. It needs an
owner who tests new entries and updates it.

## 3. Model selection per machine

Let the app offer more than one model and choose, or suggest, the best one for the machine, using
the assessment and the catalogue. Today each platform has exactly one model.

## 4. Image-to-image, ControlNet and zip export

- **Image-to-image** and **ControlNet** (pose or depth guidance) would let a prompt follow a
  reference. They need consent and likeness rules first (see
  [SAFETY_AND_LICENCES.md](SAFETY_AND_LICENCES.md)), so they are left out of version 1.
- **Zip export** would bundle the output folder and the sheet for handoff. Today images move by hand
  through Google Drive (see [HANDOFF.md](HANDOFF.md)).

## 5. Ideas for the stable-diffusion.cpp engine

The `sdcpp` engine is built (see [ARCHITECTURE.md](ARCHITECTURE.md)). These parts are not.

- **sd-server instead of one process per image.** `sd-cli` has a sibling program, `sd-server`, that
  keeps the model loaded and takes jobs over a local web address. It would save a few seconds per image
  on fast graphics cards. Today it adds a second long-running program and a port, and it holds about
  5 GB of memory between images, so one process per image is used.
- **Better time estimates at large sizes.** Estimates for 1024x1024 on a processor are rough, because
  decoding time grows with the picture size. The app corrects them after the first real image and
  warns above 15 minutes. A better curve would use the measured decode time at each benchmark size.
- **More model tiers.** Q4_0, Q5_0, Q6_K and Q8_0 of the image model could become extra tiers for
  computers with more memory (sizes in [HARDWARE_ALTERNATIVES.md](HARDWARE_ALTERNATIVES.md)), if the
  Q2_K and Q3_K anatomy is not good enough.
- **Re-pinning the release.** Releases of stable-diffusion.cpp appear for every code change, and old
  ones can be removed. If the pinned download disappears, change the release tag and checksums in
  `medimg/sdcpp/pins.py`, then re-run a real image and update the saved test logs.

## 6. Run self-test button in the Device tab

The Device tab shows only a hint that points to the self-test launcher (double-click `selftest.bat` on Windows or `selftest.command` on Mac). A button was left
out because it would load a second copy of the model while the app's worker may already hold one, which
runs 8-16 GB computers out of memory, and it would need a new kind of job. The launcher gives the same
report safely. A button could be added if the server learns to pause its worker first.

## 7. A GPU test machine

The NVIDIA path is untested on real hardware. Options (paid, so Adinath decides): GitHub GPU larger
runners, a rented GPU cloud machine registered as a self-hosted runner, or a borrowed NVIDIA PC. See
[TEST_MACHINES.md](TEST_MACHINES.md).
