"""Run a single PyInstaller build of `example_app/main.py`.

Usage: python build.py {original,fast} OUTDIR

  original    with PyInstaller's `iterate_instructions` replaced by the original implementation (see
              `original_implementation.py`)
  fast        with PyInstaller's own `iterate_instructions`, which must be the fast one

The output goes to OUTDIR/dist; PyInstaller's work files go to OUTDIR/build.
"""

import argparse
import dis
import sys
from pathlib import Path

import PyInstaller.__main__
from PyInstaller.lib.modulegraph import util

import original_implementation

HERE = Path(__file__).resolve().parent


def use_original_implementation():
    """Replace PyInstaller's `iterate_instructions` with the original. Returns a function that counts its calls."""
    calls = 0

    def iterate_instructions(code_object):
        nonlocal calls
        calls += 1
        return original_implementation.iterate_instructions(code_object)

    util.iterate_instructions = iterate_instructions  # `modulegraph` calls it as `util.iterate_instructions`.
    return lambda: calls


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("implementation", choices=["original", "fast"])
    parser.add_argument("outdir", type=Path)
    args = parser.parse_args()

    if args.implementation == "original":
        count_calls = use_original_implementation()
    elif isinstance(next(util.iterate_instructions(compile("pass", "<check>", "exec"))), dis.Instruction):
        sys.exit("PyInstaller's `iterate_instructions` yields `dis.Instruction`s, so it isn't the fast implementation.")

    pyinstaller_args = [
        str(HERE / "example_app" / "main.py"),
        "--name", "example_app",
        "--onedir",
        "--noconfirm",
        "--log-level", "WARN",
        "--distpath", str(args.outdir / "dist"),
        "--workpath", str(args.outdir / "build"),
        "--specpath", str(args.outdir),
    ]  # fmt: skip

    PyInstaller.__main__.run(pyinstaller_args)

    if args.implementation == "original" and count_calls() == 0:
        sys.exit("The original `iterate_instructions` was never called, so the build didn't use it.")


if __name__ == "__main__":
    main()
