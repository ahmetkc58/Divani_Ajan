from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from reportlab.lib.pagesizes import A4
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
    "dilekce": ("Genel dilekçe başvurusu", "Başvurumun incelenmesini ve gereğinin yapılmasını talep ediyorum."),
    "sikayet": ("Karayolu hakkında şikâyet", "Yaşanan sorunun incelenmesini ve gereğinin yapılmasını istiyorum."),
    "itiraz": ("İşleme itiraz başvurusu", "İşleme itirazımın değerlendirilmesini ve kararın yeniden incelenmesini talep ediyorum."),
    "talep": ("Yol bakım ve onarım talebi", "Belirtilen konumda gerekli bakım ve onarım çalışmasının yapılmasını talep ediyorum."),
    "izin": ("Karayolu çalışma izin başvurusu", "Çalışma için gerekli iznin değerlendirilerek tarafıma bildirilmesini talep ediyorum."),
    "belge": ("Belge ve bilgi talebi", "İstenen belgenin tarafıma verilmesini talep ediyorum."),
}


def _register_font() -> str:
    candidates = (
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf"),
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "calibri.ttf"),
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            pdfmetrics.registerFont(TTFont("SyntheticTurkish", candidate))
            return "SyntheticTurkish"
    return "Helvetica"


def _draw_pdf(path: Path, lines: list[str], *, scanned: bool) -> None:
    canvas = Canvas(str(path), pagesize=A4)
    width, height = A4
    font = _register_font()
    canvas.setFont(font, 11)
    y = height - 70
    for line in lines:
        canvas.drawString(65, y, line[:105])
        y -= 22
        if y < 70:
            canvas.showPage()
            canvas.setFont(font, 11)
            y = height - 70
    canvas.setFont(font, 8)
    canvas.drawString(65, 40, "SENTETIK TEST EVRAKI - GERCEK HUKUKI BELGE DEGILDIR")
    canvas.save()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for document_type, (subject, request) in CASES.items():
        for polarity in ("olumlu", "olumsuz"):
            for number in range(1, 11):
                missing: list[str] = []
                include_sender = polarity == "olumlu" or number not in {1, 4, 7}
                include_location = polarity == "olumlu" or number not in {2, 5, 8}
                include_request = polarity == "olumlu" or number not in {3, 6, 9}
                if not include_sender:
                    missing.append("gonderen")
                if not include_location and document_type in {"talep", "sikayet"}:
                    missing.append("konum")
                if not include_request:
                    missing.append("talep")
                document_id = f"{document_type}_{polarity}_{number:02d}"
                lines = [
                    "ÖRNEK KARAYOLU GENEL MÜDÜRLÜĞÜ",
                    f"{document_type.upper()} TEST EVRAKI",
                    "",
                ]
                if include_sender:
                    lines.append(f"Gönderen: {NAMES[(number - 1) % len(NAMES)]}")
                lines.append(f"Tarih: {number:02d}.08.2026")
                lines.append(f"Konu: {subject}")
                if include_location:
                    lines.append(f"Konum: {LOCATIONS[(number - 1) % len(LOCATIONS)]}")
                lines.extend(["", "Belirtilen hususla ilgili başvuru kaydıdır."])
                if include_request:
                    lines.append(request)
                filename = f"{document_id}.pdf"
                _draw_pdf(OUTPUT_DIR / filename, lines, scanned=polarity == "olumsuz" and number % 2 == 0)
                rows.append({
                    "document_id": document_id,
                    "filename": filename,
                    "document_type": document_type,
                    "polarity": polarity,
                    "expected_missing_fields": json.dumps(missing, ensure_ascii=False),
                    "synthetic": "true",
                })
    with MANIFEST.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} PDF oluşturuldu: {OUTPUT_DIR}")
    print(f"Manifest: {MANIFEST}")


if __name__ == "__main__":
    main()