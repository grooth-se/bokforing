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
from app.services.document_processor import DocumentProcessor, suggest_accounts

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
        ["Dashboard", "Skanna dokument", "Transaktioner", "Kontoplan", "Rapporter", "SIE-import", "Inställningar"]
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
    elif page == "Skanna dokument":
        show_document_scanner(service, db)
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

    # Använd aktivt räkenskapsår (nuvarande eller senaste)
    fiscal_year = service.get_active_fiscal_year(company_id)

    if fiscal_year:
        st.caption(f"Räkenskapsår: {fiscal_year.start_date} - {fiscal_year.end_date}")
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

    # Hämta alla räkenskapsår för företaget
    fiscal_years = service.get_fiscal_years(company_id)
    if not fiscal_years:
        st.warning("Skapa ett räkenskapsår först under Inställningar.")
        return

    # Välj räkenskapsår (visa senaste som standard)
    fiscal_year_options = {
        f"{fy.start_date} - {fy.end_date}": fy for fy in fiscal_years
    }
    selected_fy_name = st.selectbox(
        "Räkenskapsår",
        options=list(fiscal_year_options.keys()),
        index=0
    )
    fiscal_year = fiscal_year_options[selected_fy_name]

    # Visa sammanfattning
    transaction_count = service.get_transaction_count(company_id, fiscal_year.id)
    next_ver = service.get_next_verification_number(company_id, fiscal_year.id)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Antal transaktioner", transaction_count)
    with col2:
        st.metric("Nästa verifikationsnummer", next_ver)
    with col3:
        st.metric("Räkenskapsår", f"{fiscal_year.start_date.year}")

    st.divider()

    tab1, tab2 = st.tabs(["Visa transaktioner", "Ny transaktion"])

    with tab1:
        transactions = service.get_transactions(company_id, fiscal_year.id)

        if transactions:
            st.write(f"Visar {len(transactions)} transaktioner")
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
            st.info("Inga transaktioner ännu för detta räkenskapsår")

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
        ["Verifikationslista", "Råbalans", "Balansräkning", "Resultaträkning", "Huvudbok"]
    )

    if report_type == "Verifikationslista":
        show_verification_list(service, company_id)
    elif report_type == "Råbalans":
        show_trial_balance(service, company_id)
    elif report_type == "Balansräkning":
        show_balance_sheet(service, company_id)
    elif report_type == "Resultaträkning":
        show_income_statement(service, company_id)
    else:
        st.info("Huvudbok kommer snart...")


