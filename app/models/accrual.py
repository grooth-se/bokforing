"""
Periodiseringar - Automatiska periodiseringstransaktioner

Hanterar:
- Förutbetalda kostnader
- Upplupna kostnader
- Förutbetalda intäkter
- Upplupna intäkter
"""
from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Numeric, Text, Enum, Boolean
from sqlalchemy.orm import relationship
from app.models.base import Base


class AccrualType(PyEnum):
    """Typ av periodisering"""
    PREPAID_EXPENSE = "Förutbetald kostnad"      # Betalt i förväg, kostnad periodiseras
    ACCRUED_EXPENSE = "Upplupen kostnad"         # Ej betalt, kostnad redovisas
    PREPAID_INCOME = "Förutbetald intäkt"        # Fått betalt i förväg, intäkt periodiseras
    ACCRUED_INCOME = "Upplupen intäkt"           # Ej fått betalt, intäkt redovisas


class AccrualFrequency(PyEnum):
    """Hur ofta periodiseringen ska köras"""
    MONTHLY = "Månadsvis"
    QUARTERLY = "Kvartalsvis"
    ANNUAL = "Årsvis"


class Accrual(Base):
    """
    Periodiseringsdefinition

    Exempel: Försäkringspremie 12 000 kr betald 1 jan, ska periodiseras över 12 månader.
    - total_amount: 12000
    - periods: 12
    - amount_per_period: 1000
    - start_date: 2024-01-01
    - end_date: 2024-12-31
    """
    __tablename__ = "accruals"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    fiscal_year_id = Column(Integer, ForeignKey("fiscal_years.id"), nullable=False)

    # Beskrivning
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    accrual_type = Column(Enum(AccrualType), nullable=False)

    # Belopp
    total_amount = Column(Numeric(15, 2), nullable=False)
    periods = Column(Integer, nullable=False)  # Antal perioder att fördela över
    amount_per_period = Column(Numeric(15, 2), nullable=False)

    # Tidsperiod
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    frequency = Column(Enum(AccrualFrequency), default=AccrualFrequency.MONTHLY)

    # Konton
    # För förutbetald kostnad:
    #   - source_account: 1710 (Förutbetalda kostnader) - där beloppet ligger
    #   - target_account: 5XXX (Kostnadskonto) - dit periodiseringen går
    source_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    target_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)

    # Koppling till ursprungstransaktion (t.ex. betalningen av försäkringen)
    original_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)

    # Status
    is_active = Column(Boolean, default=True)
    auto_generate = Column(Boolean, default=True)  # Ska transaktioner skapas automatiskt?

    # Metadata
    created_at = Column(DateTime, default=datetime.now)
    created_by = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    # Relationer
    company = relationship("Company", backref="accruals")
    fiscal_year = relationship("FiscalYear", backref="accruals")
    source_account = relationship("Account", foreign_keys=[source_account_id])
    target_account = relationship("Account", foreign_keys=[target_account_id])
    original_transaction = relationship("Transaction", foreign_keys=[original_transaction_id])
    entries = relationship("AccrualEntry", back_populates="accrual", cascade="all, delete-orphan")

    @property
    def remaining_amount(self) -> Decimal:
        """Beräkna återstående belopp att periodisera"""
        booked = sum(Decimal(str(e.amount)) for e in self.entries if e.is_booked)
        return Decimal(str(self.total_amount)) - booked

    @property
    def periods_remaining(self) -> int:
        """Antal perioder kvar"""
        booked_periods = len([e for e in self.entries if e.is_booked])
        return self.periods - booked_periods

    def __repr__(self):
        return f"<Accrual(id={self.id}, name='{self.name}', type={self.accrual_type.value})>"


class AccrualEntry(Base):
    """
    Enskild periodiseringspost

    Varje månad/period skapas en entry som kopplas till en transaktion.
    """
    __tablename__ = "accrual_entries"

    id = Column(Integer, primary_key=True, index=True)
    accrual_id = Column(Integer, ForeignKey("accruals.id"), nullable=False)

    # Period
    period_date = Column(Date, nullable=False)
    period_number = Column(Integer, nullable=False)  # 1, 2, 3... upp till periods

    # Belopp
    amount = Column(Numeric(15, 2), nullable=False)

    # Transaktion
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    is_booked = Column(Boolean, default=False)
    booked_at = Column(DateTime, nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.now)

    # Relationer
    accrual = relationship("Accrual", back_populates="entries")
    transaction = relationship("Transaction")

    def __repr__(self):
        status = "Bokförd" if self.is_booked else "Väntande"
        return f"<AccrualEntry(id={self.id}, period={self.period_number}, {status})>"
