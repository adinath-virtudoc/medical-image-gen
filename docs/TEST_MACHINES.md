# Testing on real computers

The automatic tests in this repo use a fake image maker, so they cannot tell you whether a real model
loads, fits in memory, or is fast enough on a given computer. This guide covers the three ways to test
on real hardware, and how to read the results. The table of what each kind of test proves is in
[ARCHITECTURE.md](ARCHITECTURE.md#test-strategy).

## The three ways to test on real hardware

| Way | Who runs it | Where it runs | Use it when |
|---|---|---|---|
| 1. The self-test | The person at the computer | That computer | A new computer or laptop needs checking |
| 2. The GitHub real run | Adinath, from the GitHub website (also weekly, by itself) | A computer that GitHub lends for the run (Windows and Ubuntu, processor only) | You want a check without touching any laptop |
| 3. A self-hosted runner | Adinath, from the GitHub website | A real laptop that has been registered for this (for example the intern's laptop) | You want the exact laptop tested, with no back-and-forth |

## 1. The self-test

Run it after setup. It makes one small test image for each engine that is installed, and writes a
report. It never downloads anything and it does not change your saved settings.

- Mac: double-click `selftest.command`, or paste `./selftest.command`.
- Windows: double-click `selftest.bat`, or in PowerShell paste `.\selftest.bat`.
- Linux: paste `./selftest.sh`.

```sh
./selftest.sh
```

It takes a few minutes. On a slow laptop allow up to about 5 minutes per image. The window shows
"Test 1 of N" and a step count. When it ends, the folder with the report opens.

**What the report contains.** Two files in the `_selftest` folder inside the output folder (default
`medical-image-gen-output` in your home folder): a `.txt` you can read, and a `.json` with the same
facts for tools. They list the computer (system, processor, memory, graphics chip), one block per test
image (engine, size, steps, time per step, peak memory, which chip was used, whether it had to switch
to the processor), the plain-language cause and fix for any failure, and the last lines of the image
program's own output. The test images are saved next to the reports. Send both report files to the
project owner.

**What the ending means (exit code).**

| Result | Meaning |
|---|---|
| PASS (exit code 0) | At least one test image was made and none failed |
| FAIL (exit code 1) | A test image failed or timed out. The report says why |
| Nothing to test (exit code 2) | Nothing is installed yet. Run setup first, then the self-test again |

Useful options for developers: `--quick` (stop after the first ready test), `--all-tiers` (try every
downloaded model size), `--engine sdcpp`, `--tier low`, `--timeout SECONDS`, `--no-open`.

## 2. The GitHub real run

The workflow `real-run` makes a real image on a computer that GitHub lends for about half an hour. It
runs on Windows and on Ubuntu, on the processor (these computers have no graphics card), with the
smallest model size (`low`). It checks:

- setup downloads the program and models and the checksums match
- the graphics-chip build is tried and the app falls back to the processor build if it fails
- the app starts, accepts the sample sheet, and makes images through the web address (end to end)
- the self-test passes

It runs by itself every Monday (about 04:23 UTC). It never runs from a pull request.

**How Adinath starts it.**

1. Open the repo on GitHub and click the **Actions** tab.
2. Click **real-run** in the list on the left.
3. Click **Run workflow** (right side).
4. In **Where to run**, choose `github-cpu`, then click the green **Run workflow** button.

**How to read the results.**

1. Open the finished run and wait for the green tick or red cross next to each system.
2. Scroll to **Artifacts** at the bottom and download the artifact zip for the system (for example
   `real-run-windows-latest`). Unzip it.
3. Open the `selftest_...txt` file: it is the readable report. Open `e2e_result.json` for the
   end-to-end check: it lists each step and whether it passed.

**Cost and time.** Allow roughly 20 to 40 minutes per system. On a private repo, GitHub counts Windows
minutes at double the rate of Ubuntu minutes against the free monthly allowance, so a Windows run uses
about twice what its clock time says. Check the plan's usage page before running it often.

## What a self-hosted runner is

A runner is the program that does the work when a GitHub workflow starts. Normally GitHub lends one.
A **self-hosted runner** is a runner you install on your own computer, so GitHub's workflow runs on
that computer instead. This is how Adinath can test the intern's laptop without asking the intern to
run anything: the laptop waits for a job, and the job runs the same checks as the GitHub real run, with
the laptop's real memory, graphics chip and driver.

## The security trade-off

Read this before registering any computer.

- A self-hosted runner **runs this repo's workflow code on that laptop, with that user's rights**. Anyone
  who can change the workflow file can run programs on the laptop.
- Use it only with a **private repo** and **trusted people**.
- The workflow is set up so that the lab job starts only from a manual **Run workflow** click. It never
  starts from a pull request or a push, so a stranger cannot trigger it.
- Prefer a **separate Windows user account** for the runner, with no personal files in it.
- Run the runner **only while testing**, and stop it (close the window) afterwards.

## Registering a Windows laptop

1. Install Git for Windows (from git-scm.com) on the laptop if it is not there yet.
2. On GitHub open the repo, then **Settings** -> **Actions** -> **Runners** -> **New self-hosted runner**,
   and choose **Windows** and **x64**.
3. Open PowerShell on the laptop and copy the commands from that page into it, one block at a time.
   Put the runner in a short folder such as `C:\ar` (the page's first commands make a folder; change its
   name to `C:\ar`). A short path avoids Windows "path too long" errors.
4. When the configuration command asks for **labels**, type `medimg-lab` and press Enter. Accept the
   defaults for the other questions.
5. Start the runner with `run.cmd` and leave the window open. The window says "Listening for Jobs" when
   it is ready. Do not install it as a service, so it stops when you close the window.
6. On GitHub open **Settings** -> **Actions** -> **Runners**. The laptop should show as **Idle**. The
   test job runs setup itself, so the first run downloads about 5 GB and takes 20-60 minutes longer.
   Leave the laptop plugged in and awake.

## Registering a Mac

1. Install Git (Terminal asks to install the command line tools the first time you type `git`).
2. On GitHub open the repo, then **Settings** -> **Actions** -> **Runners** -> **New self-hosted runner**,
   and choose **macOS** and **ARM64**.
3. Open Terminal and copy the commands from that page into it, one block at a time. Use a short
   folder such as `~/ar`.
4. When the configuration command asks for **labels**, type `medimg-lab` and press Enter.
5. Start the runner with `./run.sh` and leave the window open. It says "Listening for Jobs" when ready.
   Do not install it as a service.
6. Check that the Mac shows as **Idle** under **Settings** -> **Actions** -> **Runners**.

## Removing a runner

1. Close the runner window (or press Ctrl+C in it).
2. On GitHub open **Settings** -> **Actions** -> **Runners**, click the three dots next to the
   computer and choose **Remove runner**. Follow the remove command it shows (on Windows
   `.\config.cmd remove`, on Mac `./config.sh remove`) in the runner folder.
3. Delete the runner folder (`C:\ar` or `~/ar`).

## Running a test on the lab computer

1. Make sure the runner window is open on the laptop and it shows **Idle** on GitHub.
2. Open the **Actions** tab, click **real-run**, click **Run workflow**.
3. In **Where to run** choose `self-hosted` (or `both` to include GitHub's computers too).
4. In **Model tier on the lab machine** choose a tier (`auto` lets the laptop's memory decide; `low`
   is the safest on 8 GB).
5. Click the green **Run workflow** button. Wait. A slow laptop can need an hour or more.
6. Read the results the same way as the GitHub real run: download the artifact zip named
   `real-run-lab-...`, open the selftest `.txt` and `e2e_result.json`.
7. Close the runner window when you are done.

## The GPU option (a decision for Adinath, not built)

The NVIDIA graphics-card path stays "unverified on real hardware" until it runs on a real NVIDIA
card. Nothing here is built; these are the options:

- **GitHub GPU larger runners.** GitHub rents GPU machines. They are paid per minute and need a paid
  GitHub plan.
- **Rent a GPU cloud machine** and register it as a self-hosted runner (the same steps as above, with
  the Linux download). Paid by the hour; switch it off when finished.
- **Borrow an NVIDIA PC** and register it as a self-hosted runner for a day.

Which one to pick depends on the money and who can lend a machine. See also
[FUTURE.md](FUTURE.md).

## Where this fits

See the test-strategy table in [ARCHITECTURE.md](ARCHITECTURE.md#test-strategy) for what each kind
of test proves and what it cannot.
