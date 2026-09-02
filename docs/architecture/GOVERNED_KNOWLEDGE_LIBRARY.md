# BRO Governed Knowledge Library / BRO-ի կառավարվող գիտելիքի գրադարան

## English

### The one thing this exists to keep apart

Fetching a document and believing it are different acts. Before Night School, BRO could
only study what was already in its own release — safe, because the release is reviewed
code. Opening BRO to the outside world means it can now read material nobody on this
project wrote, and the whole design follows from refusing to let *acquired* and *trusted*
become the same word.

    acquire (a person, with the network) → STAGED
      → a person reads it → REVIEWED
        → a person approves it → APPROVED_FOR_STUDY → the corpus STUDY can read

`STUDY` never crosses that line. It has no network, no subprocess, no acquisition tool and
no way to approve anything; it reads a rooted directory of files, exactly as it always has.
The corpus is simply a second rooted directory, and every byte in it was put there by
`scripts/bro_acquire_knowledge.py`, which a person runs.

### What a source carries

| Field | Why it is recorded |
|---|---|
| `publisher`, `canonical_url` | who said it, and where it can be read again |
| `authority_class` | what kind of word it is — a standard, a specification, a vendor's own documentation, a government or academic body, security guidance |
| `source_scope` | **what it is authoritative about**, which is never "everything" |
| `upstream_version` | the release or revision acquired, so staleness is visible |
| `content_digest` | the exact bytes approved |
| `source_language` | `en`, `hy` or `ru` — checked against the script actually acquired |
| `language_variant` | for Armenian, which Armenian |
| `license`, `notes` | terms, and anything the acquisition found worth recording |

**Authority is scoped, never global.** The RFC Editor is authoritative for the RFC it
published and about nothing else. Nothing on any shelf outranks BRO's own contracts,
governance, or current runtime truth — a learned claim that contradicts current truth is
withheld at retrieval, exactly as a learned lesson is.

**Acquired material is data.** A page in the corpus may contain sentences shaped like
instructions; OWASP's prompt-injection page is *made* of them. They are the subject matter,
not instructions to BRO or to any agent, and nothing in the study path can execute or obey
them. Every corpus file says so in its own header.

### The shelves

`contracts/knowledge_shelves.json` names every document at a pinned https address. Seven
shelves: the MCP specification `2026-07-28` (pinned to a commit), Claude Code and the Agent
SDK, GitHub platform documentation, the NIST AI Risk Management Framework, OWASP GenAI
security guidance, three IETF RFCs, and the Armenian language authorities.

**On the OWASP shelf, the evidence overruled the brief.** The instruction to build this
shelf named "OWASP GenAI LLM Top 10 2026" as the current release. It is recorded here as
**2025**, because three independent measurements say so: the live `/llm-top-10/` page
publishes identifiers `LLM01:2025`–`LLM09:2025`; each per-risk page carries the year inside
its own address (`/llmrisk/llm022025-…`); and the legacy project repository's newest release
tag is `2024`. No 2026 release was reachable. This is what "a documented claim is not
evidence" costs when it is taken seriously: the shelf records what was measured.

**On the Armenian shelf, scope is narrower than the name suggests.** Its `source_scope`
says so plainly: Armenian language *policy and institutions*, not a grammar or orthography
rulebook. The normative rule texts published by these bodies are not statically reachable —
their sites render content through JavaScript that the acquisition tool deliberately does
not run. What was acquired is institutional and descriptive, and it is labelled as such
rather than dressed up as a rulebook.

### Multilingual learning: one item, many doors

    source language ≠ interaction language

BRO learns from English, Armenian and Russian sources, and can be asked about any of them
in any of those languages. That is done with **one canonical learned item**, not a
translated copy per language:

- **`source_language`** is the language of the document, decided by the runtime from the
  script — not asserted by the model.
- **`evidence_language`** is the language of the quote, which is not always the document's.
  An Armenian page quoting an English standard has both, and collapsing them would
  attribute a quote to a language it was never written in.
