"""
Avskrivningshantering - Beräkning och bokföring av avskrivningar

Stödjer:
- Linjär avskrivning (K2 standard)
- Komponentavskrivning (K3)
- Månads-, kvartals- och årsavskrivningar
"""
from datetime import date
from decimal import Decimal
from typing import Optional, List
from sqlalchemy.orm import Session

from app.models import (
    Asset, AssetDepreciation, AssetType, DepreciationMethod,
    Account, Transaction, TransactionLine, Company
)
from app.services.accounting import AccountingService


class DepreciationService:
    """
    Tjänst för avskrivningsberäkning och bokföring

    K2-regler:
    - Linjär avskrivning
    - Schablonmässiga nyttjandeperioder:
      * Byggnader: 20-50 år
      * Inventarier: 5 år
      * Datorer: 3 år
      * Goodwill: 5 år

    K3-regler:
    - Komponentavskrivning för byggnader
    - Individuell bedömning av nyttjandeperiod
    - Omprövning av restvärde
    """

    # Standardkonton enligt BAS
    DEFAULT_ACCOUNTS = {
        AssetType.TANGIBLE: {
            'asset': '1220',      # Inventarier och verktyg
            'depreciation': '7832',  # Avskrivningar inventarier
            'accumulated': '1229',   # Ack avskr inventarier
        },
        AssetType.INTANGIBLE: {
            'asset': '1010',      # Balanserade utgifter
            'depreciation': '7810',  # Avskrivningar immateriella
            'accumulated': '1019',   # Ack avskr immateriella
        },
        AssetType.FINANCIAL: {
            'asset': '1310',      # Andelar i koncernföretag
            'depreciation': '8170',  # Nedskrivning fin tillg
            'accumulated': None,     # Ingen ack för finansiella
        }
    }

    def __init__(self, db: Session):
        self.db = db
        self.accounting_service = AccountingService(db)

    def create_asset(
        self,
        company_id: int,
        name: str,
        asset_type: AssetType,
        acquisition_date: date,
        acquisition_cost: Decimal,
        useful_life_months: int,
        residual_value: Decimal = Decimal(0),
        depreciation_method: DepreciationMethod = DepreciationMethod.LINEAR,
        description: str = None,
        asset_number: str = None,
        asset_account_number: str = None,
        depreciation_account_number: str = None,
        accumulated_account_number: str = None,
    ) -> Asset:
        """
        Skapa en ny anläggningstillgång

        Om kontonummer inte anges används standardkonton från BAS.
        """
        # Hämta eller använd standardkonton
        defaults = self.DEFAULT_ACCOUNTS.get(asset_type, self.DEFAULT_ACCOUNTS[AssetType.TANGIBLE])

        def get_account(number: str) -> Optional[Account]:
            if not number:
                return None
            return (
                self.db.query(Account)
                .filter(Account.company_id == company_id, Account.number == number)
                .first()
            )

        asset_account = get_account(asset_account_number or defaults['asset'])
        depreciation_account = get_account(depreciation_account_number or defaults['depreciation'])
        accumulated_account = get_account(accumulated_account_number or defaults.get('accumulated'))

        asset = Asset(
            company_id=company_id,
            name=name,
            description=description,
            asset_number=asset_number,
            asset_type=asset_type,
            asset_account_id=asset_account.id if asset_account else None,
            depreciation_account_id=depreciation_account.id if depreciation_account else None,
            accumulated_account_id=accumulated_account.id if accumulated_account else None,
            acquisition_date=acquisition_date,
            acquisition_cost=acquisition_cost,
            residual_value=residual_value,
            useful_life_months=useful_life_months,
            depreciation_method=depreciation_method,
            is_active=True
        )

        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def get_assets(self, company_id: int, active_only: bool = True) -> List[Asset]:
        """Hämta tillgångar för ett företag"""
        query = self.db.query(Asset).filter(Asset.company_id == company_id)
        if active_only:
            query = query.filter(Asset.is_active == True)
        return query.order_by(Asset.acquisition_date.desc()).all()

    def get_asset(self, asset_id: int) -> Optional[Asset]:
        """Hämta en specifik tillgång"""
        return self.db.query(Asset).filter(Asset.id == asset_id).first()

    def calculate_depreciation(
        self,
        asset: Asset,
        period_date: date
    ) -> Decimal:
        """
        Beräkna avskrivningsbelopp för en period

        För linjär avskrivning: (anskaffning - restvärde) / nyttjandeperiod
        """
        if not asset.is_active:
            return Decimal(0)

        # Kontrollera om tillgången är fullt avskriven
        book_value = asset.get_book_value(period_date)
        if book_value <= asset.residual_value:
            return Decimal(0)

        # Månadsavskrivning
        monthly = asset.monthly_depreciation

        # Kontrollera att vi inte avskriver under restvärdet
        max_depreciation = book_value - Decimal(str(asset.residual_value or 0))
        return min(monthly, max_depreciation).quantize(Decimal('0.01'))

    def create_depreciation_entry(
        self,
        asset: Asset,
        fiscal_year_id: int,
        period_date: date,
        amount: Decimal = None,
        period_type: str = "monthly"
    ) -> Optional[Transaction]:
        """
        Skapa avskrivningstransaktion i bokföringen

        Kontering:
        - Debet: Avskrivningskonto (kostnad, t.ex. 7832)
        - Kredit: Ack avskrivningar (tillgång, t.ex. 1229)
        """
        if amount is None:
            amount = self.calculate_depreciation(asset, period_date)

        if amount <= 0:
            return None

        if not asset.depreciation_account_id or not asset.accumulated_account_id:
            raise ValueError(f"Tillgång {asset.name} saknar avskrivningskonton")

        # Skapa transaktion
        description = f"Avskrivning {asset.name} ({period_type})"

        lines = [
            {
                "account_id": asset.depreciation_account_id,
                "debit": amount,
                "credit": Decimal(0)
            },
            {
                "account_id": asset.accumulated_account_id,
                "debit": Decimal(0),
                "credit": amount
            }
        ]

        tx = self.accounting_service.create_transaction(
            company_id=asset.company_id,
            fiscal_year_id=fiscal_year_id,
            transaction_date=period_date,
            description=description,
            lines=lines
        )

        # Spara avskrivningspost
        depreciation = AssetDepreciation(
            asset_id=asset.id,
            transaction_id=tx.id,
            depreciation_date=period_date,
            amount=amount,
            period_type=period_type
        )
        self.db.add(depreciation)
        self.db.commit()

        return tx

    def run_period_depreciation(
        self,
        company_id: int,
        fiscal_year_id: int,
        period_date: date,
        period_type: str = "monthly"
    ) -> List[Transaction]:
        """
        Kör avskrivningar för alla aktiva tillgångar

        Returnerar lista med skapade transaktioner.
        """
        assets = self.get_assets(company_id, active_only=True)
        transactions = []

        for asset in assets:
            # Kontrollera att tillgången var anskaffad före perioddatum
            if asset.acquisition_date > period_date:
                continue

            # Kontrollera om avskrivning redan gjorts för denna period
            existing = (
                self.db.query(AssetDepreciation)
                .filter(
                    AssetDepreciation.asset_id == asset.id,
                    AssetDepreciation.depreciation_date == period_date,
                    AssetDepreciation.period_type == period_type
                )
                .first()
            )
            if existing:
                continue

            try:
                tx = self.create_depreciation_entry(
                    asset=asset,
                    fiscal_year_id=fiscal_year_id,
                    period_date=period_date,
                    period_type=period_type
                )
                if tx:
                    transactions.append(tx)
            except Exception as e:
                # Logga fel men fortsätt med nästa tillgång
                print(f"Fel vid avskrivning av {asset.name}: {e}")

        return transactions

    def dispose_asset(
        self,
        asset: Asset,
        disposal_date: date,
        disposal_amount: Decimal,
        fiscal_year_id: int
    ) -> Transaction:
        """
        Avyttra/skrota en tillgång

        Kontering vid försäljning:
        1. Debet: Bank/Kassa (försäljningspris)
        2. Debet: Ack avskrivningar (nollställ)
        3. Kredit: Tillgångskonto (anskaffningsvärde)
        4. Debet/Kredit: Vinst/förlust avyttring
        """
        book_value = asset.get_book_value(disposal_date)
        accumulated = asset.get_accumulated_depreciation(disposal_date)

        # Beräkna vinst/förlust
        gain_loss = disposal_amount - book_value

        # Uppdatera tillgång
        asset.is_active = False
        asset.disposal_date = disposal_date
        asset.disposal_amount = disposal_amount

        self.db.commit()

        return None  # Implementera full avyttringstransaktion vid behov

    def get_depreciation_schedule(
        self,
        asset: Asset,
        periods: int = 12
    ) -> List[dict]:
        """
        Generera avskrivningsschema för framtida perioder

        Returnerar lista med:
        - period_date: Datum
        - depreciation: Avskrivningsbelopp
        - accumulated: Ackumulerad avskrivning
        - book_value: Bokfört värde
        """
        schedule = []
        current_date = asset.acquisition_date
        accumulated = Decimal(0)

        from dateutil.relativedelta import relativedelta

        for i in range(periods):
            period_date = current_date + relativedelta(months=i)
            depreciation = self.calculate_depreciation(asset, period_date)

            # Simulera ackumulering
            if i > 0:
                accumulated += schedule[-1]['depreciation']

            book_value = Decimal(str(asset.acquisition_cost)) - accumulated - depreciation

            schedule.append({
                'period': i + 1,
                'period_date': period_date,
                'depreciation': depreciation,
                'accumulated': accumulated + depreciation,
                'book_value': max(book_value, Decimal(str(asset.residual_value or 0)))
            })

        return schedule
