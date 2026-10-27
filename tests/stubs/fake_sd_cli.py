"""Fake sd-cli for tests and CI. STDLIB ONLY (runs under `python -I`).

Env switches: FAKE_SD_CLI_STEP_S (sleep per step, default 0.02), FAKE_SD_CLI_FAIL
(gpu_oom | ram_oom | no_model), FAKE_SD_CLI_HANG=1, FAKE_SD_CLI_BAD_FLAGS=1,
FAKE_SD_CLI_COUNT_FILE (append one line per invocation).
"""
import os
import struct
import sys
import time
import zlib

VALUE_FLAGS = {"--diffusion-model", "--llm", "--vae", "-p", "--cfg-scale", "--steps", "-W", "-H",
               "-s", "-o", "--backend", "--log-level", "--threads"}
BOOL_FLAGS = {"--offload-to-cpu", "--mmap", "--vae-tiling"}

GPU_OOM_LINES = [
    "[I] loading tensors completed, taking 2.88s --- model_loader.cpp:1405",
    "ggml_vulkan: Device memory allocation of size 1067397120 failed.",
    "ggml_vulkan: vk::Device::allocateMemory: ErrorOutOfDeviceMemory",
    "[E] ggml: ggml_backend_buft_alloc_buffer_n_default: failed to allocate Vulkan0 buffer of size 1067397120",
    "[E] model manager alloc compute params backend buffer failed, num_tensors = 121 --- model_manager.cpp:571",
    "[E] LLM prompt encoding failed --- conditioner.hpp:2311",
    "[E] failed to encode prompt --- image.cpp:499",
    "[E] generate failed --- main.cpp:926",
]
RAM_OOM_LINES = ["terminate called after throwing an instance of 'std::bad_alloc'",
                 "[E] generate failed --- main.cpp:926"]
NO_MODEL_LINES = ["[W] loading diffusion model from '/nonexistent.gguf' failed --- model_builders.cpp:412",
                  "[I] new_sd_ctx_t failed --- main.cpp:743"]


def out(text):
    sys.stdout.write(text)
    sys.stdout.flush()


def write_png(path, w, h, seed):
    r, g, b = (seed * 53) % 256, (seed * 97 + 80) % 256, (seed * 191 + 40) % 256
    row = b"\x00" + bytes((r, g, b)) * w
    raw = row * h

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, "wb") as f:
        f.write(png)


def bar(k, n, width=20):
    fill = int(width * k / n)
    body = "=" * max(fill - 1, 0) + (">" if fill else "") + " " * (width - fill)
    return "  |%s| %d/%d - %7.2fs/it - ETA 00:%02d\x1b[K" % (body, k, n, 0.5, n - k)


def usage(msg):
    out("[E] %s\nusage: sd-cli [options]\n" % msg)
    sys.exit(1)


def parse(argv):
    opts = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in VALUE_FLAGS:
            if i + 1 >= len(argv):
                usage("missing value for %s" % a)
            opts[a] = argv[i + 1]
            i += 2
        elif a in BOOL_FLAGS:
            opts[a] = True
            i += 1
        else:
            usage("unknown argument: %s" % a)
    return opts


def main():
    argv = sys.argv[1:]
    cf = os.environ.get("FAKE_SD_CLI_COUNT_FILE")
    if cf:
        with open(cf, "a") as f:
            f.write("invoked\n")
    if argv == ["--version"] or "--version" in argv:
        out("stable-diffusion.cpp version unknown, commit e41fbcf\n")
        return 0
    if "--list-devices" in argv:
        out("Vulkan0\tFake GPU\nCPU\tFake CPU\n")
        return 0
    o = parse(argv)
    for req in ("--diffusion-model", "--llm", "--vae", "-p", "-o"):
        if req not in o:
            usage("missing %s" % req)
    if os.environ.get("FAKE_SD_CLI_BAD_FLAGS") == "1":
        if o.get("--log-level") != "info" or o.get("--cfg-scale") != "1.0":
            usage("regression guard: --log-level info and --cfg-scale 1.0 required")
    try:
        steps = int(o.get("--steps", "8"))
        w, h, seed = int(o.get("-W", "512")), int(o.get("-H", "512")), int(o.get("-s", "42"))
    except ValueError:
        usage("bad number")
    fail = os.environ.get("FAKE_SD_CLI_FAIL", "")
    backend = o.get("--backend", "cpu")
    lines = None
    if fail == "gpu_oom" and backend.lower() != "cpu":
        lines = GPU_OOM_LINES
    elif fail == "no_device" and backend.lower() != "cpu":
        lines = ["[E] unknown backend: " + backend]
    elif fail == "ram_oom":
        lines = RAM_OOM_LINES
    elif fail == "no_model":
        lines = NO_MODEL_LINES
    if lines:
        out("\n".join(lines) + "\n")
        return 1
    step_s = float(os.environ.get("FAKE_SD_CLI_STEP_S", "0.02"))
    hang = os.environ.get("FAKE_SD_CLI_HANG") == "1"
    out("[I] get_learned_condition completed, taking 0.01s --- conditioner.hpp:1\n")
    out("[I] generating image: 1/1 - seed %d --- main.cpp:1\n" % seed)
    for k in range(1, steps + 1):
        time.sleep(step_s)
        out("\r" + bar(k, steps) + ("\n" if k == steps else ""))
        if hang and k == 1:
            out("\r")  # lets a line-based reader see the finished bar before the hang
            time.sleep(600)
    out("[I] sampling completed, taking %.2fs --- stable-diffusion.cpp:1\n" % (steps * step_s))
    out("[I] decoding 1 latents --- stable-diffusion.cpp:2\n")
    for k in range(1, 4):
        out("\r" + bar(k, 3) + ("\n" if k == 3 else ""))
    out("[I] latent 1 decoded, taking 0.01s --- stable-diffusion.cpp:3\n")
    out("[I] generate_image completed in %.2fs --- stable-diffusion.cpp:4\n" % (steps * step_s))
    write_png(o["-o"], w, h, seed)
    out("[I] save result image 0 to '%s' (success) --- main.cpp:5\n" % o["-o"])
    out("[I] 1/1 images saved --- main.cpp:6\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
