"""
Compatibility shim for Python 3.13 where the stdlib imghdr module was removed.
Provides a minimal implementation of imghdr.what used by python-telegram-bot 13.x.
This is sufficient for common image types used with Telegram bots.
"""
from __future__ import annotations

from typing import Optional


def _what_header(h: bytes) -> Optional[str]:
    # JPEG
    if h.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    # PNG
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    # GIF
    if h.startswith(b"GIF87a") or h.startswith(b"GIF89a"):
        return "gif"
    # WEBP (RIFF + WEBP)
    if len(h) >= 12 and h.startswith(b"RIFF") and h[8:12] == b"WEBP":
        return "webp"
    # BMP
    if h.startswith(b"BM"):
        return "bmp"
    # TIFF (little/big endian)
    if h.startswith(b"II\x2a\x00") or h.startswith(b"MM\x00\x2a"):
        return "tiff"
    # ICO
    if h.startswith(b"\x00\x00\x01\x00"):
        return "ico"
    return None


def what(file: str, h: Optional[bytes] = None) -> Optional[str]:
    """
    Identify image type from a file name (path) or a header bytes-like object.

    Parameters
    - file: path to the file. If h is provided, file may be None or ignored.
    - h: optional header bytes. If not provided, the function reads the first
         32 bytes from the file path.

    Returns a string like 'jpeg', 'png', 'gif', etc., or None if unknown.
    """
    if h is None:
        try:
            with open(file, 'rb') as f:
                h = f.read(32)
        except Exception:
            return None
    return _what_header(h)


__all__ = ["what"]