def show_verification_list(service: AccountingService, company_id: int):
    """Visa verifikationslista med filter"""
    st.subheader("Verifikationslista")

    # Hämta räkenskapsår
    fiscal_years = service.get_fiscal_years(company_id)
    if not fiscal_years:
        st.warning("Inga räkenskapsår finns")
        return

    # Välj räkenskapsår
    fiscal_year_options = {
        f"{fy.start_date} - {fy.end_date}": fy for fy in fiscal_years
    }
    selected_fy_name = st.selectbox(
        "Räkenskapsår",
        options=list(fiscal_year_options.keys()),
        index=0,
        key="ver_list_fy"
    )
    fiscal_year = fiscal_year_options[selected_fy_name]

    # Filterval
    filter_type = st.radio(
        "Filtrera på:",
        ["Datum", "Verifikationsnummer"],
        horizontal=True
    )

    col1, col2 = st.columns(2)

    start_date = None
    end_date = None
    ver_from = None
    ver_to = None

    if filter_type == "Datum":
        with col1:
            start_date = st.date_input(
                "Från datum",
                value=fiscal_year.start_date,
                key="ver_start_date"
            )
        with col2:
            end_date = st.date_input(
                "Till datum",
                value=fiscal_year.end_date,
                key="ver_end_date"
            )
    else:
        # Hämta min/max verifikationsnummer
        transactions = service.get_transactions(company_id, fiscal_year.id)
        if transactions:
            min_ver = min(t.verification_number for t in transactions)
            max_ver = max(t.verification_number for t in transactions)
        else:
            min_ver, max_ver = 1, 1

        with col1:
            ver_from = st.number_input(
                "Från verifikation",
                min_value=min_ver,
                max_value=max_ver,
                value=min_ver,
                key="ver_from"
            )
        with col2:
            ver_to = st.number_input(
                "Till verifikation",
                min_value=min_ver,
                max_value=max_ver,
                value=max_ver,
                key="ver_to"
            )

    st.divider()

    # Hämta transaktioner med filter
    transactions = service.get_transactions(
        company_id,
        fiscal_year.id,
        start_date=start_date,
        end_date=end_date,
        ver_from=ver_from,
        ver_to=ver_to
    )

    if not transactions:
        st.info("Inga verifikationer matchar filtret")
        return

    st.write(f"**{len(transactions)} verifikationer**")

    # Visa verifikationslista
    for tx in transactions:
        st.markdown(f"### Verifikation {tx.verification_number}")
        st.write(f"**Datum:** {tx.transaction_date} | **Beskrivning:** {tx.description}")

        # Konteringsrader som tabell
        st.write("| Konto | Kontonamn | Debet | Kredit |")
        st.write("|-------|-----------|------:|-------:|")

        total_debit = 0
        total_credit = 0
        for line in tx.lines:
            debit_str = f"{line.debit:,.2f}" if line.debit > 0 else ""
            credit_str = f"{line.credit:,.2f}" if line.credit > 0 else ""
            st.write(f"| {line.account.number} | {line.account.name} | {debit_str} | {credit_str} |")
            total_debit += float(line.debit)
            total_credit += float(line.credit)

        st.write(f"| **Summa** | | **{total_debit:,.2f}** | **{total_credit:,.2f}** |")

        # Visa bifogat verifikat om det finns
        if hasattr(tx, 'vouchers') and tx.vouchers:
            st.write("**Bifogade verifikat:**")
            for voucher in tx.vouchers:
                if voucher.file_path:
                    from pathlib import Path
                    voucher_path = Path(voucher.file_path)
                    if voucher_path.exists():
                        if voucher_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif']:
                            st.image(str(voucher_path), caption=voucher_path.name, width=400)
                        elif voucher_path.suffix.lower() == '.pdf':
                            st.write(f"📄 PDF: {voucher_path.name}")
                            with open(voucher_path, "rb") as f:
                                st.download_button(
                                    "Ladda ner PDF",
                                    f.read(),
                                    file_name=voucher_path.name,
                                    mime="application/pdf"
                                )
                        else:
                            st.write(f"📎 {voucher_path.name}")

        st.divider()


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


