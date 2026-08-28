from __future__ import annotations

import csv
from io import BytesIO
import json
import os
from pathlib import Path

import pymupdf
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "synthetic_documents" / "pdf"
MANIFEST = ROOT / "data" / "synthetic_documents" / "manifest.csv"

NAMES = ("Ayşe Örnek", "Mehmet Kurgu", "Elif Deneme", "Can Kurgusal", "Zeynep Test")
LOCATIONS = (
    "Örnek İl, Merkez, D-100 yolu 12. kilometre",
    "Kurgu İlçesi, devlet yolu 8. kilometre",
    "Deneme Beldesi, çevre yolu kuzey bağlantısı",
    "Örnek Köyü kavşağı, il yolu 4. kilometre",
    "Kurgu Mahallesi, otoyol bağlantı kolu",
)
CASES = {
    "dilekce": (
        "Genel başvurumun değerlendirilmesi",
        "Dilekçemin incelenerek sonucunun tarafıma bildirilmesini arz ederim.",
    ),
    "sikayet": (
        "Karayolu çevresindeki sürekli gürültü",
        "Uzun süredir yaşanan rahatsızlığın incelenmesini ve giderilmesini istiyorum.",
    ),
    "itiraz": (
        "Bildirilen işlemin yeniden değerlendirilmesi",
        "Tarafıma bildirilen işleme itiraz ediyor, kararın yeniden incelenmesini talep ediyorum.",
    ),
    "talep": (
        "Yol yüzeyindeki bozulmanın giderilmesi",
        "Belirtilen konumda gerekli bakım ve onarım çalışmasının yapılmasını talep ediyorum.",
    ),
    "izin": (
        "Yol kenarında ölçüm çalışması yapılması",
        "Planlanan çalışmanın yapılabilmesi için gerekli iznin verilmesini talep ediyorum.",
    ),
    "belge": (
        "Bakım programına ilişkin kayıt örneği",
        "İlgili bilgi ve belge örneğinin tarafıma verilmesini talep ediyorum.",
    ),
}


def _register_font() -> str:
    windows = os.environ.get("WINDIR", r"C:\Windows")
    candidates = (
        Path(windows) / "Fonts" / "arial.ttf",
        Path(windows) / "Fonts" / "calibri.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            pdfmetrics.registerFont(TTFont("SyntheticTurkish", str(candidate)))
            return "SyntheticTurkish"
    return "Helvetica"


def _text_pdf(lines: list[str]) -> bytes:
    target = BytesIO()
    canvas = Canvas(target, pagesize=A4)
    font = _register_font()
    _, height = A4
    canvas.setFont(font, 11)
    y = height - 70
    for line in lines:
        canvas.drawString(65, y, line[:105])
        y -= 22
    canvas.setFont(font, 8)
    canvas.drawString(65, 40, "SENTETİK VERİ - GERÇEK KİŞİ VEYA KAMU EVRAKI DEĞİLDİR")
    canvas.save()
    return target.getvalue()


def _raster_only_pdf(source: bytes) -> bytes:
    document = pymupdf.open(stream=source, filetype="pdf")
    output = BytesIO()
    canvas = Canvas(output, pagesize=A4)
    width, height = A4
    try:
        for page in document:
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            canvas.drawImage(
                ImageReader(BytesIO(pixmap.tobytes("png"))),
                0,
                0,
                width=width,
                height=height,
            )
            canvas.showPage()
    finally:
        document.close()
    canvas.save()
    return output.getvalue()


def _write_pdf(path: Path, lines: list[str], *, scanned: bool) -> None:
    content = _text_pdf(lines)
    path.write_bytes(_raster_only_pdf(content) if scanned else content)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for document_type, (subject, request) in CASES.items():
        for completeness in ("tam", "eksik"):
            for number in range(1, 11):
                missing: list[str] = []
                include_sender = completeness == "tam" or number not in {1, 4, 7}
                include_location = completeness == "tam" or number not in {2, 5, 8}
                include_request = completeness == "tam" or number not in {3, 6, 9}
                if not include_sender:
                    missing.append("gonderen")
                if not include_location and document_type in {"talep", "sikayet", "izin"}:
                    missing.append("konum")
                if not include_request:
                    missing.append("talep")
                document_id = f"{document_type}_{completeness}_{number:02d}"
                lines = ["ÖRNEK KARAYOLU GENEL MÜDÜRLÜĞÜ", ""]
                if include_sender:
                    lines.append(f"Başvuran: {NAMES[(number - 1) % len(NAMES)]}")
                lines.extend(
                    [
                        f"Tarih: {number:02d}.08.2026",
                        f"Konu: {subject}",
                    ]
                )
                if include_location:
                    lines.append(f"Konum: {LOCATIONS[(number - 1) % len(LOCATIONS)]}")
                lines.extend(["", "Aşağıda açıklanan husus hakkında başvuruda bulunuyorum."])
                if include_request:
                    lines.append(request)
                scanned = completeness == "eksik" and number % 2 == 0
                filename = f"{document_id}.pdf"
                _write_pdf(OUTPUT_DIR / filename, lines, scanned=scanned)
                rows.append(
                    {
                        "document_id": document_id,
                        "filename": filename,
                        "general_document_type": document_type,
                        "completeness": completeness,
                        "scanned": str(scanned).lower(),
                        "expected_missing_fields": json.dumps(
                            missing, ensure_ascii=False
                        ),
                        "synthetic": "true",
                    }
                )
    with MANIFEST.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} PDF generated: {OUTPUT_DIR}")
    print(f"Manifest: {MANIFEST}")


if __name__ == "__main__":
    main()
