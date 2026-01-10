"""
Rapportgenerering - Genererar dokument från mallar

Stödjer generering av:
- Årsredovisning
- Resultaträkning
- Balansräkning
- Aktiebok
- Styrelseprotokoll
- Bolagsstämmoprotokoll

Mallar lagras i: templates/
    /arsredovisning/
        k2_arsredovisning.html
        k3_arsredovisning.html
    /rapporter/
        resultatrakning.html
        balansrakning.html
    /protokoll/
        styrelsemote.html
        bolagsstamma.html
    /register/
        aktiebok.html
"""
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session
import base64

from app.models import Company, Account, FiscalYear
from app.services.accounting import AccountingService


class ReportGenerator:
    """
    Genererar dokument från Jinja2-mallar

    Mallstruktur:
    - Mallar är HTML-filer med Jinja2-syntax
    - Kan konverteras till PDF med weasyprint eller liknande
    - Innehåller platshållare för företagsdata
    """

    TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"

    # Malltyper och deras platser
    TEMPLATE_TYPES = {
        'annual_report_k2': 'arsredovisning/k2_arsredovisning.html',
        'annual_report_k3': 'arsredovisning/k3_arsredovisning.html',
        'income_statement': 'rapporter/resultatrakning.html',
        'balance_sheet': 'rapporter/balansrakning.html',
        'trial_balance': 'rapporter/rabalans.html',
        'general_ledger': 'rapporter/huvudbok.html',
        'shareholder_register': 'register/aktiebok.html',
        'board_meeting': 'protokoll/styrelsemote.html',
        'annual_meeting': 'protokoll/bolagsstamma.html',
    }

    def __init__(self, db: Session):
        self.db = db
        self.accounting_service = AccountingService(db)

        # Skapa mallmapp om den inte finns
        self.TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

        # Initiera Jinja2
        self.env = Environment(
            loader=FileSystemLoader(str(self.TEMPLATE_DIR)),
            autoescape=select_autoescape(['html', 'xml'])
        )

        # Lägg till filter
        self.env.filters['currency'] = self._currency_filter
        self.env.filters['date_format'] = self._date_filter

    def _currency_filter(self, value) -> str:
        """Formatera tal som valuta"""
        if value is None:
            return "0 kr"
        try:
            num = float(value)
            return f"{num:,.0f} kr".replace(",", " ")
        except (ValueError, TypeError):
            return str(value)

    def _date_filter(self, value, format_str: str = "%Y-%m-%d") -> str:
        """Formatera datum"""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return value.strftime(format_str)

    def get_available_templates(self) -> Dict[str, bool]:
        """Lista tillgängliga mallar"""
        available = {}
        for name, path in self.TEMPLATE_TYPES.items():
            template_path = self.TEMPLATE_DIR / path
            available[name] = template_path.exists()
        return available

    def generate_annual_report(
        self,
        company_id: int,
        fiscal_year_id: int,
        additional_data: Dict = None
    ) -> str:
        """
        Generera årsredovisning

        Args:
            company_id: Företags-ID
            fiscal_year_id: Räkenskapsår-ID
            additional_data: Extra data (styrelseledamöter, etc.)

        Returns:
            HTML-sträng
        """
        company = self.db.query(Company).filter(Company.id == company_id).first()
        fiscal_year = self.db.query(FiscalYear).filter(FiscalYear.id == fiscal_year_id).first()

        if not company or not fiscal_year:
            raise ValueError("Företag eller räkenskapsår finns inte")

        # Välj mall baserat på K2/K3
        template_key = f"annual_report_{company.accounting_standard.value.lower()}"
        template_path = self.TEMPLATE_TYPES.get(template_key)

        if not template_path or not (self.TEMPLATE_DIR / template_path).exists():
            # Använd standardmall
            return self._generate_default_annual_report(company, fiscal_year, additional_data)

        # Hämta finansiell data
        financial_data = self._get_financial_data(company_id, fiscal_year)

        # Bygg kontext
        context = {
            'company': company,
            'fiscal_year': fiscal_year,
            'generated_at': datetime.now(),
            **financial_data,
            **(additional_data or {})
        }

        # Lägg till logotyp om den finns
        if company.logo:
            logo_b64 = base64.b64encode(company.logo).decode('utf-8')
            context['logo_base64'] = f"data:{company.logo_mimetype};base64,{logo_b64}"

        template = self.env.get_template(template_path)
        return template.render(context)

    def _get_financial_data(self, company_id: int, fiscal_year: FiscalYear) -> Dict:
        """Hämta finansiell data för rapporter"""
        # Råbalans
        trial_balance = self.accounting_service.get_trial_balance(
            company_id, fiscal_year.end_date
        )

        # Gruppera per kontoklass
        income_statement = {'revenue': [], 'expenses': [], 'total_revenue': Decimal(0), 'total_expenses': Decimal(0)}
        balance_sheet = {'assets': [], 'liabilities': [], 'total_assets': Decimal(0), 'total_liabilities': Decimal(0)}

        for account_data in trial_balance:
            number = account_data['account_number']
            balance = Decimal(str(account_data['balance']))

            if number.startswith('1'):
                balance_sheet['assets'].append(account_data)
                balance_sheet['total_assets'] += balance
            elif number.startswith('2'):
                balance_sheet['liabilities'].append(account_data)
                balance_sheet['total_liabilities'] += balance
            elif number.startswith('3'):
                income_statement['revenue'].append(account_data)
                income_statement['total_revenue'] += abs(balance)
            elif number[0] in '45678':
                income_statement['expenses'].append(account_data)
                income_statement['total_expenses'] += balance

        # Resultat
        result = income_statement['total_revenue'] - income_statement['total_expenses']

        return {
            'trial_balance': trial_balance,
            'income_statement': income_statement,
            'balance_sheet': balance_sheet,
            'result': result,
        }

    def _generate_default_annual_report(
        self,
        company: Company,
        fiscal_year: FiscalYear,
        additional_data: Dict = None
    ) -> str:
        """Generera enkel årsredovisning utan mall"""
        financial_data = self._get_financial_data(company.id, fiscal_year)

        # Bygg HTML
        html = f"""
        <!DOCTYPE html>
        <html lang="sv">
        <head>
            <meta charset="UTF-8">
            <title>Årsredovisning {company.name} {fiscal_year.end_date.year}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
                h1 {{ color: #333; border-bottom: 2px solid #333; padding-bottom: 10px; }}
                h2 {{ color: #555; margin-top: 30px; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background-color: #f5f5f5; }}
                .amount {{ text-align: right; }}
                .total {{ font-weight: bold; border-top: 2px solid #333; }}
                .header {{ text-align: center; margin-bottom: 40px; }}
                .logo {{ max-width: 150px; margin-bottom: 20px; }}
                .company-info {{ margin-bottom: 30px; }}
                .footer {{ margin-top: 50px; font-size: 0.9em; color: #666; }}
            </style>
        </head>
        <body>
            <div class="header">
                {"<img src='data:" + company.logo_mimetype + ";base64," + base64.b64encode(company.logo).decode() + "' class='logo'>" if company.logo else ""}
                <h1>Årsredovisning</h1>
                <h2>{company.name}</h2>
                <p>Organisationsnummer: {company.org_number}</p>
                <p>Räkenskapsår: {fiscal_year.start_date} - {fiscal_year.end_date}</p>
            </div>

            <h2>Resultaträkning</h2>
            <table>
                <tr><th>Konto</th><th>Namn</th><th class="amount">Belopp</th></tr>
                <tr><td colspan="3"><strong>Intäkter</strong></td></tr>
        """

        for item in financial_data['income_statement']['revenue']:
            html += f"<tr><td>{item['account_number']}</td><td>{item['account_name']}</td><td class='amount'>{abs(item['balance']):,.0f} kr</td></tr>"

        html += f"""
                <tr class="total"><td></td><td>Summa intäkter</td><td class="amount">{financial_data['income_statement']['total_revenue']:,.0f} kr</td></tr>
                <tr><td colspan="3"><strong>Kostnader</strong></td></tr>
        """

        for item in financial_data['income_statement']['expenses']:
            html += f"<tr><td>{item['account_number']}</td><td>{item['account_name']}</td><td class='amount'>{item['balance']:,.0f} kr</td></tr>"

        html += f"""
                <tr class="total"><td></td><td>Summa kostnader</td><td class="amount">{financial_data['income_statement']['total_expenses']:,.0f} kr</td></tr>
                <tr class="total"><td></td><td><strong>Årets resultat</strong></td><td class="amount"><strong>{financial_data['result']:,.0f} kr</strong></td></tr>
            </table>

            <h2>Balansräkning</h2>
            <table>
                <tr><th>Konto</th><th>Namn</th><th class="amount">Belopp</th></tr>
                <tr><td colspan="3"><strong>Tillgångar</strong></td></tr>
        """

        for item in financial_data['balance_sheet']['assets']:
            if item['balance'] != 0:
                html += f"<tr><td>{item['account_number']}</td><td>{item['account_name']}</td><td class='amount'>{item['balance']:,.0f} kr</td></tr>"

        html += f"""
                <tr class="total"><td></td><td>Summa tillgångar</td><td class="amount">{financial_data['balance_sheet']['total_assets']:,.0f} kr</td></tr>
                <tr><td colspan="3"><strong>Eget kapital och skulder</strong></td></tr>
        """

        for item in financial_data['balance_sheet']['liabilities']:
            if item['balance'] != 0:
                html += f"<tr><td>{item['account_number']}</td><td>{item['account_name']}</td><td class='amount'>{abs(item['balance']):,.0f} kr</td></tr>"

        html += f"""
                <tr class="total"><td></td><td>Summa eget kapital och skulder</td><td class="amount">{abs(financial_data['balance_sheet']['total_liabilities']):,.0f} kr</td></tr>
            </table>

            <div class="footer">
                <p>Genererad: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
                <p>Redovisningsstandard: {company.accounting_standard.value}</p>
            </div>
        </body>
        </html>
        """

        return html

    def generate_income_statement(
        self,
        company_id: int,
        fiscal_year_id: int
    ) -> str:
        """Generera resultaträkning"""
        company = self.db.query(Company).filter(Company.id == company_id).first()
        fiscal_year = self.db.query(FiscalYear).filter(FiscalYear.id == fiscal_year_id).first()
        financial_data = self._get_financial_data(company_id, fiscal_year)

        # Kontrollera om mall finns
        template_path = self.TEMPLATE_TYPES.get('income_statement')
        if template_path and (self.TEMPLATE_DIR / template_path).exists():
            template = self.env.get_template(template_path)
            return template.render(
                company=company,
                fiscal_year=fiscal_year,
                **financial_data
            )

        # Standardrapport
        return self._generate_simple_report(
            "Resultaträkning",
            company,
            fiscal_year,
            financial_data['income_statement']
        )

    def generate_balance_sheet(
        self,
        company_id: int,
        fiscal_year_id: int
    ) -> str:
        """Generera balansräkning"""
        company = self.db.query(Company).filter(Company.id == company_id).first()
        fiscal_year = self.db.query(FiscalYear).filter(FiscalYear.id == fiscal_year_id).first()
        financial_data = self._get_financial_data(company_id, fiscal_year)

        # Kontrollera om mall finns
        template_path = self.TEMPLATE_TYPES.get('balance_sheet')
        if template_path and (self.TEMPLATE_DIR / template_path).exists():
            template = self.env.get_template(template_path)
            return template.render(
                company=company,
                fiscal_year=fiscal_year,
                **financial_data
            )

        return self._generate_simple_report(
            "Balansräkning",
            company,
            fiscal_year,
            financial_data['balance_sheet']
        )

    def generate_shareholder_register(
        self,
        company_id: int,
        shareholders: List[Dict]
    ) -> str:
        """Generera aktiebok"""
        company = self.db.query(Company).filter(Company.id == company_id).first()

        template_path = self.TEMPLATE_TYPES.get('shareholder_register')
        if template_path and (self.TEMPLATE_DIR / template_path).exists():
            template = self.env.get_template(template_path)
            return template.render(
                company=company,
                shareholders=shareholders,
                generated_at=datetime.now()
            )

        # Standardaktiebook
        return self._generate_default_shareholder_register(company, shareholders)

    def _generate_default_shareholder_register(
        self,
        company: Company,
        shareholders: List[Dict]
    ) -> str:
        """Generera enkel aktiebok"""
        html = f"""
        <!DOCTYPE html>
        <html lang="sv">
        <head>
            <meta charset="UTF-8">
            <title>Aktiebok - {company.name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                h1 {{ border-bottom: 2px solid #333; padding-bottom: 10px; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                th, td {{ padding: 10px; border: 1px solid #ddd; }}
                th {{ background-color: #f5f5f5; }}
            </style>
        </head>
        <body>
            <h1>Aktiebok</h1>
            <p><strong>{company.name}</strong></p>
            <p>Org.nr: {company.org_number}</p>

            <table>
                <tr>
                    <th>Aktienummer</th>
                    <th>Ägare</th>
                    <th>Personnr/Orgnr</th>
                    <th>Antal aktier</th>
                    <th>Förvärvsdag</th>
                </tr>
        """

        total_shares = 0
        for sh in shareholders:
            html += f"""
                <tr>
                    <td>{sh.get('share_numbers', '-')}</td>
                    <td>{sh.get('name', '')}</td>
                    <td>{sh.get('id_number', '')}</td>
                    <td>{sh.get('num_shares', 0)}</td>
                    <td>{sh.get('acquisition_date', '')}</td>
                </tr>
            """
            total_shares += sh.get('num_shares', 0)

        html += f"""
                <tr>
                    <td colspan="3"><strong>Totalt</strong></td>
                    <td><strong>{total_shares}</strong></td>
                    <td></td>
                </tr>
            </table>
            <p>Genererad: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        </body>
        </html>
        """

        return html

    def _generate_simple_report(
        self,
        title: str,
        company: Company,
        fiscal_year: FiscalYear,
        data: Dict
    ) -> str:
        """Generera enkel rapport"""
        html = f"""
        <!DOCTYPE html>
        <html lang="sv">
        <head>
            <meta charset="UTF-8">
            <title>{title} - {company.name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                h1 {{ border-bottom: 2px solid #333; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
                .amount {{ text-align: right; }}
            </style>
        </head>
        <body>
            <h1>{title}</h1>
            <p>{company.name} | {fiscal_year.start_date} - {fiscal_year.end_date}</p>
            <pre>{data}</pre>
        </body>
        </html>
        """
        return html

    def create_default_templates(self):
        """Skapa standardmallar i templates-mappen"""
        # Skapa mappstruktur
        for folder in ['arsredovisning', 'rapporter', 'protokoll', 'register']:
            (self.TEMPLATE_DIR / folder).mkdir(parents=True, exist_ok=True)

        # Skapa README
        readme_path = self.TEMPLATE_DIR / "README.md"
        if not readme_path.exists():
            readme_path.write_text("""# Dokumentmallar

Denna mapp innehåller Jinja2-mallar för generering av rapporter och dokument.

## Mappstruktur

- `arsredovisning/` - Mallar för årsredovisning (K2/K3)
- `rapporter/` - Finansiella rapporter
- `protokoll/` - Mötes- och styrelseprotokoll
- `register/` - Aktiebok och andra register

## Använda variabler

### Företagsdata
- `{{ company.name }}` - Företagsnamn
- `{{ company.org_number }}` - Organisationsnummer
- `{{ company.logo_base64 }}` - Logotyp som base64 (för <img>)

### Räkenskapsår
- `{{ fiscal_year.start_date }}` - Startdatum
- `{{ fiscal_year.end_date }}` - Slutdatum

### Finansiell data
- `{{ income_statement }}` - Resultaträkningsdata
- `{{ balance_sheet }}` - Balansräkningsdata
- `{{ trial_balance }}` - Råbalans

### Filter
- `{{ value|currency }}` - Formaterar som valuta
- `{{ date|date_format }}` - Formaterar datum

## Exempel

```html
<h1>Årsredovisning {{ company.name }}</h1>
<p>Org.nr: {{ company.org_number }}</p>
<p>Resultat: {{ result|currency }}</p>
```
""", encoding='utf-8')
