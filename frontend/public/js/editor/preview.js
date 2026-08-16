/**
 * Canvas Preview Module
 * Handles rendering scenes to canvas for real-time preview
 */

// Stop-words filtered out in emphasis display mode
const _EMPHASIS_STOP_WORDS = new Set([
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'am', 'do', 'does', 'did', 'has', 'have', 'had', 'having',
    'i', 'me', 'my', 'we', 'our', 'you', 'your', 'he', 'she', 'it',
    'him', 'her', 'his', 'its', 'they', 'them', 'their',
    'this', 'that', 'these', 'those', 'what', 'which', 'who', 'whom',
    'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from',
    'up', 'out', 'if', 'or', 'and', 'but', 'not', 'no', 'nor',
    'so', 'as', 'just', 'about', 'into', 'than', 'then', 'also',
    'very', 'can', 'will', 'would', 'could', 'should', 'may', 'might',
    'shall', 'must', 'here', 'there', 'when', 'where', 'how', 'all',
    'each', 'both', 'few', 'more', 'most', 'some', 'any', 'such',
    'only', 'own', 'same', 'too', 'still', 'already', 'yet'
]);

// ── Word emphasis: keyword detection ─────────────────────
function _detectEmphasisKeywords(word) {
    const clean = word.replace(/[^a-zA-Z']/g, '').toLowerCase();
    if (clean.length <= 2) return false;
    return !_EMPHASIS_STOP_WORDS.has(clean);
}

// ── Word emphasis presets ────────────────────────────────
// Each preset has:
//   apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx, canvasW, canvasH)
//   detectWords(word) → boolean (optional, defaults to _detectEmphasisKeywords)
const WORD_EMPHASIS_PRESETS = {
    color_pop: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx) {
            const colors = ['#FF6B6B', '#4ECDC4', '#FFB347', '#A78BFA', '#56CCF2', '#26DE81', '#FF8ED4'];
            ctx.fillStyle = colors[wordIdx % colors.length];
            ctx.font = `700 ${fontSize * 1.05}px "${fontFamily}", sans-serif`;
            ctx.fillText(word, x, y);
        }
    },
    scale_burst: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx, W, H) {
            const wordPhase = (progress * 3 + wordIdx * 0.15) % 1;
            const scale = wordPhase < 0.1 ? 1 + 0.3 * (wordPhase / 0.1) : wordPhase < 0.2 ? 1.3 - 0.3 * ((wordPhase - 0.1) / 0.1) : 1;
            ctx.fillStyle = '#FFB347';
            ctx.font = `700 ${fontSize * scale}px "${fontFamily}", sans-serif`;
            const yOff = (1 - scale) * fontSize * 0.3;
            ctx.fillText(word, x, y + yOff);
        }
    },
    wave: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx) {
            const wave = Math.sin(progress * Math.PI * 6 + wordIdx * 0.8) * fontSize * 0.12;
            ctx.fillStyle = '#4ECDC4';
            ctx.font = `${fontWeight} ${fontSize}px "${fontFamily}", sans-serif`;
            ctx.fillText(word, x, y + wave);
        }
    },
    glow_color: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx) {
            const colors = ['#FF6B6B', '#4ECDC4', '#A78BFA', '#FFB347'];
            const color = colors[wordIdx % colors.length];
            ctx.shadowColor = color;
            ctx.shadowBlur = 12 + Math.sin(progress * Math.PI * 4 + wordIdx) * 6;
            ctx.fillStyle = color;
            ctx.font = `700 ${fontSize}px "${fontFamily}", sans-serif`;
            ctx.fillText(word, x, y);
            ctx.shadowBlur = 0;
        }
    },
    shake_word: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx) {
            const shakeX = Math.sin(progress * 80 + wordIdx * 7) * 2;
            const shakeY = Math.cos(progress * 60 + wordIdx * 5) * 1.5;
            ctx.fillStyle = '#FF6B6B';
            ctx.font = `700 ${fontSize}px "${fontFamily}", sans-serif`;
            ctx.fillText(word, x + shakeX, y + shakeY);
        }
    },
    typewriter_word: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx) {
            // Each emphasized word fades in sequentially
            const wordDelay = wordIdx * 0.08;
            const wordProgress = Math.max(0, Math.min(1, (progress - wordDelay) * 5));
            const chars = Math.floor(word.length * wordProgress);
            const visible = word.slice(0, chars);
            ctx.fillStyle = '#4ECDC4';
            ctx.font = `700 ${fontSize}px "${fontFamily}", sans-serif`;
            ctx.fillText(visible, x, y);
            // Cursor blink
            if (chars < word.length && Math.sin(progress * 30) > 0) {
                const cursorX = x + ctx.measureText(visible).width;
                ctx.fillRect(cursorX, y - fontSize * 0.4, 2, fontSize * 0.8);
            }
        }
    },
    split_color: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx) {
            // Top half one color, bottom half another — simulated by drawing twice with clipping
            const mid = Math.floor(word.length / 2);
            const topWord = word.slice(0, mid);
            const botWord = word.slice(mid);
            ctx.font = `700 ${fontSize}px "${fontFamily}", sans-serif`;
            ctx.fillStyle = '#FF6B6B';
            ctx.fillText(topWord, x, y);
            const topW = ctx.measureText(topWord).width;
            ctx.fillStyle = '#4ECDC4';
            ctx.fillText(botWord, x + topW, y);
        }
    },
    bounce_word: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx) {
            const bouncePhase = (progress * 4 + wordIdx * 0.2) % 1;
            const bounceY = bouncePhase < 0.3 ? -Math.sin(bouncePhase / 0.3 * Math.PI) * fontSize * 0.2 : 0;
            const scale = bouncePhase < 0.3 ? 1 + 0.1 * Math.sin(bouncePhase / 0.3 * Math.PI) : 1;
            ctx.fillStyle = '#FFB347';
            ctx.font = `700 ${fontSize * scale}px "${fontFamily}", sans-serif`;
            ctx.fillText(word, x, y + bounceY);
        }
    },
    fade_stagger: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx) {
            const delay = wordIdx * 0.06;
            const alpha = Math.max(0, Math.min(1, (progress - delay) * 4));
            ctx.globalAlpha *= alpha;
            ctx.fillStyle = '#A78BFA';
            ctx.font = `700 ${fontSize * 1.05}px "${fontFamily}", sans-serif`;
            ctx.fillText(word, x, y);
        }
    },
    rise_word: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx) {
            const delay = wordIdx * 0.05;
            const wp = Math.max(0, Math.min(1, (progress - delay) * 3));
            const riseY = (1 - wp) * fontSize * 0.5;
            ctx.globalAlpha *= wp;
            ctx.fillStyle = '#56CCF2';
            ctx.font = `700 ${fontSize}px "${fontFamily}", sans-serif`;
            ctx.fillText(word, x, y + riseY);
        }
    },
    underline_sweep: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx) {
            ctx.fillStyle = '#FFB347';
            ctx.font = `700 ${fontSize}px "${fontFamily}", sans-serif`;
            ctx.fillText(word, x, y);
            // Animated underline sweep
            const wordW = ctx.measureText(word).width;
            const sweepW = wordW * Math.min(1, progress * 3);
            ctx.fillStyle = '#FFB347';
            ctx.fillRect(x, y + fontSize * 0.45, sweepW, 2);
        }
    },
    disintegrate: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx) {
            // Draw each character with random offset that increases over time
            ctx.font = `700 ${fontSize}px "${fontFamily}", sans-serif`;
            let cx = x;
            for (let i = 0; i < word.length; i++) {
                const charProgress = Math.max(0, progress - 0.6); // starts disintegrating at 60%
                const scatter = charProgress * 30;
                const dx = (Math.sin(i * 7.3 + progress * 20) * scatter);
                const dy = (Math.cos(i * 5.1 + progress * 15) * scatter) - charProgress * fontSize * 0.5;
                const alpha = Math.max(0, 1 - charProgress * 3);
                ctx.globalAlpha = alpha * (ctx.globalAlpha || 1);
                ctx.fillStyle = '#FF6B6B';
                ctx.fillText(word[i], cx + dx, y + dy);
                ctx.globalAlpha = 1;
                cx += ctx.measureText(word[i]).width;
            }
        }
    },
    neon: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx) {
            const colors = ['#FF6B6B', '#4ECDC4', '#A78BFA', '#FF8ED4'];
            const color = colors[wordIdx % colors.length];
            const pulse = 8 + Math.sin(progress * Math.PI * 6 + wordIdx * 1.2) * 8;
            ctx.shadowColor = color;
            ctx.shadowBlur = pulse;
            ctx.fillStyle = '#ffffff';
            ctx.font = `700 ${fontSize}px "${fontFamily}", sans-serif`;
            ctx.fillText(word, x, y);
            // Double draw for stronger glow
            ctx.fillStyle = color;
            ctx.globalAlpha *= 0.4;
            ctx.fillText(word, x, y);
            ctx.shadowBlur = 0;
        }
    },
    bold_highlight: {
        detectWords: _detectEmphasisKeywords,
        apply(ctx, word, x, y, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx) {
            // Draw highlight box behind word
            ctx.font = `700 ${fontSize * 1.05}px "${fontFamily}", sans-serif`;
            const wordW = ctx.measureText(word).width;
            const pad = 4;
            ctx.fillStyle = 'rgba(78, 205, 196, 0.25)';
            ctx.fillRect(x - pad, y - fontSize * 0.45, wordW + pad * 2, fontSize * 0.9);
            ctx.fillStyle = '#4ECDC4';
            ctx.fillText(word, x, y);
        }
    },
};

function _extractEmphasisWords(text) {
    if (!text) return '';
    const words = text.split(/\s+/);
    const kept = words.filter(w => {
        const clean = w.replace(/[^a-zA-Z]/g, '').toLowerCase();
        return clean.length > 0 && !_EMPHASIS_STOP_WORDS.has(clean);
    });
    return kept.length > 0 ? kept.join(' ') : text;
}

export class CanvasPreview {
    constructor(canvas, options = {}) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.width = canvas.width;
        this.height = canvas.height;

        this.scenes = [];
        this.currentTime = 0;
        this.isPlaying = false;
        this.lastFrameTime = 0;
        this.animationId = null;

        this.onTimeUpdate = options.onTimeUpdate || (() => { });
        this.onPlaybackEnd = options.onPlaybackEnd || (() => { });

        // Caption overlay
        this.captions = [];
        this.captionStyle = {};

        // Image cache
        this.imageCache = new Map();

        // Project base path for loading assets
        this.projectBasePath = '';

        // Background color
        this.backgroundColor = '#000000';

        // Overlay image cache (keyed by URL)
        this.overlayCache = new Map();

        // Stacked overlays — ordered array of URLs (bottom → top)
        this.activeOverlays = [];
        this.activeOverlayImgs = [];

        // Disabled tracks set — synced from EditorState
        this.disabledTracks = new Set();

