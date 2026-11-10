"""
title: Calculator & Time
author: Crimson
version: 1.0.0
description: Exact arithmetic, unit conversion and date maths, so the model never has to do them in its head. No dependencies, no network.
"""

import ast
import math
import operator
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

_FUNCS = {
    name: getattr(math, name)
    for name in (
        "sqrt", "cbrt", "exp", "log", "log2", "log10", "sin", "cos", "tan", "asin",
        "acos", "atan", "atan2", "sinh", "cosh", "tanh", "degrees", "radians",
        "floor", "ceil", "trunc", "gcd", "lcm", "comb", "perm", "hypot",
    )
    if hasattr(math, name)
}
_FUNCS.update(abs=abs, round=round, min=min, max=max, sum=lambda *a: sum(a))
_FUNCS["factorial"] = lambda n: math.factorial(_limit(n, 2000, "factorial argument"))
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _limit(n, cap, what):
    if abs(n) > cap:
        raise ValueError(f"{what} too large (limit {cap})")
    return n


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow):
            _limit(right, 10000, "exponent")
            if isinstance(left, int) and isinstance(right, int) and right > 0:
                if left.bit_length() * right > 200000:
                    raise ValueError("result too large")
        return _BIN[type(node.op)](left, right)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCS
        and not node.keywords
    ):
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError(f"unsupported syntax: {ast.dump(node)[:60]}")


def _fmt(x) -> str:
    if isinstance(x, float):
        if x.is_integer() and abs(x) < 1e15:
            return str(int(x))
        return f"{x:.12g}"
    return str(x)


# Factor to the base unit of each kind.
_UNITS = {
    "length": {
        "mm": 0.001, "cm": 0.01, "m": 1, "km": 1000, "in": 0.0254, "inch": 0.0254,
        "ft": 0.3048, "foot": 0.3048, "feet": 0.3048, "yd": 0.9144, "mi": 1609.344,
        "mile": 1609.344, "nmi": 1852,
    },
    "mass": {
        "mg": 1e-6, "g": 0.001, "kg": 1, "t": 1000, "oz": 0.028349523125,
        "lb": 0.45359237, "lbs": 0.45359237, "st": 6.35029318,
    },
    "volume": {
        "ml": 0.001, "cl": 0.01, "dl": 0.1, "l": 1, "m3": 1000, "tsp": 0.00492892159375,
        "tbsp": 0.01478676478125, "floz": 0.0295735295625, "cup": 0.2365882365,
        "pt": 0.473176473, "qt": 0.946352946, "gal": 3.785411784,
    },
    "time": {
        "ms": 0.001, "s": 1, "sec": 1, "min": 60, "h": 3600, "hr": 3600, "hour": 3600,
        "day": 86400, "d": 86400, "week": 604800, "year": 31557600,
    },
    "data": {
        "bit": 0.125, "b": 1, "byte": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12,
        "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4,
    },
    "speed": {"m/s": 1, "km/h": 1 / 3.6, "kph": 1 / 3.6, "mph": 0.44704, "kn": 0.514444, "knot": 0.514444},
    "area": {"cm2": 1e-4, "m2": 1, "km2": 1e6, "ha": 1e4, "ft2": 0.09290304, "acre": 4046.8564224},
    "energy": {"j": 1, "kj": 1000, "cal": 4.184, "kcal": 4184, "wh": 3600, "kwh": 3.6e6},
    "pressure": {"pa": 1, "kpa": 1000, "bar": 1e5, "atm": 101325, "psi": 6894.757293168},
}
_TEMPS = {"c", "f", "k", "celsius", "fahrenheit", "kelvin"}


def _unit_key(u: str) -> str:
    u = u.strip().lower().replace("°", "").replace(" ", "").replace("²", "2").replace("³", "3")
    return u


def _parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.lower() in ("now", "today"):
        return datetime.now()
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    for f in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    raise ValueError(f"cannot read date '{s}'; use YYYY-MM-DD or YYYY-MM-DD HH:MM")