- **`recall_terms`** are short retrieval keys naming the claim's subject in the other
  supported languages. They are the only new thing in the read path, and they are *keys*:
  bounded in length, never the evidence, never able to raise a verification state, and
  never quoted back as if the source had said them.

So an Armenian question reaches an English claim, and the answer may be explained in
Armenian — **but the evidence stays the original English sentence, in English.** A
translation is an explanation. It is never evidence, and a claim whose "quote" is a
translation is not `VERIFIED`, because the quote is not in the source.

Retrieval stays deterministic and read-only. No model call happens on the recall path, so
recall still works on a read-only connection, and cross-language reach costs one extra term
comparison — not a second knowledge store.

**The model's own multilingual ability is a separate thing.** The backend can read Armenian;
that is not BRO having learned anything. Everything claimed above is proven through BRO's
own memory path in `tests/test_multilingual_learning.py`, not inferred from the vendor's
capabilities.

### Night School limits

A library is wider than a repository and must stop later than one. Production STUDY now
runs an item budget of **30** (`BRO_STUDY_ITEM_BUDGET`) and ends on **6** consecutive
barren sources (`BRO_STUDY_DIMINISHING_AFTER`). Both are configuration, both are at least
one, and a malformed setting falls back to the default rather than removing the limit —
because a limit that a typo can switch off is not a limit.

---

## Հայերեն

### Ինչի՞ համար է սա

Փաստաթուղթ բերելը և դրան հավատալը երկու տարբեր բան են։ Մինչև Night School-ը BRO-ն
կարդում էր միայն իր սեփական release-ը՝ վերանայված կոդ։ Դրսի աշխարհը բացելը նշանակում է,
որ հիմա կարող է կարդալ նյութ, որ այս ծրագրում ոչ ոք չի գրել, ու ամբողջ նախագիծը բխում է
մեկ մերժումից՝ **«բերված»-ը և «վստահելի»-ն նույն բառը չեն**։

    ձեռք բերել (մարդ, ցանցով) → STAGED
      → մարդ կարդում է → REVIEWED
        → մարդ հաստատում է → APPROVED_FOR_STUDY → corpus, որ STUDY-ն կարդում է

`STUDY`-ն այդ գիծը երբեք չի հատում։ Ցանց չունի, subprocess չունի, ձեռքբերման գործիք չունի
ու ոչինչ հաստատել չի կարող. կարդում է արմատով սահմանափակ թղթապանակ, ինչպես միշտ։

### Ի՞նչ է կրում աղբյուրը

Ամեն աղբյուր գրանցում է հրատարակչին, canonical հասցեն, **authority_class**-ը (նորմատիվ
ստանդարտ, պաշտոնական բնութագիր, պետական կամ ակադեմիական մարմին, արտադրողի փաստաթուղթ,
անվտանգության ուղեցույց), **source_scope**-ը, upstream տարբերակը, բովանդակության digest-ը,
**source_language**-ը, հայերենի դեպքում՝ **language_variant**-ը, ու լիցենզիան։

**Հեղինակությունը շրջանակված է, երբեք գլոբալ։** RFC Editor-ը հեղինակավոր է իր հրապարակած
RFC-ի համար ու ուրիշ ոչնչի։ Ոչ մի դարակ չի գերազանցում BRO-ի սեփական contract-ները,
governance-ը կամ ընթացիկ ճշմարտությունը։

**Ձեռք բերված նյութը տվյալ է։** Corpus-ի էջը կարող է պարունակել հրահանգի տեսք ունեցող
նախադասություններ — OWASP-ի prompt-injection-ի էջը հենց դրանցից է բաղկացած։ Դրանք առարկան
են, ոչ թե հրահանգ BRO-ին. ուսուցման ուղին դրանք կատարել կամ ենթարկվել չի կարող։

### Դարակները և երկու ազնիվ ճշտում

Յոթ դարակ՝ MCP-ի բնութագիր `2026-07-28` (commit-ով ամրակցված), Claude Code, GitHub-ի
փաստաթղթեր, NIST AI RMF, OWASP GenAI, երեք RFC, ու հայոց լեզվի մարմինները։

