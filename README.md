# PyInstaller: faster bytecode scanning in modulegraph

This repo demonstrates and measures a speedup in PyInstaller's import analysis.

## The problem

> [!NOTE]
> This section describes PyInstaller as of pyinstaller/pyinstaller@78cf1b414587b7330bfd8ee253c79ae2c71b3472.

To find a module's imports, `ModuleGraph._scan_bytecode` uses `iterate_instructions`,
which yields `dis.Instruction` objects from `dis.get_instructions` for every code object of every module in the graph.

`dis.get_instructions` computes many things for each instruction, and on recent Python versions that is expensive:

* line numbers
* source positions
* jump targets and labels
* `argrepr`
* inline cache information

`_scan_bytecode` never reads any of them.
It only reads `opname` for every instruction, and `argval` for a handful of them (imports, assignments and deletions of global names, and the constants that precede imports).

## The fix

The proposed fix is in [this PR](https://github.com/pyinstaller/pyinstaller/pull/9575); everything below applies to revision `6cf31fb0ae935c7ad4413e896ca7dbc25d3d75fc`.

To measure the original, the benchmark replaces PyInstaller's `iterate_instructions` with [a copy of the original](original_implementation.py) in the build process.
Everything else is the same PyInstaller checkout.

### Reproducing

Requires [uv](https://docs.astral.sh/uv/) and a PyInstaller source checkout **with the fix** at `../pyinstaller/`:

```sh
VERSIONS_TO_TEST_WITH=(8 9 10 11 12 13 13t 14 14t 15 15t)

for version in "${VERSIONS_TO_TEST_WITH[@]}"; do
  echo
  echo "==== 💡 Python 3.$version ===="
  ./bench.py --python "3.$version" --pyinstaller ../pyinstaller/ --runs 5
  ./verify_equivalence.py --python "3.$version" --pyinstaller ../pyinstaller/
done
```

`--python` takes anything that `uv venv --python` accepts, e.g. `3.15` or `3.14t` (free-threaded).
uv downloads the interpreter if necessary.
Any version supported by the PyInstaller checkout should work.
On older Python versions, [`uv.lock`](uv.lock) has older versions of some dependencies, so the workload isn't exactly the same on all versions.
For very new Python versions, some dependencies might not have wheels yet and need to be built from source.

The scripts install the checkout in a separate venv for each Python version, e.g. `.venv-pyinstaller-python-3.14`, with the same locked dependencies as this project.
It's installed in editable mode, so edits in the checkout take effect immediately.
The venv is set up again when you pass another checkout or the locked dependencies change.
The scripts themselves only need the standard library, so the Python that runs them doesn't matter.

### Results

The [benchmark app](example_app/main.py) imports some popular Python packages, resulting in an import graph of 2000+ modules.
Each build is a fresh `pyinstaller --onedir` in a new process with a new work directory, after a warm-up build.

> [!NOTE]
> These numbers concern _entire_ builds. The speedup of `_scan_bytecode` in isolation ranges from ~2× to ~3.5× depending on Python version.

| Python | Original | Fast | Speedup |
|---|---|---|---|
| 3.8.20 | 18.18 s | 16.50 s | 1.10× |
| 3.9.25 | 16.50 s | 15.08 s | 1.09× |
| 3.10.21 | 17.03 s | 15.40 s | 1.11× |
| 3.11.16 | 19.70 s | 15.27 s | 1.29× |
| 3.12.3 | 21.42 s | 16.77 s | 1.28× |
| 3.13.15 | 21.11 s | 14.79 s | 1.43× |
| 3.13.15t | N/A[^1] | N/A[^1] | N/A[^1] |
| 3.14.7 | 24.64 s | 16.25 s | 1.52× |
| 3.14.7t | 27.14 s | 18.04 s | 1.50× |
| 3.15.0rc2 | 23.90 s | 15.54 s | 1.54× |
| 3.15.0rc2t | 25.52 s | 17.30 s | 1.48× |

[^1]: On Python 3.13.15t (free-threaded), setting up the venv (`uv pip install --quiet --python …`) consistently failed with "Failed to build `greenlet==3.5.6`" due to "No such file or directory: 'c++'".

Measured on x86_64 Linux with 16 CPUs (PyInstaller's analysis is essentially single-threaded), median of 5 runs.

**All builds that succeeded produced byte-for-byte identical output** (`bench.py` checks this).

### Correctness

[`verify_equivalence.py`](verify_equivalence.py) compares PyInstaller's `iterate_instructions` with [a copy of the original implementation](original_implementation.py).
It compiles every `.py` file in the standard library and site-packages, and runs two checks on each:

  * **Behavior:** PyInstaller's actual `_scan_bytecode` is run with each implementation, and everything it does is recorded: the imports it defers, the global attributes it adds and removes, and any exception it raises. The recordings must be identical.
  * **Instructions:** both implementations must yield the same `opname` and `argval` for every instruction, and `None` end-of-block markers in the same places. This catches divergences that don't affect the result for any file on the current Python version, but could on others, or if PyInstaller starts reading other `argval`s.

It also checks that `_scan_bytecode` is the only user of `iterate_instructions` in PyInstaller.
The times are for `_scan_bytecode` on all files with each implementation.
