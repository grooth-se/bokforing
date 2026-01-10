"""
Skattedeklarationstjänst - Genererar underlag för inkomstdeklaration

Stödjer:
- INK2 (Aktiebolag)
- INK4 (Enskild firma) - framtida
- Sparar data för återanvändning nästa år
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Dict, List
from sqlalchemy.orm import Session

from app.models import Company, Account, FiscalYear, Transaction, TransactionLine
from app.models.tax_declaration import TaxDeclaration
from app.services.accounting import AccountingService


class TaxDeclarationService:
    """
    Tjänst för skattedeklarationer

    INK2-blanketten innehåller:
    - Resultaträkning (R1-R12)
    - Balansräkning (B1-B8)
    - Skattemässiga justeringar
    - Beräkning av skatt
    """

    # Bolagsskatt 2024
    CORPORATE_TAX_RATE = Decimal('0.206')  # 20.6%

    # Kontogrupper för INK2
    ACCOUNT_GROUPS = {
        # Resultaträkning
        'revenue': ['30', '31', '32', '33', '34', '35', '36', '37', '38', '39'],  # Intäkter
        'goods_cost': ['40', '41', '42', '43', '44', '45', '46', '47', '48', '49'],  # Varuinköp
        'other_external': ['50', '51', '52', '53', '54', '55', '56', '57', '58', '59', '60', '61', '62', '63', '64', '65', '66', '67', '68', '69'],  # Övriga externa kostnader
        'personnel': ['70', '71', '72', '73', '74', '75', '76'],  # Personalkostnader
        'depreciation': ['78'],  # Avskrivningar
        'other_operating': ['77', '79'],  # Övriga rörelsekostnader
        'financial_income': ['80', '81', '82', '83'],  # Finansiella intäkter
        'financial_expense': ['84'],  # Finansiella kostnader
        'extraordinary': ['85', '86', '87', '88'],  # Extraordinära poster
        'tax': ['89'],  # Skatt

        # Balansräkning - Tillgångar
        'intangible_assets': ['10'],  # Immateriella tillgångar
        'tangible_assets': ['11', '12'],  # Materiella tillgångar
        'financial_assets': ['13'],  # Finansiella tillgångar
        'inventory': ['14'],  # Varulager
        'receivables': ['15', '16', '17'],  # Fordringar
        'cash': ['19'],  # Kassa och bank

        # Balansräkning - Eget kapital och skulder
        'equity': ['20'],  # Eget kapital
        'provisions': ['22', '23'],  # Avsättningar
        'long_term_debt': ['24'],  # Långfristiga skulder
        'short_term_debt': ['25', '26', '27', '28', '29'],  # Kortfristiga skulder
    }

    def __init__(self, db: Session):
        self.db = db
        self.accounting_service = AccountingService(db)

    def get_account_group_balance(
        self,
        company_id: int,
        as_of_date: date,
        account_prefixes: List[str]
    ) -> Decimal:
        """Beräkna summa för en kontogrupp"""
        accounts = self.accounting_service.get_accounts(company_id)
        total = Decimal(0)

        for account in accounts:
            if not account.number:
                continue

            # Kolla om kontot börjar med någon av prefix
            for prefix in account_prefixes:
                if account.number.startswith(prefix):
                    balance = self.accounting_service.get_account_balance(
                        account.id,
                        as_of_date
                    )
                    total += balance
                    break

        return total

    def generate_ink2(
        self,
        company_id: int,
        fiscal_year_id: int
    ) -> Dict:
        """
        Generera INK2-underlag för aktiebolag

        Returnerar strukturerad data med alla fält.
        """
        fiscal_year = (
            self.db.query(FiscalYear)
            .filter(FiscalYear.id == fiscal_year_id)
            .first()
        )
        if not fiscal_year:
            raise ValueError(f"Räkenskapsår {fiscal_year_id} finns inte")

        company = self.db.query(Company).filter(Company.id == company_id).first()
        if not company:
            raise ValueError(f"Företag {company_id} finns inte")

        end_date = fiscal_year.end_date

        # Resultaträkning
        revenue = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['revenue'])
        goods_cost = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['goods_cost'])
        other_external = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['other_external'])
        personnel = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['personnel'])
        depreciation = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['depreciation'])
        other_operating = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['other_operating'])
        financial_income = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['financial_income'])
        financial_expense = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['financial_expense'])

        # Bruttovinst
        gross_profit = revenue - goods_cost

        # Rörelseresultat
        operating_result = (
            gross_profit
            - other_external
            - personnel
            - depreciation
            - other_operating
        )

        # Resultat före skatt
        result_before_tax = operating_result + financial_income - financial_expense

        # Balansräkning - Tillgångar
        intangible = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['intangible_assets'])
        tangible = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['tangible_assets'])
        financial = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['financial_assets'])
        inventory = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['inventory'])
        receivables = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['receivables'])
        cash = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['cash'])

        fixed_assets = intangible + tangible + financial
        current_assets = inventory + receivables + cash
        total_assets = fixed_assets + current_assets

        # Balansräkning - Skulder och eget kapital
        equity = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['equity'])
        provisions = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['provisions'])
        long_term = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['long_term_debt'])
        short_term = self.get_account_group_balance(company_id, end_date, self.ACCOUNT_GROUPS['short_term_debt'])

        total_liabilities = equity + provisions + long_term + short_term

        # Skatteberäkning (förenklad)
        taxable_income = result_before_tax  # Kan justeras med skattemässiga justeringar
        calculated_tax = max(Decimal(0), taxable_income * self.CORPORATE_TAX_RATE)

        return {
            'company': {
                'name': company.name,
                'org_number': company.org_number,
            },
            'fiscal_year': {
                'start_date': str(fiscal_year.start_date),
                'end_date': str(fiscal_year.end_date),
            },
            'income_statement': {
                'R1_revenue': float(revenue),
                'R2_goods_cost': float(goods_cost),
                'R3_gross_profit': float(gross_profit),
                'R4_other_external': float(other_external),
                'R5_personnel': float(personnel),
                'R6_depreciation': float(depreciation),
                'R7_other_operating': float(other_operating),
                'R8_operating_result': float(operating_result),
                'R9_financial_income': float(financial_income),
                'R10_financial_expense': float(financial_expense),
                'R11_result_before_tax': float(result_before_tax),
            },
            'balance_sheet': {
                'assets': {
                    'B1_intangible': float(intangible),
                    'B2_tangible': float(tangible),
                    'B3_financial': float(financial),
                    'B4_fixed_assets': float(fixed_assets),
                    'B5_inventory': float(inventory),
                    'B6_receivables': float(receivables),
                    'B7_cash': float(cash),
                    'B8_current_assets': float(current_assets),
                    'B9_total_assets': float(total_assets),
                },
                'liabilities': {
                    'B10_equity': float(equity),
                    'B11_provisions': float(provisions),
                    'B12_long_term_debt': float(long_term),
                    'B13_short_term_debt': float(short_term),
                    'B14_total_liabilities': float(total_liabilities),
                }
            },
            'tax_calculation': {
                'taxable_income': float(taxable_income),
                'tax_rate': float(self.CORPORATE_TAX_RATE),
                'calculated_tax': float(calculated_tax),
            },
            'generated_at': datetime.now().isoformat(),
        }

    def save_declaration(
        self,
        company_id: int,
        fiscal_year_id: int,
        declaration_type: str,
        data: Dict,
        notes: str = None
    ) -> TaxDeclaration:
        """Spara skattedeklarationsunderlag"""
        # Kontrollera om det redan finns en
        existing = (
            self.db.query(TaxDeclaration)
            .filter(
                TaxDeclaration.company_id == company_id,
                TaxDeclaration.fiscal_year_id == fiscal_year_id,
                TaxDeclaration.declaration_type == declaration_type
            )
            .first()
        )

        if existing:
            # Uppdatera befintlig
            existing.data = data
            existing.notes = notes
            existing.updated_at = datetime.now()
            self.db.commit()
            return existing

        # Skapa ny
        declaration = TaxDeclaration(
            company_id=company_id,
            fiscal_year_id=fiscal_year_id,
            declaration_type=declaration_type,
            data=data,
            notes=notes,
            status="draft"
        )
        self.db.add(declaration)
        self.db.commit()
        self.db.refresh(declaration)
        return declaration

    def get_declaration(
        self,
        company_id: int,
        fiscal_year_id: int,
        declaration_type: str = "INK2"
    ) -> Optional[TaxDeclaration]:
        """Hämta sparad deklaration"""
        return (
            self.db.query(TaxDeclaration)
            .filter(
                TaxDeclaration.company_id == company_id,
                TaxDeclaration.fiscal_year_id == fiscal_year_id,
                TaxDeclaration.declaration_type == declaration_type
            )
            .first()
        )

    def get_previous_year_data(
        self,
        company_id: int,
        fiscal_year_id: int
    ) -> Optional[Dict]:
        """
        Hämta föregående års deklarationsdata

        Används som ingångsvärden för aktuellt år.
        """
        current_fy = (
            self.db.query(FiscalYear)
            .filter(FiscalYear.id == fiscal_year_id)
            .first()
        )
        if not current_fy:
            return None

        # Hitta föregående räkenskapsår
        previous_fy = (
            self.db.query(FiscalYear)
            .filter(
                FiscalYear.company_id == company_id,
                FiscalYear.end_date < current_fy.start_date
            )
            .order_by(FiscalYear.end_date.desc())
            .first()
        )

        if not previous_fy:
            return None

        previous_declaration = self.get_declaration(
            company_id,
            previous_fy.id,
            "INK2"
        )

        if previous_declaration:
            return previous_declaration.data

        return None

    def mark_as_submitted(
        self,
        declaration_id: int
    ) -> TaxDeclaration:
        """Markera deklaration som inskickad"""
        declaration = (
            self.db.query(TaxDeclaration)
            .filter(TaxDeclaration.id == declaration_id)
            .first()
        )
        if declaration:
            declaration.status = "submitted"
            declaration.submitted_at = datetime.now()
            self.db.commit()
        return declaration

    def get_all_declarations(
        self,
        company_id: int
    ) -> List[TaxDeclaration]:
        """Hämta alla deklarationer för ett företag"""
        return (
            self.db.query(TaxDeclaration)
            .filter(TaxDeclaration.company_id == company_id)
            .order_by(TaxDeclaration.created_at.desc())
            .all()
        )
