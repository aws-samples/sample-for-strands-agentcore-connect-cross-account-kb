# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Normalize Knowledge Base responses for deterministic agent presentation."""

MAX_FORMATTED_ROWS = 100


def _markdown_cell(value) -> str:
    """Return a compact, Markdown-safe representation of a row value."""
    if value is None:
        return ""
    return (
        str(value)
        .strip()
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _extract_sql_rows(response: dict) -> tuple[list[dict], str]:
    """Extract source-ordered SQL rows and the generated SQL statement."""
    rows = []
    sql = ""

    for citation in response.get("citations", []):
        for reference in citation.get("retrievedReferences", []):
            content = reference.get("content", {})
            row = content.get("row")
            if content.get("type") != "ROW" or not isinstance(row, list):
                continue

            values = {}
            for column in row:
                name = column.get("columnName")
                if name:
                    values[name] = column.get("columnValue", "")
            if values:
                rows.append(values)

            if not sql:
                sql = (
                    reference.get("location", {})
                    .get("sqlLocation", {})
                    .get("query", "")
                )

    return rows, sql


def _format_rows(rows: list[dict], max_rows: int) -> str:
    """Format source rows as a Markdown table without changing their order."""
    columns = []
    for row in rows:
        for column in row:
            if column not in columns:
                columns.append(column)

    displayed_rows = rows[:max_rows]
    lines = [
        "| " + " | ".join(_markdown_cell(column) for column in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    lines.extend(
        "| "
        + " | ".join(_markdown_cell(row.get(column, "")) for column in columns)
        + " |"
        for row in displayed_rows
    )

    summary = (
        f"Retrieved {len(rows)} row{'s' if len(rows) != 1 else ''}. "
        "The table preserves the source order."
    )
    if len(rows) > len(displayed_rows):
        summary += (
            f" Showing the first {len(displayed_rows)} rows because the display "
            f"limit is {max_rows}."
        )

    return summary + "\n\n" + "\n".join(lines)


def build_tool_response(
    response: dict,
    query: str,
    source: str,
    max_rows: int = MAX_FORMATTED_ROWS,
) -> dict:
    """Build a compact tool response, preserving all bounded SQL result rows."""
    rows, sql = _extract_sql_rows(response)
    if rows:
        displayed_row_count = min(len(rows), max_rows)
        result = {
            "answer": _format_rows(rows, max_rows),
            "query": query,
            "source": source,
            "resultFormat": "markdown_table",
            "rowCount": len(rows),
            "displayedRowCount": displayed_row_count,
        }
        if sql:
            result["sql"] = sql
        return result

    citations = [
        {
            "retrievedReferences": citation.get("retrievedReferences", []),
            "generatedResponsePart": citation.get("generatedResponsePart", ""),
        }
        for citation in response.get("citations", [])
    ]
    return {
        "answer": response.get("output", {}).get("text", ""),
        "citations": citations,
        "query": query,
        "source": source,
    }
