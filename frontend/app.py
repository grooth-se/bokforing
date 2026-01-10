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
from app.services.report_generator import ReportGenerator

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
        ["Dashboard", "Skanna dokument", "Transaktioner", "Kontoplan", "Tillgångar", "Rapporter", "Bokslut", "SIE-import", "Inställningar"]
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
    elif page == "Tillgångar":
        show_assets(service, db)
    elif page == "Rapporter":
        show_reports(service)
    elif page == "Bokslut":
        show_closing(service, db)
    elif page == "SIE-import":
        show_sie_import(db)
    elif page == "Inställningar":
        show_settings(service)

    db.close()


def show_dashboard(service: AccountingService):
    """Visa dashboard med KPI:er och diagram"""
    import plotly.graph_objects as go
    import plotly.express as px
    from datetime import datetime, timedelta
    from decimal import Decimal

    st.title("Dashboard")

    company_id = st.session_state.selected_company_id
    if not company_id:
        st.info("Välj eller skapa ett företag för att komma igång.")
        return

    company = service.get_company(company_id)
    st.header(f"📈 {company.name}")

    # Använd aktivt räkenskapsår (nuvarande eller senaste)
    fiscal_year = service.get_active_fiscal_year(company_id)

    if not fiscal_year:
        st.warning("Inget räkenskapsår finns. Skapa ett under Inställningar.")
        return

    st.caption(f"Räkenskapsår: {fiscal_year.start_date} - {fiscal_year.end_date}")

    # Hämta data
    transactions = service.get_transactions(company_id, fiscal_year.id)
    accounts = service.get_accounts(company_id)

    # Beräkna nyckeltal
    # Tillgångar (1xxx)
    total_assets = sum(
        service.get_account_balance(a.id)
        for a in accounts if a.number.startswith('1')
    )

    # Eget kapital (20xx-21xx)
    total_equity = sum(
        service.get_account_balance(a.id)
        for a in accounts if a.number.startswith(('20', '21'))
    )

    # Skulder (22xx-29xx)
    total_liabilities = sum(
        service.get_account_balance(a.id)
        for a in accounts if a.number.startswith(('22', '23', '24', '25', '26', '27', '28', '29'))
    )

    # Intäkter (3xxx)
    total_revenue = sum(
        service.get_account_balance(a.id)
        for a in accounts if a.number.startswith('3')
    )

    # Kostnader (4xxx-8xxx)
    total_expenses = sum(
        service.get_account_balance(a.id)
        for a in accounts if a.number[0] in '45678'
    )

    # Resultat
    result = total_revenue - total_expenses

    # Soliditet (Eget kapital / Totala tillgångar)
    soliditet = (float(total_equity) / float(total_assets) * 100) if total_assets != 0 else 0

    # Likviditet (Likvida medel / Kortfristiga skulder)
    liquid_assets = sum(
        service.get_account_balance(a.id)
        for a in accounts if a.number.startswith(('19', '17', '18'))  # Kassa, bank, kortfristiga placeringar
    )
    short_term_liabilities = sum(
        service.get_account_balance(a.id)
        for a in accounts if a.number.startswith(('24', '25', '26', '27', '28', '29'))
    )
    likviditet = (float(liquid_assets) / float(short_term_liabilities) * 100) if short_term_liabilities != 0 else 0

    # === KPI-KORT ===
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Tillgångar", f"{total_assets:,.0f} kr")
    with col2:
        st.metric("Eget kapital", f"{total_equity:,.0f} kr")
    with col3:
        delta_color = "normal" if result >= 0 else "inverse"
        st.metric("Resultat", f"{result:,.0f} kr", delta=f"{'Vinst' if result >= 0 else 'Förlust'}")
    with col4:
        st.metric("Verifikationer", len(transactions))

    # Andra raden med nyckeltal
    col5, col6, col7, col8 = st.columns(4)

    with col5:
        st.metric("Soliditet", f"{soliditet:.1f}%", help="Eget kapital / Totala tillgångar")
    with col6:
        st.metric("Skulder", f"{total_liabilities:,.0f} kr")
    with col7:
        st.metric("Intäkter", f"{total_revenue:,.0f} kr")
    with col8:
        st.metric("Kostnader", f"{total_expenses:,.0f} kr")

    st.divider()

    # === DIAGRAM ===
    tab1, tab2, tab3 = st.tabs(["📊 Balans & Resultat", "📈 Utveckling över tid", "📉 Nyckeltal"])

    with tab1:
        col_chart1, col_chart2 = st.columns(2)

        with col_chart1:
            # Balansräkning som stapeldiagram
            st.subheader("Balansräkning")

            fig_balance = go.Figure()

            # Tillgångar
            fig_balance.add_trace(go.Bar(
                name='Tillgångar',
                x=['Tillgångar'],
                y=[float(total_assets)],
                marker_color='#2E86AB'
            ))

            # EK + Skulder
            fig_balance.add_trace(go.Bar(
                name='Eget kapital',
                x=['EK & Skulder'],
                y=[float(total_equity)],
                marker_color='#28A745'
            ))

            fig_balance.add_trace(go.Bar(
                name='Skulder',
                x=['EK & Skulder'],
                y=[float(total_liabilities)],
                marker_color='#DC3545',
                base=[float(total_equity)]
            ))

            fig_balance.update_layout(
                barmode='stack',
                yaxis_title='Belopp (kr)',
                height=400,
                showlegend=True
            )

            st.plotly_chart(fig_balance, use_container_width=True)

        with col_chart2:
            # Resultaträkning som cirkeldiagram
            st.subheader("Resultaträkning")

            if total_revenue > 0 or total_expenses > 0:
                fig_result = go.Figure()

                # Skapa data för resultatfördelning
                labels = ['Intäkter', 'Kostnader', 'Resultat' if result >= 0 else 'Förlust']
                values = [float(total_revenue), float(total_expenses), abs(float(result))]
                colors = ['#28A745', '#DC3545', '#FFC107' if result >= 0 else '#6C757D']

                fig_result = go.Figure(data=[go.Pie(
                    labels=labels[:2],
                    values=values[:2],
                    hole=.4,
                    marker_colors=colors[:2]
                )])

                fig_result.update_layout(
                    height=400,
                    annotations=[dict(text=f'Resultat<br>{result:,.0f} kr', x=0.5, y=0.5, font_size=14, showarrow=False)]
                )

                st.plotly_chart(fig_result, use_container_width=True)
            else:
                st.info("Ingen intäkts-/kostnadsdata att visa")

    with tab2:
        st.subheader("Utveckling per månad")

        # Beräkna månatliga summor
        if transactions:
            from collections import defaultdict
            monthly_data = defaultdict(lambda: {'revenue': Decimal(0), 'expenses': Decimal(0), 'balance': Decimal(0)})

            for tx in transactions:
                month_key = tx.transaction_date.strftime('%Y-%m')
                for line in tx.lines:
                    acc_num = line.account.number
                    if acc_num.startswith('3'):
                        monthly_data[month_key]['revenue'] += line.credit - line.debit
                    elif acc_num[0] in '45678':
                        monthly_data[month_key]['expenses'] += line.debit - line.credit
                    elif acc_num.startswith('1'):
                        monthly_data[month_key]['balance'] += line.debit - line.credit

            # Sortera månader
            months = sorted(monthly_data.keys())
            revenues = [float(monthly_data[m]['revenue']) for m in months]
            expenses = [float(monthly_data[m]['expenses']) for m in months]
            results = [r - e for r, e in zip(revenues, expenses)]

            # Kumulativt resultat
            cumulative_result = []
            cum = 0
            for r in results:
                cum += r
                cumulative_result.append(cum)

            # Skapa diagram
            fig_trend = go.Figure()

            fig_trend.add_trace(go.Bar(
                name='Intäkter',
                x=months,
                y=revenues,
                marker_color='#28A745'
            ))

            fig_trend.add_trace(go.Bar(
                name='Kostnader',
                x=months,
                y=expenses,
                marker_color='#DC3545'
            ))

            fig_trend.add_trace(go.Scatter(
                name='Kumulativt resultat',
                x=months,
                y=cumulative_result,
                mode='lines+markers',
                line=dict(color='#FFC107', width=3),
                yaxis='y2'
            ))

            fig_trend.update_layout(
                barmode='group',
                yaxis_title='Belopp (kr)',
                yaxis2=dict(
                    title='Kumulativt resultat (kr)',
                    overlaying='y',
                    side='right'
                ),
                height=400,
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1)
            )

            st.plotly_chart(fig_trend, use_container_width=True)
        else:
            st.info("Inga transaktioner att visa")

    with tab3:
        st.subheader("Nyckeltal")

        col_kpi1, col_kpi2 = st.columns(2)

        with col_kpi1:
            # Soliditet som gauge
            fig_soliditet = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=soliditet,
                title={'text': "Soliditet (%)"},
                delta={'reference': 30},  # 30% anses som bra
                gauge={
                    'axis': {'range': [0, 100]},
                    'bar': {'color': "#2E86AB"},
                    'steps': [
                        {'range': [0, 20], 'color': "#FFCCCC"},
                        {'range': [20, 40], 'color': "#FFFFCC"},
                        {'range': [40, 100], 'color': "#CCFFCC"}
                    ],
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': 30
                    }
                }
            ))

            fig_soliditet.update_layout(height=300)
            st.plotly_chart(fig_soliditet, use_container_width=True)

            st.caption("Soliditet = Eget kapital / Totala tillgångar. >30% anses som bra.")

        with col_kpi2:
            # Skuldsättningsgrad som gauge
            skuldsattning = (float(total_liabilities) / float(total_equity) * 100) if total_equity != 0 else 0

            fig_skuld = go.Figure(go.Indicator(
                mode="gauge+number",
                value=skuldsattning,
                title={'text': "Skuldsättningsgrad (%)"},
                gauge={
                    'axis': {'range': [0, 300]},
                    'bar': {'color': "#DC3545"},
                    'steps': [
                        {'range': [0, 100], 'color': "#CCFFCC"},
                        {'range': [100, 200], 'color': "#FFFFCC"},
                        {'range': [200, 300], 'color': "#FFCCCC"}
                    ]
                }
            ))

            fig_skuld.update_layout(height=300)
            st.plotly_chart(fig_skuld, use_container_width=True)

            st.caption("Skuldsättningsgrad = Skulder / Eget kapital. <100% anses som bra.")

        # Tabell med nyckeltal
        st.subheader("Sammanfattning nyckeltal")

        kpi_data = {
            'Nyckeltal': ['Soliditet', 'Skuldsättningsgrad', 'Likviditet', 'Vinstmarginal'],
            'Värde': [
                f"{soliditet:.1f}%",
                f"{skuldsattning:.1f}%",
                f"{likviditet:.1f}%" if short_term_liabilities != 0 else "N/A",
                f"{(float(result) / float(total_revenue) * 100):.1f}%" if total_revenue != 0 else "N/A"
            ],
            'Bedömning': [
                "Bra" if soliditet > 30 else "Låg" if soliditet < 20 else "Acceptabel",
                "Bra" if skuldsattning < 100 else "Hög" if skuldsattning > 200 else "Acceptabel",
                "Bra" if likviditet > 100 else "Låg",
                "Bra" if total_revenue > 0 and result > 0 else "Förlust" if result < 0 else "N/A"
            ]
        }

        import pandas as pd
        df_kpi = pd.DataFrame(kpi_data)
        st.dataframe(df_kpi, use_container_width=True, hide_index=True)

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

    tab1, tab2, tab3, tab4 = st.tabs(["Visa transaktioner", "Ny transaktion", "Konteringsmallar", "Periodiseringar"])

    accounts = service.get_accounts(company_id)
    account_options = {f"{a.number} - {a.name}": a.id for a in accounts}

    with tab1:
        transactions = service.get_transactions(company_id, fiscal_year.id)

        if transactions:
            st.write(f"Visar {len(transactions)} transaktioner")
            for tx in reversed(transactions):
                # Kontrollera om transaktionen balanserar
                balance_status = "✓" if tx.is_balanced else "⚠️ OBALANSERAD"

                with st.expander(f"Ver {tx.verification_number}: {tx.description} ({tx.transaction_date}) {balance_status}"):
                    col_info, col_actions = st.columns([3, 1])

                    with col_info:
                        st.write(f"**Datum:** {tx.transaction_date}")
                        st.write(f"**Beskrivning:** {tx.description}")
                        st.write(f"**Total:** D {tx.total_debit:,.2f} / K {tx.total_credit:,.2f}")

                    with col_actions:
                        if st.button("🗑️ Ta bort transaktion", key=f"del_tx_{tx.id}", type="secondary"):
                            if service.delete_transaction(tx.id):
                                st.success("Transaktion borttagen!")
                                st.rerun()

                    st.write("**Konteringsrader:**")

                    # Visa varje rad med redigeringsmöjlighet
                    for line in tx.lines:
                        col1, col2, col3, col4, col5 = st.columns([3, 2, 2, 1, 1])

                        with col1:
                            st.write(f"{line.account.number} {line.account.name}")
                        with col2:
                            debit_str = f"{line.debit:,.2f}" if line.debit and line.debit > 0 else "-"
                            st.write(f"D: {debit_str}")
                        with col3:
                            credit_str = f"{line.credit:,.2f}" if line.credit and line.credit > 0 else "-"
                            st.write(f"K: {credit_str}")
                        with col4:
                            # Tom plats för layout
                            pass
                        with col5:
                            if st.button("❌", key=f"del_line_{line.id}", help="Ta bort rad"):
                                if service.delete_transaction_line(line.id):
                                    st.success("Rad borttagen!")
                                    st.rerun()

                    # Lägg till ny rad
                    st.divider()
                    st.write("**Lägg till rad:**")
                    col_acc, col_d, col_k, col_btn = st.columns([3, 2, 2, 1])

                    with col_acc:
                        new_account = st.selectbox(
                            "Konto",
                            [""] + list(account_options.keys()),
                            key=f"new_acc_{tx.id}",
                            label_visibility="collapsed"
                        )
                    with col_d:
                        new_debit = st.number_input(
                            "Debet",
                            min_value=0.0,
                            step=100.0,
                            key=f"new_deb_{tx.id}",
                            label_visibility="collapsed"
                        )
                    with col_k:
                        new_credit = st.number_input(
                            "Kredit",
                            min_value=0.0,
                            step=100.0,
                            key=f"new_cred_{tx.id}",
                            label_visibility="collapsed"
                        )
                    with col_btn:
                        if st.button("➕", key=f"add_line_{tx.id}", help="Lägg till rad"):
                            if new_account and (new_debit > 0 or new_credit > 0):
                                from decimal import Decimal
                                service.add_transaction_line(
                                    transaction_id=tx.id,
                                    account_id=account_options[new_account],
                                    debit=Decimal(str(new_debit)),
                                    credit=Decimal(str(new_credit))
                                )
                                st.success("Rad tillagd!")
                                st.rerun()
                            else:
                                st.error("Välj konto och ange belopp")
        else:
            st.info("Inga transaktioner ännu för detta räkenskapsår")

    with tab2:
        st.subheader("Skapa ny transaktion")

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

    with tab3:
        show_transaction_templates(service, company_id, fiscal_year, account_options)

    with tab4:
        show_accruals(service, company_id, fiscal_year, account_options)


