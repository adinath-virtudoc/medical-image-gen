# Safety and licences

## Adults only

Every image must show an adult. This is a legal line, not a model setting.

- Every prompt goes through a server-side check before generation, in batch, Single image and
  Regenerate. A failing row gets status `blocked` with the reason and is never generated.
- A prompt passes when it states an age of 18 or over, or uses a word such as adult, middle-aged,
  elderly, older man or older woman.
- A prompt is blocked when it states an age from 0 to 17, or contains a minor term such as child, kid,
  teen, boy, girl, infant, baby, toddler, minor, newborn, adolescent, juvenile, paediatric.
- The check cannot be changed from the app or the sheet. It is deliberately strict and can block an
  innocent prompt (for example one containing "school"); rephrase it.

Why: sexualised or nude images of minors are illegal in almost every country whatever the intent,
and an open model has no filter of its own. For paediatric findings use licensed atlases or clothed,
diagrammatic material instead.

## No real-person likeness

Never try to make an image of a real, identifiable person, and never make nude images from photos of
real people (non-consensual intimate imagery is illegal in many places). Version 1 has no
image-to-image and no reference upload, so this is satisfied by design. If those features are added
later they need their own consent rules first.

## A clinician reviews every image

Open models invent anatomy: wrong fingers and toes, extra or missing parts, wrong joint angles. No
source has tested these models for anatomical accuracy. A qualified clinician must check every image
before it is used for teaching.

## Local only

- The app makes no network calls at run time. Only setup downloads packages and model weights.
- The server listens on 127.0.0.1 only, so other computers on your network cannot reach it. There is
  no option to change this.
- Prompts and images stay on your computer until you upload them yourself.

## Model licences

| Model | Used on | Licence |
|---|---|---|
| `Tongyi-MAI/Z-Image-Turbo` (original, 32.9 GB) | Windows and Linux with NVIDIA | Apache 2.0 (Apache-2.0) |
| `filipstrand/Z-Image-Turbo-mflux-4bit` (community 4-bit conversion, 5.9 GB) | Mac | The Hugging Face licence field says **other**. Read the model card and get an answer before any commercial use |
| `unsloth/Z-Image-Turbo-GGUF` (quantized transformer, small NVIDIA cards only) | NVIDIA cards under 15 GB | Listed as Apache 2.0 on its page; check the page again before commercial use |

The app's own code is private. Python packages keep their own licences.
This is not legal advice; ask your organisation's counsel before commercial use.

## EU AI Act transparency note

If the images are used in the EU, the AI Act (Article 50) puts transparency duties on AI-generated
content. These apply from 2 August 2026, with a later deadline of 2 December 2026 for machine-readable
marking of content from existing generative systems. In practice:

- Label images as synthetic when you publish or teach with them.
- Each image's metadata already records the model, seed and date in its sidecar `.json` file and in
  the PNG text data. Keep that metadata.
- Report the skin-tone mix (Fitzpatrick I-VI) when you describe a set.

Check the current text with your compliance contact; dates and guidance can change.
