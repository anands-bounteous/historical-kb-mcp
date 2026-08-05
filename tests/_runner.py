"""Minimal offline test runner — use pytest when available."""
import importlib.util
import inspect
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT.parent / "src"
sys.path.insert(0, str(SRC))


def run_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tests = [(n, f) for n, f in vars(mod).items()
             if n.startswith("test_") and callable(f) and inspect.isfunction(f)]
    passed = failed = 0
    for name, func in tests:
        tmp_path = Path(tempfile.mkdtemp(prefix="hkb_"))
        env_snapshot = dict(os.environ)
        try:
            sig = inspect.signature(func)
            kwargs = {}
            if "tmp_path" in sig.parameters:
                kwargs["tmp_path"] = tmp_path
            func(**kwargs)
            print(f"  PASS {path.stem}::{name}")
            passed += 1
        except Exception:
            print(f"  FAIL {path.stem}::{name}")
            traceback.print_exc()
            failed += 1
        finally:
            os.environ.clear()
            os.environ.update(env_snapshot)
            shutil.rmtree(tmp_path, ignore_errors=True)
            # Reset singletons between tests
            try:
                import historical_kb_mcp.tools as t
                t._engine = None
            except Exception:
                pass
            try:
                import historical_kb_mcp.config as c
                c._config = None
            except Exception:
                pass
    return passed, failed


def main():
    total_p = total_f = 0
    for path in sorted(ROOT.glob("test_*.py")):
        print(f"\n{path.name}")
        p, f = run_module(path)
        total_p += p
        total_f += f
    print(f"\n{'='*50}\nTOTAL: {total_p} passed, {total_f} failed")
    sys.exit(1 if total_f else 0)


if __name__ == "__main__":
    main()
