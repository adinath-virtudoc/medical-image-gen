# Prompting guide

Write each prompt as a short, plain description of a clinical photograph or illustration. This guide
explains why the pattern below works with Z-Image Turbo, so you can adapt it.

## A worked example

This is a clothed, adult example that passes the safety check:

```text
Clinical medical photograph of the right knee of a 45-year-old adult woman seated on an examination couch, lateral view, knee flexed to 90 degrees, wearing shorts. Natural skin texture with visible pores and minor asymmetries. Plain light-grey clinical backdrop, even flat diffuse lighting, camera at knee height, 50mm lens, whole knee in frame. Medical textbook documentation style, objective and non-stylised.
```

## Why each part is there

| Part | Why it works |
|---|---|
| **Explicit adult age** (`45-year-old`) | The safety check requires an adult. A number is clearer to the model than just "adult", and it keeps the body and skin looking adult |
| **Clinical framing** (medical photograph, examination couch, textbook style, flat lighting) | Steers the model to an exam-room or atlas look rather than an artistic or glamour look |
| **Skin-realism words** (pores, minor asymmetries, natural texture) | Avoids the smooth, plastic skin that AI images often have |
| **Plain backdrop and even lighting** | Keeps attention on the body part and makes images consistent across a lecture |
| **Portrait size for full body** (`768x1344`) | A tall frame keeps head and feet inside the picture. Use `1344x768` for wide subjects |

## Making variations

Change one thing at a time and keep the rest of the prompt the same.

| Change | How |
|---|---|
| Same prompt, new image | Change the Seed (for example 42 to 43). In the Gallery use "Regenerate with new seed" |
| Skin tone | Add a Fitzpatrick type, for example `Fitzpatrick type V skin` (types I-VI). Use a mix across a lecture |
| Body type | `average build`, `thin`, `athletic`, `obese, BMI around 35` |
| Age | Use 30, 60 or 75; for older adults add `age-appropriate skin laxity` |
| View | `posterior view, facing away`, `left lateral view`, `anterior view` |
| Finding | Add one sentence, for example `Well-demarcated psoriatic plaques with silvery scale on both elbows` |

## Settings

- Steps: 9 is the default. Use 8-9 for Z-Image Turbo; more steps do not help much. The stable-diffusion.cpp engine (PCs without NVIDIA) uses the same prompts and 8 steps by default.
- There is no negative prompt and no guidance setting. Say what you want, not what you do not want.
- If you run out of memory, use `768x768` and keep the prompt the same.

## Always

- State an adult age in every prompt. Never mention children, teens or minors.
- Have a clinician check every image. Open models draw wrong hands, feet, joints and extra or missing parts.
