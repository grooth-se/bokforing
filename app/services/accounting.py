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

    def delete_company(self, company_id: int) -> bool:
        """
        Ta bort ett företag och all dess data

        Tar bort i ordning:
        1. Transaktionsrader
        2. Transaktioner
        3. Konton
        4. Räkenskapsår
        5. Företaget

        Returns:
            True om företaget togs bort, False om det inte hittades
        """
        company = self.get_company(company_id)
        if not company:
            return False

        # Ta bort transaktionsrader (via transaktioner)
        transactions = self.db.query(Transaction).filter(
            Transaction.company_id == company_id
        ).all()

        for tx in transactions:
            self.db.query(TransactionLine).filter(
                TransactionLine.transaction_id == tx.id
            ).delete()

        # Ta bort transaktioner
        self.db.query(Transaction).filter(
            Transaction.company_id == company_id
        ).delete()

        # Ta bort konton
        self.db.query(Account).filter(
            Account.company_id == company_id
        ).delete()

        # Ta bort räkenskapsår
        self.db.query(FiscalYear).filter(
            FiscalYear.company_id == company_id
        ).delete()

        # Ta bort företaget
        self.db.delete(company)
        self.db.commit()

        return True

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

    def get_transaction(self, transaction_id: int) -> Optional[Transaction]:
        """Hämta en specifik transaktion"""
        return self.db.query(Transaction).filter(Transaction.id == transaction_id).first()

    def delete_transaction_line(self, line_id: int) -> bool:
        """
        Ta bort en konteringsrad från en transaktion

        Returnerar True om raden togs bort, False om den inte hittades.
        OBS: Kontrollerar inte om transaktionen fortfarande balanserar.
        """
        line = self.db.query(TransactionLine).filter(TransactionLine.id == line_id).first()
        if line:
            self.db.delete(line)
            self.db.commit()
            return True
        return False

    def add_transaction_line(
        self,
        transaction_id: int,
        account_id: int,
        debit: Decimal = Decimal(0),
        credit: Decimal = Decimal(0),
        description: str = None
    ) -> Optional[TransactionLine]:
        """
        Lägg till en konteringsrad till en befintlig transaktion

        Returnerar den nya raden, eller None om transaktionen inte hittades.
        """
        transaction = self.get_transaction(transaction_id)
        if not transaction:
            return None

        line = TransactionLine(
            transaction_id=transaction_id,
            account_id=account_id,
            debit=debit,
            credit=credit,
            description=description
        )
        self.db.add(line)
        self.db.commit()
        self.db.refresh(line)
        return line

    def update_transaction_line(
        self,
        line_id: int,
        account_id: int = None,
        debit: Decimal = None,
        credit: Decimal = None,
        description: str = None
    ) -> Optional[TransactionLine]:
        """
        Uppdatera en befintlig konteringsrad
        """
        line = self.db.query(TransactionLine).filter(TransactionLine.id == line_id).first()
        if not line:
            return None

        if account_id is not None:
            line.account_id = account_id
        if debit is not None:
            line.debit = debit
        if credit is not None:
            line.credit = credit
        if description is not None:
            line.description = description

        self.db.commit()
        self.db.refresh(line)
        return line

    def delete_transaction(self, transaction_id: int) -> bool:
        """
        Ta bort en hel transaktion med alla dess rader

        Returnerar True om transaktionen togs bort, False om den inte hittades.
        """
        transaction = self.get_transaction(transaction_id)
        if transaction:
            self.db.delete(transaction)
            self.db.commit()
            return True
        return False

    def update_transaction(
        self,
        transaction_id: int,
        description: str = None,
        transaction_date: date = None
    ) -> Optional[Transaction]:
        """
        Uppdatera transaktionsmetadata (beskrivning, datum)
        """
        transaction = self.get_transaction(transaction_id)
        if not transaction:
            return None

        if description is not None:
            transaction.description = description
        if transaction_date is not None:
            transaction.transaction_date = transaction_date

        self.db.commit()
        self.db.refresh(transaction)
        return transaction

    # === SALDON ===

    def get_account_balance(
        self,
        account_id: int,
        end_date: Optional[date] = None
    ) -> Decimal:
        """
        Beräkna saldo för ett konto

        Enkel formel för alla konton:
        saldo = opening_balance + debit - credit

        SIE-konvention:
        - Positiv opening_balance = debetsaldo (tillgångar, kostnader)
        - Negativ opening_balance = kreditsaldo (skulder, EK, intäkter)

        Resultat:
        - Positivt saldo = debetsaldo
        - Negativt saldo = kreditsaldo

        Summan av alla balansposter (1xxx + 2xxx) ska bli 0.
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

        # Ingående balans direkt från SIE (positiv = debet, negativ = kredit)
        ib = account.opening_balance or Decimal(0)

        # Enkel formel för alla konton:
        # saldo = IB + debet - kredit
        return ib + total_debit - total_credit

    def get_trial_balance(
        self,
        company_id: int,
        end_date: Optional[date] = None
    ) -> list[dict]:
        """
        Generera råbalans (saldon för alla konton)

        Saldot returneras med:
        - balance: signerat värde (positiv = debet, negativ = kredit)
        - debit/credit: absolut värde i rätt kolumn för visning

        Konvention (från SIE):
        - Positivt saldo = debetsaldo (tillgångar, kostnader)
        - Negativt saldo = kreditsaldo (skulder, EK, intäkter)

        Summan av alla balansposter (1xxx + 2xxx) ska bli 0.
        """
        accounts = self.get_accounts(company_id)
        balances = []

        for account in accounts:
            balance = self.get_account_balance(account.id, end_date)
            if balance != 0:
                # Enkel regel: positiv = debet-kolumn, negativ = kredit-kolumn
                if balance >= 0:
                    debit_val = balance
                    credit_val = Decimal(0)
                else:
                    debit_val = Decimal(0)
                    credit_val = abs(balance)

                balances.append({
                    "account_number": account.number,
                    "account_name": account.name,
                    "account_type": account.account_type.value,
                    "balance": balance,  # Signerat värde
                    "debit": debit_val,
                    "credit": credit_val
                })

        return balances
