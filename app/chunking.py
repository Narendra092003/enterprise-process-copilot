"""
Structure-aware chunking.

1. Split each page into blocks at blank lines.
2. Track the latest markdown heading so every chunk knows its section.
3. Pack blocks into chunks of about `chunk_words` words; when a chunk is full,
   start the next one with the last `overlap_words` words for continuity.
4. A new heading always starts a new chunk, so a procedure stays with its title.
"""
import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")


@dataclass
class Chunk:
    index: int
    text: str
    section: str
    page: int


def _words(text: str):
    return text.split()


def chunk_pages(pages, chunk_words: int = 180, overlap_words: int = 30):
    chunks = []
    section = ""
    buffer = []  # blocks collected for the current chunk
    buffer_page = 1

    def flush():
        """Turn whatever is in the buffer into a finished Chunk."""
        nonlocal buffer
        text = "\n\n".join(buffer).strip()
        if text:
            chunks.append(Chunk(index=len(chunks), text=text, section=section, page=buffer_page))
        buffer = []

    for page_no, page_text in pages:
        blocks = [b.strip() for b in re.split(r"\n\s*\n", page_text) if b.strip()]
        for block in blocks:
            first_line = block.splitlines()[0]
            m = HEADING_RE.match(first_line)
            if m:
                flush()  # rule 1: a heading starts a new chunk
                section = m.group(1).strip()
                buffer_page = page_no
                rest = "\n".join(block.splitlines()[1:]).strip()
                buffer = [rest] if rest else []
                continue

            if not buffer:
                buffer_page = page_no
            current = sum(len(_words(b)) for b in buffer)
            if current and current + len(_words(block)) > chunk_words:
                # rule 3: chunk is full -> finish it, carry the last words over
                tail = " ".join(_words("\n".join(buffer))[-overlap_words:]) if overlap_words else ""
                flush()
                buffer = [tail] if tail else []
                buffer_page = page_no

            words = _words(block)
            if len(words) <= chunk_words:
                buffer.append(block)  # keep original line breaks (numbered steps)
                continue
            # rule 4: one very long block -> cut into windows
            while len(words) > chunk_words:
                buffer.append(" ".join(words[:chunk_words]))
                flush()
                words = words[chunk_words - overlap_words:]
                buffer_page = page_no
            buffer.append(" ".join(words))
    flush()
    return chunks