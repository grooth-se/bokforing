"""
Tester för bokföringstjänsten
"""
import pytest
from datetime import date
from decimal import Decimal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.base import Base, engine, SessionLocal
from app.services.accounting import AccountingService


@pytest.fixture
def db():
    """Skapa en ny databas för varje test"""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def service(db):
    """Skapa en AccountingService"""
    return AccountingService(db)


class TestCompany:
    def test_create_company(self, service):
        """Testa att skapa företag"""
        company = service.create_company(
            name="Test AB",
            org_number="556123-4567"
        )
        assert company.id is not None
        assert company.name == "Test AB"
        assert company.org_number == "556123-4567"

    def test_get_company(self, service):
        """Testa att hämta företag"""
        company = service.create_company(
            name="Test AB",
            org_number="556123-4567"
        )
        fetched = service.get_company(company.id)
        assert fetched.name == "Test AB"


class TestAccounts:
    def test_load_bas_accounts(self, service):
        """Testa att ladda BAS-kontoplan"""
        company = service.create_company(
            name="Test AB",
            org_number="556123-4567"
        )
        accounts = service.load_bas_accounts(company.id)
        assert len(accounts) > 0

        # Kontrollera att vi har några förväntade konton
        account_numbers = [a.number for a in accounts]
        assert "1930" in account_numbers  # Företagskonto
        assert "3010" in account_numbers  # Försäljning
        assert "2410" in account_numbers  # Leverantörsskulder


class TestTransactions:
    def test_create_transaction(self, service):
        """Testa att skapa transaktion"""
        company = service.create_company(
            name="Test AB",
            org_number="556123-4567"
        )
        accounts = service.load_bas_accounts(company.id)
        fiscal_year = service.create_fiscal_year(
            company.id,
            date(2024, 1, 1),
            date(2024, 12, 31)
        )

        bank = service.get_account_by_number(company.id, "1930")
        sales = service.get_account_by_number(company.id, "3010")

        transaction = service.create_transaction(
            company_id=company.id,
            fiscal_year_id=fiscal_year.id,
            transaction_date=date(2024, 1, 15),
            description="Försäljning kontant",
            lines=[
                {"account_id": bank.id, "debit": Decimal("1000"), "credit": Decimal("0")},
                {"account_id": sales.id, "debit": Decimal("0"), "credit": Decimal("1000")}
            ]
        )

        assert transaction.verification_number == 1
        assert len(transaction.lines) == 2

    def test_unbalanced_transaction_fails(self, service):
        """Testa att obalanserad transaktion kastar fel"""
        company = service.create_company(
            name="Test AB",
            org_number="556123-4567"
        )
        accounts = service.load_bas_accounts(company.id)
        fiscal_year = service.create_fiscal_year(
            company.id,
            date(2024, 1, 1),
            date(2024, 12, 31)
        )

        bank = service.get_account_by_number(company.id, "1930")
        sales = service.get_account_by_number(company.id, "3010")

        with pytest.raises(ValueError, match="balanserar inte"):
            service.create_transaction(
                company_id=company.id,
                fiscal_year_id=fiscal_year.id,
                transaction_date=date(2024, 1, 15),
                description="Obalanserad",
                lines=[
                    {"account_id": bank.id, "debit": Decimal("1000"), "credit": Decimal("0")},
                    {"account_id": sales.id, "debit": Decimal("0"), "credit": Decimal("500")}
                ]
            )


class TestBalance:
    def test_account_balance(self, service):
        """Testa kontoberäkning"""
        company = service.create_company(
            name="Test AB",
            org_number="556123-4567"
        )
        accounts = service.load_bas_accounts(company.id)
        fiscal_year = service.create_fiscal_year(
            company.id,
            date(2024, 1, 1),
            date(2024, 12, 31)
        )

        bank = service.get_account_by_number(company.id, "1930")
        sales = service.get_account_by_number(company.id, "3010")

        # Skapa transaktion
        service.create_transaction(
            company_id=company.id,
            fiscal_year_id=fiscal_year.id,
            transaction_date=date(2024, 1, 15),
            description="Försäljning",
            lines=[
                {"account_id": bank.id, "debit": Decimal("1000"), "credit": Decimal("0")},
                {"account_id": sales.id, "debit": Decimal("0"), "credit": Decimal("1000")}
            ]
        )

        # Kontrollera saldon
        bank_balance = service.get_account_balance(bank.id)
        sales_balance = service.get_account_balance(sales.id)

        assert bank_balance == Decimal("1000")  # Tillgång, debet ökar
        assert sales_balance == Decimal("1000")  # Intäkt, kredit ökar

    def test_trial_balance(self, service):
        """Testa råbalans"""
        company = service.create_company(
            name="Test AB",
            org_number="556123-4567"
        )
        accounts = service.load_bas_accounts(company.id)
        fiscal_year = service.create_fiscal_year(
            company.id,
            date(2024, 1, 1),
            date(2024, 12, 31)
        )

        bank = service.get_account_by_number(company.id, "1930")
        sales = service.get_account_by_number(company.id, "3010")

        service.create_transaction(
            company_id=company.id,
            fiscal_year_id=fiscal_year.id,
            transaction_date=date(2024, 1, 15),
            description="Försäljning",
            lines=[
                {"account_id": bank.id, "debit": Decimal("1000"), "credit": Decimal("0")},
                {"account_id": sales.id, "debit": Decimal("0"), "credit": Decimal("1000")}
            ]
        )

        trial_balance = service.get_trial_balance(company.id)

        assert len(trial_balance) == 2
        total_debit = sum(b["debit"] for b in trial_balance)
        total_credit = sum(b["credit"] for b in trial_balance)
        assert total_debit == total_credit
