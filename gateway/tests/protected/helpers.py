"""Invented documents and file builders shared by the protected-data and T2 tests."""

import io
import zipfile

from docx import Document

CONTRACT = """MASTER SERVICES AGREEMENT between Zephyros Maritime Ltd and Aspida Demo S.A.
This agreement sets out the terms under which the supplier provides vessel tracking
services to the customer. The supplier shall deliver the tracking platform described in
schedule one within ninety days of the effective date, and shall maintain an availability
of ninety nine point five percent measured monthly. The customer shall pay the annual fee
of two hundred and forty thousand euro in four equal instalments, each due thirty days
after the date of the invoice. Either party may terminate this agreement for material
breach on sixty days written notice if the breach is not remedied within that period.
Liability of the supplier is capped at the fees paid in the twelve months before the
claim, except for breach of confidentiality, data protection obligations or wilful
misconduct. The parties agree that the harbour telemetry dataset, the routing heuristics
and the tariff model called Meltemi remain the exclusive property of the supplier.
This agreement is governed by the laws of Greece and the courts of Piraeus have exclusive
jurisdiction. Signed for the customer by the chief operating officer and for the supplier
by the managing director on the effective date written above, in two original copies."""

RECIPE = """Για να φτιάξεις μουσακά χρειάζεσαι μελιτζάνες, πατάτες, κιμά, ντομάτα, κρεμμύδι
και μπεσαμέλ. Κόψε τις μελιτζάνες σε φέτες, αλάτισέ τες και άφησέ τες μισή ώρα να
στραγγίξουν. Τσιγάρισε το κρεμμύδι με τον κιμά, πρόσθεσε τη ντομάτα, λίγη κανέλα και
άφησε τη σάλτσα να δέσει. Στρώσε τις πατάτες, μετά τις μελιτζάνες, τον κιμά και από πάνω
την μπεσαμέλ με τριμμένο τυρί. Ψήσε στους εκατόν ογδόντα βαθμούς για περίπου μία ώρα,
μέχρι να ροδίσει καλά η επιφάνεια. Άφησε το φαγητό να κρυώσει λίγο πριν το κόψεις."""

DISTINCTIVE_PHRASES = ("tariff model called Meltemi", "harbour telemetry", "courts of Piraeus")


def excerpt(text: str, first_word: int, words: int) -> str:
    return " ".join(text.split()[first_word : first_word + words])


def docx_bytes(text: str) -> bytes:
    document = Document()
    for paragraph in text.split("\n"):
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def docx_bomb(unpacked_bytes: int) -> bytes:
    """A Word file a few kilobytes long whose body unpacks to `unpacked_bytes`."""
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", b"\x00" * unpacked_bytes)
    return packed.getvalue()


def pdf_document(content_stream: bytes) -> bytes:
    """A minimal one-page PDF around the given content stream object."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        content_stream,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = b"%PDF-1.4\n"
    offsets: list[int] = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + content + b"\nendobj\n"
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    body += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    body += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return body


def pdf_bytes(lines: list[str]) -> bytes:
    """A minimal one-page PDF with the given lines of ASCII text."""
    shown = "\n".join(f"({line.replace('(', '[').replace(')', ']')}) Tj 0 -14 Td" for line in lines)
    stream = f"BT /F1 11 Tf 40 780 Td\n{shown}\nET".encode("latin-1")
    return pdf_document(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    )


SERVICE_TERMS = """SERVICES AGREEMENT. This agreement is made between the supplier and the
customer named in the order form. The supplier shall provide the services described in
schedule one with reasonable skill and care. The customer shall pay the fees set out in the
order form within thirty days of the date of each invoice. Either party may terminate this
agreement on thirty days written notice if the other party commits a material breach and
fails to remedy it. The liability of each party is limited to the fees paid in the twelve
months before the claim. Each party shall keep the confidential information of the other
party secret. This agreement is governed by the laws of the jurisdiction named in the order
form, and the courts of that jurisdiction have exclusive jurisdiction over any dispute."""

LEASE_TERMS = """LEASE AGREEMENT. The landlord lets the premises to the tenant for the term
stated below. The tenant shall pay the rent in advance on the first day of each month and
shall keep the premises in good repair. The tenant shall not assign this agreement or sublet
the premises without the written consent of the landlord. Either party may terminate this
agreement on ninety days written notice. On termination the tenant shall return the premises
in the condition in which they were received. The deposit is returned within thirty days,
less any sums due. This agreement is governed by the laws of the country where the premises
are located, and the parties submit to the exclusive jurisdiction of its courts."""

SOURCE_FILE = """import json
from dataclasses import dataclass


@dataclass
class Position:
    latitude: float
    longitude: float


def load_positions(path: str) -> list[Position]:
    with open(path, encoding="utf-8") as handle:
        rows = json.load(handle)
    return [Position(row["lat"], row["lon"]) for row in rows]


def bounding_box(positions: list[Position]) -> tuple[float, float, float, float]:
    latitudes = [position.latitude for position in positions]
    longitudes = [position.longitude for position in positions]
    return min(latitudes), min(longitudes), max(latitudes), max(longitudes)
"""

SOURCE_FILE_2 = """from collections import defaultdict


class Inventory:
    def __init__(self) -> None:
        self.stock: dict[str, int] = defaultdict(int)

    def add(self, item: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self.stock[item] += quantity

    def remove(self, item: str, quantity: int) -> None:
        if self.stock[item] < quantity:
            raise ValueError("not enough stock")
        self.stock[item] -= quantity

    def report(self) -> list[tuple[str, int]]:
        return sorted(self.stock.items())
"""

HOLIDAY_REQUEST = """Hello, could you help me write a friendly message to my colleagues? I am
going on holiday next week and I would like to tell them who covers for me, where the
handover notes are, and that I will not read email until I am back. Keep it short and warm,
and add a line wishing everyone a good week. Thank you very much for your help with this."""

TRAVEL_QUESTION = """What are the best places to visit on a three day trip to an island in
spring? We like walking, swimming when the weather allows, small villages and local food.
We would rather avoid crowded places and long drives. Please suggest a simple plan for each
day, with a few ideas for where to eat, and tell us what to pack for changeable weather."""

EXEMPLARS = (
    ("contract-en-01", "contract", "en", SERVICE_TERMS),
    ("contract-en-02", "contract", "en", LEASE_TERMS),
    ("code-py-01", "source code", "en", SOURCE_FILE),
    ("code-py-02", "source code", "en", SOURCE_FILE_2),
    ("benign-en-01", "benign", "en", HOLIDAY_REQUEST),
    ("benign-en-02", "benign", "en", TRAVEL_QUESTION),
    ("benign-el-01", "benign", "el", RECIPE),
)

RESEMBLES_A_CONTRACT = """Please tidy up the wording of this clause for me. The supplier shall
provide the support services described in schedule two with reasonable skill and care. The
customer shall pay the fees within thirty days of the date of each invoice. Either party may
terminate this agreement on sixty days written notice if the other party commits a material
breach. This agreement is governed by the laws of Greece and the courts of Athens have
exclusive jurisdiction over any dispute arising from it."""
