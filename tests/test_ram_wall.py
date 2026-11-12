"""Tests for skills/ollama-tuning/scripts/ollama_ram_wall.py against a fake cgroup folder. Run: python tests/test_ram_wall.py"""

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ram_wall", ROOT / "skills" / "ollama-tuning" / "scripts" / "ollama_ram_wall.py")
wall = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wall)

MB = 1024 * 1024
ENV = "OLLAMA_HOST=0.0.0.0 LLAMA_ARG_CACHE_RAM=1536 LLAMA_ARG_CTX_CHECKPOINTS=8"


def fake(limit="22548578304", swap="0", anon=17000, killed=0):
    d = tempfile.mkdtemp(prefix="ram_wall_test_")
    files = {
        "memory.max": limit,
        "memory.swap.max": swap,
        "memory.current": str((anon + 400) * MB),
        "memory.peak": str((anon + 900) * MB),
        "memory.stat": f"anon {anon * MB}\nfile {400 * MB}\nshmem 0\n",
        "memory.events": f"low 0\nhigh 0\nmax {killed}\noom {killed}\noom_kill {killed}\n",
    }
    for name, text in files.items():
        with open(os.path.join(d, name), "w") as f:
            f.write(text + "\n")
    meminfo = os.path.join(d, "meminfo")
    with open(meminfo, "w") as f:
        f.write("MemTotal:       31935488 kB\nMemAvailable:   12000000 kB\n")
    return d, meminfo


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = wall.main(list(argv))
    return code, out.getvalue()


def test_reads_the_wall():
    d, meminfo = fake()
    w = wall.read_wall(d, ENV)
    assert w["wall"] == 21504 and w["swap_off"] and w["held"] == 17000 and w["file"] == 400
    assert w["cache"] == 1536 and w["checkpoints"] == 8 and w["killed"] == 0
    # Unset variables mean the llama.cpp defaults, which are large.
    w = wall.read_wall(d, "OLLAMA_HOST=0.0.0.0")
    assert w["cache"] == 8192 and w["checkpoints"] == 32


def test_status_says_when_the_wall_holds():
    d, meminfo = fake()
    code, text = run("--cgroup", d, "--meminfo", meminfo, "--env", ENV, "--model-mb", "17500")
    assert code == 0 and "the wall holds" in text, text
    assert "9683 MB always stay" in text
    # 17500 + 1536 + 8 x 64 + 768 = 20316
    assert "20316 MB" in text


def test_status_flags_an_appetite_larger_than_the_wall():
    d, meminfo = fake()
    code, text = run("--cgroup", d, "--meminfo", meminfo, "--env", "X=1", "--model-mb", "17500")
    assert code == 1 and "NOT SAFE" in text, text


def test_status_flags_missing_wall_swap_and_kills():
    d, meminfo = fake(limit="max")
    code, text = run("--cgroup", d, "--meminfo", meminfo, "--env", ENV)
    assert code == 1 and "NOT SET" in text
    d, meminfo = fake(swap="max")
    code, text = run("--cgroup", d, "--meminfo", meminfo, "--env", ENV)
    assert code == 1 and "ALLOWED" in text
    d, meminfo = fake(killed=2)
    code, text = run("--cgroup", d, "--meminfo", meminfo, "--env", ENV)
    assert code == 1 and "killed at it: 2" in text


def test_plan_fits_the_caches_behind_the_wall():
    settings, problem = wall.plan(31187, 9000, 17500, 8, 64, 768)
    assert not problem and settings["wall"] == 22187
    need = wall.worst_case(17500, settings["cache"], settings["checkpoints"], 64, 768)
    assert need <= settings["wall"]
    assert settings["cache"] == 22187 - 17500 - 512 - 768
    text = wall.drop_in(settings)
    assert "MemoryMax=22187M" in text and "MemorySwapMax=0" in text and "LLAMA_ARG_CACHE_RAM=3407" in text
    # A tighter wall shrinks the prompt cache first, then the checkpoints.
    settings, problem = wall.plan(31187, 12500, 17500, 8, 64, 768)
    assert not problem and settings["cache"] < 100 and settings["checkpoints"] < 8
    assert wall.worst_case(17500, settings["cache"], settings["checkpoints"], 64, 768) <= settings["wall"]


def test_plan_refuses_a_wall_the_model_cannot_fit_behind():
    settings, problem = wall.plan(31187, 16000, 17500, 8, 64, 768)
    assert settings is None and "more than a wall" in problem
    code, text = run("--plan", "--keep-free-mb", "16000", "--model-mb", "17500", "--meminfo", fake()[1])
    assert code == 1
    code, text = run("--plan", "--meminfo", fake()[1])
    assert code == 2


def test_never_unloads_or_kills():
    source = (ROOT / "skills" / "ollama-tuning" / "scripts" / "ollama_ram_wall.py").read_text()
    assert "keep_alive" not in source and "kill" not in source.replace("killed", "").replace("oom_kill", "").lower().replace("never kills", "")


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"FAIL  {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
