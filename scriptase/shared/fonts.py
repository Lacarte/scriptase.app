"""Font Scanner — builds a registry of custom fonts from the fonts/ directory."""

import os
import re

from loguru import logger

from config import FONTS_DIR, ROOT_DIR

# Variant classification patterns (order matters — more specific first)
_VARIANT_PATTERNS = [
    (re.compile(r'BoldItalic|Bold[_-]?Italic', re.I), 'bold_italic'),
    (re.compile(r'ExtraBold|Extra[_-]?Bold', re.I), 'extrabold'),
    (re.compile(r'SemiBold|Semi[_-]?Bold', re.I), 'semibold'),
    (re.compile(r'Black', re.I), 'black'),
    (re.compile(r'Bold', re.I), 'bold'),
    (re.compile(r'LightItalic|Light[_-]?Italic', re.I), 'light_italic'),
    (re.compile(r'MediumItalic|Medium[_-]?Italic', re.I), 'medium_italic'),
    (re.compile(r'Italic', re.I), 'italic'),
    (re.compile(r'Thin', re.I), 'thin'),
    (re.compile(r'ExtraLight|Extra[_-]?Light', re.I), 'extralight'),
    (re.compile(r'Light', re.I), 'light'),
    (re.compile(r'Medium', re.I), 'medium'),
    (re.compile(r'Regular', re.I), 'regular'),
]


def _classify_variant(filename):
    stem = os.path.splitext(filename)[0]
    for pattern, variant in _VARIANT_PATTERNS:
        if pattern.search(stem):
            return variant
    return 'regular'


def _scan_fonts():
    """Walk FONTS_DIR, build registry of family → variants → abs paths."""
    registry = {}
    if not os.path.isdir(FONTS_DIR):
        logger.warning("Fonts directory not found: {}", FONTS_DIR)
        return registry

    for root, _dirs, files in os.walk(FONTS_DIR):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in ('.ttf', '.otf'):
                continue

            # Skip condensed / width variants — keep only standard weight files
            stem_lower = os.path.splitext(f)[0].lower()
            if any(kw in stem_lower for kw in ('condensed', 'semicondensed', 'expanded')):
                continue

            abs_path = os.path.join(root, f)

            # Determine family from directory structure
            parent = os.path.basename(root)
            if parent == 'static':
                family_dir = os.path.basename(os.path.dirname(root))
            else:
                family_dir = parent

            # Skip if we're at the top-level fonts/ dir itself
            if os.path.normpath(root) == os.path.normpath(FONTS_DIR):
                continue

            family_name = family_dir.replace('_', ' ')
            variant = _classify_variant(f)
            is_variable = 'VariableFont' in f

            if family_name not in registry:
                registry[family_name] = {
                    'family': family_name,
                    'source': 'custom',
                    'variants': {},
                    '_var_fallbacks': {},
                }

            entry = registry[family_name]
            if is_variable:
                # Store as fallback — only used if no static version exists
                entry['_var_fallbacks'].setdefault(variant, abs_path)
            else:
                # Static fonts take priority
                entry['variants'][variant] = abs_path

    # Apply variable-font fallbacks and ensure 'regular' exists
    for entry in registry.values():
        for variant, path in entry.pop('_var_fallbacks', {}).items():
            if variant not in entry['variants']:
                entry['variants'][variant] = path
        if 'regular' not in entry['variants'] and entry['variants']:
            entry['variants']['regular'] = next(iter(entry['variants'].values()))

    logger.info("Font registry: {} custom families loaded", len(registry))
    return registry


FONT_REGISTRY = _scan_fonts()


def get_font_path(family, variant='regular'):
    """Get absolute file path for a font family + variant. Returns None if not found."""
    entry = FONT_REGISTRY.get(family)
    if not entry:
        return None
    return entry['variants'].get(variant) or entry['variants'].get('regular')


def get_font_url(abs_path):
    """Convert absolute font path to a URL-safe relative path from ROOT_DIR."""
    rel = os.path.relpath(abs_path, ROOT_DIR).replace('\\', '/')
    return '/' + rel
