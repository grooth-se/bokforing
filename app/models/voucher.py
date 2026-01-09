"""
Verifikatmodell - Dokumenthantering
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


class Voucher(Base):
    """
    Verifikat/Underlag

    Lagrar metadata om fysiska/digitala underlag som
    kvitton, fakturor, kontoutdrag etc.
    Filerna lagras i data/vouchers/ mappen.
    """
    __tablename__ = "vouchers"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)

    # Filsökväg relativt till voucher-mappen
    file_path = Column(String(500), nullable=False)

    # Ursprungligt filnamn
    original_filename = Column(String(255))

    # MIME-typ
    content_type = Column(String(100))

    # Metadata
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    # Relationer
    transaction = relationship("Transaction", back_populates="vouchers")

    def __repr__(self):
        return f"<Voucher(id={self.id}, file='{self.original_filename}')>"
