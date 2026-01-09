"""
Transaktionsmodeller - Verifikationer och konteringsrader
"""
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Numeric, CheckConstraint
from sqlalchemy.orm import relationship, validates
from app.models.base import Base


class Transaction(Base):
    """
    Verifikation/Huvudpost

    En transaktion representerar en affärshändelse med
    ett eller flera konteringsrader (debet/kredit).
    """
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    fiscal_year_id = Column(Integer, ForeignKey("fiscal_years.id"), nullable=False)

    # Verifikationsnummer (unikt inom företag och räkenskapsår)
    verification_number = Column(Integer, nullable=False)

    # Transaktionsdatum
    transaction_date = Column(Date, nullable=False, default=date.today)

    # Beskrivning
    description = Column(String(500), nullable=False)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationer
    company = relationship("Company", back_populates="transactions")
    fiscal_year = relationship("FiscalYear", back_populates="transactions")
    lines = relationship("TransactionLine", back_populates="transaction", cascade="all, delete-orphan")
    vouchers = relationship("Voucher", back_populates="transaction", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Transaction(ver={self.verification_number}, date={self.transaction_date})>"

    @property
    def total_debit(self) -> Decimal:
        """Total debet för transaktionen"""
        return sum(line.debit or Decimal(0) for line in self.lines)

    @property
    def total_credit(self) -> Decimal:
        """Total kredit för transaktionen"""
        return sum(line.credit or Decimal(0) for line in self.lines)

    @property
    def is_balanced(self) -> bool:
        """Kontrollera att debet = kredit"""
        return self.total_debit == self.total_credit


class TransactionLine(Base):
    """
    Konteringsrad

    Varje transaktion har minst två rader för dubbel bokföring.
    Summa debet måste vara lika med summa kredit.
    """
    __tablename__ = "transaction_lines"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)

    # Belopp (endast ett av debet/kredit ska vara satt)
    debit = Column(Numeric(15, 2), default=Decimal(0))
    credit = Column(Numeric(15, 2), default=Decimal(0))

    # Valfri radkommentar
    description = Column(String(255))

    # Relationer
    transaction = relationship("Transaction", back_populates="lines")
    account = relationship("Account", back_populates="transaction_lines")

    # Constraint: antingen debet eller kredit, inte båda
    __table_args__ = (
        CheckConstraint(
            "(debit > 0 AND credit = 0) OR (debit = 0 AND credit > 0) OR (debit = 0 AND credit = 0)",
            name="check_debit_or_credit"
        ),
    )

    def __repr__(self):
        if self.debit and self.debit > 0:
            return f"<TransactionLine(account={self.account_id}, debit={self.debit})>"
        return f"<TransactionLine(account={self.account_id}, credit={self.credit})>"

    @property
    def amount(self) -> Decimal:
        """Returnera beloppet (positivt för debet, negativt för kredit)"""
        if self.debit and self.debit > 0:
            return self.debit
        if self.credit and self.credit > 0:
            return -self.credit
        return Decimal(0)
