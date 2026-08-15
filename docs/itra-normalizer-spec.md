# ITRA Normalizer — Demo-spec (build-ready)

> Version 4 — opdateret på baggrund af to rigtige syntetiske ITRA-eksempler (Site Indigo / SYN-009 og Site Juniper / SYN-010). Denne version er skrevet så den kan bruges som input til en kodende agent (Claude Code, Codex e.l.) til at bygge demoen.

**Medfølgende filer (lever sammen med denne spec til den kodende agent):**

- `itra-normalizer-fixtures.zip` — indeholder de to kilde-PDF'er samt **allerede håndudtrukket, valideret JSON** for begge sites (`data/parsed/SYN-009.json`, `data/parsed/SYN-010.json`) og en delt `data/control_catalog.json` (32 controls, fælles kravtekst på tværs af sites). Disse filer følger nøjagtigt skemaet i §5.1 og kan bruges som: (a) golden-data til at teste en PDF-parser (M1) op imod, og (b) input-data til at bygge og teste M2–M7 uden at være blokeret af PDF-parsing. Se §9 for hvordan de indgår i byggeplanen.

## 1. Baggrund og formål

Hos Novo arbejdes der med **IT Risk Assessments (ITRA'er)**. Hver ITRA er et dokument for én lokation/site, som besvarer et fast sæt spørgsmål og controls om et givent IT/OT-system. Store dele af besvarelsen er **fritekst** (beskrivelser, begrundelser, undtagelser), hvilket gør det svært for QA at:

- Læse og vurdere svar hurtigt og konsistent på tværs af mange sites.
- Skabe et statistisk overblik, fx "hvor mange sites er compliant på control AC.2.1?"
- Opdage hvor et **selvrapporteret status-felt** (fx "Compliant") reelt dækker over en undtagelse, der kun fremgår af fritekstbeskrivelsen.

**ITRA normalizer** er et koncept der bruger en LLM til at læse fritekst på tværs af sites og control-svar og omdanne det til et **normaliseret, sammenligneligt svarrum** — samt validere om det selvrapporterede status-felt reelt stemmer overens med det, teksten beskriver. Denne demo skal illustrere konceptet med et lille sæt syntetiske ITRA'er, der alle følger samme skabelon men repræsenterer forskellige sites.

## 2. Kildedata: det observerede ITRA-format

To eksempel-ITRA'er (SYN-009 Site Indigo, SYN-010 Site Juniper) er modtaget som PDF og følger begge samme faste skabelon. Da "the core equipment architecture is common across all ten fictional locations" (jf. dokumenternes egen beskrivelse), er der reelt tale om **op til 10 sites** med identisk kontrol-taxonomi men forskellige lokale svar. Demoen skal bygges så den kan indlæse et vilkårligt antal ITRA'er efter dette format — i første omgang de 2, vi har.

Dokumentet har følgende sektioner:

| # | Sektion | Struktur | Normaliseringsbehov |
|---|---|---|---|
| — | Metadata (forside) | Faste felter: ITRA-nummer, version, applikation, type, state, location | Ingen — allerede struktureret |
| 1 | Canonical Equipment Architecture | Tabel: komponent, formål, OS, auth, site-variation | Kontekst, indgår ikke i normalisering i v1 |
| 2 | ITRA Scoping Questions (B.x) | ID, spørgsmål, kort svar (Yes/No/Potentially/High/Low/tal), fritekst-rationale | Delvist — kort svar er allerede kategorisk, rationale er fritekst |
| 3 | Technical Assessment (T.x) | ID, spørgsmål, kort svar, fritekst-comment | Delvist |
| 4 | IT Security Assessment (S.x) | ID, spørgsmål, kort svar (typisk Yes/No/Restricted), fritekst-comment | Delvist — **her ligger S.7 "Are shared interactive accounts used?", se §6** |
| 5 | Security Threat Scenarios (TH.x) | ID, trussel, gross likelihood-kategori, fritekst-rationale | Lavt — allerede kategoriseret |
| 6 | **ITRA Controls** (AC/NW/LG/VM/BC/TP/DI/PD-præfiks) | Control-ID, kravtekst, **Status** (Compliant / Partially Compliant / Not Applicable — muligvis også Non-Compliant), Type, **Detailed Description** (fritekst), **Implementation Considerations** (fritekst) | **Højt — dette er kernen i normalizeren, se §6** |
| 7 | ITRA Risks (R.x) | Risk-ID, navn, Gross/Net impact × likelihood × risk (allerede tal), fritekst-comment | Ingen — allerede fuldt kvantificeret, indlæses direkte |
| A | Appendix A — Local Implementation Notes | Fri prosa, opsummerer sektionerne i lokalt sprog | Kun til RAG, ikke til struktureret BI |

Vigtig pointe fra dokumenterne selv: Appendix A skriver eksplicit *"They intentionally use local phrasing rather than normalized analytics labels"* — det er stort set en direkte beskrivelse af det problem, normalizeren skal løse.

**Konklusion for v1-scope:** Normaliseringsindsatsen koncentreres om **Sektion 6 (Controls)**, da det er her det interessante fritekst/status-mismatch opstår (se eksemplet i §6). Sektion 2–4 (Scoping/Technical/Security) tages med i BI-databasen som allerede-strukturerede felter (kort svar + rationale gemt som støttetekst til RAG). Sektion 7 (Risks) indlæses direkte uden LLM-involvering. Dette holder demoen fokuseret uden at underspille kompleksiteten i den fulde ITRA.

## 3. Begreber

| Begreb | Forklaring |
|---|---|
| Site | En lokation/instans af det vurderede system (fx "Site Indigo"), identificeret ved ITRA-nummer. |
| Control | Et krav i Sektion 6, identificeret ved et control-ID (fx `AC.2.1`), med kravtekst, selvrapporteret Status, Type, Detailed Description og Implementation Considerations. |
| Status (rå) | Det selvrapporterede compliance-felt i kildedokumentet: `Compliant`, `Partially Compliant`, `Not Applicable` (evt. `Non-Compliant`). |
| Normaliseret status | LLM'ens vurdering af den *reelle* compliance-tilstand, udledt af Detailed Description — kan afvige fra Status (rå). |
| Reconciliation flag | Markering af om normaliseret status stemmer overens med rå Status, og om sagen bør til QA-review. |
| Scoping/Technical/Security-svar | Kort, allerede kategorisk besvarede spørgsmål (Sektion 2–4) med en fritekst-rationale. |
| RAG / "tal med data" | Semantisk søgning + LLM-svar på tværs af alle fritekstfelter (Detailed Description, Implementation Considerations, rationale/comments, Appendix A). |

## 4. Overordnet flow

```
   [N ITRA-PDF'er, samme skabelon, forskellige sites]
                    │
                    ▼
   A. PARSE: PDF → struktureret JSON pr. site
      (alle 7 sektioner + appendiks)
                    │
                    ▼
   B. NORMALISÉR (LLM, pr. control-ID, på tværs af sites):
      - Udled normaliseret svarrum for controllens "emne"
        (fx AC.2.1 → bruges delte konti: Ja/Nej/Ja-med-undtagelse)
      - Sammenlign rå Status mod Detailed Description
      - Sæt reconciliation-flag + confidence
                    │
                    ▼
   C. KLASSIFICÉR alle sites' control-svar mod svarrummet
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
D. Struktureret DB (SQLite)   E. Vektor-DB (RAG)
   → BI: "hvor mange sites      → "tal med data" på tværs
     er Compliant på AC.2.1?"     af Detailed Description,
   → "hvor mange steder           Implementation Considerations,
     afviger Status fra           rationale/comments og
     normaliseret vurdering?"     Appendix A
```

Sektion 2, 3, 4 og 7 flyder direkte til D uden LLM-normalisering (de er allerede strukturerede), men deres fritekstfelter (rationale/comments) flyder også til E, så de er søgbare i RAG-laget.

## 5. Datamodel

### 5.1 Rå input (efter PDF-parsing, pr. site)

```json
{
  "site_id": "SYN-009",
  "site_name": "Site Indigo",
  "business_application": "Orion Automated Assembly Line - Site Indigo",
  "application_id": "NMD-ORA-009",
  "state": "Approved for synthetic analytics testing",

  "scoping_answers": [
    {"question_id": "B.1", "question": "Does the application support a regulated manufacturing process?", "answer": "Yes", "rationale": "..."}
  ],
  "technical_answers": [
    {"question_id": "T.1", "question": "Software category", "answer": "Industrial control and manufacturing application", "comment": "..."}
  ],
  "security_answers": [
    {"question_id": "S.7", "question": "Are shared interactive accounts used?", "answer": "No - routine users", "comment": "The answer depends on local HMI/maintenance implementation and may require reading multiple control responses."}
  ],
  "threat_scenarios": [
    {"threat_id": "TH.1", "threat": "Unauthorized access to operator or engineering functions", "gross_likelihood": "Possible (10-25%)", "rationale": "..."}
  ],
  "controls": [
    {
      "control_id": "AC.2.1",
      "control_text": "Shared interactive identities may only be used where justified and must have compensating controls.",
      "status_raw": "Compliant",
      "type": "Risk Control",
      "detailed_description": "During troubleshooting, the maintenance interface is sometimes opened with a common engineering login so vendor and site engineers can use the same diagnostic profile. This is treated locally as an exception to the named-user model. The local assessor still marked the requirement compliant because named accounts remain the standard access method.",
      "implementation_considerations": "Document whether the exception is technically necessary or chosen for convenience."
    }
  ],
  "risks": [
    {"risk_id": "R.1", "name": "Unauthorized production access", "gross_impact": "4 - Critical", "gross_likelihood": "2 - Possible", "gross_risk": 8, "net_impact": "4 - Critical", "net_likelihood": "2 - Possible", "net_risk": 8, "comments": "..."}
  ],
  "appendix_notes": "The notes below are assessment working context...(fuld prosa-tekst)"
}
```

### 5.2 Normaliseret svarrum + reconciliation (pr. control-ID, udledt af LLM i trin B/C)

```json
{
  "control_id": "AC.2.1",
  "normalized_fields": [
    {
      "field": "shared_accounts_used",
      "type": "enum",
      "values": ["Nej", "Ja", "Ja - med begrundet undtagelse"]
    },
    {
      "field": "compensating_control_present",
      "type": "boolean"
    }
  ],
  "site_results": [
    {
      "site_id": "SYN-009",
      "status_raw": "Compliant",
      "normalized_value": {"shared_accounts_used": "Ja - med begrundet undtagelse", "compensating_control_present": true},
      "status_reconciled": "Delvist afvigende",
      "reconciliation_note": "Status er sat til Compliant, men Detailed Description beskriver en delt engineering-login-undtagelse. S.7 svarer kun 'No - routine users', hvilket underspiller undtagelsen.",
      "confidence": 0.82,
      "llm_agreement_rate": "3/3",
      "needs_review": true
    },
    {
      "site_id": "SYN-010",
      "status_raw": "Compliant",
      "normalized_value": {"shared_accounts_used": "Nej", "compensating_control_present": null},
      "status_reconciled": "Stemmer overens",
      "reconciliation_note": "Ingen delt konto beskrevet; Status og tekst stemmer overens. S.7 svarer konsistent 'No'.",
      "confidence": 0.95,
      "llm_agreement_rate": "3/3",
      "needs_review": false
    }
  ]
}
```

`status_reconciled` er selve pointen med demoen: den viser hvor LLM'ens læsning af fritekst afviger fra det selvrapporterede felt, og dermed hvor QA bør kigge først.

### 5.3 Struktureret BI-database (SQLite)

```sql
CREATE TABLE sites (
  site_id TEXT PRIMARY KEY,
  site_name TEXT,
  business_application TEXT,
  application_id TEXT,
  state TEXT
);

CREATE TABLE control_catalog (
  control_id TEXT PRIMARY KEY,
  section_prefix TEXT,        -- AC, NW, LG, VM, BC, TP, DI, PD
  control_text TEXT
);

CREATE TABLE control_answers (
  site_id TEXT REFERENCES sites(site_id),
  control_id TEXT REFERENCES control_catalog(control_id),
  status_raw TEXT,
  type TEXT,
  detailed_description TEXT,
  implementation_considerations TEXT,
  normalized_value_json TEXT,   -- serialiseret normaliseret svarrum
  status_reconciled TEXT,       -- 'Stemmer overens' / 'Delvist afvigende' / 'Afvigende'
  reconciliation_note TEXT,
  confidence REAL,
  needs_review BOOLEAN,
  llm_agreement_rate TEXT,      -- fx '3/3', '2/3' — fra selv-konsistens-kørslen, se §8.2
  PRIMARY KEY (site_id, control_id)
);

CREATE TABLE scoping_answers (
  site_id TEXT REFERENCES sites(site_id),
  question_id TEXT, question TEXT, answer TEXT, rationale TEXT,
  PRIMARY KEY (site_id, question_id)
);

CREATE TABLE technical_answers (
  site_id TEXT REFERENCES sites(site_id),
  question_id TEXT, question TEXT, answer TEXT, comment TEXT,
  PRIMARY KEY (site_id, question_id)
);

CREATE TABLE security_answers (
  site_id TEXT REFERENCES sites(site_id),
  question_id TEXT, question TEXT, answer TEXT, comment TEXT,
  PRIMARY KEY (site_id, question_id)
);

CREATE TABLE risks (
  site_id TEXT REFERENCES sites(site_id),
  risk_id TEXT, name TEXT,
  gross_impact TEXT, gross_likelihood TEXT, gross_risk INTEGER,
  net_impact TEXT, net_likelihood TEXT, net_risk INTEGER,
  comments TEXT,
  PRIMARY KEY (site_id, risk_id)
);
```

Eksempel-BI-forespørgsel, der demonstrerer værdien:

```sql
-- Hvor mange sites er "Compliant" på papiret, men flaget needs_review = 1?
SELECT control_id, COUNT(*) AS antal_afvigelser
FROM control_answers
WHERE status_raw = 'Compliant' AND needs_review = 1
GROUP BY control_id
ORDER BY antal_afvigelser DESC;
```

### 5.4 Vektor-database / RAG

Ét embedding pr. fritekstfelt, med metadata der gør citation mulig:

```json
{
  "id": "SYN-009:AC.2.1:detailed_description",
  "text": "During troubleshooting, the maintenance interface is sometimes opened with a common engineering login...",
  "metadata": {
    "site_id": "SYN-009",
    "site_name": "Site Indigo",
    "control_id": "AC.2.1",
    "field": "detailed_description",
    "section": "controls"
  }
}
```

Alle fritekstfelter indekseres: `detailed_description`, `implementation_considerations`, sektion 2-4's `rationale`/`comment`, sektion 5's `rationale`, sektion 7's `comments`, samt `appendix_notes` (evt. splittet pr. underoverskrift).

## 6. Konkret eksempel: AC.2.1 sammenholdt med S.7, Site Indigo vs. Site Juniper

Dette er det bedste eksempel fra de to modtagne dokumenter og bør bruges som demoens "hero example":

**Control AC.2.1:** *"Shared interactive identities may only be used where justified and must have compensating controls."*

| | Site Indigo (SYN-009) | Site Juniper (SYN-010) |
|---|---|---|
| Status (rå) | Compliant | Compliant |
| Detailed Description | "...the maintenance interface is sometimes opened with a common engineering login so vendor and site engineers can use the same diagnostic profile. This is treated locally as an exception..." | "No shared interactive workforce account is used. Automated service identities are addressed separately and are not used for human logon." |
| S.7-svar ("Are shared interactive accounts used?") | **"No - routine users"** + comment: *"may require reading multiple control responses"* | **"No"** (rent) |
| Normaliseret vurdering | Ja, med begrundet undtagelse | Nej |
| `status_reconciled` | **Delvist afvigende** — Status siger Compliant uden forbehold, men beskrivelsen viser en reel undtagelse som QA bør se | Stemmer overens |

Pointen, der skal stå tydeligt i demoen: begge sites rapporterer **Compliant**, og begge svarer **"No"/"No - routine users"** på S.7 — men kun normalizeren, der læser Detailed Description, fanger at Site Indigo reelt har en delt konto-praksis, mens Site Juniper ikke har det. Uden normalisering ville en simpel keyword- eller status-baseret opsummering konkludere "begge sites er compliant, ingen deler konti" — hvilket er misvisende.

## 7. User Interface

Anbefalet stack til demoen: **Python + Streamlit** (ét codebase, hurtigt at bygge, godt nok til en stakeholder-demo). Alternativ (mere "produkt-agtig", men dyrere at bygge): FastAPI-backend + let React/Next.js-frontend. Denne spec antager Streamlit; sig til hvis I hellere vil have en rigtig web-app.

**Skærm 1 — Ingest**
- Vælg blandt medfølgende eksempel-ITRA'er (Site Indigo, Site Juniper, ...) eller upload en ny PDF i samme skabelon.
- Knap "Kør normalisering" der trigger parse → LLM-normalisering → DB/vektor-indeksering, med simpel fremgangsindikator (pr. control-ID).

**Skærm 2 — Control Explorer**
- Vælg et control-ID (eller browse pr. sektion: AC/NW/LG/VM/BC/TP/DI/PD).
- Tabel med én række pr. site: Status (rå), Detailed Description (trunkeret, kan foldes ud), normaliseret værdi, `status_reconciled`-badge (grøn/gul/rød), reconciliation-note.
- AC.2.1 vises som fremhævet eksempel/walkthrough i en "Se eksempel"-boks.

**Skærm 3 — BI Dashboard**
- Compliance-fordeling pr. control eller sektion (stacked bar: Compliant/Partially Compliant/Not Applicable).
- "Top afvigelser" — de controls hvor flest sites har `needs_review = true`, sorteret faldende.
- Simpelt filter på site og sektion.

**Skærm 4 — Tal med data (fri chat, BI + RAG)**
- Et helt frit chat-vindue — ikke en liste af forudbestemte spørgsmål. Brugeren kan spørge om hvad som helst, og agenten afgør selv hvordan spørgsmålet bedst besvares (se §8.1 for den tekniske model).
- Svar vises altid med kildehenvisning: enten den udførte SQL + resultatsæt (for aggregerede spørgsmål), et citat med site + control-ID (for semantiske spørgsmål), eller begge dele — med link tilbage til Control Explorer.
- Eksempler i UI'en er kun forslags-chips til inspiration ("Prøv: ...") — de er ikke en begrænsning af hvad der kan spørges om.

## 8. Teknisk arkitektur og stack

### 8.1 Chat-agenten: BI + RAG i samme samtale

Skærm 4 er **ikke** en ren RAG-pipeline og **ikke** en fast liste af eksempelspørgsmål — det er en tool-use-agent (Claude med værktøjsadgang) der frit kan kombinere strukturerede og semantiske opslag i én samtale:

1. **`sql_query(question)`** — agenten får databasens skema (§5.3) i systemprompten og formulerer selv en **read-only** SQL-forespørgsel mod SQLite for tælle-/aggregerings-/sammenligningsspørgsmål (fx "hvor mange sites er Partially Compliant på VM.1.1?"). Værktøjet validerer at forespørgslen kun er `SELECT` før den køres, og returnerer resultatsættet til agenten.
2. **`semantic_search(question)`** — vektor-søgning i Chroma for spørgsmål der kræver at finde/citere konkrete formuleringer (fx "hvilke sites har undtagelser for delte konti, og hvad er begrundelsen?").

Agenten vælger selv ét eller begge værktøjer pr. spørgsmål — fx til "hvilke controls har flest reconciliation-afvigelser, og hvad er den typiske begrundelse?" vil den typisk først køre en SQL-aggregering og derefter en semantisk søgning på de fundne control-ID'er, og syntetisere ét svar med begge kilder citeret. Dette er reelt et lille "text-to-SQL + RAG"-agent-mønster, som er relevant at teste i sig selv — ikke kun som demo-pynt, men som en arkitektur-komponent I kan validere robustheden af (fejlhåndtering ved forkert genereret SQL, hvornår agenten vælger forkert værktøj, osv.).

### 8.2 Determinisme og konsistens i normaliseringen

En kendt risiko ved LLM-baseret klassificering: samme input kan give forskellige svar ved gentagne kørsler. Det er særligt vigtigt at adressere her, fordi et IT-risikoværktøj skal opleves som troværdigt og reproducerbart — ikke fordi det er umuligt at løse, men fordi det kræver bevidst design. Tiltag, i prioriteret rækkefølge:

1. **Normalisér én gang, gem resultatet — det vigtigste fix.** Normalisering skal køre én gang pr. site+control ved ingest (M3) og skrives til `control_answers`. UI'en (Control Explorer, Dashboard, Chat) læser altid det gemte, deterministiske resultat og genkalder aldrig LLM'en ved almindelig visning. Hvis den tidlige håndholdte demo viste forskellige svar på "samme control", var det højst sandsynligt fordi normaliseringen reelt blev genkørt live hver gang — det problem forsvinder helt med denne arkitektur, som allerede er en del af spec'en.
2. **Temperature = 0** på normaliserings- og reconciliation-kaldene. Reducerer variation markant, men garanterer ikke bit-identiske svar — selv ved temperature 0 kan hostede LLM-API'er variere let pga. batching/infrastruktur. Betragt det som "meget mere stabilt", ikke "matematisk garanteret".
3. **Tvunget struktureret output** (jf. `normalized_fields`-enums i §5.2) i stedet for fri tekst. Når modellen kun må vælge mellem fx `["Nej", "Ja", "Ja - med begrundet undtagelse"]`, er der langt mindre rum for at "formulere sig forskelligt" mellem kørsler.
4. **Eksplicit rubrik/few-shot-eksempler i prompten:** giv modellen 2-3 konkrete, forklarede eksempler (inkl. AC.2.1-casen fra §6) direkte i system-prompten. Anker modellens "domme" og reducerer reel drift langt mere end temperature alene.
5. **Selv-konsistens (self-consistency) som sikkerhedsnet:** kør normaliseringen af hver control N gange (fx 3) og brug flertalsafgørelse. Hvis kørslerne er uenige, sættes automatisk `needs_review = true` med en note om LLM-uenighed. Dette er ikke en fejl at skjule, men et ekstra confidence-signal der passer direkte ind i det eksisterende reconciliation-koncept — tilføj feltet `llm_agreement_rate` (fx "3/3", "2/3") til skemaet i §5.2. Koster N× flere LLM-kald ved ingest, men det sker kun én gang (jf. punkt 1), så det er billigt i praksis.
6. **Log model- og promptversion pr. resultat**, så I kan se om ændringer i prompten reelt ændrer outputtet — vigtigt både til fejlsøgning og til den arkitektur-test-brug, I har nævnt.

Den ærlige konklusion: 100% determinisme kan ikke garanteres med en hostet LLM, men lav temperature + struktureret output + few-shot-rubrik + selv-konsistens + "normalisér-én-gang"-arkitekturen gør resultatet stabilt nok til demo/produktion — og gør den resterende usikkerhed synlig frem for skjult, hvilket faktisk er en styrke i en risikovurderings-kontekst.

- **Sprog:** Python.
- **PDF-parsing:** `pdfplumber` (tabel-udtræk) til at konvertere kildedokumenterne til JSON iht. §5.1. Da PDF-parsing kan være skrøbelig, gemmes det udtrukne JSON som cache/fixture, så demoen ikke er afhængig af live-parsing for at være stabil under en fremvisning.
- **LLM:** Claude API, brugt til to opgaver: (1) udlede normaliseret svarrum + reconciliation pr. control, (2) besvare RAG-spørgsmål.
- **Struktureret DB:** SQLite (jf. §5.3).
- **Vektor-DB:** Chroma, lokal/in-process — ingen ekstern infrastruktur nødvendig.
- **UI:** Streamlit (jf. §7).
- **Forudsætninger/opsætning:** `ANTHROPIC_API_KEY` som miljøvariabel; Python-afhængigheder `pdfplumber`, `chromadb`, `streamlit`, `anthropic`, plus standard `sqlite3` (indbygget). Ingen ekstern infrastruktur (DB/vektor-DB kører begge lokalt/in-process). Pin en konkret Claude-modelversion i konfigurationen (ikke en "seneste"-alias), så resultater er reproducerbare på tværs af kørsler — relevant for §8.2.
- **Foreslået repo-struktur** (fixtures fra `itra-normalizer-fixtures.zip`, §0, lægges direkte ind under `data/`):
  ```
  itra-normalizer/
    data/raw_pdfs/              # kilde-PDF'er (fra fixtures.zip)
    data/parsed/                # JSON-udtræk pr. site (golden data fra fixtures.zip + nye parses)
    data/control_catalog.json   # delt control-taxonomi (fra fixtures.zip)
    src/ingest/parse_pdf.py     # PDF → JSON
    src/normalize/normalize.py  # LLM-normalisering + reconciliation
    src/db/schema.sql
    src/db/load.py
    src/rag/index.py
    src/rag/query.py
    app/streamlit_app.py
    app/pages/1_ingest.py
    app/pages/2_control_explorer.py
    app/pages/3_dashboard.py
    app/pages/4_chat.py
  ```

## 9. Byggeplan (milestones til kodende agent)

0. **M0 — Fixtures:** Pak `itra-normalizer-fixtures.zip` ud i repoet (§0). Brug de to `data/parsed/*.json`-filer og `data/control_catalog.json` som golden data — de er allerede valideret manuelt mod kilde-PDF'erne, så M2–M7 kan bygges og testes uafhængigt af om M1 (PDF-parsing) er færdig.
1. **M1 — Parsing:** Byg `parse_pdf.py` der konverterer én ITRA-PDF (i det viste format) til JSON iht. §5.1. Valider output mod de medfølgende golden-JSON-filer fra M0 (feltniveau-diff, ikke kun "kører uden fejl"). Hvis en fremtidig PDF afviger fra skabelonen, skal parseren fejle synligt frem for at gætte.
2. **M2 — Struktureret DB:** Opret SQLite-skema (§5.3), load Sektion 2/3/4/7 direkte (ingen LLM), samt `control_catalog` og rå `control_answers` (uden normalisering endnu). Brug fixtures fra M0 som seed-data.
3. **M3 — Normalisering:** Byg LLM-kald der for hvert control-ID på tværs af indlæste sites udleder normaliseret svarrum + `status_reconciled` (§5.2), med temperature=0, struktureret output og selv-konsistens (N=3 kørsler, jf. §8.2), og skriver resultatet inkl. `llm_agreement_rate` til `control_answers`. Valider specifikt at AC.2.1-eksemplet (§6) giver det forventede resultat, og at genkørsel af hele pipelinen på samme input giver samme lagrede resultat (idempotens-test).
4. **M4 — Vektor-indeksering:** Embed alle fritekstfelter (§5.4) i Chroma med korrekt metadata.
5. **M5 — Chat-agent (BI + RAG):** Byg tool-use-agenten (§8.1) med begge værktøjer (`sql_query`, `semantic_search`), inkl. validering af at genereret SQL er read-only. Test med mindst ét rent BI-spørgsmål, ét rent semantisk spørgsmål, og ét kombineret spørgsmål der kræver begge værktøjer.
6. **M6 — UI:** Byg de fire Streamlit-skærme (§7), i rækkefølgen Ingest → Control Explorer → Dashboard → Chat.
7. **M7 — Demo-polish:** Sørg for at AC.2.1/S.7-eksemplet er let at finde/fremvise i UI'en som det centrale "aha"-øjeblik.

## 10. Demo-scope og afgrænsning

**Funktionskrav (ikke til forhandling):** Demoen skal være **reelt funktionsdygtig end-to-end**, ikke en mockup med forhåndsberegnede eller hardcodede outputs. Alle LLM-kald (normalisering, reconciliation, chat-agentens SQL/RAG-værktøjer) skal være ægte kørsler på hver session, og alle trin i pipelinen (parse → normalisér → gem i DB/vektor-DB → forespørg) skal faktisk virke. Årsagen er, at demoen skal kunne genbruges som et rigtigt testværktøj i en arkitektur-opklaringsfase — fx til at afprøve prompt-strategier, se hvor LLM'en er usikker (lav confidence), eller stresteste chat-agentens værktøjsvalg — og det kræver at alt under motorhjelmen reelt kører, ikke kun ser sådan ud.

**Med i demoen:**

- De 2 (evt. flere, op til 10) syntetiske ITRA'er i det viste format.
- Ægte LLM-kald til normalisering og reconciliation af Sektion 6 (Controls) — ikke hardcodet.
- Struktureret BI-database og et par konkrete aggregerede forespørgsler.
- Vektor-DB samt en fri chat-agent (§8.1) der frit kan kombinere BI (SQL) og RAG (semantisk søgning) — ikke begrænset til forudbestemte eksempelspørgsmål.
- De fire UI-skærme beskrevet i §7.

**Ikke med i demoen:**

- Rigtige/følsomme ITRA-data eller integration til Novo's produktionssystemer.
- Normalisering af Sektion 2–4 (Scoping/Technical/Security) — de indlæses strukturet as-is; kan tilføjes som v2 hvis relevant.
- Governance omkring hvornår et normaliseret svarrum må ændres over tid (skema-drift).
- Adgangsstyring, audit trail og compliance-krav til selve værktøjet.
- Menneskeligt review-workflow (dog antydes behovet via `needs_review`-feltet).
- Robust generel PDF-parsing af vilkårlige ITRA-layouts — v1 antager den viste skabelon.

## 11. Success-kriterier

- AC.2.1-eksemplet (§6) kan fremvises end-to-end: rå PDF → normaliseret status → synligt reconciliation-flag i UI.
- BI-dashboardet kan korrekt besvare "hvor mange sites er Compliant på control X" og "hvilke controls har flest reconciliation-afvigelser".
- Chat-agenten kan, uden forhåndsprogrammerede svar, korrekt besvare mindst: (a) et rent BI/tælle-spørgsmål via genereret SQL, (b) et rent semantisk spørgsmål via RAG-citation, og (c) et spørgsmål der kræver begge dele.
- Chat-agenten afviser eller håndterer sikkert forsøg på ikke-read-only SQL (fx et spørgsmål der fører til `UPDATE`/`DELETE`-lignende hensigt).
- Hele kæden (Ingest → Control Explorer → Dashboard → Chat) kan gennemføres live — uden forhåndsberegnede outputs — og forklares for en ikke-teknisk stakeholder på under 10 minutter.

## 12. Åbne spørgsmål til næste iteration

- Skal Sektion 2–4 (Scoping/Technical/Security) også LLM-normaliseres i en senere version, eller er rå/strukturerede felter nok?
- Findes der en "Non-Compliant"-statusværdi i det fulde datasæt (ikke set i de 2 modtagne dokumenter), og skal reconciliation-logikken håndtere den eksplicit?
- Skal demoen antage alle 10 sites findes, eller arbejde robust med et vilkårligt undersæt (som nu, 2 sites)?
- Foretrækkes Streamlit, eller skal der bygges en "rigtigere" web-app (FastAPI + frontend) fra start?
