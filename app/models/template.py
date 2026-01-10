"""
Konteringsmallar - Mallar för återkommande transaktioner

Exempel:
- Momskontering (ingående/utgående moms)
- Lönekontering (lön, skatt, arbetsgivaravgifter)
- Hyra
- El och uppvärmning
"""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Text, Boolean, JSON
from sqlalchemy.orm import relationship
from app.models.base import Base


class TransactionTemplate(Base):
    """
    Mall för återkommande transaktioner

    Innehåller:
    - Namn och beskrivning
    - Lista med konteringsrader (konton och fördelning)
    - Kan ha fasta belopp eller procentsatser
    """
    __tablename__ = "transaction_templates"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Mallinfo
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)  # T.ex. "Moms", "Lön", "Hyra"

    # Status
    is_active = Column(Boolean, default=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    usage_count = Column(Integer, default=0)  # Antal gånger använd

    # Relationer
    company = relationship("Company", backref="transaction_templates")
    lines = relationship("TemplateLineItem", back_populates="template", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<TransactionTemplate(id={self.id}, name='{self.name}')>"


class TemplateLineItem(Base):
    """
    Rad i en konteringsmall

    Kan specificeras på olika sätt:
    1. Fast belopp: amount_fixed = 1000
    2. Procent av totalbelopp: amount_percentage = 25 (25%)
    3. Resterande belopp: is_remainder = True (används för balansrad)
    """
    __tablename__ = "template_line_items"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("transaction_templates.id"), nullable=False)

    # Konto
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)

    # Debet eller kredit
    is_debit = Column(Boolean, nullable=False)  # True = debet, False = kredit

    # Beloppsspecifikation (en av dessa används)
    amount_fixed = Column(Numeric(15, 2), nullable=True)  # Fast belopp
    amount_percentage = Column(Numeric(5, 2), nullable=True)  # Procent av total
    is_remainder = Column(Boolean, default=False)  # Resterande belopp

    # Ordning
    sort_order = Column(Integer, default=0)

    # Beskrivning för raden
    description = Column(String(255), nullable=True)

    # Relationer
    template = relationship("TransactionTemplate", back_populates="lines")
    account = relationship("Account")

    def calculate_amount(self, total_amount: Decimal) -> Decimal:
        """Beräkna belopp baserat på specifikation"""
        if self.amount_fixed is not None:
            return Decimal(str(self.amount_fixed))
        elif self.amount_percentage is not None:
            return (Decimal(str(total_amount)) * Decimal(str(self.amount_percentage)) / 100).quantize(Decimal('0.01'))
        else:
            return Decimal(0)

    def __repr__(self):
        side = "D" if self.is_debit else "K"
        return f"<TemplateLineItem(id={self.id}, account={self.account_id}, {side})>"


# Fördefinierade standardmallar
STANDARD_TEMPLATES = {
    'moms_25_inköp': {
        'name': 'Inköp med 25% moms',
        'description': 'Mall för inköp med 25% moms',
        'category': 'Moms',
        'lines': [
            {'account_number': '4000', 'is_debit': True, 'percentage': 80},  # Varuinköp (80% av inkl moms)
            {'account_number': '2640', 'is_debit': True, 'percentage': 20},  # Ingående moms (20% av inkl moms)
            {'account_number': '2440', 'is_debit': False, 'is_remainder': True},  # Leverantörsskuld
        ]
    },
    'moms_25_försäljning': {
        'name': 'Försäljning med 25% moms',
        'description': 'Mall för försäljning med 25% moms',
        'category': 'Moms',
        'lines': [
            {'account_number': '1510', 'is_debit': True, 'is_remainder': True},  # Kundfordran
            {'account_number': '3000', 'is_debit': False, 'percentage': 80},  # Försäljning
            {'account_number': '2610', 'is_debit': False, 'percentage': 20},  # Utgående moms
        ]
    },
    'lön_enkel': {
        'name': 'Löneutbetalning (enkel)',
        'description': 'Enkel lönekostnad utan arbetsgivaravgifter',
        'category': 'Lön',
        'lines': [
            {'account_number': '7010', 'is_debit': True, 'percentage': 100},  # Lönekostnad
            {'account_number': '2710', 'is_debit': False, 'percentage': 30},  # Källskatt (ca 30%)
            {'account_number': '1930', 'is_debit': False, 'is_remainder': True},  # Bank (nettolön)
        ]
    },
    'lön_komplett': {
        'name': 'Löneutbetalning (komplett)',
        'description': 'Lönekostnad med arbetsgivaravgifter',
        'category': 'Lön',
        'lines': [
            {'account_number': '7010', 'is_debit': True, 'percentage': 76.16},  # Bruttolön
            {'account_number': '7510', 'is_debit': True, 'percentage': 23.84},  # Arbetsgivaravgifter (31.42% av brutto)
            {'account_number': '2710', 'is_debit': False, 'percentage': 22.85},  # Källskatt (30% av brutto)
            {'account_number': '2730', 'is_debit': False, 'percentage': 23.84},  # Skuld arbetsgivaravgifter
            {'account_number': '1930', 'is_debit': False, 'is_remainder': True},  # Bank (nettolön)
        ]
    },
    'hyra': {
        'name': 'Hyra lokal',
        'description': 'Månadshyra för lokal',
        'category': 'Lokalkostnader',
        'lines': [
            {'account_number': '5010', 'is_debit': True, 'percentage': 100},  # Lokalhyra
            {'account_number': '2440', 'is_debit': False, 'is_remainder': True},  # Leverantörsskuld
        ]
    },
    'kontant_inköp': {
        'name': 'Kontant inköp',
        'description': 'Inköp betalt kontant/kort',
        'category': 'Inköp',
        'lines': [
            {'account_number': '4000', 'is_debit': True, 'percentage': 80},  # Varuinköp
            {'account_number': '2640', 'is_debit': True, 'percentage': 20},  # Ingående moms
            {'account_number': '1930', 'is_debit': False, 'is_remainder': True},  # Bank
        ]
    }
}
