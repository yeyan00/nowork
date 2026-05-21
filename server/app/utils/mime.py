from pathlib import Path
from typing import Optional, Tuple, Union

SUPPORTED_IMAGE_MIMES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
}

SUPPORTED_MEDIA_MIMES = SUPPORTED_IMAGE_MIMES | {"application/pdf"}

_EXTENSION_MIMES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".pdf": "application/pdf",
}


def _starts_with(data: bytes, prefix: bytes) -> bool:
    return len(data) >= len(prefix) and data[: len(prefix)] == prefix


def sniff_mime_type(
    file_path: Union[str, Path],
    sample_bytes: Optional[bytes] = None,
) -> str:
    path = Path(file_path)
    ext = path.suffix.lower()
    fallback = _EXTENSION_MIMES.get(ext, "application/octet-stream")

    if sample_bytes:
        if _starts_with(sample_bytes, b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if _starts_with(sample_bytes, b"\xff\xd8\xff"):
            return "image/jpeg"
        if _starts_with(sample_bytes, b"GIF8"):
            return "image/gif"
        if _starts_with(sample_bytes, b"BM"):
            return "image/bmp"
        if _starts_with(sample_bytes, b"%PDF-"):
            return "application/pdf"
        if (
            _starts_with(sample_bytes, b"RIFF")
            and len(sample_bytes) > 12
            and sample_bytes[8:12] == b"WEBP"
        ):
            return "image/webp"

    return fallback


def is_image(
    file_path: Union[str, Path],
    sample_bytes: Optional[bytes] = None,
) -> bool:
    mime = sniff_mime_type(file_path, sample_bytes)
    return mime in SUPPORTED_IMAGE_MIMES


def is_pdf(
    file_path: Union[str, Path],
    sample_bytes: Optional[bytes] = None,
) -> bool:
    return sniff_mime_type(file_path, sample_bytes) == "application/pdf"


def read_file_as_data_url(
    file_path: Union[str, Path],
) -> Tuple[str, str]:
    import base64

    path = Path(file_path)

    with open(path, "rb") as f:
        sample = f.read(8192)

    mime = sniff_mime_type(path, sample)

    with open(path, "rb") as f:
        content = f.read()

    b64_content = base64.b64encode(content).decode("utf-8")
    data_url = f"data:{mime};base64,{b64_content}"
    return data_url, mime