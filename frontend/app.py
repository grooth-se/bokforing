"""
Bokföringssystem - Streamlit Huvudapp
"""
import streamlit as st
from pathlib import Path
import sys

# Lägg till projektrot i path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.base import engine, Base, SessionLocal
from app.services.accounting import AccountingService
from app.services.sie_import import SIEImporter

# Skapa databastabeller
Base.metadata.create_all(bind=engine)

st.set_page_config(
    page_title="Bokföring",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Session state för valt företag
if "selected_company_id" not in st.session_state:
    st.session_state.selected_company_id = None


def get_db():
    """Hämta databassession"""
    db = SessionLocal()
    try:
        return db
    finally:
        pass  # Stängs manuellt


def main():
    st.sidebar.title("📊 Bokföring")

    db = get_db()
    service = AccountingService(db)

    # Företagsväljare
    companies = service.get_all_companies()

    if companies:
        company_options = {c.name: c.id for c in companies}
        selected_name = st.sidebar.selectbox(
            "Välj företag",
            options=list(company_options.keys())
        )
        st.session_state.selected_company_id = company_options[selected_name]
    else:
        st.sidebar.warning("Inga företag finns. Skapa ett nedan.")
        st.session_state.selected_company_id = None

    st.sidebar.divider()

    # Navigation
    page = st.sidebar.radio(
        "Navigation",
        ["Dashboard", "Transaktioner", "Kontoplan", "Rapporter", "SIE-import", "Inställningar"]
    )

    st.sidebar.divider()

    # Snabbåtgärder
    with st.sidebar.expander("➕ Nytt företag"):
        with st.form("new_company"):
            name = st.text_input("Företagsnamn")
            org_nr = st.text_input("Organisationsnummer", placeholder="XXXXXX-XXXX")
            standard = st.selectbox("Redovisningsstandard", ["K2", "K3"])

            if st.form_submit_button("Skapa"):
                if name and org_nr:
                    try:
                        company = service.create_company(
                            name=name,
                            org_number=org_nr,
                            accounting_standard=standard
                        )
                        service.load_bas_accounts(company.id)
                        st.success(f"Företaget '{name}' skapat!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fel: {e}")
                else:
                    st.error("Fyll i alla fält")

    # Sidinnehåll
    if page == "Dashboard":
        show_dashboard(service)
    elif page == "Transaktioner":
        show_transactions(service)
    elif page == "Kontoplan":
        show_accounts(service)
    elif page == "Rapporter":
        show_reports(service)
    elif page == "SIE-import":
        show_sie_import(db)
    elif page == "Inställningar":
        show_settings(service)

    db.close()


def show_dashboard(service: AccountingService):
    """Visa dashboard med KPI:er"""
    st.title("Dashboard")

    company_id = st.session_state.selected_company_id
    if not company_id:
        st.info("Välj eller skapa ett företag för att komma igång.")
        return

    company = service.get_company(company_id)
    st.header(f"📈 {company.name}")

    # KPI-kort
    col1, col2, col3, col4 = st.columns(4)

    fiscal_year = service.get_current_fiscal_year(company_id)

    if fiscal_year:
        transactions = service.get_transactions(company_id, fiscal_year.id)

        # Beräkna totaler
        total_transactions = len(transactions)

        # Hämta saldon för några nyckelkonton
        accounts = service.get_accounts(company_id)

        # Bank (1930)
        bank_account = next((a for a in accounts if a.number == "1930"), None)
        bank_balance = service.get_account_balance(bank_account.id) if bank_account else 0

        # Kundfordringar (1510)
        customer_account = next((a for a in accounts if a.number == "1510"), None)
        customer_balance = service.get_account_balance(customer_account.id) if customer_account else 0

        # Leverantörsskulder (2410)
        supplier_account = next((a for a in accounts if a.number == "2410"), None)
        supplier_balance = service.get_account_balance(supplier_account.id) if supplier_account else 0

        with col1:
            st.metric("Banksaldo", f"{bank_balance:,.0f} kr")
        with col2:
            st.metric("Kundfordringar", f"{customer_balance:,.0f} kr")
        with col3:
            st.metric("Leverantörsskulder", f"{supplier_balance:,.0f} kr")
        with col4:
            st.metric("Verifikationer", total_transactions)

        st.divider()

        # Senaste transaktioner
        st.subheader("Senaste transaktioner")
        if transactions:
            for tx in transactions[-5:]:
                with st.expander(f"Ver {tx.verification_number}: {tx.description} ({tx.transaction_date})"):
                    for line in tx.lines:
                        if line.debit > 0:
                            st.write(f"  {line.account.number} {line.account.name}: {line.debit:,.2f} D")
                        else:
                            st.write(f"  {line.account.number} {line.account.name}: {line.credit:,.2f} K")
        else:
            st.info("Inga transaktioner ännu")
    else:
        st.warning("Inget räkenskapsår finns. Skapa ett under Inställningar.")


def show_transactions(service: AccountingService):
    """Visa och skapa transaktioner"""
    st.title("Transaktioner")

    company_id = st.session_state.selected_company_id
    if not company_id:
        st.info("Välj ett företag först.")
        return

    fiscal_year = service.get_current_fiscal_year(company_id)
    if not fiscal_year:
        st.warning("Skapa ett räkenskapsår först under Inställningar.")
        return

    tab1, tab2 = st.tabs(["Visa transaktioner", "Ny transaktion"])

    with tab1:
        transactions = service.get_transactions(company_id, fiscal_year.id)

        if transactions:
            for tx in reversed(transactions):
                with st.expander(f"Ver {tx.verification_number}: {tx.description} ({tx.transaction_date})"):
                    st.write(f"**Datum:** {tx.transaction_date}")
                    st.write(f"**Beskrivning:** {tx.description}")
                    st.write("**Konteringar:**")

                    for line in tx.lines:
                        debit_str = f"{line.debit:,.2f}" if line.debit > 0 else ""
                        credit_str = f"{line.credit:,.2f}" if line.credit > 0 else ""
                        st.write(f"  {line.account.number} {line.account.name}: D {debit_str} / K {credit_str}")
        else:
            st.info("Inga transaktioner ännu")

    with tab2:
        st.subheader("Skapa ny transaktion")

        accounts = service.get_accounts(company_id)
        account_options = {f"{a.number} - {a.name}": a.id for a in accounts}

        with st.form("new_transaction"):
            date = st.date_input("Datum")
            description = st.text_input("Beskrivning")

            st.write("**Konteringsrader:**")

            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

            lines = []
            for i in range(4):
                with col1:
                    account = st.selectbox(f"Konto {i+1}", [""] + list(account_options.keys()), key=f"acc_{i}")
                with col2:
                    debit = st.number_input(f"Debet {i+1}", min_value=0.0, step=100.0, key=f"deb_{i}")
                with col3:
                    credit = st.number_input(f"Kredit {i+1}", min_value=0.0, step=100.0, key=f"cred_{i}")

                if account and (debit > 0 or credit > 0):
                    lines.append({
                        "account_id": account_options[account],
                        "debit": debit,
                        "credit": credit
                    })

            if st.form_submit_button("Spara transaktion"):
                if description and len(lines) >= 2:
                    try:
                        tx = service.create_transaction(
                            company_id=company_id,
                            fiscal_year_id=fiscal_year.id,
                            transaction_date=date,
                            description=description,
                            lines=lines
                        )
                        st.success(f"Transaktion {tx.verification_number} skapad!")
                        st.rerun()
                    except ValueError as e:
                        st.error(f"Valideringsfel: {e}")
                    except Exception as e:
                        st.error(f"Fel: {e}")
                else:
                    st.error("Fyll i beskrivning och minst 2 konteringsrader")


def show_accounts(service: AccountingService):
    """Visa kontoplan"""
    st.title("Kontoplan")

    company_id = st.session_state.selected_company_id
    if not company_id:
        st.info("Välj ett företag först.")
        return

    accounts = service.get_accounts(company_id)

    if not accounts:
        if st.button("Ladda BAS-kontoplan"):
            service.load_bas_accounts(company_id)
            st.success("BAS-kontoplan laddad!")
            st.rerun()
        return

    # Gruppera per kontoklass
    classes = {}
    for acc in accounts:
        cls = acc.account_class
        if cls not in classes:
            classes[cls] = []
        classes[cls].append(acc)

    class_names = {
        1: "Tillgångar",
        2: "Eget kapital och skulder",
        3: "Intäkter",
        4: "Kostnader för varor",
        5: "Övriga externa kostnader",
        6: "Övriga externa kostnader",
        7: "Personalkostnader",
        8: "Finansiella poster"
    }

    for cls in sorted(classes.keys()):
        with st.expander(f"Klass {cls}: {class_names.get(cls, 'Övrigt')} ({len(classes[cls])} konton)"):
            for acc in classes[cls]:
                balance = service.get_account_balance(acc.id)
                balance_str = f"{balance:,.2f} kr" if balance != 0 else "-"
                st.write(f"**{acc.number}** {acc.name} | Saldo: {balance_str}")


def show_reports(service: AccountingService):
    """Visa rapporter"""
    st.title("Rapporter")

    company_id = st.session_state.selected_company_id
    if not company_id:
        st.info("Välj ett företag först.")
        return

    report_type = st.selectbox(
        "Välj rapport",
        ["Råbalans", "Balansräkning", "Resultaträkning", "Huvudbok"]
    )

    if report_type == "Råbalans":
        show_trial_balance(service, company_id)
    elif report_type == "Balansräkning":
        show_balance_sheet(service, company_id)
    elif report_type == "Resultaträkning":
        show_income_statement(service, company_id)
    else:
        st.info("Huvudbok kommer snart...")


def show_trial_balance(service: AccountingService, company_id: int):
    """Visa råbalans"""
    st.subheader("Råbalans")

    balances = service.get_trial_balance(company_id)

    if not balances:
        st.info("Inga saldon att visa")
        return

    total_debit = sum(b["debit"] for b in balances)
    total_credit = sum(b["credit"] for b in balances)

    # Tabell
    st.write("| Konto | Namn | Debet | Kredit |")
    st.write("|-------|------|------:|-------:|")

    for b in balances:
        debit = f"{b['debit']:,.2f}" if b['debit'] > 0 else ""
        credit = f"{b['credit']:,.2f}" if b['credit'] > 0 else ""
        st.write(f"| {b['account_number']} | {b['account_name']} | {debit} | {credit} |")

    st.write(f"| **Summa** | | **{total_debit:,.2f}** | **{total_credit:,.2f}** |")

    if total_debit == total_credit:
        st.success("✓ Balanserar")
    else:
        st.error(f"✗ Balanserar inte! Differens: {total_debit - total_credit:,.2f}")


def show_balance_sheet(service: AccountingService, company_id: int):
    """Visa balansräkning"""
    st.subheader("Balansräkning")

    accounts = service.get_accounts(company_id)

    # Tillgångar (klass 1)
    st.write("### TILLGÅNGAR")
    assets_total = 0
    for acc in accounts:
        if acc.number.startswith("1"):
            balance = service.get_account_balance(acc.id)
            if balance != 0:
                st.write(f"{acc.number} {acc.name}: {balance:,.2f} kr")
                assets_total += balance
    st.write(f"**Summa tillgångar: {assets_total:,.2f} kr**")

    st.divider()

    # Eget kapital och skulder (klass 2)
    st.write("### EGET KAPITAL OCH SKULDER")
    liabilities_total = 0
    for acc in accounts:
        if acc.number.startswith("2"):
            balance = service.get_account_balance(acc.id)
            if balance != 0:
                st.write(f"{acc.number} {acc.name}: {balance:,.2f} kr")
                liabilities_total += balance
    st.write(f"**Summa eget kapital och skulder: {liabilities_total:,.2f} kr**")


def show_income_statement(service: AccountingService, company_id: int):
    """Visa resultaträkning"""
    st.subheader("Resultaträkning")

    accounts = service.get_accounts(company_id)

    # Intäkter (klass 3)
    st.write("### INTÄKTER")
    revenue_total = 0
    for acc in accounts:
        if acc.number.startswith("3"):
            balance = service.get_account_balance(acc.id)
            if balance != 0:
                st.write(f"{acc.number} {acc.name}: {balance:,.2f} kr")
                revenue_total += balance
    st.write(f"**Summa intäkter: {revenue_total:,.2f} kr**")

    st.divider()

    # Kostnader (klass 4-8)
    st.write("### KOSTNADER")
    expense_total = 0
    for acc in accounts:
        first_digit = acc.number[0] if acc.number else ""
        if first_digit in ["4", "5", "6", "7", "8"]:
            balance = service.get_account_balance(acc.id)
            if balance != 0:
                st.write(f"{acc.number} {acc.name}: {balance:,.2f} kr")
                expense_total += balance
    st.write(f"**Summa kostnader: {expense_total:,.2f} kr**")

    st.divider()

    result = revenue_total - expense_total
    st.write(f"### ÅRETS RESULTAT: {result:,.2f} kr")


def show_settings(service: AccountingService):
    """Visa inställningar"""
    st.title("Inställningar")

    company_id = st.session_state.selected_company_id
    if not company_id:
        st.info("Välj ett företag först.")
        return

    company = service.get_company(company_id)

    st.subheader(f"Företag: {company.name}")
    st.write(f"**Organisationsnummer:** {company.org_number}")
    st.write(f"**Redovisningsstandard:** {company.accounting_standard.value}")

    st.divider()

    # Räkenskapsår
    st.subheader("Räkenskapsår")

    fiscal_years = service.get_fiscal_years(company_id)

    if fiscal_years:
        for fy in fiscal_years:
            status = "🔒 Stängt" if fy.is_closed else "✓ Aktivt"
            st.write(f"**{fy.start_date} - {fy.end_date}** {status}")
    else:
        st.info("Inga räkenskapsår")

    with st.form("new_fiscal_year"):
        st.write("**Skapa nytt räkenskapsår**")
        from datetime import date
        start = st.date_input("Startdatum", value=date(date.today().year, 1, 1))
        end = st.date_input("Slutdatum", value=date(date.today().year, 12, 31))

        if st.form_submit_button("Skapa räkenskapsår"):
            try:
                fy = service.create_fiscal_year(company_id, start, end)
                st.success(f"Räkenskapsår {start} - {end} skapat!")
                st.rerun()
            except Exception as e:
                st.error(f"Fel: {e}")


def show_sie_import(db):
    """Visa SIE-import"""
    st.title("SIE-import")

    st.write("""
    Importera bokföringsdata från SIE-filer (Standard Import Export).
    SIE är ett svenskt standardformat som används av de flesta bokföringsprogram
    som Fortnox, Visma, Speedledger m.fl.
    """)

    company_id = st.session_state.selected_company_id

    tab1, tab2 = st.tabs(["Importera till befintligt företag", "Skapa nytt företag"])

    with tab1:
        if not company_id:
            st.warning("Välj ett företag först för att importera till det.")
        else:
            uploaded_file = st.file_uploader(
                "Välj SIE-fil",
                type=['se', 'si', 'sie'],
                key="sie_existing"
            )

            if uploaded_file:
                if st.button("Importera", key="import_existing"):
                    try:
                        content = uploaded_file.read().decode('cp437', errors='replace')
                        importer = SIEImporter(db)
                        stats = importer.import_file(content, company_id=company_id)

                        st.success("Import klar!")
                        st.write(f"- Konton importerade: {stats['accounts_imported']}")
                        st.write(f"- Transaktioner importerade: {stats['transactions_imported']}")

                        if stats['errors']:
                            st.warning("Varningar:")
                            for error in stats['errors']:
                                st.write(f"  - {error}")

                        st.rerun()

                    except Exception as e:
                        st.error(f"Importfel: {e}")

    with tab2:
        st.write("Skapa ett nytt företag baserat på SIE-filens innehåll.")

        uploaded_file = st.file_uploader(
            "Välj SIE-fil",
            type=['se', 'si', 'sie'],
            key="sie_new"
        )

        if uploaded_file:
            if st.button("Importera som nytt företag", key="import_new"):
                try:
                    content = uploaded_file.read().decode('cp437', errors='replace')
                    importer = SIEImporter(db)
                    stats = importer.import_file(content, company_id=None)

                    st.success("Import klar! Nytt företag skapat.")
                    st.write(f"- Konton importerade: {stats['accounts_imported']}")
                    st.write(f"- Transaktioner importerade: {stats['transactions_imported']}")

                    if stats['errors']:
                        st.warning("Varningar:")
                        for error in stats['errors']:
                            st.write(f"  - {error}")

                    st.rerun()

                except Exception as e:
                    st.error(f"Importfel: {e}")

    st.divider()

    # Information om SIE-format
    with st.expander("Om SIE-formatet"):
        st.write("""
        **SIE (Standard Import Export)** är ett svenskt standardformat för
        överföring av bokföringsdata mellan olika system.

        **Versioner som stöds:**
        - SIE4 (komplett bokföring med verifikationer)

        **Innehåll som importeras:**
        - Företagsinformation (namn, organisationsnummer)
        - Kontoplan
        - Räkenskapsår
        - Ingående balanser
        - Verifikationer med konteringsrader

        **Exportera från andra system:**
        - Fortnox: Inställningar > Importera/Exportera > Exportera SIE-fil
        - Visma: Administration > Import/Export > SIE-export
        - Speedledger: Inställningar > Export > SIE4
        """)


if __name__ == "__main__":
    main()