def show_document_scanner(service: AccountingService, db):
    """Skanna dokument och skapa transaktioner automatiskt"""
    st.title("Skanna dokument")

    company_id = st.session_state.selected_company_id
    if not company_id:
        st.info("Välj ett företag först.")
        return

    fiscal_years = service.get_fiscal_years(company_id)
    if not fiscal_years:
        st.warning("Skapa ett räkenskapsår först under Inställningar.")
        return

    fiscal_year = fiscal_years[0]

    st.write("""
    Ladda upp kvitton, fakturor eller andra dokument.
    Systemet extraherar automatiskt datum, belopp och leverantör
    och föreslår en bokföringstransaktion.
    """)

    # Filuppladdning
    uploaded_file = st.file_uploader(
        "Välj dokument",
        type=['pdf', 'jpg', 'jpeg', 'png', 'webp'],
        help="Stödjer PDF, JPG, PNG och WEBP"
    )

    if uploaded_file:
        col1, col2 = st.columns([1, 1])

        with col1:
            st.subheader("Dokument")
            # Visa förhandsgranskning för bilder
            if uploaded_file.type.startswith('image/'):
                st.image(uploaded_file, use_container_width=True)
            else:
                st.info(f"PDF: {uploaded_file.name}")

        with col2:
            st.subheader("Extraherad data")

            # Bearbeta dokument
            try:
                processor = DocumentProcessor()
                file_content = uploaded_file.read()
                uploaded_file.seek(0)  # Reset för eventuell senare användning

                with st.spinner("Analyserar dokument..."):
                    extracted = processor.process_file(file_content, uploaded_file.name)

                # Visa extraherad data
                if extracted.raw_text:
                    confidence_pct = int(extracted.confidence * 100)
                    st.progress(extracted.confidence, text=f"Konfidens: {confidence_pct}%")

                    # Formulär för att justera och spara
                    with st.form("transaction_form"):
                        st.write("**Justera och spara transaktion**")

                        # Datum
                        from datetime import date as date_type
                        tx_date = st.date_input(
                            "Datum",
                            value=extracted.date or date_type.today()
                        )

                        # Leverantör/beskrivning
                        description = st.text_input(
                            "Beskrivning",
                            value=extracted.description or ""
                        )

                        # Belopp
                        total = st.number_input(
                            "Totalbelopp (inkl moms)",
                            value=float(extracted.total_amount or 0),
                            min_value=0.0,
                            step=10.0
                        )

                        # Moms
                        vat_rate = st.selectbox(
                            "Momssats",
                            options=[25, 12, 6, 0],
                            index=0 if not extracted.vat_rate else [25, 12, 6, 0].index(extracted.vat_rate)
                        )

                        # Kontoförslag
                        suggestions = suggest_accounts(extracted)

                        st.write(f"**Kategori:** {suggestions['category']}")

                        # Hämta konton för dropdown
                        accounts = service.get_accounts(company_id)
                        account_options = {f"{a.number} - {a.name}": a.id for a in accounts}
                        account_list = list(account_options.keys())

                        # Hitta förvalda konton
                        expense_default = next(
                            (a for a in account_list if a.startswith(suggestions['expense_account'])),
                            account_list[0] if account_list else None
                        )
                        payment_default = next(
                            (a for a in account_list if a.startswith(suggestions['payment_account'])),
                            account_list[0] if account_list else None
                        )

                        expense_account = st.selectbox(
                            "Kostnadskonto",
                            options=account_list,
                            index=account_list.index(expense_default) if expense_default in account_list else 0
                        )

                        payment_account = st.selectbox(
                            "Betalkonto",
                            options=account_list,
                            index=account_list.index(payment_default) if payment_default in account_list else 0
                        )

                        # Spara-knapp
                        if st.form_submit_button("Skapa transaktion", type="primary"):
                            if total > 0 and description:
                                try:
                                    from decimal import Decimal

                                    # Beräkna belopp
                                    total_dec = Decimal(str(total))
                                    if vat_rate > 0:
                                        vat_amount = total_dec * Decimal(vat_rate) / Decimal(100 + vat_rate)
                                        net_amount = total_dec - vat_amount
                                    else:
                                        vat_amount = Decimal(0)
                                        net_amount = total_dec

                                    # Bygg transaktionsrader
                                    lines = [
                                        {
                                            "account_id": account_options[expense_account],
                                            "debit": net_amount.quantize(Decimal('0.01')),
                                            "credit": Decimal(0)
                                        },
                                        {
                                            "account_id": account_options[payment_account],
                                            "debit": Decimal(0),
                                            "credit": total_dec.quantize(Decimal('0.01'))
                                        }
                                    ]

                                    # Lägg till moms om tillämpligt
                                    if vat_rate > 0:
                                        vat_account = next(
                                            (a for a in accounts if a.number == "1610"),
                                            None
                                        )
                                        if vat_account:
                                            lines.insert(1, {
                                                "account_id": vat_account.id,
                                                "debit": vat_amount.quantize(Decimal('0.01')),
                                                "credit": Decimal(0)
                                            })

                                    # Skapa transaktion
                                    tx = service.create_transaction(
                                        company_id=company_id,
                                        fiscal_year_id=fiscal_year.id,
                                        transaction_date=tx_date,
                                        description=description,
                                        lines=lines
                                    )

                                    # Spara verifikat
                                    voucher_path = processor.save_voucher(file_content, uploaded_file.name)

                                    st.success(f"Transaktion {tx.verification_number} skapad!")
                                    st.info(f"Verifikat sparat: {voucher_path}")
                                    st.rerun()

                                except Exception as e:
                                    st.error(f"Fel vid skapande: {e}")
                            else:
                                st.error("Fyll i belopp och beskrivning")

                    # Visa råtext
                    with st.expander("Visa extraherad text"):
                        st.text(extracted.raw_text[:2000] if len(extracted.raw_text) > 2000 else extracted.raw_text)

                else:
                    st.warning("Kunde inte extrahera text från dokumentet. Kontrollera att det är läsbart.")

            except Exception as e:
                st.error(f"Fel vid dokumentbearbetning: {e}")

    st.divider()

    # Information
    with st.expander("Om dokumentskanning"):
        st.write("""
        **Funktioner:**
        - OCR (optisk teckenigenkänning) för bilder och skannade PDF:er
        - Automatisk extraktion av datum, belopp och moms
        - Identifiering av vanliga leverantörer
        - Förslag på bokföringskonton baserat på leverantör

        **Tips för bästa resultat:**
        - Använd tydliga, välbelysta bilder
        - Se till att texten är läsbar och inte suddig
        - PDF:er med inbäddad text ger bäst resultat

        **Systemkrav:**
        - Tesseract OCR måste vara installerat för bildskanning
        - Installera med: `brew install tesseract tesseract-lang`
        """)