def show_transaction_templates(service, company_id, fiscal_year, account_options):
    """Visa och använd konteringsmallar"""
    from app.services.template import TemplateService
    from app.models import get_db
    from decimal import Decimal

    st.subheader("Konteringsmallar")

    st.write("""
    Använd mallar för återkommande transaktioner som momskontering, lön, hyra etc.
    """)

    db = next(get_db())
    template_service = TemplateService(db)

    # Lista mallar
    templates = template_service.get_templates(company_id)

    if not templates:
        st.info("Inga mallar skapade ännu")
        if st.button("Skapa standardmallar"):
            created = template_service.initialize_standard_templates(company_id)
            if created:
                st.success(f"{len(created)} standardmallar skapade!")
                st.rerun()
            else:
                st.warning("Kontrollera att BAS-kontoplanen är laddad")
    else:
        # Använd mall
        st.write("**Använd mall**")

        template_options = {t.name: t for t in templates}
        selected_template_name = st.selectbox(
            "Välj mall",
            options=list(template_options.keys()),
            key="template_select"
        )
        template = template_options[selected_template_name]

        if template:
            st.caption(f"Kategori: {template.category or 'Ingen'} | Använd: {template.usage_count} gånger")

            if template.description:
                st.write(template.description)

            # Visa mallens konteringsrader
            with st.expander("Visa mallstruktur"):
                for line in template.lines:
                    side = "Debet" if line.is_debit else "Kredit"
                    if line.amount_percentage:
                        amount_str = f"{line.amount_percentage}%"
                    elif line.amount_fixed:
                        amount_str = f"{line.amount_fixed:,.2f} kr"
                    else:
                        amount_str = "Resterande"
                    st.write(f"- {line.account.number} {line.account.name}: {side} {amount_str}")

            # Formulär för att använda mallen
            with st.form("use_template"):
                tx_date = st.date_input("Datum", key="template_date")
                total_amount = st.number_input(
                    "Totalbelopp (inkl moms)",
                    min_value=0.01,
                    step=100.0,
                    key="template_amount"
                )
                tx_description = st.text_input(
                    "Beskrivning",
                    value=f"Transaktion från mall: {template.name}",
                    key="template_desc"
                )

                if st.form_submit_button("Skapa transaktion från mall", type="primary"):
                    try:
                        tx = template_service.apply_template(
                            template=template,
                            fiscal_year_id=fiscal_year.id,
                            transaction_date=tx_date,
                            total_amount=Decimal(str(total_amount)),
                            description=tx_description
                        )
                        st.success(f"Transaktion {tx.verification_number} skapad!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fel: {e}")

    st.divider()

    # Skapa ny mall
    st.write("**Skapa ny mall**")

    with st.expander("Lägg till mall"):
        with st.form("new_template"):
            name = st.text_input("Mallnamn")
            description = st.text_area("Beskrivning", height=60)
            category = st.text_input("Kategori", placeholder="T.ex. Moms, Lön, Hyra")

            st.write("**Konteringsrader:**")
            st.caption("Ange procent av totalbelopp för varje rad. Den sista raden kan vara 'resterande'.")

            template_lines = []
            for i in range(4):
                col1, col2, col3, col4 = st.columns([3, 1, 2, 1])
                with col1:
                    acc = st.selectbox(f"Konto", [""] + list(account_options.keys()), key=f"tmpl_acc_{i}")
                with col2:
                    is_debit = st.checkbox("Debet", key=f"tmpl_deb_{i}")
                with col3:
                    pct = st.number_input("Procent", min_value=0.0, max_value=100.0, key=f"tmpl_pct_{i}")
                with col4:
                    is_rem = st.checkbox("Rest", key=f"tmpl_rem_{i}")

                if acc:
                    template_lines.append({
                        'account_id': account_options[acc],
                        'is_debit': is_debit,
                        'percentage': pct if pct > 0 and not is_rem else None,
                        'is_remainder': is_rem
                    })

            if st.form_submit_button("Skapa mall"):
                if name and len(template_lines) >= 2:
                    try:
                        new_template = template_service.create_template(
                            company_id=company_id,
                            name=name,
                            description=description,
                            category=category,
                            lines=template_lines
                        )
                        st.success(f"Mall '{name}' skapad!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fel: {e}")
                else:
                    st.error("Ange namn och minst 2 konteringsrader")

    db.close()


def show_accruals(service, company_id, fiscal_year, account_options):
    """Visa och hantera periodiseringar"""
    from app.services.accrual import AccrualService
    from app.models import get_db
    from app.models.accrual import AccrualType, AccrualFrequency
    from decimal import Decimal
    from datetime import date

    st.subheader("Periodiseringar")

    st.write("""
    Skapa periodiseringar för kostnader eller intäkter som ska fördelas över flera perioder.
    Transaktioner skapas automatiskt varje månad/kvartal så länge periodiseringen är aktiv.
    """)

    db = next(get_db())
    accrual_service = AccrualService(db)

    # Lista aktiva periodiseringar
    accruals = accrual_service.get_accruals(company_id, active_only=True)

    if accruals:
        st.write("**Aktiva periodiseringar:**")

        for acc in accruals:
            status = f"{acc.periods - acc.periods_remaining}/{acc.periods} perioder bokförda"
            with st.expander(f"{acc.name} - {status}"):
                col1, col2 = st.columns(2)

                with col1:
                    st.write(f"**Typ:** {acc.accrual_type.value}")
                    st.write(f"**Totalbelopp:** {acc.total_amount:,.2f} kr")
                    st.write(f"**Per period:** {acc.amount_per_period:,.2f} kr")
                    st.write(f"**Återstående:** {acc.remaining_amount:,.2f} kr")

                with col2:
                    st.write(f"**Startdatum:** {acc.start_date}")
                    st.write(f"**Slutdatum:** {acc.end_date}")
                    st.write(f"**Frekvens:** {acc.frequency.value}")
                    st.write(f"**Auto-generering:** {'Ja' if acc.auto_generate else 'Nej'}")

                # Visa bokförda perioder
                if acc.entries:
                    st.write("**Bokförda perioder:**")
                    for entry in acc.entries:
                        status_icon = "✅" if entry.is_booked else "⏳"
                        st.caption(f"{status_icon} Period {entry.period_number}: {entry.period_date} - {entry.amount:,.2f} kr")

                # Avsluta periodisering
                if st.button("Avsluta periodisering", key=f"deactivate_{acc.id}"):
                    accrual_service.deactivate_accrual(acc.id)
                    st.success("Periodisering avslutad")
                    st.rerun()
    else:
        st.info("Inga aktiva periodiseringar")

    # Kör väntande periodiseringar
    st.divider()
    st.write("**Kör periodiseringar**")

    pending = accrual_service.get_pending_entries(company_id)

    if pending:
        st.write(f"**{len(pending)} väntande periodiseringar:**")
        for p in pending[:5]:
            st.caption(f"- {p['accrual_name']}: Period {p['period_number']} ({p['period_date']}) - {p['amount']:,.2f} kr")

        if st.button("Kör alla väntande periodiseringar", type="primary"):
            entries = accrual_service.run_auto_accruals(company_id)
            if entries:
                st.success(f"{len(entries)} periodiseringstransaktioner skapade!")
                st.rerun()
            else:
                st.info("Inga periodiseringar att köra")
    else:
        st.success("Alla periodiseringar är uppdaterade")

    # Skapa ny periodisering
    st.divider()
    st.write("**Skapa ny periodisering**")

    with st.form("new_accrual"):
        name = st.text_input("Namn", placeholder="T.ex. 'Försäkring 2024'")
        description = st.text_area("Beskrivning", height=60)

        col1, col2 = st.columns(2)

        with col1:
            accrual_type = st.selectbox(
                "Typ av periodisering",
                options=[t for t in AccrualType],
                format_func=lambda x: x.value
            )
            total_amount = st.number_input("Totalbelopp", min_value=0.01, step=100.0)
            periods = st.number_input("Antal perioder", min_value=1, max_value=60, value=12)

        with col2:
            start_date = st.date_input("Startdatum", value=date.today().replace(day=1))
            frequency = st.selectbox(
                "Frekvens",
                options=[f for f in AccrualFrequency],
                format_func=lambda x: x.value
            )
            auto_generate = st.checkbox("Generera transaktioner automatiskt", value=True)

        st.write("**Konton:**")
        col1, col2 = st.columns(2)
        with col1:
            source_acc = st.selectbox(
                "Källkonto (t.ex. förutbetald kostnad)",
                options=list(account_options.keys()),
                key="accrual_source"
            )
        with col2:
            target_acc = st.selectbox(
                "Målkonto (t.ex. kostnadskonto)",
                options=list(account_options.keys()),
                key="accrual_target"
            )

        if st.form_submit_button("Skapa periodisering", type="primary"):
            if name and total_amount > 0 and source_acc and target_acc:
                try:
                    accrual = accrual_service.create_accrual(
                        company_id=company_id,
                        fiscal_year_id=fiscal_year.id,
                        name=name,
                        description=description,
                        accrual_type=accrual_type,
                        total_amount=Decimal(str(total_amount)),
                        periods=periods,
                        start_date=start_date,
                        source_account_id=account_options[source_acc],
                        target_account_id=account_options[target_acc],
                        frequency=frequency,
                        auto_generate=auto_generate
                    )
                    st.success(f"Periodisering '{name}' skapad!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fel: {e}")
            else:
                st.error("Fyll i alla obligatoriska fält")

    db.close()


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

    # Flikar för kontoplan och ingående balanser
    tab1, tab2 = st.tabs(["Kontoplan", "Ingående balanser"])

    with tab1:
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

    with tab2:
        show_opening_balances(service, company_id, accounts)


