"""
Skatterapportering - Moms och arbetsgivaravgifter

Genererar rapporter för:
- Momsdeklaration (SKV 4700)
- Arbetsgivardeklaration (AGI)
"""
from datetime import date
from decimal import Decimal
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Account, Transaction, TransactionLine


class VATReport:
    """
    Genererar momsrapport enligt Skatteverkets format (SKV 4700)

    Momskonton enligt BAS:
    - 2610: Utgående moms 25%
    - 2620: Utgående moms 12%
    - 2630: Utgående moms 6%
    - 2640: Ingående moms
    - 2650: Redovisningskonto för moms

    Momspliktiga intäktskonton:
    - 3xxx: Rörelsens intäkter
    """

    # Momskonton enligt BAS-kontoplanen
    VAT_ACCOUNTS = {
        'output_25': '2610',  # Utgående moms 25%
        'output_12': '2620',  # Utgående moms 12%
        'output_6': '2630',   # Utgående moms 6%
        'input': '2640',      # Ingående moms
        'settlement': '2650', # Redovisningskonto
    }

    def __init__(self, db: Session):
        self.db = db

    def generate(
        self,
        company_id: int,
        period_start: date,
        period_end: date
    ) -> dict:
        """
        Generera momsrapport för period

        Returnerar dict med:
        - sales_excl_vat: Momspliktig försäljning exkl moms (ruta 05)
        - output_vat_25: Utgående moms 25% (ruta 10)
        - output_vat_12: Utgående moms 12% (ruta 11)
        - output_vat_6: Utgående moms 6% (ruta 12)
        - input_vat: Ingående moms (ruta 48)
        - vat_to_pay: Moms att betala/få tillbaka (ruta 49)
        """
        # Hämta summa per momskonto
        def get_account_sum(account_number: str) -> Decimal:
            """Hämta nettosumma (kredit - debet) för ett konto under perioden"""
            result = (
                self.db.query(
                    func.coalesce(func.sum(TransactionLine.credit), 0) -
                    func.coalesce(func.sum(TransactionLine.debit), 0)
                )
                .join(Transaction, TransactionLine.transaction_id == Transaction.id)
                .join(Account, TransactionLine.account_id == Account.id)
                .filter(
                    Transaction.company_id == company_id,
                    Transaction.transaction_date >= period_start,
                    Transaction.transaction_date <= period_end,
                    Account.number == account_number
                )
                .scalar()
            )
            return Decimal(str(result or 0))

        def get_account_sum_debit(account_number: str) -> Decimal:
            """Hämta summa debet för ett konto under perioden"""
            result = (
                self.db.query(
                    func.coalesce(func.sum(TransactionLine.debit), 0)
                )
                .join(Transaction, TransactionLine.transaction_id == Transaction.id)
                .join(Account, TransactionLine.account_id == Account.id)
                .filter(
                    Transaction.company_id == company_id,
                    Transaction.transaction_date >= period_start,
                    Transaction.transaction_date <= period_end,
                    Account.number == account_number
                )
                .scalar()
            )
            return Decimal(str(result or 0))

        # Hämta intäkter (konto 3xxx) för att beräkna momspliktig försäljning
        sales_result = (
            self.db.query(
                func.coalesce(func.sum(TransactionLine.credit), 0) -
                func.coalesce(func.sum(TransactionLine.debit), 0)
            )
            .join(Transaction, TransactionLine.transaction_id == Transaction.id)
            .join(Account, TransactionLine.account_id == Account.id)
            .filter(
                Transaction.company_id == company_id,
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date <= period_end,
                Account.number.like('3%')
            )
            .scalar()
        )
        sales_excl_vat = Decimal(str(sales_result or 0))

        # Hämta momssummor
        output_vat_25 = get_account_sum(self.VAT_ACCOUNTS['output_25'])
        output_vat_12 = get_account_sum(self.VAT_ACCOUNTS['output_12'])
        output_vat_6 = get_account_sum(self.VAT_ACCOUNTS['output_6'])
        input_vat = get_account_sum_debit(self.VAT_ACCOUNTS['input'])

        # Total utgående moms
        total_output_vat = output_vat_25 + output_vat_12 + output_vat_6

        # Moms att betala (positiv) eller få tillbaka (negativ)
        vat_to_pay = total_output_vat - input_vat

        return {
            'period_start': period_start,
            'period_end': period_end,
            # Ruta 05: Momspliktig försäljning
            'sales_excl_vat': sales_excl_vat,
            # Ruta 10-12: Utgående moms per sats
            'output_vat_25': output_vat_25,
            'output_vat_12': output_vat_12,
            'output_vat_6': output_vat_6,
            'total_output_vat': total_output_vat,
            # Ruta 48: Ingående moms
            'input_vat': input_vat,
            # Ruta 49: Att betala/få tillbaka
            'vat_to_pay': vat_to_pay,
        }


