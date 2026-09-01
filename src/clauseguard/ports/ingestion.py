"""Port: document ingestion.

A :class:`DocumentParser` turns raw bytes (a PDF, an image, etc.) into text plus
any recovered table structure and light metadata. Concrete adapters live under
``clauseguard.adapters.ingestion``. Carrying ``tables`` (not just flattened
text) is what enables layout-aware extraction downstream: the geometry of a
digital PDF's line-item table is reconstructed here, once, and interpreted by
the extraction layer.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ParsedDocument(BaseModel):
    """Text, recovered tables, and metadata extracted from a raw document.

    Attributes:
        text: Flattened plain text (headers, prose, and table cells linearised).
        page_count: Number of pages parsed.
        source_ref: Filename/URI used for citations downstream.
        tables: Zero or more tables recovered from the document's layout, each a
            list of rows, each row a list of cell strings. Empty when the source
            has no detectable table structure (e.g. plain text or a scan without
            OCR+layout).
    """

    text: str
    page_count: int
    source_ref: str
    tables: list[list[list[str]]] = Field(default_factory=list)


@runtime_checkable
class DocumentParser(Protocol):
    """Parse raw document bytes into text and recovered tables."""

    def parse(self, content: bytes, *, source_ref: str) -> ParsedDocument:
        """Parse ``content`` into a :class:`ParsedDocument`.

        Args:
            content: Raw document bytes.
            source_ref: A label identifying the source (filename/URI) used for
                citations downstream.

        Returns:
            The parsed document.

        Raises:
            UnsupportedDocumentError: If the format cannot be handled.
            DocumentParseError: If parsing fails.
        """
        ...