def show_opening_balances(service: AccountingService, company_id: int, accounts):
    """Visa och redigera ingående balanser"""
    from decimal import Decimal

    st.subheader("Ingående balanser")
    st.write("""
    Ange ingående balanser för balanskonton (klass 1-2).
    Dessa värden används som startvärden för räkenskapsåret.
    """)

    # Filtrera till balanskonton (klass 1-2)
    balance_accounts = [a for a in accounts if a.is_balance_account]

    # Visa summa för kontroll
    total_assets = sum(a.opening_balance or Decimal(0) for a in balance_accounts if a.number.startswith('1'))
    total_liabilities = sum(a.opening_balance or Decimal(0) for a in balance_accounts if a.number.startswith('2'))

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Tillgångar (IB)", f"{total_assets:,.2f} kr")
    with col2:
        st.metric("EK & Skulder (IB)", f"{total_liabilities:,.2f} kr")
    with col3:
        diff = total_assets - total_liabilities
        if diff == 0:
            st.metric("Differens", "0 kr", delta="Balanserar")
        else:
            st.metric("Differens", f"{diff:,.2f} kr", delta="Balanserar EJ", delta_color="inverse")

    st.divider()

    # Snabbredigering av konton med saldo eller vanliga balanskonton
    st.write("### Ange ingående balanser")

    # Hämta db-session från service
    db = service.db

    # Visa tillgångar (klass 1)
    st.write("#### Tillgångar (klass 1)")
    assets = [a for a in balance_accounts if a.number.startswith('1')]

    for acc in assets:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"**{acc.number}** {acc.name}")
        with col2:
            current_balance = float(acc.opening_balance or 0)
            new_balance = st.number_input(
                f"IB {acc.number}",
                value=current_balance,
                step=100.0,
                format="%.2f",
                key=f"ib_{acc.number}",
                label_visibility="collapsed"
            )
            if new_balance != current_balance:
                acc.opening_balance = Decimal(str(new_balance))
                db.commit()
                st.rerun()

    st.write("#### Eget kapital och skulder (klass 2)")
    liabilities = [a for a in balance_accounts if a.number.startswith('2')]

    for acc in liabilities:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"**{acc.number}** {acc.name}")
        with col2:
            current_balance = float(acc.opening_balance or 0)
            new_balance = st.number_input(
                f"IB {acc.number}",
                value=current_balance,
                step=100.0,
                format="%.2f",
                key=f"ib_{acc.number}",
                label_visibility="collapsed"
            )
            if new_balance != current_balance:
                acc.opening_balance = Decimal(str(new_balance))
                db.commit()
                st.rerun()

    st.divider()

    # Nollställ alla ingående balanser
    if st.button("Nollställ alla ingående balanser", type="secondary"):
        for acc in balance_accounts:
            acc.opening_balance = Decimal(0)
        db.commit()
        st.success("Alla ingående balanser nollställda!")
        st.rerun()


def show_report_export_buttons(db, report_type: str, company_id: int, fiscal_year_id: int, **kwargs):
    """Visa exportknappar för rapporter"""
    st.divider()
    st.write("**Exportera rapport:**")

    col1, col2, col3, col4 = st.columns(4)

    report_generator = ReportGenerator(db)

    # Mappa rapporttyp till intern nyckel
    type_map = {
        "Balansräkning": "balance_sheet",
        "Resultaträkning": "income_statement",
        "Råbalans": "trial_balance",
        "Huvudbok": "general_ledger",
        "Årsredovisning": "annual_report",
    }
    internal_type = type_map.get(report_type)

    if not internal_type:
        st.info("Export ej tillgänglig för denna rapport")
        return

    try:
        with col1:
            if st.button("📄 HTML", key=f"export_html_{report_type}"):
                data, content_type, filename = report_generator.generate_report_with_export(
                    internal_type, company_id, fiscal_year_id, "html", **kwargs
                )
                st.download_button(
                    "Ladda ner HTML",
                    data,
                    filename,
                    content_type,
                    key=f"dl_html_{report_type}"
                )

        with col2:
            if st.button("📕 PDF", key=f"export_pdf_{report_type}"):
                try:
                    data, content_type, filename = report_generator.generate_report_with_export(
                        internal_type, company_id, fiscal_year_id, "pdf", **kwargs
                    )
                    st.download_button(
                        "Ladda ner PDF",
                        data,
                        filename,
                        content_type,
                        key=f"dl_pdf_{report_type}"
                    )
                except Exception as e:
                    st.error(f"Kunde inte generera PDF: {e}")

        with col3:
            if st.button("📘 Word", key=f"export_docx_{report_type}"):
                try:
                    data, content_type, filename = report_generator.generate_report_with_export(
                        internal_type, company_id, fiscal_year_id, "docx", **kwargs
                    )
                    st.download_button(
                        "Ladda ner Word",
                        data,
                        filename,
                        content_type,
                        key=f"dl_docx_{report_type}"
                    )
                except Exception as e:
                    st.error(f"Kunde inte generera Word: {e}")

        with col4:
            if st.button("🖨️ Förhandsgranska", key=f"preview_{report_type}"):
                data, _, _ = report_generator.generate_report_with_export(
                    internal_type, company_id, fiscal_year_id, "html", **kwargs
                )
                st.components.v1.html(data.decode('utf-8'), height=800, scrolling=True)

    except Exception as e:
        st.error(f"Fel vid export: {e}")


def show_reports(service: AccountingService):
    """Visa rapporter"""
    st.title("Rapporter")

    company_id = st.session_state.selected_company_id
    if not company_id:
        st.info("Välj ett företag först.")
        return

    # Hämta räkenskapsår för export
    db = get_db()
    fiscal_years = service.get_fiscal_years(company_id)
    fiscal_year = fiscal_years[0] if fiscal_years else None

    report_type = st.selectbox(
        "Välj rapport",
        ["Verifikationslista", "Huvudbok", "Råbalans", "Balansräkning", "Resultaträkning",
         "Momsrapport", "Arbetsgivardeklaration", "Skattedeklaration (INK2)"]
    )

    if report_type == "Verifikationslista":
        show_verification_list(service, company_id)
    elif report_type == "Huvudbok":
        show_general_ledger(service, company_id)
        if fiscal_year:
            show_report_export_buttons(db, report_type, company_id, fiscal_year.id)
    elif report_type == "Råbalans":
        show_trial_balance(service, company_id)
        if fiscal_year:
            show_report_export_buttons(db, report_type, company_id, fiscal_year.id)
    elif report_type == "Balansräkning":
        show_balance_sheet(service, company_id)
        if fiscal_year:
            show_report_export_buttons(db, report_type, company_id, fiscal_year.id)
    elif report_type == "Resultaträkning":
        show_income_statement(service, company_id)
        if fiscal_year:
            show_report_export_buttons(db, report_type, company_id, fiscal_year.id)
    elif report_type == "Momsrapport":
        show_vat_report(service, company_id)
    elif report_type == "Arbetsgivardeklaration":
        show_employer_report(service, company_id)
    elif report_type == "Skattedeklaration (INK2)":
        show_tax_declaration(service, company_id)


def show_general_ledger(service: AccountingService, company_id: int):
    """Visa huvudbok - alla transaktioner per konto"""
    st.subheader("Huvudbok")

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
        key="gl_fy"
    )
    fiscal_year = fiscal_year_options[selected_fy_name]

    # Hämta konton
    accounts = service.get_accounts(company_id)
    if not accounts:
        st.info("Inga konton finns")
        return

    # Filter för kontogrupp
    account_groups = {
        "Alla konton": None,
        "1xxx - Tillgångar": "1",
        "2xxx - Eget kapital och skulder": "2",
        "3xxx - Intäkter": "3",
        "4xxx - Kostnader varor": "4",
        "5xxx - Övriga externa kostnader": "5",
        "6xxx - Övriga externa kostnader": "6",
        "7xxx - Personal": "7",
        "8xxx - Finansiella poster": "8"
    }

    col1, col2 = st.columns(2)
    with col1:
        selected_group = st.selectbox(
            "Kontogrupp",
            options=list(account_groups.keys()),
            key="gl_group"
        )
    with col2:
        # Specifikt konto
        account_list = ["Alla"] + [f"{a.number} - {a.name}" for a in accounts]
        selected_account = st.selectbox(
            "Specifikt konto",
            options=account_list,
            key="gl_account"
        )

    # Datumfilter
    col3, col4 = st.columns(2)
    with col3:
        start_date = st.date_input(
            "Från datum",
            value=fiscal_year.start_date,
            key="gl_start"
        )
    with col4:
        end_date = st.date_input(
            "Till datum",
            value=fiscal_year.end_date,
            key="gl_end"
        )

    st.divider()

    # Filtrera konton
    group_prefix = account_groups[selected_group]
    if selected_account != "Alla":
        # Specifikt konto valt
        acc_number = selected_account.split(" - ")[0]
        filtered_accounts = [a for a in accounts if a.number == acc_number]
    elif group_prefix:
        filtered_accounts = [a for a in accounts if a.number.startswith(group_prefix)]
    else:
        filtered_accounts = accounts

    # Hämta alla transaktioner för perioden
    transactions = service.get_transactions(
        company_id,
        fiscal_year.id,
        start_date=start_date,
        end_date=end_date
    )

    # Bygg en lookup för transaktionsrader per konto
    from collections import defaultdict
    from decimal import Decimal

    account_transactions = defaultdict(list)
    for tx in transactions:
        for line in tx.lines:
            account_transactions[line.account_id].append({
                'date': tx.transaction_date,
                'ver': tx.verification_number,
                'description': tx.description,
                'debit': line.debit,
                'credit': line.credit
            })

    # Visa huvudbok per konto
    accounts_with_activity = 0

    for account in sorted(filtered_accounts, key=lambda a: a.number):
        tx_lines = account_transactions.get(account.id, [])
        opening_balance = account.opening_balance or Decimal(0)

        # Visa endast konton med aktivitet eller ingående balans
        if not tx_lines and opening_balance == 0:
            continue

        accounts_with_activity += 1

        with st.expander(f"**{account.number}** {account.name}", expanded=False):
            # Ingående balans
            st.write(f"**Ingående balans:** {opening_balance:,.2f} kr")

            if tx_lines:
                # Sortera efter datum och ver.nr
                tx_lines_sorted = sorted(tx_lines, key=lambda x: (x['date'], x['ver']))

                # Visa tabell
                st.write("| Datum | Ver | Beskrivning | Debet | Kredit | Saldo |")
                st.write("|-------|-----|-------------|------:|-------:|------:|")

                running_balance = opening_balance
                total_debit = Decimal(0)
                total_credit = Decimal(0)

                for line in tx_lines_sorted:
                    # Beräkna löpande saldo beroende på kontotyp
                    if account.account_type.value in ['Tillgång', 'Kostnad']:
                        running_balance += line['debit'] - line['credit']
                    else:
                        running_balance += line['credit'] - line['debit']

                    total_debit += line['debit']
                    total_credit += line['credit']

                    debit_str = f"{line['debit']:,.2f}" if line['debit'] > 0 else ""
                    credit_str = f"{line['credit']:,.2f}" if line['credit'] > 0 else ""
                    desc_short = line['description'][:30] + "..." if len(line['description']) > 30 else line['description']

                    st.write(f"| {line['date']} | {line['ver']} | {desc_short} | {debit_str} | {credit_str} | {running_balance:,.2f} |")

                st.write(f"| **Summa** | | | **{total_debit:,.2f}** | **{total_credit:,.2f}** | |")
                st.write(f"**Utgående balans:** {running_balance:,.2f} kr")
            else:
                st.write("Inga transaktioner under perioden")

    if accounts_with_activity == 0:
        st.info("Inga konton med aktivitet för vald period och filter")


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

    # Visa räkenskapsår
    fiscal_year = service.get_active_fiscal_year(company_id)
    if fiscal_year:
        st.caption(f"Räkenskapsår: {fiscal_year.start_date} - {fiscal_year.end_date}")
        st.caption(f"Per balansdagen: {fiscal_year.end_date}")

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

    # Visa räkenskapsår
    fiscal_year = service.get_active_fiscal_year(company_id)
    if fiscal_year:
        st.caption(f"Räkenskapsår: {fiscal_year.start_date} - {fiscal_year.end_date}")

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


