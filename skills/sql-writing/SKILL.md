---
name: sql-writing
description: Write, explain, fix or speed up SQL queries. Use when the user asks for a SQL query, wants a question answered from database tables, has a query that returns wrong results or runs slowly, or asks about joins, grouping, window functions or indexes.
---

# Writing SQL

## Before writing

You need the table and column names, what one row of each table represents, and the database (PostgreSQL, MySQL, SQLite, SQL Server). If the schema was not given, ask for it or state the assumed schema at the top. Never invent column names silently.

## Method

1. **Restate the question as a result table.** What is one output row (a customer? a month?), and which columns does it have?
2. **Find the grain.** If one output row is "a customer", then anything with many rows per customer must be aggregated before or while joining.
3. **Build in steps with CTEs** (`WITH step AS (...)`), one idea per step, and name them for what they hold.
4. **Check the row count** in your head at every join: does this join multiply rows?

## Mistakes that give wrong numbers

- **Join fan-out.** Joining orders to order_items and then summing an order-level column counts it once per item. Aggregate first, then join.
- **`WHERE` on the right table of a `LEFT JOIN`** turns it into an inner join. Put that condition in the `ON` clause.
- **`NULL`.** `= NULL` is never true; use `IS NULL`. `NOT IN (subquery)` returns nothing if the subquery yields a NULL; use `NOT EXISTS`. `COUNT(col)` skips NULLs, `COUNT(*)` does not.
- **Non-aggregated columns** missing from `GROUP BY`. MySQL may pick an arbitrary value.
- **`BETWEEN` with timestamps** misses most of the last day. Use `>= start AND < next_day`.
- **Integer division**: `1/2` is `0` in several databases. Multiply by `1.0` or cast.
- **`DISTINCT` to hide duplicates** you do not understand. Find the join that causes them.
- **Top-N per group** needs `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)`, not `LIMIT`.

## Making it fast

- Look at the plan first: `EXPLAIN ANALYZE` (PostgreSQL), `EXPLAIN` (MySQL), `EXPLAIN QUERY PLAN` (SQLite).
- Index the columns in `WHERE`, `JOIN` and `ORDER BY`. A function on a column (`WHERE lower(email) = ...`, `WHERE date(ts) = ...`) prevents index use; rewrite as a range or index the expression.
- Select only the columns needed. Filter early. Avoid a correlated subquery that runs once per row when a join does the same.
- `LIKE '%text'` cannot use a normal index.

## Safety

- For `UPDATE` and `DELETE`: write the `SELECT` with the same `WHERE` first, check the count, and run the change inside a transaction.
- Values from users go in as parameters (`?`, `$1`, `:name`), never by string concatenation.

## Answer format

The query in a code block, formatted with one clause per line. Then: which database dialect it is for, what one result row represents, the assumptions made about the schema, and how to sanity-check the result (for example a total that must match a known number).
