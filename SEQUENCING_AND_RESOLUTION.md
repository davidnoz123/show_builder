# Sequencing and Resolution

This document defines how reusable shows/blocks are composed and resolved.

## Core Idea

A show is not a special object. A show is just a top-level sequence.

Sequences can contain:

- items
- other sequences

This allows:

- reusable intro blocks
- reusable feature blocks
- variant shows built from the same material
- composition without duplication

## Serial vs Parallel

Each sequence has a `timing_mode`.

### serial

Children play one after the other.

### parallel

Children can overlap in time using `local_start_ms`.

V1 can emphasize `serial`, but the concept of `parallel` should be preserved in the schema now.

## Resolution Process

The Python resolver takes a selected root `sequence_id` and expands it into one flat, resolved timeline.

### Steps

1. load workbook tables
2. choose root sequence
3. expand sequence entries in order
4. for each entry:
   - resolve item directly, or
   - recursively expand nested sequence
5. apply any allowed overrides
6. choose effective text set
7. calculate effective timing
8. detect illegal cycles
9. emit one flat resolved list for the browser player

## Allowed Overrides

Keep overrides deliberately simple.

Recommended v1 overrides:

- `override_duration_ms`
- `override_media_start_s`
- `override_effect_name`
- `override_effect_params_json`
- `override_text_set_id`

## Cycle Rules

Nested sequences are allowed.
Cyclic references are not.

Resolver must detect cycles.

## Timing Model

### Item timing

Each item resolves to:

- effective source asset
- effective media start
- effective duration
- effective text overlays

### Sequence timing

In `serial` mode:
- children are laid out end-to-end

In `parallel` mode:
- children are placed using `local_start_ms`
- sequence duration becomes the max of child end times

## Text Set Selection

Text overlays should not be patched line-by-line through sequence overrides.

Instead:
- an item has one or more text sets
- the resolver selects the effective text set
- overlay rows come from that selected text set

## Flattened Output

The browser player should receive a resolved linear model.

That flattened model should already have:

- media resolved
- timings resolved
- text overlays resolved
- effects resolved
- format context known

The browser should not need to understand nested sequence logic.