def show_vat_report(service: AccountingService, company_id: int):
    """Visa momsrapport enligt Skatteverkets format"""
    st.subheader("Momsrapport (SKV 4700)")

    from app.services.tax import VATReport
    from app.models import get_db

    # Hämta räkenskapsår
    fiscal_years = service.get_fiscal_years(company_id)
    if not fiscal_years:
        st.warning("Inga räkenskapsår finns")
        return

    fiscal_year = fiscal_years[0]

    st.write("Välj rapportperiod:")

    col1, col2 = st.columns(2)
    with col1:
        period_start = st.date_input(
            "Från",
            value=fiscal_year.start_date,
            key="vat_start"
        )
    with col2:
        period_end = st.date_input(
            "Till",
            value=fiscal_year.end_date,
            key="vat_end"
        )

    # Snabbval för perioder
    st.write("**Snabbval:**")
    period_cols = st.columns(4)
    from datetime import date as date_type
    from dateutil.relativedelta import relativedelta

    with period_cols[0]:
        if st.button("Januari"):
            year = fiscal_year.start_date.year
            period_start = date_type(year, 1, 1)
            period_end = date_type(year, 1, 31)
    with period_cols[1]:
        if st.button("Q1"):
            year = fiscal_year.start_date.year
            period_start = date_type(year, 1, 1)
            period_end = date_type(year, 3, 31)
    with period_cols[2]:
        if st.button("Q2"):
            year = fiscal_year.start_date.year
            period_start = date_type(year, 4, 1)
            period_end = date_type(year, 6, 30)
    with period_cols[3]:
        if st.button("Helår"):
            period_start = fiscal_year.start_date
            period_end = fiscal_year.end_date

    if st.button("Generera momsrapport", type="primary"):
        db = next(get_db())
        try:
            vat_report = VATReport(db)
            report = vat_report.generate(company_id, period_start, period_end)

            st.divider()
            st.write(f"### Momsrapport {report['period_start']} - {report['period_end']}")

            # Försäljning
            st.write("#### Momspliktiga intäkter")
            st.write(f"**Ruta 05 - Momspliktig försäljning exkl. moms:** {report['sales_excl_vat']:,.2f} kr")

            st.divider()

            # Utgående moms
            st.write("#### Utgående moms")
            st.write(f"**Ruta 10 - Utgående moms 25%:** {report['output_vat_25']:,.2f} kr")
            st.write(f"**Ruta 11 - Utgående moms 12%:** {report['output_vat_12']:,.2f} kr")
            st.write(f"**Ruta 12 - Utgående moms 6%:** {report['output_vat_6']:,.2f} kr")
            st.write(f"**Summa utgående moms:** {report['total_output_vat']:,.2f} kr")

            st.divider()

            # Ingående moms
            st.write("#### Ingående moms")
            st.write(f"**Ruta 48 - Ingående moms:** {report['input_vat']:,.2f} kr")

            st.divider()

            # Resultat
            st.write("#### Resultat")
            vat_to_pay = report['vat_to_pay']
            if vat_to_pay > 0:
                st.error(f"**Ruta 49 - Moms att betala:** {vat_to_pay:,.2f} kr")
            else:
                st.success(f"**Ruta 49 - Moms att få tillbaka:** {abs(vat_to_pay):,.2f} kr")

        except Exception as e:
            st.error(f"Fel vid generering: {e}")
        finally:
            db.close()


def show_employer_report(service: AccountingService, company_id: int):
    """Visa arbetsgivardeklaration"""
    st.subheader("Arbetsgivardeklaration (AGI)")

    from app.services.tax import EmployerReport
    from app.models import get_db

    # Hämta räkenskapsår
    fiscal_years = service.get_fiscal_years(company_id)
    if not fiscal_years:
        st.warning("Inga räkenskapsår finns")
        return

    fiscal_year = fiscal_years[0]

    st.write("Välj rapportperiod (normalt en månad):")

    col1, col2 = st.columns(2)
    with col1:
        period_start = st.date_input(
            "Från",
            value=fiscal_year.start_date,
            key="agi_start"
        )
    with col2:
        period_end = st.date_input(
            "Till",
            value=fiscal_year.end_date,
            key="agi_end"
        )

    if st.button("Generera arbetsgivarrapport", type="primary"):
        db = next(get_db())
        try:
            employer_report = EmployerReport(db)
            report = employer_report.generate(company_id, period_start, period_end)

            st.divider()
            st.write(f"### Arbetsgivardeklaration {report['period_start']} - {report['period_end']}")

            # Löneuppgifter
            st.write("#### Löneuppgifter")
            st.write(f"**Bruttolön:** {report['gross_salary']:,.2f} kr")
            st.write(f"**Semesterersättning:** {report['vacation_pay']:,.2f} kr")
            st.write(f"**Totalt löneunderlag:** {report['total_salary_base']:,.2f} kr")

            st.divider()

            # Arbetsgivaravgifter
            st.write("#### Arbetsgivaravgifter")
            rate_pct = float(report['contribution_rate']) * 100
            st.write(f"**Avgiftssats:** {rate_pct:.2f}%")
            st.write(f"**Beräknade arbetsgivaravgifter:** {report['calculated_contributions']:,.2f} kr")
            st.write(f"**Bokförda arbetsgivaravgifter (skuld):** {report['employer_contributions']:,.2f} kr")

            st.divider()

            # Skatt
            st.write("#### Avdragen skatt")
            st.write(f"**Personalens källskatt (skuld):** {report['withholding_tax']:,.2f} kr")

            st.divider()

            # Summa att betala
            st.write("#### Att betala till Skatteverket")
            st.error(f"**Totalt:** {report['total_to_pay']:,.2f} kr")

            st.info("""
            **Obs!** Arbetsgivardeklarationen ska lämnas senast den 12:e i månaden
            efter löneutbetalningen. Beloppet ska vara inbetalat samma dag.
            """)

        except Exception as e:
            st.error(f"Fel vid generering: {e}")
        finally:
            db.close()


def show_tax_declaration(service: AccountingService, company_id: int):
    """Visa skattedeklarationsunderlag (INK2)"""
    st.subheader("Skattedeklaration INK2 (Aktiebolag)")

    from app.services.tax_declaration import TaxDeclarationService
    from app.models import get_db

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
        key="tax_decl_fy"
    )
    fiscal_year = fiscal_year_options[selected_fy_name]

    db = next(get_db())
    try:
        tax_service = TaxDeclarationService(db)

        # Kolla om det finns sparat underlag
        existing = tax_service.get_declaration(company_id, fiscal_year.id, "INK2")

        col1, col2 = st.columns([2, 1])
        with col1:
            if existing:
                st.success(f"Underlag sparad: {existing.updated_at.strftime('%Y-%m-%d %H:%M')}")
                if existing.status == "submitted":
                    st.info(f"Inskickad: {existing.submitted_at.strftime('%Y-%m-%d')}")

        with col2:
            generate = st.button("Generera underlag", type="primary")

        if generate:
            with st.spinner("Genererar skatteunderlag..."):
                data = tax_service.generate_ink2(company_id, fiscal_year.id)

                # Resultaträkning
                st.divider()
                st.write("### Resultaträkning")
                income = data['income_statement']

                col1, col2 = st.columns(2)
                with col1:
                    st.write("**Intäkter och kostnader**")
                    st.write(f"R1. Nettoomsättning: {income['R1_revenue']:,.0f} kr")
                    st.write(f"R2. Varuinköp: {income['R2_goods_cost']:,.0f} kr")
                    st.write(f"R3. Bruttovinst: {income['R3_gross_profit']:,.0f} kr")
                    st.write(f"R4. Övriga externa kostnader: {income['R4_other_external']:,.0f} kr")
                    st.write(f"R5. Personalkostnader: {income['R5_personnel']:,.0f} kr")
                    st.write(f"R6. Avskrivningar: {income['R6_depreciation']:,.0f} kr")

                with col2:
                    st.write("**Finansiella poster**")
                    st.write(f"R8. Rörelseresultat: {income['R8_operating_result']:,.0f} kr")
                    st.write(f"R9. Finansiella intäkter: {income['R9_financial_income']:,.0f} kr")
                    st.write(f"R10. Finansiella kostnader: {income['R10_financial_expense']:,.0f} kr")
                    st.metric("R11. Resultat före skatt", f"{income['R11_result_before_tax']:,.0f} kr")

                # Balansräkning
                st.divider()
                st.write("### Balansräkning")
                balance = data['balance_sheet']

                col1, col2 = st.columns(2)
                with col1:
                    st.write("**Tillgångar**")
                    st.write(f"B1. Immateriella tillgångar: {balance['assets']['B1_intangible']:,.0f} kr")
                    st.write(f"B2. Materiella tillgångar: {balance['assets']['B2_tangible']:,.0f} kr")
                    st.write(f"B3. Finansiella tillgångar: {balance['assets']['B3_financial']:,.0f} kr")
                    st.write(f"B4. Anläggningstillgångar: {balance['assets']['B4_fixed_assets']:,.0f} kr")
                    st.write(f"B5. Varulager: {balance['assets']['B5_inventory']:,.0f} kr")
                    st.write(f"B6. Fordringar: {balance['assets']['B6_receivables']:,.0f} kr")
                    st.write(f"B7. Kassa och bank: {balance['assets']['B7_cash']:,.0f} kr")
                    st.metric("B9. Summa tillgångar", f"{balance['assets']['B9_total_assets']:,.0f} kr")

                with col2:
                    st.write("**Eget kapital och skulder**")
                    st.write(f"B10. Eget kapital: {balance['liabilities']['B10_equity']:,.0f} kr")
                    st.write(f"B11. Avsättningar: {balance['liabilities']['B11_provisions']:,.0f} kr")
                    st.write(f"B12. Långfristiga skulder: {balance['liabilities']['B12_long_term_debt']:,.0f} kr")
                    st.write(f"B13. Kortfristiga skulder: {balance['liabilities']['B13_short_term_debt']:,.0f} kr")
                    st.metric("B14. Summa skulder", f"{balance['liabilities']['B14_total_liabilities']:,.0f} kr")

                # Skatteberäkning
                st.divider()
                st.write("### Skatteberäkning")
                tax = data['tax_calculation']

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Skattemässigt resultat", f"{tax['taxable_income']:,.0f} kr")
                with col2:
                    st.metric("Skattesats", f"{tax['tax_rate']*100:.1f}%")
                with col3:
                    st.metric("Beräknad bolagsskatt", f"{tax['calculated_tax']:,.0f} kr")

                # Spara underlag
                st.divider()
                notes = st.text_area("Anteckningar", value=existing.notes if existing else "")

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Spara underlag", type="primary"):
                        saved = tax_service.save_declaration(
                            company_id=company_id,
                            fiscal_year_id=fiscal_year.id,
                            declaration_type="INK2",
                            data=data,
                            notes=notes
                        )
                        st.success("Underlag sparat!")
                        st.rerun()

                with col2:
                    if existing and existing.status != "submitted":
                        if st.button("Markera som inskickad"):
                            tax_service.mark_as_submitted(existing.id)
                            st.success("Markerad som inskickad!")
                            st.rerun()

                # Föregående år
                previous = tax_service.get_previous_year_data(company_id, fiscal_year.id)
                if previous:
                    st.divider()
                    with st.expander("Föregående års data"):
                        st.json(previous)

    except Exception as e:
        st.error(f"Fel: {e}")
    finally:
        db.close()


