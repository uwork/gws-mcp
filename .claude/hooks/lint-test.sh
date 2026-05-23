#!/usr/bin/env bash

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -n "$FILE" ] || exit 0
echo "$FILE" | grep -qE '\.py$' || exit 0

FORMAT_OUT=$(.venv/bin/ruff format "$FILE" 2>&1)
FORMAT_EXIT=$?

LINT_OUT=$(.venv/bin/ruff check --fix "$FILE" 2>&1)
LINT_EXIT=$?

TEST_OUT=$(uv run pytest 2>&1 | tail -25)
TEST_EXIT=$?

SUMMARY="Auto-check results for ${FILE}:
[ruff format] $([ $FORMAT_EXIT -eq 0 ] && echo 'OK' || echo "FAILED: $FORMAT_OUT")
[ruff check --fix] $([ $LINT_EXIT -eq 0 ] && echo 'OK' || echo "Issues: $LINT_OUT")
[pytest] $([ $TEST_EXIT -eq 0 ] && echo 'PASSED' || echo "FAILED:
$TEST_OUT")"

jq -n --arg ctx "$SUMMARY" \
  '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