class EmployerReport:
    """
    Genererar arbetsgivardeklaration (AGI)

    Relevanta konton enligt BAS:
    - 7010-7090: Löner och ersättningar
    - 7510-7690: Arbetsgivaravgifter (kostnad)
    - 2710: Personalens källskatt (skuld)
    - 2730-2739: Arbetsgivaravgifter (skuld)
    """

    # Lönekonton
    SALARY_ACCOUNTS = ['7010', '7011', '7012', '7013', '7014', '7019',
                       '7020', '7030', '7080', '7082', '7090']

    # Arbetsgivaravgiftskonton (skuld)
    EMPLOYER_TAX_ACCOUNTS = ['2730', '2731', '2732', '2733', '2734', '2735']

    # Källskatt (skuld)
    WITHHOLDING_TAX_ACCOUNT = '2710'

    # Arbetsgivaravgiftssatser 2024
    EMPLOYER_CONTRIBUTION_RATE = Decimal('0.3142')  # 31.42%

    def __init__(self, db: Session):
        self.db = db

    def generate(
        self,
        company_id: int,
        period_start: date,
        period_end: date
    ) -> dict:
        """
        Generera arbetsgivarrapport för period

        Returnerar dict med:
        - gross_salary: Bruttolöner
        - employer_contributions: Arbetsgivaravgifter
        - withholding_tax: Avdragen skatt
        - total_to_pay: Totalt att betala till Skatteverket
        """
        def get_account_pattern_sum(pattern: str, debit: bool = True) -> Decimal:
            """Hämta summa för konton som matchar mönster"""
            if debit:
                col = func.coalesce(func.sum(TransactionLine.debit), 0)
            else:
                col = func.coalesce(func.sum(TransactionLine.credit), 0)

            result = (
                self.db.query(col)
                .join(Transaction, TransactionLine.transaction_id == Transaction.id)
                .join(Account, TransactionLine.account_id == Account.id)
                .filter(
                    Transaction.company_id == company_id,
                    Transaction.transaction_date >= period_start,
                    Transaction.transaction_date <= period_end,
                    Account.number.like(pattern)
                )
                .scalar()
            )
            return Decimal(str(result or 0))

        # Bruttolöner (konto 7xxx kostnad = debet)
        gross_salary = get_account_pattern_sum('70%', debit=True)

        # Semesterersättning etc.
        vacation_pay = get_account_pattern_sum('702%', debit=True)

        # Totala löneunderlag
        total_salary_base = gross_salary

        # Beräknade arbetsgivaravgifter
        calculated_contributions = total_salary_base * self.EMPLOYER_CONTRIBUTION_RATE

        # Bokförda arbetsgivaravgifter (konto 75xx = kostnad)
        booked_contributions = get_account_pattern_sum('75%', debit=True)

        # Skuld källskatt (2710 kredit = skuld)
        withholding_tax_liability = (
            self.db.query(
                func.coalesce(func.sum(TransactionLine.credit), 0) -
                func.coalesce(func.sum(TransactionLine.debit), 0)
            )
            .join(Transaction, TransactionLine.transaction_id == Transaction.id)
            .join(Account, TransactionLine.account_id == Account.id)
            .filter(
                Transaction.company_id == company_id,
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date <= period_end,
                Account.number == self.WITHHOLDING_TAX_ACCOUNT
            )
            .scalar()
        )
        withholding_tax = Decimal(str(withholding_tax_liability or 0))

        # Skuld arbetsgivaravgifter (273x kredit = skuld)
        contributions_liability = (
            self.db.query(
                func.coalesce(func.sum(TransactionLine.credit), 0) -
                func.coalesce(func.sum(TransactionLine.debit), 0)
            )
            .join(Transaction, TransactionLine.transaction_id == Transaction.id)
            .join(Account, TransactionLine.account_id == Account.id)
            .filter(
                Transaction.company_id == company_id,
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date <= period_end,
                Account.number.like('273%')
            )
            .scalar()
        )
        employer_contributions = Decimal(str(contributions_liability or 0))

        # Totalt att betala till Skatteverket
        total_to_pay = withholding_tax + employer_contributions

        return {
            'period_start': period_start,
            'period_end': period_end,
            # Löneuppgifter
            'gross_salary': gross_salary,
            'vacation_pay': vacation_pay,
            'total_salary_base': total_salary_base,
            # Beräknade avgifter
            'calculated_contributions': calculated_contributions.quantize(Decimal('0.01')),
            'contribution_rate': self.EMPLOYER_CONTRIBUTION_RATE,
            # Skulder
            'withholding_tax': withholding_tax,
            'employer_contributions': employer_contributions,
            # Summa
            'total_to_pay': total_to_pay,
        }
