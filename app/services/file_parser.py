"""File parser service for extracting text from uploaded novel files."""

import re
import io
from docx import Document


def parse_txt(content: bytes) -> str:
    """Parse a .txt file and return its text content."""
    # Try UTF-8 first, then fallback to GBK (common for Chinese texts)
    for encoding in ["utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "big5"]:
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    raise ValueError("Unable to decode file. Unsupported text encoding.")


def parse_docx(content: bytes) -> str:
    """Parse a .docx file and return its text content."""
    doc = Document(io.BytesIO(content))
    paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
    return "\n".join(paragraphs)


def parse_file(filename: str, content: bytes) -> str:
    """Parse an uploaded file based on its extension."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext == "txt":
        return parse_txt(content)
    elif ext == "docx":
        return parse_docx(content)
    else:
        raise ValueError(f"Unsupported file format: .{ext}. Supported: .txt, .docx")


def split_into_chapters(text: str) -> list[dict]:
    """
    Split raw text into chapters by detecting chapter headers.

    Supports patterns like:
    - 第一章, 第二章, ... (Chinese numerals)
    - 第1章, 第2章, ... (Arabic numerals)
    - Chapter 1, Chapter 2, ...
    - 章节1, 章节2, ...

    The header must appear at the very beginning of a line to count as a
    chapter delimiter.  Mentions of "第xxx章" inside body text won't trigger
    a split.
    """

    # Each tuple is (header_regex, split_regex).
    # header_regex  – matches a chapter-header line (used to split).
    # The pattern MUST use ^ with re.MULTILINE so only *line-starts* match.
    chapter_header_patterns = [
        # Chinese: 第X章 / 第X节 / 第X回 …  (X = digits or CJK numerals)
        r"^(第[一二三四五六七八九十百千万零\d]+[章节回卷集部篇].*)",
        # English: Chapter N …
        r"^(Chapter\s+\d+.*)",
    ]

    for header_re in chapter_header_patterns:
        # Find all header positions
        headers = list(re.finditer(header_re, text, re.MULTILINE))

        if not headers:
            continue

        # We found at least one chapter header → build the chapter list.
        raw_chapters: list[dict] = []

        # Any text *before* the first header is front-matter: attach it to
        # the first chapter's content so nothing is lost.
        front_matter = text[: headers[0].start()].strip()

        for idx, hdr in enumerate(headers):
            title_line = hdr.group(1).strip()

            # Content runs from end-of-header-line to start-of-next-header
            # (or end-of-text for the last chapter).
            content_start = hdr.end()
            content_end = headers[idx + 1].start() if idx + 1 < len(headers) else len(text)
            body = text[content_start:content_end].strip()

            # For the very first chapter, prepend front-matter if present.
            if idx == 0 and front_matter:
                body = front_matter + "\n\n" + body if body else front_matter

            raw_chapters.append({
                "title": title_line,
                "content": body,
            })

        # ── Merge sub-parts that belong to the same logical chapter ──
        # Files often split one chapter into parts like:
        #   第1466章 ... (1/2)
        #   第1466章 ... (2/2)
        # We detect this by extracting the chapter number from the title
        # and merging consecutive entries that share the same number.
        num_re = re.compile(r"第([一二三四五六七八九十百千万零\d]+)[章节回卷集部篇]")

        def _extract_chapter_id(title: str) -> str:
            m = num_re.search(title)
            return m.group(1) if m else title

        merged: list[dict] = []
        for ch in raw_chapters:
            ch_id = _extract_chapter_id(ch["title"])
            if merged and _extract_chapter_id(merged[-1]["title"]) == ch_id:
                # Same logical chapter → append content
                merged[-1]["content"] = (
                    merged[-1]["content"] + "\n\n" + ch["content"]
                ).strip()
            else:
                merged.append(dict(ch))

        # Assign sequential chapter numbers
        chapters = []
        for i, ch in enumerate(merged):
            chapters.append({
                "chapter_number": i + 1,
                "title": ch["title"],
                "content": ch["content"],
            })

        return chapters

    # Fallback: no chapter pattern detected → treat entire file as one
    # complete chapter.  Never split arbitrarily.
    return [{
        "chapter_number": 1,
        "title": "Chương 1",
        "content": text.strip(),
    }]
