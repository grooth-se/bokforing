"""
Konfiguration för bokföringssystemet
"""
from enum import Enum
from pathlib import Path

# Projektrot
BASE_DIR = Path(__file__).resolve().parent.parent

# Databas
DATABASE_URL = f"sqlite:///{BASE_DIR}/data/bokforing.db"

# Verifikatmapp
VOUCHER_DIR = BASE_DIR / "data" / "vouchers"


class AccountingStandard(str, Enum):
    """Svenska redovisningsstandarder"""
    K2 = "K2"  # Förenklat regelverk för mindre företag
    K3 = "K3"  # Principbaserat huvudregelverk


class AccountType(str, Enum):
    """Kontotyper enligt BAS"""
    ASSET = "Tillgång"
    LIABILITY = "Skuld"
    EQUITY = "Eget kapital"
    REVENUE = "Intäkt"
    EXPENSE = "Kostnad"


# Momssatser i Sverige
VAT_RATES = {
    "standard": 0.25,  # 25% - de flesta varor och tjänster
    "reduced": 0.12,   # 12% - livsmedel, hotell, restaurang
    "low": 0.06,       # 6% - böcker, tidningar, kultur, persontransport
    "exempt": 0.0,     # 0% - momsfritt (t.ex. sjukvård, utbildning)
}

# BAS-kontoklasser
BAS_CLASSES = {
    1: "Tillgångar",
    2: "Eget kapital och skulder",
    3: "Rörelsens intäkter",
    4: "Rörelsens kostnader (varor)",
    5: "Övriga externa kostnader",
    6: "Övriga externa kostnader",
    7: "Personal",
    8: "Finansiella poster och skatter",
}
