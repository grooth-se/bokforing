"""
Tester för SIE-import
"""
import pytest
from datetime import date
from decimal import Decimal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.sie_import import SIEParser, SIEImporter
from app.models.base import Base, engine, SessionLocal


# Exempel på SIE4-fil
SAMPLE_SIE = """
#FLAGGA 0
#FORMAT PC8
#SIETYP 4
#PROGRAM "Test" 1.0
#GEN 20240115
#FNAMN "Test AB"
#ORGNR 5561234567
#RAR 0 20240101 20241231
#KONTO 1930 "Företagskonto"
#KONTO 3010 "Försäljning"
#KONTO 2410 "Leverantörsskulder"
#IB 0 1930 50000.00
#VER A 1 20240115 "Försäljning kontant"
{
#TRANS 1930 {} 1000.00
#TRANS 3010 {} -1000.00
}
#VER A 2 20240120 "Inköp"
{
#TRANS 2410 {} -500.00
#TRANS 1930 {} -500.00
}
"""


@pytest.fixture
def db():
    """Skapa en ny databas för varje test"""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


class TestSIEParser:
    def test_parse_company_name(self):
        """Testa parsing av företagsnamn"""
        parser = SIEParser()
        data = parser.parse(SAMPLE_SIE)
        assert data.company_name == "Test AB"

    def test_parse_org_number(self):
        """Testa parsing av organisationsnummer"""
        parser = SIEParser()
        data = parser.parse(SAMPLE_SIE)
        assert data.org_number == "5561234567"

    def test_parse_fiscal_year(self):
        """Testa parsing av räkenskapsår"""
        parser = SIEParser()
        data = parser.parse(SAMPLE_SIE)
        assert data.fiscal_year_start == date(2024, 1, 1)
        assert data.fiscal_year_end == date(2024, 12, 31)

    def test_parse_accounts(self):
        """Testa parsing av konton"""
        parser = SIEParser()
        data = parser.parse(SAMPLE_SIE)
        assert len(data.accounts) == 3

        account_numbers = [a.number for a in data.accounts]
        assert "1930" in account_numbers
        assert "3010" in account_numbers
        assert "2410" in account_numbers

    def test_parse_opening_balance(self):
        """Testa parsing av ingående balans"""
        parser = SIEParser()
        data = parser.parse(SAMPLE_SIE)
        assert "1930" in data.opening_balances
        assert data.opening_balances["1930"] == Decimal("50000.00")

    def test_parse_transactions(self):
        """Testa parsing av transaktioner"""
        parser = SIEParser()
        data = parser.parse(SAMPLE_SIE)
        assert len(data.transactions) == 2

        # Första transaktionen
        tx1 = data.transactions[0]
        assert tx1.verification_number == 1
        assert tx1.date == date(2024, 1, 15)
        assert tx1.description == "Försäljning kontant"
        assert len(tx1.lines) == 2


class TestSIEImporter:
    def test_import_creates_company(self, db):
        """Testa att import skapar företag"""
        importer = SIEImporter(db)
        stats = importer.import_file(SAMPLE_SIE)

        assert stats['company_created'] is True

    def test_import_creates_accounts(self, db):
        """Testa att import skapar konton"""
        importer = SIEImporter(db)
        stats = importer.import_file(SAMPLE_SIE)

        assert stats['accounts_imported'] == 3

    def test_import_creates_transactions(self, db):
        """Testa att import skapar transaktioner"""
        importer = SIEImporter(db)
        stats = importer.import_file(SAMPLE_SIE)

        assert stats['transactions_imported'] == 2