def show_assets(service: AccountingService, db):
    """Visa och hantera anläggningstillgångar"""
    st.title("Anläggningstillgångar")

    company_id = st.session_state.selected_company_id
    if not company_id:
        st.info("Välj ett företag först.")
        return

    from app.services.depreciation import DepreciationService
    from app.models import AssetType, DepreciationMethod
    from decimal import Decimal

    dep_service = DepreciationService(db)

    tab1, tab2, tab3, tab4 = st.tabs(["Tillgångslista", "Lägg till tillgång", "Aktieinnehav", "Kör avskrivningar"])

    with tab1:
        st.subheader("Registrerade tillgångar")

        assets = dep_service.get_assets(company_id, active_only=False)

        if not assets:
            st.info("Inga tillgångar registrerade ännu")
        else:
            for asset in assets:
                status = "Aktiv" if asset.is_active else "Avyttrad"
                with st.expander(f"**{asset.name}** ({asset.asset_type.value}) - {status}"):
                    col1, col2 = st.columns(2)

                    with col1:
                        st.write(f"**Anskaffningsdatum:** {asset.acquisition_date}")
                        st.write(f"**Anskaffningsvärde:** {asset.acquisition_cost:,.2f} kr")
                        st.write(f"**Restvärde:** {asset.residual_value or 0:,.2f} kr")
                        st.write(f"**Nyttjandeperiod:** {asset.useful_life_months} månader")

                    with col2:
                        from datetime import date as date_type
                        book_value = asset.get_book_value(date_type.today())
                        accumulated = asset.get_accumulated_depreciation(date_type.today())

                        st.write(f"**Avskrivningsmetod:** {asset.depreciation_method.value}")
                        st.write(f"**Ack. avskrivningar:** {accumulated:,.2f} kr")
                        st.write(f"**Bokfört värde:** {book_value:,.2f} kr")
                        st.write(f"**Årlig avskrivning:** {asset.annual_depreciation:,.2f} kr")

                    # Avskrivningsschema
                    with st.expander("Visa avskrivningsschema"):
                        schedule = dep_service.get_depreciation_schedule(asset, periods=12)
                        st.write("| Period | Datum | Avskrivning | Ack. | Bokfört värde |")
                        st.write("|--------|-------|------------:|-----:|--------------:|")
                        for row in schedule:
                            st.write(f"| {row['period']} | {row['period_date']} | {row['depreciation']:,.2f} | {row['accumulated']:,.2f} | {row['book_value']:,.2f} |")

    with tab2:
        st.subheader("Registrera ny tillgång")

        accounts = service.get_accounts(company_id)
        account_list = [f"{a.number} - {a.name}" for a in accounts]
        account_map = {f"{a.number} - {a.name}": a.number for a in accounts}

        with st.form("new_asset_form"):
            name = st.text_input("Namn på tillgång")
            description = st.text_area("Beskrivning", height=80)

            col1, col2 = st.columns(2)

            with col1:
                asset_type = st.selectbox(
                    "Typ av tillgång",
                    options=[t.value for t in AssetType],
                    index=0
                )
                from datetime import date as date_type
                acq_date = st.date_input("Anskaffningsdatum", value=date_type.today())
                acq_cost = st.number_input("Anskaffningsvärde (kr)", min_value=0.0, step=1000.0)

            with col2:
                residual = st.number_input("Restvärde (kr)", min_value=0.0, step=100.0, value=0.0)
                useful_life = st.number_input("Nyttjandeperiod (månader)", min_value=1, max_value=600, value=60)
                dep_method = st.selectbox(
                    "Avskrivningsmetod",
                    options=[m.value for m in DepreciationMethod],
                    index=0
                )

            st.write("**Koppling till konton:**")
            col3, col4, col5 = st.columns(3)

            with col3:
                asset_account = st.selectbox(
                    "Tillgångskonto",
                    options=["Automatiskt"] + account_list,
                    help="Ex: 1220 Inventarier"
                )
            with col4:
                dep_account = st.selectbox(
                    "Avskrivningskonto",
                    options=["Automatiskt"] + account_list,
                    help="Ex: 7832 Avskrivning inventarier"
                )
            with col5:
                acc_account = st.selectbox(
                    "Ack. avskrivningar",
                    options=["Automatiskt"] + account_list,
                    help="Ex: 1229 Ack avskr inventarier"
                )

            if st.form_submit_button("Registrera tillgång", type="primary"):
                if not name or acq_cost <= 0:
                    st.error("Fyll i namn och anskaffningsvärde")
                else:
                    try:
                        type_map = {t.value: t for t in AssetType}
                        method_map = {m.value: m for m in DepreciationMethod}

                        asset = dep_service.create_asset(
                            company_id=company_id,
                            name=name,
                            description=description,
                            asset_type=type_map[asset_type],
                            acquisition_date=acq_date,
                            acquisition_cost=Decimal(str(acq_cost)),
                            residual_value=Decimal(str(residual)),
                            useful_life_months=useful_life,
                            depreciation_method=method_map[dep_method],
                            asset_account_number=account_map.get(asset_account) if asset_account != "Automatiskt" else None,
                            depreciation_account_number=account_map.get(dep_account) if dep_account != "Automatiskt" else None,
                            accumulated_account_number=account_map.get(acc_account) if acc_account != "Automatiskt" else None,
                        )
                        st.success(f"Tillgång '{name}' registrerad!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fel: {e}")

    with tab3:
        show_shareholdings(service, db, company_id)

    with tab4:
        st.subheader("Kör periodavskrivningar")

        fiscal_years = service.get_fiscal_years(company_id)
        if not fiscal_years:
            st.warning("Inga räkenskapsår finns")
            return

        fiscal_year = fiscal_years[0]

        st.write(f"**Räkenskapsår:** {fiscal_year.start_date} - {fiscal_year.end_date}")

        from datetime import date as date_type
        period_date = st.date_input(
            "Avskrivningsdatum",
            value=date_type.today(),
            key="dep_date"
        )

        period_type = st.selectbox(
            "Periodicitet",
            options=["monthly", "quarterly", "annual"],
            format_func=lambda x: {"monthly": "Månadsvis", "quarterly": "Kvartalsvis", "annual": "Årsvis"}[x]
        )

        if st.button("Kör avskrivningar", type="primary"):
            try:
                transactions = dep_service.run_period_depreciation(
                    company_id=company_id,
                    fiscal_year_id=fiscal_year.id,
                    period_date=period_date,
                    period_type=period_type
                )

                if transactions:
                    st.success(f"{len(transactions)} avskrivningstransaktioner skapade!")
                    for tx in transactions:
                        st.write(f"- Ver {tx.verification_number}: {tx.description}")
                else:
                    st.info("Inga avskrivningar att göra (redan körda eller inga aktiva tillgångar)")

            except Exception as e:
                st.error(f"Fel vid avskrivning: {e}")


def show_shareholdings(service, db, company_id: int):
    """Visa och hantera aktieinnehav i onoterade bolag"""
    from app.models import Shareholding, ShareholdingType, ShareholdingTransaction
    from decimal import Decimal
    from datetime import date

    st.subheader("Aktieinnehav i onoterade bolag")

    st.write("""
    Hantera aktieinnehav i dotterbolag, intresseföretag och övriga onoterade aktier.
    """)

    # Lista befintliga innehav
    shareholdings = (
        db.query(Shareholding)
        .filter(Shareholding.company_id == company_id)
        .order_by(Shareholding.holding_type, Shareholding.target_company_name)
        .all()
    )

    if shareholdings:
        # Gruppera per typ
        grouped = {}
        for sh in shareholdings:
            if sh.holding_type not in grouped:
                grouped[sh.holding_type] = []
            grouped[sh.holding_type].append(sh)

        for holding_type, holdings in grouped.items():
            st.write(f"**{holding_type.value}:**")

            for sh in holdings:
                status = "Aktivt" if sh.is_active else "Avyttrat"
                with st.expander(f"{sh.target_company_name} ({sh.ownership_percentage or 0:.1f}%) - {status}"):
                    col1, col2 = st.columns(2)

                    with col1:
                        st.write(f"**Org.nummer:** {sh.target_org_number or 'Ej angivet'}")
                        st.write(f"**Land:** {sh.target_country}")
                        st.write(f"**Antal aktier:** {sh.num_shares:,}")
                        if sh.total_shares_in_target:
                            st.write(f"**Totalt aktier i bolaget:** {sh.total_shares_in_target:,}")
                        st.write(f"**Ägarandel:** {sh.ownership_percentage or 0:.2f}%")
                        if sh.voting_percentage:
                            st.write(f"**Röstandel:** {sh.voting_percentage:.2f}%")

                    with col2:
                        st.write(f"**Anskaffningsdatum:** {sh.acquisition_date}")
                        st.write(f"**Anskaffningsvärde:** {sh.acquisition_cost:,.2f} kr")
                        st.write(f"**Bokfört värde:** {sh.book_value:,.2f} kr")
                        if sh.total_impairment > 0:
                            st.write(f"**Nedskrivningar:** {sh.total_impairment:,.2f} kr")
                        if sh.market_value:
                            st.write(f"**Marknadsvärde:** {sh.market_value:,.2f} kr")
                        if sh.total_dividends_received > 0:
                            st.write(f"**Erhållna utdelningar:** {sh.total_dividends_received:,.2f} kr")

                    if sh.disposal_date:
                        st.divider()
                        st.write(f"**Avyttrad:** {sh.disposal_date}")
                        if sh.disposal_amount:
                            st.write(f"**Försäljningspris:** {sh.disposal_amount:,.2f} kr")
                        if sh.disposal_gain_loss:
                            result_type = "Vinst" if sh.disposal_gain_loss > 0 else "Förlust"
                            st.write(f"**{result_type}:** {abs(sh.disposal_gain_loss):,.2f} kr")

                    if sh.notes:
                        st.write(f"**Anteckningar:** {sh.notes}")

                    # Transaktionshistorik
                    transactions = (
                        db.query(ShareholdingTransaction)
                        .filter(ShareholdingTransaction.shareholding_id == sh.id)
                        .order_by(ShareholdingTransaction.transaction_date.desc())
                        .all()
                    )

                    if transactions:
                        st.divider()
                        st.write("**Transaktioner:**")
                        for tx in transactions:
                            type_labels = {
                                'purchase': 'Köp',
                                'sale': 'Försäljning',
                                'dividend': 'Utdelning',
                                'impairment': 'Nedskrivning',
                                'reversal': 'Återföring'
                            }
                            st.caption(f"{tx.transaction_date} - {type_labels.get(tx.transaction_type, tx.transaction_type)}: {tx.amount:,.2f} kr")

    else:
        st.info("Inga aktieinnehav registrerade")

    st.divider()

    # Lägg till nytt innehav
    st.write("**Registrera nytt aktieinnehav**")

    with st.form("new_shareholding"):
        target_name = st.text_input("Bolagets namn")
        target_org = st.text_input("Organisationsnummer", placeholder="XXXXXX-XXXX")

        col1, col2 = st.columns(2)

        with col1:
            holding_type = st.selectbox(
                "Typ av innehav",
                options=[ht for ht in ShareholdingType],
                format_func=lambda x: x.value
            )
            target_country = st.text_input("Land", value="Sverige")
            acq_date = st.date_input("Anskaffningsdatum", value=date.today())
            acq_cost = st.number_input("Anskaffningsvärde (kr)", min_value=0.0, step=1000.0)

        with col2:
            num_shares = st.number_input("Antal aktier", min_value=1, step=1)
            total_shares = st.number_input("Totalt antal aktier i bolaget (valfritt)", min_value=0, step=1)
            ownership_pct = st.number_input("Ägarandel (%)", min_value=0.0, max_value=100.0, step=0.01)
            voting_pct = st.number_input("Röstandel (%, valfritt)", min_value=0.0, max_value=100.0, step=0.01)

        # Koppling till konto
        accounts = service.get_accounts(company_id)
        account_options = {f"{a.number} - {a.name}": a.id for a in accounts if a.number.startswith('13')}
        selected_account = st.selectbox(
            "Tillgångskonto",
            options=["Inget"] + list(account_options.keys()),
            help="Ex: 1310 Andelar i koncernföretag"
        )

        notes = st.text_area("Anteckningar")

        if st.form_submit_button("Registrera innehav", type="primary"):
            if target_name and num_shares > 0 and acq_cost > 0:
                new_sh = Shareholding(
                    company_id=company_id,
                    target_company_name=target_name,
                    target_org_number=target_org if target_org else None,
                    target_country=target_country,
                    holding_type=holding_type,
                    num_shares=num_shares,
                    total_shares_in_target=total_shares if total_shares > 0 else None,
                    ownership_percentage=Decimal(str(ownership_pct)),
                    voting_percentage=Decimal(str(voting_pct)) if voting_pct > 0 else None,
                    acquisition_date=acq_date,
                    acquisition_cost=Decimal(str(acq_cost)),
                    acquisition_cost_per_share=Decimal(str(acq_cost / num_shares)),
                    book_value=Decimal(str(acq_cost)),
                    asset_account_id=account_options.get(selected_account) if selected_account != "Inget" else None,
                    is_active=True,
                    notes=notes if notes else None
                )

                db.add(new_sh)

                # Skapa initialtransaktion
                init_tx = ShareholdingTransaction(
                    shareholding_id=new_sh.id,
                    transaction_type='purchase',
                    transaction_date=acq_date,
                    num_shares=num_shares,
                    amount=Decimal(str(acq_cost)),
                    price_per_share=Decimal(str(acq_cost / num_shares)),
                    description=f"Initialt köp av {num_shares} aktier i {target_name}"
                )
                db.add(init_tx)

                db.commit()
                st.success(f"Aktieinnehav i {target_name} registrerat!")
                st.rerun()
            else:
                st.error("Fyll i namn, antal aktier och anskaffningsvärde")


