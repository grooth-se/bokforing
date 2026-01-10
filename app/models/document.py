"""
Dokumenthantering - Företagsdokument med versionshistorik
"""
from datetime import date, datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, LargeBinary, Text, Enum, Boolean
from sqlalchemy.orm import relationship
from app.models.base import Base


class DocumentType(PyEnum):
    """Typ av företagsdokument"""
    REGISTRATION_CERT = "Registreringsbevis"
    F_TAX_CERT = "F-skattebevis"
    VAT_REGISTRATION = "Momsregistrering"
    ARTICLES = "Bolagsordning"
    BOARD_REGISTER = "Styrelseregister"
    SHAREHOLDER_REGISTER = "Aktiebok"
    ANNUAL_MEETING = "Bolagsstämmoprotokoll"
    BOARD_MEETING = "Styrelseprotokoll"
    BANK_STATEMENT = "Bankutdrag"
    INSURANCE = "Försäkringsbrev"
    CONTRACT = "Avtal"
    PERMIT = "Tillstånd"
    OTHER = "Övrigt"


class CompanyDocument(Base):
    """
    Företagsdokument med versionshistorik

    När ett dokument uppdateras (t.ex. nytt registreringsbevis vid adressbyte)
    skapas en ny version medan den gamla behålls för historik.
    """
    __tablename__ = "company_documents"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Dokumentinfo
    document_type = Column(Enum(DocumentType), nullable=False)
    name = Column(String(255), nullable=False)  # Beskrivande namn
    description = Column(Text, nullable=True)

    # Fil
    file_data = Column(LargeBinary, nullable=False)
    filename = Column(String(255), nullable=False)
    mimetype = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)  # bytes

    # Versionshantering
    version = Column(Integer, default=1, nullable=False)
    parent_id = Column(Integer, ForeignKey("company_documents.id"), nullable=True)
    is_current = Column(Boolean, default=True, nullable=False)

    # Giltighetsdatum
    valid_from = Column(Date, nullable=True)
    valid_until = Column(Date, nullable=True)

    # Utfärdare
    issuer = Column(String(255), nullable=True)  # T.ex. "Bolagsverket", "Skatteverket"
    reference_number = Column(String(100), nullable=True)  # Ärendenummer etc.

    # Metadata
    uploaded_at = Column(DateTime, default=datetime.now, nullable=False)
    uploaded_by = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    # Relationer
    company = relationship("Company", back_populates="documents")
    previous_versions = relationship(
        "CompanyDocument",
        backref="newer_version",
        remote_side=[id],
        foreign_keys=[parent_id]
    )

    def __repr__(self):
        return f"<CompanyDocument(id={self.id}, type={self.document_type.value}, v{self.version})>"


class AnnualReport(Base):
    """
    Register över inskickade årsredovisningar till Bolagsverket
    """
    __tablename__ = "annual_reports"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    fiscal_year_id = Column(Integer, ForeignKey("fiscal_years.id"), nullable=False)

    # Räkenskapsår
    fiscal_year_start = Column(Date, nullable=False)
    fiscal_year_end = Column(Date, nullable=False)

    # Inskickning
    submitted_date = Column(Date, nullable=True)
    registered_date = Column(Date, nullable=True)  # Datum Bolagsverket registrerade
    bolagsverket_reference = Column(String(100), nullable=True)  # Ärendenummer

    # Status
    status = Column(String(50), default="draft")  # draft, submitted, registered, rejected

    # Dokument
    report_file = Column(LargeBinary, nullable=True)
    report_filename = Column(String(255), nullable=True)

    # Nyckeltal från årsredovisningen
    revenue = Column(Integer, nullable=True)  # Omsättning
    profit_loss = Column(Integer, nullable=True)  # Resultat
    total_assets = Column(Integer, nullable=True)  # Balansomslutning
    equity = Column(Integer, nullable=True)  # Eget kapital
    num_employees = Column(Integer, nullable=True)  # Antal anställda

    # Underskrifter
    signed_by = Column(Text, nullable=True)  # JSON med lista på undertecknare
    signed_date = Column(Date, nullable=True)

    # Revision
    auditor_name = Column(String(255), nullable=True)
    auditor_report_date = Column(Date, nullable=True)
    auditor_opinion = Column(String(50), nullable=True)  # clean, qualified, adverse, disclaimer

    # Metadata
    created_at = Column(DateTime, default=datetime.now)
    notes = Column(Text, nullable=True)

    # Relationer
    company = relationship("Company", back_populates="annual_reports")
    fiscal_year = relationship("FiscalYear", backref="annual_report")

    def __repr__(self):
        return f"<AnnualReport(id={self.id}, year={self.fiscal_year_end.year}, status={self.status})>"
