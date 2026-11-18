#!/usr/bin/env python3
"""Check that PyInstaller's fast bytecode scanning is equivalent to the original, and time both.

Runs with the given Python version and the PyInstaller from a source checkout (see `pyinstaller_checkout.py`).
Its `iterate_instructions` is compared with the original implementation, a copy of which is in
`original_implementation.py`.

Compiles every `.py` file in the standard library and in site-packages (or in the directories given as arguments) and
runs two checks on each:

  1. Behavior: PyInstaller's actual `ModuleGraph._scan_bytecode` is run with each implementation, and everything it
     does is recorded: the imports it defers, the global attributes it adds and removes, and any exception it raises
     (e.g. a failed assertion about which opcode pushed the `fromlist` of an import).
     The two recordings must be identical.

  2. Instructions: both implementations must yield the same `opname` and `argval` for every instruction, and the `None`
     end-of-block markers in the same places.
     This catches divergences that don't affect the result for any of the files on this Python version, but could on
     other files or versions, or if PyInstaller starts reading other instructions' `argval`.

It also checks that the checkout actually has the fast implementation, and that `_scan_bytecode` is the only user of
`iterate_instructions` in PyInstaller.

The time reported is that of `_scan_bytecode` with each implementation, i.e. including reading `argval` where it does.

Usage: ./verify_equivalence.py --python VERSION --pyinstaller CHECKOUT [DIR ...]
"""

import argparse
import dis
import sys
import sysconfig
import time
import warnings
from pathlib import Path

import pyinstaller_checkout


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    pyinstaller_checkout.add_arguments(parser)
    parser.add_argument("dirs", nargs="*", type=Path, metavar="DIR")
    return parser.parse_args()


# Before PyInstaller is imported, rerun this script in the venv with the checkout.
ARGS = parse_args()
pyinstaller_checkout.run_in_venv(ARGS)

import PyInstaller  # noqa: E402
from PyInstaller.lib.modulegraph import util  # noqa: E402
from PyInstaller.lib.modulegraph.modulegraph import ModuleGraph  # noqa: E402

import original_implementation  # noqa: E402


IMPLEMENTATIONS = {"original": original_implementation.iterate_instructions, "fast": util.iterate_instructions}


def check_fast_implementation_used():
    """Return a description of why PyInstaller doesn't use the fast implementation, or `None` if it does."""
    first = next(util.iterate_instructions(compile("import os", "<check>", "exec")))
    if isinstance(first, dis.Instruction):
        return "it yields `dis.Instruction`s, like the original (does the checkout have the fix?)"
    return None


def check_only_caller():
    """Make sure that `_scan_bytecode` is the only user of `iterate_instructions`, so that checking it suffices."""
    package = Path(PyInstaller.__file__).parent
    users = {
        path.relative_to(package).as_posix(): path.read_text(encoding="utf-8").count("iterate_instructions(")
        for path in package.rglob("*.py")
        if "iterate_instructions" in path.read_text(encoding="utf-8")
    }
    del users["lib/modulegraph/util.py"]  # Where it's defined.
    if users != {"lib/modulegraph/modulegraph.py": 1}:  # The call in `_scan_bytecode`.
        sys.exit(f"❌ Unexpected uses of `iterate_instructions` in PyInstaller: {users}; this check may be insufficient.")


class RecordingModule:
    """Stands in for the module node that `_scan_bytecode` reports its findings to."""

    def __init__(self):
        self.events = []
        self._deferred_imports = self  # So that `module._deferred_imports.append(...)` calls `self.append`.

    def append(self, deferred_import):
        have_star, (target, module, fromlist, level), kwargs = deferred_import
        assert module is self
        self.events.append(("import", target, fromlist, level, have_star, kwargs))

    def add_global_attr(self, name):
        self.events.append(("add_global_attr", name))

    def remove_global_attr_if_found(self, name):
        self.events.append(("remove_global_attr_if_found", name))


def scan(implementation, code):
    """Run `_scan_bytecode` with the given `iterate_instructions` and return what it did."""
    module = RecordingModule()
    original = util.iterate_instructions
    util.iterate_instructions = implementation
    try:
        ModuleGraph._scan_bytecode(None, module, code, is_scanning_imports=True)
    except Exception as e:
        module.events.append(("raised", type(e).__name__, str(e)))
    finally:
        util.iterate_instructions = original
    return module.events


def instruction_stream(implementation, code):
    return [None if i is None else (i.opname, i.argval) for i in implementation(code)]


def first_difference(a, b):
    return next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))


def report(label, path, original, fast, count):
    if count <= 5:
        k = first_difference(original, fast)
        print(f"{label} MISMATCH in {path} at item {k}:")
        print(f"  original: {original[k:k + 3]}")
        print(f"  fast:     {fast[k:k + 3]}")


def main():
    check_only_caller()
    not_fast = check_fast_implementation_used()
    print(f"PyInstaller {PyInstaller.__version__} from {Path(PyInstaller.__file__).parent.parent}")

    dirs = ARGS.dirs or sorted(
        {Path(sysconfig.get_path(key)) for key in ("stdlib", "purelib", "platlib")}
    )
    files = sorted({path for d in dirs for path in d.rglob("*.py")})
    print(f"Python {sys.version.split()[0]}, {len(files)} .py files in: {', '.join(map(str, dirs))}")

    code_objects = []
    for path in files:
        try:
            source = path.read_bytes()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                code_objects.append((path, compile(source, str(path), "exec", dont_inherit=True)))
        except (SyntaxError, ValueError):
            pass  # E.g. test files with deliberate syntax errors, or code for other Python versions.
    print(f"Compiled {len(code_objects)} of them.")

    timings = {}
    for name, implementation in IMPLEMENTATIONS.items():
        start = time.perf_counter()
        for _, code in code_objects:
            scan(implementation, code)
        timings[name] = time.perf_counter() - start

    behavior_mismatches = instruction_mismatches = instructions = events = 0
    for path, code in code_objects:
        original, fast = (scan(implementation, code) for implementation in IMPLEMENTATIONS.values())
        events += len(original)
        if original != fast:
            behavior_mismatches += 1
            report("Behavior", path, original, fast, behavior_mismatches)

        original, fast = (instruction_stream(i, code) for i in IMPLEMENTATIONS.values())
        instructions += len(original)
        if original != fast:
            instruction_mismatches += 1
            report("Instruction", path, original, fast, instruction_mismatches)

    print(
        f"Time for `_scan_bytecode` on all files ({instructions} instructions): original {timings['original']:.2f} s, "
        f"fast {timings['fast']:.2f} s ({timings['original'] / timings['fast']:.1f}× faster)."
    )
    n = len(code_objects)
    if not_fast:
        print(f"❌ PyInstaller doesn't use the fast implementation: {not_fast}.")
    else:
        print("✅ PyInstaller uses the fast implementation.")
    print(
        f"{'❌' if behavior_mismatches else '✅'} Behavior of `_scan_bytecode`: "
        f"{f'differs for {behavior_mismatches} of {n} files' if behavior_mismatches else f'identical for all {n} files'}"
        f" ({events} recorded events)."
    )
    print(
        f"{'❌' if instruction_mismatches else '✅'} Instruction streams: "
        f"{f'differ for {instruction_mismatches} of {n} files' if instruction_mismatches else f'identical for all {n} files'}."
    )
    if behavior_mismatches or instruction_mismatches or not_fast:
        sys.exit(1)


if __name__ == "__main__":
    main()
