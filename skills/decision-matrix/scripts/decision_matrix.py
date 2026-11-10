#!/usr/bin/env python3
"""Score options against weighted criteria and show how robust the winner is.

Input is JSON (file argument or stdin):
{
  "criteria": {"price": 5, "quality": 3, "delivery time": 2},
  "options": {
    "A": {"price": 7, "quality": 6, "delivery time": 9},
    "B": {"price": 4, "quality": 9, "delivery time": 6}
  }
}
Weights are relative importance (any positive numbers). Scores are 0-10, higher is better.

Usage: decision_matrix.py matrix.json
"""
import json
import sys


def totals(criteria, options):
    wsum = sum(criteria.values())
    return {o: sum(scores[c] * w for c, w in criteria.items()) / wsum for o, scores in options.items()}


def main():
    try:
        data = json.load(open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin)
        criteria, options = data["criteria"], data["options"]
    except (OSError, ValueError, KeyError) as e:
        sys.exit(f"cannot read input: {e}\n{__doc__}")
    if len(options) < 2 or not criteria:
        sys.exit("need at least two options and one criterion")
    for c, w in criteria.items():
        if not isinstance(w, (int, float)) or w <= 0:
            sys.exit(f"weight for '{c}' must be a positive number")
    for o, scores in options.items():
        missing = [c for c in criteria if c not in scores]
        if missing:
            sys.exit(f"option '{o}' has no score for: {', '.join(missing)}")
        for c in criteria:
            if not 0 <= scores[c] <= 10:
                sys.exit(f"score for '{o}' on '{c}' must be between 0 and 10")

    wsum = sum(criteria.values())
    result = totals(criteria, options)
    ranked = sorted(result, key=result.get, reverse=True)
    width = max(len(o) for o in options)

    print("Weights: " + ", ".join(f"{c} {w / wsum:.0%}" for c, w in criteria.items()))
    print()
    for o in ranked:
        parts = "  ".join(f"{c} {options[o][c]:g}" for c in criteria)
        print(f"{o:<{width}}  {result[o]:5.2f} / 10   ({parts})")

    best, second = ranked[0], ranked[1]
    margin = result[best] - result[second]
    print(f"\nWinner: {best}, ahead of {second} by {margin:.2f} points")
    for c in criteria:
        diff = options[best][c] - options[second][c]
        if diff:
            print(f"  {c}: {best} {'leads' if diff > 0 else 'trails'} by {abs(diff):g} (worth {abs(diff) * criteria[c] / wsum:.2f})")

    # Robustness: does the winner change if one weight is doubled or halved?
    flips = []
    for c in criteria:
        for factor in (0.5, 2):
            trial = dict(criteria)
            trial[c] = criteria[c] * factor
            t = totals(trial, options)
            top = max(t, key=t.get)
            if top != best:
                flips.append(f"{'doubling' if factor == 2 else 'halving'} the weight of '{c}' makes {top} win")
    print()
    if margin < 0.3:
        print("The gap is small; treat this as a tie and decide on something the matrix does not capture.")
    if flips:
        print("Sensitive result:")
        for f in flips:
            print(f"  - {f}")
    else:
        print("Robust result: the winner stays the same when any single weight is doubled or halved.")


if __name__ == "__main__":
    main()
