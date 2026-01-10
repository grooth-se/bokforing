"""
Skattedeklarationsmodell - Sparar underlag för inkomstdeklaration
"""
from datetime import date, datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from app.models.base import Base


class TaxDeclaration(Base):
    """
    Skattedeklarationsunderlag

    Sparar strukturerad data för inkomstdeklaration (INK2 för aktiebolag).
    Används som ingångsvärden för nästa års deklaration.
    """
    __tablename__ = "tax_declarations"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    fiscal_year_id = Column(Integer, ForeignKey("fiscal_years.id"), nullable=False)

    # Typ av deklaration
    declaration_type = Column(String(20), nullable=False)  # "INK2", "INK4", etc.

    # Status
    status = Column(String(20), default="draft")  # "draft", "final", "submitted"

    # Strukturerad data (JSON)
    # Innehåller alla fält från deklarationen
    data = Column(JSON, nullable=False, default=dict)

    # Kommentarer/anteckningar
    notes = Column(Text)

    # Tidsstämplar
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    submitted_at = Column(DateTime, nullable=True)

    # Relationer
    company = relationship("Company", backref="tax_declarations")
    fiscal_year = relationship("FiscalYear", backref="tax_declarations")

    def __repr__(self):
        return f"<TaxDeclaration(id={self.id}, type={self.declaration_type}, year={self.fiscal_year_id})>"
