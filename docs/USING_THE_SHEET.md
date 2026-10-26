# Using the Excel sheet

The sheet is the only record of progress. Start from `templates/image_prompts_template.xlsx` (empty,
with a "How to fill" tab) or look at `templates/image_prompts_sample.xlsx` (3 example rows).

## Columns

Header names are matched ignoring capital letters and extra spaces. Column order does not matter.

| Column | Required | What to put |
|---|---|---|
| Subject | yes | Becomes the top folder, e.g. `Anatomy` |
| Unit | yes | Becomes the second folder, e.g. `Upper limb` |
| Lecture | yes | Becomes the third folder, e.g. `Hand` |
| Image Prompt | yes | The full prompt. Must state an adult (see below) |
| Image Name | yes | File name without `.png`, e.g. `hand_xray_ap` |
| Status | yes, may be blank | See statuses below. Blank means pending |
| Size | optional | Width x height, e.g. `768x1344`. Blank uses the size chosen in the app |
| Seed | optional | A whole number. Blank gets a random seed, which the tool writes back |

The tool adds these columns itself after yours. Do not fill them in: Steps, Seed Used, Generated At,
Machine, Model, Generation Time (s), Output Path, Error.

## Statuses

| Status | Meaning | What you do |
|---|---|---|
| pending | Waiting to be generated (blank counts as pending) | Nothing |
| done | Image made. The sheet is trusted: a done row stays done even if the image is not on your disk | Nothing |
| failed | The model errored on this row; the reason is in Error | Switch on "Retry failed rows", or set Status to pending |
| blocked | The adults-only check stopped the prompt; the reason is in Error | Rewrite the prompt to state an adult age, then upload again |
| invalid | A cell is missing, Size is wrong, or two rows would save to the same file; the reason is in Error | Fix the cell, then upload again |

Blocked and invalid rows are re-checked every time you upload, so fixing the cell and uploading again
is enough. If a pending row already has its image at the expected place on your computer, it is marked
done (this covers resuming after a crash).

## Sizes

Pick one of the app's presets or type your own in the Size column. Sides are rounded down to a
multiple of 16, each side must be 256-1536, and width x height must not exceed 1,048,576 pixels.

| Size | Use for |
|---|---|
| 1024x1024 | Square, default |
| 768x1344 | Portrait, full body |
| 1344x768 | Landscape |
| 832x1216 | Portrait, close to 2:3 |
| 1216x832 | Landscape, close to 3:2 |
| 768x768 | Low memory |

## Image Name advice

- Use short, plain names: `knee_exam_lateral`, `shoulder_diagram_01`.
- Letters, numbers, `_` and `-` are safest. The characters `< > : " / \ | ? *` are removed.
- Do not add `.png`; if you do, the tool does not add a second one.
- Names are unique within one Subject/Unit/Lecture folder. Two rows with the same folder and name
  (ignoring capitals) are both marked invalid. Add a number to tell them apart.
- Keep names under about 60 characters; Windows limits total path length (240 here).

## The adults-only rule

Every prompt must state an adult: an age of 18 or over (`45-year-old`, `aged 60`) or a word such as
`adult`, `middle-aged`, `elderly`. A prompt is blocked if it states an age under 18 or contains a word
such as child, kid, teen, boy, girl, infant, baby, toddler, minor, newborn, adolescent, juvenile,
paediatric. This check runs on the server for every image and cannot be switched off from the sheet or
the app. Plain words can trigger it by accident (for example "school" in "medical school"); just
rephrase. Details: [SAFETY_AND_LICENCES.md](SAFETY_AND_LICENCES.md).

## Keep the sheet simple

The tool edits your file with a library (openpyxl) that keeps text, column widths and basic formatting
but can lose charts, pictures, macros and some conditional formatting. So:

- Keep prompts in plain cells, one row per image. No formulas, charts or pictures in the prompt sheet.
- Do not reorder rows once generation has started; the tool never reorders them.
- Keep extra notes in a different worksheet; other worksheets are left alone.
- Save as `.xlsx` (not `.xls` or `.csv`). Maximum file size 20 MB.
- The tool works on a copy, so having the original open in Excel is fine. Your original file is never
  changed; use "Download updated sheet" to get the new version.
