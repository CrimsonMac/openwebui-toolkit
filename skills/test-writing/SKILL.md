---
name: test-writing
description: Write useful automated tests for code and decide what to test. Use when the user asks for unit tests, test cases, pytest or Jest tests, wants better coverage, or asks how to test a function, class, API or bug fix.
---

# Writing tests

A test earns its place by failing when the code is wrong. A test that cannot fail is noise.

## Before writing

Read the code under test. Know what it promises: inputs, outputs, side effects, errors. If the intended behaviour is unclear, ask; do not write tests that only confirm what the code happens to do, since they would also confirm its bugs.

Use the test framework and style the project already has. If none, use the standard one for the language (pytest for Python, the built-in runner or Jest/Vitest for JavaScript).

## What to test

Go through this list for each function:

1. **The normal case**, with a realistic input.
2. **Boundaries:** empty input, one element, the largest allowed, zero, negative, exactly at a limit and one past it.
3. **Bad input:** wrong type, None/null, malformed strings. Check that the right error is raised.
4. **Each branch** of the logic at least once.
5. **Special values of the domain:** Unicode and whitespace in text, time zones and month ends in dates, rounding in money, duplicates and ordering in lists.
6. **For a bug fix:** a test that fails without the fix and passes with it.

## How to write each test

- **One behaviour per test.** When it fails, the name alone should say what broke: `test_discount_is_not_applied_twice`.
- **Arrange, act, assert**, in that order, with a blank line between.
- **Assert the exact result**, not just that something came back. `assert total == 42.50`, not `assert total`.
- **Tests are independent.** No shared mutable state, no required order.
- **Deterministic.** Fix the clock, the random seed, and the locale. No real network, no sleep.
- **Fake only what is outside the unit:** network, time, file system, external services. Mocking the code under test proves nothing.
- **Plain test code.** No clever loops or logic that could itself be wrong. Use the framework's parametrize feature for many inputs.
- **Test behaviour, not implementation.** A refactor that keeps behaviour should not break tests.

## Rules

- Never change the code under test to make a test pass, and never weaken an assertion to get green. If a test exposes a bug, report the bug.
- Do not write tests for trivial getters or for the language and libraries themselves.
- If you could not run the tests, say so. Do not claim they pass.

## Answer format

The test file, complete and runnable, with the command to run it. Then a short list of what is covered and what is deliberately left out, and any behaviour that looked like a bug while writing the tests.
