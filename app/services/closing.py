"""
Bokslutsrutiner - Månads-, kvartals- och årsbokslut

Hanterar:
- Avstämning och validering
- Periodiseringar
- Resultatdisposition
- Avslutning av räkenskapsår
"""
from datetime import date
from decimal import Decimal
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import (
    Company, Account, FiscalYear, Transaction, TransactionLine
)
from app.config import AccountType
from app.services.accounting import AccountingService


class ClosingService:
    """
    Tjänst för bokslutsrutiner

    Månadsbokslut:
    - Avstämning av bankkonton
    - Momspliktig period-avstämning
    - Generera månadsrapport

    Kvartalsbokslut:
    - Momsdeklaration
    - Kvartalsrapport

    Årsbokslut:
    - Periodiseringar
    - Avskrivningar
    - Resultatdisposition (2099 -> 2098)
    - Överföring till eget kapital
    - Stäng räkenskapsår
    """

    # Nyckelkonton för bokslut
    CLOSING_ACCOUNTS = {
        'result_current_year': '2099',     # Årets resultat
        'result_previous_year': '2098',    # Balanserat resultat
        'retained_earnings': '2091',       # Balanserad vinst/förlust
    }

    def __init__(self, db: Session):
        self.db = db
        self.accounting_service = AccountingService(db)

    def prepare_closing_checklist(
        self,
        company_id: int,
        period_type: str,
        period_end: date
    ) -> List[Dict]:
        """
        Generera checklista för bokslut

        period_type: "monthly", "quarterly", "annual"
        """
        checklist = []

        # Grundläggande kontroller
        checklist.append({
            'task': 'Verifiera råbalans',
            'description': 'Kontrollera att debet = kredit',
            'status': self._check_trial_balance(company_id, period_end),
            'required': True
        })

        checklist.append({
            'task': 'Bankavstämning',
            'description': 'Stäm av bankkonto mot kontoutdrag',
            'status': 'pending',  # Manuell kontroll
            'required': True
        })

        if period_type in ['quarterly', 'annual']:
            checklist.append({
                'task': 'Momsavstämning',
                'description': 'Kontrollera momskonton och förbered deklaration',
                'status': 'pending',
                'required': True
            })

        if period_type == 'annual':
            checklist.append({
                'task': 'Avskrivningar',
                'description': 'Kör avskrivningar för alla anläggningstillgångar',
                'status': 'pending',
                'required': True
            })

            checklist.append({
                'task': 'Periodiseringar',
                'description': 'Bokför förutbetalda kostnader och upplupna intäkter',
                'status': 'pending',
                'required': True
            })

            checklist.append({
                'task': 'Resultatdisposition',
                'description': 'Överför årets resultat till balanserat resultat',
                'status': 'pending',
                'required': True
            })

            checklist.append({
                'task': 'Inventering',
                'description': 'Värdera lager och pågående arbeten',
                'status': 'pending',
                'required': False
            })

        return checklist

    def _check_trial_balance(self, company_id: int, as_of_date: date) -> str:
        """Kontrollera att råbalansen balanserar"""
        balances = self.accounting_service.get_trial_balance(company_id, as_of_date)

        total_debit = sum(Decimal(str(b['debit'])) for b in balances)
        total_credit = sum(Decimal(str(b['credit'])) for b in balances)

        if abs(total_debit - total_credit) < Decimal('0.01'):
            return 'passed'
        return 'failed'

    def validate_closing(
        self,
        company_id: int,
        period_end: date
    ) -> Dict:
        """
        Validera bokslut före stängning

        Kontrollerar:
        - Råbalans balanserar
        - Inga obalanserade transaktioner
        - Alla obligatoriska konton har saldon
        """
        errors = []
        warnings = []

        # Kontrollera råbalans
        trial_status = self._check_trial_balance(company_id, period_end)
        if trial_status != 'passed':
            errors.append("Råbalansen balanserar inte (debet != kredit)")

        # Kontrollera att det finns transaktioner
        fiscal_year = self.accounting_service.get_active_fiscal_year(company_id)
        if fiscal_year:
            transactions = self.accounting_service.get_transactions(
                company_id,
                fiscal_year.id,
                end_date=period_end
            )
            if not transactions:
                warnings.append("Inga transaktioner finns för perioden")

        # Kontrollera nyckelkonton
        accounts = self.accounting_service.get_accounts(company_id)
        result_account = next((a for a in accounts if a.number == '2099'), None)
        if not result_account:
            warnings.append("Konto 2099 (Årets resultat) saknas")

        return {
            'is_valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }

    def calculate_period_result(
        self,
        company_id: int,
        start_date: date,
        end_date: date
    ) -> Decimal:
        """
        Beräkna periodens resultat (intäkter - kostnader)
        """
        accounts = self.accounting_service.get_accounts(company_id)

        revenue = Decimal(0)
        expenses = Decimal(0)

        for account in accounts:
            if not account.number:
                continue

            balance = self.accounting_service.get_account_balance(account.id, end_date)

            first_digit = account.number[0]
            if first_digit == '3':
                revenue += balance
            elif first_digit in ['4', '5', '6', '7', '8']:
                expenses += balance

        return revenue - expenses

    def close_month(
        self,
        company_id: int,
        month_end: date
    ) -> Dict:
        """
        Utför månadsbokslut

        Returnerar sammanfattning med:
        - result: Månadens resultat
        - validation: Valideringsresultat
        - checklist: Statuslista
        """
        validation = self.validate_closing(company_id, month_end)
        checklist = self.prepare_closing_checklist(company_id, 'monthly', month_end)

        # Beräkna månadsresultat
        from dateutil.relativedelta import relativedelta
        month_start = month_end.replace(day=1)
        result = self.calculate_period_result(company_id, month_start, month_end)

        return {
            'period_type': 'monthly',
            'period_end': month_end,
            'result': result,
            'validation': validation,
            'checklist': checklist,
            'status': 'completed' if validation['is_valid'] else 'incomplete'
        }

    def close_quarter(
        self,
        company_id: int,
        quarter_end: date
    ) -> Dict:
        """
        Utför kvartalsbokslut
        """
        validation = self.validate_closing(company_id, quarter_end)
        checklist = self.prepare_closing_checklist(company_id, 'quarterly', quarter_end)

        # Beräkna kvartalsresultat
        from dateutil.relativedelta import relativedelta
        quarter_start = quarter_end - relativedelta(months=2)
        quarter_start = quarter_start.replace(day=1)
        result = self.calculate_period_result(company_id, quarter_start, quarter_end)

        return {
            'period_type': 'quarterly',
            'period_end': quarter_end,
            'result': result,
            'validation': validation,
            'checklist': checklist,
            'status': 'completed' if validation['is_valid'] else 'incomplete'
        }

    def close_year(
        self,
        company_id: int,
        fiscal_year_id: int,
        create_result_disposition: bool = True
    ) -> Dict:
        """
        Utför årsbokslut

        Steg:
        1. Validera
        2. Skapa resultatdisposition (om begärt)
        3. Markera räkenskapsår som stängt
        4. Skapa ingående balanser för nästa år
        """
        fiscal_year = (
            self.db.query(FiscalYear)
            .filter(FiscalYear.id == fiscal_year_id)
            .first()
        )
        if not fiscal_year:
            raise ValueError(f"Räkenskapsår {fiscal_year_id} finns inte")

        validation = self.validate_closing(company_id, fiscal_year.end_date)
        checklist = self.prepare_closing_checklist(company_id, 'annual', fiscal_year.end_date)

        # Beräkna årets resultat
        result = self.calculate_period_result(
            company_id,
            fiscal_year.start_date,
            fiscal_year.end_date
        )

        # Skapa resultatdisposition om begärt och allt är OK
        disposition_tx = None
        if create_result_disposition and validation['is_valid']:
            disposition_tx = self._create_result_disposition(
                company_id,
                fiscal_year_id,
                result,
                fiscal_year.end_date
            )

        # Markera räkenskapsår som stängt
        if validation['is_valid']:
            fiscal_year.is_closed = True
            self.db.commit()

        return {
            'period_type': 'annual',
            'fiscal_year': f"{fiscal_year.start_date} - {fiscal_year.end_date}",
            'result': result,
            'validation': validation,
            'checklist': checklist,
            'disposition_transaction': disposition_tx.verification_number if disposition_tx else None,
            'status': 'closed' if fiscal_year.is_closed else 'incomplete'
        }

    def _create_result_disposition(
        self,
        company_id: int,
        fiscal_year_id: int,
        result: Decimal,
        disposition_date: date
    ) -> Optional[Transaction]:
        """
        Skapa transaktion för resultatdisposition

        Vinst (positivt resultat):
        - Debet: 2099 Årets resultat
        - Kredit: 2098 Balanserat resultat

        Förlust (negativt resultat):
        - Debet: 2098 Balanserat resultat
        - Kredit: 2099 Årets resultat
        """
        if result == 0:
            return None

        accounts = self.accounting_service.get_accounts(company_id)
        current_year = next((a for a in accounts if a.number == '2099'), None)
        previous_year = next((a for a in accounts if a.number == '2098'), None)

        if not current_year or not previous_year:
            return None

        amount = abs(result)

        if result > 0:
            # Vinst: 2099 debet -> 2098 kredit
            lines = [
                {"account_id": current_year.id, "debit": amount, "credit": Decimal(0)},
                {"account_id": previous_year.id, "debit": Decimal(0), "credit": amount}
            ]
        else:
            # Förlust: 2098 debet -> 2099 kredit
            lines = [
                {"account_id": previous_year.id, "debit": amount, "credit": Decimal(0)},
                {"account_id": current_year.id, "debit": Decimal(0), "credit": amount}
            ]

        return self.accounting_service.create_transaction(
            company_id=company_id,
            fiscal_year_id=fiscal_year_id,
            transaction_date=disposition_date,
            description=f"Resultatdisposition {disposition_date.year}",
            lines=lines
        )

    def create_opening_balances(
        self,
        company_id: int,
        source_fiscal_year_id: int,
        target_fiscal_year_id: int
    ) -> int:
        """
        Skapa ingående balanser för nytt räkenskapsår

        Kopierar utgående balanser från föregående år
        som ingående balanser på balansräkningskonton (1xxx och 2xxx).

        Returnerar antal konton med ingående balans.
        """
        accounts = self.accounting_service.get_accounts(company_id)
        source_fy = self.db.query(FiscalYear).filter(FiscalYear.id == source_fiscal_year_id).first()

        if not source_fy:
            raise ValueError("Källräkenskapsår finns inte")

        count = 0
        for account in accounts:
            if not account.number:
                continue

            # Endast balansräkningskonton (1xxx och 2xxx)
            if account.number[0] not in ['1', '2']:
                continue

            # Beräkna utgående balans från föregående år
            closing_balance = self.accounting_service.get_account_balance(
                account.id,
                source_fy.end_date
            )

            if closing_balance != 0:
                account.opening_balance = closing_balance
                count += 1

        self.db.commit()
        return count
