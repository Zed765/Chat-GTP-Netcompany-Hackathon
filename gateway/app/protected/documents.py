"""Turns a document into fingerprint vectors: mask, chunk, embed. The text goes no further."""

import asyncio

from gateway.app.detect.fingerprint import chunks, mask_by_type
from gateway.app.detect.local import LocalEngine
from gateway.app.llm.client import LLM, Matrix

MASK_BLOCK_CHARS = 8000


def _blocks(text: str) -> list[str]:
    """Whole lines up to the block size; a longer line is cut."""
    blocks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        for start in range(0, len(line), MASK_BLOCK_CHARS):
            piece = line[start : start + MASK_BLOCK_CHARS]
            if current and len(current) + len(piece) > MASK_BLOCK_CHARS:
                blocks.append(current)
                current = ""
            current += piece
    return [*blocks, current] if current else blocks


def mask_document(engine: LocalEngine, text: str) -> str:
    """Mask by type with T0 and T1, block by block so a long file stays within budget."""
    return "".join(mask_by_type(block, engine.detect(block).findings) for block in _blocks(text))


async def fingerprint(engine: LocalEngine, llm: LLM, text: str) -> Matrix:
    """One L2-normalised vector per chunk of the masked text."""
    masked = await asyncio.to_thread(mask_document, engine, text)
    return (await llm.embed(chunks(masked))).value
