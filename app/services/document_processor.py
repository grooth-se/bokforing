"""
Dokumenthantering - OCR och textextraktion från kvitton/fakturor

Stödjer:
- Bilder (JPG, PNG, WEBP)
- PDF-dokument
"""
import re
import io
import uuid
import shutil
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from typing import Optional
from PIL import Image

from app.config import BASE_DIR

# Försök importera OCR-bibliotek
try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

try:
    import fitz  # PyMuPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


@dataclass
class ExtractedTransaction:
    """Extraherad transaktionsdata från dokument"""
    date: Optional[date] = None
    total_amount: Optional[Decimal] = None
    vat_amount: Optional[Decimal] = None
    vat_rate: Optional[int] = None  # 25, 12, 6
    vendor: Optional[str] = None
    description: Optional[str] = None
    ocr_number: Optional[str] = None  # OCR/fakturanummer
    raw_text: str = ""
    confidence: float = 0.0  # 0-1, hur säker vi är på extraktionen


class DocumentProcessor:
    """
    Processor för att extrahera transaktionsdata från dokument
    """

    # Svenska månader för datumparsning
    MONTHS_SV = {
        'januari': 1, 'jan': 1,
        'februari': 2, 'feb': 2,
        'mars': 3, 'mar': 3,
        'april': 4, 'apr': 4,
        'maj': 5,
        'juni': 6, 'jun': 6,
        'juli': 7, 'jul': 7,
        'augusti': 8, 'aug': 8,
        'september': 9, 'sep': 9, 'sept': 9,
        'oktober': 10, 'okt': 10,
        'november': 11, 'nov': 11,
        'december': 12, 'dec': 12
    }

    # Vanliga leverantörsnamn att leta efter
    COMMON_VENDORS = [
        'ica', 'coop', 'willys', 'lidl', 'hemköp',
        'kjell', 'elgiganten', 'mediamarkt', 'netonnet',
        'bauhaus', 'hornbach', 'jula', 'biltema',
        'circle k', 'preem', 'okq8', 'shell', 'st1',
        'postnord', 'dhl', 'ups', 'schenker',
        'telia', 'tele2', 'tre', 'telenor',
        'ikea', 'jysk', 'mio', 'em',
        'h&m', 'kappahl', 'lindex', 'stadium',
        'apoteket', 'kronans apotek', 'lloyds',
        'systembolaget',
        'swish', 'klarna', 'paypal'
    ]

    def __init__(self):
        self.voucher_dir = BASE_DIR / "data" / "vouchers"
        self.voucher_dir.mkdir(parents=True, exist_ok=True)

    def process_file(self, file_content: bytes, filename: str) -> ExtractedTransaction:
        """
        Bearbeta en fil och extrahera transaktionsdata

        Args:
            file_content: Filinnehåll som bytes
            filename: Ursprungligt filnamn

        Returns:
            ExtractedTransaction med extraherad data
        """
        # Bestäm filtyp
        ext = Path(filename).suffix.lower()

        if ext == '.pdf':
            text = self._extract_text_from_pdf(file_content)
        elif ext in ['.jpg', '.jpeg', '.png', '.webp', '.tiff', '.bmp']:
            text = self._extract_text_from_image(file_content)
        else:
            raise ValueError(f"Filtyp {ext} stöds inte. Använd PDF eller bild.")

        # Extrahera transaktionsdata från texten
        return self._extract_transaction_data(text)

    def save_voucher(self, file_content: bytes, filename: str) -> str:
        """
        Spara verifikat/underlag till disk

        Returns:
            Sökväg relativ till voucher-mappen
        """
        ext = Path(filename).suffix.lower()
        unique_name = f"{uuid.uuid4().hex}{ext}"

        # Organisera i mappar per år/månad
        today = date.today()
        subdir = self.voucher_dir / str(today.year) / f"{today.month:02d}"
        subdir.mkdir(parents=True, exist_ok=True)

        file_path = subdir / unique_name
        file_path.write_bytes(file_content)

        # Returnera relativ sökväg
        return str(file_path.relative_to(self.voucher_dir))

    def _extract_text_from_pdf(self, content: bytes) -> str:
        """Extrahera text från PDF"""
        if not PDF_AVAILABLE:
            raise RuntimeError("PyMuPDF (fitz) är inte installerat. Kör: pip install pymupdf")

        text_parts = []

        # Öppna PDF från bytes
        doc = fitz.open(stream=content, filetype="pdf")

        for page in doc:
            # Försök extrahera text direkt
            page_text = page.get_text()

            if page_text.strip():
                text_parts.append(page_text)
            else:
                # Om ingen text, försök OCR på sidan som bild
                if OCR_AVAILABLE:
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x upplösning
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    ocr_text = pytesseract.image_to_string(img, lang='swe+eng')
                    text_parts.append(ocr_text)

        doc.close()
        return "\n".join(text_parts)

    def _extract_text_from_image(self, content: bytes) -> str:
        """Extrahera text från bild med OCR"""
        if not OCR_AVAILABLE:
            raise RuntimeError("pytesseract är inte installerat. Kör: pip install pytesseract")

        # Öppna bild
        img = Image.open(io.BytesIO(content))

        # Konvertera till RGB om nödvändigt
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Kör OCR med svenska och engelska
        text = pytesseract.image_to_string(img, lang='swe+eng')

        return text

    def _extract_transaction_data(self, text: str) -> ExtractedTransaction:
        """Extrahera strukturerad transaktionsdata från text"""
        result = ExtractedTransaction(raw_text=text)

        if not text.strip():
            return result

        # Normalisera text
        text_lower = text.lower()
        lines = text.split('\n')

        # Extrahera datum
        result.date = self._extract_date(text)

        # Extrahera belopp
        amounts = self._extract_amounts(text)
        if amounts:
            # Största beloppet är troligen totalen
            result.total_amount = max(amounts)

            # Leta efter moms
            vat_info = self._extract_vat(text, amounts)
            if vat_info:
                result.vat_amount, result.vat_rate = vat_info

        # Extrahera leverantör
        result.vendor = self._extract_vendor(text, lines)

        # Extrahera OCR/fakturanummer
        result.ocr_number = self._extract_ocr_number(text)

        # Skapa beskrivning
        result.description = self._generate_description(result)

        # Beräkna konfidenspoäng
        result.confidence = self._calculate_confidence(result)

        return result

    def _extract_date(self, text: str) -> Optional[date]:
        """Extrahera datum från text"""
        today = date.today()

        # Mönster för olika datumformat
        patterns = [
            # 2024-01-15, 2024/01/15
            r'(20\d{2})[-/](\d{1,2})[-/](\d{1,2})',
            # 15-01-2024, 15/01/2024
            r'(\d{1,2})[-/](\d{1,2})[-/](20\d{2})',
            # 15 januari 2024, 15 jan 2024
            r'(\d{1,2})\s+(januari|februari|mars|april|maj|juni|juli|augusti|september|oktober|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|okt|nov|dec)\s+(20\d{2})',
            # 240115 (YYMMDD)
            r'\b(\d{2})(\d{2})(\d{2})\b',
        ]

        for i, pattern in enumerate(patterns):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    groups = match.groups()

                    if i == 0:  # YYYY-MM-DD
                        return date(int(groups[0]), int(groups[1]), int(groups[2]))
                    elif i == 1:  # DD-MM-YYYY
                        return date(int(groups[2]), int(groups[1]), int(groups[0]))
                    elif i == 2:  # DD månad YYYY
                        month = self.MONTHS_SV.get(groups[1].lower(), 1)
                        return date(int(groups[2]), month, int(groups[0]))
                    elif i == 3:  # YYMMDD
                        year = 2000 + int(groups[0])
                        if year > today.year + 1:
                            year -= 100
                        return date(year, int(groups[1]), int(groups[2]))
                except (ValueError, KeyError):
                    continue

        return None

    def _extract_amounts(self, text: str) -> list[Decimal]:
        """Extrahera alla belopp från text"""
        amounts = []

        # Mönster för belopp: 1234,56 eller 1 234,56 eller 1234.56
        patterns = [
            r'(\d{1,3}(?:\s?\d{3})*)[,.](\d{2})\b',  # Med decimaler
            r'\b(\d{1,3}(?:\s?\d{3})*)\s*kr\b',  # Heltal med "kr"
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                try:
                    if len(match.groups()) == 2:
                        # Med decimaler
                        whole = match.group(1).replace(' ', '')
                        decimal = match.group(2)
                        amount = Decimal(f"{whole}.{decimal}")
                    else:
                        # Heltal
                        whole = match.group(1).replace(' ', '')
                        amount = Decimal(whole)

                    if amount > 0 and amount < 10000000:  # Rimlig gräns
                        amounts.append(amount)
                except (InvalidOperation, ValueError):
                    continue

        return list(set(amounts))  # Ta bort dubbletter

    def _extract_vat(self, text: str, amounts: list[Decimal]) -> Optional[tuple[Decimal, int]]:
        """Extrahera momsbelopp och momssats"""
        text_lower = text.lower()

        # Leta efter momssats
        vat_rate = None
        if '25%' in text or '25 %' in text or 'moms 25' in text_lower:
            vat_rate = 25
        elif '12%' in text or '12 %' in text or 'moms 12' in text_lower:
            vat_rate = 12
        elif '6%' in text or '6 %' in text or 'moms 6' in text_lower:
            vat_rate = 6

        # Leta efter momsbelopp
        vat_patterns = [
            r'moms[:\s]+(\d+[,.]?\d*)',
            r'varav moms[:\s]+(\d+[,.]?\d*)',
            r'mva[:\s]+(\d+[,.]?\d*)',
        ]

        for pattern in vat_patterns:
            match = re.search(pattern, text_lower)
            if match:
                try:
                    vat_str = match.group(1).replace(',', '.')
                    vat_amount = Decimal(vat_str)

                    # Gissa momssats om inte redan hittad
                    if not vat_rate and amounts:
                        total = max(amounts)
                        if total > 0:
                            calc_rate = (vat_amount / (total - vat_amount)) * 100
                            if 24 <= calc_rate <= 26:
                                vat_rate = 25
                            elif 11 <= calc_rate <= 13:
                                vat_rate = 12
                            elif 5 <= calc_rate <= 7:
                                vat_rate = 6

                    return (vat_amount, vat_rate or 25)
                except (InvalidOperation, ValueError):
                    continue

        # Om vi har momssats men inget belopp, beräkna det
        if vat_rate and amounts:
            total = max(amounts)
            vat_amount = total * Decimal(vat_rate) / Decimal(100 + vat_rate)
            return (vat_amount.quantize(Decimal('0.01')), vat_rate)

        return None

    def _extract_vendor(self, text: str, lines: list[str]) -> Optional[str]:
        """Extrahera leverantörsnamn"""
        text_lower = text.lower()

        # Kolla mot kända leverantörer
        for vendor in self.COMMON_VENDORS:
            if vendor in text_lower:
                return vendor.title()

        # Ta första icke-tomma raden som ofta är leverantörens namn
        for line in lines[:5]:  # Kolla första 5 raderna
            line = line.strip()
            if line and len(line) > 2 and len(line) < 50:
                # Filtrera bort siffror och vanliga rubriker
                if not re.match(r'^[\d\s,.-]+$', line):
                    if not any(word in line.lower() for word in ['kvitto', 'faktura', 'datum', 'kl:', 'org']):
                        return line

        return None

    def _extract_ocr_number(self, text: str) -> Optional[str]:
        """Extrahera OCR-nummer eller fakturanummer"""
        patterns = [
            r'ocr[:\s#]*(\d{6,25})',
            r'faktura(?:nummer)?[:\s#]*(\d{4,15})',
            r'invoice[:\s#]*(\d{4,15})',
            r'referens[:\s#]*(\d{4,15})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _generate_description(self, data: ExtractedTransaction) -> str:
        """Generera beskrivning för transaktionen"""
        parts = []

        if data.vendor:
            parts.append(data.vendor)

        if data.ocr_number:
            parts.append(f"#{data.ocr_number}")

        if parts:
            return " ".join(parts)

        return "Skannat dokument"

    def _calculate_confidence(self, data: ExtractedTransaction) -> float:
        """Beräkna konfidenspoäng för extraktionen"""
        score = 0.0

        if data.date:
            score += 0.25
        if data.total_amount:
            score += 0.30
        if data.vat_amount:
            score += 0.15
        if data.vendor:
            score += 0.20
        if data.ocr_number:
            score += 0.10

        return min(score, 1.0)


def suggest_accounts(extracted: ExtractedTransaction, vendor: Optional[str] = None) -> dict:
    """
    Föreslå bokföringskonton baserat på extraherad data

    Returns:
        dict med föreslagna konton: {"expense": "konto", "vat": "konto", "payment": "konto"}
    """
    suggestions = {
        "expense_account": "4010",  # Standard: Inköp varor
        "vat_account": "1610",  # Ingående moms
        "payment_account": "1930",  # Företagskonto
        "category": "Inköp"
    }

    vendor_lower = (vendor or extracted.vendor or "").lower()

    # Kategorisera baserat på leverantör
    if any(v in vendor_lower for v in ['ica', 'coop', 'willys', 'lidl', 'hemköp']):
        suggestions["expense_account"] = "4010"  # Inköp varor
        suggestions["category"] = "Varuinköp"

    elif any(v in vendor_lower for v in ['circle k', 'preem', 'okq8', 'shell', 'st1']):
        suggestions["expense_account"] = "5610"  # Kostnader för transportmedel
        suggestions["category"] = "Drivmedel"

    elif any(v in vendor_lower for v in ['telia', 'tele2', 'tre', 'telenor']):
        suggestions["expense_account"] = "6210"  # Telefon
        suggestions["category"] = "Telefoni"

    elif any(v in vendor_lower for v in ['postnord', 'dhl', 'ups', 'schenker']):
        suggestions["expense_account"] = "6250"  # Porto
        suggestions["category"] = "Frakt"

    elif any(v in vendor_lower for v in ['bauhaus', 'hornbach', 'jula', 'biltema']):
        suggestions["expense_account"] = "5410"  # Förbrukningsinventarier
        suggestions["category"] = "Material"

    elif any(v in vendor_lower for v in ['kjell', 'elgiganten', 'mediamarkt', 'netonnet']):
        suggestions["expense_account"] = "5420"  # Programvaror / IT
        suggestions["category"] = "IT/Elektronik"

    elif any(v in vendor_lower for v in ['ikea', 'jysk', 'mio']):
        suggestions["expense_account"] = "5410"  # Förbrukningsinventarier
        suggestions["category"] = "Kontorsinredning"

    elif any(v in vendor_lower for v in ['apoteket', 'kronans', 'lloyds']):
        suggestions["expense_account"] = "7690"  # Övriga personalkostnader
        suggestions["category"] = "Sjukvård"

    # Justera momskonto baserat på momssats
    if extracted.vat_rate == 12:
        suggestions["vat_account"] = "1610"  # Samma konto, men 12%
    elif extracted.vat_rate == 6:
        suggestions["vat_account"] = "1610"  # Samma konto, men 6%

    return suggestions
