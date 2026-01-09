"""
SIE-import - Parser för SIE4-format

SIE (Standard Import Export) är ett svenskt standardformat för
att överföra bokföringsdata mellan olika system.
"""
import re
from datetime import date
from decimal import Decimal
from typing import Optional
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

from app.models import Company, Account, FiscalYear, Transaction, TransactionLine
from app.config import AccountType


@dataclass
class SIEAccount:
    """Konto från SIE-fil"""
    number: str
    name: str


@dataclass
class SIETransaction:
    """Transaktion från SIE-fil"""
    verification_number: int
    date: date
    description: str
    lines: list[dict] = field(default_factory=list)


@dataclass
class SIEData:
    """Parsad SIE-data"""
    company_name: Optional[str] = None
    org_number: Optional[str] = None
    fiscal_year_start: Optional[date] = None
    fiscal_year_end: Optional[date] = None
    accounts: list[SIEAccount] = field(default_factory=list)
    opening_balances: dict = field(default_factory=dict)  # account_number -> balance
    transactions: list[SIETransaction] = field(default_factory=list)


class SIEParser:
    """
    Parser för SIE4-format

    Hanterar:
    - #FNAMN - Företagsnamn
    - #ORGNR - Organisationsnummer
    - #RAR - Räkenskapsår
    - #KONTO - Konton
    - #IB - Ingående balanser
    - #VER - Verifikationer med transaktioner
    """

    def __init__(self):
        self.data = SIEData()

    def parse(self, content: str) -> SIEData:
        """Parsa SIE-filinnehåll"""
        self.data = SIEData()

        # SIE använder CP437 eller Latin-1 kodning
        lines = content.split('\n')

        current_verification = None

        for line in lines:
            line = line.strip()
            if not line or line.startswith('//'):
                continue

            # Identifiera taggar
            if line.startswith('#FNAMN'):
                self._parse_company_name(line)
            elif line.startswith('#ORGNR'):
                self._parse_org_number(line)
            elif line.startswith('#RAR'):
                self._parse_fiscal_year(line)
            elif line.startswith('#KONTO'):
                self._parse_account(line)
            elif line.startswith('#IB'):
                self._parse_opening_balance(line)
            elif line.startswith('#VER'):
                current_verification = self._parse_verification(line)
            elif line.startswith('#TRANS') and current_verification:
                self._parse_transaction_line(line, current_verification)
            elif line.startswith('}'):
                if current_verification and current_verification.lines:
                    self.data.transactions.append(current_verification)
                current_verification = None

        return self.data

    def _parse_company_name(self, line: str):
        """Parsa #FNAMN "Företagsnamn"""
        match = re.search(r'"([^"]+)"', line)
        if match:
            self.data.company_name = match.group(1)

    def _parse_org_number(self, line: str):
        """Parsa #ORGNR orgnummer"""
        parts = line.split()
        if len(parts) >= 2:
            self.data.org_number = parts[1].replace('"', '')

    def _parse_fiscal_year(self, line: str):
        """Parsa #RAR 0 20240101 20241231"""
        parts = line.split()
        if len(parts) >= 4:
            try:
                start_str = parts[2]
                end_str = parts[3]
                self.data.fiscal_year_start = date(
                    int(start_str[:4]), int(start_str[4:6]), int(start_str[6:8])
                )
                self.data.fiscal_year_end = date(
                    int(end_str[:4]), int(end_str[4:6]), int(end_str[6:8])
                )
            except (ValueError, IndexError):
                pass

    def _parse_account(self, line: str):
        """Parsa #KONTO 1930 "Företagskonto\""""
        parts = line.split('"')
        if len(parts) >= 2:
            number_part = parts[0].replace('#KONTO', '').strip()
            name = parts[1]
            self.data.accounts.append(SIEAccount(number=number_part, name=name))

    def _parse_opening_balance(self, line: str):
        """Parsa #IB 0 1930 50000.00"""
        parts = line.split()
        if len(parts) >= 4:
            try:
                account_number = parts[2]
                balance = Decimal(parts[3].replace(',', '.'))
                self.data.opening_balances[account_number] = balance
            except (ValueError, IndexError):
                pass

    def _parse_verification(self, line: str) -> SIETransaction:
        """Parsa #VER A 1 20240115 "Beskrivning\""""
        parts = line.split('"')

        # Extrahera verifikationsnummer och datum
        number_parts = parts[0].replace('#VER', '').strip().split()

        ver_number = 1
        ver_date = date.today()

        if len(number_parts) >= 3:
            try:
                ver_number = int(number_parts[1])
                date_str = number_parts[2]
                ver_date = date(
                    int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8])
                )
            except (ValueError, IndexError):
                pass

        description = parts[1] if len(parts) >= 2 else "Importerad"

        return SIETransaction(
            verification_number=ver_number,
            date=ver_date,
            description=description
        )

    def _parse_transaction_line(self, line: str, verification: SIETransaction):
        """Parsa #TRANS 1930 {} 1000.00"""
        parts = line.replace('#TRANS', '').strip().split()

        if len(parts) >= 3:
            try:
                account_number = parts[0]
                # Hoppa över {} dimensioner
                amount_str = parts[-1].replace(',', '.')
                amount = Decimal(amount_str)

                if amount >= 0:
                    verification.lines.append({
                        'account_number': account_number,
                        'debit': amount,
                        'credit': Decimal(0)
                    })
                else:
                    verification.lines.append({
                        'account_number': account_number,
                        'debit': Decimal(0),
                        'credit': abs(amount)
                    })
            except (ValueError, IndexError):
                pass