**OWASP-ի դեպքում ապացույցը գերակշռեց հանձնարարականին։** Հանձնարարականն ասում էր
«2026»։ Այստեղ գրված է **2025**, որովհետև երեք անկախ չափում այդպես է ասում. կենդանի էջը
հրապարակում է `LLM01:2025`–`LLM09:2025`, ամեն ռիսկի էջ թվականը կրում է իր հասցեի մեջ
(`/llmrisk/llm022025-…`), իսկ հին repo-ի վերջին release-ը `2024` է։ 2026 թողարկում
հասանելի չէր։

**Հայկական դարակի շրջանակն ավելի նեղ է, քան անունն է հուշում։** `source_scope`-ն ուղիղ
գրում է՝ լեզվական **քաղաքականություն և հաստատություններ**, ոչ թե ուղղագրության
կանոնագիրք։ Այս մարմինների նորմատիվ տեքստերը ստատիկ հասանելի չեն — կայքերը բովանդակությունը
բեռնում են JavaScript-ով, որը ձեռքբերման գործիքը դիտավորյալ չի կատարում։ Ձեռք բերվածը
հաստատութենական ու նկարագրական է, ու հենց այդպես էլ պիտակավորված է։

### Բազմալեզու ուսուցում՝ մեկ միավոր, շատ դռներ

    աղբյուրի լեզուն ≠ շփման լեզուն

BRO-ն սովորում է անգլերեն, հայերեն ու ռուսերեն աղբյուրներից, ու կարելի է հարցնել ցանկացած
այդ լեզվով — **մեկ canonical միավորով**, ոչ թե ամեն լեզվի համար թարգմանված պատճենով.

- **`source_language`** — փաստաթղթի լեզուն, որոշում է runtime-ը գրի հիման վրա, ոչ մոդելը։
- **`evidence_language`** — մեջբերման լեզուն, որը միշտ չէ որ նույնն է. հայերեն էջը կարող է
  բառացի մեջբերել անգլերեն ստանդարտ, ու երկուսը շփոթելը մեջբերումը կվերագրեր լեզվի, որով
  այն երբեք չի գրվել։
- **`recall_terms`** — կարճ որոնման բանալիներ մյուս լեզուներով։ Դրանք **միայն բանալի** են.
  երկարությամբ սահմանափակ, երբեք ապացույց, երբեք verification վիճակ բարձրացնող։

Այսինքն՝ հայերեն հարցը հասնում է անգլերեն claim-ին, պատասխանը կարող է հայերեն բացատրվել,
**բայց ապացույցը մնում է բնագիր անգլերեն նախադասությունը՝ անգլերեն**։ Թարգմանությունը
բացատրություն է, ոչ ապացույց. claim, որի «մեջբերումը» թարգմանություն է, `VERIFIED` չի
դառնում, որովհետև այդ մեջբերումը աղբյուրում չկա։

Retrieval-ը մնում է դետերմինիստիկ ու միայն-կարդալ. recall-ի ուղում մոդելի կանչ չկա։

**Մոդելի բազմալեզու կարողությունն առանձին բան է։** Backend-ը հայերեն կարդում է — դա BRO-ի
սովորածը չէ։ Վերևի ամեն պնդում ապացուցված է BRO-ի սեփական հիշողության ուղով
(`tests/test_multilingual_learning.py`), ոչ թե ենթադրված արտադրողի հնարավորություններից։

### Night School-ի սահմանները

Գրադարանն ավելի լայն է, քան repo-ն, ու պիտի ավելի ուշ կանգնի։ Production STUDY-ն հիմա
վազում է **30** item budget-ով (`BRO_STUDY_ITEM_BUDGET`) ու կանգնում **6** անընդմեջ ամուլ
աղբյուրից հետո (`BRO_STUDY_DIMINISHING_AFTER`)։ Երկուսն էլ կոնֆիգուրացիա են, երկուսն էլ
առնվազն մեկ, ու սխալ գրված արժեքը վերադառնում է լռելյայնին, այլ ոչ թե անջատում սահմանը։
