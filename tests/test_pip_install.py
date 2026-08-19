"""Install the built wheel in a clean venv and verify bundled runtime assets."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _expected_version() -> str:
    version_file = ROOT / "abi" / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    for line in (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("could not resolve expected version")


class PipInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls._tmp.name)
        cls.wheel_dir = cls.work / "wheels"
        cls.venv_dir = cls.work / "venv"
        cls.wheel_dir.mkdir()

        build = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-w", str(cls.wheel_dir)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if build.returncode != 0:
            raise unittest.SkipTest(f"pip wheel failed: {build.stderr.strip() or build.stdout.strip()}")

        wheels = sorted(cls.wheel_dir.glob("agents_memory-*.whl"))
        if not wheels:
            raise unittest.SkipTest("wheel build produced no agents_memory artifact")
        cls.wheel = wheels[-1]

        create = subprocess.run(
            [sys.executable, "-m", "venv", str(cls.venv_dir)],
            capture_output=True,
            text=True,
        )
        if create.returncode != 0:
            raise unittest.SkipTest(f"venv creation failed: {create.stderr.strip()}")

        pip_exe = cls._venv_executable("pip")
        install = subprocess.run(
            [str(pip_exe), "install", str(cls.wheel)],
            capture_output=True,
            text=True,
        )
        if install.returncode != 0:
            raise unittest.SkipTest(f"wheel install failed: {install.stderr.strip()}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    @classmethod
    def _venv_executable(cls, name: str) -> Path:
        scripts = cls.venv_dir / ("Scripts" if os.name == "nt" else "bin")
        suffix = ".exe" if os.name == "nt" else ""
        return scripts / f"{name}{suffix}"

    def _run_installed_python(self, code: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self._venv_executable("python")), "-c", code],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_bundled_paths_and_version(self) -> None:
        expected = _expected_version()
        proc = self._run_installed_python(
            "import agents_memory\n"
            "from agents_memory.store import ABI_DIR, EXAMPLES\n"
            "from pathlib import Path\n"
            "abi = Path(ABI_DIR)\n"
            "examples = Path(EXAMPLES)\n"
            "bundled = 'bundled'\n"
            "assert bundled in abi.as_posix(), abi\n"
            "assert bundled in examples.as_posix(), examples\n"
            "assert (abi / 'VERSION').is_file()\n"
            "assert len(list(abi.glob('*.md'))) >= 8\n"
            "assert len(list(examples.iterdir())) >= 5\n"
            "bundled_root = agents_memory.PACKAGE_DIR / 'bundled'\n"
            "bundled_files = [p for p in bundled_root.rglob('*') if p.is_file()]\n"
            "assert len(bundled_files) >= 17, len(bundled_files)\n"
            f"assert agents_memory.__version__ == {expected!r}, agents_memory.__version__\n"
            "print('ok')\n"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.strip() or proc.stdout.strip())
        self.assertIn("ok", proc.stdout)

    def test_console_script_help(self) -> None:
        proc = subprocess.run(
            [str(self._venv_executable("agents-memory")), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.strip() or proc.stdout.strip())
        self.assertIn("Commands:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