class SIEImporter:
    """
    Importerar SIE-data till databasen
    """

    def __init__(self, db: Session):
        self.db = db
        self.parser = SIEParser()

    def import_file(self, content: str, company_id: Optional[int] = None) -> dict:
        """
        Importera SIE-fil

        Args:
            content: SIE-filinnehåll
            company_id: Befintligt företags-ID (om None skapas nytt)

        Returns:
            dict med importstatistik
        """
        data = self.parser.parse(content)

        stats = {
            'company_created': False,
            'accounts_imported': 0,
            'transactions_imported': 0,
            'errors': []
        }

        # Skapa eller hämta företag
        if company_id:
            company = self.db.query(Company).filter(Company.id == company_id).first()
        else:
            company = self._create_company(data)
            stats['company_created'] = True

        if not company:
            stats['errors'].append("Kunde inte skapa/hämta företag")
            return stats

        # Importera konton
        if data.accounts:
            stats['accounts_imported'] = self._import_accounts(company.id, data.accounts)

        # Skapa räkenskapsår
        fiscal_year = self._get_or_create_fiscal_year(company.id, data)

        if fiscal_year:
            # Importera ingående balanser
            self._import_opening_balances(company.id, data.opening_balances)

            # Importera transaktioner
            stats['transactions_imported'] = self._import_transactions(
                company.id, fiscal_year.id, data.transactions
            )

        return stats

    def _create_company(self, data: SIEData) -> Optional[Company]:
        """Skapa företag från SIE-data"""
        name = data.company_name or "Importerat företag"
        org_number = data.org_number or "000000-0000"

        company = Company(
            name=name,
            org_number=org_number
        )
        self.db.add(company)
        self.db.commit()
        self.db.refresh(company)
        return company

    def _import_accounts(self, company_id: int, accounts: list[SIEAccount]) -> int:
        """Importera konton"""
        count = 0
        for acc in accounts:
            # Kontrollera om kontot redan finns
            existing = self.db.query(Account).filter(
                Account.company_id == company_id,
                Account.number == acc.number
            ).first()

            if not existing:
                # Bestäm kontotyp baserat på kontonummer
                account_type = self._determine_account_type(acc.number)

                account = Account(
                    company_id=company_id,
                    number=acc.number,
                    name=acc.name,
                    account_type=account_type
                )
                self.db.add(account)
                count += 1

        self.db.commit()
        return count

    def _determine_account_type(self, number: str) -> AccountType:
        """Bestäm kontotyp baserat på BAS-kontonummer"""
        if not number:
            return AccountType.ASSET

        first_digit = number[0]
        if first_digit == '1':
            return AccountType.ASSET
        elif first_digit == '2':
            # 20xx är eget kapital, resten skulder
            if number.startswith('20') or number.startswith('21'):
                return AccountType.EQUITY
            return AccountType.LIABILITY
        elif first_digit == '3':
            return AccountType.REVENUE
        else:
            return AccountType.EXPENSE

    def _get_or_create_fiscal_year(self, company_id: int, data: SIEData) -> Optional[FiscalYear]:
        """Hämta eller skapa räkenskapsår"""
        if not data.fiscal_year_start or not data.fiscal_year_end:
            # Använd standardår
            today = date.today()
            start = date(today.year, 1, 1)
            end = date(today.year, 12, 31)
        else:
            start = data.fiscal_year_start
            end = data.fiscal_year_end

        # Kontrollera om det finns
        existing = self.db.query(FiscalYear).filter(
            FiscalYear.company_id == company_id,
            FiscalYear.start_date == start,
            FiscalYear.end_date == end
        ).first()

        if existing:
            return existing

        fiscal_year = FiscalYear(
            company_id=company_id,
            start_date=start,
            end_date=end
        )
        self.db.add(fiscal_year)
        self.db.commit()
        self.db.refresh(fiscal_year)
        return fiscal_year

    def _import_opening_balances(self, company_id: int, balances: dict):
        """Importera ingående balanser"""
        for account_number, balance in balances.items():
            account = self.db.query(Account).filter(
                Account.company_id == company_id,
                Account.number == account_number
            ).first()

            if account:
                account.opening_balance = balance

        self.db.commit()

    def _import_transactions(
        self,
        company_id: int,
        fiscal_year_id: int,
        transactions: list[SIETransaction]
    ) -> int:
        """Importera transaktioner"""
        count = 0

        for tx_data in transactions:
            try:
                # Skapa transaktion
                transaction = Transaction(
                    company_id=company_id,
                    fiscal_year_id=fiscal_year_id,
                    verification_number=tx_data.verification_number,
                    transaction_date=tx_data.date,
                    description=tx_data.description
                )
                self.db.add(transaction)
                self.db.flush()

                # Skapa transaktionsrader
                for line_data in tx_data.lines:
                    account = self.db.query(Account).filter(
                        Account.company_id == company_id,
                        Account.number == line_data['account_number']
                    ).first()

                    if account:
                        line = TransactionLine(
                            transaction_id=transaction.id,
                            account_id=account.id,
                            debit=line_data['debit'],
                            credit=line_data['credit']
                        )
                        self.db.add(line)

                count += 1

            except Exception:
                # Hoppa över felaktiga transaktioner
                continue

        self.db.commit()
        return count
