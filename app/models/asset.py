"""
Anläggningstillgångar - Inventarier, maskiner, immateriella tillgångar

Hanterar:
- Materiella tillgångar (inventarier, maskiner, byggnader)
- Immateriella tillgångar (patent, goodwill, licenser)
- Finansiella tillgångar (aktier, andelar)
- Avskrivningsberäkning enligt K2/K3
"""
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional
from sqlalchemy import Column, Integer, String, Date, Numeric, ForeignKey, Boolean, Enum as SQLEnum
from sqlalchemy.orm import relationship

from app.models.base import Base


class AssetType(Enum):
    """Typ av anläggningstillgång"""
    TANGIBLE = "Materiell"        # Inventarier, maskiner, byggnader
    INTANGIBLE = "Immateriell"    # Patent, goodwill, licenser
    FINANCIAL = "Finansiell"      # Aktier, andelar


class DepreciationMethod(Enum):
    """Avskrivningsmetod"""
    LINEAR = "Linjär"             # Linjär avskrivning (vanligast)
    DECLINING = "Degressiv"       # Degressiv avskrivning
    COMPONENT = "Komponent"       # Komponentavskrivning (K3)


class Asset(Base):
    """
    Anläggningstillgång

    BAS-konton för tillgångar:
    - 1010-1099: Immateriella tillgångar
    - 1110-1119: Byggnader
    - 1210-1299: Maskiner och inventarier
    - 1310-1399: Finansiella tillgångar

    Ackumulerade avskrivningar:
    - 1019: Ack avskr immateriella
    - 1119: Ack avskr byggnader
    - 1219: Ack avskr inventarier
    """
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Grunduppgifter
    name = Column(String(200), nullable=False)
    description = Column(String(500))
    asset_number = Column(String(50))  # Internt inventarienummer
    asset_type = Column(SQLEnum(AssetType), default=AssetType.TANGIBLE)

    # Koppling till bokföring
    asset_account_id = Column(Integer, ForeignKey("accounts.id"))  # Tillgångskonto (1220)
    depreciation_account_id = Column(Integer, ForeignKey("accounts.id"))  # Avskrivningskostnad (7830)
    accumulated_account_id = Column(Integer, ForeignKey("accounts.id"))  # Ack avskrivningar (1229)

    # Ekonomiska uppgifter
    acquisition_date = Column(Date, nullable=False)
    acquisition_cost = Column(Numeric(15, 2), nullable=False)  # Anskaffningsvärde
    residual_value = Column(Numeric(15, 2), default=0)  # Restvärde
    useful_life_months = Column(Integer, nullable=False)  # Nyttjandeperiod i månader

    # Avskrivningsmetod
    depreciation_method = Column(SQLEnum(DepreciationMethod), default=DepreciationMethod.LINEAR)

    # Status
    is_active = Column(Boolean, default=True)
    disposal_date = Column(Date)
    disposal_amount = Column(Numeric(15, 2))

    # Relationer
    company = relationship("Company", back_populates="assets")
    asset_account = relationship("Account", foreign_keys=[asset_account_id])
    depreciation_account = relationship("Account", foreign_keys=[depreciation_account_id])
    accumulated_account = relationship("Account", foreign_keys=[accumulated_account_id])
    depreciations = relationship("AssetDepreciation", back_populates="asset", cascade="all, delete-orphan")

    @property
    def depreciable_amount(self) -> Decimal:
        """Avskrivningsbart belopp (anskaffning - restvärde)"""
        return Decimal(str(self.acquisition_cost)) - Decimal(str(self.residual_value or 0))

    @property
    def monthly_depreciation(self) -> Decimal:
        """Månadsavskrivning för linjär metod"""
        if self.useful_life_months and self.useful_life_months > 0:
            return self.depreciable_amount / self.useful_life_months
        return Decimal(0)

    @property
    def annual_depreciation(self) -> Decimal:
        """Årlig avskrivning"""
        return self.monthly_depreciation * 12

    @property
    def depreciation_rate(self) -> Decimal:
        """Avskrivningsprocent per år"""
        if self.useful_life_months and self.useful_life_months > 0:
            return Decimal(12) / Decimal(self.useful_life_months) * 100
        return Decimal(0)

    def get_accumulated_depreciation(self, as_of_date: date) -> Decimal:
        """Beräkna ackumulerad avskrivning t.o.m. datum"""
        total = Decimal(0)
        for dep in self.depreciations:
            if dep.depreciation_date <= as_of_date:
                total += dep.amount
        return total

    def get_book_value(self, as_of_date: date) -> Decimal:
        """Beräkna bokfört värde (anskaffning - ack avskrivningar)"""
        return Decimal(str(self.acquisition_cost)) - self.get_accumulated_depreciation(as_of_date)

    def __repr__(self):
        return f"<Asset {self.name} ({self.asset_type.value})>"


class AssetDepreciation(Base):
    """
    Avskrivningspost för en tillgång

    Varje gång avskrivning körs skapas en post här
    som kopplas till en bokföringstransaktion.
    """
    __tablename__ = "asset_depreciations"

    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    transaction_id = Column(Integer, ForeignKey("transactions.id"))

    depreciation_date = Column(Date, nullable=False)
    amount = Column(Numeric(15, 2), nullable=False)
    period_type = Column(String(20))  # "monthly", "quarterly", "annual"

    # Relationer
    asset = relationship("Asset", back_populates="depreciations")
    transaction = relationship("Transaction")

    def __repr__(self):
        return f"<AssetDepreciation {self.depreciation_date}: {self.amount}>"
