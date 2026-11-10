"""Tests for tools/calc_time.py. Run: python tests/test_calc_time.py"""

import asyncio
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "calc_time", Path(__file__).resolve().parent.parent / "tools" / "calc_time.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
T = mod.Tools()
run = asyncio.run


def test_calculate():
    assert run(T.calculate("(1249.50 * 12) / 3 + sqrt(144)")).endswith("= 5010")
    assert run(T.calculate("2^10")).endswith("= 1024")
    assert run(T.calculate("factorial(20)")).endswith("= 2432902008176640000")
    assert run(T.calculate("0.1 + 0.2")).endswith("= 0.3")
    assert run(T.calculate("round(pi, 4)")).endswith("= 3.1416")


def test_calculate_rejects_unsafe_and_huge():
    for bad in ("__import__('os').system('id')", "9**9**9", "open('x')", "(1).__class__", "1/0", "3,5 * 2", "factorial(99999)"):
        assert run(T.calculate(bad)).startswith("Error"), bad


def test_convert():
    assert "= 62.1371192237 mi" in run(T.convert_units(100, "km", "mi"))
    assert "= 100 °C" in run(T.convert_units(212, "F", "C"))
    assert "= 1024 MiB" in run(T.convert_units(1, "GiB", "MiB"))
    assert run(T.convert_units(1, "kg", "km")).startswith("Error")


def test_dates():
    out = run(T.date_difference("2024-01-31", "2026-11-10"))
    assert "1014 days" in out and "2 years, 9 months, 10 days" in out
    assert run(T.date_difference("2026-03-01", "2026-02-01")).count("-28 days") == 1
    assert run(T.add_to_date("2024-01-31", months=1)).startswith("2024-02-29 (Thursday)")
    assert run(T.add_to_date("2026-11-10", days=-10, years=1)).startswith("2027-10-31")
    assert run(T.add_to_date("not a date")).startswith("Error")


def test_time():
    assert "UTC+0900" in run(T.current_time("Asia/Tokyo"))
    assert "UTC" in run(T.current_time())
    assert run(T.current_time("Mars/Olympus")).startswith("Error")


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
