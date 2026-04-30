# Effects System

This document defines the extensible effect model.

## Goal

Effects must be easy to add without redesigning the data schema.

That is why both media items and text overlays use:

- `effect_name`
- `effect_params`

## Design Rule

Excel stores:

- effect name
- effect parameter bag

Browser code owns:

- effect implementation

Do not store executable code in Excel.

## Media Effects

Suggested v1 media effects:

- `none`
- `fade`
- `zoom_in`
- `zoom_out`
- `pan_left`
- `pan_right`
- `pan_up`
- `pan_down`
- `ken_burns`

### ken_burns example

```json
{
  "effect_name": "ken_burns",
  "effect_params": {
    "x1": 0.5,
    "y1": 0.5,
    "s1": 1.0,
    "x2": 0.6,
    "y2": 0.4,
    "s2": 1.2,
    "ease": "ease_in_out"
  }
}
```

## Text Effects

Suggested v1 text effects:

- `none`
- `fade`
- `slide_up`
- `slide_down`
- `typewriter`

### typewriter example

```json
{
  "effect_name": "typewriter",
  "effect_params": {
    "char_ms": 35
  }
}
```

## Effect Registry Pattern

Recommended conceptual structure:

```javascript
const mediaEffects = {
  none: applyNone,
  ken_burns: applyKenBurns
};

const textEffects = {
  none: applyTextNone,
  fade: applyTextFade,
  typewriter: applyTextTypewriter
};
```
