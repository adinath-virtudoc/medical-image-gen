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