def show_closing(service: AccountingService, db):
    """Visa bokslutsrutiner"""
    st.title("Bokslut")

    company_id = st.session_state.selected_company_id
    if not company_id:
        st.info("Välj ett företag först.")
        return

    from app.services.closing import ClosingService

    closing_service = ClosingService(db)

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
        index=0
    )
    fiscal_year = fiscal_year_options[selected_fy_name]

    if fiscal_year.is_closed:
        st.success("Detta räkenskapsår är stängt")
    else:
        st.info("Räkenskapsåret är öppet")

    tab1, tab2, tab3 = st.tabs(["Månadsbokslut", "Kvartalsbokslut", "Årsbokslut"])

    with tab1:
        st.subheader("Månadsbokslut")

        from datetime import date as date_type
        month_end = st.date_input(
            "Periodens slutdatum",
            value=fiscal_year.end_date,
            key="month_end"
        )

        if st.button("Utför månadsbokslut", key="monthly_close"):
            result = closing_service.close_month(company_id, month_end)

            st.write(f"**Periodens resultat:** {result['result']:,.2f} kr")

            # Visa checklista
            st.write("**Checklista:**")
            for item in result['checklist']:
                status_icon = "✓" if item['status'] == 'passed' else "○" if item['status'] == 'pending' else "✗"
                st.write(f"{status_icon} {item['task']}: {item['description']}")

            # Visa validering
            if result['validation']['errors']:
                st.error("Fel:")
                for error in result['validation']['errors']:
                    st.write(f"- {error}")
            if result['validation']['warnings']:
                st.warning("Varningar:")
                for warning in result['validation']['warnings']:
                    st.write(f"- {warning}")

    with tab2:
        st.subheader("Kvartalsbokslut")

        from datetime import date as date_type
        quarter_end = st.date_input(
            "Kvartalets slutdatum",
            value=fiscal_year.end_date,
            key="quarter_end"
        )

        if st.button("Utför kvartalsbokslut", key="quarterly_close"):
            result = closing_service.close_quarter(company_id, quarter_end)

            st.write(f"**Kvartalets resultat:** {result['result']:,.2f} kr")

            st.write("**Checklista:**")
            for item in result['checklist']:
                status_icon = "✓" if item['status'] == 'passed' else "○" if item['status'] == 'pending' else "✗"
                st.write(f"{status_icon} {item['task']}: {item['description']}")

            if result['validation']['errors']:
                st.error("Fel:")
                for error in result['validation']['errors']:
                    st.write(f"- {error}")

    with tab3:
        st.subheader("Årsbokslut")

        st.write(f"**Räkenskapsår:** {fiscal_year.start_date} - {fiscal_year.end_date}")

        # Beräkna årsresultat
        result_amount = closing_service.calculate_period_result(
            company_id,
            fiscal_year.start_date,
            fiscal_year.end_date
        )
        st.metric("Årets resultat", f"{result_amount:,.2f} kr")

        create_disposition = st.checkbox(
            "Skapa resultatdisposition (2099 -> 2098)",
            value=True,
            help="Överför årets resultat till balanserat resultat"
        )

        st.warning("""
        **OBS!** Årsbokslut stänger räkenskapsåret permanent.
        Se till att alla periodiseringar och avskrivningar är gjorda innan.
        """)

        if fiscal_year.is_closed:
            st.info("Räkenskapsåret är redan stängt")
        else:
            if st.button("Utför årsbokslut", type="primary", key="annual_close"):
                try:
                    result = closing_service.close_year(
                        company_id,
                        fiscal_year.id,
                        create_result_disposition=create_disposition
                    )

                    if result['status'] == 'closed':
                        st.success("Årsbokslut genomfört!")
                        st.write(f"**Årets resultat:** {result['result']:,.2f} kr")
                        if result['disposition_transaction']:
                            st.write(f"**Resultatdisposition:** Ver {result['disposition_transaction']}")
                        st.rerun()
                    else:
                        st.error("Årsbokslut kunde inte genomföras")
                        for error in result['validation']['errors']:
                            st.write(f"- {error}")

                except Exception as e:
                    st.error(f"Fel vid årsbokslut: {e}")


def show_settings(service: AccountingService):
    """Visa inställningar"""
    st.title("Inställningar")

    company_id = st.session_state.selected_company_id
    if not company_id:
        st.info("Välj ett företag först.")
        return

    from app.models import get_db, CompanyDocument, DocumentType, AnnualReport, Company
    from datetime import date
    import base64

    db = next(get_db())
    # Hämta company från samma session som vi använder för att spara
    company = db.query(Company).filter(Company.id == company_id).first()

    # Flikar för olika inställningar
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Företagsuppgifter",
        "Dokument",
        "Årsredovisningar",
        "Räkenskapsår",
        "Backup"
    ])

    with tab1:
        show_company_info(service, db, company)

    with tab2:
        show_company_documents(db, company_id)

    with tab3:
        show_annual_reports(service, db, company_id)

    with tab4:
        show_fiscal_years_settings(service, company_id)

    with tab5:
        show_backup_settings(db)

    db.close()


def show_company_info(service, db, company):
    """Visa och redigera företagsuppgifter inkl logotyp"""
    import base64

    st.subheader(f"Företag: {company.name}")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.write(f"**Organisationsnummer:** {company.org_number}")
        st.write(f"**Redovisningsstandard:** {company.accounting_standard.value}")

        if company.address:
            st.write(f"**Adress:** {company.address}")
        if company.postal_code and company.city:
            st.write(f"**Postadress:** {company.postal_code} {company.city}")
        if company.email:
            st.write(f"**E-post:** {company.email}")
        if company.phone:
            st.write(f"**Telefon:** {company.phone}")
        if company.website:
            st.write(f"**Webbplats:** {company.website}")

    with col2:
        # Visa logotyp
        if company.logo:
            # Konvertera från memoryview/bytes till bytes om nödvändigt
            logo_bytes = bytes(company.logo) if company.logo else None
            if logo_bytes:
                st.image(logo_bytes, width=150, caption="Företagslogotyp")
        else:
            st.info("Ingen logotyp uppladdad")

    st.divider()

    # Redigera företagsuppgifter
    with st.expander("Redigera företagsuppgifter"):
        with st.form("edit_company"):
            name = st.text_input("Företagsnamn", value=company.name)
            address = st.text_input("Gatuadress", value=company.address or "")
            col1, col2 = st.columns(2)
            with col1:
                postal_code = st.text_input("Postnummer", value=company.postal_code or "")
            with col2:
                city = st.text_input("Ort", value=company.city or "")
            email = st.text_input("E-post", value=company.email or "")
            phone = st.text_input("Telefon", value=company.phone or "")
            website = st.text_input("Webbplats", value=company.website or "")

            if st.form_submit_button("Spara ändringar"):
                company.name = name
                company.address = address
                company.postal_code = postal_code
                company.city = city
                company.email = email
                company.phone = phone
                company.website = website
                db.commit()
                st.success("Uppgifter uppdaterade!")
                st.rerun()

    # Ladda upp logotyp
    st.write("**Logotyp**")
    uploaded_logo = st.file_uploader(
        "Ladda upp logotyp",
        type=['png', 'jpg', 'jpeg', 'svg'],
        help="Rekommenderad storlek: 200x200 pixlar. Visas i rapporter."
    )

    if uploaded_logo:
        # Förhandsgranska
        st.image(uploaded_logo, width=150, caption="Förhandsgranskning")

        if st.button("Spara logotyp", type="primary"):
            logo_data = uploaded_logo.read()
            company.logo = logo_data
            company.logo_filename = uploaded_logo.name
            company.logo_mimetype = uploaded_logo.type
            db.commit()
            st.success("Logotyp sparad!")
            st.rerun()

    if company.logo:
        if st.button("Ta bort logotyp"):
            company.logo = None
            company.logo_filename = None
            company.logo_mimetype = None
            db.commit()
            st.success("Logotyp borttagen!")
            st.rerun()


