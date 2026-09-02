# Acquiring Knowledge Sources / Գիտելիքի աղբյուրների ձեռքբերում

## English

Acquisition is an **operator** procedure. BRO never runs it, and nothing in the runtime can.
Run it as the service identity so the registry and the corpus are owned by `bro`:

```bash
sudo -u bro env HOME=/var/lib/bro PYTHONPATH=/opt/bro/current/src \
  python3 /opt/bro/current/scripts/bro_acquire_knowledge.py <command> [options]
```

| Command | What it does |
|---|---|
| `acquire` | fetches every document in the shelf manifest, converts it to text, hashes it, records it as `STAGED` and writes the bytes to the **staging** tree |
| `screen --actor <who>` | runs the screening gates against the authorized source policy and marks passing sources `SCREENED`; a source the policy does not name is refused by name |
| `rescreen --actor <who>` | sends approved sources back through screening, deliberately and on the record |
| `publish --actor <who>` | approves screened sources on a recorded basis, writes exactly the approved bytes into the **corpus**, and removes anything in the corpus that is not approved |
| `content-review --actor <person> --path <p> --evidence <artifact>` | records that a **person read that document** — separate from approval, and never implied by it |
| `verify` | re-reads the corpus and reports any file that is unapproved, altered or missing |
| `status` | lists every source and its lifecycle state |
| `probe --url <url>` | fetches one address and prints what the extractor would see; changes nothing |

Defaults: registry `/var/lib/bro/runtime.sqlite3`, staging `/var/lib/bro/knowledge-staging`,
corpus `/var/lib/bro/knowledge`. **Staging and corpus are different directories on purpose.**
Acquiring something must not make it readable by `STUDY`; only `publish` moves bytes across
that line, and only for a source a named person approved.

### What approval claims

`APPROVED_FOR_STUDY` says the screening gates passed: the source is in the authorized policy
at the address it came from, agrees with that policy, carries complete provenance, is
contained and study-eligible, carries no credential, and its approved bytes are its screened
bytes. **It does not say a person read the document.** `--actor` on `screen` and `publish`
names whoever ran the gates, which for Night School v1 is
`claude-code-builder@night-school-v1`.

If a person does read a document, record that with `content-review`. It needs a named reader
and an artifact, and it is the only thing that sets `HUMAN_CONTENT_REVIEWED`.

**Ի՞նչ է պնդում հաստատումը։** `APPROVED_FOR_STUDY`-ն ասում է, որ screening-ի gate-երն անցել
են։ **Չի ասում, որ մարդ կարդացել է փաստաթուղթը։** `--actor`-ը անվանում է gate-երը վազեցնողին։
Եթե մարդ իսկապես կարդում է փաստաթուղթը, դա գրանցվում է `content-review`-ով՝ անվանված
ընթերցողով ու արտեֆակտով։

### Pointing STUDY at the corpus

`BRO_STUDY_ROOT=/var/lib/bro/knowledge` in `/etc/bro/bro.env`. The default is the deployed
release, so an unset variable means BRO studies its own code — not the library.

### What acquisition refuses

- anything that is not `https`
- a document over 2 MB, or one that yields too little text to be the document
- a corpus path that escapes the root, hides in a dot-directory, or names an executable,
  archive, key file or image
- material carrying an actual credential — a private key with a body, a real token. Material
  that merely *names* one is accepted, because security documentation is full of those and
  rejecting it would empty the shelf it exists to fill.

### Pacing

Acquisition leaves 1.5 seconds between requests to the same host and retries a transient
refusal — `429`, `403`, `408` or a `5xx` — up to three attempts, honouring the server's own
`Retry-After` and capping any wait at a minute. Fifty documents come from a handful of
hosts, and fetching them back to back is how a polite reader starts to look like a scraper:
the first production acquisition had two OWASP pages answer `429` and `403`, and both served
normally a minute later. A permanent refusal such as `404` is not retried.

