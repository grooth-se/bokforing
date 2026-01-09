"""
Räkenskapsårsmodell
"""
from datetime import date
from sqlalchemy import Column, Integer, Date, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


class FiscalYear(Base):
    """
    Räkenskapsår

    Hanterar bokföringsperioder och årsbokslut.
    De flesta svenska företag har kalenderår (jan-dec),
    men brutet räkenskapsår är också möjligt.
    """
    __tablename__ = "fiscal_years"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)

    # Är räkenskapsåret avslutat/låst?
    is_closed = Column(Boolean, default=False)

    # Relationer
    company = relationship("Company", back_populates="fiscal_years")
    transactions = relationship("Transaction", back_populates="fiscal_year")

    def __repr__(self):
        return f"<FiscalYear({self.start_date} - {self.end_date})>"

    @property
    def year(self) -> int:
        """Returnera huvudåret (baserat på slutdatum)"""
        return self.end_date.year

    @property
    def is_current(self) -> bool:
        """Är detta det aktuella räkenskapsåret?"""
        today = date.today()
        return self.start_date <= today <= self.end_date

    def contains_date(self, check_date: date) -> bool:
        """Kontrollera om ett datum ligger inom räkenskapsåret"""
        return self.start_date <= check_date <= self.end_date