def show_company_documents(db, company_id: int):
    """Visa och hantera företagsdokument med versionshistorik"""
    from app.models import CompanyDocument, DocumentType
    from datetime import date

    st.subheader("Företagsdokument")

    st.write("""
    Ladda upp viktiga dokument som registreringsbevis, F-skattebevis, bolagsordning etc.
    Dokumenten versionshanteras automatiskt - gamla versioner sparas som historik.
    """)

    # Lista befintliga dokument
    documents = (
        db.query(CompanyDocument)
        .filter(CompanyDocument.company_id == company_id, CompanyDocument.is_current == True)
        .order_by(CompanyDocument.document_type, CompanyDocument.uploaded_at.desc())
        .all()
    )

    if documents:
        for doc in documents:
            with st.expander(f"{doc.document_type.value}: {doc.name}"):
                col1, col2 = st.columns([2, 1])

                with col1:
                    st.write(f"**Filnamn:** {doc.filename}")
                    st.write(f"**Storlek:** {doc.file_size / 1024:.1f} KB")
                    st.write(f"**Uppladdad:** {doc.uploaded_at.strftime('%Y-%m-%d %H:%M')}")
                    st.write(f"**Version:** {doc.version}")

                    if doc.valid_from:
                        st.write(f"**Giltig från:** {doc.valid_from}")
                    if doc.valid_until:
                        st.write(f"**Giltig till:** {doc.valid_until}")
                    if doc.issuer:
                        st.write(f"**Utfärdare:** {doc.issuer}")
                    if doc.reference_number:
                        st.write(f"**Referens:** {doc.reference_number}")
                    if doc.notes:
                        st.write(f"**Anteckningar:** {doc.notes}")

                with col2:
                    # Ladda ner
                    st.download_button(
                        "Ladda ner",
                        data=doc.file_data,
                        file_name=doc.filename,
                        mime=doc.mimetype,
                        key=f"dl_{doc.id}"
                    )

                # Visa versionshistorik
                previous_versions = (
                    db.query(CompanyDocument)
                    .filter(
                        CompanyDocument.company_id == company_id,
                        CompanyDocument.document_type == doc.document_type,
                        CompanyDocument.is_current == False
                    )
                    .order_by(CompanyDocument.version.desc())
                    .all()
                )

                if previous_versions:
                    st.write("**Tidigare versioner:**")
                    for old_doc in previous_versions:
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.caption(f"v{old_doc.version} - {old_doc.uploaded_at.strftime('%Y-%m-%d')}")
                        with col2:
                            st.download_button(
                                "Ladda ner",
                                data=old_doc.file_data,
                                file_name=f"v{old_doc.version}_{old_doc.filename}",
                                mime=old_doc.mimetype,
                                key=f"dl_old_{old_doc.id}"
                            )
    else:
        st.info("Inga dokument uppladdade")

    st.divider()

    # Ladda upp nytt dokument
    st.write("**Ladda upp nytt dokument**")

    with st.form("upload_document"):
        doc_type = st.selectbox(
            "Dokumenttyp",
            options=[dt for dt in DocumentType],
            format_func=lambda x: x.value
        )

        name = st.text_input("Beskrivande namn", placeholder="T.ex. 'Registreringsbevis 2024'")

        uploaded_file = st.file_uploader(
            "Välj fil",
            type=['pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx']
        )

        col1, col2 = st.columns(2)
        with col1:
            valid_from = st.date_input("Giltig från", value=date.today())
        with col2:
            valid_until = st.date_input("Giltig till (valfritt)", value=None)

        issuer = st.text_input("Utfärdare", placeholder="T.ex. 'Bolagsverket'")
        reference = st.text_input("Referensnummer", placeholder="Ärendenummer etc.")
        notes = st.text_area("Anteckningar")

        if st.form_submit_button("Ladda upp", type="primary"):
            if uploaded_file and name:
                file_data = uploaded_file.read()

                # Kolla om det finns ett befintligt dokument av samma typ
                existing = (
                    db.query(CompanyDocument)
                    .filter(
                        CompanyDocument.company_id == company_id,
                        CompanyDocument.document_type == doc_type,
                        CompanyDocument.is_current == True
                    )
                    .first()
                )

                new_version = 1
                if existing:
                    # Markera gamla som icke-aktuell
                    existing.is_current = False
                    new_version = existing.version + 1

                # Skapa nytt dokument
                new_doc = CompanyDocument(
                    company_id=company_id,
                    document_type=doc_type,
                    name=name,
                    file_data=file_data,
                    filename=uploaded_file.name,
                    mimetype=uploaded_file.type,
                    file_size=len(file_data),
                    version=new_version,
                    parent_id=existing.id if existing else None,
                    is_current=True,
                    valid_from=valid_from,
                    valid_until=valid_until if valid_until else None,
                    issuer=issuer if issuer else None,
                    reference_number=reference if reference else None,
                    notes=notes if notes else None
                )

                db.add(new_doc)
                db.commit()

                if existing:
                    st.success(f"Dokument uppdaterat (version {new_version})!")
                else:
                    st.success("Dokument uppladdat!")
                st.rerun()
            else:
                st.error("Fyll i namn och välj en fil")


def show_annual_reports(service, db, company_id: int):
    """Visa register över inskickade årsredovisningar"""
    from app.models import AnnualReport
    from datetime import date

    st.subheader("Årsredovisningar")

    st.write("""
    Register över inskickade årsredovisningar till Bolagsverket.
    Håll reda på status och viktiga datum.
    """)

    # Hämta räkenskapsår
    fiscal_years = service.get_fiscal_years(company_id)

    # Lista befintliga årsredovisningar
    reports = (
        db.query(AnnualReport)
        .filter(AnnualReport.company_id == company_id)
        .order_by(AnnualReport.fiscal_year_end.desc())
        .all()
    )

    if reports:
        for report in reports:
            status_icons = {
                'draft': '📝',
                'submitted': '📤',
                'registered': '✅',
                'rejected': '❌'
            }
            status_icon = status_icons.get(report.status, '❓')

            with st.expander(f"{status_icon} {report.fiscal_year_start} - {report.fiscal_year_end}"):
                col1, col2 = st.columns(2)

                with col1:
                    st.write(f"**Status:** {report.status.capitalize()}")
                    if report.submitted_date:
                        st.write(f"**Inskickad:** {report.submitted_date}")
                    if report.registered_date:
                        st.write(f"**Registrerad:** {report.registered_date}")
                    if report.bolagsverket_reference:
                        st.write(f"**Bolagsverkets ref:** {report.bolagsverket_reference}")

                with col2:
                    if report.revenue:
                        st.metric("Omsättning", f"{report.revenue:,} kr")
                    if report.profit_loss:
                        st.metric("Resultat", f"{report.profit_loss:,} kr")

                # Revisorns uppgifter
                if report.auditor_name:
                    st.write(f"**Revisor:** {report.auditor_name}")
                    if report.auditor_opinion:
                        opinions = {
                            'clean': 'Ren revisionsberättelse',
                            'qualified': 'Med anmärkning',
                            'adverse': 'Avvikande mening',
                            'disclaimer': 'Avstår uttalande'
                        }
                        st.write(f"**Utlåtande:** {opinions.get(report.auditor_opinion, report.auditor_opinion)}")

                # Ladda ner årsredovisning
                if report.report_file:
                    st.download_button(
                        "Ladda ner årsredovisning",
                        data=report.report_file,
                        file_name=report.report_filename or f"arsredovisning_{report.fiscal_year_end.year}.pdf",
                        mime="application/pdf",
                        key=f"dl_ar_{report.id}"
                    )

                if report.notes:
                    st.write(f"**Anteckningar:** {report.notes}")

                # Uppdatera status
                st.divider()
                col1, col2, col3 = st.columns(3)

                with col1:
                    new_status = st.selectbox(
                        "Ändra status",
                        options=['draft', 'submitted', 'registered', 'rejected'],
                        index=['draft', 'submitted', 'registered', 'rejected'].index(report.status),
                        key=f"status_{report.id}"
                    )

                with col2:
                    new_submitted = st.date_input(
                        "Inskickad datum",
                        value=report.submitted_date,
                        key=f"submitted_{report.id}"
                    )

                with col3:
                    new_registered = st.date_input(
                        "Registrerad datum",
                        value=report.registered_date,
                        key=f"registered_{report.id}"
                    )

                if st.button("Spara ändringar", key=f"save_{report.id}"):
                    report.status = new_status
                    report.submitted_date = new_submitted if new_submitted else None
                    report.registered_date = new_registered if new_registered else None
                    db.commit()
                    st.success("Uppdaterat!")
                    st.rerun()
    else:
        st.info("Inga årsredovisningar registrerade")

    st.divider()

    # Lägg till ny årsredovisning
    st.write("**Registrera ny årsredovisning**")

    with st.form("new_annual_report"):
        # Välj räkenskapsår
        if fiscal_years:
            fy_options = {f"{fy.start_date} - {fy.end_date}": fy for fy in fiscal_years}
            selected_fy = st.selectbox("Räkenskapsår", options=list(fy_options.keys()))
            fiscal_year = fy_options[selected_fy]
        else:
            st.warning("Skapa ett räkenskapsår först")
            fiscal_year = None

        col1, col2 = st.columns(2)
        with col1:
            revenue = st.number_input("Omsättning (kr)", min_value=0, step=1000)
            profit_loss = st.number_input("Resultat (kr)", step=1000)
        with col2:
            total_assets = st.number_input("Balansomslutning (kr)", min_value=0, step=1000)
            equity = st.number_input("Eget kapital (kr)", step=1000)

        num_employees = st.number_input("Antal anställda", min_value=0, step=1)

        st.write("**Revisor**")
        auditor_name = st.text_input("Revisorns namn")
        auditor_opinion = st.selectbox(
            "Revisionsutlåtande",
            options=[None, 'clean', 'qualified', 'adverse', 'disclaimer'],
            format_func=lambda x: {
                None: "Ej granskat",
                'clean': 'Ren revisionsberättelse',
                'qualified': 'Med anmärkning',
                'adverse': 'Avvikande mening',
                'disclaimer': 'Avstår uttalande'
            }.get(x, x)
        )

        report_file = st.file_uploader("Årsredovisning (PDF)", type=['pdf'])

        notes = st.text_area("Anteckningar")

        if st.form_submit_button("Registrera", type="primary"):
            if fiscal_year:
                # Kolla om det redan finns en för detta räkenskapsår
                existing = (
                    db.query(AnnualReport)
                    .filter(
                        AnnualReport.company_id == company_id,
                        AnnualReport.fiscal_year_id == fiscal_year.id
                    )
                    .first()
                )

                if existing:
                    st.error("Det finns redan en årsredovisning för detta räkenskapsår")
                else:
                    new_report = AnnualReport(
                        company_id=company_id,
                        fiscal_year_id=fiscal_year.id,
                        fiscal_year_start=fiscal_year.start_date,
                        fiscal_year_end=fiscal_year.end_date,
                        status='draft',
                        revenue=revenue if revenue else None,
                        profit_loss=profit_loss if profit_loss else None,
                        total_assets=total_assets if total_assets else None,
                        equity=equity if equity else None,
                        num_employees=num_employees if num_employees else None,
                        auditor_name=auditor_name if auditor_name else None,
                        auditor_opinion=auditor_opinion,
                        notes=notes if notes else None
                    )

                    if report_file:
                        new_report.report_file = report_file.read()
                        new_report.report_filename = report_file.name

                    db.add(new_report)
                    db.commit()
                    st.success("Årsredovisning registrerad!")
                    st.rerun()


def show_fiscal_years_settings(service, company_id: int):
    """Visa och hantera räkenskapsår"""
    from datetime import date

    st.subheader("Räkenskapsår")

    fiscal_years = service.get_fiscal_years(company_id)

    if fiscal_years:
        for fy in fiscal_years:
            status = "🔒 Stängt" if fy.is_closed else "✅ Aktivt"
            st.write(f"**{fy.start_date} - {fy.end_date}** {status}")
    else:
        st.info("Inga räkenskapsår")

    with st.form("new_fiscal_year"):
        st.write("**Skapa nytt räkenskapsår**")
        start = st.date_input("Startdatum", value=date(date.today().year, 1, 1))
        end = st.date_input("Slutdatum", value=date(date.today().year, 12, 31))

        if st.form_submit_button("Skapa räkenskapsår"):
            try:
                fy = service.create_fiscal_year(company_id, start, end)
                st.success(f"Räkenskapsår {start} - {end} skapat!")
                st.rerun()
            except Exception as e:
                st.error(f"Fel: {e}")


