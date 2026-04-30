# Agent Workflow

This document defines how a VS Code agent such as Claude should work with ShowBuilder.

## Core Rule

Do not automate Excel as a GUI unless absolutely necessary.

Preferred approach:
- edit the workbook structurally through Python tools
- validate after changes
- rebuild preview output
- inspect results

## Agent Operating Principles

- preserve stable IDs unless intentionally creating new entities
- make the smallest safe structural change
- always validate after edits
- prefer cloning and reusing sequences/items over duplicating data blindly
- do not invent uncontrolled enum values
- do not bypass validation rules

## Recommended Workflow Loop

1. inspect schema / IDs
2. decide smallest safe change
3. update workbook via Python tooling
4. run validation
5. build resolved show JSON
6. preview the result
