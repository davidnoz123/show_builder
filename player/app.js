// app.js -- ShowBuilder player v2
// Renders a flat resolved show JSON produced by showbuilder/resolver.py.
//
// window.createPlayer(container) -- factory; returns a player API object.
// Multiple independent instances can be created by passing different container elements.
// For the default full-page player, index.html calls createPlayer and binds the
// returned API to window globals so Python/CDP Runtime.evaluate calls still work.
//
// Player API:
//   loadShow(json)      load a resolved show (JSON string or object)
//   playShow()          start playback from current item
//   pauseShow()         freeze current item; resume restarts it
//   stopShow()          stop and reset to item 0
//   goToItem(n)         jump to item index n (plays immediately if playing)
//   getShowStatus()     returns {state, item, total, sequence}
//   getStageRect()      returns the stage's DOMRect (viewport coordinates + size)

window.createPlayer = function (container, options) {
    'use strict';
    options = options || {};
    // masks: true (default) -- create four fixed viewport masks to contain YouTube OOPIF overflow.
    // Set to false for embedded/multi-player layouts where players share the viewport.
    // Local video assets don't need masks; only YouTube iframes need them.
    var _useMasks = options.masks !== false;

    // ---- Build DOM ----
    // All player structure is created here so multiple instances can coexist.
    container.innerHTML = [
        '<div class="sb-stage">',
        '  <div class="sb-media-layer"></div>',
        '  <div class="sb-overlay-layer"></div>',
        '  <div class="sb-stage-frame"></div>',
        '</div>',
        '<div class="sb-debug-bar"><span class="sb-debug-info">idle</span></div>',
    ].join('\n');

    // Viewport masks: fixed-position, appended to document.body so they sit in
    // the viewport stacking context and composite above YouTube OOPIF layers.
    // Only created when masks:true (the default for full-page single-player use).
    function _makeMask(extra) {
        var m = document.createElement('div');
        m.className = 'sb-mask ' + extra;
        document.body.appendChild(m);
        return m;
    }
    var _maskTop    = _useMasks ? _makeMask('sb-mask-top')    : null;
    var _maskBottom = _useMasks ? _makeMask('sb-mask-bottom') : null;
    var _maskLeft   = _useMasks ? _makeMask('sb-mask-left')   : null;
    var _maskRight  = _useMasks ? _makeMask('sb-mask-right')  : null;

    var _stage        = container.querySelector('.sb-stage');
    var _mediaLayer   = container.querySelector('.sb-media-layer');
    var _overlayLayer = container.querySelector('.sb-overlay-layer');
    var _debugInfo    = container.querySelector('.sb-debug-info');

    // ---- State ----
    var _show          = null;
    var _state         = 'idle';   // idle | loaded | playing | paused | stopped
    var _itemIndex     = 0;
    var _rafHandle     = null;
    var _itemTimer     = null;
    var _outTimer      = null;
    var _freezeTimer   = null;
    var _resumeTimer   = null;
    var _overlayTimers = [];
    var _ytPlayer      = null;
    var _ytApiLoading  = false;
    var _ytCallbacks   = [];

    // Position the four fixed masks around the stage rect so they cover any
    // OOPIF overflow that escapes the stage boundary.
    function _updateMasks() {
        if (!_useMasks) return;
        var r  = _stage.getBoundingClientRect();
        var vw = window.innerWidth;
        var vh = window.innerHeight;
        // top mask: full width, above stage
        _maskTop.style.cssText    = 'left:0;top:0;width:' + vw + 'px;height:' + r.top + 'px;';
        // bottom mask: full width, below stage
        _maskBottom.style.cssText = 'left:0;top:' + r.bottom + 'px;width:' + vw + 'px;height:' + (vh - r.bottom) + 'px;';
        // left mask: stage height, left of stage
        _maskLeft.style.cssText   = 'left:0;top:' + r.top + 'px;width:' + r.left + 'px;height:' + r.height + 'px;';
        // right mask: stage height, right of stage
        _maskRight.style.cssText  = 'left:' + r.right + 'px;top:' + r.top + 'px;width:' + (vw - r.right) + 'px;height:' + r.height + 'px;';
    }
    _updateMasks();
    window.addEventListener('resize', _updateMasks);

    // ---- Debug ----
    function _dbg(msg) {
        if (_debugInfo) _debugInfo.textContent = msg;
        console.log('[player]', msg);
    }

    // ---- Easing ----
    function _ease(name, p) {
        p = Math.max(0, Math.min(1, p));
        if (name === 'ease_in')     return p * p;
        if (name === 'ease_out')    return p * (2 - p);
        if (name === 'ease_in_out') return p < 0.5 ? 2 * p * p : -1 + (4 - 2 * p) * p;
        return p;  // linear
    }

    // ---- Stage sizing ----
    function _applyFormat(fmt) {
        if (!fmt || !fmt.width_px || !fmt.height_px) return;
        _stage.style.aspectRatio = (fmt.width_px / fmt.height_px).toFixed(6);
    }

    // ---- Overlay positioning ----
    var _PRESETS = {
        top_left:      { left: '2%',  top: '2%',    bottom: '', right: '',  transform: '' },
        top_center:    { left: '50%', top: '2%',    bottom: '', right: '',  transform: 'translateX(-50%)' },
        top_right:     { left: '',    top: '2%',    bottom: '', right: '2%', transform: '' },
        center_left:   { left: '2%',  top: '50%',   bottom: '', right: '',  transform: 'translateY(-50%)' },
        center:        { left: '50%', top: '50%',   bottom: '', right: '',  transform: 'translate(-50%,-50%)' },
        center_right:  { left: '',    top: '50%',   bottom: '', right: '2%', transform: 'translateY(-50%)' },
        bottom_left:   { left: '2%',  top: '',      bottom: '2%', right: '', transform: '' },
        bottom_center: { left: '50%', top: '',      bottom: '2%', right: '', transform: 'translateX(-50%)' },
        bottom_right:  { left: '',    top: '',      bottom: '2%', right: '2%', transform: '' },
    };

    var _ANCHOR_TRANSFORMS = {
        top_left:      '',
        top_center:    'translateX(-50%)',
        top_right:     'translateX(-100%)',
        center_left:   'translateY(-50%)',
        center:        'translate(-50%,-50%)',
        center_right:  'translate(-100%,-50%)',
        bottom_left:   'translateY(-100%)',
        bottom_center: 'translate(-50%,-100%)',
        bottom_right:  'translate(-100%,-100%)',
    };

    function _positionOverlay(el, ov) {
        if (ov.position_mode === 'coords') {
            el.style.left      = (ov.pos_x * 100) + '%';
            el.style.top       = (ov.pos_y * 100) + '%';
            el.style.transform = _ANCHOR_TRANSFORMS[ov.anchor] || '';
            if (ov.width_norm) el.style.width = (ov.width_norm * 100) + '%';
        } else {
            var p = _PRESETS[ov.position_preset] || _PRESETS.bottom_center;
            el.style.left      = p.left;
            el.style.top       = p.top;
            el.style.bottom    = p.bottom;
            el.style.right     = p.right;
            el.style.transform = p.transform;
        }
    }

    // ---- Media effects (rAF-driven) ----
    // Returns a function(rawProgress 0..1) or null.
    function _makeMediaEffectFn(effectName, params, el) {
        var ease = params.ease || 'linear';
        switch (effectName) {
            case 'ken_burns': {
                var x1 = params.x1 != null ? params.x1 : 0.5;
                var y1 = params.y1 != null ? params.y1 : 0.5;
                var s1 = params.s1 != null ? params.s1 : 1.0;
                var x2 = params.x2 != null ? params.x2 : 0.5;
                var y2 = params.y2 != null ? params.y2 : 0.5;
                var s2 = params.s2 != null ? params.s2 : 1.2;
                return function (raw) {
                    var p  = _ease(ease, raw);
                    var fx = x1 + (x2 - x1) * p;
                    var fy = y1 + (y2 - y1) * p;
                    var sc = s1 + (s2 - s1) * p;
                    el.style.transformOrigin = (fx * 100) + '% ' + (fy * 100) + '%';
                    el.style.transform       = 'scale(' + sc + ')';
                };
            }
            case 'zoom_in': {
                var from = params.from != null ? params.from : 1.0;
                var to   = params.to   != null ? params.to   : 1.15;
                return function (raw) {
                    el.style.transform = 'scale(' + (from + (to - from) * _ease(ease, raw)) + ')';
                };
            }
            case 'zoom_out': {
                var from2 = params.from != null ? params.from : 1.15;
                var to2   = params.to   != null ? params.to   : 1.0;
                return function (raw) {
                    el.style.transform = 'scale(' + (from2 + (to2 - from2) * _ease(ease, raw)) + ')';
                };
            }
            case 'pan_left':
                return function (raw) {
                    el.style.transform = 'scale(1.15) translateX(' + (_ease(ease, raw) * -6) + '%)';
                };
            case 'pan_right':
                return function (raw) {
                    el.style.transform = 'scale(1.15) translateX(' + ((1 - _ease(ease, raw)) * -6) + '%)';
                };
            case 'pan_up':
                return function (raw) {
                    el.style.transform = 'scale(1.15) translateY(' + (_ease(ease, raw) * -6) + '%)';
                };
            case 'pan_down':
                return function (raw) {
                    el.style.transform = 'scale(1.15) translateY(' + ((1 - _ease(ease, raw)) * -6) + '%)';
                };
            default:
                return null;  // none or unrecognised
        }
    }

    // ---- Item-level transitions ----
    var _TRANS_MS = 400;

    // ---- YouTube-specific layout effects ----
    // Uses width/height/left/top instead of CSS transforms so that overflow:hidden
    // on wrapper clips at the box-model level (before OOPIF compositing), which
    // reliably contains YouTube iframes that transform: scale() cannot clip.
    function _makeYTEffectFn(effectName, params, zoomTarget) {
        if (!effectName) return null;
        var ease = params.ease || 'linear';
        // Release right/bottom constraints so we can drive size freely.
        zoomTarget.style.right  = 'auto';
        zoomTarget.style.bottom = 'auto';
        function _setBox(s, cx, cy) {
            zoomTarget.style.width  = (s * 100) + '%';
            zoomTarget.style.height = (s * 100) + '%';
            zoomTarget.style.left   = ((0.5 - cx * s) * 100) + '%';
            zoomTarget.style.top    = ((0.5 - cy * s) * 100) + '%';
        }
        switch (effectName) {
            case 'zoom_in': {
                var from = params.from != null ? params.from : 1.0;
                var to   = params.to   != null ? params.to   : 1.15;
                return function (raw) { _setBox(from + (to - from) * _ease(ease, raw), 0.5, 0.5); };
            }
            case 'zoom_out': {
                var from2 = params.from != null ? params.from : 1.15;
                var to2   = params.to   != null ? params.to   : 1.0;
                return function (raw) { _setBox(from2 + (to2 - from2) * _ease(ease, raw), 0.5, 0.5); };
            }
            case 'ken_burns': {
                var x1 = params.x1 != null ? params.x1 : 0.5;
                var y1 = params.y1 != null ? params.y1 : 0.5;
                var s1 = params.s1 != null ? params.s1 : 1.0;
                var x2 = params.x2 != null ? params.x2 : 0.5;
                var y2 = params.y2 != null ? params.y2 : 0.5;
                var s2 = params.s2 != null ? params.s2 : 1.2;
                return function (raw) {
                    var p = _ease(ease, raw);
                    _setBox(s1 + (s2 - s1) * p, x1 + (x2 - x1) * p, y1 + (y2 - y1) * p);
                };
            }
            // Pan effects: keep 110% size so edges don't reveal background.
            case 'pan_left':
                return function (raw) { _setBox(1.1, 0.5 + _ease(ease, raw) * 0.1, 0.5); };
            case 'pan_right':
                return function (raw) { _setBox(1.1, 0.5 - _ease(ease, raw) * 0.1, 0.5); };
            case 'pan_up':
                return function (raw) { _setBox(1.1, 0.5, 0.5 + _ease(ease, raw) * 0.1); };
            case 'pan_down':
                return function (raw) { _setBox(1.1, 0.5, 0.5 - _ease(ease, raw) * 0.1); };
            default:
                return null;
        }
    }

    function _applyTransitionIn(el, name) {
        if (!name || name === 'none' || name === '') return;
        if (name === 'fade') {
            el.style.opacity    = '0';
            el.style.transition = 'opacity ' + (_TRANS_MS / 1000).toFixed(2) + 's ease';
            setTimeout(function () { el.style.opacity = '1'; }, 20);
        }
    }

    function _scheduleTransitionOut(el, name, durationMs) {
        if (!name || name === 'none' || name === '') return null;
        if (name === 'fade') {
            return setTimeout(function () {
                el.style.transition = 'opacity ' + (_TRANS_MS / 1000).toFixed(2) + 's ease';
                el.style.opacity    = '0';
            }, Math.max(0, durationMs - _TRANS_MS));
        }
        return null;
    }

    // ---- Text effects ----
    function _applyTextIn(el, effectName, params) {
        switch (effectName) {
            case 'fade':
                el.style.opacity    = '0';
                el.style.transition = 'opacity 0.4s ease';
                setTimeout(function () { el.style.opacity = '1'; }, 20);
                break;
            case 'slide_up':
                el.style.opacity    = '0';
                el.style.transform  = (el.style.transform || '') + ' translateY(24px)';
                el.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
                setTimeout(function () {
                    el.style.opacity   = '1';
                    el.style.transform = el.style.transform.replace('translateY(24px)', 'translateY(0)');
                }, 20);
                break;
            case 'slide_down':
                el.style.opacity    = '0';
                el.style.transform  = (el.style.transform || '') + ' translateY(-24px)';
                el.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
                setTimeout(function () {
                    el.style.opacity   = '1';
                    el.style.transform = el.style.transform.replace('translateY(-24px)', 'translateY(0)');
                }, 20);
                break;
            case 'typewriter': {
                var full   = el.dataset.fullContent || '';
                var charMs = (params && params.char_ms) ? params.char_ms : 35;
                el.textContent = '';
                var i = 0;
                var tw = setInterval(function () {
                    if (i < full.length) {
                        el.textContent += full[i++];
                    } else {
                        clearInterval(tw);
                    }
                }, charMs);
                el.dataset.twInterval = tw;
                break;
            }
            default:
                break;  // none — appear immediately
        }
    }

    function _applyTextOut(el, effectName) {
        if (el.dataset.twInterval) clearInterval(parseInt(el.dataset.twInterval, 10));
        switch (effectName) {
            case 'fade':
                el.style.transition = 'opacity 0.3s ease';
                el.style.opacity    = '0';
                setTimeout(function () { if (el.parentNode) el.remove(); }, 320);
                break;
            case 'slide_up':
                el.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                el.style.opacity    = '0';
                el.style.transform  = (el.style.transform || '') + ' translateY(-24px)';
                setTimeout(function () { if (el.parentNode) el.remove(); }, 320);
                break;
            case 'slide_down':
                el.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                el.style.opacity    = '0';
                el.style.transform  = (el.style.transform || '') + ' translateY(24px)';
                setTimeout(function () { if (el.parentNode) el.remove(); }, 320);
                break;
            default:
                if (el.parentNode) el.remove();
                break;
        }
    }

    // ---- Overlay scheduling ----
    function _scheduleOverlays(overlays, durationMs) {
        overlays.forEach(function (ov) {
            var showAt = ov.start_ms   != null ? ov.start_ms                  : 0;
            var hideAt = ov.duration_ms != null ? showAt + ov.duration_ms : durationMs;

            var h1 = setTimeout(function () {
                if (_state !== 'playing') return;
                var el = _makeOverlayEl(ov);
                _overlayLayer.appendChild(el);
                _applyTextIn(el, ov.effect_name, ov.effect_params);
            }, showAt);
            _overlayTimers.push(h1);

            var h2 = setTimeout(function () {
                _overlayLayer
                    .querySelectorAll('[data-text-id="' + ov.text_id + '"]')
                    .forEach(function (e) { _applyTextOut(e, ov.effect_name); });
            }, hideAt);
            _overlayTimers.push(h2);
        });
    }

    function _makeOverlayEl(ov) {
        var el = document.createElement('div');
        el.className           = 'overlay-text';
        el.dataset.textId      = ov.text_id;
        el.dataset.fullContent = ov.content;
        el.textContent         = ov.content;
        if (ov.align)       el.style.textAlign = ov.align;
        if (ov.style_class) el.classList.add('style-' + ov.style_class);
        _positionOverlay(el, ov);
        return el;
    }

    // ---- Clear helpers ----
    function _clearTimers() {
        if (_rafHandle)   { cancelAnimationFrame(_rafHandle); _rafHandle = null; }
        if (_itemTimer)   { clearTimeout(_itemTimer);  _itemTimer  = null; }
        if (_outTimer)    { clearTimeout(_outTimer);   _outTimer   = null; }
        if (_freezeTimer) { clearTimeout(_freezeTimer); _freezeTimer = null; }
        if (_resumeTimer) { clearTimeout(_resumeTimer); _resumeTimer = null; }
        _overlayTimers.forEach(function (h) { clearTimeout(h); });
        _overlayTimers = [];
    }

    function _clearMedia() {
        if (_ytPlayer) { try { _ytPlayer.stopVideo(); } catch (e) {} _ytPlayer = null; }
        _mediaLayer.innerHTML   = '';
        _overlayLayer.innerHTML = '';
    }

    // ---- YouTube ----
    function _parseYouTubeId(url) {
        var m;
        m = url.match(/youtu\.be\/([A-Za-z0-9_-]{11})/);    if (m) return m[1];
        m = url.match(/[?&]v=([A-Za-z0-9_-]{11})/);          if (m) return m[1];
        m = url.match(/embed\/([A-Za-z0-9_-]{11})/);          if (m) return m[1];
        return url;
    }

    function _loadYouTubeApi(cb) {
        _ytCallbacks.push(cb);
        if (_ytApiLoading) return;
        _ytApiLoading = true;
        var prev = window.onYouTubeIframeAPIReady;
        window.onYouTubeIframeAPIReady = function () {
            if (prev) prev();
            _ytCallbacks.splice(0).forEach(function (fn) { fn(); });
        };
        var s  = document.createElement('script');
        s.src  = 'https://www.youtube.com/iframe_api';
        document.head.appendChild(s);
    }

    function _renderYouTube(item, onActuallyPlaying) {
        // wrapper: fixed-size crop frame, controls opacity.
        // zoomTarget: inner div that receives CSS transforms (zoom/pan).
        // YT.Player replaces target (inside zoomTarget) with an <iframe>.
        var wrapper = document.createElement('div');
        wrapper.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;overflow:hidden;opacity:0;transition:opacity 0.2s ease;';
        _mediaLayer.appendChild(wrapper);

        var zoomTarget = document.createElement('div');
        zoomTarget.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;';
        wrapper.appendChild(zoomTarget);

        var target = document.createElement('div');
        target.id  = 'yt-embed';
        target.style.cssText = 'width:100%;height:100%;';
        zoomTarget.appendChild(target);

        var videoId   = _parseYouTubeId(item.src || '');
        var startSec  = item.media_start_s || 0;
        var transName = item.transition_in;
        var _playFired = false;
        var freezeAtMs       = item.yt_freeze_at_s       ? item.yt_freeze_at_s * 1000 : 0;
        var freezeDurationMs = item.yt_freeze_duration_ms || 0;

        function _showWrapper() {
            wrapper.style.opacity = '1';
            _applyTransitionIn(wrapper, transName);
            // Matte: cover everything outside the stage with black strips from
            // _overlayLayer. For same-origin <video> this works; for OOPIF
            // (YouTube) it will only clip if the OOPIF doesn't escape compositing.
            var cw = _overlayLayer.offsetWidth;
            var ch = _overlayLayer.offsetHeight;
            var crop = item.src_crop || null;
            var px, py, pw, ph;
            if (crop) {
                // src_crop is in encoded-video pixels; here we don't know the video
                // dimensions until later, so fall back to full stage if absent.
                px = 0; py = 0; pw = cw; ph = ch;
            } else {
                px = 0; py = 0; pw = cw; ph = ch;
            }
            var strips = [
                {l:0,     t:0,     w:cw,        h:py},
                {l:0,     t:py+ph, w:cw,        h:ch-(py+ph)},
                {l:0,     t:py,    w:px,         h:ph},
                {l:px+pw, t:py,    w:cw-(px+pw), h:ph},
            ];
            strips.forEach(function(r) {
                if (r.w <= 0 || r.h <= 0) return;
                var d = document.createElement('div');
                d.style.cssText = 'position:absolute;background:#000;pointer-events:none;' +
                                  'left:' + r.l + 'px;top:' + r.t + 'px;' +
                                  'width:' + r.w + 'px;height:' + r.h + 'px;';
                _overlayLayer.appendChild(d);
            });
        }

        function _startEffect() {
            if (!item.effect_name) return;
            var effectFn = _makeYTEffectFn(item.effect_name, item.effect_params || {}, zoomTarget);
            if (!effectFn) return;
            var _effT0  = performance.now();
            var _effDur = item.duration_ms || 5000;
            var _effLoop = function () {
                if (_state !== 'playing') return;
                effectFn((performance.now() - _effT0) / _effDur);
                _rafHandle = requestAnimationFrame(_effLoop);
            };
            _rafHandle = requestAnimationFrame(_effLoop);
        }

        // Fallback: if PLAYING never fires within 1s (e.g. slow network),
        // show the wrapper and start the timer anyway.
        var _fallbackTimer = setTimeout(function () {
            if (!_playFired) {
                _playFired = true;
                _showWrapper();
                _startEffect();
                if (onActuallyPlaying) onActuallyPlaying();
            }
        }, 1000);

        function _create() {
            _ytPlayer = new YT.Player(target, {   // eslint-disable-line no-undef
                videoId:    videoId,
                width:      '100%',
                height:     '100%',
                playerVars: { autoplay: 1, mute: 1, start: Math.floor(startSec), controls: 0, modestbranding: 1, rel: 0 },
                events: {
                    onReady: function (e) {
                        e.target.playVideo();
                    },
                    onStateChange: function (e) {
                        // Show the player and start the duration timer on the first
                        // PLAYING event. mute:1 ensures autoplay works without Chrome
                        // flags; we unmute immediately once playing.
                        if (e.data === YT.PlayerState.PLAYING && !_playFired) {  // eslint-disable-line no-undef
                            _playFired = true;
                            clearTimeout(_fallbackTimer);
                            e.target.unMute();
                            _showWrapper();
                            _startEffect();
                            // Freeze: pause at freeze_at_s, hold, then resume
                            if (freezeAtMs > 0 && freezeDurationMs > 0) {
                                _freezeTimer = setTimeout(function () {
                                    try { e.target.pauseVideo(); } catch (_) {}
                                    _resumeTimer = setTimeout(function () {
                                        try { e.target.playVideo(); } catch (_) {}
                                    }, freezeDurationMs);
                                }, freezeAtMs);
                            }
                            if (onActuallyPlaying) onActuallyPlaying();
                        }
                    },
                }
            });
        }

        if (window.YT && window.YT.Player) {
            _create();
        } else {
            _loadYouTubeApi(_create);
        }
    }

    // ---- Render one item ----
    function _renderItem(item) {
        _clearTimers();

        var duration = item.duration_ms || 5000;
        var t0       = performance.now();

        _dbg('item ' + (_itemIndex + 1) + '/' + _show.items.length +
             '  ' + item.item_id + '  ' + item.asset_type +
             '  dur=' + duration + 'ms  effect=' + (item.effect_name || 'none'));

        var effectFn = null;

        if (item.asset_type === 'youtube') {
            // Keep old clip visible while the new one loads to avoid a black gap.
            // Snapshot old state now; clean up once the new clip starts playing.
            var _oldNodes     = Array.prototype.slice.call(_mediaLayer.children);
            var _oldYtPlayer  = _ytPlayer;
            _ytPlayer = null;
            _overlayLayer.innerHTML = '';
            function _cleanupOld() {
                if (_oldYtPlayer) { try { _oldYtPlayer.stopVideo(); } catch (e) {} }
                _oldNodes.forEach(function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
            }
            _renderYouTube(item, function () {
                _cleanupOld();
                _outTimer  = _scheduleTransitionOut(_mediaLayer, item.transition_out, duration);
                _itemTimer = setTimeout(_advanceItem, duration);
            });
            return;
        }

        _clearMedia();

        if (item.asset_type === 'image') {
            var img       = document.createElement('img');
            img.src       = item.src;
            img.className = 'fit-' + (item.fit_mode || 'cover');
            var txBox     = document.createElement('div');   // receives the CSS transform
            txBox.style.cssText = 'position:absolute;inset:0;';
            txBox.appendChild(img);
            var clipBox   = document.createElement('div');   // GPU layer + overflow clip
            clipBox.style.cssText = 'position:absolute;inset:0;overflow:hidden;transform:translateZ(0);';
            clipBox.appendChild(txBox);
            _mediaLayer.appendChild(clipBox);
            _applyTransitionIn(img, item.transition_in);
            effectFn = _makeMediaEffectFn(item.effect_name, item.effect_params || {}, txBox);
            _outTimer = _scheduleTransitionOut(img, item.transition_out, duration);

        } else if (item.asset_type === 'video') {
            var vid       = document.createElement('video');
            vid.src       = item.src;
            vid.muted     = true;
            vid.style.cssText = 'position:absolute;display:block;border:none;';
            var effectBox = document.createElement('div');
            effectBox.style.cssText = 'position:absolute;inset:0;';
            effectBox.appendChild(vid);
            var clipBox2  = document.createElement('div');
            // Start full-stage size so overflow:hidden clips the video from frame 1.
            // loadedmetadata will tighten this to the crop rect.
            clipBox2.style.cssText = 'position:absolute;inset:0;overflow:hidden;transform:translateZ(0);';
            clipBox2.appendChild(effectBox);
            _mediaLayer.appendChild(clipBox2);
            // Hide until loadedmetadata finishes layout so there's no unsized flash.
            vid.style.visibility = 'hidden';
            vid.addEventListener('canplay', function () {
                if (item.media_start_s) vid.currentTime = item.media_start_s;
                vid.play().catch(function () {});
            }, { once: true });
            var _crop2 = item.src_crop || null;
            vid.addEventListener('loadedmetadata', function () {
                var cw    = _mediaLayer.offsetWidth;
                var ch    = _mediaLayer.offsetHeight;
                var encW  = vid.videoWidth;
                var encH  = vid.videoHeight;
                var scale = Math.min(cw / encW, ch / encH);
                var envW  = Math.round(encW * scale);
                var envH  = Math.round(encH * scale);
                var envX  = Math.round((cw - envW) / 2);
                var envY  = Math.round((ch - envH) / 2);
                var px, py, pw, ph;
                if (_crop2) {
                    px = Math.round(envX + _crop2.x * scale);
                    py = Math.round(envY + _crop2.y * scale);
                    pw = Math.round(_crop2.w * scale);
                    ph = Math.round(_crop2.h * scale);
                } else {
                    px = envX; py = envY; pw = envW; ph = envH;
                }
                // Clip box: tightened to picture rect, overflow:hidden clips effects.
                clipBox2.style.cssText = 'position:absolute;overflow:hidden;transform:translateZ(0);' +
                    'left:' + px + 'px;top:' + py + 'px;' +
                    'width:' + pw + 'px;height:' + ph + 'px;';
                // effectBox fills clipBox2 exactly -- effects scale from its center.
                effectBox.style.cssText = 'position:absolute;inset:0;';
                // Video covers the full encoded-frame envelope, offset so that
                // the picture area aligns with (0,0) of effectBox.
                vid.style.cssText = 'position:absolute;display:block;border:none;' +
                    'left:' + (envX - px) + 'px;top:' + (envY - py) + 'px;' +
                    'width:' + envW + 'px;height:' + envH + 'px;';
                vid.style.visibility = '';
                // Matte strips cover letterbox/pillarbox bars and anything outside the crop.
                var strips = [
                    {l:0,     t:0,     w:cw,         h:py},
                    {l:0,     t:py+ph, w:cw,         h:ch-(py+ph)},
                    {l:0,     t:py,    w:px,         h:ph},
                    {l:px+pw, t:py,    w:cw-(px+pw), h:ph},
                ];
                strips.forEach(function(r) {
                    if (r.w <= 0 || r.h <= 0) return;
                    var d = document.createElement('div');
                    d.style.cssText = 'position:absolute;background:#000;pointer-events:none;' +
                                      'left:' + r.l + 'px;top:' + r.t + 'px;' +
                                      'width:' + r.w + 'px;height:' + r.h + 'px;';
                    _overlayLayer.appendChild(d);
                });
                _applyTransitionIn(vid, item.transition_in);
            }, { once: true });
            effectFn  = _makeMediaEffectFn(item.effect_name, item.effect_params || {}, effectBox);
            _outTimer = _scheduleTransitionOut(vid, item.transition_out, duration);
        }

        // rAF effect loop (image/video only)
        if (effectFn) {
            var _loop = function () {
                if (_state !== 'playing') return;
                effectFn((performance.now() - t0) / duration);
                _rafHandle = requestAnimationFrame(_loop);
            };
            _rafHandle = requestAnimationFrame(_loop);
        }

        _scheduleOverlays(item.overlays || [], duration);
        _itemTimer = setTimeout(_advanceItem, duration);
    }

    function _advanceItem() {
        _itemIndex++;
        if (!_show || _itemIndex >= _show.items.length) {
            _clearMedia();
            _state = 'stopped';
            _dbg('show complete');
            return;
        }
        _renderItem(_show.items[_itemIndex]);
    }

    // ---- Public API ----

    return {
        loadShow: function (json) {
            _clearTimers();
            _clearMedia();
            try {
                _show = typeof json === 'string' ? JSON.parse(json) : json;
            } catch (e) {
                console.error('[player] loadShow parse error', e);
                _show = null;
            }
            _itemIndex = 0;
            _state     = 'loaded';
            if (_show && _show.format) _applyFormat(_show.format);
            _dbg('loaded  ' + (_show
                ? (_show.sequence_name + '  items=' + _show.items.length + '  total=' + _show.total_duration_ms + 'ms')
                : 'null'));
            console.log('[player] loadShow', _show);
        },

        playShow: function () {
            if (!_show || _state === 'playing') return;
            _state = 'playing';
            _renderItem(_show.items[_itemIndex]);
        },

        pauseShow: function () {
            if (_state !== 'playing') return;
            _clearTimers();
            if (_ytPlayer) { try { _ytPlayer.pauseVideo(); } catch (e) {} }
            var vid = _mediaLayer.querySelector('video');
            if (vid) vid.pause();
            _state = 'paused';
            _dbg('paused  item=' + _itemIndex);
        },

        stopShow: function () {
            _clearTimers();
            _clearMedia();
            _itemIndex = 0;
            _state     = 'stopped';
            _dbg('stopped');
        },

        goToItem: function (index) {
            if (!_show) return;
            _itemIndex = Math.max(0, Math.min(index, _show.items.length - 1));
            if (_state === 'playing') _renderItem(_show.items[_itemIndex]);
            _dbg('at item ' + _itemIndex);
        },

        getShowStatus: function () {
            return {
                state:    _state,
                item:     _itemIndex,
                total:    _show ? _show.items.length : 0,
                sequence: _show ? _show.sequence_name : null,
            };
        },

        // Returns the stage's DOMRect (viewport coordinates and pixel dimensions).
        // Use this to find out the actual rendered size of the player at any moment.
        getStageRect: function () {
            return _stage.getBoundingClientRect();
        },
    };

};  // end createPlayer

// ---- Default page instance (CDP bridge) ----
// index.html provides a single <div id="player-host"> as the mount point.
// This block creates the instance and binds the API to window globals so
// Python/CDP Runtime.evaluate calls (window.loadShow etc.) continue to work.
(function () {
    var host = document.getElementById('player-host');
    if (!host) return;
    var _p = window.createPlayer(host);
    window.loadShow      = function (j) { return _p.loadShow(j); };
    window.playShow      = function ()  { return _p.playShow(); };
    window.pauseShow     = function ()  { return _p.pauseShow(); };
    window.stopShow      = function ()  { return _p.stopShow(); };
    window.goToItem      = function (n) { return _p.goToItem(n); };
    window.getShowStatus = function ()  { return _p.getShowStatus(); };
    window.getStageRect  = function ()  { return _p.getStageRect(); };
}());