def show_sie_import(db):
    """Visa SIE-import"""
    from app.services.sie_import import SIEParser
    from app.services.accounting import AccountingService

    st.title("SIE-import")

    st.write("""
    Importera bokföringsdata från SIE-filer. Ladda upp en fil för att
    förhandsgranska innehållet innan import.
    """)

    # Filuppladdning
    uploaded_file = st.file_uploader(
        "Välj SIE-fil (.se, .si, .sie)",
        type=['se', 'si', 'sie'],
        key="sie_upload"
    )

    if uploaded_file:
        try:
            # Läs och parsa filen
            content = uploaded_file.read().decode('cp437', errors='replace')
            parser = SIEParser()
            data = parser.parse(content)

            st.success(f"Fil laddad: {uploaded_file.name}")

            # Visa förhandsgranskning
            st.subheader("Förhandsgranskning")

            col1, col2 = st.columns(2)

            with col1:
                st.write("**Företagsinformation från filen:**")
                st.write(f"- Namn: {data.company_name or '(ej angivet)'}")
                st.write(f"- Org.nr: {data.org_number or '(ej angivet)'}")
                if data.fiscal_year_start and data.fiscal_year_end:
                    st.write(f"- Räkenskapsår: {data.fiscal_year_start} - {data.fiscal_year_end}")

            with col2:
                st.write("**Innehåll:**")
                st.write(f"- Konton: {len(data.accounts)}")
                st.write(f"- Ingående balanser: {len(data.opening_balances)}")
                st.write(f"- Transaktioner: {len(data.transactions)}")

            st.divider()

            # Importalternativ
            st.subheader("Importalternativ")

            service = AccountingService(db)
            companies = service.get_all_companies()

            # Val: nytt eller befintligt företag
            import_option = st.radio(
                "Välj importmetod:",
                ["Skapa nytt företag från SIE-filen", "Importera till befintligt företag"],
                index=0
            )

            if import_option == "Skapa nytt företag från SIE-filen":
                # Analysera transaktionsdatum för att föreslå räkenskapsår
                from datetime import date as date_type

                transaction_dates = [tx.date for tx in data.transactions if tx.date]

                if transaction_dates:
                    min_date = min(transaction_dates)
                    max_date = max(transaction_dates)

                    # Föreslå räkenskapsår baserat på transaktioner
                    suggested_start = date_type(min_date.year, 1, 1)
                    suggested_end = date_type(min_date.year, 12, 31)

                    st.info(f"""
                    **Analys av transaktioner:**
                    - Antal transaktioner: {len(data.transactions)}
                    - Tidigaste transaktion: {min_date}
                    - Senaste transaktion: {max_date}
                    - **Föreslaget räkenskapsår: {suggested_start} - {suggested_end}**
                    """)
                else:
                    suggested_start = data.fiscal_year_start or date_type(date_type.today().year, 1, 1)
                    suggested_end = data.fiscal_year_end or date_type(date_type.today().year, 12, 31)

                # Om SIE-filen har räkenskapsår, visa det också
                if data.fiscal_year_start and data.fiscal_year_end:
                    if data.fiscal_year_start != suggested_start or data.fiscal_year_end != suggested_end:
                        st.write(f"*Räkenskapsår från filen: {data.fiscal_year_start} - {data.fiscal_year_end}*")

                st.divider()

                # Bekräftelsefråga
                st.subheader("Vill du skapa detta företag?")

                with st.form("new_company_import"):
                    st.write("**Företagsinformation:**")

                    col1, col2 = st.columns(2)
                    with col1:
                        company_name = st.text_input(
                            "Företagsnamn",
                            value=data.company_name or "Nytt företag"
                        )
                        accounting_standard = st.selectbox(
                            "Redovisningsstandard",
                            ["K2", "K3"],
                            index=0,
                            help="K2 för mindre företag, K3 för större"
                        )
                    with col2:
                        org_number = st.text_input(
                            "Organisationsnummer",
                            value=data.org_number or "000000-0000"
                        )

                    st.write("**Räkenskapsår:**")

                    # Använd föreslaget räkenskapsår som standard
                    col_start, col_end = st.columns(2)
                    with col_start:
                        fy_start = st.date_input("Startdatum", value=suggested_start)
                    with col_end:
                        fy_end = st.date_input("Slutdatum", value=suggested_end)

                    st.divider()

                    st.write("**Sammanfattning av import:**")
                    st.write(f"- {len(data.accounts)} konton kommer importeras")
                    st.write(f"- {len(data.opening_balances)} ingående balanser")
                    st.write(f"- {len(data.transactions)} transaktioner")

                    if st.form_submit_button("✓ Ja, skapa företag och importera", type="primary"):
                        try:
                            # Skapa företag manuellt
                            company = service.create_company(
                                name=company_name,
                                org_number=org_number,
                                accounting_standard=accounting_standard
                            )

                            # Skapa räkenskapsår
                            fiscal_year = service.create_fiscal_year(
                                company.id, fy_start, fy_end
                            )

                            # Importera data till företaget
                            importer = SIEImporter(db)
                            stats = importer.import_file(content, company_id=company.id)

                            st.success(f"Import klar! Företaget '{company_name}' skapat.")
                            st.write(f"- Konton importerade: {stats['accounts_imported']}")
                            st.write(f"- Transaktioner importerade: {stats['transactions_imported']}")

                            # Uppdatera valt företag
                            st.session_state.selected_company_id = company.id
                            st.rerun()

                        except Exception as e:
                            st.error(f"Importfel: {e}")

            else:  # Importera till befintligt företag
                if not companies:
                    st.warning("Inga företag finns. Välj 'Skapa nytt företag' ovan.")
                else:
                    with st.form("existing_company_import"):
                        company_options = {c.name: c.id for c in companies}
                        selected_company = st.selectbox(
                            "Välj företag",
                            options=list(company_options.keys())
                        )

                        st.warning(
                            "OBS: Befintliga transaktioner behålls. "
                            "Dubbletter kan uppstå om filen redan importerats."
                        )

                        if st.form_submit_button("Importera till valt företag", type="primary"):
                            try:
                                company_id = company_options[selected_company]
                                importer = SIEImporter(db)
                                stats = importer.import_file(content, company_id=company_id)

                                st.success(f"Import klar till '{selected_company}'!")
                                st.write(f"- Konton importerade: {stats['accounts_imported']}")
                                st.write(f"- Transaktioner importerade: {stats['transactions_imported']}")

                                st.session_state.selected_company_id = company_id
                                st.rerun()

                            except Exception as e:
                                st.error(f"Importfel: {e}")

            # Visa detaljer
            with st.expander("Visa konton i filen"):
                if data.accounts:
                    for acc in data.accounts[:50]:
                        st.write(f"  {acc.number}: {acc.name}")
                    if len(data.accounts) > 50:
                        st.write(f"  ... och {len(data.accounts) - 50} till")
                else:
                    st.write("Inga konton i filen")

            with st.expander("Visa transaktioner i filen"):
                if data.transactions:
                    for tx in data.transactions[:20]:
                        st.write(f"  Ver {tx.verification_number}: {tx.description} ({tx.date})")
                    if len(data.transactions) > 20:
                        st.write(f"  ... och {len(data.transactions) - 20} till")
                else:
                    st.write("Inga transaktioner i filen")

        except Exception as e:
            st.error(f"Kunde inte läsa filen: {e}")

    else:
        # Visa info när ingen fil är uppladdad
        st.info("Ladda upp en SIE-fil för att komma igång.")

        with st.expander("Om SIE-formatet"):
            st.write("""
            **SIE (Standard Import Export)** är ett svenskt standardformat för
            överföring av bokföringsdata mellan olika system.

            **Stödda filtyper:** .se, .si, .sie

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
