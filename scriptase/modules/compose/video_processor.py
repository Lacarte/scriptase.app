"""
Video Processor
FFmpeg-based video processing for scene assembly and effects
"""

import json
import os
import re
import subprocess
import tempfile
import shutil
import hashlib
from PIL import Image, ImageDraw, ImageFont
import platform
from loguru import logger

from config import ROOT_DIR
from scriptase.shared.fonts import get_font_path as _custom_font_path
from scriptase.shared.ffmpeg_utils import find_ffmpeg, find_ffprobe

# Check if ffmpeg-python is available, fallback to subprocess
try:
    import ffmpeg
    USE_FFMPEG_PYTHON = True
except ImportError:
    USE_FFMPEG_PYTHON = False
    logger.warning("ffmpeg-python not installed, using subprocess fallback")
FFMPEG_BIN = find_ffmpeg() or "ffmpeg"
FFPROBE_BIN = find_ffprobe() or "ffprobe"


# Hook animation fallback map (resolves hook_animation → animation + emphasis
# when the frontend sends only the hook ID without resolved keys)
_HOOK_ANIMATION_MAP = {
    # Reveal family
    "creep_reveal":     ("blur_in",     "fade_stagger"),
    "slow_reveal":      ("stoic_fade",  "fade_stagger"),
    "soft_reveal":      ("fade",        "fade_stagger"),
    "deep_reveal":      ("blur_in",     "rise_word"),
    # Rise family
    "epic_rise":        ("rise",        "fade_stagger"),
    "gentle_rise":      ("rise",        "rise_word"),
    # Cinematic family
    "movie_title":      ("movie_title", "fade_stagger"),
    "title_card":       ("movie_title", "underline_sweep"),
    # Atmospheric family
    "drift_fade":       ("drift",       "fade_stagger"),
    "glow_emerge":      ("glow_pulse",  "glow_color"),
    "breathe_in":       ("breathe",     "fade_stagger"),
    # Impact family
    "hard_cut":         ("hard_cut",    "fade_stagger"),
    "drop_in":          ("drop_in",     "fade_stagger"),
    "slam_in":          ("slam",        "scale_burst"),
    # Slide family
    "slide_in":         ("slide_left",  "fade_stagger"),
    "slide_up":         ("slide_up",    "fade_stagger"),
    # Dark / tension family
    "flicker_in":       ("flicker",     "fade_stagger"),
    "glitch_in":        ("glitch",      "neon"),
    "void_emerge":      ("stoic_fade",  "disintegrate"),
}


def _resolve_hook(config):
    """Resolve hook_animation to animation + emphasis, using fallback map if needed."""
    hook = config.get("hook_animation") or ""
    animation = config.get("animation") or ""
    emphasis = config.get("emphasis") or "none"

    if not animation and hook in _HOOK_ANIMATION_MAP:
        animation, emphasis = _HOOK_ANIMATION_MAP[hook]
    if not animation:
        animation = "fade"
    return animation, emphasis


# Word emphasis: color palettes per emphasis type (used in PIL rendering)
# Each maps to a list of hex colors applied cyclically to emphasized words.
# None = no emphasis (draw all words in base color).
_EMPHASIS_COLOR_MAP = {
    'color_pop':       ['#FF6B6B', '#4ECDC4', '#FFB347', '#A78BFA', '#56CCF2', '#26DE81', '#FF8ED4'],
    'scale_burst':     ['#FFB347'],
    'wave':            ['#4ECDC4'],
    'glow_color':      ['#FF6B6B', '#4ECDC4', '#A78BFA', '#FFB347'],
    'shake_word':      ['#FF6B6B'],
    'typewriter_word': ['#4ECDC4'],
    'split_color':     ['#FF6B6B', '#4ECDC4'],
    'bounce_word':     ['#FFB347'],
    'fade_stagger':    ['#A78BFA'],
    'rise_word':       ['#56CCF2'],
    'underline_sweep': ['#FFB347'],
    'disintegrate':    ['#FF6B6B'],
    'neon':            ['#FF6B6B', '#4ECDC4', '#A78BFA', '#FF8ED4'],
    'bold_highlight':  ['#4ECDC4'],
}


