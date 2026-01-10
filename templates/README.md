# Dokumentmallar

Denna mapp innehåller Jinja2-mallar för generering av rapporter och dokument.

## Mappstruktur

- `arsredovisning/` - Mallar för årsredovisning (K2/K3)
- `rapporter/` - Finansiella rapporter (resultat, balans, råbalans)
- `protokoll/` - Mötes- och styrelseprotokoll
- `register/` - Aktiebok och andra register

## Mallnamn

| Fil | Beskrivning |
|-----|-------------|
| `arsredovisning/k2_arsredovisning.html` | Årsredovisning enligt K2 |
| `arsredovisning/k3_arsredovisning.html` | Årsredovisning enligt K3 |
| `rapporter/resultatrakning.html` | Resultaträkning |
| `rapporter/balansrakning.html` | Balansräkning |
| `rapporter/rabalans.html` | Råbalans |
| `rapporter/huvudbok.html` | Huvudbok |
| `register/aktiebok.html` | Aktiebok |
| `protokoll/styrelsemote.html` | Styrelseprotokoll |
| `protokoll/bolagsstamma.html` | Bolagsstämmoprotokoll |

## Tillgängliga variabler i mallar

### Företagsdata
```jinja2
{{ company.name }}           # Företagsnamn
{{ company.org_number }}     # Organisationsnummer
{{ company.address }}        # Adress
{{ company.postal_code }}    # Postnummer
{{ company.city }}           # Ort
{{ company.email }}          # E-post
{{ company.phone }}          # Telefon
{{ logo_base64 }}            # Logotyp som base64 (för <img src>)
```

### Räkenskapsår
```jinja2
{{ fiscal_year.start_date }}  # Startdatum
{{ fiscal_year.end_date }}    # Slutdatum
{{ fiscal_year.is_closed }}   # Om året är stängt
```

### Finansiell data
```jinja2
{{ income_statement.revenue }}         # Lista med intäktskonton
{{ income_statement.expenses }}        # Lista med kostnadskonton
{{ income_statement.total_revenue }}   # Summa intäkter
{{ income_statement.total_expenses }}  # Summa kostnader

{{ balance_sheet.assets }}             # Lista med tillgångskonton
{{ balance_sheet.liabilities }}        # Lista med skuld/EK-konton
{{ balance_sheet.total_assets }}       # Summa tillgångar
{{ balance_sheet.total_liabilities }}  # Summa skulder

{{ trial_balance }}                    # Råbalans (lista med alla konton)
{{ result }}                           # Årets resultat
```

### Filter
```jinja2
{{ value|currency }}           # Formaterar som "1 234 kr"
{{ date|date_format }}         # Formaterar datum som "2024-01-15"
{{ date|date_format('%d %B %Y') }}  # Anpassat datumformat
```

## Exempel på mall

```html
<!DOCTYPE html>
<html lang="sv">
<head>
    <meta charset="UTF-8">
    <title>Resultaträkning - {{ company.name }}</title>
</head>
<body>
    {% if logo_base64 %}
    <img src="{{ logo_base64 }}" alt="Logotyp" style="max-width: 150px;">
    {% endif %}

    <h1>Resultaträkning</h1>
    <h2>{{ company.name }}</h2>
    <p>Org.nr: {{ company.org_number }}</p>
    <p>Räkenskapsår: {{ fiscal_year.start_date }} - {{ fiscal_year.end_date }}</p>

    <h3>Intäkter</h3>
    <table>
        {% for item in income_statement.revenue %}
        <tr>
            <td>{{ item.account_number }}</td>
            <td>{{ item.account_name }}</td>
            <td>{{ item.balance|currency }}</td>
        </tr>
        {% endfor %}
        <tr>
            <td colspan="2"><strong>Summa intäkter</strong></td>
            <td><strong>{{ income_statement.total_revenue|currency }}</strong></td>
        </tr>
    </table>

    <h3>Kostnader</h3>
    <table>
        {% for item in income_statement.expenses %}
        <tr>
            <td>{{ item.account_number }}</td>
            <td>{{ item.account_name }}</td>
            <td>{{ item.balance|currency }}</td>
        </tr>
        {% endfor %}
        <tr>
            <td colspan="2"><strong>Summa kostnader</strong></td>
            <td><strong>{{ income_statement.total_expenses|currency }}</strong></td>
        </tr>
    </table>

    <h3>Resultat</h3>
    <p><strong>Årets resultat: {{ result|currency }}</strong></p>

    <footer>
        <p>Genererad: {{ generated_at|date_format }}</p>
    </footer>
</body>
</html>
```

## Skapa egna mallar

1. Skapa en HTML-fil i lämplig undermapp
2. Använd Jinja2-syntax för dynamiskt innehåll
3. Testa mallen genom att generera en rapport i systemet
4. Mallarna renderas till HTML som kan skrivas ut eller konverteras till PDF
