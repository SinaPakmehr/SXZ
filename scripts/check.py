"""Build native code in a temporary directory and run dependency-light checks."""
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "lab/zip-protocol"


def run(*args, env=None):
    subprocess.run(args, cwd=CORE, env=env, check=True)


with TemporaryDirectory() as tmp:
    ext = ".dll" if os.name == "nt" else ".dylib" if sys.platform == "darwin" else ".so"
    lib = Path(tmp) / ("reference_scan" + ext)
    run("rustc", "--edition=2021", "--crate-type", "cdylib", "-O", "native/reference_scan.rs", "-o", str(lib))
    env = dict(os.environ, SINUXZ_SCAN_DLL=str(lib), PYTHONDONTWRITEBYTECODE="1")
    run(sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", env=env)
    run(sys.executable, "-B", "-m", "unittest", "experiments.sxz4.test_sxz4", env=env)
    run(sys.executable, "-B", str(ROOT / "examples/demo.py"), env=env)