# Font family mapping: frontend name -> system font paths by OS
# These match the fonts available in the frontend preview.js
FONT_MAP = {
    'Inter': {
        'win32': ['C:/Windows/Fonts/Inter-Regular.ttf', 'C:/Windows/Fonts/segoeui.ttf', 'arial.ttf'],
        'darwin': ['/System/Library/Fonts/SFCompact.ttf', '/Library/Fonts/Inter-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/inter/Inter-Regular.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    },
    'Roboto': {
        'win32': ['C:/Windows/Fonts/Roboto-Regular.ttf', 'arial.ttf'],
        'darwin': ['/Library/Fonts/Roboto-Regular.ttf', '/System/Library/Fonts/Helvetica.ttc'],
        'linux': ['/usr/share/fonts/truetype/roboto/Roboto-Regular.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    },
    'Open Sans': {
        'win32': ['C:/Windows/Fonts/OpenSans-Regular.ttf', 'arial.ttf'],
        'darwin': ['/Library/Fonts/OpenSans-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/open-sans/OpenSans-Regular.ttf']
    },
    'Montserrat': {
        'win32': ['C:/Windows/Fonts/Montserrat-Regular.ttf', 'arial.ttf'],
        'darwin': ['/Library/Fonts/Montserrat-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/montserrat/Montserrat-Regular.ttf']
    },
    'Poppins': {
        'win32': ['C:/Windows/Fonts/Poppins-Regular.ttf', 'arial.ttf'],
        'darwin': ['/Library/Fonts/Poppins-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/poppins/Poppins-Regular.ttf']
    },
    'Playfair Display': {
        'win32': ['C:/Windows/Fonts/PlayfairDisplay-Regular.ttf', 'times.ttf'],
        'darwin': ['/Library/Fonts/PlayfairDisplay-Regular.ttf', '/System/Library/Fonts/Times.ttc'],
        'linux': ['/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-Regular.ttf']
    },
    'Merriweather': {
        'win32': ['C:/Windows/Fonts/Merriweather-Regular.ttf', 'times.ttf'],
        'darwin': ['/Library/Fonts/Merriweather-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/merriweather/Merriweather-Regular.ttf']
    },
    'Lato': {
        'win32': ['C:/Windows/Fonts/Lato-Regular.ttf', 'arial.ttf'],
        'darwin': ['/Library/Fonts/Lato-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/lato/Lato-Regular.ttf']
    },
    'Oswald': {
        'win32': ['C:/Windows/Fonts/Oswald-Regular.ttf', 'arial.ttf'],
        'darwin': ['/Library/Fonts/Oswald-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/oswald/Oswald-Regular.ttf']
    },
    'Raleway': {
        'win32': ['C:/Windows/Fonts/Raleway-Regular.ttf', 'arial.ttf'],
        'darwin': ['/Library/Fonts/Raleway-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/raleway/Raleway-Regular.ttf']
    },
    'Bebas Neue': {
        'win32': ['C:/Windows/Fonts/BebasNeue-Regular.ttf', 'impact.ttf'],
        'darwin': ['/Library/Fonts/BebasNeue-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/bebas-neue/BebasNeue-Regular.ttf']
    },
    'Anton': {
        'win32': ['C:/Windows/Fonts/Anton-Regular.ttf', 'impact.ttf'],
        'darwin': ['/Library/Fonts/Anton-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/anton/Anton-Regular.ttf']
    },
    'Archivo Black': {
        'win32': ['C:/Windows/Fonts/ArchivoBlack-Regular.ttf', 'arialbd.ttf'],
        'darwin': ['/Library/Fonts/ArchivoBlack-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/archivo-black/ArchivoBlack-Regular.ttf']
    },
    'Bangers': {
        'win32': ['C:/Windows/Fonts/Bangers-Regular.ttf', 'comic.ttf'],
        'darwin': ['/Library/Fonts/Bangers-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/bangers/Bangers-Regular.ttf']
    },
    'Permanent Marker': {
        'win32': ['C:/Windows/Fonts/PermanentMarker-Regular.ttf', 'comic.ttf'],
        'darwin': ['/Library/Fonts/PermanentMarker-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/permanent-marker/PermanentMarker-Regular.ttf']
    },
    'Pacifico': {
        'win32': ['C:/Windows/Fonts/Pacifico-Regular.ttf', 'comic.ttf'],
        'darwin': ['/Library/Fonts/Pacifico-Regular.ttf'],
        'linux': ['/usr/share/fonts/truetype/pacifico/Pacifico-Regular.ttf']
    }
}

# Bold font variants mapping
FONT_BOLD_MAP = {
    'Inter': 'Inter-Bold.ttf',
    'Roboto': 'Roboto-Bold.ttf',
    'Open Sans': 'OpenSans-Bold.ttf',
    'Montserrat': 'Montserrat-Bold.ttf',
    'Poppins': 'Poppins-Bold.ttf',
    'Playfair Display': 'PlayfairDisplay-Bold.ttf',
    'Merriweather': 'Merriweather-Bold.ttf',
    'Lato': 'Lato-Bold.ttf',
    'Oswald': 'Oswald-Bold.ttf',
    'Raleway': 'Raleway-Bold.ttf',
}


class VideoProcessor:
    """Processes scenes into a final video using FFmpeg"""

    def __init__(self, export_data, progress_callback=None):
        self.export_data = export_data
        self.progress_callback = progress_callback or (lambda p, m: None)

        # Extract output settings
        output = export_data.get('output', {})
        resolution = output.get('resolution', {})
        # Ensure dimensions are even (required by most codecs / yuv420p)
        self.width = (resolution.get('width', 1080) // 2) * 2
        self.height = (resolution.get('height', 1920) // 2) * 2
        self.fps = output.get('fps', 30)
        self.codec = output.get('codec', 'libx264')
        self.pixel_format = output.get('pixel_format', 'yuv420p')
        self.preset = output.get('preset', 'medium')
        self.crf = output.get('crf', 23)

        # Base path for media files (relative to backend folder)
        self.media_base_path = export_data.get('media_base_path', '')

        # Resolve media relative to the repo root where app.py/output/animator live.
        self.backend_dir = os.path.dirname(os.path.abspath(__file__))
        self.project_root = ROOT_DIR
        self.frontend_dir = os.path.join(ROOT_DIR, 'frontend')

        logger.info("VideoProcessor init: {}x{} {}fps crf={} codec={} preset={}",
                     self.width, self.height, self.fps, self.crf, self.codec, self.preset)
        logger.debug("VideoProcessor paths: backend={} root={} frontend={}",
                      self.backend_dir, self.project_root, self.frontend_dir)
        logger.debug("VideoProcessor ffmpeg: {} (lib={})", FFMPEG_BIN, USE_FFMPEG_PYTHON)

    def _update_progress(self, progress, message):
        """Update progress callback"""
        self.progress_callback(progress, message)

    def _get_total_duration(self):
        """Resolve timeline duration from export payload, falling back to scene sum."""
        timeline = self.export_data.get('timeline', {}) or {}
        total_duration = timeline.get('total_duration')
        if total_duration:
            try:
                return float(total_duration)
            except (TypeError, ValueError):
                logger.debug("Invalid timeline total_duration: {}", total_duration)

        scene_total = 0.0
        for scene in self.export_data.get('scenes', []) or []:
            try:
                scene_total += float(scene.get('duration', 0) or 0)
            except (AttributeError, TypeError, ValueError):
                continue

        return scene_total if scene_total > 0 else 60.0

    def _get_caption_entries(self):
        """Accept both export-style captions.entries and editor-style captions.captions."""
        captions = self.export_data.get('captions')
        if not isinstance(captions, dict):
            return []

        entries = captions.get('entries')
        if isinstance(entries, list) and entries:
            return entries

        legacy_entries = captions.get('captions')
        if isinstance(legacy_entries, list):
            return legacy_entries

        return []

    def _get_media_path(self, relative_path):
        """Resolve media path from working-assets folder"""
        if not relative_path:
            logger.warning("Empty media path provided")
            return None

        raw_path = str(relative_path).strip()
        drive, _ = os.path.splitdrive(raw_path)
        is_url_style_path = raw_path.startswith(('/', '\\')) and not drive and not raw_path.startswith(('//', '\\\\'))
        candidate_path = raw_path.lstrip('/\\') if is_url_style_path else raw_path

        if os.path.isabs(raw_path) and not is_url_style_path:
            if os.path.exists(raw_path):
                return raw_path
            logger.error("Absolute media path does not exist: {}", raw_path)
            raise FileNotFoundError(f"Media file not found: {relative_path}")

        # Strip leading slash for URL-style paths (e.g. /output/animator/...)
        cleaned = candidate_path.lstrip('/\\')

        # Try paths relative to project root and frontend folder
        paths_to_try = [
            os.path.join(self.project_root, cleaned),
            os.path.join(self.frontend_dir, cleaned),
            os.path.join(self.project_root, raw_path),
            os.path.join(self.frontend_dir, raw_path),
            cleaned,
            raw_path,
        ]

        for path in paths_to_try:
            if os.path.exists(path):
                resolved = os.path.abspath(path)
                logger.debug("Resolved media: {} -> {}", relative_path, resolved)
                return resolved

        logger.error("Media not found. Tried: {}", paths_to_try)
        raise FileNotFoundError(f"Media file not found: {relative_path}")

    def _create_text_scene(self, scene, temp_dir, index):
        """Create a video clip for a text scene"""
        text_config = scene.get('text', {})
        duration = scene.get('duration', 3)
        background_cfg = text_config.get('background', {}) or {}
        use_solid_background = bool(background_cfg.get('enabled'))
        media = scene.get('media', {})
        media_path = media.get('path')

        if media_path and not use_solid_background:
            full_media_path = self._get_media_path(media_path)
            effect = scene.get('effect', {})
            base_output_path = os.path.join(temp_dir, f"text_base_{index:03d}.mp4")
            output_path = os.path.join(temp_dir, f"scene_{index:03d}.mp4")

            is_video_source = full_media_path.lower().endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv'))
            if is_video_source:
                self._create_scene_from_video(full_media_path, base_output_path, duration, effect)
            elif USE_FFMPEG_PYTHON:
                self._create_scene_ffmpeg(full_media_path, base_output_path, duration, effect)
            else:
                self._create_scene_subprocess(full_media_path, base_output_path, duration, effect)

            self._apply_scene_text_overlay(base_output_path, output_path, {
                'start_time': 0,
                'duration': duration,
                'content': text_config.get('content', ''),
                'color_hex': text_config.get('color_hex', '#ffffff'),
                'font_family': text_config.get('font_family', 'Inter'),
                'font_size': text_config.get('font_size', 48),
                'font_style': text_config.get('font_style', 'bold'),
                'hook_animation': text_config.get('hook_animation', ''),
                'animation': text_config.get('animation', 'fade'),
                'emphasis': text_config.get('emphasis', 'none'),
                'position': text_config.get('position', {}) or {},
                'text_align': text_config.get('text_align', 'center'),
                'vertical_align': text_config.get('vertical_align', 'center'),
                'background': {
                    'enabled': False,
                    'color': background_cfg.get('color', '#000000')
                }
            }, temp_dir, index)
            return output_path

        text_image_path = os.path.join(temp_dir, f"text_{index:03d}.png")
        self._render_text_image(text_config, text_image_path)

        output_path = os.path.join(temp_dir, f"scene_{index:03d}.mp4")

        if USE_FFMPEG_PYTHON:
            self._create_video_from_image_ffmpeg(text_image_path, output_path, duration)
        else:
            self._create_video_from_image_subprocess(text_image_path, output_path, duration)

        return output_path

    def _load_font(self, font_family, font_size, font_style='normal'):
        """Load font by family name with fallback support"""
        # Try custom fonts first (from fonts/ directory)
        variant = 'bold' if font_style == 'bold' else ('italic' if font_style == 'italic' else 'regular')
        if font_style == 'bold-italic':
            variant = 'bold_italic'
        custom_path = _custom_font_path(font_family, variant)
        if custom_path and os.path.isfile(custom_path):
            try:
                font = ImageFont.truetype(custom_path, font_size)
                logger.debug("Font loaded (custom): {} {} -> {}", font_family, variant, custom_path)
                return font
            except (OSError, IOError):
                logger.warning("Custom font file failed to load: {}", custom_path)

        current_os = platform.system().lower()
        os_key = 'win32' if current_os == 'windows' else ('darwin' if current_os == 'darwin' else 'linux')

        font_paths = []
        if font_family in FONT_MAP:
            # Create a copy so we can prepend bold variants without modifying the list we are iterating over
            font_paths = list(FONT_MAP[font_family].get(os_key, []))

            if font_style == 'bold' and font_family in FONT_BOLD_MAP:
                bold_name = FONT_BOLD_MAP[font_family]
                bold_paths_to_add = []
                for path in font_paths:
                    bold_path = path.replace('-Regular', '-Bold').replace('.ttf', '')
                    if '-Bold' not in bold_path:
                        bold_path = path.rsplit('.', 1)[0] + '-Bold.ttf'
                    bold_paths_to_add.append(bold_path)
                
                # Prepend the bold paths
                font_paths = bold_paths_to_add + font_paths

        fallback_fonts = [
            'arial.ttf', 'arialbd.ttf',
            'C:/Windows/Fonts/arial.ttf',
            'C:/Windows/Fonts/arialbd.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/System/Library/Fonts/Helvetica.ttc'
        ]
        font_paths.extend(fallback_fonts)

        for font_path in font_paths:
            try:
                font = ImageFont.truetype(font_path, font_size)
                logger.debug("Font loaded: {}", font_path)
                return font
            except (OSError, IOError):
                continue

        logger.warning("No font file found for '{}', using PIL default", font_family)
        return ImageFont.load_default()

    # ── Word emphasis: stop words (same as frontend) ─────────
    _EMPHASIS_STOP = frozenset([
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
        'only', 'own', 'same', 'too', 'still', 'already', 'yet',
    ])

    def _is_emphasis_word(self, word):
        clean = ''.join(c for c in word if c.isalpha()).lower()
        return len(clean) > 2 and clean not in self._EMPHASIS_STOP

    def _draw_line_with_emphasis(self, draw, line, x, y, font, font_family,
                                  font_size, font_style, base_color,
                                  emphasis_colors, emphasis_type):
        """Draw a line word-by-word, applying emphasis colors to keywords."""
        import re
        tokens = re.split(r'(\s+)', line)
        cursor_x = x
        word_idx = 0

        # Load a slightly larger bold font for emphasized words
        emphasis_font = self._load_font(font_family, int(font_size * 1.05), 'bold')

        for token in tokens:
            if not token.strip():
                # Whitespace — measure and advance
                bbox = draw.textbbox((0, 0), token, font=font)
                cursor_x += bbox[2] - bbox[0]
                continue

            if self._is_emphasis_word(token):
                color = emphasis_colors[word_idx % len(emphasis_colors)]
                use_font = emphasis_font

                if emphasis_type == 'bold_highlight':
                    # Draw highlight box behind word
                    bbox = draw.textbbox((cursor_x, y), token, font=use_font)
                    pad = 4
                    draw.rectangle(
                        [bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad],
                        fill=color + '40'  # 25% opacity hex
                    )

                draw.text((cursor_x, y), token, fill=color, font=use_font)
                bbox = draw.textbbox((0, 0), token, font=use_font)
                word_idx += 1
            else:
                draw.text((cursor_x, y), token, fill=base_color, font=font)
                bbox = draw.textbbox((0, 0), token, font=font)

            cursor_x += bbox[2] - bbox[0]

    def _render_text_image(self, text_config, output_path):
        """Render text overlay on background image or solid color"""
        content = text_config.get('content', '')
        # Clean text: strip special chars (keep letters, numbers, spaces, ! ? [ ]) and uppercase
        content = re.sub(r'[^\w\s!?\[\]]', '', content)
        content = re.sub(r'\s{2,}', ' ', content).strip().upper()
        color_hex = text_config.get('color_hex', '#ffffff')
        background = text_config.get('background', {})
        transparent_bg = bool(background.get('transparent'))

        font_family = text_config.get('font_family', 'Inter')
        font_size = text_config.get('font_size', 48)
        font_style = text_config.get('font_style', 'bold')

        position = text_config.get('position', {})
        text_x = position.get('x')
        text_y = position.get('y')

        text_align = text_config.get('text_align', 'center')
        vertical_align = text_config.get('vertical_align', 'center')

        logger.debug("Text scene: font={} {}px {} align={}/{} pos=({},{})",
                      font_family, font_size, font_style, text_align, vertical_align, text_x, text_y)

        # Try to load background image
        bg_image = None
        bg_image_path = background.get('image_path')
        if bg_image_path:
            try:
                full_path = self._get_media_path(bg_image_path)
                bg_image = Image.open(full_path).convert('RGBA')
                bg_image = bg_image.resize((self.width, self.height), Image.Resampling.LANCZOS)
                logger.debug("Text background image: {}", bg_image_path)
            except Exception as e:
                logger.warning("Could not load text background image: {}", e)
                bg_image = None

        if bg_image:
            img = bg_image
        else:
            fallback_color = background.get('fallback_color', '#000000')
            if transparent_bg:
                img = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
                logger.debug("Text transparent background")
            else:
                img = Image.new('RGB', (self.width, self.height), fallback_color)
                logger.debug("Text solid background: {}", fallback_color)

        draw = ImageDraw.Draw(img)
        font = self._load_font(font_family, font_size, font_style)

        padding = text_config.get('padding', 80)
        max_width = self.width - (padding * 2)
        lines = self._wrap_text(content, font, max_width, draw)

        line_height = font_size * 1.3
        total_height = len(lines) * line_height

        if text_y is not None:
            y = (text_y / 100) * self.height - (total_height / 2)
        else:
            if vertical_align == 'top':
                y = padding
            elif vertical_align == 'bottom':
                y = self.height - total_height - padding
            else:
                y = (self.height - total_height) / 2

        _, emphasis = _resolve_hook(text_config)
        emphasis_colors = _EMPHASIS_COLOR_MAP.get(emphasis)

        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]

            if text_x is not None:
                x = (text_x / 100) * self.width - (text_width / 2)
            else:
                if text_align == 'left':
                    x = padding
                elif text_align == 'right':
                    x = self.width - text_width - padding
                else:
                    x = (self.width - text_width) / 2

            x = max(padding / 2, min(x, self.width - text_width - padding / 2))

            if emphasis_colors:
                # Word-level emphasis: draw each word with emphasis color on keywords
                self._draw_line_with_emphasis(
                    draw, line, x, y, font, font_family, font_size, font_style,
                    color_hex, emphasis_colors, emphasis
                )
            else:
                draw.text((x, y), line, fill=color_hex, font=font)
            y += line_height

        img.save(output_path, 'PNG')
        logger.debug("Text image saved (emphasis={}): {}", emphasis, output_path)

    def _probe_duration(self, video_path):
        """Get duration of a video file in seconds via ffprobe."""
        try:
            r = subprocess.run(
                [FFPROBE_BIN, '-v', 'error',
                 '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
                capture_output=True, encoding='utf-8', errors='replace', timeout=10,
            )
            return float(r.stdout.strip())
        except Exception:
            return 0.0

    def _build_text_animation_filter(self, animation, start_time, duration, end_time):
        """Build FFmpeg filter chain for text animation on overlay input [1:v].

        Returns (overlay_prep_filter, overlay_x_expr, overlay_y_expr, alpha_filters)
        where overlay_prep_filter is applied to [1:v] before overlay, and
        alpha_filters are fade filters applied before the overlay filter.
        """
        S = f"{start_time:.3f}"
        E = f"{end_time:.3f}"
        D = f"{duration:.3f}"
        fade_in_d = min(0.4, duration * 0.15)
        fade_out_d = min(0.4, duration * 0.15)
        fade_out_st = max(start_time, end_time - fade_out_d)

        # Default: simple fade in/out, centered overlay at 0,0 (image is pre-positioned)
        alpha = f"fade=t=in:st={S}:d={fade_in_d:.3f}:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"
        prep = ""
        x_expr = "0"
        y_expr = "0"

        anim = animation or "fade"

        if anim == "fade":
            pass  # default alpha is fine

        elif anim == "stoic_fade":
            slow_in = min(1.0, duration * 0.3)
            slow_out = min(1.0, duration * 0.3)
            slow_out_st = max(start_time, end_time - slow_out)
            alpha = f"fade=t=in:st={S}:d={slow_in:.3f}:alpha=1,fade=t=out:st={slow_out_st:.3f}:d={slow_out:.3f}:alpha=1"

        elif anim == "slide_up":
            fin = min(0.5, duration * 0.2)
            # Slide from 15% below to 0
            y_expr = f"if(lt(t,{start_time + fin:.3f}),(1-((t-{S})/{fin:.3f}))*h*0.15,0)"
            alpha = f"fade=t=in:st={S}:d={fin:.3f}:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"

        elif anim == "slide_left":
            fin = min(0.5, duration * 0.2)
            x_expr = f"if(lt(t,{start_time + fin:.3f}),(1-((t-{S})/{fin:.3f}))*W*0.2,0)"
            alpha = f"fade=t=in:st={S}:d={fin:.3f}:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"

        elif anim == "slide_right":
            fin = min(0.5, duration * 0.2)
            x_expr = f"if(lt(t,{start_time + fin:.3f}),-(1-((t-{S})/{fin:.3f}))*W*0.2,0)"
            alpha = f"fade=t=in:st={S}:d={fin:.3f}:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"

        elif anim == "drop_in":
            fin = min(0.4, duration * 0.15)
            y_expr = f"if(lt(t,{start_time + fin:.3f}),-(1-((t-{S})/{fin:.3f}))*H*0.3,0)"
            alpha = f"fade=t=in:st={S}:d={fin:.3f}:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"

        elif anim == "rise":
            fin = min(0.6, duration * 0.25)
            y_expr = f"if(lt(t,{start_time + fin:.3f}),(1-((t-{S})/{fin:.3f}))*h*0.05,0)"
            alpha = f"fade=t=in:st={S}:d={fin:.3f}:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"

        elif anim in ("slam", "zoom_burst", "scale_pop", "expand", "bounce"):
            # Scale animations — use zoompan or scale on the overlay before overlay
            # Scale from 1.3x to 1x quickly (slam effect)
            scale_d = min(0.3, duration * 0.12)
            if anim == "slam":
                prep = f"scale=iw*1.3:ih*1.3:eval=init,fade=t=in:st={S}:d=0.08:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"
            elif anim == "zoom_burst":
                prep = f"scale=iw*1.4:ih*1.4:eval=init,fade=t=in:st={S}:d=0.06:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"
            elif anim == "bounce":
                prep = f"scale=iw*1.15:ih*1.15:eval=init,fade=t=in:st={S}:d=0.1:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"
            elif anim == "expand":
                prep = f"fade=t=in:st={S}:d={min(0.6, duration * 0.25):.3f}:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"
            else:  # scale_pop
                prep = f"scale=iw*1.12:ih*1.12:eval=init,fade=t=in:st={S}:d=0.1:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"
            # Center the scaled overlay
            x_expr = "(W-w)/2"
            y_expr = "(H-h)/2"
            alpha = ""  # already in prep

        elif anim == "movie_title":
            # Slow fade in, slight zoom via scale
            slow_in = min(0.8, duration * 0.3)
            slow_out = min(0.6, duration * 0.25)
            slow_out_st = max(start_time, end_time - slow_out)
            prep = f"scale=iw*1.04:ih*1.04:eval=init,fade=t=in:st={S}:d={slow_in:.3f}:alpha=1,fade=t=out:st={slow_out_st:.3f}:d={slow_out:.3f}:alpha=1"
            x_expr = "(W-w)/2"
            y_expr = "(H-h)/2"
            alpha = ""

        elif anim == "shake":
            # Shake via oscillating x/y offset
            x_expr = f"if(between(t,{S},{E}),4*sin(t*60),0)"
            y_expr = f"if(between(t,{S},{E}),2*cos(t*47),0)"

        elif anim == "drift":
            # Gentle lateral drift
            x_expr = f"if(between(t,{S},{E}),sin((t-{S})*3.14*2)*W*0.015,0)"
            y_expr = f"if(between(t,{S},{E}),cos((t-{S})*3.14*1.5)*H*0.008,0)"
            slow_in = min(0.6, duration * 0.2)
            slow_out = min(0.6, duration * 0.2)
            slow_out_st = max(start_time, end_time - slow_out)
            alpha = f"fade=t=in:st={S}:d={slow_in:.3f}:alpha=1,fade=t=out:st={slow_out_st:.3f}:d={slow_out:.3f}:alpha=1"

        elif anim == "pulse":
            # Rhythmic scale pulse — approximated with slight x/y jitter
            x_expr = f"if(between(t,{S},{E}),sin(t*25)*2,0)"
            y_expr = f"if(between(t,{S},{E}),cos(t*25)*1,0)"

        elif anim in ("flicker", "glitch"):
            # Flicker/glitch — rapid alpha toggling via very short fade cycles
            flicker_in = min(0.15, duration * 0.1)
            alpha = (
                f"fade=t=in:st={S}:d={flicker_in:.3f}:alpha=1,"
                f"fade=t=out:st={start_time + flicker_in:.3f}:d=0.03:alpha=1,"
                f"fade=t=in:st={start_time + flicker_in + 0.03:.3f}:d=0.02:alpha=1,"
                f"fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"
            )
            if anim == "glitch":
                x_expr = f"if(between(t,{S},{start_time + 0.3:.3f}),sin(t*120)*6,0)"

        elif anim == "breathe":
            # Gentle slow fade
            slow_in = min(0.7, duration * 0.25)
            slow_out = min(0.7, duration * 0.25)
            slow_out_st = max(start_time, end_time - slow_out)
            alpha = f"fade=t=in:st={S}:d={slow_in:.3f}:alpha=1,fade=t=out:st={slow_out_st:.3f}:d={slow_out:.3f}:alpha=1"

        elif anim == "rotate_in":
            # Rotation not easily done with overlay alone; use fade + slide
            fin = min(0.4, duration * 0.2)
            x_expr = f"if(lt(t,{start_time + fin:.3f}),(1-((t-{S})/{fin:.3f}))*W*0.05,0)"
            y_expr = f"if(lt(t,{start_time + fin:.3f}),(1-((t-{S})/{fin:.3f}))*H*-0.02,0)"
            alpha = f"fade=t=in:st={S}:d={fin:.3f}:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"

        elif anim == "split_reveal":
            # Vertical scale reveal — approximated with fast fade
            fast_in = min(0.2, duration * 0.1)
            alpha = f"fade=t=in:st={S}:d={fast_in:.3f}:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"

        elif anim == "hard_cut":
            alpha = ""  # No fade at all — just enable/disable via overlay timing

        elif anim == "typewriter":
            # Fast fade in, hold, clean fade out
            fast_in = min(0.15, duration * 0.08)
            alpha = f"fade=t=in:st={S}:d={fast_in:.3f}:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"

        elif anim == "glow_pulse":
            # Gentle fade with slightly longer hold
            alpha = f"fade=t=in:st={S}:d={fade_in_d:.3f}:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"

        elif anim == "blur_in":
            # Longer fade in to simulate de-blur
            blur_in = min(0.5, duration * 0.2)
            alpha = f"fade=t=in:st={S}:d={blur_in:.3f}:alpha=1,fade=t=out:st={fade_out_st:.3f}:d={fade_out_d:.3f}:alpha=1"

        return prep, x_expr, y_expr, alpha

    def _render_sequential_word_overlay(self, input_path, output_path, overlay_config, temp_dir, index):
        """Render emphasis words sequentially — one at a time as separate overlays."""
        content = overlay_config.get('content', '')
        content = re.sub(r'[^\w\s!?\[\]]', '', content).strip().upper()
        duration = max(0.0, float(overlay_config.get('duration', 0) or 0))
        start_time = max(0.0, float(overlay_config.get('start_time', 0) or 0))

        # Extract emphasis words
        words_raw = content.split()
        words = [w.upper() for w in words_raw
                 if len(re.sub(r'[^a-zA-Z]', '', w)) > 2
                 and re.sub(r'[^a-zA-Z]', '', w).lower() not in self._EMPHASIS_STOP]
        if not words:
            words = [w.upper() for w in words_raw if len(w) > 1][:5]
        if not words:
            shutil.copy2(input_path, output_path)
            return

        font_family = overlay_config.get('font_family', 'Inter')
        font_size = int(overlay_config.get('font_size', 48) * 1.4)
        color_hex = overlay_config.get('color_hex', '#ffffff')

        video_dur = self._probe_duration(input_path)
        if video_dur <= 0:
            video_dur = 120

        # Timing: 85% active, 15% exit buffer
        active_dur = duration * 0.85
        slot_dur = active_dur / len(words)

        # Render each word as a separate transparent PNG
        word_images = []
        font = self._load_font(font_family, font_size, 'bold')
        for i, word in enumerate(words):
            img = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            bbox = draw.textbbox((0, 0), word, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x = (self.width - tw) / 2
            y = (self.height - th) / 2
            draw.text((x, y), word, fill=color_hex, font=font)
            word_path = os.path.join(temp_dir, f"scene_{index:03d}_word_{i:02d}.png")
            img.save(word_path, 'PNG')
            word_images.append(word_path)

        # Build FFmpeg filter: each word overlay with timed fade in/out
        inputs = ['-i', input_path]
        for wp in word_images:
            inputs += ['-loop', '1', '-t', f'{video_dur:.3f}', '-i', wp]

        filter_parts = []
        current = '[0:v]'
        for i, word in enumerate(words):
            ws = start_time + i * slot_dur
            we = ws + slot_dur
            fade_in = min(0.15, slot_dur * 0.18)
            fade_out = min(0.2, slot_dur * 0.22)
            fade_out_st = max(ws, we - fade_out)

            ov_label = f'[{i+1}:v]'
            prep_label = f'[ov{i}]'
            out_label = f'[v{i}]'

            filter_parts.append(
                f"{ov_label}format=rgba,"
                f"fade=t=in:st={ws:.3f}:d={fade_in:.3f}:alpha=1,"
                f"fade=t=out:st={fade_out_st:.3f}:d={fade_out:.3f}:alpha=1"
                f"{prep_label}"
            )
            filter_parts.append(
                f"{current}{prep_label}overlay=0:0:enable='between(t,{ws:.3f},{we:.3f})':format=auto{out_label}"
            )
            current = out_label

        filter_complex = ';'.join(filter_parts)

        cmd = [
            FFMPEG_BIN, '-y',
            *inputs,
            '-filter_complex', filter_complex,
            '-map', current,
            '-map', '0:a?',
            '-c:v', self.codec, '-preset', self.preset, '-crf', str(self.crf),
            '-pix_fmt', self.pixel_format,
            '-c:a', 'copy',
            '-t', f'{video_dur:.3f}',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=600)
        if result.returncode != 0:
            logger.error("Sequential word overlay failed: {}", result.stderr[-700:] if result.stderr else '')
            shutil.copy2(input_path, output_path)
        else:
            logger.info("Sequential word overlay: {} words rendered for scene {}", len(words), index)

    def _apply_scene_text_overlay(self, input_path, output_path, overlay_config, temp_dir, index):
        """Burn a timed, animated text overlay onto a rendered image/video scene clip."""
        duration = max(0.0, float(overlay_config.get('duration', 0) or 0))
        if duration <= 0:
            shutil.copy2(input_path, output_path)
            return

        # If hook_animation is set, use sequential word rendering
        hook = overlay_config.get('hook_animation', '')
        if hook and hook in _HOOK_ANIMATION_MAP:
            self._render_sequential_word_overlay(input_path, output_path, overlay_config, temp_dir, index)
            return

        bg_cfg = overlay_config.get('background', {}) or {}
        overlay_text_cfg = {
            'content': overlay_config.get('content', ''),
            'color_hex': overlay_config.get('color_hex', '#ffffff'),
            'font_family': overlay_config.get('font_family', 'Inter'),
            'font_size': overlay_config.get('font_size', 48),
            'font_style': overlay_config.get('font_style', 'bold'),
            'emphasis': overlay_config.get('emphasis', 'none'),
            'position': overlay_config.get('position', {}) or {},
            'text_align': overlay_config.get('text_align', 'center'),
            'vertical_align': overlay_config.get('vertical_align', 'center'),
            'background': {
                'transparent': not bg_cfg.get('enabled'),
                'fallback_color': bg_cfg.get('color', '#000000')
            }
        }

        overlay_image_path = os.path.join(temp_dir, f"scene_{index:03d}_text_overlay.png")
        self._render_text_image(overlay_text_cfg, overlay_image_path)

        video_dur = self._probe_duration(input_path)
        if video_dur <= 0:
            video_dur = 120

        start_time = max(0.0, float(overlay_config.get('start_time', 0) or 0))
        end_time = start_time + duration
        animation, _ = _resolve_hook(overlay_config)

        prep, x_expr, y_expr, alpha_filters = self._build_text_animation_filter(
            animation, start_time, duration, end_time
        )

        # Build filter chain for overlay input
        ov_chain = "[1:v]format=rgba"
        if prep:
            ov_chain += f",{prep}"
        if alpha_filters:
            ov_chain += f",{alpha_filters}"
        ov_chain += "[ov]"

        enable = f"enable='between(t,{start_time:.3f},{end_time:.3f})'"
        filter_complex = (
            f"{ov_chain};"
            f"[0:v][ov]overlay={x_expr}:{y_expr}:{enable}:format=auto[v]"
        )

        cmd = [
            FFMPEG_BIN, '-y',
            '-i', input_path,
            '-loop', '1', '-t', f'{video_dur:.3f}', '-i', overlay_image_path,
            '-filter_complex', filter_complex,
            '-map', '[v]',
            '-map', '0:a?',
            '-c:v', self.codec, '-preset', self.preset, '-crf', str(self.crf),
            '-pix_fmt', self.pixel_format,
            '-c:a', 'copy',
            '-t', f'{video_dur:.3f}',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=600)
        if result.returncode != 0:
            logger.error("Scene text overlay failed (anim={}): {}", animation, result.stderr[-700:] if result.stderr else '')
            shutil.copy2(input_path, output_path)
        else:
            logger.info("Scene text overlay applied (anim={}): {}", animation, os.path.basename(output_path))

    def _wrap_text(self, text, font, max_width, draw):
        """Wrap text to fit within max_width"""
        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test_line, font=font)
            width = bbox[2] - bbox[0]

            if width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        return lines

    def _create_scene_clip(self, scene, temp_dir, index):
        """Create a video clip for a single scene"""
        media = scene.get('media', {})
        media_type = media.get('type', 'image')
        scene_id = scene.get('id', index + 1)

        logger.debug("Scene {}: type={}", scene_id, media_type)

        # Handle text scenes
        if media_type == 'text':
            logger.debug("Scene {}: creating text scene", scene_id)
            return self._create_text_scene(scene, temp_dir, index)

        # Handle image/video scenes
        media_path = media.get('path')
        if not media_path:
            logger.error("Scene {} has no media path", scene_id)
            raise ValueError(f"Scene {scene_id} has no media path")

        logger.debug("Scene {}: looking for media: {}", scene_id, media_path)

        try:
            full_media_path = self._get_media_path(media_path)
            logger.debug("Scene {}: resolved media: {}", scene_id, full_media_path)
        except FileNotFoundError as e:
            logger.error("Scene {}: media not found: {}", scene_id, e)
            raise

        duration = scene.get('duration', 3)
        effect = scene.get('effect', {})
        effect_type = effect.get('type', 'static')

        logger.info("Scene {}: {}s effect={} path={}",
                     scene_id, duration, effect_type, os.path.basename(full_media_path))

        output_path = os.path.join(temp_dir, f"scene_{index:03d}.mp4")

        # Detect video source files
        is_video_source = full_media_path.lower().endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv'))

        if is_video_source:
            # Probe the video to verify it's valid before heavy processing
            probe = self._probe_video(full_media_path)
            if probe and probe['width'] > 0 and probe['height'] > 0:
                self._create_scene_from_video(full_media_path, output_path, duration, effect)
            else:
                # Video is invalid/corrupt — try extracting first frame as image
                logger.warning("Scene {}: video probe failed or empty, falling back to image",
                               scene_id)
                fallback_img = os.path.join(temp_dir, f"scene_{index:03d}_probe_fb.jpg")
                if self._extract_first_frame(full_media_path, fallback_img):
                    logger.info("Scene {}: using extracted frame as static image", scene_id)
                    self._create_scene_subprocess(fallback_img, output_path, duration, effect)
                else:
                    logger.error("Scene {}: video unusable and frame extraction failed", scene_id)
                    raise RuntimeError(f"Scene {scene_id}: video file is corrupt")
        elif USE_FFMPEG_PYTHON:
            self._create_scene_ffmpeg(full_media_path, output_path, duration, effect)
        else:
            self._create_scene_subprocess(full_media_path, output_path, duration, effect)

        # Verify output was created
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            logger.debug("Scene {}: output {} ({:.1f} KB)", scene_id, output_path, size / 1024)
        else:
            logger.error("Scene {}: output file was NOT created: {}", scene_id, output_path)

        text_overlay = scene.get('text_overlay') or {}
        if text_overlay.get('content') and float(text_overlay.get('duration', 0) or 0) > 0:
            overlaid_output_path = os.path.join(temp_dir, f"scene_{index:03d}_overlay.mp4")
            self._apply_scene_text_overlay(output_path, overlaid_output_path, text_overlay, temp_dir, index)
            return overlaid_output_path

        return output_path

    # Supported blend modes mapping (CSS name → ffmpeg blend mode)
    _BLEND_MAP = {
        'normal': None,  # uses overlay filter
        'screen': 'screen',
        'multiply': 'multiply',
        'overlay': 'overlay',
        'soft-light': 'softlight',
        'hard-light': 'hardlight',
        'lighten': 'lighten',
        'darken': 'darken',
        'color-dodge': 'dodge',
    }

    def _apply_overlay(self, input_path, output_path, overlay_entry):
        """Composite an overlay PNG on top of the full video using ffmpeg.

        overlay_entry can be a URL string or a dict with
        {url, opacity, blend} keys.
        """
        if isinstance(overlay_entry, str):
            overlay_url = overlay_entry
            opacity = 1.0
            blend = 'normal'
        else:
            overlay_url = overlay_entry.get('url', '')
            opacity = max(0.0, min(1.0, float(overlay_entry.get('opacity', 1.0))))
            blend = overlay_entry.get('blend', 'normal') or 'normal'

        rel = overlay_url.lstrip('/')
        overlay_path = os.path.join(self.project_root, rel)
        if not os.path.exists(overlay_path):
            logger.warning("Overlay not found: {} (resolved: {})", overlay_url, overlay_path)
            shutil.copy2(input_path, output_path)
            return

        logger.info("Applying overlay: {} (opacity={}, blend={})", os.path.basename(overlay_path), opacity, blend)

        # Build alpha adjustment (colorchannelmixer adjusts overlay alpha)
        alpha_filter = f',colorchannelmixer=aa={opacity:.2f}' if opacity < 1.0 else ''
        ff_blend = self._BLEND_MAP.get(blend)

        if ff_blend:
            # Blend mode: use ffmpeg blend filter
            filter_complex = (
                f'[1:v]scale={self.width}:{self.height}:flags=lanczos,format=rgba{alpha_filter}[ov];'
                f'[0:v][ov]blend=all_mode={ff_blend}:all_opacity=1'
            )
        else:
            # Normal mode: standard overlay compositing
            filter_complex = (
                f'[1:v]scale={self.width}:{self.height}:flags=lanczos,format=rgba{alpha_filter}[ov];'
                f'[0:v][ov]overlay=0:0:format=auto'
            )

        cmd = [
            FFMPEG_BIN, '-y',
            '-i', input_path,
            '-i', overlay_path,
            '-filter_complex', filter_complex,
            '-map', '0:a?',
            '-c:v', self.codec, '-preset', self.preset, '-crf', str(self.crf),
            '-pix_fmt', 'yuv420p',
            '-c:a', 'copy',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=600)
        if result.returncode != 0:
            logger.error("Overlay compositing failed: {}", result.stderr[-500:] if result.stderr else '')
            shutil.copy2(input_path, output_path)
        else:
            logger.info("Overlay applied successfully")

    @staticmethod
    def _overlay_url(entry):
        """Extract URL from an overlay entry (string or dict)."""
        if isinstance(entry, str):
            return entry
        return entry.get('url', '') if isinstance(entry, dict) else ''

    def _is_white_dot_grain_overlay(self, overlay_entry):
        """Return True if overlay URL should use animated white-dot grain pass."""
        url = self._overlay_url(overlay_entry)
        if not url:
            return False
        name = os.path.basename(str(url)).lower()
        return name in ("grain-noise.png", "white-dot-grain", "white-dot-grain.png")

    def _apply_white_dot_grain_overlay(self, input_path, output_path, cfg=None):
        """Apply animated white-dot grain (screen blend + fade envelope)."""
        cfg = cfg or {}
        opacity = max(0.0, min(1.0, float(cfg.get('opacity', 0.16))))
        start = max(0.0, float(cfg.get('start', 0.0)))
        fade_in = max(0.0, float(cfg.get('fade_in', cfg.get('fadeIn', 0.12))))
        hold = max(0.0, float(cfg.get('hold', 0.65)))
        fade_out = max(0.0, float(cfg.get('fade_out', cfg.get('fadeOut', 1.2))))
        noise_strength = max(0, min(100, int(cfg.get('noise_strength', cfg.get('noiseStrength', 88)))))
        threshold = max(0, min(255, int(cfg.get('threshold', 246))))
        fade_out_start = start + fade_in + hold

        envelope = (
            f"fade=t=in:st={start:.3f}:d={fade_in:.3f}:alpha=1,"
            f"fade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}:alpha=1"
        )
        grain_chain = (
            f"format=gray,noise=alls={noise_strength}:allf=t+u,"
            f"eq=contrast=2.0:brightness=-0.05,"
            f"lutyuv=y='if(gt(val\\,{threshold}),255,0)',"
            f"format=rgba,colorchannelmixer=aa=1.0,{envelope}"
        )
        filter_complex = (
            f"[1:v]{grain_chain}[grain];"
            f"[0:v]format=rgba[base];"
            f"[base][grain]blend=all_mode=screen:all_opacity={opacity:.3f},format={self.pixel_format}[v]"
        )

        logger.info(
            "Applying white-dot grain: opacity={} start={} fade_in={} hold={} fade_out={} noise={} threshold={}",
            opacity, start, fade_in, hold, fade_out, noise_strength, threshold
        )
        cmd = [
            FFMPEG_BIN, '-y',
            '-i', input_path,
            '-f', 'lavfi', '-i', f"color=c=black:s={self.width}x{self.height}:r={self.fps}",
            '-filter_complex', filter_complex,
            '-map', '[v]',
            '-map', '0:a?',
            '-c:v', self.codec, '-preset', self.preset, '-crf', str(self.crf),
            '-pix_fmt', self.pixel_format,
            '-c:a', 'copy',
            '-shortest',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=900)
        if result.returncode != 0:
            logger.error("White-dot grain overlay failed: {}", result.stderr[-700:] if result.stderr else '')
            shutil.copy2(input_path, output_path)
        else:
            logger.info("White-dot grain overlay applied")

    def _apply_logo_overlay(self, input_path, output_path, cfg=None):
        """Composite a managed branding image at a profile-relative position."""
        cfg = cfg or {}
        logo_url = str(cfg.get('path') or cfg.get('url') or '').replace('\\', '/')
        rel = logo_url.lstrip('/')
        logo_path = os.path.abspath(os.path.join(self.project_root, rel))
        branding_root = os.path.abspath(os.path.join(self.project_root, 'output', 'branding'))
        try:
            managed = os.path.commonpath([branding_root, logo_path]) == branding_root
        except ValueError:
            managed = False
        if not managed or not os.path.isfile(logo_path):
            raise ValueError("Logo overlay must reference an existing managed branding asset")

        size = max(2.0, min(40.0, float(cfg.get('size', 10))))
        opacity = max(0.05, min(1.0, float(cfg.get('opacity', 0.9))))
        margin = max(0, min(200, int(cfg.get('margin', 32))))
        position = cfg.get('position', 'top_right')
        positions = {
            'top_left': (str(margin), str(margin)),
            'top_center': ('(W-w)/2', str(margin)),
            'top_right': (f'W-w-{margin}', str(margin)),
            'middle_left': (str(margin), '(H-h)/2'),
            'center': ('(W-w)/2', '(H-h)/2'),
            'middle_right': (f'W-w-{margin}', '(H-h)/2'),
            'bottom_left': (str(margin), f'H-h-{margin}'),
            'bottom_center': ('(W-w)/2', f'H-h-{margin}'),
            'bottom_right': (f'W-w-{margin}', f'H-h-{margin}'),
        }
        x, y = positions.get(position, positions['top_right'])
        logo_width = max(2, int(round(self.width * size / 100.0)))
        filter_complex = (
            f"[1:v]scale={logo_width}:-2:flags=lanczos,format=rgba,"
            f"colorchannelmixer=aa={opacity:.3f}[logo];"
            f"[0:v][logo]overlay=x={x}:y={y}:format=auto,format={self.pixel_format}[v]"
        )
        cmd = [
            FFMPEG_BIN, '-y', '-i', input_path, '-i', logo_path,
            '-filter_complex', filter_complex, '-map', '[v]', '-map', '0:a?',
            '-c:v', self.codec, '-preset', self.preset, '-crf', str(self.crf),
            '-pix_fmt', self.pixel_format, '-c:a', 'copy', output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"Logo overlay failed: {(result.stderr or '')[-700:]}")
        logger.info("Logo overlay applied: position={} size={} opacity={}", position, size, opacity)

    def _create_video_from_image_ffmpeg(self, image_path, output_path, duration):
        """Create video from static image using ffmpeg-python"""
        logger.debug("ffmpeg-python: image->video {}s {}", duration, image_path)
        (
            ffmpeg
            .input(image_path, loop=1, t=duration)
            .filter('scale', w=self.width, h=self.height)
            .output(
                output_path,
                vcodec=self.codec,
                pix_fmt=self.pixel_format,
                r=self.fps,
                crf=self.crf,
                preset=self.preset
            )
            .overwrite_output()
            .run(cmd=FFMPEG_BIN, quiet=True)
        )

    def _create_video_from_image_subprocess(self, image_path, output_path, duration):
        """Create video from static image using subprocess"""
        cmd = [
            FFMPEG_BIN, '-y',
            '-loop', '1',
            '-i', image_path,
            '-t', str(duration),
            '-vf', f'scale={self.width}:{self.height}',
            '-c:v', self.codec,
            '-pix_fmt', self.pixel_format,
            '-r', str(self.fps),
            '-crf', str(self.crf),
            '-preset', self.preset,
            output_path
        ]
        logger.debug("subprocess: image->video cmd={}", ' '.join(cmd[:8]) + '...')
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=300)
        if result.returncode != 0:
            logger.error("FFmpeg image->video failed: {}", result.stderr[:500])
            raise RuntimeError(f"FFmpeg failed: {result.stderr[:200]}")

    def _create_scene_ffmpeg(self, media_path, output_path, duration, effect):
        """Create scene video with effects using ffmpeg-python"""
        effect_type = effect.get('type', 'static')

        logger.debug("Creating {}s clip: effect={}", duration, effect_type)

        if effect_type in ['static', 'fade']:
            self._create_simple_scene(media_path, output_path, duration, effect_type)
            return

        self._create_effect_scene(media_path, output_path, duration, effect)

    def _create_simple_scene(self, media_path, output_path, duration, effect_type):
        """Fast method for static/fade scenes without zoompan"""
        filters = [
            f"scale='if(gte(iw/ih,{self.width}/{self.height}),-2,{self.width})':'if(gte(iw/ih,{self.width}/{self.height}),{self.height},-2)'",
            f"crop={self.width}:{self.height}",
            f"fps={self.fps}"
        ]

        if effect_type == 'fade':
            fade_dur = min(0.5, duration / 2)
            filters.append(f"fade=t=in:st=0:d={fade_dur}")
            filters.append(f"fade=t=out:st={duration - fade_dur}:d={fade_dur}")

        filters.append(f"format={self.pixel_format}")
        vf = ','.join(filters)

        cmd = [
            FFMPEG_BIN, '-y',
            '-loop', '1',
            '-i', media_path,
            '-t', str(duration),
            '-vf', vf,
            '-c:v', self.codec,
            '-pix_fmt', self.pixel_format,
            '-preset', 'fast',
            '-crf', str(self.crf),
            output_path
        ]

        logger.debug("Simple scene cmd: {}", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=300)
        if result.returncode != 0:
            stderr = result.stderr or ""
            if len(stderr) > 1500:
                stderr_summary = stderr[:750] + "\n...\n" + stderr[-750:]
            else:
                stderr_summary = stderr
            logger.error("FFmpeg simple scene failed:\nstdout: {}\nstderr: {}",
                          result.stdout[:500], stderr_summary)
            raise RuntimeError(f"FFmpeg simple scene failed: {stderr_summary}")

    def _create_effect_scene(self, media_path, output_path, duration, effect):
        """Create scene with zoom/pan effects using zoompan filter (for image sources)"""
        effect_type = effect.get('type', 'static')
        frames = int(duration * self.fps)
        zoompan_fps = 25
        zoompan_frames = int(duration * zoompan_fps)

        if effect_type == 'zoom_in':
            start_scale = effect.get('start_scale', 1.0)
            end_scale = effect.get('end_scale', 1.2)
            z_expr = f"'min({start_scale}+on*{(end_scale-start_scale)/zoompan_frames},{end_scale})'"
            x_expr = "'iw/2-(iw/zoom/2)'"
            y_expr = "'ih/2-(ih/zoom/2)'"
        elif effect_type == 'zoom_out':
            start_scale = effect.get('start_scale', 1.2)
            end_scale = effect.get('end_scale', 1.0)
            z_expr = f"'max({start_scale}-on*{(start_scale-end_scale)/zoompan_frames},{end_scale})'"
            x_expr = "'iw/2-(iw/zoom/2)'"
            y_expr = "'ih/2-(ih/zoom/2)'"
        elif effect_type == 'pan_left':
            pan_amount = effect.get('pan_amount', 0.2)
            z_expr = "'1.1'"
            x_expr = f"'iw*{pan_amount}*(1-on/{zoompan_frames})'"
            y_expr = "'(ih-oh)/2'"
        elif effect_type == 'pan_right':
            pan_amount = effect.get('pan_amount', 0.2)
            z_expr = "'1.1'"
            x_expr = f"'iw*{pan_amount}*on/{zoompan_frames}'"
            y_expr = "'(ih-oh)/2'"
        elif effect_type == 'pan_up':
            pan_amount = effect.get('pan_amount', 0.2)
            z_expr = "'1.1'"
            x_expr = "'iw/2-(iw/zoom/2)'"
            y_expr = f"'ih*{pan_amount}*(1-on/{zoompan_frames})'"
        elif effect_type == 'pan_down':
            pan_amount = effect.get('pan_amount', 0.2)
            z_expr = "'1.1'"
            x_expr = "'iw/2-(iw/zoom/2)'"
            y_expr = f"'ih*{pan_amount}*on/{zoompan_frames}'"
        elif effect_type == 'pan_diagonal_tl':
            pan_amount = effect.get('pan_amount', 0.15)
            z_expr = "'1.1'"
            x_expr = f"'iw*{pan_amount}*(1-on/{zoompan_frames})'"
            y_expr = f"'ih*{pan_amount}*(1-on/{zoompan_frames})'"
        elif effect_type == 'pan_diagonal_br':
            pan_amount = effect.get('pan_amount', 0.15)
            z_expr = "'1.1'"
            x_expr = f"'iw*{pan_amount}*on/{zoompan_frames}'"
            y_expr = f"'ih*{pan_amount}*on/{zoompan_frames}'"
        elif effect_type == 'ken_burns':
            start_scale = effect.get('start_scale', 1.0)
            end_scale = effect.get('end_scale', 1.15)
            pan_amount = effect.get('pan_amount', 0.05)
            z_expr = f"'min({start_scale}+on*{(end_scale-start_scale)/zoompan_frames},{end_scale})'"
            x_expr = f"'iw/2-(iw/zoom/2)+iw*{pan_amount}*on/{zoompan_frames}'"
            y_expr = "'ih/2-(ih/zoom/2)'"
        elif effect_type == 'shake':
            intensity = effect.get('intensity', 5)
            frequency = effect.get('frequency', 20)
            z_expr = "'1.05'"
            x_expr = f"'iw/2-(iw/zoom/2)+{intensity}*sin({frequency}*2*PI*on/{zoompan_frames})'"
            y_expr = f"'ih/2-(ih/zoom/2)+{intensity}*cos({frequency}*2*PI*on/{zoompan_frames})'"
        else:
            self._create_simple_scene(media_path, output_path, duration, 'static')
            return

        vf = f"zoompan=z={z_expr}:x={x_expr}:y={y_expr}:d={zoompan_frames}:s={self.width}x{self.height}:fps={zoompan_fps},fps={self.fps},format={self.pixel_format}"

        cmd = [
            FFMPEG_BIN, '-y',
            '-i', media_path,
            '-vf', vf,
            '-t', str(duration),
            '-c:v', self.codec,
            '-pix_fmt', self.pixel_format,
            '-preset', 'fast',
            '-crf', str(self.crf),
            output_path
        ]

        logger.info("Zoompan effect: {} {}s", effect_type, duration)
        logger.debug("Zoompan cmd: {}", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=300)
        if result.returncode != 0:
            stderr = result.stderr or ""
            if len(stderr) > 1500:
                stderr_summary = stderr[:750] + "\n...\n" + stderr[-750:]
            else:
                stderr_summary = stderr
            logger.error("FFmpeg zoompan failed:\nstdout: {}\nstderr: {}",
                          result.stdout[:500], stderr_summary)
            raise RuntimeError(f"FFmpeg zoompan failed: {stderr_summary}")

    def _probe_video(self, video_path):
        """Probe a video file and return stream info. Returns None if invalid."""
        try:
            cmd = [
                FFPROBE_BIN,
                '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=codec_name,width,height,duration,nb_frames',
                '-show_entries', 'format=duration',
                '-of', 'json',
                video_path,
            ]
            result = subprocess.run(cmd, capture_output=True, encoding='utf-8',
                                    errors='replace', timeout=15)
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout)
            streams = data.get('streams', [])
            if not streams:
                return None
            stream = streams[0]
            fmt = data.get('format', {})
            return {
                'codec': stream.get('codec_name', ''),
                'width': int(stream.get('width', 0)),
                'height': int(stream.get('height', 0)),
                'duration': float(stream.get('duration') or fmt.get('duration') or 0),
                'nb_frames': int(stream.get('nb_frames') or 0),
            }
        except Exception as e:
            logger.debug("Probe failed for {}: {}", video_path, e)
            return None

    def _extract_first_frame(self, video_path, output_image_path):
        """Extract the first frame from a video as a fallback image."""
        cmd = [
            FFMPEG_BIN, '-y',
            '-i', video_path,
            '-vframes', '1',
            '-q:v', '2',
            output_image_path,
        ]
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8',
                                errors='replace', timeout=30)
        return result.returncode == 0 and os.path.isfile(output_image_path)

    def _create_scene_from_video(self, video_path, output_path, duration, effect):
        """Create a scene clip from a video source — trim, scale, and re-encode.

        For motion effects (zoom, pan, shake, ken_burns) on video sources, the
        strategy is:
        1. Scale the video *larger* than the target resolution (headroom).
        2. Use FFmpeg ``crop`` with time-based expressions to animate the
           visible viewport, producing the motion effect.
        3. Scale back to the target resolution if the crop size varies (zoom).

        Falls back to image-based processing if the video is invalid/corrupt.
        """
        effect_type = effect.get('type', 'static')
        W, H = self.width, self.height
        dur = duration

        # ── Determine headroom multiplier ────────────────────────────
        needs_motion = effect_type in (
            'zoom_in', 'zoom_out', 'pan_left', 'pan_right',
            'pan_up', 'pan_down', 'pan_diagonal_tl', 'pan_diagonal_br',
            'ken_burns', 'shake',
        )

        if effect_type in ('zoom_in', 'zoom_out', 'ken_burns'):
            headroom = 1.3
        elif needs_motion:
            headroom = 1.25
        else:
            headroom = 1.0

        # Scaled dimensions (even numbers required by most codecs)
        sw = (int(W * headroom) // 2) * 2
        sh = (int(H * headroom) // 2) * 2

        # ── Build filter chain ───────────────────────────────────────
        filters = [
            f"scale='if(gte(iw/ih,{sw}/{sh}),-2,{sw})':'if(gte(iw/ih,{sw}/{sh}),{sh},-2)'",
            f"crop={sw}:{sh}",
            f"fps={self.fps}",
        ]

        if needs_motion:
            pan_amount = effect.get('pan_amount', 0.2)
            pan_px_x = sw - W          # horizontal headroom pixels
            pan_px_y = sh - H          # vertical headroom pixels
            cx = f"({sw}-{W})/2"       # centered x offset
            cy = f"({sh}-{H})/2"       # centered y offset

            if effect_type in ('zoom_in', 'zoom_out', 'ken_burns'):
                # For zoom: scale to exact target first, then use per-frame
                # upscale + fixed crop.  crop can't have varying output dims,
                # so we scale UP over time and crop the center at WxH.
                # Replace the initial oversized scale+crop with target-fit.
                filters[0] = (
                    f"scale='if(gte(iw/ih,{W}/{H}),-2,{W})':"
                    f"'if(gte(iw/ih,{W}/{H}),{H},-2)'"
                )
                filters[1] = f"crop={W}:{H}"

                start_s = effect.get('start_scale', 1.0 if effect_type != 'zoom_out' else 1.2)
                end_s = effect.get('end_scale', 1.2 if effect_type == 'zoom_in' else (1.15 if effect_type == 'ken_burns' else 1.0))
                delta = end_s - start_s  # positive for zoom_in, negative for zoom_out
                # Per-frame upscale then center-crop back to WxH
                scale_expr_w = f"trunc(iw*({start_s}+{delta}*t/{dur})/2)*2"
                scale_expr_h = f"trunc(ih*({start_s}+{delta}*t/{dur})/2)*2"
                filters.append(
                    f"scale=w='{scale_expr_w}':h='{scale_expr_h}':eval=frame:flags=lanczos"
                )
                if effect_type == 'ken_burns':
                    # Subtle rightward + downward drift while zooming
                    pan_drift = int(W * 0.03)
                    filters.append(
                        f"crop={W}:{H}:'(iw-{W})/2+{pan_drift}*t/{dur}':'(ih-{H})/2'"
                    )
                else:
                    filters.append(f"crop={W}:{H}:(iw-{W})/2:(ih-{H})/2")

            elif effect_type == 'pan_left':
                filters.append(f"crop={W}:{H}:'{pan_px_x}*(1-t/{dur})':{cy}")

            elif effect_type == 'pan_right':
                filters.append(f"crop={W}:{H}:'{pan_px_x}*t/{dur}':{cy}")

            elif effect_type == 'pan_up':
                filters.append(f"crop={W}:{H}:{cx}:'{pan_px_y}*(1-t/{dur})'")

            elif effect_type == 'pan_down':
                filters.append(f"crop={W}:{H}:{cx}:'{pan_px_y}*t/{dur}'")

            elif effect_type == 'pan_diagonal_tl':
                filters.append(f"crop={W}:{H}:'{pan_px_x}*(1-t/{dur})':'{pan_px_y}*(1-t/{dur})'")

            elif effect_type == 'pan_diagonal_br':
                filters.append(f"crop={W}:{H}:'{pan_px_x}*t/{dur}':'{pan_px_y}*t/{dur}'")

            elif effect_type == 'shake':
                intensity = effect.get('intensity', 5)
                frequency = effect.get('frequency', 20)
                filters.append(
                    f"crop={W}:{H}:"
                    f"'{cx}+{intensity}*sin({frequency}*2*PI*t)':"
                    f"'{cy}+{intensity}*cos({frequency}*2*PI*t)'"
                )

        elif effect_type == 'fade':
            fade_dur = min(0.5, duration / 2)
            filters.append(f"fade=t=in:st=0:d={fade_dur}")
            filters.append(f"fade=t=out:st={duration - fade_dur}:d={fade_dur}")

        # Guarantee even dimensions and encoder-compatible pixel format
        filters.append(f"scale=trunc(iw/2)*2:trunc(ih/2)*2")
        filters.append(f"format={self.pixel_format}")
        vf = ','.join(filters)

        cmd = [
            FFMPEG_BIN, '-y',
            '-i', video_path,
            '-map', '0:v:0',
            '-t', str(duration),
            '-vf', vf,
            '-c:v', self.codec,
            '-pix_fmt', self.pixel_format,
            '-an',
            '-preset', 'fast',
            '-crf', str(self.crf),
            output_path,
        ]

        logger.info("Video source scene: {}s effect={} src={}",
                     duration, effect_type, os.path.basename(video_path))
        logger.debug("Video scene cmd: {}", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=300)
        if result.returncode != 0:
            stderr = result.stderr or ""
            if len(stderr) > 1500:
                stderr_summary = stderr[:750] + "\n...\n" + stderr[-750:]
            else:
                stderr_summary = stderr
            logger.warning("FFmpeg video scene failed, attempting fallback:\n{}",
                            stderr_summary[-300:])

            # ── Fallback: extract first frame and process as image ──
            fallback_img = output_path.replace('.mp4', '_fallback.jpg')
            try:
                if self._extract_first_frame(video_path, fallback_img):
                    logger.info("Fallback: extracted first frame, processing as image")
                    self._create_scene_subprocess(fallback_img, output_path, duration, effect)
                    return
                else:
                    logger.warning("Fallback: frame extraction failed, trying re-encode with safe settings")
            except Exception as fb_err:
                logger.warning("Fallback image processing failed: {}", fb_err)
            finally:
                if os.path.isfile(fallback_img):
                    try:
                        os.remove(fallback_img)
                    except OSError:
                        pass

            # ── Fallback 2: re-encode with minimal filters ──
            safe_cmd = [
                FFMPEG_BIN, '-y',
                '-i', video_path,
                '-t', str(duration),
                '-vf', f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                       f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black,"
                       f"format={self.pixel_format}",
                '-c:v', self.codec,
                '-pix_fmt', self.pixel_format,
                '-an',
                '-preset', 'fast',
                '-crf', str(self.crf),
                output_path,
            ]
            logger.debug("Safe fallback cmd: {}", ' '.join(safe_cmd))
            safe_result = subprocess.run(safe_cmd, capture_output=True, encoding='utf-8',
                                          errors='replace', timeout=300)
            if safe_result.returncode == 0:
                logger.success("Fallback 2 succeeded: safe re-encode")
                return

            logger.error("All video processing attempts failed for: {}", video_path)
            raise RuntimeError(f"FFmpeg video scene failed: {stderr_summary}")

    def _create_scene_subprocess(self, media_path, output_path, duration, effect):
        """Create scene video with effects using subprocess (fallback)"""
        effect_type = effect.get('type', 'static')

        vf_filters = [
            f"scale='if(gte(iw/ih,{self.width}/{self.height}),-2,{self.width})':'if(gte(iw/ih,{self.width}/{self.height}),{self.height},-2)'",
            f"crop={self.width}:{self.height}"
        ]

        if effect_type == 'fade':
            fade_duration = min(effect.get('fade_duration', 0.5), duration / 2)
            vf_filters.append(f"fade=t=in:st=0:d={fade_duration}")
            vf_filters.append(f"fade=t=out:st={duration-fade_duration}:d={fade_duration}")

        vf_filters.append(f"format={self.pixel_format}")
        vf = ','.join(vf_filters)

        cmd = [
            FFMPEG_BIN, '-y',
            '-loop', '1',
            '-i', media_path,
            '-t', str(duration),
            '-vf', vf,
            '-c:v', self.codec,
            '-pix_fmt', self.pixel_format,
            '-r', str(self.fps),
            '-crf', str(self.crf),
            '-preset', self.preset,
            output_path
        ]
        logger.debug("Subprocess scene cmd: {}", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=300)
        if result.returncode != 0:
            stderr = result.stderr or ""
            if len(stderr) > 1500:
                stderr_summary = stderr[:750] + "\n...\n" + stderr[-750:]
            else:
                stderr_summary = stderr
            logger.error("FFmpeg subprocess scene failed:\nstdout: {}\nstderr: {}",
                          result.stdout[:500], stderr_summary)
            raise RuntimeError(f"FFmpeg subprocess scene failed: {stderr_summary}")

    def _concat_scenes(self, scene_clips, output_path):
        """Concatenate scene clips into final video"""
        concat_list_path = os.path.join(os.path.dirname(scene_clips[0]), 'concat_list.txt')

        logger.info("Concatenating {} clips", len(scene_clips))
        with open(concat_list_path, 'w') as f:
            for clip in scene_clips:
                clip_path = clip.replace('\\', '/')
                f.write(f"file '{clip_path}'\n")
                logger.debug("  concat: {}", os.path.basename(clip_path))

        audio_config = self.export_data.get('audio')

        if USE_FFMPEG_PYTHON:
            self._concat_ffmpeg(concat_list_path, output_path, audio_config)
        else:
            self._concat_subprocess(concat_list_path, output_path, audio_config)

    def _concat_ffmpeg(self, concat_list_path, output_path, audio_config):
        """Concatenate using ffmpeg-python (delegates to subprocess for bgMusic/SFX mixing)."""
        bg_music = self.export_data.get('bgMusic')
        sfx = self.export_data.get('sfx')
        bgmusic_path = self._resolve_music_path(bg_music) if bg_music else None
        sfx_path = self._resolve_sfx_path(sfx) if sfx else None

        if bgmusic_path or sfx_path:
            logger.info("BgMusic/SFX present, using subprocess path for filter_complex")
            self._concat_subprocess(concat_list_path, output_path, audio_config)
            return

        video = ffmpeg.input(concat_list_path, format='concat', safe=0)

        if audio_config and audio_config.get('path'):
            try:
                audio_path = self._get_media_path(audio_config['path'])
                logger.info("Concat with audio: {}", audio_path)
                audio = ffmpeg.input(audio_path)

                volume = audio_config.get('volume', 1.0)
                audio = audio.filter('volume', volume=volume)

                start_offset = audio_config.get('start_offset', 0)
                timeline_offset = audio_config.get('timeline_offset', 0)
                trimmed_duration = audio_config.get('trimmed_duration')
                if start_offset or trimmed_duration:
                    trim_kwargs = {}
                    if start_offset:
                        trim_kwargs['start'] = start_offset
                    if trimmed_duration:
                        trim_kwargs['duration'] = trimmed_duration
                    audio = audio.filter('atrim', **trim_kwargs).filter('asetpts', 'PTS-STARTPTS')
                if timeline_offset:
                    delay_ms = int(round(float(timeline_offset) * 1000))
                    audio = audio.filter('adelay', delays=f'{delay_ms}|{delay_ms}')

                fade_out = audio_config.get('fade_out', 0.5)
                total_duration = self._get_total_duration()
                audio = audio.filter('afade', type='out', start_time=total_duration - fade_out, duration=fade_out)
                # Pad audio with silence so it never ends before the video
                audio = audio.filter('apad', whole_dur=total_duration)

                logger.debug("Audio: vol={} fade_out={}s total_dur={}s", volume, fade_out, total_duration)

                (
                    ffmpeg
                    .output(
                        video, audio,
                        output_path,
                        vcodec='copy',
                        acodec='aac',
                        audio_bitrate='192k',
                    )
                    .overwrite_output()
                    .run(cmd=FFMPEG_BIN, quiet=True)
                )
                logger.info("Concat with audio completed: {}", output_path)
            except FileNotFoundError as e:
                logger.warning("Audio file not found, exporting without audio: {}", e)
                self._concat_video_only(video, output_path)
        else:
            logger.info("Concat without audio")
            self._concat_video_only(video, output_path)

    def _concat_video_only(self, video_stream, output_path):
        """Concatenate video only (no audio)"""
        logger.debug("Concat video-only: {}", output_path)
        (
            ffmpeg
            .output(video_stream, output_path, vcodec='copy', an=None)
            .overwrite_output()
            .run(cmd=FFMPEG_BIN, quiet=True)
        )

    def _resolve_music_path(self, bg_music):
        """Resolve background music file path.

        Two valid sources:
          1. /assets/sounds/music/<folder>/<file> — built-in library under
             APP_ASSETS_DIR (auto-pick by tone, manual replace from picker)
          2. /output/musics/<file>                — user-uploaded music in
             MUSIC_DIR
        """
        music_path = bg_music.get('path', '')
        if not music_path:
            logger.debug("BgMusic: no path specified")
            return None
        if music_path.startswith('/assets/'):
            from config import APP_ASSETS_DIR
            rel = music_path.replace('/assets/', '', 1)
            full = os.path.join(APP_ASSETS_DIR, rel)
            if os.path.isfile(full):
                logger.debug("BgMusic resolved via assets: {} -> {}", music_path, full)
                return full
            logger.warning("BgMusic (assets) not found at {}", full)
        if music_path.startswith('/output/musics/'):
            from config import MUSIC_DIR
            fname = music_path.replace('/output/musics/', '', 1)
            full = os.path.join(MUSIC_DIR, fname)
            if os.path.isfile(full):
                logger.debug("BgMusic resolved (uploads): {} -> {}", music_path, full)
                return full
            logger.warning("BgMusic (uploads) not found at {}", full)
        try:
            resolved = self._get_media_path(music_path)
            logger.debug("BgMusic resolved via media path: {}", resolved)
            return resolved
        except FileNotFoundError:
            logger.warning("BgMusic not found anywhere: {}", music_path)
            return None

    def _resolve_sfx_path(self, sfx):
        """Resolve SFX file path. SFX URLs typically look like
        `/assets/sounds/sfx/<folder>/<file>` which Flask serves from
        APP_ASSETS_DIR — map it back to the filesystem here so ffmpeg can
        read it directly.
        """
        if not isinstance(sfx, dict):
            return None
        sfx_path = sfx.get('path', '')
        if not sfx_path:
            logger.debug("SFX: no path specified")
            return None
        if sfx_path.startswith('/assets/'):
            from config import APP_ASSETS_DIR
            rel = sfx_path.replace('/assets/', '', 1)
            full = os.path.join(APP_ASSETS_DIR, rel)
            if os.path.isfile(full):
                logger.debug("SFX resolved: {} -> {}", sfx_path, full)
                return full
            logger.warning("SFX file not found at {}", full)
        try:
            resolved = self._get_media_path(sfx_path)
            logger.debug("SFX resolved via media path: {}", resolved)
            return resolved
        except FileNotFoundError:
            logger.warning("SFX not found anywhere: {}", sfx_path)
            return None

    def _build_audio_filter(self, audio_config, bg_music, total_duration, sfx=None):
        """Build FFmpeg audio filter complex for narration + bgMusic + SFX mixing."""
        has_narration = audio_config and audio_config.get('path')
        has_bgmusic = bg_music is not None and self._resolve_music_path(bg_music) is not None
        has_sfx = sfx is not None and self._resolve_sfx_path(sfx) is not None

        if not has_narration and not has_bgmusic and not has_sfx:
            logger.debug("Audio filter: no audio sources")
            return None, None

        filters = []
        narration_label = None
        bgmusic_label = None
        sfx_label = None

        if has_narration:
            vol = audio_config.get('volume', 1.0)
            fade_out = audio_config.get('fade_out', 0.5)
            start_offset = audio_config.get('start_offset', 0)
            timeline_offset = audio_config.get('timeline_offset', 0)
            trimmed_duration = audio_config.get('trimmed_duration')
            fade_start = max(0, total_duration - fade_out)
            # apad pads with silence so audio never ends before video
            narration_parts = [f"[1:a]volume={vol}"]
            if start_offset or trimmed_duration:
                atrim = 'atrim='
                if start_offset:
                    atrim += f"start={start_offset}"
                if trimmed_duration:
                    atrim += f"{':' if start_offset else ''}duration={trimmed_duration}"
                narration_parts.extend([atrim, "asetpts=PTS-STARTPTS"])
            if timeline_offset:
                delay_ms = int(round(float(timeline_offset) * 1000))
                narration_parts.append(f"adelay={delay_ms}|{delay_ms}")
            narration_parts.extend([
                f"afade=t=out:st={fade_start}:d={fade_out}",
                f"apad=whole_dur={total_duration}[narration]"
            ])
            filters.append(','.join(narration_parts))
            narration_label = '[narration]'
            logger.debug("Audio filter: narration vol={} fade_out={}s", vol, fade_out)

        # Track the next free [N:a] input index. The video concat is [0],
        # narration is [1] (when present), bgmusic is the next slot, then sfx.
        next_input_idx = 1
        if has_narration:
            next_input_idx = 2

        if has_bgmusic:
            bgm_input_idx = next_input_idx
            next_input_idx += 1
            vol = bg_music.get('volume', 0.15)
            fade_in = bg_music.get('fade_in', 2.0)
            fade_out = bg_music.get('fade_out', 3.0)
            ducking = bg_music.get('ducking_enabled', True)
            duck_level = max(0.12, float(bg_music.get('ducking_level', 0.2)))

            effective_vol = duck_level if (ducking and has_narration) else vol

            fade_out_start = max(0, total_duration - fade_out)
            parts = [
                f"[{bgm_input_idx}:a]volume={effective_vol}",
                f"afade=t=in:st=0:d={fade_in}",
                f"afade=t=out:st={fade_out_start}:d={fade_out}",
                f"atrim=0:{total_duration}",
                f"asetpts=PTS-STARTPTS"
            ]
            filters.append(','.join(parts) + '[bgm]')
            bgmusic_label = '[bgm]'
            logger.debug("Audio filter: bgmusic vol={} (effective={}) fade_in={} fade_out={} ducking={}",
                          vol, effective_vol, fade_in, fade_out, ducking)

        if has_sfx:
            sfx_input_idx = next_input_idx
            next_input_idx += 1
            vol = sfx.get('volume', 0.10)
            fade_in = sfx.get('fade_in', 1.5)
            fade_out = sfx.get('fade_out', 2.0)
            ducking = sfx.get('ducking_enabled', True)
            duck_level = max(0.08, float(sfx.get('ducking_level', 0.20)))

            effective_vol = duck_level if (ducking and has_narration) else vol

            fade_out_start = max(0, total_duration - fade_out)
            parts = [
                f"[{sfx_input_idx}:a]volume={effective_vol}",
                f"afade=t=in:st=0:d={fade_in}",
                f"afade=t=out:st={fade_out_start}:d={fade_out}",
                f"atrim=0:{total_duration}",
                f"asetpts=PTS-STARTPTS"
            ]
            filters.append(','.join(parts) + '[sfx]')
            sfx_label = '[sfx]'
            logger.debug("Audio filter: sfx vol={} (effective={}) fade_in={} fade_out={} ducking={}",
                          vol, effective_vol, fade_in, fade_out, ducking)

        # Mix whatever combination of layers we have
        active_labels = [lbl for lbl in (narration_label, bgmusic_label, sfx_label) if lbl]
        if len(active_labels) > 1:
            filters.append(
                f"{''.join(active_labels)}amix=inputs={len(active_labels)}:duration=longest:normalize=0[audio_out]"
            )
            out_label = '[audio_out]'
            logger.debug("Audio filter: mixing {} layers", len(active_labels))
        elif active_labels:
            out_label = active_labels[0]
        else:
            out_label = None

        filter_str = ';'.join(filters)
        logger.debug("Audio filter_complex: {}", filter_str)
        return filter_str, out_label

    def _concat_subprocess(self, concat_list_path, output_path, audio_config):
        """Concatenate using subprocess with optional bgMusic + SFX mixing."""
        bg_music = self.export_data.get('bgMusic')
        sfx = self.export_data.get('sfx')
        total_duration = self._get_total_duration()

        narration_path = None
        if audio_config and audio_config.get('path'):
            try:
                narration_path = self._get_media_path(audio_config['path'])
                logger.info("Narration audio: {}", narration_path)
            except FileNotFoundError:
                logger.warning("Narration audio not found: {}", audio_config.get('path'))
                narration_path = None

        bgmusic_path = self._resolve_music_path(bg_music) if bg_music else None
        sfx_path = self._resolve_sfx_path(sfx) if sfx else None

        if not narration_path and not bgmusic_path and not sfx_path:
            logger.info("Concat: no audio, video-only")
            cmd = [
                FFMPEG_BIN, '-y',
                '-f', 'concat', '-safe', '0', '-i', concat_list_path,
                '-c:v', 'copy', '-an',
                output_path
            ]
            logger.debug("Concat cmd: {}", ' '.join(cmd))
            result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=600)
            if result.returncode != 0:
                logger.error("FFmpeg concat (no audio) failed:\nstderr: {}", result.stderr[-1000:] if result.stderr else "")
                raise RuntimeError(f"FFmpeg concat failed: {result.stderr[-500:] if result.stderr else ''}")
            return

        # Build input list
        cmd = [FFMPEG_BIN, '-y', '-f', 'concat', '-safe', '0', '-i', concat_list_path]
        if narration_path:
            cmd += ['-i', narration_path]
        if bgmusic_path:
            loop_flag = bg_music.get('loop', True)
            if loop_flag:
                cmd += ['-stream_loop', '-1']
            cmd += ['-i', bgmusic_path]
            logger.info("BgMusic input: {} (loop={})", bgmusic_path, loop_flag)
        if sfx_path:
            sfx_loop = sfx.get('loop', True)
            if sfx_loop:
                cmd += ['-stream_loop', '-1']
            cmd += ['-i', sfx_path]
            logger.info("SFX input: {} (loop={})", sfx_path, sfx_loop)

        # Build filter complex
        filter_str, out_label = self._build_audio_filter(
            audio_config if narration_path else None,
            bg_music if bgmusic_path else None,
            total_duration,
            sfx=sfx if sfx_path else None,
        )

        if filter_str:
            cmd += ['-filter_complex', filter_str, '-map', '0:v', '-map', out_label]
        else:
            cmd += ['-map', '0:v', '-an']

        cmd += ['-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', str(total_duration), output_path]

        n_audio_inputs = (1 if narration_path else 0) + (1 if bgmusic_path else 0) + (1 if sfx_path else 0)
        logger.info("Concat with audio: {} inputs (video+{} audio), filter_complex={}",
                     1 + n_audio_inputs, n_audio_inputs, bool(filter_str))
        logger.debug("Full concat cmd: {}", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=600)
        if result.returncode != 0:
            logger.error("FFmpeg concat failed:\nstdout: {}\nstderr: {}",
                          result.stdout[:300], result.stderr[-1000:] if result.stderr else "")
            raise RuntimeError(f"FFmpeg concat failed: {result.stderr[-500:] if result.stderr else ''}")
        logger.info("Concat completed: {}", output_path)

    def _resolve_font_path(self, family, weight='normal'):
        """Resolve a font family name to a filesystem path for FFmpeg drawtext."""
        # Map numeric/string weights to font variant names
        weight_str = str(weight).strip().lower()
        _weight_variant_map = {
            'bold': 'bold', '700': 'bold',
            '800': 'extrabold', 'extrabold': 'extrabold', 'extra-bold': 'extrabold',
            '900': 'black', 'black': 'black',
            '600': 'semibold', 'semibold': 'semibold', 'semi-bold': 'semibold',
            '500': 'medium', 'medium': 'medium',
            '300': 'light', 'light': 'light',
            '100': 'thin', 'thin': 'thin',
            '200': 'extralight', 'extralight': 'extralight',
        }
        variant = _weight_variant_map.get(weight_str, 'regular')

        # Try custom fonts first — try exact variant, then bold fallback for heavy weights
        custom_path = _custom_font_path(family, variant)
        if not custom_path and variant in ('extrabold', 'black', 'semibold'):
            custom_path = _custom_font_path(family, 'bold')
        if custom_path and os.path.isfile(custom_path):
            logger.debug("Font resolved (custom): {} {} -> {}", family, variant, custom_path)
            return custom_path

        current_os = platform.system().lower()
        os_key = 'win32' if current_os == 'windows' else ('darwin' if current_os == 'darwin' else 'linux')

        if variant in ('bold', 'extrabold', 'black') and family in FONT_BOLD_MAP:
            bold_name = FONT_BOLD_MAP[family]
            candidates = []
            if os_key == 'win32':
                candidates.append(f'C:/Windows/Fonts/{bold_name}')
            elif os_key == 'darwin':
                candidates.append(f'/Library/Fonts/{bold_name}')
            else:
                candidates.append(f'/usr/share/fonts/truetype/{family.lower().replace(" ", "-")}/{bold_name}')
            for c in candidates:
                if os.path.isfile(c):
                    logger.debug("Font resolved (bold): {} -> {}", family, c)
                    return c

        if family in FONT_MAP:
            for path in FONT_MAP[family].get(os_key, []):
                if os.path.isfile(path):
                    logger.debug("Font resolved: {} -> {}", family, path)
                    return path

        fallbacks = {
            'win32': 'C:/Windows/Fonts/arial.ttf',
            'darwin': '/System/Library/Fonts/Helvetica.ttc',
            'linux': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        }
        fb = fallbacks.get(os_key, 'arial.ttf')
        if os.path.isfile(fb):
            logger.debug("Font fallback: {} -> {}", family, fb)
            return fb
        logger.warning("No font found for '{}', using arial.ttf", family)
        return 'arial.ttf'

    def _wrap_caption_text(self, text, font_path, font_size, max_width):
        """Word-wrap caption text to fit within max_width using Pillow for measurement."""
        def split_token_to_fit(token, measure_fn):
            if measure_fn(token) <= max_width:
                return [token]
            parts = []
            chunk = ''
            for ch in token:
                test = chunk + ch
                if not chunk or measure_fn(test) <= max_width:
                    chunk = test
                else:
                    parts.append(chunk)
                    chunk = ch
            if chunk:
                parts.append(chunk)
            return parts or [token]

        try:
            pil_font = ImageFont.truetype(font_path, font_size)
        except (OSError, IOError):
            # Can't measure - estimate ~0.6 chars per pixel at this font size
            avg_char_w = font_size * 0.6
            chars_per_line = max(1, int(max_width / avg_char_w))
            words = str(text).split()
            lines, line = [], ''
            for w in words:
                parts = [w[i:i + chars_per_line] for i in range(0, len(w), chars_per_line)] or [w]
                for part in parts:
                    test = f"{line} {part}".strip()
                    if len(test) > chars_per_line and line:
                        lines.append(line)
                        line = part
                    else:
                        line = test
            if line:
                lines.append(line)
            return lines

        def measure(s):
            bbox = pil_font.getbbox(s)
            return (bbox[2] - bbox[0]) if bbox else 0

        words = str(text).split()
        lines = []
        current_line = ''

        for word in words:
            word_parts = split_token_to_fit(word, measure)
            for part in word_parts:
                test_line = f"{current_line} {part}".strip() if current_line else part
                if measure(test_line) > max_width and current_line:
                    lines.append(current_line)
                    current_line = part
                else:
                    current_line = test_line

        if current_line:
            lines.append(current_line)

        return lines if lines else [text]

    def _wrap_caption_words(self, text, words_per_line, font_path, font_size, max_width):
        """Split into short word chunks, then fit each chunk to width."""
        words = str(text or '').split()
        if not words or words_per_line <= 0:
            return self._wrap_caption_text(text, font_path, font_size, max_width)

        lines = []
        for i in range(0, len(words), words_per_line):
            chunk = ' '.join(words[i:i + words_per_line])
            lines.extend(self._wrap_caption_text(chunk, font_path, font_size, max_width))
        return lines if lines else [text]

    def _wrap_caption_lead_word(self, text, words_per_chunk, font_path, font_size, max_width):
        """Put the first word on its own line, then chunk the rest."""
        words = str(text or '').split()
        if len(words) <= 1:
            return self._wrap_caption_text(text, font_path, font_size, max_width)
        first = words[0]
        rest = ' '.join(words[1:])
        lines = [first]
        lines.extend(self._wrap_caption_words(rest, max(1, words_per_chunk), font_path, font_size, max_width))
        return lines if lines else [text]
    def _burn_captions(self, video_path, output_path):
        """Burn caption overlays into the video using FFmpeg drawtext filter."""
        captions = self.export_data.get('captions')
        if not captions:
            logger.debug("No captions to burn")
            return video_path

        entries = self._get_caption_entries()
        if not entries:
            logger.debug("Captions present but no entries")
            return video_path

        # Compute timespans of text scenes that requested caption hiding so we
        # can drop caption entries that fall inside them.
        hide_spans = []
        cumulative = 0.0
        for scene in self.export_data.get('scenes', []) or []:
            try:
                duration = float(scene.get('duration', 0) or 0)
            except (TypeError, ValueError):
                duration = 0.0
            scene_start = float(scene.get('start_time', cumulative) or cumulative)
            scene_end = float(scene.get('end_time', scene_start + duration) or (scene_start + duration))
            scene_type = str(scene.get('type') or '').lower()
            if scene_type in ('text', 'cta'):
                text_cfg = scene.get('text') or {}
                if text_cfg.get('hide_captions', True):
                    hide_spans.append((scene_start, scene_end))
            cumulative = scene_end if scene_end > cumulative else (cumulative + duration)

        if hide_spans:
            def _in_hidden_span(start_t):
                for s, e in hide_spans:
                    if s <= start_t < e:
                        return True
                return False

            filtered = [e for e in entries if not _in_hidden_span(float(e.get('start', 0) or 0))]
            dropped = len(entries) - len(filtered)
            if dropped:
                logger.info("Suppressing {} caption(s) inside {} text scene span(s)", dropped, len(hide_spans))
            entries = filtered
            if not entries:
                logger.debug("All captions filtered out by text scenes")
                return video_path

        style = captions.get('style', {})
        # Support both camelCase and snake_case keys from frontend
        font_family = style.get('fontFamily', style.get('font_family', 'Inter'))
        font_weight = style.get('fontWeight', style.get('font_weight', 'bold'))
        font_size = style.get('fontSize', style.get('font_size', 48))
        font_color_raw = style.get('color', '#FFFFFF')
        # Parse rgba() to FFmpeg color@alpha format, or strip # for hex
        _rgba_match = re.match(r'rgba?\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\)', font_color_raw)
        if _rgba_match:
            r, g, b = int(_rgba_match.group(1)), int(_rgba_match.group(2)), int(_rgba_match.group(3))
            a = float(_rgba_match.group(4)) if _rgba_match.group(4) else 1.0
            font_color = f"{r:02x}{g:02x}{b:02x}@{a:.2f}"
        else:
            font_color = font_color_raw.lstrip('#')
        bg_color = style.get('backgroundColor', style.get('background', ''))
        text_transform = style.get('textTransform', style.get('text_transform', 'none'))
        stroke_width = style.get('strokeWidth', style.get('stroke_width', 2))
        stroke_color = style.get('strokeColor', style.get('stroke_color', '#000000')).lstrip('#')
        position_y = style.get('positionY', style.get('position_y', 80))
        text_align = str(style.get('textAlign', style.get('text_align', 'center'))).lower()
        if text_align not in ('left', 'center', 'right'):
            text_align = 'center'
        position_x = float(style.get('positionX', style.get('position_x', 50)))
        current_word_scale = min(1.18, max(1.0, float(style.get('currentWordScale', style.get('current_word_scale', 1.0)))))
        box_padding_x = style.get('boxPaddingX', style.get('box_padding_x', 0))
        box_padding_y = style.get('boxPaddingY', style.get('box_padding_y', 0))
        shadow_color = style.get('shadowColor', style.get('shadow_color', ''))
        shadow_x = style.get('shadowOffsetX', style.get('shadow_offset_x', 0))
        shadow_y = style.get('shadowOffsetY', style.get('shadow_offset_y', 0))
        blend_mode = style.get('blendMode', style.get('blend_mode', 'normal'))
        letter_spacing = style.get('letterSpacing', style.get('letter_spacing', 0))
        edge_fade_ms = float(style.get('edgeFadeMs', style.get('edge_fade_ms', 90)))
        wrap_words_per_line = max(0, int(style.get('wrapWordsPerLine', style.get('wrap_words_per_line', 0)) or 0))
        random_line_emphasis = bool(style.get('randomLineEmphasis', style.get('random_line_emphasis', False)))
        random_line_scale = max(1.0, float(style.get('randomLineScale', style.get('random_line_scale', 1.14))))
        random_line_chance = max(0.0, min(1.0, float(style.get('randomLineChance', style.get('random_line_chance', 0.5)))))
        lead_word_line = bool(style.get('leadWordLine', style.get('lead_word_line', False)))
        word_by_word_reveal = bool(style.get('wordByWordReveal', style.get('word_by_word_reveal', False)))
        random_line_targets_raw = style.get('randomLineTargets', style.get('random_line_targets', [1, 3]))
        if isinstance(random_line_targets_raw, (list, tuple)):
            random_line_targets = {int(v) for v in random_line_targets_raw if str(v).strip().isdigit()}
        elif isinstance(random_line_targets_raw, str):
            random_line_targets = {int(v.strip()) for v in random_line_targets_raw.split(',') if v.strip().isdigit()}
        else:
            random_line_targets = {1, 3}
        if not random_line_targets:
            random_line_targets = {1, 3}
        preset_id = style.get('preset', '')
        is_single_line_style = (
            preset_id in ('single_line', 'single_line_highlight')
            or blend_mode == 'difference'
        )

        # Highlight settings
        do_highlight = style.get('highlight', False)
        highlight_mode = style.get('highlight_mode', style.get('highlightMode', 'text'))  # 'text' or 'box'
        highlight_color_raw = style.get('highlight_color', style.get('highlightColor', '#4ECDC4'))
        highlight_color_hex = highlight_color_raw.lstrip('#') if highlight_color_raw.startswith('#') else '4ECDC4'

        font_path = self._resolve_font_path(font_family, font_weight)
        font_path_esc = font_path.replace('\\', '/').replace(':', '\\:')

        # Pillow font cache for width measurement at dynamic sizes
        _pil_font_cache = {}
        def _get_pil_font(size):
            s = max(8, int(size))
            if s not in _pil_font_cache:
                try:
                    _pil_font_cache[s] = ImageFont.truetype(font_path, s)
                except (OSError, IOError):
                    _pil_font_cache[s] = None
            return _pil_font_cache[s]

        # Max text width: 85% of video width (matches preview canvas wrapping)
        safe_pad_x = max(24, int(self.width * 0.05))
        anchor_x = int((position_x / 100.0) * self.width)
        anchor_x = max(safe_pad_x, min(self.width - safe_pad_x, anchor_x))
        base_line_height = int(font_size * 1.25)

        # Reserve room for stroke and random-line scaling so the rendered
        # result never exceeds the safe area.
        _stroke_pad = int(stroke_width * 2) if (stroke_color and stroke_color != 'none' and stroke_width) else 0
        _max_line_scale = random_line_scale if random_line_emphasis else 1.0
        def _safe_max(raw):
            return max(80, int((raw - _stroke_pad) / _max_line_scale))

        max_text_width = _safe_max(int(self.width * 0.85))
        max_single_line_width = _safe_max(int(self.width * 0.90))

        def _line_x_expr():
            # Clamp so text stays within safe area even when line-scaled
            # NOTE: expressions with commas MUST be single-quoted in filter_complex_script
            # or FFmpeg interprets the comma as a filter chain separator.
            r_bound = self.width - safe_pad_x
            if text_align == 'left':
                return f"'min({anchor_x},{r_bound}-text_w)'"
            if text_align == 'right':
                return f"'max({safe_pad_x},{anchor_x}-text_w)'"
            return f"'max({safe_pad_x},min({r_bound}-text_w,{anchor_x}-text_w/2))'"

        def _line_scale_for(entry, line_no):
            if not random_line_emphasis:
                return 1.0
            if line_no not in random_line_targets:
                return 1.0
            key = f"{preset_id}|{entry.get('start',0)}|{entry.get('end',0)}|{entry.get('text','')}|{line_no}"
            seed = hashlib.md5(key.encode('utf-8')).hexdigest()[:8]
            unit = int(seed, 16) / 0xFFFFFFFF
            return random_line_scale if unit < random_line_chance else 1.0

        def _line_start_x(line_width):
            if text_align == 'left':
                return anchor_x
            if text_align == 'right':
                return anchor_x - line_width
            return int(anchor_x - line_width / 2)

        def _wrap_limit_for_align():
            if text_align == 'left':
                return _safe_max(max(120, self.width - anchor_x - safe_pad_x))
            if text_align == 'right':
                return _safe_max(max(120, anchor_x - safe_pad_x))
            return max_text_width

        wrap_limit_width = _wrap_limit_for_align()

        logger.info("Burning {} captions: font={} {}px color=#{} stroke={}px pos=({},{}%) align={} max_w={} highlight={} scale={:.2f}",
                     len(entries), font_family, font_size, font_color, stroke_width, position_x, position_y, text_align, wrap_limit_width,
                     f"{highlight_mode}({highlight_color_hex})" if do_highlight else "off", current_word_scale)

        def _escape_text(t):
            return (t.replace("\\", "\\\\")
                     .replace("'", "\u2019")
                     .replace(":", "\\:")
                     .replace("%", "%%")
                     .replace("[", "\\[")
                     .replace("]", "\\]")
                     .replace(";", "\\;"))

        def _shadow_suffix():
            if shadow_color and shadow_color not in ('none', 'transparent'):
                sc = shadow_color.lstrip('#')
                if sc.startswith('rgba') or sc.startswith('rgb'):
                    sc = '000000'
                return f":shadowcolor=#{sc}:shadowx={shadow_x}:shadowy={shadow_y}"
            return ''

        def _stroke_suffix():
            if stroke_width and stroke_color and stroke_color != 'none':
                return f":borderw={stroke_width}:bordercolor=#{stroke_color}"
            return ''

        def _letter_spacing_suffix():
            # Note: ffmpeg drawtext does not support letter_spacing, only line_spacing
            # Letter spacing is handled via preview canvas only; skip in burn-in
            return ''

        def _measure_text(text, size=font_size):
            """Measure text width in pixels using Pillow."""
            pil_font = _get_pil_font(size)
            if pil_font:
                bbox = pil_font.getbbox(text)
                return bbox[2] - bbox[0] if bbox else int(len(text) * size * 0.6)
            return int(len(text) * size * 0.6)

        def _alpha_suffix(start, end):
            if not is_single_line_style:
                return ''
            dur = max(0.001, float(end) - float(start))
            fade = min(max(0.0, edge_fade_ms) / 1000.0, dur * 0.25)
            if fade <= 0:
                return ''
            return (
                f":alpha='if(lt(t,{start + fade:.3f}),(t-{start:.3f})/{fade:.3f},"
                f"if(gt(t,{end - fade:.3f}),({end:.3f}-t)/{fade:.3f},1))'"
            )

        drawtext_parts = []
        for i, entry in enumerate(entries):
            text = entry.get('text', '')
            if not text:
                continue

            # Strip special characters (keep letters, numbers, spaces, ! ? [ ])
            text = re.sub(r'[^\w\s!?\[\]]', '', text)
            text = re.sub(r'\s{2,}', ' ', text).strip()
            if text_transform == 'uppercase':
                text = text.upper()

            start = entry.get('start', 0)
            end = entry.get('end', start + 1)
            words = entry.get('words', [])
            alpha_suffix = _alpha_suffix(start, end)

            render_font_size = int(font_size)
            line_height = base_line_height

            if is_single_line_style:
                text_w = _measure_text(text, render_font_size)
                if text_w > max_single_line_width:
                    fit_scale = max_single_line_width / max(1, text_w)
                    min_size = max(24, int(font_size * 0.72))
                    render_font_size = max(min_size, int(font_size * fit_scale))
                line_height = int(render_font_size * 1.1 * (random_line_scale if random_line_emphasis else 1.0))
                # After scaling, if text still exceeds width, wrap it
                final_w = _measure_text(text, render_font_size)
                if final_w > max_single_line_width:
                    lines = self._wrap_caption_text(text, font_path, render_font_size, max_single_line_width)
                else:
                    lines = [text]
            else:
                # Word-wrap text to fit within video width
                if wrap_words_per_line > 0:
                    if lead_word_line:
                        lines = self._wrap_caption_lead_word(
                            text, wrap_words_per_line, font_path, render_font_size, wrap_limit_width
                        )
                    else:
                        lines = self._wrap_caption_words(
                            text, wrap_words_per_line, font_path, render_font_size, wrap_limit_width
                        )
                else:
                    lines = self._wrap_caption_text(text, font_path, render_font_size, wrap_limit_width)
                line_height = int(render_font_size * 1.25 * (random_line_scale if random_line_emphasis else 1.0))

            num_lines = len(lines)

            # Center the block around position_y
            block_height = num_lines * line_height
            base_y_px = int(self.height * position_y / 100 - block_height / 2)

            if do_highlight and words:
                # --- Highlight mode: render each word individually ---
                # Build a flat list of (word_text, begin, end) with uppercase applied
                word_timings = []
                for w in words:
                    wt = re.sub(r'[^\w\s!?\[\]]', '', w.get('word', ''))
                    if text_transform == 'uppercase':
                        wt = wt.upper()
                    if not wt.strip():
                        continue
                    word_timings.append({
                        'text': wt,
                        'begin': w.get('begin', start),
                        'end': w.get('end', end),
                    })

                # Map words to lines (split each line to match word count)
                word_idx = 0
                for line_idx, line_text in enumerate(lines):
                    line_y = base_y_px + line_idx * line_height
                    line_words = line_text.split(' ')
                    n_line_words = len(line_words)

                    # Calculate x positions for each word in this line
                    full_line_w = _measure_text(line_text, render_font_size)
                    line_start_x = _line_start_x(full_line_w)
                    # Clamp so line stays within safe area
                    line_start_x = max(safe_pad_x, min(self.width - safe_pad_x - full_line_w, line_start_x))
                    space_w = _measure_text(' ', render_font_size)

                    word_x = line_start_x
                    for lw_idx in range(n_line_words):
                        if word_idx >= len(word_timings):
                            break
                        wt = word_timings[word_idx]
                        word_w = _measure_text(wt['text'], render_font_size)
                        escaped_word = _escape_text(wt['text'])

                        dim_color = font_color  # base color (may be dim for single_line_highlight)

                        # Compute highlight window for this word
                        w_begin = wt['begin']
                        if word_idx + 1 < len(word_timings):
                            w_active_end = word_timings[word_idx + 1]['begin']
                        else:
                            w_active_end = end

                        # Dim pass: show word in base color, but EXCLUDE the highlight window
                        # so the scaled highlight word doesn't have dim text bleeding through
                        if current_word_scale > 1.0:
                            dim_enable = f"between(t,{start},{end})*not(between(t,{w_begin},{w_active_end}))"
                        else:
                            dim_enable = f"between(t,{start},{end})"
                        dt_dim = (
                            f"drawtext=fontfile='{font_path_esc}'"
                            f":text='{escaped_word}'"
                            f":fontsize={render_font_size}"
                            f":fontcolor=#{dim_color}"
                            f":x={word_x}"
                            f":y={line_y}"
                            f":enable='{dim_enable}'"
                        )
                        dt_dim += _letter_spacing_suffix() + alpha_suffix + _stroke_suffix() + _shadow_suffix()
                        drawtext_parts.append(dt_dim)

                        if highlight_mode == 'box':
                            # Draw colored box behind word, then white text on top
                            box_pad = int(render_font_size * 0.15)
                            box_x = word_x - box_pad
                            box_y = line_y - int(render_font_size * 0.1) - box_pad
                            box_w = word_w + box_pad * 2
                            box_h = int(render_font_size * 1.1) + box_pad * 2

                            dt_box = (
                                f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}"
                                f":color=#{highlight_color_hex}:t=fill"
                                f":enable='between(t,{w_begin},{w_active_end})'"
                            )
                            drawtext_parts.append(dt_box)

                            # Redraw word in white on top of box
                            scaled_fs = int(render_font_size * current_word_scale) if current_word_scale > 1.0 else render_font_size
                            scaled_w = _measure_text(wt['text'], scaled_fs)
                            active_x = word_x - int((scaled_w - word_w) / 2) if current_word_scale > 1.0 else word_x
                            active_y = line_y - int((scaled_fs - render_font_size) / 2) if current_word_scale > 1.0 else line_y
                            dt_active = (
                                f"drawtext=fontfile='{font_path_esc}'"
                                f":text='{escaped_word}'"
                                f":fontsize={scaled_fs}"
                                f":fontcolor=#FFFFFF"
                                f":x={active_x}"
                                f":y={active_y}"
                                f":enable='between(t,{w_begin},{w_active_end})'"
                            )
                            dt_active += _letter_spacing_suffix() + alpha_suffix + _stroke_suffix() + _shadow_suffix()
                            drawtext_parts.append(dt_active)
                        else:
                            # Text highlight: redraw word in highlight color
                            scaled_fs = int(render_font_size * current_word_scale) if current_word_scale > 1.0 else render_font_size
                            scaled_w = _measure_text(wt['text'], scaled_fs)
                            active_x = word_x - int((scaled_w - word_w) / 2) if current_word_scale > 1.0 else word_x
                            active_y = line_y - int((scaled_fs - render_font_size) / 2) if current_word_scale > 1.0 else line_y
                            dt_active = (
                                f"drawtext=fontfile='{font_path_esc}'"
                                f":text='{escaped_word}'"
                                f":fontsize={scaled_fs}"
                                f":fontcolor=#{highlight_color_hex}"
                                f":x={active_x}"
                                f":y={active_y}"
                                f":enable='between(t,{w_begin},{w_active_end})'"
                            )
                            dt_active += _letter_spacing_suffix() + alpha_suffix + _stroke_suffix() + _shadow_suffix()
                            drawtext_parts.append(dt_active)

                        word_x += word_w + space_w
                        word_idx += 1
            else:
                # --- Standard mode: render full lines ---
                if word_by_word_reveal and words:
                    word_timings = []
                    for w in words:
                        wt = re.sub(r'[^\w\s!?\[\]]', '', w.get('word', ''))
                        if text_transform == 'uppercase':
                            wt = wt.upper()
                        if not wt.strip():
                            continue
                        word_timings.append({
                            'text': wt,
                            'begin': w.get('begin', start),
                        })

                    word_idx = 0
                    for line_idx, line_text in enumerate(lines):
                        line_y = base_y_px + line_idx * line_height
                        line_scale = _line_scale_for(entry, line_idx + 1)
                        line_font_size = int(render_font_size * line_scale)
                        line_y_draw = line_y - int((line_font_size - render_font_size) / 2)
                        line_words = line_text.split(' ')
                        full_line_w = _measure_text(line_text, line_font_size)
                        line_start_x = _line_start_x(full_line_w)
                        line_start_x = max(safe_pad_x, min(self.width - safe_pad_x - full_line_w, line_start_x))
                        space_w = _measure_text(' ', line_font_size)

                        word_x = line_start_x
                        for lw in line_words:
                            if word_idx >= len(word_timings):
                                break
                            wt = word_timings[word_idx]
                            word_w = _measure_text(wt['text'], line_font_size)
                            escaped_word = _escape_text(wt['text'])

                            dt = (
                                f"drawtext=fontfile='{font_path_esc}'"
                                f":text='{escaped_word}'"
                                f":fontsize={line_font_size}"
                                f":fontcolor=#{font_color}"
                                f":x={word_x}"
                                f":y={line_y_draw}"
                                f":enable='between(t,{wt['begin']},{end})'"
                            )
                            dt += _letter_spacing_suffix() + alpha_suffix + _stroke_suffix() + _shadow_suffix()
                            drawtext_parts.append(dt)

                            word_x += word_w + space_w
                            word_idx += 1
                else:
                    for line_idx, line_text in enumerate(lines):
                        escaped = _escape_text(line_text)
                        line_y = base_y_px + line_idx * line_height
                        line_scale = _line_scale_for(entry, line_idx + 1)
                        line_font_size = int(render_font_size * line_scale)
                        line_y_draw = line_y - int((line_font_size - render_font_size) / 2)

                        dt = (
                            f"drawtext=fontfile='{font_path_esc}'"
                            f":text='{escaped}'"
                            f":fontsize={line_font_size}"
                            f":fontcolor=#{font_color}"
                            f":x={_line_x_expr()}"
                            f":y={line_y_draw}"
                            f":enable='between(t,{start},{end})'"
                        )
                        dt += _letter_spacing_suffix() + alpha_suffix
                        dt += _stroke_suffix()

                        if bg_color and bg_color not in ('transparent', 'none'):
                            bg_hex = bg_color.lstrip('#')
                            pad = max(box_padding_x, box_padding_y, 8)
                            dt += f":box=1:boxcolor=#{bg_hex}:boxborderw={pad}"

                        dt += _shadow_suffix()
                        drawtext_parts.append(dt)

            logger.debug("  Caption {}: [{:.1f}s-{:.1f}s] {} line(s) '{}'{}", i + 1, start, end, num_lines, text[:40],
                         f" [highlight {highlight_mode}]" if do_highlight and words else "")

        if not drawtext_parts:
            logger.debug("No valid caption entries after filtering")
            return video_path

        vf_drawtext = ','.join(drawtext_parts)
        if blend_mode == 'difference':
            # Read tuned strength values from style config
            diff_strength = float(style.get('diff_strength', style.get('diffStrength', 1.0)))
            overlay_strength = float(style.get('overlay_strength', style.get('overlayStrength', 0.0)))

            # Convert diff_strength (0-1) to a gray hex for drawtext fontcolor
            gray_val = int(diff_strength * 255)
            diff_hex = f"{gray_val:02x}" * 3  # e.g. 0.59 -> '969696'

            # Build drawtext filters with gray font for controlled diff strength
            # Include shadow on the mask — it gets inverted along with text
            diff_drawtext_parts = []
            for dt in drawtext_parts:
                dt_diff = dt.replace(f":fontcolor=#{font_color}", f":fontcolor=#{diff_hex}")
                diff_drawtext_parts.append(dt_diff)
            vf_diff_drawtext = ','.join(diff_drawtext_parts)

            # Difference blend: gray text on black → blend with original
            # NOTE: format=gbrp (planar rgb) BEFORE drawbox ensures black is true (0,0,0)
            # pack format like rgb24 is NOT supported by blend filter, prompting auto YUV fallback
            vf = (f"split[base][mask_bg];"
                  f"[mask_bg]format=gbrp,"
                  f"drawbox=x=0:y=0:w=iw:h=ih:color=0x000000:t=fill,"
                  f"{vf_diff_drawtext}[mask];"
                  f"[base]format=gbrp[base_rgb];"
                  f"[base_rgb][mask]blend=all_mode=difference,format={self.pixel_format}")

            # Overlay brightness boost: draw text again with low-alpha white on top
            if overlay_strength > 0:
                overlay_dt_parts = []
                for dt in drawtext_parts:
                    # White text with controlled alpha, no shadow/stroke
                    # Supported alpha notation: color@0.X
                    dt_ov = dt.replace(f":fontcolor=#{font_color}",
                                       f":fontcolor=white@{overlay_strength:.2f}")
                    if ':shadowcolor=' in dt_ov:
                        dt_ov = re.sub(r':shadowcolor=[^:]*:shadowx=[^:]*:shadowy=[^:]*', '', dt_ov)
                    if ':borderw=' in dt_ov:
                        dt_ov = re.sub(r':borderw=[^:]*:bordercolor=[^:]*', '', dt_ov)
                    overlay_dt_parts.append(dt_ov)
                vf_overlay = ','.join(overlay_dt_parts)
                vf += f",{vf_overlay}"
        else:
            vf = vf_drawtext

        is_complex = blend_mode == 'difference'
        logger.info("Running caption burn-in ({} drawtext filters, vf len={}, complex={})...",
                     len(drawtext_parts), len(vf), is_complex)

        # Write filter to a temp file to avoid Windows command-line length limits
        vf_file = None
        try:
            vf_fd, vf_file = tempfile.mkstemp(suffix='.txt', prefix='caption_vf_')
            with os.fdopen(vf_fd, 'w', encoding='utf-8') as f:
                f.write(vf)

            if is_complex:
                # Complex filter graph (split/blend) needs -filter_complex_script
                cmd = [
                    FFMPEG_BIN, '-y',
                    '-i', video_path,
                    '-filter_complex_script', vf_file,
                    '-c:v', self.codec,
                    '-crf', str(self.crf),
                    '-preset', 'fast',
                    '-pix_fmt', self.pixel_format,
                    '-c:a', 'copy',
                    output_path
                ]
            else:
                # Simple filter chain uses -filter_script:v
                cmd = [
                    FFMPEG_BIN, '-y',
                    '-i', video_path,
                    '-filter_script:v', vf_file,
                    '-c:v', self.codec,
                    '-crf', str(self.crf),
                    '-preset', 'fast',
                    '-pix_fmt', self.pixel_format,
                    '-c:a', 'copy',
                    output_path
                ]

            logger.debug("Caption cmd: {} ... (vf file={})", ' '.join(cmd[:6]), vf_file)

            # Stream FFmpeg stderr to report progress (90% → 98%) instead of blocking silently
            total_dur = self._get_total_duration() or 0
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding='utf-8', errors='replace',
            )
            stderr_lines = []
            _time_re = re.compile(r'time=(\d+):(\d+):(\d+)\.(\d+)')
            try:
                for line in proc.stderr:
                    stderr_lines.append(line)
                    if total_dur > 0:
                        m = _time_re.search(line)
                        if m:
                            t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 100
                            pct = 90 + int(min(8, (t / total_dur) * 8))
                            self._update_progress(pct, "Burning captions into video")
            except Exception:
                pass
            proc.wait(timeout=600)

            if proc.returncode != 0:
                stderr_msg = ''.join(stderr_lines).strip()
                logger.error("Caption burn-in failed (rc={}):\nstderr: {}",
                              proc.returncode, stderr_msg[-1500:] if stderr_msg else "(empty)")
                if not stderr_msg and vf_file and os.path.exists(vf_file):
                    logger.debug("Filter script preserved for debugging: {}", vf_file)
                    vf_file = None  # prevent cleanup so we can inspect
                raise RuntimeError(f"Caption burn-in failed: {stderr_msg[-500:] if stderr_msg else f'ffmpeg exited with code {proc.returncode}'}")
        finally:
            if vf_file and os.path.exists(vf_file):
                try:
                    os.unlink(vf_file)
                except OSError:
                    pass

        logger.success("Caption burn-in complete: {}", output_path)
        return output_path

    def _render_scene_clips(self, scenes, temp_dir):
        scene_clips = []
        total_scenes = len(scenes)
        for i, scene in enumerate(scenes):
            progress = int((i / total_scenes) * 80)
            scene_type = scene.get('media', {}).get('type', 'image')
            scene_id = scene.get('id', i + 1)
            logger.info("Processing scene {}/{} (id={} type={})",
                        i + 1, total_scenes, scene_id, scene_type)
            self._update_progress(progress, f"Processing scene {i + 1}/{total_scenes} ({scene_type})")

            try:
                clip_path = self._create_scene_clip(scene, temp_dir, i)
                scene_clips.append(clip_path)
                logger.info("Scene {}/{} done: {}", i + 1, total_scenes, os.path.basename(clip_path))
            except Exception as error:
                logger.error("Scene {}/{} FAILED: {}", i + 1, total_scenes, error)
                raise
        return scene_clips

    def _build_post_process_plan(self):
        has_captions = bool(self._get_caption_entries())
        overlay_list = self.export_data.get('overlays') or []
        if not overlay_list and self.export_data.get('overlay'):
            overlay_list = [self.export_data['overlay']]
        grain_cfg = self.export_data.get('grain_overlay') or self.export_data.get('grainOverlay') or {}
        has_grain_cfg = bool(grain_cfg and grain_cfg.get('enabled'))
        has_grain_overlay = has_grain_cfg or any(self._is_white_dot_grain_overlay(ov) for ov in overlay_list)
        logo_cfg = self.export_data.get('logo_overlay') or self.export_data.get('logoOverlay') or {}
        has_logo = bool(logo_cfg and logo_cfg.get('enabled') and (logo_cfg.get('path') or logo_cfg.get('url')))
        return {
            'has_captions': has_captions,
            'overlay_list': overlay_list,
            'grain_cfg': grain_cfg,
            'has_grain_cfg': has_grain_cfg,
            'has_grain_overlay': has_grain_overlay,
            'logo_cfg': logo_cfg,
            'has_logo': has_logo,
            'has_overlay': bool(overlay_list),
            'needs_post': has_captions or bool(overlay_list) or has_grain_overlay or has_logo,
        }

    def _apply_post_processing(self, concat_output, output_path, temp_dir, post_plan):
        overlay_list = post_plan['overlay_list']
        has_captions = post_plan['has_captions']
        has_grain_overlay = post_plan['has_grain_overlay']
        grain_cfg = post_plan['grain_cfg']
        has_logo = post_plan['has_logo']
        logo_cfg = post_plan['logo_cfg']

        if post_plan['has_overlay']:
            self._update_progress(85, f"Applying {len(overlay_list)} overlay(s)")
            current_input = concat_output
            for ov_idx, ov_entry in enumerate(overlay_list):
                is_last_overlay = ov_idx == len(overlay_list) - 1
                final_post_step = is_last_overlay and not has_captions and not has_grain_overlay and not has_logo
                ov_output = output_path if final_post_step else os.path.join(temp_dir, f'overlay_{ov_idx}.mp4')
                if self._is_white_dot_grain_overlay(ov_entry):
                    self._apply_white_dot_grain_overlay(current_input, ov_output, grain_cfg)
                else:
                    self._apply_overlay(current_input, ov_output, ov_entry)
                current_input = ov_output
            concat_output = current_input

        if post_plan['has_grain_cfg'] and not any(self._is_white_dot_grain_overlay(ov) for ov in overlay_list):
            self._update_progress(88, "Applying grain overlay")
            grain_output = os.path.join(temp_dir, 'grain_overlay.mp4') if (has_captions or has_logo) else output_path
            self._apply_white_dot_grain_overlay(concat_output, grain_output, grain_cfg)
            concat_output = grain_output

        if has_logo:
            self._update_progress(89, "Applying logo overlay")
            logo_output = os.path.join(temp_dir, 'logo_overlay.mp4') if has_captions else output_path
            self._apply_logo_overlay(concat_output, logo_output, logo_cfg)
            concat_output = logo_output

        if has_captions:
            logger.info("Starting caption burn-in...")
            self._update_progress(90, "Burning captions into video")
            self._burn_captions(concat_output, output_path)

        return concat_output

    def process(self, output_path):
        """Process all scenes into a final video"""
        scenes = self.export_data.get('scenes', [])
        if not scenes:
            logger.error("No scenes to process")
            raise ValueError("No scenes to process")

        logger.info("=== Export started: {} scenes -> {} ===", len(scenes), output_path)
        logger.debug("Frontend dir: {}", self.frontend_dir)

        self._update_progress(0, "Starting video processing")

        temp_dir = tempfile.mkdtemp(prefix='video_export_')
        logger.debug("Temp directory: {}", temp_dir)

        try:
            scene_clips = self._render_scene_clips(scenes, temp_dir)

            logger.info("All scenes rendered, concatenating {} clips...", len(scene_clips))
            self._update_progress(82, "Concatenating scenes and adding audio")

            post_plan = self._build_post_process_plan()
            has_captions = post_plan['has_captions']
            overlay_list = post_plan['overlay_list']
            grain_cfg = post_plan['grain_cfg']
            has_grain_cfg = post_plan['has_grain_cfg']
            has_grain_overlay = post_plan['has_grain_overlay']
            has_overlay = post_plan['has_overlay']

            if post_plan['needs_post']:
                concat_output = os.path.join(temp_dir, 'concat_output.mp4')
                logger.debug("Post-processing needed (overlays={} captions={}) — concat to temp", len(overlay_list), has_captions)
            else:
                concat_output = output_path

            self._concat_scenes(scene_clips, concat_output)

            if post_plan['needs_post']:
                self._apply_post_processing(concat_output, output_path, temp_dir, post_plan)
                has_overlay = False
                has_grain_cfg = False
                has_captions = False

            # Apply global overlays sequentially (between scenes and captions)
            if has_overlay:
                self._update_progress(85, f"Applying {len(overlay_list)} overlay(s)")
                current_input = concat_output
                for ov_idx, ov_entry in enumerate(overlay_list):
                    is_last_overlay = (ov_idx == len(overlay_list) - 1)
                    final_post_step = is_last_overlay and not has_captions and not has_grain_overlay
                    if final_post_step:
                        ov_output = output_path
                    else:
                        ov_output = os.path.join(temp_dir, f'overlay_{ov_idx}.mp4')
                    if self._is_white_dot_grain_overlay(ov_entry):
                        self._apply_white_dot_grain_overlay(current_input, ov_output, grain_cfg)
                    else:
                        self._apply_overlay(current_input, ov_output, ov_entry)
                    current_input = ov_output
                concat_output = current_input

            # Apply grain pass even when no explicit overlay card was selected.
            if has_grain_cfg and not any(self._is_white_dot_grain_overlay(ov) for ov in overlay_list):
                self._update_progress(88, "Applying grain overlay")
                grain_output = os.path.join(temp_dir, 'grain_overlay.mp4') if has_captions else output_path
                self._apply_white_dot_grain_overlay(concat_output, grain_output, grain_cfg)
                concat_output = grain_output

            if has_captions:
                logger.info("Starting caption burn-in...")
                self._update_progress(90, "Burning captions into video")
                self._burn_captions(concat_output, output_path)

            if os.path.exists(output_path):
                size = os.path.getsize(output_path)
                logger.success("=== Export completed: {} ({:.1f} MB) ===", output_path, size / (1024 * 1024))
            else:
                logger.error("=== Export output file missing: {} ===", output_path)

            self._update_progress(100, "Export completed")

        finally:
            logger.debug("Cleaning up temp directory: {}", temp_dir)
            shutil.rmtree(temp_dir, ignore_errors=True)

        return output_path

