"""CLI: python -m medimg setup | assess | serve | smoke. Imports nothing heavy."""
from __future__ import annotations

import argparse
import importlib
import os
import sys

from medimg.config import ENGINE_CHOICES, VERSION
from medimg.errors import MedimgError

# command -> (module, function, runs offline)
DISPATCH = {
    "setup": ("medimg.setup_cmd", "run", False),
    "assess": ("medimg.assess", "run", True),
    "serve": ("medimg.server", "main", True),
    "smoke": ("medimg.smoke", "run", True),
    "selftest": ("medimg.selftest", "run", True),
}


def _add_engine(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--engine", choices=ENGINE_CHOICES, default=None, metavar="{auto,sdcpp}",
                    help="image engine: 'auto' picks the best one for this computer; 'sdcpp' forces "
                         "the one that works without an NVIDIA card (Intel/AMD graphics or processor "
                         "only)")


def _add_tier(sp: argparse.ArgumentParser, choices=("auto", "low", "mid", "high")) -> None:
    sp.add_argument("--tier", choices=choices, default=None, metavar="{" + ",".join(choices) + "}",
                    help="sd.cpp model size: low (smallest), mid, high; 'auto' picks from this "
                         "computer's memory")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m medimg", description="Local medical image generator.")
    p.add_argument("--version", action="version", version=f"medical-image-gen {VERSION}")
    sub = p.add_subparsers(dest="command", metavar="{setup,assess,serve,smoke,selftest}")

    s = sub.add_parser("setup", help="one-time setup: download model, smoke test, assess")
    s.add_argument("--skip-smoke", action="store_true", help="skip the test image")
    s.add_argument("--skip-assess", action="store_true", help="skip the device assessment")
    s.add_argument("--yes", action="store_true", help="do not ask for confirmation")

    s.add_argument("--output-root", metavar="P", help="folder for output images")

    _add_engine(s)
    _add_tier(s)

    a = sub.add_parser("assess", help="check this machine and estimate speed")
    a.add_argument("--no-benchmark", action="store_true", help="detect only, no timing run")
    a.add_argument("--json", action="store_true", help="print the profile as JSON")
    a.add_argument("--output-root", metavar="P", help="folder for output images")

    a.add_argument("--retry-gpu", action="store_true",
                   help="test the graphics card again even if it failed before")

    _add_engine(a)
    _add_tier(a)

    v = sub.add_parser("serve", help="start the local web UI")
    v.add_argument("--port", type=int, metavar="N", help="port (default 8750)")
    v.add_argument("--fake-engine", action="store_true", help="use the fake engine (no model)")
    v.add_argument("--no-browser", action="store_true", help="do not open the browser")
    v.add_argument("--output-root", metavar="P", help="folder for output images")

    _add_engine(v)

    m = sub.add_parser("smoke", help="generate one test image with the real model")
    m.add_argument("--size", default="512x512", metavar="WxH", help="image size (default 512x512)")
    m.add_argument("--steps", type=int, default=4, metavar="N", help="steps (default 4)")
    m.add_argument("--fake-engine", action="store_true", help="use the fake engine (no model)")
    _add_engine(m)
    _add_tier(m)

    t = sub.add_parser("selftest", help="make one tiny real image per engine and write a report")
    t.add_argument("--quick", action="store_true", help="only the first ready engine")
    t.add_argument("--all-tiers", action="store_true", help="test every downloaded model size")
    t.add_argument("--size", default="512x512", metavar="WxH", help="image size (default 512x512)")
    t.add_argument("--steps", type=int, default=4, metavar="N", help="steps (default 4)")
    t.add_argument("--timeout", type=float, default=1800, metavar="SECONDS",
                   help="give up on one image after this long (default 1800)")
    t.add_argument("--output-root", metavar="P", help="folder for output images")
    t.add_argument("--no-open", action="store_true", help="do not open the report folder")
    t.add_argument("--json", action="store_true", help="print the report as JSON")
    t.add_argument("--fake-engine", action="store_true", help="use the fake engine (no model)")
    _add_engine(t)
    _add_tier(t, ("low", "mid", "high"))
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 2
    if not args.command:
        parser.print_help()
        return 2
    module_name, func_name, offline = DISPATCH[args.command]
    if offline:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        if e.name == module_name or (e.name and module_name.startswith(e.name + ".")):
            print(f"The '{args.command}' command is not available in this build "
                  f"(missing module {module_name}). Update the repo and try again.", file=sys.stderr)
            return 1
        print(f"Missing Python package '{e.name}'. Run the setup command again.", file=sys.stderr)
        return 1
    func = getattr(module, func_name, None)
    if func is None:
        print(f"The '{args.command}' command is not available in this build "
              f"({module_name}.{func_name} not found).", file=sys.stderr)
        return 1
    try:
        rc = func(args)
    except MedimgError as e:
        print(f"Problem: {e.cause}", file=sys.stderr)
        if e.fix:
            print(f"Fix: {e.fix}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 1
    return int(rc or 0)


if __name__ == "__main__":
    sys.exit(main())
