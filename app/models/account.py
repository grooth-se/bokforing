"""
Kontomodell - BAS-kontoplan
"""
from sqlalchemy import Column, Integer, String, ForeignKey, Enum, Boolean, Numeric
from sqlalchemy.orm import relationship
from app.models.base import Base
from app.config import AccountType


class Account(Base):
    """
    Konto enligt BAS-kontoplan

    BAS-kontoplanen är indelad i klasser:
    - 1xxx: Tillgångar
    - 2xxx: Eget kapital och skulder
    - 3xxx: Rörelsens intäkter
    - 4xxx: Rörelsens kostnader (varor)
    - 5-6xxx: Övriga externa kostnader
    - 7xxx: Personal
    - 8xxx: Finansiella poster och skatter
    """
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # BAS-kontonummer (t.ex. 1910 för Kassa, 3010 för Försäljning)
    number = Column(String(10), nullable=False)
    name = Column(String(255), nullable=False)

    # Kontotyp
    account_type = Column(Enum(AccountType), nullable=False)

    # Momskod (för automatisk momshantering)
    vat_code = Column(String(10))  # t.ex. "25", "12", "6", "0"

    # Är kontot aktivt?
    is_active = Column(Boolean, default=True)

    # Ingående balans för räkenskapsåret
    opening_balance = Column(Numeric(15, 2), default=0)

    # Relationer
    company = relationship("Company", back_populates="accounts")
    transaction_lines = relationship("TransactionLine", back_populates="account")

    def __repr__(self):
        return f"<Account(number={self.number}, name='{self.name}')>"

    @property
    def account_class(self) -> int:
        """Returnera kontoklass (1-8) baserat på kontonummer"""
        if self.number:
            return int(self.number[0])
        return 0

    @property
    def is_balance_account(self) -> bool:
        """Är detta ett balanskonto (klass 1-2)?"""
        return self.account_class in [1, 2]

    @property
    def is_result_account(self) -> bool:
        """Är detta ett resultatkonto (klass 3-8)?"""
        return self.account_class in [3, 4, 5, 6, 7, 8]
