"""Pinned stable-diffusion.cpp release assets and model files. Data only, no I/O."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from medimg.config import SDCPP_MODEL_ID, SDCPP_RELEASE_TAG, TOOLS_DIR

_BASE = f"https://github.com/leejet/stable-diffusion.cpp/releases/download/{SDCPP_RELEASE_TAG}/"


@dataclass(frozen=True)
class Asset:
    key: str
    name: str
    url: str
    size: int
    sha256: str
    exe: str


@dataclass(frozen=True)
class ModelFile:
    repo: str
    revision: str
    filename: str
    gb: float
    sha256: str


def _a(key: str, name: str, size: int, sha: str, exe: str) -> Asset:
    return Asset(key, name, _BASE + name, size, sha, exe)


ASSETS: dict[str, Asset] = {a.key: a for a in (
    _a("win-vulkan-x64", "sd-master-e41fbcf-bin-win-vulkan-x64.zip", 29_744_345,
       "259ceeb62f1069190d24c85ea1c4549d2d61deb0ef712510dbe98d79ce93a38b", "sd-cli.exe"),
    _a("win-cpu-x64", "sd-master-e41fbcf-bin-win-cpu-x64.zip", 18_080_790,
       "bfc02f16df7744296ecc7720503a2b633575490dd7d8b448aee035c1fc836bec", "sd-cli.exe"),
    _a("linux-vulkan-x64", "sd-master-e41fbcf-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip", 37_644_143,
       "0ae9ef34eea1ff6a229b892144a65ed8c00b6438c5ba783cdeca77024b2fc697", "sd-cli"),
    _a("linux-cpu-x64", "sd-master-e41fbcf-bin-Linux-Ubuntu-24.04-x86_64.zip", 27_320_021,
       "422bc495ca647d95e9bd88b04d3eaae52e641d89497ea0dda7335f44c46e9109", "sd-cli"),
    _a("mac-arm64", "sd-master-e41fbcf-bin-Darwin-macOS-26.6.2-arm64.zip", 37_584_335,
       "933fb5b622b578df7a0d22c41f39bc83791d40b876648a084fe1c4cbff2ef36c", "sd-cli"),
)}

_Z_REPO = SDCPP_MODEL_ID
_Z_REV = "c61c0e422dc8b541b7548cf33a4ef8302b0f8085"
_Q_REPO = "unsloth/Qwen3-4B-Instruct-2507-GGUF"
_Q_REV = "a06e946bb6b655725eafa393f4a9745d460374c9"
_V = ModelFile("Comfy-Org/z_image_turbo", "6fc90a3b1b653e935a0d175e260736de25b84df5",
               "split_files/vae/ae.safetensors", 0.335,
               "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38")
_Q3 = ModelFile(_Q_REPO, _Q_REV, "Qwen3-4B-Instruct-2507-Q3_K_M.gguf", 2.076,
                "9c6e0763577125a994a9bea0bbd7a737ac4498b8a6a4e0f788727553af1806c9")
_Q4 = ModelFile(_Q_REPO, _Q_REV, "Qwen3-4B-Instruct-2507-Q4_K_M.gguf", 2.497,
                "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597")

TIERS: dict[str, dict[str, ModelFile]] = {
    "low": {"diffusion": ModelFile(_Z_REPO, _Z_REV, "z_image_turbo-Q2_K.gguf", 2.592,
                                   "a9cf1b0368e24c2f9d542d2951c01f6f7fc85ed8c9ed39b5b37b15375508d58a"),
            "llm": _Q3, "vae": _V},
    "mid": {"diffusion": ModelFile(_Z_REPO, _Z_REV, "z_image_turbo-Q3_K.gguf", 3.144,
                                   "4b44bdaa7814f20d7cf144e3939bd93aa32f50660204dd0c2aea5c5376232980"),
            "llm": _Q3, "vae": _V},
    "high": {"diffusion": ModelFile(_Z_REPO, _Z_REV, "z_image_turbo-Q4_K.gguf", 3.864,
                                    "14b375ab4f226bc5378f68f37e899ef3c2242b8541e61e2bc1aff40976086fbd"),
             "llm": _Q4, "vae": _V},
}
TIER_GB: dict[str, float] = {"low": 5.0, "mid": 5.56, "high": 6.7}


def tier_for_ram(ram_total_gb: float) -> str:
    if ram_total_gb < 12:
        return "low"
    if ram_total_gb < 24:
        return "mid"
    return "high"


def build_for(os_name: str, arch: str, *, cpu_fallback: bool = False) -> str | None:
    a = (arch or "").strip().lower()
    if a in ("amd64", "x64", "x86_64"):
        a = "x86_64"
    elif a in ("aarch64", "arm64"):
        a = "arm64"
    if os_name == "Windows" and a == "x86_64":
        return "win-cpu-x64" if cpu_fallback else "win-vulkan-x64"
    if os_name == "Linux" and a == "x86_64":
        return "linux-cpu-x64" if cpu_fallback else "linux-vulkan-x64"
    if os_name == "Darwin" and a == "arm64":
        return "mac-arm64"
    return None


def binary_dir(build: str, tools_dir: Path = TOOLS_DIR) -> Path:
    return Path(tools_dir) / "sdcpp" / SDCPP_RELEASE_TAG / build