def show_backup_settings(db):
    """Visa och konfigurera backup-inställningar"""
    from app.services.backup import BackupService, BackupConfig

    st.subheader("Säkerhetskopiering")

    st.write("""
    Konfigurera automatisk säkerhetskopiering till en nätverksplats.
    Om datorn inte är ansluten till nätverket vid backup-tillfället,
    körs kopieringen automatiskt när anslutningen återupprättas.
    """)

    # Ladda konfiguration
    config = BackupConfig()

    # Backup-sökväg
    st.write("**Backup-plats**")
    backup_path = st.text_input(
        "Sökväg till backup-mapp",
        value=config.backup_path,
        placeholder="/Volumes/NAS/backup/bokforing eller //server/share/backup",
        help="Ange sökväg till en mapp på ditt lokala nätverk"
    )

    col1, col2 = st.columns(2)
    with col1:
        interval = st.number_input(
            "Backup-intervall (timmar)",
            min_value=1,
            max_value=168,
            value=config.interval_hours,
            help="Hur ofta backup ska köras"
        )
    with col2:
        retention = st.number_input(
            "Behåll backups (dagar)",
            min_value=7,
            max_value=365,
            value=config.retention_days,
            help="Hur länge gamla backups sparas"
        )

    enabled = st.checkbox("Aktivera automatisk backup", value=config.enabled)

    if st.button("Spara inställningar"):
        config.backup_path = backup_path
        config.interval_hours = interval
        config.retention_days = retention
        config.enabled = enabled
        st.success("Inställningar sparade!")

    st.divider()

    # Manuell backup
    st.write("**Manuell backup**")

    if backup_path:
        backup_service = BackupService(
            db_path="data/bokforing.db",
            backup_base_path=backup_path,
            retention_days=retention
        )

        col1, col2 = st.columns(2)

        with col1:
            if backup_service.is_network_available():
                st.success("Nätverksplatsen är tillgänglig")
            else:
                st.warning("Nätverksplatsen är inte tillgänglig")

        with col2:
            if st.button("Kör backup nu", type="primary"):
                with st.spinner("Skapar backup..."):
                    result = backup_service.create_backup(db)

                if result['success']:
                    st.success(f"Backup skapad: {result['backup_name']}")
                    config.last_backup = result['backup_name']
                else:
                    st.error(f"Backup misslyckades: {result.get('error', 'Okänt fel')}")

        # Lista befintliga backups
        st.divider()
        st.write("**Befintliga backups**")

        backups = backup_service.list_backups()
        if backups:
            for backup in backups[:10]:  # Visa max 10
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    st.write(f"**{backup['name']}**")
                with col2:
                    size_mb = backup['db_size'] / (1024 * 1024) if backup['db_size'] else 0
                    st.caption(f"{size_mb:.1f} MB, {backup['documents_count']} dok")
                with col3:
                    if st.button("Återställ", key=f"restore_{backup['name']}"):
                        if st.session_state.get(f"confirm_restore_{backup['name']}"):
                            result = backup_service.restore_backup(backup['name'])
                            if result['success']:
                                st.success("Återställd! Starta om appen.")
                            else:
                                st.error(f"Fel: {result.get('error')}")
                        else:
                            st.session_state[f"confirm_restore_{backup['name']}"] = True
                            st.warning("Klicka igen för att bekräfta återställning")
        else:
            st.info("Inga backups hittades")
    else:
        st.info("Ange en backup-sökväg för att aktivera backup-funktionen")

    # Dokumentexport
    st.divider()
    st.write("**Exportera alla dokument**")
    st.write("Ladda ner alla uppladdade dokument som en ZIP-fil.")

    if st.button("Exportera dokument"):
        from app.models import CompanyDocument
        import zipfile
        import io

        documents = db.query(CompanyDocument).all()

        if documents:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for doc in documents:
                    filename = f"{doc.document_type.value}/{doc.filename}"
                    zip_file.writestr(filename, doc.file_data)

            st.download_button(
                "Ladda ner ZIP",
                data=zip_buffer.getvalue(),
                file_name=f"dokument_export_{date.today()}.zip",
                mime="application/zip"
            )
        else:
            st.info("Inga dokument att exportera")


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
    och föreslår en bokföringstransaktion. Om OCR misslyckas kan du
    registrera transaktionen manuellt.
    """)

    # Filuppladdning
    uploaded_file = st.file_uploader(
        "Välj dokument",
        type=['pdf', 'jpg', 'jpeg', 'png', 'webp'],
        help="Stödjer PDF, JPG, PNG och WEBP"
    )

    if uploaded_file:
        # Visa dokumentförhandsgranskning
        st.subheader("Dokument")
        col_preview, col_data = st.columns([1, 1])

        with col_preview:
            if uploaded_file.type.startswith('image/'):
                st.image(uploaded_file, use_container_width=True)
            else:
                st.info(f"PDF: {uploaded_file.name}")

        # Läs filinnehåll
        file_content = uploaded_file.read()
        uploaded_file.seek(0)

        # Bearbeta dokument med OCR
        processor = DocumentProcessor()
        try:
            with st.spinner("Analyserar dokument..."):
                extracted = processor.process_file(file_content, uploaded_file.name)
            ocr_success = extracted.raw_text and len(extracted.raw_text) > 10
        except Exception:
            extracted = None
            ocr_success = False

        with col_data:
            if ocr_success:
                confidence_pct = int(extracted.confidence * 100)
                st.progress(extracted.confidence, text=f"OCR Konfidens: {confidence_pct}%")
                if extracted.confidence < 0.5:
                    st.warning("Låg konfidens - överväg manuell registrering")
            else:
                st.warning("OCR kunde inte läsa dokumentet")

        st.divider()

        # Flikar för OCR-resultat och manuell registrering
        tab1, tab2 = st.tabs(["OCR-resultat", "Manuell registrering"])

        # Hämta konton för båda flikarna
        accounts = service.get_accounts(company_id)
        account_options = {f"{a.number} - {a.name}": a.id for a in accounts}
        account_list = list(account_options.keys())

        with tab1:
            if ocr_success:
                with st.form("ocr_transaction_form"):
                    st.write("**Justera och spara transaktion**")

                    from datetime import date as date_type

                    tx_date = st.date_input(
                        "Datum",
                        value=extracted.date or date_type.today(),
                        key="ocr_date"
                    )

                    description = st.text_input(
                        "Beskrivning",
                        value=extracted.description or "",
                        key="ocr_desc"
                    )

                    total = st.number_input(
                        "Totalbelopp (inkl moms)",
                        value=float(extracted.total_amount or 0),
                        min_value=0.0,
                        step=10.0,
                        key="ocr_total"
                    )

                    vat_rate = st.selectbox(
                        "Momssats",
                        options=[25, 12, 6, 0],
                        index=0 if not extracted.vat_rate else [25, 12, 6, 0].index(extracted.vat_rate),
                        key="ocr_vat"
                    )

                    suggestions = suggest_accounts(extracted)
                    st.write(f"**Kategori:** {suggestions['category']}")

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
                        index=account_list.index(expense_default) if expense_default in account_list else 0,
                        key="ocr_expense"
                    )

                    payment_account = st.selectbox(
                        "Betalkonto",
                        options=account_list,
                        index=account_list.index(payment_default) if payment_default in account_list else 0,
                        key="ocr_payment"
                    )

                    if st.form_submit_button("Skapa transaktion", type="primary"):
                        if total > 0 and description:
                            try:
                                from decimal import Decimal

                                total_dec = Decimal(str(total))
                                if vat_rate > 0:
                                    vat_amount = total_dec * Decimal(vat_rate) / Decimal(100 + vat_rate)
                                    net_amount = total_dec - vat_amount
                                else:
                                    vat_amount = Decimal(0)
                                    net_amount = total_dec

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

                                if vat_rate > 0:
                                    vat_account = next(
                                        (a for a in accounts if a.number == "2640"),
                                        None
                                    )
                                    if vat_account:
                                        lines.insert(1, {
                                            "account_id": vat_account.id,
                                            "debit": vat_amount.quantize(Decimal('0.01')),
                                            "credit": Decimal(0)
                                        })

                                tx = service.create_transaction(
                                    company_id=company_id,
                                    fiscal_year_id=fiscal_year.id,
                                    transaction_date=tx_date,
                                    description=description,
                                    lines=lines
                                )

                                voucher_path = processor.save_voucher(file_content, uploaded_file.name)
                                st.success(f"Transaktion {tx.verification_number} skapad!")
                                st.info(f"Verifikat sparat: {voucher_path}")
                                st.rerun()

                            except Exception as e:
                                st.error(f"Fel vid skapande: {e}")
                        else:
                            st.error("Fyll i belopp och beskrivning")

                with st.expander("Visa extraherad text"):
                    st.text(extracted.raw_text[:2000] if len(extracted.raw_text) > 2000 else extracted.raw_text)
            else:
                st.info("Ingen OCR-data tillgänglig. Använd fliken 'Manuell registrering' för att bokföra dokumentet.")

        with tab2:
            st.write("**Registrera transaktion manuellt**")
            st.write("Lägg till konteringsrader. Summa debet måste vara lika med summa kredit.")

            with st.form("manual_transaction_form"):
                from datetime import date as date_type

                manual_date = st.date_input(
                    "Datum",
                    value=date_type.today(),
                    key="manual_date"
                )

                manual_description = st.text_input(
                    "Beskrivning",
                    key="manual_desc"
                )

                st.write("**Konteringsrader:**")

                # Initiera session state för antal rader
                if 'manual_rows' not in st.session_state:
                    st.session_state.manual_rows = 4

                manual_lines = []
                total_debit = 0.0
                total_credit = 0.0

                for i in range(st.session_state.manual_rows):
                    col1, col2, col3 = st.columns([3, 1, 1])
                    with col1:
                        acc = st.selectbox(
                            f"Konto {i+1}",
                            options=[""] + account_list,
                            key=f"manual_acc_{i}"
                        )
                    with col2:
                        debit = st.number_input(
                            f"Debet {i+1}",
                            min_value=0.0,
                            step=100.0,
                            key=f"manual_debit_{i}"
                        )
                    with col3:
                        credit = st.number_input(
                            f"Kredit {i+1}",
                            min_value=0.0,
                            step=100.0,
                            key=f"manual_credit_{i}"
                        )

                    if acc and (debit > 0 or credit > 0):
                        manual_lines.append({
                            "account": acc,
                            "debit": debit,
                            "credit": credit
                        })
                        total_debit += debit
                        total_credit += credit

                # Visa summa
                st.divider()
                col_sum1, col_sum2, col_sum3 = st.columns([3, 1, 1])
                with col_sum1:
                    st.write("**Summa:**")
                with col_sum2:
                    st.write(f"**{total_debit:,.2f}**")
                with col_sum3:
                    st.write(f"**{total_credit:,.2f}**")

                # Balansindikator
                if total_debit > 0 or total_credit > 0:
                    diff = abs(total_debit - total_credit)
                    if diff < 0.01:
                        st.success("Transaktionen balanserar")
                    else:
                        st.error(f"Differens: {diff:,.2f} kr")

                if st.form_submit_button("Spara transaktion", type="primary"):
                    if not manual_description:
                        st.error("Ange en beskrivning")
                    elif len(manual_lines) < 2:
                        st.error("Minst 2 konteringsrader krävs")
                    elif abs(total_debit - total_credit) >= 0.01:
                        st.error("Transaktionen balanserar inte (debet != kredit)")
                    else:
                        try:
                            from decimal import Decimal

                            lines = []
                            for line in manual_lines:
                                lines.append({
                                    "account_id": account_options[line["account"]],
                                    "debit": Decimal(str(line["debit"])),
                                    "credit": Decimal(str(line["credit"]))
                                })

                            tx = service.create_transaction(
                                company_id=company_id,
                                fiscal_year_id=fiscal_year.id,
                                transaction_date=manual_date,
                                description=manual_description,
                                lines=lines
                            )

                            # Spara verifikat
                            voucher_path = processor.save_voucher(file_content, uploaded_file.name)

                            st.success(f"Transaktion {tx.verification_number} skapad!")
                            st.info(f"Verifikat sparat: {voucher_path}")
                            st.rerun()

                        except Exception as e:
                            st.error(f"Fel vid skapande: {e}")

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
