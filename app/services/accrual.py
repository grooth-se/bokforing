"""
Periodiseringstjänst - Skapar och hanterar periodiseringar

Hanterar:
- Skapa periodiseringsdefinitioner
- Generera periodiseringstransaktioner
- Automatisk körning av aktiva periodiseringar
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Dict
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from app.models import Account, Transaction, FiscalYear
from app.models.accrual import Accrual, AccrualEntry, AccrualType, AccrualFrequency
from app.services.accounting import AccountingService


class AccrualService:
    """
    Tjänst för periodiseringar

    Användning:
    1. Skapa periodisering med create_accrual()
    2. Generera transaktioner med generate_entries() eller run_auto_accruals()
    """

    # Standardkonton för olika periodiseringstyper
    DEFAULT_ACCOUNTS = {
        AccrualType.PREPAID_EXPENSE: {
            'source': '1710',  # Förutbetalda kostnader
        },
        AccrualType.ACCRUED_EXPENSE: {
            'source': '2990',  # Övriga upplupna kostnader
        },
        AccrualType.PREPAID_INCOME: {
            'source': '2990',  # Förutbetalda intäkter
        },
        AccrualType.ACCRUED_INCOME: {
            'source': '1790',  # Upplupna intäkter
        },
    }

    def __init__(self, db: Session):
        self.db = db
        self.accounting_service = AccountingService(db)

    def create_accrual(
        self,
        company_id: int,
        fiscal_year_id: int,
        name: str,
        accrual_type: AccrualType,
        total_amount: Decimal,
        periods: int,
        start_date: date,
        source_account_id: int,
        target_account_id: int,
        description: str = None,
        frequency: AccrualFrequency = AccrualFrequency.MONTHLY,
        auto_generate: bool = True,
        original_transaction_id: int = None
    ) -> Accrual:
        """
        Skapa en ny periodisering

        Args:
            company_id: Företags-ID
            fiscal_year_id: Räkenskapsår-ID
            name: Beskrivande namn (t.ex. "Försäkring 2024")
            accrual_type: Typ av periodisering
            total_amount: Totalt belopp att periodisera
            periods: Antal perioder att fördela över
            start_date: Startdatum för periodiseringen
            source_account_id: Källkonto (t.ex. förutbetald kostnad)
            target_account_id: Målkonto (t.ex. kostnadskonto)
            description: Valfri beskrivning
            frequency: Hur ofta (månad/kvartal/år)
            auto_generate: Om transaktioner ska skapas automatiskt
            original_transaction_id: Koppling till ursprungstransaktion
        """
        # Beräkna slutdatum och belopp per period
        if frequency == AccrualFrequency.MONTHLY:
            end_date = start_date + relativedelta(months=periods - 1)
        elif frequency == AccrualFrequency.QUARTERLY:
            end_date = start_date + relativedelta(months=(periods * 3) - 1)
        else:  # ANNUAL
            end_date = start_date + relativedelta(years=periods - 1)

        amount_per_period = (Decimal(str(total_amount)) / periods).quantize(Decimal('0.01'))

        accrual = Accrual(
            company_id=company_id,
            fiscal_year_id=fiscal_year_id,
            name=name,
            description=description,
            accrual_type=accrual_type,
            total_amount=total_amount,
            periods=periods,
            amount_per_period=amount_per_period,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            source_account_id=source_account_id,
            target_account_id=target_account_id,
            original_transaction_id=original_transaction_id,
            is_active=True,
            auto_generate=auto_generate
        )

        self.db.add(accrual)
        self.db.commit()
        self.db.refresh(accrual)

        return accrual

    def get_accruals(
        self,
        company_id: int,
        active_only: bool = True
    ) -> List[Accrual]:
        """Hämta periodiseringar för ett företag"""
        query = self.db.query(Accrual).filter(Accrual.company_id == company_id)
        if active_only:
            query = query.filter(Accrual.is_active == True)
        return query.order_by(Accrual.start_date.desc()).all()

    def get_accrual(self, accrual_id: int) -> Optional[Accrual]:
        """Hämta en specifik periodisering"""
        return self.db.query(Accrual).filter(Accrual.id == accrual_id).first()

    def generate_entry(
        self,
        accrual: Accrual,
        period_date: date,
        period_number: int
    ) -> Optional[AccrualEntry]:
        """
        Generera en periodiseringspost och transaktion

        Returns:
            AccrualEntry om skapad, None om redan finns
        """
        # Kontrollera om entry redan finns
        existing = (
            self.db.query(AccrualEntry)
            .filter(
                AccrualEntry.accrual_id == accrual.id,
                AccrualEntry.period_number == period_number
            )
            .first()
        )
        if existing:
            return None

        # Bestäm belopp (sista perioden får eventuell avrundningsdifferens)
        if period_number == accrual.periods:
            amount = accrual.remaining_amount
        else:
            amount = accrual.amount_per_period

        # Skapa entry
        entry = AccrualEntry(
            accrual_id=accrual.id,
            period_date=period_date,
            period_number=period_number,
            amount=amount,
            is_booked=False
        )
        self.db.add(entry)

        # Skapa transaktion
        tx = self._create_accrual_transaction(accrual, entry)
        if tx:
            entry.transaction_id = tx.id
            entry.is_booked = True
            entry.booked_at = datetime.now()

        self.db.commit()
        return entry

    def _create_accrual_transaction(
        self,
        accrual: Accrual,
        entry: AccrualEntry
    ) -> Optional[Transaction]:
        """
        Skapa bokföringstransaktion för periodisering

        Kontering beror på typ:
        - Förutbetald kostnad: Debet kostnad, Kredit förutbetald
        - Upplupen kostnad: Debet kostnad, Kredit upplupen skuld
        - Förutbetald intäkt: Debet förutbetald, Kredit intäkt
        - Upplupen intäkt: Debet upplupen fordran, Kredit intäkt
        """
        amount = entry.amount

        if accrual.accrual_type == AccrualType.PREPAID_EXPENSE:
            # Flytta från förutbetald (kredit) till kostnad (debet)
            lines = [
                {"account_id": accrual.target_account_id, "debit": amount, "credit": Decimal(0)},
                {"account_id": accrual.source_account_id, "debit": Decimal(0), "credit": amount}
            ]
        elif accrual.accrual_type == AccrualType.ACCRUED_EXPENSE:
            # Kostnad (debet) mot upplupen skuld (kredit)
            lines = [
                {"account_id": accrual.target_account_id, "debit": amount, "credit": Decimal(0)},
                {"account_id": accrual.source_account_id, "debit": Decimal(0), "credit": amount}
            ]
        elif accrual.accrual_type == AccrualType.PREPAID_INCOME:
            # Flytta från förutbetald (debet) till intäkt (kredit)
            lines = [
                {"account_id": accrual.source_account_id, "debit": amount, "credit": Decimal(0)},
                {"account_id": accrual.target_account_id, "debit": Decimal(0), "credit": amount}
            ]
        else:  # ACCRUED_INCOME
            # Upplupen fordran (debet) mot intäkt (kredit)
            lines = [
                {"account_id": accrual.source_account_id, "debit": amount, "credit": Decimal(0)},
                {"account_id": accrual.target_account_id, "debit": Decimal(0), "credit": amount}
            ]

        description = f"Periodisering: {accrual.name} ({entry.period_number}/{accrual.periods})"

        return self.accounting_service.create_transaction(
            company_id=accrual.company_id,
            fiscal_year_id=accrual.fiscal_year_id,
            transaction_date=entry.period_date,
            description=description,
            lines=lines
        )

    def run_auto_accruals(
        self,
        company_id: int,
        up_to_date: date = None
    ) -> List[AccrualEntry]:
        """
        Kör alla automatiska periodiseringar fram till ett datum

        Args:
            company_id: Företags-ID
            up_to_date: Datum att köra fram till (default: idag)

        Returns:
            Lista med skapade entries
        """
        if up_to_date is None:
            up_to_date = date.today()

        accruals = self.get_accruals(company_id, active_only=True)
        created_entries = []

        for accrual in accruals:
            if not accrual.auto_generate:
                continue

            entries = self._generate_pending_entries(accrual, up_to_date)
            created_entries.extend(entries)

        return created_entries

    def _generate_pending_entries(
        self,
        accrual: Accrual,
        up_to_date: date
    ) -> List[AccrualEntry]:
        """Generera alla väntande entries för en periodisering"""
        entries = []

        # Beräkna vilka perioder som ska finnas
        current_date = accrual.start_date
        for period_num in range(1, accrual.periods + 1):
            if current_date > up_to_date:
                break

            # Kontrollera om entry redan finns
            existing = (
                self.db.query(AccrualEntry)
                .filter(
                    AccrualEntry.accrual_id == accrual.id,
                    AccrualEntry.period_number == period_num
                )
                .first()
            )

            if not existing:
                entry = self.generate_entry(accrual, current_date, period_num)
                if entry:
                    entries.append(entry)

            # Nästa period
            if accrual.frequency == AccrualFrequency.MONTHLY:
                current_date = current_date + relativedelta(months=1)
            elif accrual.frequency == AccrualFrequency.QUARTERLY:
                current_date = current_date + relativedelta(months=3)
            else:
                current_date = current_date + relativedelta(years=1)

        # Markera som inaktiv om alla perioder är bokförda
        if accrual.periods_remaining == 0:
            accrual.is_active = False
            self.db.commit()

        return entries

    def deactivate_accrual(self, accrual_id: int) -> bool:
        """Inaktivera en periodisering"""
        accrual = self.get_accrual(accrual_id)
        if accrual:
            accrual.is_active = False
            self.db.commit()
            return True
        return False

    def get_pending_entries(
        self,
        company_id: int,
        up_to_date: date = None
    ) -> List[Dict]:
        """
        Förhandsgranska väntande periodiseringar utan att skapa dem

        Returns:
            Lista med info om väntande periodiseringar
        """
        if up_to_date is None:
            up_to_date = date.today()

        accruals = self.get_accruals(company_id, active_only=True)
        pending = []

        for accrual in accruals:
            current_date = accrual.start_date

            for period_num in range(1, accrual.periods + 1):
                if current_date > up_to_date:
                    break

                # Kontrollera om entry redan finns
                existing = (
                    self.db.query(AccrualEntry)
                    .filter(
                        AccrualEntry.accrual_id == accrual.id,
                        AccrualEntry.period_number == period_num
                    )
                    .first()
                )

                if not existing:
                    pending.append({
                        'accrual_id': accrual.id,
                        'accrual_name': accrual.name,
                        'period_number': period_num,
                        'period_date': current_date,
                        'amount': float(accrual.amount_per_period),
                        'type': accrual.accrual_type.value
                    })

                # Nästa period
                if accrual.frequency == AccrualFrequency.MONTHLY:
                    current_date = current_date + relativedelta(months=1)
                elif accrual.frequency == AccrualFrequency.QUARTERLY:
                    current_date = current_date + relativedelta(months=3)
                else:
                    current_date = current_date + relativedelta(years=1)

        return pending
