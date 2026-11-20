"""Text extraction for uploaded documents. Everything happens in memory: the file is never
written to disk, and the caller discards the text once it is fingerprinted."""

import io
import zipfile

from docx import Document
from pypdf import PdfReader
from pypdf.errors import LimitReachedError, PyPdfError

from gateway.app.protected.errors import InvalidInputError, TooLargeError, UnsupportedFileError

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
# A small upload can unpack to gigabytes. These bound what one file may expand to.
MAX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 2000
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
_TEXT_ENCODINGS = ("utf-8-sig", "cp1253")


def _too_large() -> TooLargeError:
    limit = MAX_EXPANDED_BYTES // (1024 * 1024)
    return TooLargeError(f"The file unpacks to more than {limit} MB, or {MAX_PDF_PAGES} pages")


def _pdf(content: bytes) -> str:
    """pypdf itself stops a single stream that inflates past its own limit (75 MB by
    default); the page count and the amount of text are bounded here."""
    try:
        reader = PdfReader(io.BytesIO(content))
        if len(reader.pages) > MAX_PDF_PAGES:
            raise _too_large()
        pages: list[str] = []
        extracted = 0
        for page in reader.pages:
            pages.append(page.extract_text() or "")
            extracted += len(pages[-1])
            if extracted > MAX_EXPANDED_BYTES:
                raise _too_large()
    except LimitReachedError as problem:
        raise _too_large() from problem
    except (PyPdfError, ValueError, KeyError) as problem:
        raise InvalidInputError("The PDF could not be read") from problem
    return "\n".join(pages)


def _docx(content: bytes) -> str:
    try:
        # The archive's directory states each member's unpacked size, and the zip reader
        # never reads a member past it, so the sum is known before anything is inflated.
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            expanded = sum(member.file_size for member in archive.infolist())
        if expanded > MAX_EXPANDED_BYTES:
            raise _too_large()
        document = Document(io.BytesIO(content))
    except (zipfile.BadZipFile, KeyError, ValueError) as problem:
        raise InvalidInputError("The Word document could not be read") from problem
    cells = (cell.text for table in document.tables for row in table.rows for cell in row.cells)
    return "\n".join([*(paragraph.text for paragraph in document.paragraphs), *cells])


def _plain(content: bytes) -> str:
    if b"\x00" in content:
        raise UnsupportedFileError(
            "Only text, Markdown, PDF, Word (.docx) and source files can be fingerprinted"
        )
    for encoding in _TEXT_ENCODINGS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnsupportedFileError("The file is not text in UTF-8 or Windows-1253")


def extract_text(filename: str, content: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf") or content.startswith(_PDF_MAGIC):
        text = _pdf(content)
    elif name.endswith(".docx") or content.startswith(_ZIP_MAGIC):
        text = _docx(content)
    else:
        text = _plain(content)
    if not text.strip():
        raise InvalidInputError("No text could be extracted from this file")
    return text
