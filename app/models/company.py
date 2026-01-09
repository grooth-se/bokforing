"""
Företagsmodell - Multi-tenant stöd
"""
from datetime import date
from sqlalchemy import Column, Integer, String, Date, Enum
from sqlalchemy.orm import relationship
from app.models.base import Base
from app.config import AccountingStandard


class Company(Base):
    """
    Företag/Organisation

    Varje företag har sin egen kontoplan, transaktioner och räkenskapsår.
    Stödjer både K2 och K3 redovisningsstandard.
    """
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    org_number = Column(String(20), unique=True, nullable=False)  # Organisationsnummer

    # Redovisningsstandard (K2 eller K3)
    accounting_standard = Column(
        Enum(AccountingStandard),
        default=AccountingStandard.K2,
        nullable=False
    )

    # Räkenskapsårets startmånad (1-12, oftast 1 för kalenderår)
    fiscal_year_start_month = Column(Integer, default=1, nullable=False)

    # Kontaktuppgifter
    address = Column(String(500))
    email = Column(String(255))
    phone = Column(String(50))

    # Metadata
    created_at = Column(Date, default=date.today)

    # Relationer
    accounts = relationship("Account", back_populates="company", cascade="all, delete-orphan")
    fiscal_years = relationship("FiscalYear", back_populates="company", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Company(id={self.id}, name='{self.name}', org={self.org_number})>"
