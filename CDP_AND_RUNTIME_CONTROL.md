# CDP and Runtime Control

This document defines how Python controls a local Chrome player through CDP.

## Goal

Use a local Chrome tab as the rendering/player surface.

Python should:

- launch or connect to Chrome
- load the local player page
- send resolved show JSON to the player
- command playback
- inspect state
- later support render/export flows

## Browser Hosting

Use a tiny local static HTTP server.

Recommended initial approach:
- Python built-in static file server
- serve `index.html`, `app.js`, `styles.css`, and local media

## Player Page Contract

The browser player should expose a small JS API, for example:

- `window.loadShow(showJson)`
- `window.playShow()`
- `window.pauseShow()`
- `window.stopShow()`
- `window.goToItem(index)`
- `window.getShowStatus()`

Python calls these through CDP runtime evaluation.
