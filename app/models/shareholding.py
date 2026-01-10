"""
Aktieinnehav - Hantering av aktier i onoterade bolag
"""
from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Numeric, Text, Enum, Boolean
from sqlalchemy.orm import relationship
from app.models.base import Base


class ShareholdingType(PyEnum):
    """Typ av innehav"""
    SUBSIDIARY = "Dotterbolag"  # >50% röster
    ASSOCIATED = "Intresseföretag"  # 20-50% röster
    PARTICIPATION = "Ägarintresse"  # <20%
    OTHER = "Övriga aktier"


class Shareholding(Base):
    """
    Aktieinnehav i onoterade bolag

    Används för att spåra företagets innehav i andra bolag,
    inklusive anskaffningsvärde, marknadsvärde och eventuella
    nedskrivningar.
    """
    __tablename__ = "shareholdings"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Målbolagets uppgifter
    target_company_name = Column(String(255), nullable=False)
    target_org_number = Column(String(20), nullable=True)
    target_country = Column(String(100), default="Sverige")

    # Typ av innehav
    holding_type = Column(Enum(ShareholdingType), nullable=False)

    # Aktieinnehav
    num_shares = Column(Integer, nullable=False)
    total_shares_in_target = Column(Integer, nullable=True)  # Totalt antal aktier i bolaget
    ownership_percentage = Column(Numeric(5, 2), nullable=True)  # Ägarandel i %
    voting_percentage = Column(Numeric(5, 2), nullable=True)  # Röstandel i %

    # Värdering
    acquisition_date = Column(Date, nullable=False)
    acquisition_cost = Column(Numeric(15, 2), nullable=False)  # Anskaffningsvärde
    acquisition_cost_per_share = Column(Numeric(15, 2), nullable=True)

    # Bokfört värde (kan skilja från anskaffning vid nedskrivning)
    book_value = Column(Numeric(15, 2), nullable=False)
    last_valuation_date = Column(Date, nullable=True)
    market_value = Column(Numeric(15, 2), nullable=True)  # Om känt

    # Nedskrivningar
    total_impairment = Column(Numeric(15, 2), default=0)  # Ackumulerade nedskrivningar

    # Koppling till konto i bokföringen
    asset_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)

    # Status
    is_active = Column(Boolean, default=True)
    disposal_date = Column(Date, nullable=True)
    disposal_amount = Column(Numeric(15, 2), nullable=True)
    disposal_gain_loss = Column(Numeric(15, 2), nullable=True)

    # Utdelningar
    total_dividends_received = Column(Numeric(15, 2), default=0)

    # Anteckningar
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationer
    company = relationship("Company", back_populates="shareholdings")
    asset_account = relationship("Account", foreign_keys=[asset_account_id])
    transactions = relationship("ShareholdingTransaction", back_populates="shareholding", cascade="all, delete-orphan")

    @property
    def unrealized_gain_loss(self) -> Decimal:
        """Beräkna orealiserad vinst/förlust"""
        if self.market_value:
            return Decimal(str(self.market_value)) - Decimal(str(self.book_value))
        return Decimal(0)

    def __repr__(self):
        return f"<Shareholding(id={self.id}, target={self.target_company_name}, shares={self.num_shares})>"


class ShareholdingTransaction(Base):
    """
    Transaktioner för aktieinnehav (köp, försäljning, utdelning, nedskrivning)
    """
    __tablename__ = "shareholding_transactions"

    id = Column(Integer, primary_key=True, index=True)
    shareholding_id = Column(Integer, ForeignKey("shareholdings.id"), nullable=False)

    # Typ av transaktion
    transaction_type = Column(String(50), nullable=False)  # purchase, sale, dividend, impairment, reversal

    # Datum och belopp
    transaction_date = Column(Date, nullable=False)
    num_shares = Column(Integer, nullable=True)  # Antal aktier (vid köp/sälj)
    amount = Column(Numeric(15, 2), nullable=False)
    price_per_share = Column(Numeric(15, 2), nullable=True)

    # Koppling till bokföringstransaktion
    accounting_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)

    # Beskrivning
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    # Relationer
    shareholding = relationship("Shareholding", back_populates="transactions")
    accounting_transaction = relationship("Transaction")

    def __repr__(self):
        return f"<ShareholdingTransaction(id={self.id}, type={self.transaction_type}, amount={self.amount})>"
