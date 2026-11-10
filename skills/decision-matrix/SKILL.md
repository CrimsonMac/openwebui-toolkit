---
name: decision-matrix
description: Help choose between several options in a structured way using weighted criteria. Use when the user is deciding between products, tools, jobs, offers, designs or plans and asks which is best, asks to compare options, or says they cannot decide.
---

# Deciding between options

The aim is a choice the user understands and trusts, not a number.

## Steps

1. **Pin down the decision.** What exactly is being chosen, by when, and can it be undone later? A reversible choice deserves less analysis.
2. **List the options**, including "do nothing" or "wait" when that is real. Two to five options.
3. **Find the deal-breakers first.** Any option that fails a hard requirement (budget cap, must run on Linux) is out before scoring.
4. **Get the criteria from the user**, three to six of them, and how much each matters. Ask "what would make you regret this choice?" if they are unsure. Do not invent their priorities.
5. **Score each option 0–10 per criterion**, higher is better, and give the reason for each score. Mark scores that are guesses. For cost-like criteria, a low cost gets a high score.
6. **Compute.** If you can run code, write the matrix as JSON and run:

   ```
   python scripts/decision_matrix.py matrix.json
   ```

   ```json
   {
     "criteria": {"price": 5, "quality": 3, "delivery time": 2},
     "options": {
       "A": {"price": 7, "quality": 6, "delivery time": 9},
       "B": {"price": 4, "quality": 9, "delivery time": 6}
     }
   }
   ```

   It ranks the options, shows which criteria decide between the top two, and tests whether the winner changes when any weight is doubled or halved. Without code execution, compute weighted sums with a calculator tool, never in your head.
7. **Sanity-check with the user.** "The matrix says A. Does that feel right?" If it feels wrong, a criterion is missing or a weight is off. Find it; that is the real result.

## Rules

- Show the table. The user must be able to disagree with a single cell.
- A lead under about 0.3 points is a tie. Say so, and decide on something the matrix leaves out: risk, reversibility, gut feeling.
- If the result flips when one weight changes, tell the user that the decision hinges on that one priority.
- Give a recommendation at the end. "It depends" is not an answer; say what it depends on and which way you lean.
