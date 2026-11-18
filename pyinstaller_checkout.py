"""Set up and use a venv with a given Python version and PyInstaller installed from a source checkout.

The venv has the same locked dependencies as this project, except that PyInstaller is installed in editable mode from
the checkout, so edits there take effect immediately. There is one venv per Python version.
"""

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Set in the venv's process when it has been set up by `run_in_venv`, to avoid setting it up again.
_IN_VENV = "BENCHMARK_PYINSTALLER_CHECKOUT_VENV"


def add_arguments(parser):
    parser.add_argument(
        "--python",
        required=True,
        metavar="VERSION",
        help="Python version to use, e.g. 3.14 or 3.14t; anything that `uv venv --python` accepts",
    )
    parser.add_argument(
        "--pyinstaller",
        type=Path,
        required=True,
        metavar="CHECKOUT",
        help="PyInstaller source checkout to use, e.g. ../pyinstaller",
    )


def venv_python(args):
    """Set up the venv for the arguments added by `add_arguments` (if necessary) and return its Python."""
    checkout = args.pyinstaller.resolve()
    if not (checkout / "PyInstaller" / "__init__.py").is_file():
        sys.exit(f"{checkout} is not a PyInstaller source checkout.")

    venv = HERE / f".venv-pyinstaller-python-{re.sub(r'[^A-Za-z0-9.+-]', '_', args.python)}"
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    # Reinstall when the checkout or the locked dependencies change. Edits in the checkout don't need a reinstall.
    marker = venv / "benchmark-installed-from"
    state = f"{checkout}\n{hashlib.sha256((HERE / 'uv.lock').read_bytes()).hexdigest()}\n"
    if not python.exists() or not marker.exists() or marker.read_text() != state:
        print(f"Setting up {venv.name} with PyInstaller from {checkout} …", file=sys.stderr)
        subprocess.run(["uv", "venv", "--quiet", "--allow-existing", "--python", args.python, str(venv)], check=True)
        with tempfile.TemporaryDirectory() as tmp:
            requirements = Path(tmp) / "requirements.txt"
            subprocess.run(
                ["uv", "export", "--frozen", "--quiet", "--no-hashes", "--no-emit-package", "pyinstaller",
                 "--output-file", str(requirements)],
                cwd=HERE, check=True,
            )  # fmt: skip
            subprocess.run(
                ["uv", "pip", "install", "--quiet", "--python", str(python), "--requirements", str(requirements),
                 "--editable", str(checkout)],
                check=True,
            )  # fmt: skip
        marker.write_text(state)
    return python


def run_in_venv(args):
    """Rerun the current script with the venv's Python, unless that's what is running. Returns if it is."""
    if os.environ.get(_IN_VENV):
        return
    python = venv_python(args)
    sys.exit(subprocess.run([str(python), *sys.argv], env={**os.environ, _IN_VENV: "1"}).returncode)
