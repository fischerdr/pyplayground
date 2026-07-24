#!/usr/bin/env python3
"""ja_tokenize.py - Japanese word/morpheme boundary lookup for click-to-add-term.

Japanese text has no spaces between words, so Tk's built-in wordstart/
wordend (which works fine for the rendered English translation) can't
find sensible word boundaries in the original Japanese text. This module
uses fugashi (a pure-pip MeCab wrapper, bundled with the unidic-lite
dictionary so no system MeCab install is required) to find the morpheme
a given character offset falls inside, for the reader's click-a-word-in
-the-text-to-add-a-glossary-term feature.

Chinese is out of scope here -- MeCab/fugashi dictionaries don't parse
Chinese, and the reader has no Chinese source pipeline today. A future
Chinese equivalent (e.g. using jieba) should live in its own function
(find_zh_word_at) and be dispatched on source_lang by the caller, not
folded into this module.
"""

from typing import Optional, Tuple

from fugashi import Tagger

from pyplayground.utils.logging_utils import get_logger

logger = get_logger(__name__)

_tagger: Optional[Tagger] = None


def _get_tagger() -> Tagger:
    """Return the lazily-constructed, process-wide fugashi Tagger.

    Returns:
        A fugashi Tagger backed by the bundled unidic-lite dictionary.
    """
    global _tagger
    if _tagger is None:
        logger.debug("Initializing fugashi Tagger (unidic-lite)")
        _tagger = Tagger()
    return _tagger


def find_ja_word_at(text: str, char_offset: int) -> Optional[Tuple[int, int]]:
    """Find the morpheme boundary at a character offset in Japanese text.

    Args:
        text: The Japanese text to tokenize.
        char_offset: A 0-based character offset into `text`, typically
            from a UI click landing inside a word.

    Returns:
        (start, end) character offsets of the morpheme containing
        char_offset, or None if the offset is out of range or lands on
        punctuation/whitespace (nothing sensible to select).
    """
    if char_offset < 0 or char_offset >= len(text):
        return None

    pos = 0
    for word in _get_tagger()(text):
        surface = word.surface
        start = pos
        end = pos + len(surface)
        if start <= char_offset < end:
            if not any(ch.isalnum() or _is_cjk(ch) for ch in surface):
                # Punctuation/whitespace-only token -- nothing to select.
                return None
            return (start, end)
        pos = end
    return None


def _is_cjk(ch: str) -> bool:
    """Check whether a character is in a CJK unicode block.

    Args:
        ch: A single character.

    Returns:
        True if `ch` falls in a common CJK (kanji/hiragana/katakana) range.
    """
    code = ord(ch)
    return 0x3040 <= code <= 0x309F or 0x30A0 <= code <= 0x30FF or 0x4E00 <= code <= 0x9FFF  # Hiragana  # Katakana  # CJK Unified Ideographs