**Կշռույթը։** Նույն host-ին ուղղված հարցումների միջև 1.5 վայրկյան, ու ժամանակավոր մերժումը
(`429`, `403`, `408`, `5xx`) կրկնվում է մինչև երեք փորձ՝ հարգելով սերվերի `Retry-After`-ը ու
սահմանափակելով սպասումը մեկ րոպեով։ Մշտական մերժումը (`404`) չի կրկնվում։

### Re-acquiring

Running `acquire` again re-fetches. Unchanged documents are reported `unchanged` and nothing
moves. A changed document supersedes its predecessor — which stays on the record, with the
reason — and is staged afresh, so it needs a new review and a new approval before study sees
it. `verify` after every `publish`; a `FAIL` there means the corpus no longer matches what
anyone approved.

---

## Հայերեն

Ձեռքբերումը **օպերատորի** ընթացակարգ է։ BRO-ն այն երբեք չի կանչում, ու runtime-ից ոչինչ չի
կարող։ Աշխատեցրու ծառայության ինքնությամբ, որ registry-ն ու corpus-ը պատկանեն `bro`-ին
(տես վերևի հրամանը)։

| Հրաման | Ի՞նչ է անում |
|---|---|
| `acquire` | բերում է manifest-ի ամեն փաստաթուղթ, դարձնում տեքստ, hash անում, գրանցում `STAGED` ու գրում **staging**-ում |
| `screen --actor <ով>` | վազեցնում է screening-ի gate-երը թույլատրված քաղաքականության դեմ ու անցածները նշում `SCREENED` |
| `rescreen --actor <ով>` | հաստատվածները միտումնավոր ու գրառմամբ վերադարձնում է screening |
| `publish --actor <ով>` | հաստատում է գրանցված հիմքով ու գրում հենց հաստատված բայթերը **corpus**-ում |
| `content-review --actor <անուն> --path <ուղի> --evidence <արտեֆակտ>` | գրանցում է, որ **մարդ կարդացել է** այդ փաստաթուղթը. առանձին է հաստատումից ու երբեք դրանից չի բխեցվում |
| `verify` | վերընթերցում է corpus-ը ու հայտնում չհաստատված, փոփոխված կամ բացակայող ֆայլերը |
| `status` | ցույց է տալիս ամեն աղբյուր ու իր վիճակը |
| `probe --url <url>` | բերում է մեկ հասցե ու տպում՝ ինչ կտեսներ extractor-ը. ոչինչ չի փոխում |

**Staging-ը և corpus-ը դիտավորյալ տարբեր թղթապանակներ են։** Բերելը չպիտի նյութը դարձնի
`STUDY`-ի համար ընթեռնելի. միայն `publish`-ն է գիծը հատում, ու միայն անուն կրող մարդու
հաստատած աղբյուրի համար։

`BRO_STUDY_ROOT=/var/lib/bro/knowledge` — առանց դրա BRO-ն ուսումնասիրում է իր սեփական
կոդը, ոչ գրադարանը։

**Ձեռքբերումը մերժում է** ոչ-`https` հասցեն, 2 ՄԲ-ից մեծ փաստաթուղթը, արմատից դուրս եկող
կամ գործարկելի/արխիվ/բանալի ուղին, ու **իրական** credential կրող նյութը։ Credential-ի
անունը պարզապես **հիշատակող** նյութն ընդունվում է — անվտանգության փաստաթղթերը լի են
դրանով, ու մերժելը կդատարկեր հենց այն դարակը, որի համար այս ամենը կա։

Կրկնակի `acquire`-ը՝ չփոխված փաստաթուղթը `unchanged` է, փոխվածը՝ հին տարբերակը դառնում է
`SUPERSEDED` (մնում է գրառման մեջ) ու նորը կրկին անցնում է review-ի ու հաստատման միջով։
Ամեն `publish`-ից հետո՝ `verify`։ Կրկնակի `screen`-ը հաստատվածների վրա չի աշխատում.
դրա համար կա `rescreen`, որ վիճակի փոփոխությունը մնա գրառման մեջ։
