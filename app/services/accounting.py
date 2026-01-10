"""
Bokföringstjänst - Kärnlogik för transaktioner och kontohantering
"""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.config import BASE_DIR, AccountType
from app.models import Company, Account, FiscalYear, Transaction, TransactionLine


class AccountingService:
    """
    Tjänst för bokföringsoperationer

    Hanterar:
    - Företag och kontoplaner
    - Transaktioner med dubbel bokföring
    - Räkenskapsår
    - Balanser och saldon
    """

    def __init__(self, db: Session):
        self.db = db

    # === FÖRETAG ===

    def create_company(
        self,
        name: str,
        org_number: str,
        accounting_standard: str = "K2",
        fiscal_year_start_month: int = 1
    ) -> Company:
        """Skapa ett nytt företag"""
        company = Company(
            name=name,
            org_number=org_number,
            accounting_standard=accounting_standard,
            fiscal_year_start_month=fiscal_year_start_month
        )
        self.db.add(company)
        self.db.commit()
        self.db.refresh(company)
        return company

    def get_company(self, company_id: int) -> Optional[Company]:
        """Hämta företag"""
        return self.db.query(Company).filter(Company.id == company_id).first()

    def get_all_companies(self) -> list[Company]:
        """Hämta alla företag"""
        return self.db.query(Company).all()

    # === KONTOPLAN ===

    def load_bas_accounts(self, company_id: int) -> list[Account]:
        """Ladda BAS-kontoplan för ett företag"""
        bas_file = BASE_DIR / "data" / "bas_kontoplan.json"

        with open(bas_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        type_mapping = {
            "Tillgång": AccountType.ASSET,
            "Skuld": AccountType.LIABILITY,
            "Eget kapital": AccountType.EQUITY,
            "Intäkt": AccountType.REVENUE,
            "Kostnad": AccountType.EXPENSE,
        }

        accounts = []
        for acc_data in data["accounts"]:
            account = Account(
                company_id=company_id,
                number=acc_data["number"],
                name=acc_data["name"],
                account_type=type_mapping.get(acc_data["type"], AccountType.ASSET),
                vat_code=acc_data.get("vat_code"),
            )
            self.db.add(account)
            accounts.append(account)

        self.db.commit()
        return accounts

    def get_accounts(self, company_id: int) -> list[Account]:
        """Hämta alla konton för ett företag"""
        return (
            self.db.query(Account)
            .filter(Account.company_id == company_id)
            .order_by(Account.number)
            .all()
        )

    def get_account_by_number(self, company_id: int, number: str) -> Optional[Account]:
        """Hämta konto via kontonummer"""
        return (
            self.db.query(Account)
            .filter(Account.company_id == company_id, Account.number == number)
            .first()
        )

    # === RÄKENSKAPSÅR ===

    def create_fiscal_year(
        self,
        company_id: int,
        start_date: date,
        end_date: date
    ) -> FiscalYear:
        """Skapa ett nytt räkenskapsår"""
        fiscal_year = FiscalYear(
            company_id=company_id,
            start_date=start_date,
            end_date=end_date
        )
        self.db.add(fiscal_year)
        self.db.commit()
        self.db.refresh(fiscal_year)
        return fiscal_year

    def get_current_fiscal_year(self, company_id: int) -> Optional[FiscalYear]:
        """Hämta aktuellt räkenskapsår (där dagens datum ligger inom perioden)"""
        today = date.today()
        return (
            self.db.query(FiscalYear)
            .filter(
                FiscalYear.company_id == company_id,
                FiscalYear.start_date <= today,
                FiscalYear.end_date >= today
            )
            .first()
        )

    def get_active_fiscal_year(self, company_id: int) -> Optional[FiscalYear]:
        """
        Hämta aktivt räkenskapsår - först nuvarande, annars senaste.
        Används för att hantera importerad historisk data.
        """
        # Försök hitta nuvarande räkenskapsår
        current = self.get_current_fiscal_year(company_id)
        if current:
            return current

        # Annars hämta senaste räkenskapsåret
        return (
            self.db.query(FiscalYear)
            .filter(FiscalYear.company_id == company_id)
            .order_by(FiscalYear.end_date.desc())
            .first()
        )

    def get_fiscal_years(self, company_id: int) -> list[FiscalYear]:
        """Hämta alla räkenskapsår för ett företag"""
        return (
            self.db.query(FiscalYear)
            .filter(FiscalYear.company_id == company_id)
            .order_by(FiscalYear.start_date.desc())
            .all()
        )

    # === TRANSAKTIONER ===

    def get_next_verification_number(self, company_id: int, fiscal_year_id: int) -> int:
        """Hämta nästa verifikationsnummer"""
        max_ver = (
            self.db.query(func.max(Transaction.verification_number))
            .filter(
                Transaction.company_id == company_id,
                Transaction.fiscal_year_id == fiscal_year_id
            )
            .scalar()
        )
        return (max_ver or 0) + 1

    def create_transaction(
        self,
        company_id: int,
        fiscal_year_id: int,
        transaction_date: date,
        description: str,
        lines: list[dict]
    ) -> Transaction:
        """
        Skapa en ny transaktion med konteringsrader

        lines: lista med dicts: {"account_id": int, "debit": Decimal, "credit": Decimal}

        Kastar ValueError om transaktionen inte balanserar.
        """
        # Validera att debet = kredit
        total_debit = sum(Decimal(str(line.get("debit", 0))) for line in lines)
        total_credit = sum(Decimal(str(line.get("credit", 0))) for line in lines)

        if total_debit != total_credit:
            raise ValueError(
                f"Transaktionen balanserar inte: debet={total_debit}, kredit={total_credit}"
            )

        if total_debit == 0:
            raise ValueError("Transaktionen har inga belopp")

        # Skapa transaktion
        ver_number = self.get_next_verification_number(company_id, fiscal_year_id)

        transaction = Transaction(
            company_id=company_id,
            fiscal_year_id=fiscal_year_id,
            verification_number=ver_number,
            transaction_date=transaction_date,
            description=description
        )
        self.db.add(transaction)
        self.db.flush()  # För att få transaction.id

        # Skapa konteringsrader
        for line_data in lines:
            line = TransactionLine(
                transaction_id=transaction.id,
                account_id=line_data["account_id"],
                debit=Decimal(str(line_data.get("debit", 0))),
                credit=Decimal(str(line_data.get("credit", 0))),
                description=line_data.get("description")
            )
            self.db.add(line)

        self.db.commit()
        self.db.refresh(transaction)
        return transaction

    def get_transactions(
        self,
        company_id: int,
        fiscal_year_id: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        ver_from: Optional[int] = None,
        ver_to: Optional[int] = None
    ) -> list[Transaction]:
        """Hämta transaktioner med filter"""
        query = self.db.query(Transaction).filter(Transaction.company_id == company_id)

        if fiscal_year_id:
            query = query.filter(Transaction.fiscal_year_id == fiscal_year_id)
        if start_date:
            query = query.filter(Transaction.transaction_date >= start_date)
        if end_date:
            query = query.filter(Transaction.transaction_date <= end_date)
        if ver_from:
            query = query.filter(Transaction.verification_number >= ver_from)
        if ver_to:
            query = query.filter(Transaction.verification_number <= ver_to)

        return query.order_by(Transaction.verification_number).all()

    def get_transaction_count(self, company_id: int, fiscal_year_id: int) -> int:
        """Hämta antal transaktioner för ett räkenskapsår"""
        return (
            self.db.query(func.count(Transaction.id))
            .filter(
                Transaction.company_id == company_id,
                Transaction.fiscal_year_id == fiscal_year_id
            )
            .scalar() or 0
        )

    # === SALDON ===

    def get_account_balance(
        self,
        account_id: int,
        end_date: Optional[date] = None
    ) -> Decimal:
        """
        Beräkna saldo för ett konto

        För tillgångar och kostnader: debet - kredit
        För skulder, eget kapital och intäkter: kredit - debet
        """
        account = self.db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return Decimal(0)

        query = (
            self.db.query(
                func.coalesce(func.sum(TransactionLine.debit), 0),
                func.coalesce(func.sum(TransactionLine.credit), 0)
            )
            .join(Transaction)
            .filter(TransactionLine.account_id == account_id)
        )

        if end_date:
            query = query.filter(Transaction.transaction_date <= end_date)

        result = query.first()
        total_debit = Decimal(str(result[0]))
        total_credit = Decimal(str(result[1]))

        # Tillgångar och kostnader har normalt debetsaldo
        if account.account_type in [AccountType.ASSET, AccountType.EXPENSE]:
            return total_debit - total_credit + (account.opening_balance or Decimal(0))
        # Skulder, EK och intäkter har normalt kreditsaldo
        else:
            return total_credit - total_debit + (account.opening_balance or Decimal(0))

    def get_trial_balance(
        self,
        company_id: int,
        end_date: Optional[date] = None
    ) -> list[dict]:
        """
        Generera råbalans (saldon för alla konton)
        """
        accounts = self.get_accounts(company_id)
        balances = []

        for account in accounts:
            balance = self.get_account_balance(account.id, end_date)
            if balance != 0:
                # Tillgångar och kostnader har debetsaldo, övriga kreditsaldo
                is_debit_account = account.account_type in [AccountType.ASSET, AccountType.EXPENSE]
                balances.append({
                    "account_number": account.number,
                    "account_name": account.name,
                    "account_type": account.account_type.value,
                    "balance": balance,
                    "debit": balance if is_debit_account else Decimal(0),
                    "credit": balance if not is_debit_account else Decimal(0)
                })

        return balances
