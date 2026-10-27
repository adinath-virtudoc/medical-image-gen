"""Human-readable report for the terminal and the UI Device panel."""
from __future__ import annotations

from medimg.assess.estimate import estimates_table
from medimg.config import DEFAULT_STEPS


def fmt_duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def render_report(profile: dict) -> str:
    m = profile.get("machine") or {}
    b = profile.get("backend") or {}
    gpu = m.get("gpu") or {}
    lines = ["DEVICE REPORT", "=============",
             f"Computer : {m.get('os_name', '?')} {m.get('os_version', '')} ({m.get('arch', '?')})",
             f"CPU      : {m.get('cpu', '?')}",
             f"Memory   : {m.get('ram_total_gb', 0):.1f} GB total, {m.get('ram_free_gb', 0):.1f} GB free"]
    if gpu:
        vram = f", {gpu['vram_gb']:.1f} GB VRAM" if gpu.get("vram_gb") else ""
        drv = f", driver {gpu['driver']}" if gpu.get("driver") else ""
        cuda = f", CUDA {gpu['cuda']}" if gpu.get("cuda") else ""
        lines.append(f"GPU      : {gpu.get('name', '?')}{vram}{drv}{cuda}")
    else:
        lines.append("GPU      : none found")
    lines.append(f"Disk     : {m.get('disk_free_gb', 0):.1f} GB free at {m.get('disk_path', '?')}")
    lines.append(f"Python   : {m.get('python', '?')}   uv: {m.get('uv') or 'not found'}")
    lines.append("")
    if b.get("supported"):
        mode = f" ({b['offload_mode']})" if b.get("offload_mode") else ""
        sd = b.get("sdcpp")
        if b.get("name") == "sdcpp" and sd:
            from medimg.sdcpp.pins import TIERS
            tier = sd.get("tier")
            quant = "?"
            try:
                quant = TIERS[tier]["diffusion"].filename.rsplit("-", 1)[-1].split(".")[0]
            except (KeyError, TypeError):
                pass
            lines.append(f"Supported: yes. Backend sdcpp on {b.get('device') or '?'} "
                         f"(tier {tier}: {quant} image model). {b.get('reason', '')}")
        else:
            lines.append(f"Supported: yes. Backend {b.get('name')}{mode}. {b.get('reason', '')}")
    else:
        lines.append(f"Supported: NO. {b.get('reason', '')}")
        if b.get("fix"):
            lines.append(f"Fix      : {b['fix']}")
    bench = profile.get("benchmark")
    if bench:
        lines.append(f"Benchmark: model load {bench.get('load_s', 0):.1f}s; "
                     + "; ".join(f"{p['width']}x{p['height']} @ {p['steps']} steps = {p['total_s']:.1f}s"
                                 for p in bench.get("points", [])))
    actuals = profile.get("actuals") or []
    if actuals:
        lines.append(f"Actual runs recorded: {len(actuals)} (the last 10 per size drive the estimates)")
    for n in profile.get("notes") or []:
        lines.append(f"Note     : {n}")
    lines.append("")
    rows = estimates_table(profile, DEFAULT_STEPS)
    if rows:
        lines.append(f"Estimated time at {DEFAULT_STEPS} steps")
        lines.append(f"{'Size':<22}{'1 image':>10}{'10 images':>12}{'25 images':>12}{'50 images':>12}")
        for r in rows:
            lines.append(f"{r['label']:<22}{fmt_duration(r['seconds']):>10}{fmt_duration(r['for_10']):>12}"
                         f"{fmt_duration(r['for_25']):>12}{fmt_duration(r['for_50']):>12}")
    elif b.get("supported"):
        lines.append("No time estimates yet: run the assessment without --no-benchmark, "
                     "or generate an image.")
    return "\n".join(lines) + "\n"
