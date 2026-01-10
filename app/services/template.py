"""
Malltjänst - Hantering av konteringsmallar och rapportmallar

Två typer av mallar:
1. Konteringsmallar - för återkommande transaktioner
2. Rapportmallar - för generering av dokument (årsredovisning, etc.)
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Dict
from pathlib import Path
from sqlalchemy.orm import Session

from app.models import Account, Transaction
from app.models.template import TransactionTemplate, TemplateLineItem, STANDARD_TEMPLATES
from app.services.accounting import AccountingService


class TemplateService:
    """
    Tjänst för konteringsmallar

    Användning:
    1. Skapa mall med create_template()
    2. Använd mall med apply_template() för att skapa transaktion
    """

    def __init__(self, db: Session):
        self.db = db
        self.accounting_service = AccountingService(db)

    def create_template(
        self,
        company_id: int,
        name: str,
        lines: List[Dict],
        description: str = None,
        category: str = None
    ) -> TransactionTemplate:
        """
        Skapa en ny konteringsmall

        Args:
            company_id: Företags-ID
            name: Mallens namn
            lines: Lista med konteringsrader:
                [
                    {
                        'account_id': 123,
                        'is_debit': True,
                        'percentage': 25,  # eller 'fixed': 1000, eller 'is_remainder': True
                    },
                    ...
                ]
            description: Beskrivning
            category: Kategori (Moms, Lön, etc.)
        """
        template = TransactionTemplate(
            company_id=company_id,
            name=name,
            description=description,
            category=category,
            is_active=True
        )

        self.db.add(template)
        self.db.flush()  # För att få template.id

        for i, line_data in enumerate(lines):
            line = TemplateLineItem(
                template_id=template.id,
                account_id=line_data['account_id'],
                is_debit=line_data['is_debit'],
                amount_fixed=line_data.get('fixed'),
                amount_percentage=line_data.get('percentage'),
                is_remainder=line_data.get('is_remainder', False),
                sort_order=i,
                description=line_data.get('description')
            )
            self.db.add(line)

        self.db.commit()
        self.db.refresh(template)
        return template

    def get_templates(
        self,
        company_id: int,
        category: str = None,
        active_only: bool = True
    ) -> List[TransactionTemplate]:
        """Hämta mallar för ett företag"""
        query = (
            self.db.query(TransactionTemplate)
            .filter(TransactionTemplate.company_id == company_id)
        )

        if active_only:
            query = query.filter(TransactionTemplate.is_active == True)

        if category:
            query = query.filter(TransactionTemplate.category == category)

        return query.order_by(TransactionTemplate.category, TransactionTemplate.name).all()

    def get_template(self, template_id: int) -> Optional[TransactionTemplate]:
        """Hämta en specifik mall"""
        return self.db.query(TransactionTemplate).filter(TransactionTemplate.id == template_id).first()

    def apply_template(
        self,
        template: TransactionTemplate,
        fiscal_year_id: int,
        transaction_date: date,
        total_amount: Decimal,
        description: str = None
    ) -> Transaction:
        """
        Använd mall för att skapa transaktion

        Args:
            template: Mallen att använda
            fiscal_year_id: Räkenskapsår-ID
            transaction_date: Transaktionsdatum
            total_amount: Totalbelopp (inkl moms om relevant)
            description: Transaktionsbeskrivning

        Returns:
            Skapad transaktion
        """
        lines = []
        running_total_debit = Decimal(0)
        running_total_credit = Decimal(0)
        remainder_line = None

        # Sortera rader
        sorted_lines = sorted(template.lines, key=lambda x: x.sort_order)

        for line in sorted_lines:
            if line.is_remainder:
                remainder_line = line
                continue

            amount = line.calculate_amount(total_amount)

            if line.is_debit:
                lines.append({
                    "account_id": line.account_id,
                    "debit": amount,
                    "credit": Decimal(0)
                })
                running_total_debit += amount
            else:
                lines.append({
                    "account_id": line.account_id,
                    "debit": Decimal(0),
                    "credit": amount
                })
                running_total_credit += amount

        # Hantera remainder (balansrad)
        if remainder_line:
            diff = running_total_debit - running_total_credit
            if remainder_line.is_debit:
                amount = abs(diff) if diff < 0 else Decimal(0)
                lines.append({
                    "account_id": remainder_line.account_id,
                    "debit": amount if amount > 0 else (total_amount - running_total_debit),
                    "credit": Decimal(0)
                })
            else:
                amount = abs(diff) if diff > 0 else Decimal(0)
                lines.append({
                    "account_id": remainder_line.account_id,
                    "debit": Decimal(0),
                    "credit": amount if amount > 0 else (total_amount - running_total_credit)
                })

        # Uppdatera användningsstatistik
        template.usage_count += 1

        # Skapa transaktion
        tx = self.accounting_service.create_transaction(
            company_id=template.company_id,
            fiscal_year_id=fiscal_year_id,
            transaction_date=transaction_date,
            description=description or f"Transaktion från mall: {template.name}",
            lines=lines
        )

        self.db.commit()
        return tx

    def initialize_standard_templates(self, company_id: int) -> List[TransactionTemplate]:
        """
        Skapa standardmallar för ett företag

        Skapar mallar för vanliga transaktionstyper som moms, lön, etc.
        """
        created = []
        accounts = self.accounting_service.get_accounts(company_id)
        account_map = {a.number: a.id for a in accounts}

        for key, template_def in STANDARD_TEMPLATES.items():
            # Kontrollera om mallen redan finns
            existing = (
                self.db.query(TransactionTemplate)
                .filter(
                    TransactionTemplate.company_id == company_id,
                    TransactionTemplate.name == template_def['name']
                )
                .first()
            )
            if existing:
                continue

            # Bygg lines med korrekta account_ids
            lines = []
            for line_def in template_def['lines']:
                account_number = line_def['account_number']
                account_id = account_map.get(account_number)

                if not account_id:
                    continue  # Hoppa över om kontot inte finns

                line = {
                    'account_id': account_id,
                    'is_debit': line_def['is_debit'],
                }

                if 'percentage' in line_def:
                    line['percentage'] = line_def['percentage']
                if 'fixed' in line_def:
                    line['fixed'] = line_def['fixed']
                if line_def.get('is_remainder'):
                    line['is_remainder'] = True

                lines.append(line)

            if lines:
                template = self.create_template(
                    company_id=company_id,
                    name=template_def['name'],
                    description=template_def['description'],
                    category=template_def['category'],
                    lines=lines
                )
                created.append(template)

        return created

    def delete_template(self, template_id: int) -> bool:
        """Ta bort en mall"""
        template = self.get_template(template_id)
        if template:
            self.db.delete(template)
            self.db.commit()
            return True
        return False

    def update_template(
        self,
        template_id: int,
        name: str = None,
        description: str = None,
        category: str = None,
        is_active: bool = None
    ) -> Optional[TransactionTemplate]:
        """Uppdatera mall-metadata (inte rader)"""
        template = self.get_template(template_id)
        if not template:
            return None

        if name is not None:
            template.name = name
        if description is not None:
            template.description = description
        if category is not None:
            template.category = category
        if is_active is not None:
            template.is_active = is_active

        self.db.commit()
        return template

    def get_categories(self, company_id: int) -> List[str]:
        """Hämta alla unika kategorier"""
        results = (
            self.db.query(TransactionTemplate.category)
            .filter(
                TransactionTemplate.company_id == company_id,
                TransactionTemplate.category.isnot(None)
            )
            .distinct()
            .all()
        )
        return [r[0] for r in results if r[0]]
