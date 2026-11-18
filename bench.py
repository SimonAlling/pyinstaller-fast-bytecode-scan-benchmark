#!/usr/bin/env python3
"""Benchmark PyInstaller builds of `example_app/main.py` with and without the fast bytecode scanning.

Usage: ./bench.py --python VERSION --pyinstaller CHECKOUT --runs N

Both variants use Python VERSION and the PyInstaller from CHECKOUT (see `pyinstaller_checkout.py`):

  original    with `iterate_instructions` replaced by the original implementation (see `original_implementation.py`)
  fast        with the checkout's own `iterate_instructions`, which must be the fast one

It checks that both produce identical output.

Each build runs in a fresh process with a fresh work directory. After one discarded warm-up build per variant (so that
`.pyc` files and PyInstaller's caches exist), the variants are run in rotating order to spread out noise.
"""

import argparse
import hashlib
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import pyinstaller_checkout

HERE = Path(__file__).resolve().parent


@dataclass
class Variant:
    name: str  # Passed to `build.py`.
    times: list[float] = field(default_factory=list)
    output_hashes: set[str] = field(default_factory=set)


def hash_tree(root):
    """A hash of the paths and contents of all files under `root`."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def count_modules(build_dir):
    toc = build_dir / "build" / "example_app" / "PYZ-00.toc"
    return toc.read_text(encoding="utf-8").count("'PYMODULE'") if toc.exists() else None


def build(python, variant, env):
    """Run one build. Returns (seconds, output hash, number of modules in the PYZ)."""
    with tempfile.TemporaryDirectory(prefix="pyinstaller-bench-") as tmp:
        outdir = Path(tmp)
        command = [str(python), str(HERE / "build.py"), variant.name, str(outdir)]
        start = time.perf_counter()
        result = subprocess.run(command, cwd=HERE, env=env, capture_output=True, text=True)
        seconds = time.perf_counter() - start
        if result.returncode != 0:
            sys.exit(f"Build with variant {variant.name!r} failed:\n{result.stdout}{result.stderr}")
        return seconds, hash_tree(outdir / "dist"), count_modules(outdir)


def describe_python(python):
    code = "import platform, PyInstaller as p; print(platform.python_version(), p.__version__, p.__path__[0])"
    python_version, pyinstaller_version, path = subprocess.check_output([python, "-c", code], text=True).split(" ", 2)
    return f"Python {python_version}, PyInstaller {pyinstaller_version} from {Path(path.strip()).parent}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, required=True, help="timed builds per variant")
    pyinstaller_checkout.add_arguments(parser)
    args = parser.parse_args()
    python = pyinstaller_checkout.venv_python(args)

    # Make the output deterministic, so that the outputs of different variants can be compared.
    env = {**os.environ, "PYTHONHASHSEED": "0", "SOURCE_DATE_EPOCH": "1700000000"}
    variants = [Variant("original"), Variant("fast")]

    print(f"Machine: {platform.machine()}, {os.cpu_count()} CPUs, {platform.system()} {platform.release()}")
    print(describe_python(python))

    print("\nWarm-up builds …")
    for variant in variants:
        _, output_hash, modules = build(python, variant, env)
        variant.output_hashes.add(output_hash)
        print(f"  {variant.name}: {modules} modules in the PYZ")

    for run in range(args.runs):
        print(f"Run {run + 1}/{args.runs}:", end="", flush=True)
        for i in range(len(variants)):
            variant = variants[(run + i) % len(variants)]
            seconds, output_hash, _ = build(python, variant, env)
            variant.times.append(seconds)
            variant.output_hashes.add(output_hash)
            print(f"  {variant.name} {seconds:.2f} s", end="", flush=True)
        print()

    baseline = statistics.median(variants[0].times)
    width = max(len(v.name) for v in variants)
    print(f"\n{'variant':<{width}}  median     min     max  speedup")
    for variant in variants:
        median = statistics.median(variant.times)
        print(
            f"{variant.name:<{width}}  {median:5.2f} s  {min(variant.times):5.2f} s  {max(variant.times):5.2f} s"
            f"  {baseline / median:6.2f}×"
        )

    all_hashes = set().union(*(v.output_hashes for v in variants))
    if len(all_hashes) == 1:
        print(f"\n✅ All {sum(len(v.times) + 1 for v in variants)} builds produced identical output.")
    else:
        print("\n❌ The builds did not all produce identical output:")
        for variant in variants:
            print(f"  {variant.name}: {', '.join(sorted(h[:12] for h in variant.output_hashes))}")
        sys.exit(1)


if __name__ == "__main__":
    main()
