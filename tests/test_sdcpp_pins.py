import pytest

from medimg import config
from medimg.sdcpp import pins

EXPECT = {
    "win-vulkan-x64": ("sd-master-e41fbcf-bin-win-vulkan-x64.zip", 29744345, "sd-cli.exe"),
    "win-cpu-x64": ("sd-master-e41fbcf-bin-win-cpu-x64.zip", 18080790, "sd-cli.exe"),
    "linux-vulkan-x64": ("sd-master-e41fbcf-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip", 37644143, "sd-cli"),
    "linux-cpu-x64": ("sd-master-e41fbcf-bin-Linux-Ubuntu-24.04-x86_64.zip", 27320021, "sd-cli"),
    "mac-arm64": ("sd-master-e41fbcf-bin-Darwin-macOS-26.6.2-arm64.zip", 37584335, "sd-cli"),
}


def test_assets():
    assert set(pins.ASSETS) == set(EXPECT)
    for k, (name, size, exe) in EXPECT.items():
        a = pins.ASSETS[k]
        assert (a.key, a.name, a.size, a.exe) == (k, name, size, exe)
        assert a.url == f"https://github.com/leejet/stable-diffusion.cpp/releases/download/{config.SDCPP_RELEASE_TAG}/{name}"
        assert len(a.sha256) == 64
    assert pins.ASSETS["win-vulkan-x64"].sha256 == "259ceeb62f1069190d24c85ea1c4549d2d61deb0ef712510dbe98d79ce93a38b"


def test_tiers():
    files = {"low": ("z_image_turbo-Q2_K.gguf", "Qwen3-4B-Instruct-2507-Q3_K_M.gguf"),
             "mid": ("z_image_turbo-Q3_K.gguf", "Qwen3-4B-Instruct-2507-Q3_K_M.gguf"),
             "high": ("z_image_turbo-Q4_K.gguf", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf")}
    assert set(pins.TIERS) == set(files)
    for t, (d, l) in files.items():
        tier = pins.TIERS[t]
        assert set(tier) == {"diffusion", "llm", "vae"}
        assert tier["diffusion"].filename == d and tier["llm"].filename == l
        assert tier["vae"].filename == "split_files/vae/ae.safetensors"
        assert tier["diffusion"].repo == "leejet/Z-Image-Turbo-GGUF"
        assert tier["diffusion"].revision == "c61c0e422dc8b541b7548cf33a4ef8302b0f8085"
        assert tier["llm"].revision == "a06e946bb6b655725eafa393f4a9745d460374c9"
        assert tier["vae"].sha256.startswith("afc8e282")
        assert abs(sum(m.gb for m in tier.values()) - pins.TIER_GB[t]) < 0.01
    assert pins.TIERS["low"]["diffusion"].sha256.startswith("a9cf1b03")


@pytest.mark.parametrize("gb,tier", [(7.7, "low"), (11.9, "low"), (12, "mid"), (16, "mid"), (24, "high"), (32, "high")])
def test_tier_for_ram(gb, tier):
    assert pins.tier_for_ram(gb) == tier


@pytest.mark.parametrize("os_name,arch,fb,expected", [
    ("Windows", "AMD64", False, "win-vulkan-x64"),
    ("Windows", "x86_64", True, "win-cpu-x64"),
    ("Linux", "x86_64", False, "linux-vulkan-x64"),
    ("Linux", "x64", True, "linux-cpu-x64"),
    ("Darwin", "arm64", False, "mac-arm64"),
    ("Darwin", "aarch64", True, "mac-arm64"),
    ("Darwin", "x86_64", False, None),
    ("Linux", "arm64", False, None),
    ("Windows", "ARM64", False, None),
    ("FreeBSD", "x86_64", False, None),
])
def test_build_for(os_name, arch, fb, expected):
    assert pins.build_for(os_name, arch, cpu_fallback=fb) == expected


def test_binary_dir(tmp_path):
    assert pins.binary_dir("mac-arm64", tmp_path) == tmp_path / "sdcpp" / config.SDCPP_RELEASE_TAG / "mac-arm64"
