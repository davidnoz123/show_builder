# Python System

This document defines the Python-side responsibilities.

## Goal

Python is the structural brain of the system.

It should own:

- workbook IO
- validation
- sequence resolution
- JSON building
- CLI tools
- CDP control of the browser player

## Main Responsibilities

### Workbook IO

Read and write the Excel workbook.

### Validation

Detect workbook issues early.

Checks should include:

- unique IDs
- missing foreign keys
- invalid enums
- malformed JSON params
- invalid coordinates
- invalid timing
- recursion cycles
- invalid override targets

### Resolver / Compiler

Resolve one selected top-level show sequence into a flat timeline.

### JSON Builder

Convert resolved Python models into browser-ready JSON.

### Tooling / CLI

Provide agent-friendly commands instead of Excel GUI automation.