class Tools:
    class Valves(BaseModel):
        default_timezone: str = Field(
            "", description="IANA timezone used when none is given. Empty = the server's local timezone."
        )

    def __init__(self):
        self.valves = self.Valves()

    async def calculate(self, expression: str) -> str:
        """
        Evaluate a maths expression exactly. Use this for ANY arithmetic instead of computing it yourself.
        Supports + - * / // % **, parentheses, pi, e, and functions such as sqrt, log, log10, sin, cos, tan,
        factorial, comb, gcd, round, min, max. Percent example: "15% of 80" is written as "0.15 * 80".

        :param expression: The expression, for example "(1249.50 * 12) / 3 + sqrt(144)".
        :return: The result, or an error message explaining what to fix.
        """
        try:
            expr = expression.replace("^", "**").replace("×", "*").replace("÷", "/")
            if len(expr) > 500:
                return "Error: expression too long."
            return f"{expression} = {_fmt(_eval(ast.parse(expr.strip(), mode='eval')))}"
        except ZeroDivisionError:
            return "Error: division by zero."
        except Exception as e:
            hint = " Use '.' as the decimal separator." if "," in expression else ""
            return f"Error: {e}.{hint}"

    async def convert_units(self, value: float, from_unit: str, to_unit: str) -> str:
        """
        Convert a quantity between units of the same kind: length, mass, volume, time, data size,
        speed, area, energy, pressure or temperature.

        :param value: The number to convert, for example 5.5.
        :param from_unit: Unit to convert from, for example "km", "lb", "gal", "mph", "GiB", "F".
        :param to_unit: Unit to convert to, for example "mi", "kg", "l", "km/h", "MB", "C".
        :return: The converted value, or the list of supported units if one is unknown.
        """
        a, b = _unit_key(from_unit), _unit_key(to_unit)
        if a in _TEMPS and b in _TEMPS:
            a, b = a[0], b[0]
            kelvin = {"c": value + 273.15, "f": (value - 32) * 5 / 9 + 273.15, "k": value}[a]
            out = {"c": kelvin - 273.15, "f": (kelvin - 273.15) * 9 / 5 + 32, "k": kelvin}[b]
            return f"{_fmt(value)} °{a.upper()} = {_fmt(round(out, 4))} °{b.upper()}"
        for kind, table in _UNITS.items():
            if a in table and b in table:
                out = value * table[a] / table[b]
                return f"{_fmt(value)} {from_unit} = {_fmt(out)} {to_unit} ({kind})"
        known = "; ".join(f"{k}: {', '.join(t)}" for k, t in _UNITS.items())
        return f"Error: cannot convert '{from_unit}' to '{to_unit}'. Supported units — {known}; temperature: C, F, K."

    async def current_time(self, timezone: str = "") -> str:
        """
        Get the current date, time, weekday and ISO week number. Use this whenever the answer depends on today's date.

        :param timezone: IANA timezone name such as "Europe/Berlin" or "America/New_York". Leave empty for the default.
        :return: The current local date and time.
        """
        name = timezone.strip() or self.valves.default_timezone
        try:
            now = datetime.now(ZoneInfo(name)) if name else datetime.now().astimezone()
        except Exception:
            return f"Error: unknown timezone '{timezone}'. Use an IANA name like 'Europe/Berlin'."
        return (
            f"{now:%A %Y-%m-%d %H:%M:%S} {name or now.tzname()} (UTC{now:%z}), "
            f"ISO week {now.isocalendar().week}, day {now.timetuple().tm_yday} of the year"
        )

    async def date_difference(self, start: str, end: str) -> str:
        """
        Compute the exact time between two dates or datetimes.

        :param start: Start date, "YYYY-MM-DD" or "YYYY-MM-DD HH:MM", or "today".
        :param end: End date in the same format, or "today".
        :return: The difference in days, weeks, and years/months/days.
        """
        try:
            a, b = _parse_dt(start), _parse_dt(end)
        except ValueError as e:
            return f"Error: {e}"
        delta = b - a
        lo, hi = sorted((a, b))
        years = hi.year - lo.year
        months = hi.month - lo.month
        days = hi.day - lo.day
        if days < 0:
            months -= 1
            prev_month_end = date(hi.year, hi.month, 1) - timedelta(days=1)
            days += prev_month_end.day
        if months < 0:
            years -= 1
            months += 12
        sign = "-" if delta.total_seconds() < 0 else ""
        total = abs(delta)
        out = (
            f"From {a:%Y-%m-%d %H:%M} ({a:%A}) to {b:%Y-%m-%d %H:%M} ({b:%A}): "
            f"{sign}{total.days} days ({sign}{total.days / 7:.1f} weeks), "
            f"or {sign}{years} years, {months} months, {days} days"
        )
        if total.seconds:
            out += f", plus {total.seconds // 3600} h {total.seconds % 3600 // 60} min"
        return out

    async def add_to_date(self, start: str, days: int = 0, weeks: int = 0, months: int = 0, years: int = 0) -> str:
        """
        Add (or subtract, with negative numbers) days, weeks, months and years to a date.

        :param start: Start date, "YYYY-MM-DD" or "today".
        :param days: Days to add. Negative subtracts.
        :param weeks: Weeks to add. Negative subtracts.
        :param months: Months to add. Negative subtracts.
        :param years: Years to add. Negative subtracts.
        :return: The resulting date and its weekday.
        """
        try:
            d = _parse_dt(start)
        except ValueError as e:
            return f"Error: {e}"
        m = d.month - 1 + months + years * 12
        year, month = d.year + m // 12, m % 12 + 1
        next_month = date(year + month // 12, month % 12 + 1, 1)
        last_day = (next_month - timedelta(days=1)).day
        try:
            d = d.replace(year=year, month=month, day=min(d.day, last_day)) + timedelta(days=days, weeks=weeks)
        except (ValueError, OverflowError) as e:
            return f"Error: {e}"
        return f"{d:%Y-%m-%d} ({d:%A}), ISO week {d.isocalendar().week}"
