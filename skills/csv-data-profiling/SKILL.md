---
name: csv-data-profiling
description: Understand and sanity-check a CSV or TSV file before analysing it. Use when the user shares or mentions a data file, spreadsheet export or table and wants to know what is in it, whether it is clean, or wants analysis, statistics or charts from it.
---

# Profiling tabular data

Look at the data before answering questions about it. Most wrong analyses come from a column that was not what it seemed.

## Steps

1. **Profile the file.** If you can run code:

   ```
   python scripts/profile_csv.py data.csv
   python scripts/profile_csv.py data.tsv --delimiter $'\t' --top 10
   ```

   It reports rows and columns, and for each column the detected type, missing values, distinct count, range or most common values, outliers, mixed casing, duplicated rows and ragged rows. It needs only the Python standard library.

   If you cannot run code, ask for the header and the first 20 rows, and say that your view is limited to that sample.

2. **Say what one row represents** (an order, a person, a day?) and which column identifies it. If you cannot tell, ask. Everything else depends on it.

3. **Report problems before results**: missing values, duplicates, impossible values (negative ages, dates in the future), mixed units, categories that differ only in spelling or casing, numbers stored as text, decimal commas.

4. **Only then analyse.** For each number you give, say which column and which rows it came from, and how missing values were treated.

## Rules

- Never invent values, column meanings or totals you did not compute. If you did not run the calculation, do not state the result.
- An average over a skewed column misleads; give the median too.
- A correlation is not a cause. Say "is associated with".
- State the row count used for every figure, since filtering changes it.
- If the file was cut off at a row limit, say so.

## Answer format

**What the file is:** one row = …, N rows, N columns.
**Data quality:** the problems found, most important first, or "no problems found in the checks above".
**Answer:** the result, with the columns and rows used.