        // Video embedded audio — muted by default, can be toggled
        this.videoAudioEnabled = false;
    }

    /**
     * Set project base path for loading text backgrounds
     */
    setProjectPath(basePath) {
        this.projectBasePath = basePath;
    }

    /**
     * Set the global overlay (applied to entire timeline).
     * Accepts a single URL string (legacy), an array of URLs, or an array of
     * {url, opacity, blend} objects (stacked, bottom → top).
     * Pass null/empty to remove all.
     */
    setOverlay(urlOrArray) {
        // Normalise to array of {url, opacity, blend}
        if (!urlOrArray || (Array.isArray(urlOrArray) && urlOrArray.length === 0)) {
            this.activeOverlays = [];
            this.activeOverlayImgs = [];
            this.overlayEntries = [];
            // Legacy compat
            this.activeOverlay = null;
            this.activeOverlayImg = null;
            this.render();
            return;
        }
        const entries = Array.isArray(urlOrArray) ? urlOrArray : [urlOrArray];
        // Normalise each entry to {url, opacity, blend}
        this.overlayEntries = entries.map(e => {
            if (typeof e === 'string') return { url: e, opacity: 1.0, blend: 'normal' };
            return { url: e.url || '', opacity: e.opacity ?? 1.0, blend: e.blend || 'normal' };
        });
        const urls = this.overlayEntries.map(e => e.url);
        this.activeOverlays = urls;
        this.activeOverlayImgs = new Array(urls.length).fill(null);
        // Legacy compat (first overlay)
        this.activeOverlay = urls[0] || null;
        this.activeOverlayImg = null;

        let loaded = 0;
        urls.forEach((url, i) => {
            if (this.overlayCache.has(url)) {
                this.activeOverlayImgs[i] = this.overlayCache.get(url);
                loaded++;
                if (loaded === urls.length) {
                    this.activeOverlayImg = this.activeOverlayImgs[0] || null;
                    this.render();
                }
                return;
            }
            const img = new Image();
            img.onload = () => {
                this.overlayCache.set(url, img);
                this.activeOverlayImgs[i] = img;
                loaded++;
                if (loaded === urls.length) {
                    this.activeOverlayImg = this.activeOverlayImgs[0] || null;
                    this.render();
                }
            };
            img.onerror = () => {
                console.warn('Failed to load overlay:', url);
                loaded++;
                if (loaded === urls.length) this.render();
            };
            img.src = url;
        });
    }

    /**
     * Render global overlay stack on top of current frame (full canvas, preserving alpha).
     * Applies per-overlay opacity and blend mode.
     */
    renderOverlay() {
        const entries = this.overlayEntries || [];
        for (let i = 0; i < this.activeOverlayImgs.length; i++) {
            const img = this.activeOverlayImgs[i];
            if (!img) continue;
            const entry = entries[i] || {};
            const opacity = entry.opacity ?? 1.0;
            const blend = entry.blend || 'normal';

            this.ctx.save();
            this.ctx.globalAlpha = opacity;
            this.ctx.globalCompositeOperation = blend === 'normal' ? 'source-over' : blend;
            this.ctx.drawImage(img, 0, 0, this.width, this.height);
            this.ctx.restore();
        }
    }

    /**
     * Set scenes for preview.
     * Returns a Promise that resolves once all media is preloaded and the
     * first frame has been rendered.  Callers that need assets ready before
     * proceeding (e.g. the loading-overlay flow) can `await` this.
     */
    setScenes(scenes) {
        this.scenes = scenes;
        this._preloadPromise = this.preloadImages().then(() => {
            this.render();
        });
        return this._preloadPromise;
    }

    /**
     * Wait for any in-flight preload kicked off by setScenes().
     * Resolves immediately if nothing is loading.
     */
    waitForPreload() {
        return this._preloadPromise || Promise.resolve();
    }

    /**
     * Preload all scene media (images and videos)
     */
    async preloadImages() {
        const TIMEOUT = 10000;
        for (const scene of this.scenes) {
            if (scene.mediaUrl && !this.imageCache.has(scene.id)) {
                const ext = (scene.mediaUrl || '').split('.').pop().toLowerCase();
                const isVid = scene.isVideo || ['mp4', 'webm', 'mov'].includes(ext);
                if (isVid) {
                    // Load as <video> element for canvas drawing
                    try {
                        const video = document.createElement('video');
                        video.muted = true;
                        video.playsInline = true;
                        video.preload = 'auto';
                        video.loop = true;
                        if (scene.mediaUrl.startsWith('blob:') || scene.mediaUrl.startsWith('http')) {
                            video.crossOrigin = 'anonymous';
                        }
                        await new Promise((resolve, reject) => {
                            const timer = setTimeout(() => {
                                console.warn(`Preview: Timeout loading video for scene ${scene.id}`);
                                reject(new Error('timeout'));
                            }, TIMEOUT);
                            video.onloadeddata = () => {
                                clearTimeout(timer);
                                resolve();
                            };
                            video.onerror = (e) => {
                                clearTimeout(timer);
                                console.warn(`Preview: Failed to load video for scene ${scene.id}:`, scene.mediaUrl, e);
                                reject(e);
                            };
                            video.src = scene.mediaUrl;
                        });
                        video._isVideo = true;
                        this.imageCache.set(scene.id, video);
                    } catch (error) {
                        console.warn(`Failed to load video for scene ${scene.id}:`, error);
                    }
                } else {
                    const img = new Image();
                    // Only set crossOrigin for non-local URLs (blob: or http:)
                    if (scene.mediaUrl.startsWith('blob:') || scene.mediaUrl.startsWith('http')) {
                        img.crossOrigin = 'anonymous';
                    }
                    try {
                        await new Promise((resolve, reject) => {
                            const timer = setTimeout(() => {
                                console.warn(`Preview: Timeout loading image for scene ${scene.id}`);
                                reject(new Error('timeout'));
                            }, TIMEOUT);
                            img.onload = () => {
                                clearTimeout(timer);
                                resolve();
                            };
                            img.onerror = (e) => {
                                clearTimeout(timer);
                                console.warn(`Preview: Failed to load image for scene ${scene.id}:`, scene.mediaUrl, e);
                                reject(e);
                            };
                            img.src = scene.mediaUrl;
                        });
                        this.imageCache.set(scene.id, img);
                    } catch (error) {
                        console.warn(`Failed to load image for scene ${scene.id}:`, error);
                    }
                }
            }
        }
    }

    /**
     * Get current scene based on playback time
     */
    getCurrentScene() {
        let accumulated = 0;

        for (const scene of this.scenes) {
            if (this.currentTime >= accumulated && this.currentTime < accumulated + scene.duration) {
                return {
                    scene,
                    start: accumulated,
                    end: accumulated + scene.duration,
                    localTime: this.currentTime - accumulated,
                    progress: (this.currentTime - accumulated) / scene.duration
                };
            }
            accumulated += scene.duration;
        }

        return null;
    }

    /**
     * Get total duration of all scenes
     */
    getTotalDuration() {
        const scenesDuration = this.scenes.reduce((sum, scene) => sum + scene.duration, 0);
        return Math.max(scenesDuration, this.overrideDuration || 0);
    }

    /**
     * Set override duration (e.g. for audio)
     */
    setDuration(duration) {
        this.overrideDuration = duration;
    }

    /**
     * Seek to specific time
     */
    seek(time) {
        this.currentTime = Math.max(0, Math.min(time, this.getTotalDuration()));
        this.render();
        this.onTimeUpdate(this.currentTime);
    }

    /**
     * Start playback
     */
    play() {
        if (this.isPlaying) return;

        this.isPlaying = true;
        this.lastFrameTime = performance.now();
        this.tick();
    }

    /**
     * Pause playback
     */
    pause() {
        this.isPlaying = false;
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
        this._pauseAllVideos();
    }

    /**
     * Toggle play/pause
     */
    toggle() {
        if (this.isPlaying) {
            this.pause();
        } else {
            this.play();
        }
        return this.isPlaying;
    }

    /**
     * Set external time source (e.g., audio element)
     */
    setTimeSource(getTime) {
        this.externalTimeSource = getTime;
    }

    /**
     * Animation tick
     */
    tick() {
        if (!this.isPlaying) return;

        // Use external time source if available (e.g., audio element for perfect sync)
        if (this.externalTimeSource) {
            this.currentTime = this.externalTimeSource();
        } else {
            const now = performance.now();
            const delta = (now - this.lastFrameTime) / 1000;
            this.lastFrameTime = now;
            this.currentTime += delta;
        }

        const totalDuration = this.getTotalDuration();
        if (this.currentTime >= totalDuration) {
            this.currentTime = 0;
            this.pause();
            this.onPlaybackEnd();
            this.render();
            return;
        }

        this.render();
        this.onTimeUpdate(this.currentTime);

        this.animationId = requestAnimationFrame(() => this.tick());
    }

    /**
     * Render current frame
     */
    render() {
        // Clear canvas
        this.ctx.fillStyle = this.backgroundColor;
        this.ctx.fillRect(0, 0, this.width, this.height);

        const current = this.getCurrentScene();
        if (!current) return;

        const { scene, progress } = current;
        const img = this.imageCache.get(scene.id);

        // For text scenes, render background + text overlay (unless text track disabled)
        if (scene.type === 'text' || scene.type === 'cta') {
            if (this.disabledTracks.has('text')) {
                this.renderPlaceholder(scene);
            } else {
                this.renderTextScene(scene, current.localTime, progress);
            }
            this.renderOverlay();
            // Captions over text scenes: when hiding is enabled, only suppress
            // captions that *begin* inside this scene. Captions already in
            // flight (started before) keep rendering until they end naturally,
            // so we never cut a caption mid-word.
            if (scene.text_hide_captions === false) {
                this.renderCaptionOverlay(this.currentTime);
            } else {
                this.renderCaptionOverlay(this.currentTime, { suppressStartingAfter: current.start });
            }
            return;
        }

        // For image/video scenes, render media with effects
        if (img) {
            if (img._isVideo) {
                this._syncVideo(img, current.localTime);
                this.renderImage(img, scene.visual_fx || 'static', progress);
            } else {
                this.renderImage(img, scene.visual_fx || 'static', progress);
            }
        } else {
            this.renderPlaceholder(scene);
        }

        this.renderSceneTextOverlay(scene, current.localTime, progress);

        // Transition blending into next scene
        if (scene.transition && scene.transition.type !== 'none' && scene.transition.type !== 'cut' && scene.transition.duration > 0) {
            const transStart = 1.0 - (scene.transition.duration / scene.duration);
            if (progress > transStart) {
                const alpha = (progress - transStart) / (1.0 - transStart); // 0→1
                const trType = scene.transition.type;

                if (trType === 'crossfade') {
                    const nextScene = this._getNextScene();
                    if (nextScene) {
                        const nextMedia = this.imageCache.get(nextScene.id);
                        if (nextMedia) {
                            this.ctx.save();
                            this.ctx.globalAlpha = alpha;
                            if (nextMedia._isVideo) this._syncVideo(nextMedia, 0);
                            this.renderImage(nextMedia, nextScene.visual_fx || 'static', 0);
                            this.ctx.restore();
                        }
                    }
                } else if (trType === 'fade_black') {
                    this.ctx.save();
                    this.ctx.globalAlpha = alpha < 0.5 ? alpha * 2 : 1.0;
                    this.ctx.fillStyle = '#000000';
                    this.ctx.fillRect(0, 0, this.width, this.height);
                    this.ctx.restore();
                    if (alpha > 0.5) {
                        const nextScene = this._getNextScene();
                        if (nextScene) {
                            const nextMedia = this.imageCache.get(nextScene.id);
                            if (nextMedia) {
                                this.ctx.save();
                                this.ctx.globalAlpha = (alpha - 0.5) * 2;
                                if (nextMedia._isVideo) this._syncVideo(nextMedia, 0);
                                this.renderImage(nextMedia, nextScene.visual_fx || 'static', 0);
                                this.ctx.restore();
                            }
                        }
                    }
                } else if (trType === 'fade_white') {
                    this.ctx.save();
                    this.ctx.globalAlpha = alpha < 0.5 ? alpha * 2 : 1.0;
                    this.ctx.fillStyle = '#ffffff';
                    this.ctx.fillRect(0, 0, this.width, this.height);
                    this.ctx.restore();
                    if (alpha > 0.5) {
                        const nextScene = this._getNextScene();
                        if (nextScene) {
                            const nextMedia = this.imageCache.get(nextScene.id);
                            if (nextMedia) {
                                this.ctx.save();
                                this.ctx.globalAlpha = (alpha - 0.5) * 2;
                                if (nextMedia._isVideo) this._syncVideo(nextMedia, 0);
                                this.renderImage(nextMedia, nextScene.visual_fx || 'static', 0);
                                this.ctx.restore();
                            }
                        }
                    }
                } else if (trType === 'slide_left' || trType === 'slide_right' || trType === 'slide_up' || trType === 'slide_down') {
                    const nextScene = this._getNextScene();
                    if (nextScene) {
                        const nextMedia = this.imageCache.get(nextScene.id);
                        if (nextMedia) {
                            const ease = alpha * alpha * (3 - 2 * alpha); // smoothstep
                            // Clear canvas — we'll redraw both scenes at shifted positions
                            this.ctx.clearRect(0, 0, this.width, this.height);
                            this.ctx.save();
                            if (trType === 'slide_left') {
                                this.ctx.translate(-this.width * ease, 0);
                            } else if (trType === 'slide_right') {
                                this.ctx.translate(this.width * ease, 0);
                            } else if (trType === 'slide_up') {
                                this.ctx.translate(0, -this.height * ease);
                            } else {
                                this.ctx.translate(0, this.height * ease);
                            }
                            // Redraw current scene at shifted position
                            if (img) this.renderImage(img, scene.visual_fx || 'static', progress);
                            else this.renderPlaceholder(scene);
                            // Draw next scene adjacent
                            if (trType === 'slide_left') {
                                this.ctx.translate(this.width, 0);
                            } else if (trType === 'slide_right') {
                                this.ctx.translate(-this.width, 0);
                            } else if (trType === 'slide_up') {
                                this.ctx.translate(0, this.height);
                            } else {
                                this.ctx.translate(0, -this.height);
                            }
                            if (nextMedia._isVideo) this._syncVideo(nextMedia, 0);
                            this.renderImage(nextMedia, nextScene.visual_fx || 'static', 0);
                            this.ctx.restore();
                        }
                    }
                } else if (trType === 'wipe_left' || trType === 'wipe_right') {
                    const nextScene = this._getNextScene();
                    if (nextScene) {
                        const nextMedia = this.imageCache.get(nextScene.id);
                        if (nextMedia) {
                            const ease = alpha * alpha * (3 - 2 * alpha);
                            this.ctx.save();
                            if (trType === 'wipe_left') {
                                this.ctx.beginPath();
                                this.ctx.rect(this.width * (1 - ease), 0, this.width * ease, this.height);
                            } else {
                                this.ctx.beginPath();
                                this.ctx.rect(0, 0, this.width * ease, this.height);
                            }
                            this.ctx.clip();
                            if (nextMedia._isVideo) this._syncVideo(nextMedia, 0);
                            this.renderImage(nextMedia, nextScene.visual_fx || 'static', 0);
                            this.ctx.restore();
                        }
                    }
                } else if (trType === 'zoom_in') {
                    const nextScene = this._getNextScene();
                    if (nextScene) {
                        const nextMedia = this.imageCache.get(nextScene.id);
                        if (nextMedia) {
                            const ease = alpha * alpha * (3 - 2 * alpha);
                            const scale = 1 + ease * 0.3; // current scene zooms in
                            this.ctx.save();
                            this.ctx.translate(this.width / 2, this.height / 2);
                            this.ctx.scale(scale, scale);
                            this.ctx.translate(-this.width / 2, -this.height / 2);
                            this.ctx.globalAlpha = 1 - ease;
                            if (img) this.renderImage(img, scene.visual_fx || 'static', progress);
                            this.ctx.restore();
                            // Next scene fades in
                            this.ctx.save();
                            this.ctx.globalAlpha = ease;
                            if (nextMedia._isVideo) this._syncVideo(nextMedia, 0);
                            this.renderImage(nextMedia, nextScene.visual_fx || 'static', 0);
                            this.ctx.restore();
                        }
                    }
                } else if (trType === 'zoom_out') {
                    const nextScene = this._getNextScene();
                    if (nextScene) {
                        const nextMedia = this.imageCache.get(nextScene.id);
                        if (nextMedia) {
                            const ease = alpha * alpha * (3 - 2 * alpha);
                            const scale = 1 - ease * 0.3; // current scene shrinks
                            this.ctx.save();
                            this.ctx.globalAlpha = ease;
                            if (nextMedia._isVideo) this._syncVideo(nextMedia, 0);
                            this.renderImage(nextMedia, nextScene.visual_fx || 'static', 0);
                            this.ctx.restore();
                            // Current scene shrinks on top
                            this.ctx.save();
                            this.ctx.translate(this.width / 2, this.height / 2);
                            this.ctx.scale(scale, scale);
                            this.ctx.translate(-this.width / 2, -this.height / 2);
                            this.ctx.globalAlpha = 1 - ease;
                            if (img) this.renderImage(img, scene.visual_fx || 'static', progress);
                            this.ctx.restore();
                        }
                    }
                }
            }
        }

        // Global overlay layer (between scene and captions)
        this.renderOverlay();

        // Caption overlay on top
        this.renderCaptionOverlay(this.currentTime);
    }

    renderSceneTextOverlay(scene, localTime, progress) {
        const text = (scene.text_content || '').replace(/[^\w\s!?\[\]]/g, '').replace(/  +/g, ' ').trim().toUpperCase();
        if (!text || ['text', 'cta'].includes(scene.type)) {
            this.currentTextScene = null;
            return;
        }

        const start = Math.max(0, Number(scene.text_timeline_offset) || 0);
        const duration = Math.max(0, Number(scene.text_overlay_duration) || (scene.duration - start));
        if (duration <= 0 || localTime < start || localTime > start + duration) {
            this.currentTextScene = null;
            return;
        }

        const overlayProgress = duration > 0 ? Math.max(0, Math.min(1, (localTime - start) / duration)) : progress;

        if (scene.text_background_enabled) {
            this.ctx.fillStyle = scene.text_background_color || '#000000';
            this.ctx.fillRect(0, 0, this.width, this.height);
        }

        this.renderTextOverlay(text, overlayProgress, {
            color: scene.text_color || 'white',
            size: scene.text_size || 72,
            style: scene.font_style || 'bold',
            fontFamily: scene.font_family || 'Inter',
            textAlign: scene.text_align || 'center',
            verticalAlign: scene.vertical_align || 'center',
            textX: scene.text_x,
            textY: scene.text_y,
            displayMode: scene.text_display_mode || 'emphasis',
            animation: scene.text_animation || 'fade',
            emphasis: scene.text_emphasis || 'none'
        });

        this.currentTextScene = scene;
    }

    /**
     * Sync a <video> element to the scene-local time.
     * Plays during playback, pauses+seeks during scrubbing.
     */
    _syncVideo(video, localTime) {
        // Sync muted state based on videoAudioEnabled flag
        video.muted = !this.videoAudioEnabled;

        if (this.isPlaying) {
            if (video.paused) video.play().catch(() => { });
        } else {
            if (!video.paused) video.pause();
            // Only seek if far enough from current (avoid jitter)
            if (Math.abs(video.currentTime - localTime) > 0.1) {
                video.currentTime = localTime % (video.duration || 1);
            }
        }
    }

    /**
     * Enable or disable embedded video audio
     */
    setVideoAudioEnabled(enabled) {
        this.videoAudioEnabled = !!enabled;
        // Update all cached video elements immediately
        for (const [, el] of this.imageCache) {
            if (el._isVideo) {
                el.muted = !this.videoAudioEnabled;
            }
        }
    }

    /**
     * Pause all cached video elements (call on stop/pause)
     */
    _pauseAllVideos() {
        for (const media of this.imageCache.values()) {
            if (media._isVideo && !media.paused) {
                media.pause();
            }
        }
    }

    /**
     * Return a contrasting background color for a given text color.
     */
    _contrastBg(color) {
        if (color === 'white') return '#000000';
        if (color === 'black') return '#ffffff';
        if (!color || !color.startsWith('#')) return '#000000';
        // Parse hex and compute perceived luminance
        const hex = color.length === 4
            ? '#' + color[1] + color[1] + color[2] + color[2] + color[3] + color[3]
            : color;
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
        return lum > 0.5 ? '#000000' : '#ffffff';
    }

    /**
     * Render a text scene using its actual media background when available,
     * or a solid background when explicitly enabled.
     */
    renderTextScene(scene, localTime, progress) {
        const textColor = scene.text_color || 'white';
        const media = this.imageCache.get(scene.id);

        if (scene.text_background_enabled) {
            this.ctx.fillStyle = scene.text_background_color || '#000000';
            this.ctx.fillRect(0, 0, this.width, this.height);
        } else if (media) {
            if (media._isVideo) {
                this._syncVideo(media, localTime);
                this.renderImage(media, scene.visual_fx || 'static', progress);
            } else {
                this.renderImage(media, scene.visual_fx || 'static', progress);
            }
        } else {
            this.ctx.fillStyle = this._contrastBg(textColor);
            this.ctx.fillRect(0, 0, this.width, this.height);
        }

        // Render text on top with fade effect
        let textContent = scene.text_content || scene.script;
        if (textContent) textContent = textContent.replace(/[^\w\s!?\[\]]/g, '').replace(/  +/g, ' ').trim().toUpperCase();
        const start = Math.max(0, Number(scene.text_timeline_offset) || 0);
        const duration = Math.max(0, Number(scene.text_overlay_duration) || (scene.duration - start));
        const showText = !!textContent && duration > 0 && localTime >= start && localTime <= start + duration;

        if (showText) {
            const overlayProgress = duration > 0
                ? Math.max(0, Math.min(1, (localTime - start) / duration))
                : progress;
            this.renderTextOverlay(textContent, overlayProgress, {
                color: textColor,
                size: scene.text_size || 72,
                style: scene.font_style || 'bold',
                fontFamily: scene.font_family || 'Inter',
                textAlign: scene.text_align || 'center',
                verticalAlign: scene.vertical_align || 'center',
                textX: scene.text_x,
                textY: scene.text_y,
                displayMode: scene.text_display_mode || 'emphasis',
                animation: scene.text_animation || 'fade',
                emphasis: scene.text_emphasis || 'none'
            });
        }

        // Store current scene for drag reference
        this.currentTextScene = showText ? scene : null;
    }

    /**
     * Render text overlay with specified options
     * @param {string} text - Text to render
     * @param {number} progress - Animation progress (0-1)
     * @param {object|string} options - Text options or legacy textColor string
     */
    renderTextOverlay(text, progress, options = {}) {
        // Support legacy string parameter for backward compatibility
        if (typeof options === 'string') {
            options = { color: options };
        }

        const displayMode = options.displayMode || 'emphasis';
        const animation = options.animation || 'fade';
        const textColor = options.color || 'white';
        const textSize = options.size || 48;
        const fontStyle = options.style || 'bold';
        const fontFamily = options.fontFamily || 'Inter';
        const textAlign = options.textAlign || 'center';
        const verticalAlign = options.verticalAlign || 'center';
        // Custom position (0-100 percentage, null means use alignment)
        const textX = options.textX;
        const textY = options.textY;

        // Apply display mode — emphasis filters out stop words
        if (displayMode === 'emphasis') {
            text = _extractEmphasisWords(text);
        }

        // Clean text: strip special chars (keep letters, numbers, spaces, ! ? [ ]) and uppercase
        text = text.replace(/[^\w\s!?\[\]]/g, '').replace(/  +/g, ' ').trim().toUpperCase();

        this.ctx.save();

        // Apply animation based on type
        this._applyTextAnimation(animation, progress);

        // Text styling — support named presets and arbitrary hex
        this.ctx.fillStyle = textColor === 'white' ? '#ffffff'
            : textColor === 'black' ? '#000000'
            : textColor.startsWith('#') ? textColor : '#ffffff';
        this.ctx.textBaseline = 'middle';

        // Calculate font size - support both pixel values and legacy string values
        let baseFontSize;
        if (typeof textSize === 'number') {
            // Pixel value - scale relative to canvas (canvas is 1080x1920, scale accordingly)
            baseFontSize = textSize * (this.height / 1920);
        } else {
            // Legacy string value for backward compatibility
            const sizeMultipliers = {
                small: 0.6,
                medium: 1.0,
                large: 1.4,
                xlarge: 1.8
            };
            const sizeMultiplier = sizeMultipliers[textSize] || 1.0;
            baseFontSize = Math.min(48, this.height / 10) * sizeMultiplier;
        }

        // Build font string based on style
        let fontWeight = '400';  // normal
        let fontStyleStr = 'normal';

        switch (fontStyle) {
            case 'bold':
                fontWeight = '700';
                break;
            case 'light':
                fontWeight = '300';
                break;
            case 'italic':
                fontStyleStr = 'italic';
                break;
            case 'bold-italic':
                fontWeight = '700';
                fontStyleStr = 'italic';
                break;
            case 'normal':
            default:
                fontWeight = '400';
                break;
        }

        const fontString = `${fontStyleStr} ${fontWeight} ${baseFontSize}px "${fontFamily}", sans-serif`;

        // Word wrap the text
        const maxWidth = this.width * 0.9; // 90% of canvas width
        const lines = this.wrapText(text, maxWidth, baseFontSize, fontString);
        const lineHeight = baseFontSize * 1.3;
        const totalHeight = lines.length * lineHeight;

        // Calculate position - use custom position if set, otherwise use alignment
        let finalX, finalY;

        if (textX !== null && textX !== undefined) {
            // Custom position: percentage (0-100) of canvas
            finalX = (textX / 100) * this.width;
            this.ctx.textAlign = 'center'; // Always center-align when using custom position
        } else {
            // Use text alignment
            this.ctx.textAlign = textAlign;
            switch (textAlign) {
                case 'left':
                    finalX = this.width * 0.05; // 5% padding from left
                    break;
                case 'right':
                    finalX = this.width * 0.95; // 5% padding from right
                    break;
                case 'center':
                default:
                    finalX = this.width / 2;
                    break;
            }
        }

        if (textY !== null && textY !== undefined) {
            // Custom position: percentage (0-100) of canvas
            finalY = (textY / 100) * this.height;
        } else {
            // Use vertical alignment
            switch (verticalAlign) {
                case 'top':
                    finalY = lineHeight / 2 + (this.height * 0.05); // 5% padding from top
                    break;
                case 'bottom':
                    finalY = this.height - totalHeight + lineHeight / 2 - (this.height * 0.05); // 5% padding from bottom
                    break;
                case 'center':
                default:
                    finalY = (this.height - totalHeight) / 2 + lineHeight / 2;
                    break;
            }
        }

        // Store text bounds for hit testing (used for dragging)
        this.lastTextBounds = {
            x: finalX,
            y: finalY,
            width: maxWidth,
            height: totalHeight,
            lines: lines,
            lineHeight: lineHeight
        };

        // Draw each line — with word emphasis if configured
        const emphasis = options.emphasis || 'none';
        this.ctx.font = fontString;

        if (emphasis !== 'none') {
            this._drawLinesWithEmphasis(lines, finalX, finalY, lineHeight, baseFontSize, fontString, fontWeight, fontFamily, textColor, emphasis, progress);
        } else {
            lines.forEach((line, index) => {
                this.ctx.fillText(line, finalX, finalY + index * lineHeight);
            });
        }

        this.ctx.restore();
    }

    /**
     * Draw text lines with per-word emphasis effects.
     */
    _drawLinesWithEmphasis(lines, x, y, lineHeight, fontSize, fontString, fontWeight, fontFamily, baseColor, emphasis, progress) {
        const emphasisDef = WORD_EMPHASIS_PRESETS[emphasis];
        if (!emphasisDef) {
            lines.forEach((line, i) => this.ctx.fillText(line, x, y + i * lineHeight));
            return;
        }

        // Detect which words should be emphasized
        const emphasisWords = emphasisDef.detectWords || _detectEmphasisKeywords;

        lines.forEach((line, lineIdx) => {
            const words = line.split(/(\s+)/);
            const lineY = y + lineIdx * lineHeight;

            // Measure full line width for centering
            this.ctx.font = fontString;
            const fullWidth = this.ctx.measureText(line).width;
            const align = this.ctx.textAlign;
            let cursorX;
            if (align === 'center') cursorX = x - fullWidth / 2;
            else if (align === 'right') cursorX = x - fullWidth;
            else cursorX = x;

            // Save text align and switch to left for word-by-word
            const origAlign = this.ctx.textAlign;
            this.ctx.textAlign = 'left';

            words.forEach((word, wordIdx) => {
                if (!word.trim()) {
                    // whitespace — just advance
                    this.ctx.font = fontString;
                    cursorX += this.ctx.measureText(word).width;
                    return;
                }

                const isEmphasized = emphasisWords(word);

                if (isEmphasized) {
                    this.ctx.save();
                    emphasisDef.apply(this.ctx, word, cursorX, lineY, fontSize, fontWeight, fontFamily, baseColor, progress, wordIdx, this.width, this.height);
                    this.ctx.restore();
                } else {
                    this.ctx.font = fontString;
                    this.ctx.fillStyle = baseColor.startsWith('#') ? baseColor : '#ffffff';
                    this.ctx.fillText(word, cursorX, lineY);
                }

                this.ctx.font = fontString;
                cursorX += this.ctx.measureText(word).width;
            });

            this.ctx.textAlign = origAlign;
        });
    }

    /**
     * Apply animation transform/alpha to the canvas context.
     * Called inside renderTextOverlay before text is drawn.
     * @param {string} animation - Animation type
     * @param {number} progress - 0-1 progress through the scene
     */
    _applyTextAnimation(animation, progress) {
        switch (animation) {
            case 'fade': {
                const fadeIn = Math.min(1, progress * 4);
                const fadeOut = Math.min(1, (1 - progress) * 4);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                break;
            }
            case 'flicker': {
                // Glitch flicker — rapid alpha oscillation during entry
                const fadeIn = Math.min(1, progress * 5);
                const fadeOut = Math.min(1, (1 - progress) * 4);
                let alpha = Math.min(fadeIn, fadeOut);
                if (progress < 0.2) {
                    // Flicker during first 20%
                    const flickerPhase = Math.sin(progress * 80) * 0.5 + 0.5;
                    alpha *= flickerPhase;
                }
                this.ctx.globalAlpha = alpha;
                break;
            }
            case 'slam': {
                // Scale slam — overshoots then settles
                const fadeOut = Math.min(1, (1 - progress) * 4);
                let scale = 1;
                if (progress < 0.15) {
                    // Scale from 3x down to 1x with overshoot
                    const t = progress / 0.15;
                    scale = 3 - 2 * t;
                } else if (progress < 0.25) {
                    const t = (progress - 0.15) / 0.1;
                    scale = 1 + 0.08 * Math.sin(t * Math.PI);
                }
                this.ctx.globalAlpha = fadeOut;
                this.ctx.translate(this.width / 2, this.height / 2);
                this.ctx.scale(scale, scale);
                this.ctx.translate(-this.width / 2, -this.height / 2);
                break;
            }
            case 'typewriter': {
                // Reveal effect — we fade in progressively, fade out at end
                const fadeOut = Math.min(1, (1 - progress) * 4);
                const reveal = Math.min(1, progress * 3);
                this.ctx.globalAlpha = reveal * fadeOut;
                break;
            }
            case 'rise': {
                // Float upward with fade
                const fadeIn = Math.min(1, progress * 4);
                const fadeOut = Math.min(1, (1 - progress) * 4);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                const offsetY = progress < 0.25
                    ? (1 - progress / 0.25) * this.height * 0.05
                    : 0;
                this.ctx.translate(0, offsetY);
                break;
            }
            case 'bounce': {
                // Playful bounce-in
                const fadeOut = Math.min(1, (1 - progress) * 4);
                let scale = 1;
                if (progress < 0.1) {
                    scale = progress / 0.1;
                } else if (progress < 0.2) {
                    const t = (progress - 0.1) / 0.1;
                    scale = 1 + 0.2 * Math.sin(t * Math.PI);
                } else if (progress < 0.3) {
                    const t = (progress - 0.2) / 0.1;
                    scale = 1 + 0.08 * Math.sin(t * Math.PI);
                }
                this.ctx.globalAlpha = fadeOut;
                this.ctx.translate(this.width / 2, this.height / 2);
                this.ctx.scale(scale, scale);
                this.ctx.translate(-this.width / 2, -this.height / 2);
                break;
            }
            case 'glow_pulse': {
                // Soft glow pulse — gentle alpha oscillation
                const fadeIn = Math.min(1, progress * 4);
                const fadeOut = Math.min(1, (1 - progress) * 4);
                const pulse = 0.85 + 0.15 * Math.sin(progress * Math.PI * 6);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut) * pulse;
                break;
            }
            case 'hard_cut': {
                // Instant appear/disappear
                this.ctx.globalAlpha = (progress > 0.02 && progress < 0.98) ? 1 : 0;
                break;
            }
            case 'scale_pop': {
                // Pop in with scale overshoot
                const fadeOut = Math.min(1, (1 - progress) * 4);
                let scale = 1;
                if (progress < 0.1) {
                    scale = (progress / 0.1) * 1.15;
                } else if (progress < 0.2) {
                    const t = (progress - 0.1) / 0.1;
                    scale = 1.15 - 0.15 * t;
                }
                this.ctx.globalAlpha = fadeOut;
                this.ctx.translate(this.width / 2, this.height / 2);
                this.ctx.scale(scale, scale);
                this.ctx.translate(-this.width / 2, -this.height / 2);
                break;
            }
            case 'slide_up': {
                // Slide in from below
                const fadeIn = Math.min(1, progress * 5);
                const fadeOut = Math.min(1, (1 - progress) * 4);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                const offsetY = progress < 0.2
                    ? (1 - progress / 0.2) * this.height * 0.15
                    : 0;
                this.ctx.translate(0, offsetY);
                break;
            }
            case 'blur_in': {
                // Simulate blur via alpha ramp (canvas has no native blur for text)
                const fadeIn = Math.min(1, progress * 6);
                const fadeOut = Math.min(1, (1 - progress) * 4);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                // Slight scale to simulate de-blur
                if (progress < 0.15) {
                    const t = progress / 0.15;
                    const s = 1.04 - 0.04 * t;
                    this.ctx.translate(this.width / 2, this.height / 2);
                    this.ctx.scale(s, s);
                    this.ctx.translate(-this.width / 2, -this.height / 2);
                }
                break;
            }
            case 'movie_title': {
                // Cinematic movie title — slow scale up with letterbox fade
                const fadeIn = Math.min(1, progress * 2.5);
                const fadeOut = Math.min(1, (1 - progress) * 3);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                const scaleT = Math.min(1, progress * 1.5);
                const s = 1 + 0.06 * scaleT; // slow subtle zoom
                this.ctx.translate(this.width / 2, this.height / 2);
                this.ctx.scale(s, s);
                this.ctx.translate(-this.width / 2, -this.height / 2);
                break;
            }
            case 'shake': {
                // Earthquake shake — jitters during hold
                const fadeIn = Math.min(1, progress * 5);
                const fadeOut = Math.min(1, (1 - progress) * 4);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                if (progress > 0.05 && progress < 0.9) {
                    const intensity = 4 * Math.sin(progress * 60);
                    const iy = 2 * Math.cos(progress * 47);
                    this.ctx.translate(intensity, iy);
                }
                break;
            }
            case 'slide_left': {
                // Slide in from the right side
                const fadeIn = Math.min(1, progress * 5);
                const fadeOut = Math.min(1, (1 - progress) * 4);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                const offsetX = progress < 0.2
                    ? (1 - progress / 0.2) * this.width * 0.2
                    : 0;
                this.ctx.translate(offsetX, 0);
                break;
            }
            case 'slide_right': {
                // Slide in from the left side
                const fadeIn = Math.min(1, progress * 5);
                const fadeOut = Math.min(1, (1 - progress) * 4);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                const offsetX = progress < 0.2
                    ? -(1 - progress / 0.2) * this.width * 0.2
                    : 0;
                this.ctx.translate(offsetX, 0);
                break;
            }
            case 'zoom_burst': {
                // Explosive zoom from tiny to overshoot then settle
                const fadeOut = Math.min(1, (1 - progress) * 3);
                let scale = 1;
                if (progress < 0.08) {
                    scale = (progress / 0.08) * 1.6;
                } else if (progress < 0.16) {
                    const t = (progress - 0.08) / 0.08;
                    scale = 1.6 - 0.6 * t;
                } else if (progress < 0.22) {
                    const t = (progress - 0.16) / 0.06;
                    scale = 1 + 0.1 * Math.sin(t * Math.PI);
                }
                this.ctx.globalAlpha = fadeOut;
                this.ctx.translate(this.width / 2, this.height / 2);
                this.ctx.scale(scale, scale);
                this.ctx.translate(-this.width / 2, -this.height / 2);
                break;
            }
            case 'drop_in': {
                // Fall from above with slight bounce
                const fadeOut = Math.min(1, (1 - progress) * 4);
                let offsetY = 0;
                if (progress < 0.12) {
                    offsetY = -(1 - progress / 0.12) * this.height * 0.3;
                } else if (progress < 0.2) {
                    const t = (progress - 0.12) / 0.08;
                    offsetY = 6 * Math.sin(t * Math.PI);
                }
                this.ctx.globalAlpha = Math.min(progress < 0.12 ? progress / 0.12 : 1, fadeOut);
                this.ctx.translate(0, offsetY);
                break;
            }
            case 'rotate_in': {
                // Subtle rotation entry
                const fadeIn = Math.min(1, progress * 5);
                const fadeOut = Math.min(1, (1 - progress) * 4);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                if (progress < 0.2) {
                    const t = progress / 0.2;
                    const angle = (1 - t) * -0.08; // radians (~4.5 degrees)
                    this.ctx.translate(this.width / 2, this.height / 2);
                    this.ctx.rotate(angle);
                    this.ctx.translate(-this.width / 2, -this.height / 2);
                }
                break;
            }
            case 'split_reveal': {
                // Scale from center line outward
                const fadeOut = Math.min(1, (1 - progress) * 4);
                let scaleY = 1;
                if (progress < 0.15) {
                    scaleY = progress / 0.15;
                }
                this.ctx.globalAlpha = Math.min(progress < 0.15 ? progress / 0.15 : 1, fadeOut);
                this.ctx.translate(this.width / 2, this.height / 2);
                this.ctx.scale(1, scaleY);
                this.ctx.translate(-this.width / 2, -this.height / 2);
                break;
            }
            case 'pulse': {
                // Rhythmic heartbeat pulse during hold
                const fadeIn = Math.min(1, progress * 4);
                const fadeOut = Math.min(1, (1 - progress) * 4);
                const beat = 1 + 0.04 * Math.sin(progress * Math.PI * 8);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                this.ctx.translate(this.width / 2, this.height / 2);
                this.ctx.scale(beat, beat);
                this.ctx.translate(-this.width / 2, -this.height / 2);
                break;
            }
            case 'glitch': {
                // Digital glitch — horizontal slices jitter
                const fadeIn = Math.min(1, progress * 5);
                const fadeOut = Math.min(1, (1 - progress) * 4);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                if (progress < 0.25) {
                    const jitter = Math.sin(progress * 120) * 6;
                    this.ctx.translate(jitter, 0);
                } else if (Math.random() < 0.06) {
                    this.ctx.translate(Math.random() * 4 - 2, 0);
                }
                break;
            }
            case 'breathe': {
                // Slow inhale/exhale scale — meditative, calm
                const fadeIn = Math.min(1, progress * 3);
                const fadeOut = Math.min(1, (1 - progress) * 3);
                const breathe = 1 + 0.025 * Math.sin(progress * Math.PI * 4);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                this.ctx.translate(this.width / 2, this.height / 2);
                this.ctx.scale(breathe, breathe);
                this.ctx.translate(-this.width / 2, -this.height / 2);
                break;
            }
            case 'stoic_fade': {
                // Ultra-slow deliberate fade — philosophical weight
                const fadeIn = Math.min(1, progress * 1.8);
                const fadeOut = Math.min(1, (1 - progress) * 2);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                break;
            }
            case 'drift': {
                // Gentle lateral drift during hold — dreamy, nostalgic
                const fadeIn = Math.min(1, progress * 3);
                const fadeOut = Math.min(1, (1 - progress) * 3);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                const driftX = Math.sin(progress * Math.PI * 2) * this.width * 0.015;
                const driftY = Math.cos(progress * Math.PI * 1.5) * this.height * 0.008;
                this.ctx.translate(driftX, driftY);
                break;
            }
            case 'expand': {
                // Scale from 0 to 100% with deceleration — revelation, epiphany
                const fadeOut = Math.min(1, (1 - progress) * 4);
                let scale = 1;
                if (progress < 0.25) {
                    const t = progress / 0.25;
                    scale = t * t * (3 - 2 * t); // smoothstep
                }
                this.ctx.globalAlpha = Math.min(progress < 0.25 ? progress / 0.25 : 1, fadeOut);
                this.ctx.translate(this.width / 2, this.height / 2);
                this.ctx.scale(scale, scale);
                this.ctx.translate(-this.width / 2, -this.height / 2);
                break;
            }
            default: {
                // Fallback to standard fade
                const fadeIn = Math.min(1, progress * 4);
                const fadeOut = Math.min(1, (1 - progress) * 4);
                this.ctx.globalAlpha = Math.min(fadeIn, fadeOut);
                break;
            }
        }
    }

    /**
     * Wrap text to fit within maxWidth
     * @param {string} text - Text to wrap
     * @param {number} maxWidth - Maximum line width
     * @param {number} fontSize - Font size (used for fallback font string)
     * @param {string} fontString - Optional full font string to use
     */
    wrapText(text, maxWidth, fontSize, fontString = null) {
        this.ctx.font = fontString || `bold ${fontSize}px Inter, sans-serif`;
        const words = text.split(' ');
        const lines = [];
        let currentLine = '';

        for (const word of words) {
            const testLine = currentLine ? `${currentLine} ${word}` : word;
            const metrics = this.ctx.measureText(testLine);

            if (metrics.width > maxWidth && currentLine) {
                lines.push(currentLine);
                currentLine = word;
            } else {
                currentLine = testLine;
            }
        }

        if (currentLine) {
            lines.push(currentLine);
        }

        return lines;
    }

    /**
     * Render image with effect
     */
    renderImage(img, effect, progress) {
        this.ctx.save();

        // Calculate how to fit image in canvas (cover)
        // Video elements use videoWidth/videoHeight; Image elements use width/height
        const w = img.videoWidth || img.naturalWidth || img.width;
        const h = img.videoHeight || img.naturalHeight || img.height;
        if (!w || !h) { this.ctx.restore(); return; } // not ready yet
        const imgAspect = w / h;
        const canvasAspect = this.width / this.height;

        let drawWidth, drawHeight, offsetX, offsetY;

        if (imgAspect > canvasAspect) {
            // Image is wider - fit to height
            drawHeight = this.height;
            drawWidth = drawHeight * imgAspect;
            offsetX = (this.width - drawWidth) / 2;
            offsetY = 0;
        } else {
            // Image is taller - fit to width
            drawWidth = this.width;
            drawHeight = drawWidth / imgAspect;
            offsetX = 0;
            offsetY = (this.height - drawHeight) / 2;
        }

        // Apply effect
        switch (effect) {
            case 'zoom_in':
                this.applyZoomIn(progress, drawWidth, drawHeight, offsetX, offsetY);
                break;
            case 'zoom_out':
                this.applyZoomOut(progress, drawWidth, drawHeight, offsetX, offsetY);
                break;
            case 'pan_left':
                this.applyPanLeft(progress, drawWidth, drawHeight, offsetY);
                break;
            case 'pan_right':
                this.applyPanRight(progress, drawWidth, drawHeight, offsetY);
                break;
            case 'fade':
                this.ctx.globalAlpha = this.easeInOut(progress);
                break;
            case 'shake':
                this.applyShake(progress);
                break;
            case 'pan_up':
                this.applyPanUp(progress, drawWidth, drawHeight, offsetX);
                break;
            case 'pan_down':
                this.applyPanDown(progress, drawWidth, drawHeight, offsetX);
                break;
            case 'pan_diagonal_tl':
                this.applyPanDiagonalTL(progress, drawWidth, drawHeight);
                break;
            case 'pan_diagonal_br':
                this.applyPanDiagonalBR(progress, drawWidth, drawHeight);
                break;
            case 'ken_burns':
                this.applyKenBurns(progress, drawWidth, drawHeight, offsetX, offsetY);
                break;
            case 'static':
            default:
                // No transform needed
                break;
        }

        this.ctx.drawImage(img, offsetX, offsetY, drawWidth, drawHeight);
        this.ctx.restore();
    }

    /**
     * Apply zoom in effect
     */
    applyZoomIn(progress, drawWidth, drawHeight, offsetX, offsetY) {
        const startScale = 1.0;
        const endScale = 1.2;
        const scale = startScale + (endScale - startScale) * this.easeInOut(progress);

        const centerX = this.width / 2;
        const centerY = this.height / 2;

        this.ctx.translate(centerX, centerY);
        this.ctx.scale(scale, scale);
        this.ctx.translate(-centerX, -centerY);
    }

    /**
     * Apply zoom out effect
     */
    applyZoomOut(progress, drawWidth, drawHeight, offsetX, offsetY) {
        const startScale = 1.2;
        const endScale = 1.0;
        const scale = startScale + (endScale - startScale) * this.easeInOut(progress);

        const centerX = this.width / 2;
        const centerY = this.height / 2;

        this.ctx.translate(centerX, centerY);
        this.ctx.scale(scale, scale);
        this.ctx.translate(-centerX, -centerY);
    }

    /**
     * Apply pan left effect
     */
    applyPanLeft(progress, drawWidth, drawHeight, offsetY) {
        const panAmount = (drawWidth - this.width) * 0.5;
        const translateX = panAmount * (1 - progress);
        this.ctx.translate(-translateX, 0);
    }

    /**
     * Apply pan right effect
     */
    applyPanRight(progress, drawWidth, drawHeight, offsetY) {
        const panAmount = (drawWidth - this.width) * 0.5;
        const translateX = panAmount * progress;
        this.ctx.translate(-translateX, 0);
    }

    /**
     * Apply shake effect
     */
    applyShake(progress) {
        const intensity = 5;
        const frequency = 20;
        const shakeX = Math.sin(progress * Math.PI * 2 * frequency) * intensity;
        const shakeY = Math.cos(progress * Math.PI * 2 * frequency) * intensity;
        this.ctx.translate(shakeX, shakeY);
    }

    applyPanUp(progress, drawWidth, drawHeight, offsetX) {
        const panAmount = (drawHeight - this.height) * 0.5;
        const translateY = panAmount * (1 - this.easeInOut(progress));
        this.ctx.translate(0, -translateY);
    }

    applyPanDown(progress, drawWidth, drawHeight, offsetX) {
        const panAmount = (drawHeight - this.height) * 0.5;
        const translateY = panAmount * this.easeInOut(progress);
        this.ctx.translate(0, -translateY);
    }

    applyPanDiagonalTL(progress, drawWidth, drawHeight) {
        const p = this.easeInOut(progress);
        const panX = (drawWidth - this.width) * 0.3 * (1 - p);
        const panY = (drawHeight - this.height) * 0.3 * (1 - p);
        this.ctx.translate(-panX, -panY);
    }

    applyPanDiagonalBR(progress, drawWidth, drawHeight) {
        const p = this.easeInOut(progress);
        const panX = (drawWidth - this.width) * 0.3 * p;
        const panY = (drawHeight - this.height) * 0.3 * p;
        this.ctx.translate(-panX, -panY);
    }

    applyKenBurns(progress, drawWidth, drawHeight, offsetX, offsetY) {
        const p = this.easeInOut(progress);
        const scale = 1.0 + 0.15 * p;
        const panX = (drawWidth - this.width) * 0.05 * p;
        const centerX = this.width / 2;
        const centerY = this.height / 2;
        this.ctx.translate(centerX, centerY);
        this.ctx.scale(scale, scale);
        this.ctx.translate(-centerX - panX, -centerY);
    }

    /**
     * Easing function for smooth animations
     */
    easeInOut(t) {
        return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
    }

    /**
     * Render placeholder when no image is loaded
     */
    renderPlaceholder(scene) {
        // Background gradient based on scene type
        const colors = {
            hook: '#FF4444',
            buildup: '#FF8C00',
            text: '#AA44FF',
            peak: '#FFDD00',
            transition: '#4488FF',
            cta: '#44FF44',
            speaker: '#FF44AA',
            final_statement: '#44FFFF'
        };

        const color = colors[scene.type] || '#666666';

        // Create gradient
        const gradient = this.ctx.createLinearGradient(0, 0, this.width, this.height);
        gradient.addColorStop(0, this.hexToRgba(color, 0.3));
        gradient.addColorStop(1, this.hexToRgba(color, 0.1));

        this.ctx.fillStyle = gradient;
        this.ctx.fillRect(0, 0, this.width, this.height);

        // Draw scene type label
        this.ctx.fillStyle = '#ffffff';
        this.ctx.font = 'bold 48px Inter, sans-serif';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        this.ctx.fillText(scene.type.toUpperCase(), this.width / 2, this.height / 2 - 30);

        // Draw scene ID
        this.ctx.font = '32px Inter, sans-serif';
        this.ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
        this.ctx.fillText(`Scene ${scene.id}`, this.width / 2, this.height / 2 + 30);
    }

    /**
     * Convert hex color to rgba
     */
    hexToRgba(hex, alpha) {
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    /**
     * Enable text dragging on the canvas
     * @param {function} onPositionChange - Callback when text position changes (x, y in percentage)
     */
    enableTextDrag(onPositionChange) {
        this.onTextPositionChange = onPositionChange;
        this.isDraggingText = false;
        this.dragStartPos = null;

        // Mouse event handlers
        this.canvas.addEventListener('mousedown', this._handleMouseDown.bind(this));
        this.canvas.addEventListener('mousemove', this._handleMouseMove.bind(this));
        this.canvas.addEventListener('mouseup', this._handleMouseUp.bind(this));
        this.canvas.addEventListener('mouseleave', this._handleMouseUp.bind(this));

        // Touch event handlers for mobile
        this.canvas.addEventListener('touchstart', this._handleTouchStart.bind(this));
        this.canvas.addEventListener('touchmove', this._handleTouchMove.bind(this));
        this.canvas.addEventListener('touchend', this._handleTouchEnd.bind(this));
    }

    /**
     * Get mouse position relative to canvas
     */
    _getCanvasPos(e) {
        const rect = this.canvas.getBoundingClientRect();
        const scaleX = this.canvas.width / rect.width;
        const scaleY = this.canvas.height / rect.height;
        return {
            x: (e.clientX - rect.left) * scaleX,
            y: (e.clientY - rect.top) * scaleY
        };
    }

    /**
     * Check if position is within text bounds
     */
    _isOverText(pos) {
        if (!this.lastTextBounds || !this.currentTextScene) return false;

        const bounds = this.lastTextBounds;
        const halfWidth = bounds.width / 2;
        const halfHeight = bounds.height / 2;

        return pos.x >= bounds.x - halfWidth &&
            pos.x <= bounds.x + halfWidth &&
            pos.y >= bounds.y - halfHeight &&
            pos.y <= bounds.y + bounds.height - halfHeight;
    }

    /**
     * Handle mouse down - start dragging if over text
     */
    _handleMouseDown(e) {
        if (!this.currentTextScene) return;

        const pos = this._getCanvasPos(e);
        if (this._isOverText(pos)) {
            this.isDraggingText = true;
            this.dragStartPos = pos;
            this.canvas.style.cursor = 'grabbing';
            e.preventDefault();
        }
    }

    /**
     * Handle mouse move - update text position while dragging
     */
    _handleMouseMove(e) {
        const pos = this._getCanvasPos(e);

        if (this.isDraggingText && this.currentTextScene) {
            // Calculate new position as percentage
            const newX = (pos.x / this.width) * 100;
            const newY = (pos.y / this.height) * 100;

            // Clamp to canvas bounds (5% padding)
            const clampedX = Math.max(5, Math.min(95, newX));
            const clampedY = Math.max(5, Math.min(95, newY));

            // Update scene position
            this.currentTextScene.text_x = clampedX;
            this.currentTextScene.text_y = clampedY;

            // Re-render
            this.render();

            // Notify callback
            if (this.onTextPositionChange) {
                this.onTextPositionChange(clampedX, clampedY, this.currentTextScene);
            }

            e.preventDefault();
        } else {
            // Update cursor based on hover state
            if (this._isOverText(pos) && this.currentTextScene) {
                this.canvas.style.cursor = 'grab';
            } else {
                this.canvas.style.cursor = 'default';
            }
        }
    }

    /**
     * Handle mouse up - stop dragging
     */
    _handleMouseUp(e) {
        if (this.isDraggingText) {
            this.isDraggingText = false;
            this.dragStartPos = null;
            this.canvas.style.cursor = this._isOverText(this._getCanvasPos(e)) ? 'grab' : 'default';
        }
    }

    /**
     * Handle touch start
     */
    _handleTouchStart(e) {
        if (e.touches.length === 1) {
            const touch = e.touches[0];
            this._handleMouseDown({ clientX: touch.clientX, clientY: touch.clientY, preventDefault: () => e.preventDefault() });
        }
    }

    /**
     * Handle touch move
     */
    _handleTouchMove(e) {
        if (e.touches.length === 1) {
            const touch = e.touches[0];
            this._handleMouseMove({ clientX: touch.clientX, clientY: touch.clientY, preventDefault: () => e.preventDefault() });
        }
    }

    /**
     * Handle touch end
     */
    _handleTouchEnd(e) {
        this._handleMouseUp({ clientX: 0, clientY: 0 });
    }

    /**
     * Get the next scene after the current one
     */
    _getNextScene() {
        let accumulated = 0;
        for (let i = 0; i < this.scenes.length; i++) {
            if (this.currentTime >= accumulated && this.currentTime < accumulated + this.scenes[i].duration) {
                return this.scenes[i + 1] || null;
            }
            accumulated += this.scenes[i].duration;
        }
        return null;
    }

    // ---- Caption Overlay ----

    /**
     * Set captions data and style for overlay rendering
     */
    setCaptions(captions, style) {
        this.captions = captions || [];
        this.captionStyle = style || {};
        // Re-render so captions appear immediately (even when paused)
        this.render();
    }

    /**
     * Render active caption on top of scene at the given time.
     *
     * @param {number} time
     * @param {object} [opts]
     * @param {number} [opts.suppressStartingAfter] - drop captions whose
     *        start time is at or after this value (used by text scenes that
     *        hide captions but still let in-flight captions finish).
     */
    renderCaptionOverlay(time, opts = {}) {
        if (!this.captions.length) return;

        const suppressStartingAfter = typeof opts.suppressStartingAfter === 'number'
            ? opts.suppressStartingAfter
            : null;

        // Find active caption
        let active = null;
        for (const cap of this.captions) {
            if (time >= cap.start && time < cap.end) { active = cap; break; }
        }
        if (!active) return;
        // If a text scene is hiding captions, only render this one if it
        // started *before* the text scene began (mid-flight finishing).
        if (suppressStartingAfter !== null && active.start >= suppressStartingAfter) return;

        const style = this.captionStyle;
        const fontFamily = style.font_family || 'Montserrat';
        const fontWeight = style.font_weight || '800';
        const scale = this.height / 1920;
        const fontSize = (style.font_size || 64) * scale;
        const color = style.color || '#FFFFFF';
        const strokeColor = style.stroke_color ?? '#000000';
        const strokeWidth = (style.stroke_width ?? 4) * scale;
        const posY = (style.position_y || 80) / 100;
        const textAlign = (style.text_align || 'center').toLowerCase();
        const currentWordScale = Math.min(1.18, Math.max(1, Number(style.current_word_scale || 1)));
        const wrapWordsPerLine = Math.max(0, parseInt(style.wrap_words_per_line || 0, 10) || 0);
        const randomLineEmphasis = !!style.random_line_emphasis;
        const randomLineScale = Math.max(1, Number(style.random_line_scale || 1.14));
        const randomLineChance = Math.max(0, Math.min(1, Number(style.random_line_chance ?? 0.5)));
        const randomLineTargets = Array.isArray(style.random_line_targets)
            ? style.random_line_targets.map(v => parseInt(v, 10)).filter(v => Number.isFinite(v) && v > 0)
            : [1, 3];
        const wordByWordReveal = !!style.word_by_word_reveal;
        const leadWordLine = !!style.lead_word_line;
        const wordFontMix = !!style.word_font_mix;
        const wordFontFamilies = this._parseStyleList(style.word_font_families, [fontFamily]);
        const wordFontWeights = this._parseStyleList(style.word_font_weights, [fontWeight]);
        const wordFontStyles = this._parseStyleList(style.word_font_styles, ['normal']);
        const transform = style.text_transform || 'uppercase';
        const animation = style.animation || 'pop';
        const letterSpacing = (style.letter_spacing || 0) * scale; // px units, scaled
        const bgColor = style.background || 'none';
        const blendMode = style.blend_mode || 'source-over';
        const boxPadX = (style.box_padding_x || 0) * scale;
        const boxPadY = (style.box_padding_y || 0) * scale;
        const shadowColor = style.shadow_color || '';
        const shadowBlur = (style.shadow_blur || 0) * scale;
        const shadowOffX = (style.shadow_offset_x || 0) * scale;
        const shadowOffY = (style.shadow_offset_y || 0) * scale;

        let text = active.text;
        // Strip special characters (keep letters, numbers, spaces, ! ? [ ])
        text = text.replace(/[^\p{L}\p{N}\s!?\[\]]/gu, '').replace(/\s{2,}/g, ' ').trim();
        if (transform === 'uppercase') text = text.toUpperCase();

        this.ctx.save();
        this.ctx.globalCompositeOperation = blendMode;
        this.ctx.font = `${fontWeight} ${fontSize}px "${fontFamily}", sans-serif`;
        this.ctx.textAlign = textAlign === 'left' ? 'left' : (textAlign === 'right' ? 'right' : 'center');
        this.ctx.textBaseline = 'middle';

        // Apply letter-spacing via canvas letterSpacing (widely supported)
        if (letterSpacing) {
            this.ctx.letterSpacing = `${letterSpacing}px`;
        }

        // Keep caption text inside frame with side-safe padding.
        const sideSafePx = Math.max(24 * scale, this.width * 0.05);
        const maxCaptionWidth = Math.max(80, this.width - sideSafePx * 2);
        const requestedX = (Number(style.position_x) / 100) * this.width;
        let anchorX = Number.isFinite(requestedX) ? requestedX : (this.width / 2);
        anchorX = Math.max(sideSafePx, Math.min(this.width - sideSafePx, anchorX));
        const lineStartX = (lineWidth) => {
            if (textAlign === 'left') return anchorX;
            if (textAlign === 'right') return anchorX - lineWidth;
            return anchorX - lineWidth / 2;
        };

        // Alignment-aware max width — prevent text from extending past safe area
        // based on anchor position and text alignment.
        const alignMaxWidth = (() => {
            if (textAlign === 'left') return Math.max(120, this.width - anchorX - sideSafePx);
            if (textAlign === 'right') return Math.max(120, anchorX - sideSafePx);
            // center: limited by whichever side has less room
            return Math.max(120, Math.min(anchorX - sideSafePx, this.width - anchorX - sideSafePx) * 2);
        })();

        // Reserve room for stroke and random-line / word scaling so the
        // rendered result never exceeds the safe area.
        const hasStroke = strokeColor && strokeColor !== 'none' && strokeWidth > 0;
        const strokePad = hasStroke ? strokeWidth * 2 : 0;
        const maxLineScale = randomLineEmphasis ? randomLineScale : 1;
        const safeMaxWidth = (raw) => Math.max(80, (raw - strokePad) / maxLineScale);

        // Single-line mode: wrap only if text exceeds caption-safe width
        const isSingleLine = (
            style.preset === 'single_line'
            || style.preset === 'single_line_highlight'
            || blendMode === 'difference'
            || style.force_single_line === true
        ) && wrapWordsPerLine <= 0;
        let lines, lineHeight, totalHeight, baseY;
        let lineTargetWidth = maxCaptionWidth;
        let renderFontSize = fontSize;

        if (isSingleLine) {
            const maxWidth = safeMaxWidth(Math.min(maxCaptionWidth, alignMaxWidth));
            // Set font before measuring
            this.ctx.font = `${fontWeight} ${renderFontSize}px "${fontFamily}", sans-serif`;
            const measuredWidth = this._measureTextWidth(text, letterSpacing);
            if (measuredWidth > maxWidth) {
                const fitScale = maxWidth / Math.max(1, measuredWidth);
                const minFontSize = fontSize * 0.72;
                renderFontSize = Math.max(minFontSize, fontSize * fitScale);
                this.ctx.font = `${fontWeight} ${renderFontSize}px "${fontFamily}", sans-serif`;
            }
            // After scaling, if text still exceeds width, wrap it
            const finalSingleWidth = this._measureTextWidth(text, letterSpacing);
            lines = finalSingleWidth > maxWidth
                ? this._wrapText(text, maxWidth, letterSpacing)
                : [text];
            lineTargetWidth = maxWidth;
            lineHeight = renderFontSize * 1.1 * (randomLineEmphasis ? randomLineScale : 1);
            totalHeight = lines.length * lineHeight;
            baseY = this.height * posY - (totalHeight - lineHeight) / 2;
        } else {
            const maxWidth = safeMaxWidth(Math.min(this.width * 0.85, maxCaptionWidth, alignMaxWidth));
            if (wordFontMix) {
                lines = wrapWordsPerLine > 0
                    ? this._wrapTextByWordCountMixed(text, wrapWordsPerLine, maxWidth, letterSpacing, renderFontSize, fontFamily, fontWeight, wordFontFamilies, wordFontWeights, wordFontStyles)
                    : this._wrapTextMixed(text, maxWidth, letterSpacing, renderFontSize, fontFamily, fontWeight, wordFontFamilies, wordFontWeights, wordFontStyles);
            } else if (leadWordLine) {
                lines = this._wrapLeadWordThenChunks(
                    text,
                    wrapWordsPerLine > 0 ? wrapWordsPerLine : 3,
                    maxWidth,
                    letterSpacing
                );
            } else {
                lines = wrapWordsPerLine > 0
                    ? this._wrapTextByWordCount(text, wrapWordsPerLine, maxWidth, letterSpacing)
                    : this._wrapText(text, maxWidth, letterSpacing);
            }
            lineTargetWidth = maxWidth;
            lineHeight = renderFontSize * 1.25 * (randomLineEmphasis ? randomLineScale : 1);
            totalHeight = lines.length * lineHeight;
            baseY = this.height * posY - (totalHeight - lineHeight) / 2;
        }

        // Pop animation: scale in
        if (animation === 'pop') {
            const capProgress = (time - active.start) / (active.end - active.start);
            const popScale = capProgress < 0.1 ? (capProgress / 0.1) * 0.1 + 0.9 : 1.0;
            const alpha = capProgress < 0.05 ? capProgress / 0.05 : (capProgress > 0.9 ? (1.0 - capProgress) / 0.1 : 1.0);
            this.ctx.globalAlpha = Math.max(0, Math.min(1, alpha));
            const cx = anchorX;
            const cy = this.height * posY;
            this.ctx.translate(cx, cy);
            this.ctx.scale(popScale, popScale);
            this.ctx.translate(-cx, -cy);
        }

        // Hard-cut animation: instant appear/disappear (no fade, optional fast scale-up)
        if (animation === 'hard_cut') {
            const capProgress = (time - active.start) / (active.end - active.start);
            if (capProgress < 0.05) {
                const s = 0.9 + (capProgress / 0.05) * 0.1;
                const cx = anchorX;
                const cy = this.height * posY;
                this.ctx.translate(cx, cy);
                this.ctx.scale(s, s);
                this.ctx.translate(-cx, -cy);
            }
            // Single-line style gets a short edge fade for a premium, less "chunky" transition.
            const edgeFadeMs = Number(style.edge_fade_ms ?? 90);
            const fadeSec = Math.max(0, edgeFadeMs) / 1000;
            const dur = Math.max(0.001, active.end - active.start);
            const fadeRatio = Math.min(0.25, fadeSec / dur);
            if (fadeRatio > 0) {
                const fadeIn = Math.min(1, capProgress / fadeRatio);
                const fadeOut = Math.min(1, (1 - capProgress) / fadeRatio);
                this.ctx.globalAlpha *= Math.max(0, Math.min(1, Math.min(fadeIn, fadeOut)));
            }
        }

        const isDifference = blendMode === 'difference';
        const fontStr = `${fontWeight} ${renderFontSize}px "${fontFamily}", sans-serif`;

        if (isDifference) {
            // --- 3-pass difference blend rendering ---
            // Read tuned values from style config
            const diffStrength = style.diff_strength ?? 1.0;
            const overlayStrength = style.overlay_strength ?? 0.35;
            const overlayColor = style.overlay_color || '#ffffff';

            // Convert diff_strength (0-1) to fill alpha for the difference pass
            const diffR = Math.round(diffStrength * 255);
            const diffFill = `rgb(${diffR},${diffR},${diffR})`;

            // Parse overlay color hex to rgb for rgba fill
            const oR = parseInt((overlayColor).slice(1, 3), 16) || 255;
            const oG = parseInt((overlayColor).slice(3, 5), 16) || 255;
            const oB = parseInt((overlayColor).slice(5, 7), 16) || 255;
            const overlayFill = `rgba(${oR},${oG},${oB},${overlayStrength})`;

            // Pass 1: drop shadow (normal compositing)
            this.ctx.restore();
            this.ctx.save();
            this.ctx.font = fontStr;
            this.ctx.textAlign = textAlign === 'left' ? 'left' : (textAlign === 'right' ? 'right' : 'center');
            this.ctx.textBaseline = 'middle';
            if (letterSpacing) this.ctx.letterSpacing = `${letterSpacing}px`;
            this.ctx.globalCompositeOperation = 'source-over';
            this.ctx.shadowColor = shadowColor || 'rgba(0,0,0,0.45)';
            this.ctx.shadowBlur = shadowBlur || 6 * scale;
            this.ctx.shadowOffsetX = shadowOffX || 3 * scale;
            this.ctx.shadowOffsetY = shadowOffY || 3 * scale;
            this.ctx.fillStyle = 'rgba(0,0,0,0)';
            for (let i = 0; i < lines.length; i++) {
                this.ctx.fillText(lines[i], anchorX, baseY + i * lineHeight);
            }
            this.ctx.restore();

            // Pass 2: difference blend — inverts image inside glyphs
            this.ctx.save();
            this.ctx.font = fontStr;
            this.ctx.textAlign = textAlign === 'left' ? 'left' : (textAlign === 'right' ? 'right' : 'center');
            this.ctx.textBaseline = 'middle';
            if (letterSpacing) this.ctx.letterSpacing = `${letterSpacing}px`;
            this.ctx.globalCompositeOperation = 'difference';
            this.ctx.fillStyle = diffFill;
            for (let i = 0; i < lines.length; i++) {
                this.ctx.fillText(lines[i], anchorX, baseY + i * lineHeight);
            }
            this.ctx.restore();

            // Pass 3: overlay brightness/contrast boost
            this.ctx.save();
            this.ctx.font = fontStr;
            this.ctx.textAlign = textAlign === 'left' ? 'left' : (textAlign === 'right' ? 'right' : 'center');
            this.ctx.textBaseline = 'middle';
            if (letterSpacing) this.ctx.letterSpacing = `${letterSpacing}px`;
            this.ctx.globalCompositeOperation = 'overlay';
            this.ctx.fillStyle = overlayFill;
            for (let i = 0; i < lines.length; i++) {
                this.ctx.fillText(lines[i], anchorX, baseY + i * lineHeight);
            }
            this.ctx.restore();
        } else {
            // --- Standard rendering ---
            const doHighlight = style.highlight && active.words?.length > 0;
            const highlightColor = style.highlight_color || '#4ECDC4';
            const highlightMode = style.highlight_mode || 'text'; // 'text' = color word, 'box' = bg rectangle
            const isRandomLineActive = (lineIdx) => {
                if (!randomLineEmphasis || doHighlight) return false;
                const lineNo = lineIdx + 1;
                if (!randomLineTargets.includes(lineNo)) return false;
                const key = `${style.preset || ''}|${active.start}|${active.end}|${active.text}|${lineNo}`;
                return this._hashToUnit(key) < randomLineChance;
            };

            // Find active word index for highlighting
            let activeWordIdx = -1;
            if (doHighlight) {
                for (let w = active.words.length - 1; w >= 0; w--) {
                    if (time >= active.words[w].begin) { activeWordIdx = w; break; }
                }
            } else if (wordByWordReveal && active.words?.length) {
                for (let w = active.words.length - 1; w >= 0; w--) {
                    if (time >= active.words[w].begin) { activeWordIdx = w; break; }
                }
            }

            for (let i = 0; i < lines.length; i++) {
                const ly = baseY + i * lineHeight;
                let lineScale = isRandomLineActive(i) ? randomLineScale : 1;
                const lineFontSize = renderFontSize * lineScale;
                this.ctx.font = `${fontWeight} ${lineFontSize}px "${fontFamily}", sans-serif`;
                const lineWords = lines[i].split(' ');
                let lineWordOffset = 0;
                for (let li = 0; li < i; li++) lineWordOffset += lines[li].split(' ').length;

                // Draw solid background box behind text
                if (bgColor && bgColor !== 'none' && bgColor !== 'transparent') {
                    const textW = wordFontMix
                        ? this._measureMixedLineWidth(lineWords, lineWordOffset, lineFontSize, fontFamily, fontWeight, wordFontFamilies, wordFontWeights, wordFontStyles, letterSpacing)
                        : this._measureTextWidth(lines[i], letterSpacing);
                    const bx = lineStartX(textW) - boxPadX;
                    const by = ly - lineFontSize / 2 - boxPadY;
                    const bw = textW + boxPadX * 2;
                    const bh = lineFontSize + boxPadY * 2;
                    this.ctx.fillStyle = bgColor;
                    this.ctx.fillRect(bx, by, bw, bh);
                }

                // Stroke (skip for doHighlight — handled per-word below)
                if (!isSingleLine && !doHighlight && strokeColor && strokeColor !== 'none' && strokeWidth > 0) {
                    this.ctx.strokeStyle = strokeColor;
                    this.ctx.lineWidth = strokeWidth;
                    this.ctx.lineJoin = 'round';
                    this.ctx.strokeText(lines[i], anchorX, ly);
                }

                // Text shadow
                if (shadowColor && shadowColor !== 'none') {
                    this.ctx.shadowColor = shadowColor;
                    this.ctx.shadowBlur = shadowBlur;
                    this.ctx.shadowOffsetX = shadowOffX;
                    this.ctx.shadowOffsetY = shadowOffY;
                }

                if (wordFontMix) {
                    this.ctx.textAlign = 'left';
                    const wordWidths = [];
                    const spaceWidths = [];
                    for (let w = 0; w < lineWords.length; w++) {
                        const globalWordIdx = lineWordOffset + w;
                        wordWidths.push(this._measureMixedWordWidth(lineWords[w], globalWordIdx, lineFontSize, fontFamily, fontWeight, wordFontFamilies, wordFontWeights, wordFontStyles, letterSpacing));
                        if (w < lineWords.length - 1) {
                            spaceWidths.push(this._measureMixedWordWidth(' ', globalWordIdx + 1, lineFontSize, fontFamily, fontWeight, wordFontFamilies, wordFontWeights, wordFontStyles, letterSpacing));
                        }
                    }
                    const totalWordsW = wordWidths.reduce((sum, w) => sum + w, 0);
                    const totalSpacesW = spaceWidths.reduce((sum, w) => sum + w, 0);
                    const mixedLineW = totalWordsW + totalSpacesW;
                    let drawX = lineStartX(mixedLineW);
                    drawX = Math.max(sideSafePx, Math.min(this.width - sideSafePx - mixedLineW, drawX));

                    for (let w = 0; w < lineWords.length; w++) {
                        const globalWordIdx = lineWordOffset + w;
                        const wordText = lineWords[w];
                        const wordW = wordWidths[w];
                        this.ctx.font = this._mixedWordFont(globalWordIdx, lineFontSize, fontFamily, fontWeight, wordFontFamilies, wordFontWeights, wordFontStyles);

                        if (!wordByWordReveal || !active.words?.length || globalWordIdx <= activeWordIdx) {
                            if (!isSingleLine && strokeColor && strokeColor !== 'none' && strokeWidth > 0) {
                                this.ctx.strokeStyle = strokeColor;
                                this.ctx.lineWidth = strokeWidth;
                                this.ctx.lineJoin = 'round';
                                this.ctx.strokeText(wordText, drawX, ly);
                            }
                            this.ctx.fillStyle = color;
                            this.ctx.fillText(wordText, drawX, ly);
                        }
                        drawX += wordW + (w < lineWords.length - 1 ? spaceWidths[w] : 0);
                    }
                    this.ctx.textAlign = textAlign === 'left' ? 'left' : (textAlign === 'right' ? 'right' : 'center');
                    this.ctx.font = `${fontWeight} ${lineFontSize}px "${fontFamily}", sans-serif`;
                } else if (doHighlight) {
                    // Two-pass rendering: shadow pass (full line), then word-by-word color pass
                    const lineWords = lines[i].split(' ');
                    const fullLineW = this._measureTextWidth(lines[i], letterSpacing);

                    // Compute word offset within the full caption for this line
                    let wordOffset = 0;
                    for (let li = 0; li < i; li++) {
                        wordOffset += lines[li].split(' ').length;
                    }

                    // Draw word-by-word so spacing remains correct when active word is scaled.
                    this.ctx.textAlign = 'left';
                    const spaceW = this._measureTextWidth(' ', letterSpacing);
                    const basePad = fontSize * 0.15;
                    const boxRadius = fontSize * 0.12;
                    const baseFont = `${fontWeight} ${renderFontSize}px "${fontFamily}", sans-serif`;
                    let drawX = lineStartX(fullLineW);

                    // Measure per-word widths with active word scaling so layout reflects the emphasis.
                    const wordWidths = [];
                    for (let w = 0; w < lineWords.length; w++) {
                        const globalWordIdx = wordOffset + w;
                        const isActive = globalWordIdx === activeWordIdx;
                        const wordSize = isActive ? (renderFontSize * currentWordScale) : renderFontSize;
                        this.ctx.font = `${fontWeight} ${wordSize}px "${fontFamily}", sans-serif`;
                        wordWidths.push(this._measureTextWidth(lineWords[w], letterSpacing));
                    }
                    this.ctx.font = baseFont;
                    const totalWordsW = wordWidths.reduce((sum, w) => sum + w, 0);
                    const fullLineScaledW = totalWordsW + spaceW * Math.max(0, lineWords.length - 1);
                    drawX = lineStartX(fullLineScaledW);
                    // Clamp so scaled line stays within safe area
                    drawX = Math.max(sideSafePx, Math.min(this.width - sideSafePx - fullLineScaledW, drawX));

                    for (let w = 0; w < lineWords.length; w++) {
                        const globalWordIdx = wordOffset + w;
                        const isActive = globalWordIdx === activeWordIdx;
                        const wordText = lineWords[w];
                        const wordW = wordWidths[w];
                        const wordSize = isActive ? (renderFontSize * currentWordScale) : renderFontSize;
                        this.ctx.font = `${fontWeight} ${wordSize}px "${fontFamily}", sans-serif`;
                        const yOffset = isActive ? ((renderFontSize - wordSize) * 0.5) : 0;
                        const wordY = ly + yOffset;

                        // Box mode: draw colored rectangle behind active word
                        if (isActive && highlightMode === 'box') {
                    const boxPad = basePad * Math.max(1, currentWordScale * 0.95);
                            const bx = drawX - boxPad;
                            const by = wordY - wordSize * 0.55 - boxPad;
                            const bw = wordW + boxPad * 2;
                            const bh = wordSize * 1.1 + boxPad * 2;
                            this.ctx.fillStyle = highlightColor;
                            this.ctx.beginPath();
                            this.ctx.roundRect(bx, by, bw, bh, boxRadius);
                            this.ctx.fill();
                        }

                        // Shadow for per-word rendering
                        if (shadowColor && shadowColor !== 'none') {
                            this.ctx.shadowColor = shadowColor;
                            this.ctx.shadowBlur = shadowBlur;
                            this.ctx.shadowOffsetX = shadowOffX;
                            this.ctx.shadowOffsetY = shadowOffY;
                        }

                        // Per-word stroke (aligned with scaled word position)
                        if (strokeColor && strokeColor !== 'none' && strokeWidth > 0) {
                            this.ctx.strokeStyle = strokeColor;
                            this.ctx.lineWidth = strokeWidth;
                            this.ctx.lineJoin = 'round';
                            this.ctx.strokeText(wordText, drawX, wordY);
                        }

                        // Text mode: active word gets highlight color; box mode keeps base color.
                        this.ctx.fillStyle = (isActive && highlightMode === 'text') ? highlightColor : color;
                        this.ctx.fillText(wordText, drawX, wordY);

                        // Reset shadow after each word to avoid bleeding into next draw ops
                        if (shadowColor && shadowColor !== 'none') {
                            this.ctx.shadowColor = 'transparent';
                            this.ctx.shadowBlur = 0;
                            this.ctx.shadowOffsetX = 0;
                            this.ctx.shadowOffsetY = 0;
                        }

                        drawX += wordW + (w < lineWords.length - 1 ? spaceW : 0);
                    }
                    this.ctx.font = baseFont;
                    this.ctx.textAlign = textAlign === 'left' ? 'left' : (textAlign === 'right' ? 'right' : 'center');
                } else {
                    if (wordByWordReveal && active.words?.length) {
                        const lineWords = lines[i].split(' ');
                        let wordOffset = 0;
                        for (let li = 0; li < i; li++) wordOffset += lines[li].split(' ').length;
                        const spaceW = this._measureTextWidth(' ', letterSpacing);
                        const wordWidths = lineWords.map(w => this._measureTextWidth(w, letterSpacing));
                        const totalWordsW = wordWidths.reduce((sum, w) => sum + w, 0);
                        const fullLineW = totalWordsW + spaceW * Math.max(0, lineWords.length - 1);
                        let drawX = lineStartX(fullLineW);
                        drawX = Math.max(sideSafePx, Math.min(this.width - sideSafePx - fullLineW, drawX));

                        this.ctx.textAlign = 'left';
                        this.ctx.fillStyle = color;
                        for (let w = 0; w < lineWords.length; w++) {
                            const globalWordIdx = wordOffset + w;
                            if (globalWordIdx <= activeWordIdx) {
                                this.ctx.fillText(lineWords[w], drawX, ly);
                            }
                            drawX += wordWidths[w] + (w < lineWords.length - 1 ? spaceW : 0);
                        }
                        this.ctx.textAlign = textAlign === 'left' ? 'left' : (textAlign === 'right' ? 'right' : 'center');
                    } else {
                        // Fill text (no highlight)
                        this.ctx.fillStyle = color;
                        this.ctx.fillText(lines[i], anchorX, ly);
                    }
                }

                // Reset shadow
                if (shadowColor && shadowColor !== 'none') {
                    this.ctx.shadowColor = 'transparent';
                    this.ctx.shadowBlur = 0;
                    this.ctx.shadowOffsetX = 0;
                    this.ctx.shadowOffsetY = 0;
                }
            }

            this.ctx.restore();
        }
    }

    /**
     * Wrap text into lines that fit within maxWidth on the canvas
     */
    _wrapText(text, maxWidth, letterSpacing = 0) {
        const words = String(text || '').split(/\s+/).filter(Boolean);
        if (!words.length) return [''];

        const lines = [];
        let currentLine = '';

        for (const rawWord of words) {
            const wordParts = this._splitTokenToFit(rawWord, maxWidth, letterSpacing);
            for (const part of wordParts) {
                const candidate = currentLine ? `${currentLine} ${part}` : part;
                if (!currentLine || this._measureTextWidth(candidate, letterSpacing) <= maxWidth) {
                    currentLine = candidate;
                } else {
                    lines.push(currentLine);
                    currentLine = part;
                }
            }
        }

        if (currentLine) lines.push(currentLine);
        return lines;
    }

    _wrapTextMixed(text, maxWidth, letterSpacing, fontSize, defaultFamily, defaultWeight, families, weights, styles, startWordIndex = 0) {
        const words = String(text || '').split(/\s+/).filter(Boolean);
        if (!words.length) return [''];

        const lines = [];
        let currentWords = [];
        let currentWidth = 0;
        let wordIndex = startWordIndex;

        for (const rawWord of words) {
            const parts = this._splitTokenToFitMixed(rawWord, maxWidth, letterSpacing, wordIndex, fontSize, defaultFamily, defaultWeight, families, weights, styles);
            for (const part of parts) {
                const partW = this._measureMixedWordWidth(part, wordIndex, fontSize, defaultFamily, defaultWeight, families, weights, styles, letterSpacing);
                const spaceW = currentWords.length
                    ? this._measureMixedWordWidth(' ', wordIndex, fontSize, defaultFamily, defaultWeight, families, weights, styles, letterSpacing)
                    : 0;
                if (currentWords.length && currentWidth + spaceW + partW > maxWidth) {
                    lines.push(currentWords.join(' '));
                    currentWords = [part];
                    currentWidth = partW;
                } else {
                    currentWords.push(part);
                    currentWidth += spaceW + partW;
                }
            }
            wordIndex += 1;
        }

        if (currentWords.length) lines.push(currentWords.join(' '));
        return lines.length ? lines : [''];
    }

    _wrapTextByWordCountMixed(text, wordsPerLine, maxWidth, letterSpacing, fontSize, defaultFamily, defaultWeight, families, weights, styles) {
        const words = String(text || '').split(/\s+/).filter(Boolean);
        if (!words.length || wordsPerLine <= 0) return this._wrapTextMixed(text, maxWidth, letterSpacing, fontSize, defaultFamily, defaultWeight, families, weights, styles, 0);

        const out = [];
        let globalWordIndex = 0;
        for (let i = 0; i < words.length; i += wordsPerLine) {
            const chunkWords = words.slice(i, i + wordsPerLine);
            const chunkText = chunkWords.join(' ');
            const wrapped = this._wrapTextMixed(chunkText, maxWidth, letterSpacing, fontSize, defaultFamily, defaultWeight, families, weights, styles, globalWordIndex);
            out.push(...wrapped);
            globalWordIndex += chunkWords.length;
        }
        return out.length ? out : [''];
    }

    _wrapTextByWordCount(text, wordsPerLine, maxWidth, letterSpacing = 0) {
        const words = String(text || '').split(/\s+/).filter(Boolean);
        if (!words.length || wordsPerLine <= 0) return this._wrapText(text, maxWidth, letterSpacing);

        const chunks = [];
        for (let i = 0; i < words.length; i += wordsPerLine) {
            chunks.push(words.slice(i, i + wordsPerLine).join(' '));
        }

        const out = [];
        for (const chunk of chunks) {
            const wrapped = this._wrapText(chunk, maxWidth, letterSpacing);
            out.push(...wrapped);
        }
        return out.length ? out : [''];
    }

    _wrapLeadWordThenChunks(text, wordsPerChunk, maxWidth, letterSpacing = 0) {
        const words = String(text || '').split(/\s+/).filter(Boolean);
        if (words.length <= 1) return this._wrapText(text, maxWidth, letterSpacing);
        const first = words[0];
        const rest = words.slice(1).join(' ');
        const lines = [first];
        const restLines = this._wrapTextByWordCount(rest, Math.max(1, wordsPerChunk), maxWidth, letterSpacing);
        lines.push(...restLines);
        return lines;
    }

    _splitTokenToFit(token, maxWidth, letterSpacing = 0) {
        if (this._measureTextWidth(token, letterSpacing) <= maxWidth) return [token];
        const parts = [];
        let chunk = '';
        for (const ch of token) {
            const test = chunk + ch;
            if (!chunk || this._measureTextWidth(test, letterSpacing) <= maxWidth) {
                chunk = test;
            } else {
                parts.push(chunk);
                chunk = ch;
            }
        }
        if (chunk) parts.push(chunk);
        return parts.length ? parts : [token];
    }

    _splitTokenToFitMixed(token, maxWidth, letterSpacing, wordIdx, fontSize, defaultFamily, defaultWeight, families, weights, styles) {
        if (this._measureMixedWordWidth(token, wordIdx, fontSize, defaultFamily, defaultWeight, families, weights, styles, letterSpacing) <= maxWidth) return [token];
        const parts = [];
        let chunk = '';
        for (const ch of token) {
            const test = chunk + ch;
            if (!chunk || this._measureMixedWordWidth(test, wordIdx, fontSize, defaultFamily, defaultWeight, families, weights, styles, letterSpacing) <= maxWidth) {
                chunk = test;
            } else {
                parts.push(chunk);
                chunk = ch;
            }
        }
        if (chunk) parts.push(chunk);
        return parts.length ? parts : [token];
    }

    _measureMixedLineWidth(words, wordOffset, fontSize, defaultFamily, defaultWeight, families, weights, styles, letterSpacing = 0) {
        if (!words.length) return 0;
        let total = 0;
        for (let i = 0; i < words.length; i++) {
            const idx = wordOffset + i;
            total += this._measureMixedWordWidth(words[i], idx, fontSize, defaultFamily, defaultWeight, families, weights, styles, letterSpacing);
            if (i < words.length - 1) {
                total += this._measureMixedWordWidth(' ', idx + 1, fontSize, defaultFamily, defaultWeight, families, weights, styles, letterSpacing);
            }
        }
        return total;
    }

    _measureMixedWordWidth(word, wordIdx, fontSize, defaultFamily, defaultWeight, families, weights, styles, letterSpacing = 0) {
        const prevFont = this.ctx.font;
        this.ctx.font = this._mixedWordFont(wordIdx, fontSize, defaultFamily, defaultWeight, families, weights, styles);
        const width = this._measureTextWidth(word, letterSpacing);
        this.ctx.font = prevFont;
        return width;
    }

    _mixedWordFont(wordIdx, fontSize, defaultFamily, defaultWeight, families, weights, styles) {
        const family = families[wordIdx % families.length] || defaultFamily;
        const weight = weights[wordIdx % weights.length] || defaultWeight;
        const style = styles[wordIdx % styles.length] || 'normal';
        return `${style} ${weight} ${fontSize}px "${family}", sans-serif`;
    }

    _parseStyleList(raw, fallback = []) {
        if (Array.isArray(raw)) {
            const vals = raw.map(v => String(v || '').trim()).filter(Boolean);
            return vals.length ? vals : fallback;
        }
        if (typeof raw === 'string') {
            const vals = raw.split(',').map(v => v.trim()).filter(Boolean);
            return vals.length ? vals : fallback;
        }
        return fallback;
    }

    _measureTextWidth(text, letterSpacing = 0) {
        // ctx.letterSpacing is set on the canvas context before any measurement,
        // so ctx.measureText() already includes letter-spacing. No manual
        // compensation needed — adding it again would double-count.
        return this.ctx.measureText(text).width;
    }

    _hashToUnit(str) {
        // Stable 32-bit FNV-1a hash mapped to [0,1)
        let h = 0x811c9dc5;
        const s = String(str || '');
        for (let i = 0; i < s.length; i++) {
            h ^= s.charCodeAt(i);
            h = Math.imul(h, 0x01000193);
        }
        return (h >>> 0) / 4294967296;
    }

    /**
     * Clean up resources
     */
    destroy() {
        this.pause();
        this.imageCache.forEach(img => {
            if (img.src.startsWith('blob:')) {
                URL.revokeObjectURL(img.src);
            }
        });
        this.imageCache.clear();
    }
}
