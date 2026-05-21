"""T19 — purity lint: no hamilton/pi import in L1 gate module (V5).

Two complementary enforcement mechanisms:
  1. AST-scan: statically inspects every .py under src/insight_kit/gate/ for
     any import of `hamilton` or any pi package.  Catches both top-level and
     nested imports (e.g. inside `if TYPE_CHECKING:` blocks).
  2. sys.modules probe: imports insight_kit.gate in a fresh subprocess and
     asserts that `hamilton` and any pi module are absent from sys.modules
     after import.

Both checks must pass.  The AST-scan is the primary enforcement; the
sys.modules probe catches any dynamic / deferred import that AST-scan misses.

Cites: V5, C1.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants — forbidden module prefixes
# ---------------------------------------------------------------------------

_GATE_DIR = Path(__file__).parent.parent.parent / "src" / "insight_kit" / "gate"

# Exact module names or prefixes that must never appear in gate/
# "hamilton" covers sf-hamilton and hamilton submodules.
# "pi" as a standalone package name or any submodule (pi.*, pi_*).
_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "hamilton",
    "earendil",  # @earendil-works/pi-coding-agent Python bindings, if any
)

# Exact standalone names that are banned (e.g. bare `import pi`)
_FORBIDDEN_EXACT: frozenset[str] = frozenset({"hamilton", "pi"})


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _extract_imports(tree: ast.AST) -> list[str]:
    """Walk an AST and return all imported module names (dotted strings).

    Handles:
      import foo            → ["foo"]
      import foo.bar        → ["foo.bar"]
      from foo import bar   → ["foo"]
      from foo.bar import x → ["foo.bar"]
    """
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
            # from . import x (relative, module=None) — safe, no absolute name
    return names


def _is_forbidden(module_name: str) -> bool:
    """True if module_name matches any forbidden prefix or exact name."""
    if module_name in _FORBIDDEN_EXACT:
        return True
    top_level = module_name.split(".")[0]
    if top_level in _FORBIDDEN_EXACT:
        return True
    return any(module_name == p or module_name.startswith(p + ".") for p in _FORBIDDEN_PREFIXES)


# ---------------------------------------------------------------------------
# V5 — AST-scan test (primary enforcement)
# ---------------------------------------------------------------------------


class TestGateImportPurityAST:
    """Statically verify no hamilton/pi import in any gate module."""

    def _gate_py_files(self) -> list[Path]:
        """All .py files under src/insight_kit/gate/ (not __pycache__)."""
        return [
            p for p in _GATE_DIR.rglob("*.py")
            if "__pycache__" not in p.parts
        ]

    def test_gate_dir_exists(self):
        """Sanity: gate directory is where we expect it."""
        assert _GATE_DIR.is_dir(), f"gate dir not found: {_GATE_DIR}"

    def test_gate_py_files_found(self):
        """At least one .py file found under gate/."""
        files = self._gate_py_files()
        assert len(files) > 0, f"No .py files found under {_GATE_DIR}"

    def test_no_hamilton_import_ast(self):
        """No gate module imports hamilton (AST scan, all nesting levels)."""
        violations: list[str] = []
        for py_file in self._gate_py_files():
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError as exc:
                violations.append(f"{py_file}: SyntaxError — {exc}")
                continue
            for imp in _extract_imports(tree):
                if _is_forbidden(imp) and "hamilton" in imp:
                    violations.append(f"{py_file}: forbidden import of {imp!r}")

        assert not violations, (
            "V5 violation — hamilton import found in gate module(s):\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_no_pi_import_ast(self):
        """No gate module imports pi package (AST scan, all nesting levels)."""
        violations: list[str] = []
        for py_file in self._gate_py_files():
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError as exc:
                violations.append(f"{py_file}: SyntaxError — {exc}")
                continue
            for imp in _extract_imports(tree):
                if _is_forbidden(imp) and (imp == "pi" or imp.startswith("pi.")):
                    violations.append(f"{py_file}: forbidden import of {imp!r}")

        assert not violations, (
            "V5 violation — pi import found in gate module(s):\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_no_earendil_import_ast(self):
        """No gate module imports earendil (pi-coding-agent) package (AST scan)."""
        violations: list[str] = []
        for py_file in self._gate_py_files():
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError as exc:
                violations.append(f"{py_file}: SyntaxError — {exc}")
                continue
            for imp in _extract_imports(tree):
                if _is_forbidden(imp) and "earendil" in imp:
                    violations.append(f"{py_file}: forbidden import of {imp!r}")

        assert not violations, (
            "V5 violation — earendil/pi-coding-agent import found in gate module(s):\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_combined_forbidden_scan(self):
        """Combined scan: no forbidden import in any gate module (exhaustive)."""
        violations: list[str] = []
        for py_file in self._gate_py_files():
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError as exc:
                violations.append(f"{py_file}: SyntaxError — {exc}")
                continue
            for imp in _extract_imports(tree):
                if _is_forbidden(imp):
                    violations.append(f"{py_file}: forbidden import of {imp!r}")

        assert not violations, (
            "V5 violation — forbidden import(s) found in gate module(s):\n"
            + "\n".join(f"  {v}" for v in violations)
        )


# ---------------------------------------------------------------------------
# V5 — sys.modules probe (subprocess — clean interpreter state)
# ---------------------------------------------------------------------------

_PURITY_PROBE = """\
import sys
import insight_kit.gate  # noqa: F401

# Check: hamilton must not be in sys.modules after gate import
hamilton_mods = [m for m in sys.modules if m == "hamilton" or m.startswith("hamilton.")]
# Check: pi must not be a loaded package (bare "pi" or pi.*)
pi_mods = [m for m in sys.modules if m == "pi" or m.startswith("pi.")]
# Check: earendil must not be loaded
earendil_mods = [m for m in sys.modules if "earendil" in m]

violations = hamilton_mods + pi_mods + earendil_mods
if violations:
    raise AssertionError(
        f"V5 violated: gate import pulled in forbidden module(s): {violations}"
    )
print("PURITY_OK")
"""


class TestGateImportPuritySysModules:
    """Probe sys.modules after gate import in a fresh subprocess."""

    def test_hamilton_absent_from_sys_modules_after_gate_import(self):
        """hamilton not in sys.modules after import insight_kit.gate."""
        result = subprocess.run(
            [sys.executable, "-c", _PURITY_PROBE],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"V5 sys.modules probe failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert result.stdout.strip() == "PURITY_OK"

    def test_pi_absent_from_sys_modules_after_gate_import(self):
        """pi package not in sys.modules after import insight_kit.gate."""
        probe = """\
import sys
import insight_kit.gate  # noqa: F401
pi_mods = [m for m in sys.modules if m == "pi" or m.startswith("pi.")]
if pi_mods:
    raise AssertionError(f"V5 violated: pi loaded: {pi_mods}")
print("PI_ABSENT_OK")
"""
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"V5 pi probe failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert result.stdout.strip() == "PI_ABSENT_OK"
