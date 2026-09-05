# Governed Study Acquisition / Կառավարվող ուսուցողական ձեռքբերում

## English

### The separation this rests on

**Network acquisition and study reading are different authorities.** `StudySourceReader` is
still local, rooted and networkless — it never learned to fetch anything. `study_acquisition`
is the one owner of external retrieval, and the study runtime does not import it: it is
*handed* an acquirer, so the authority to reach outside is granted by wiring and visible at
the call site rather than assumed by anything that imports a file. The gate enforces both
halves, and a network name appearing in the study runtime fails the build.

    DISCOVERED → SCREENED → ACQUIRED → ADMITTED (or refused)
      → studied by the existing runtime → retained by the existing learning boundary

### The bootstrap problem, and what replaced the manifest

A source used to have to be named in a shelf manifest before it could be evaluated at all,
which makes autonomous discovery impossible: nothing new can be judged. Screening now checks
against **`contracts/source_policy.json`** — an explicit, governable policy of host families,
tiers and scopes that a person writes and BRO cannot edit. A page nobody has ever listed can
therefore be judged on the spot, by the family its host belongs to.

That is knowledge governance, not authority expansion. Admission decides what may be
**studied**; it never decides what may be **executed**.

### Tiers

**A — canonical/primary**: standards bodies, official project documentation, government
technical frameworks, original specifications. Auto-admitted, may produce verified knowledge.
**B — academic**: recognised university material and original research. Same.
**C — proven engineering**: good references that are still someone's summary of a
specification. Admitted only where the policy marks the family admissible, and never
automatically — a person decides.
**D — discovery only**: forums, blogs, social media, Q&A. **May lead, never testify.** Never
admitted, never a source of verified knowledge.
**UNCLASSIFIED**: a host no family claims. It stays a candidate for a person, and **BRO never
promotes one** — a system that can classify its own new sources can eventually classify
anything as authoritative.

A look-alike host inherits nothing: `evil-nist.gov` is not `nist.gov`, and refusing to notice
that is how an allowlist stops being one.

### Retrieval

HTTPS only. No credentials in a URL, no non-standard port. **Only GET is expressible** —
there is no method parameter to widen, no request body, and the gate holds the module to
exactly one request verb.

Every hop is re-checked: the first request and each redirect are re-validated against the
policy *and* re-resolved, and a host is refused unless **every** address it answers with is
public. One public and one loopback answer is still a way in. A permitted host that redirects
to `169.254.169.254` is exactly how a fetcher becomes a proxy into its own network, so that
redirect is refused rather than followed.

Response size, redirect count, timeout, attempts and per-host pacing all come from the policy.
A download stopped at its budget is recorded as **partial**, never as whole.

### Normalisation

Acquired HTML becomes a local inert artifact: headings, paragraphs, lists and code blocks
preserved; scripts, styles, navigation and embedded objects dropped. **STUDY reads the
artifact, never live Internet content.** Every artifact carries its own provenance header —
requested URL, final URL, host, publisher, tier, class, scope, discovery query, retrieval
time, content type, content digest, and whether it is complete.

**PDF is read properly, and refuses when it cannot be.** `pdf_text` reads the real object
table — including the compressed object streams every PDF 1.5 and later uses, which is why a
regex over raw bytes finds three objects in a document that has four hundred — resolves each
font's `/ToUnicode` CMap for composite and simple fonts alike, and turns wide inter-run
kerning into word breaks, because a PDF draws *"one two"* as two runs and a kern rather than
a run containing a space.

It fails closed **twice**. Once when more than 2% of glyphs came from fonts it could not map:
guessing them produces a quote that verifies perfectly against the wrong text. And again when
the mapped result does not read as language, because those are different failures and an
extractor that checks only the first hands study confident nonsense.

Measured on this host against three authoritative documents — NIST AI 100-1, NIST SP 800-207
and *Attention Is All You Need* — all three now extract clean prose with `identification` and
`organizations` intact, zero control characters, and every checked phrase present
character-for-character. The first version of this extractor produced readable-*looking* text
from the same NIST framework with the `fi` dropped out of `identification`; that is the
failure the fidelity gates exist for. OCR is still not attempted, and a scanned PDF is still
refused.

One residual, measured rather than assumed: a PDF repositions mid-line to justify text, and
treating every such move as a line break cut **328 words in half** in NIST SP 800-207
(`incl uding`, `reso urces`). Only a *vertical* move now starts a line; a horizontal one
separates. That is not free — a word repositioned mid-glyph comes out with a space in it —
and across the three documents the residual is **63 words in 42 884 (0.15%)**, a space rather
than a line break, so paragraph structure survives. A tuned distance threshold recovered 12
of those 63 and was not worth a constant that will rot.

### Link frontier

A document proposes; policy disposes. Bounded depth, per-host and per-mission page budgets,
canonical URL deduplication (tracking parameters and fragments stripped, so two spellings of
one page are one page), and only admissible tiers.

**Permission is not relevance**, and that distinction cost a page. An allowlisted host still
publishes release notes and conference notices, and the first version of this frontier
followed one into a mission about transaction isolation. A link now has to look like it is
about what the mission is studying — judged deterministically, before any page budget is
spent, from the link's path and from what the link called itself, using the same tokeniser
retrieval uses. Anchor text matters because a path like `/docs/current/xfunc.html` says
nothing while its link text says *"Transaction isolation in user functions"*.

Two details that are easy to get wrong: the host's own words are not subject matches —
`postgresql` appears in every URL on `postgresql.org`, release notes included, so counting it
makes the gate agree with everything. And a mission whose subject yields no usable words has
*no opinion* about relevance rather than refusing everything.

### Prompt injection

**Acquired text is data.** A page may contain sentences shaped like instructions — the OWASP
prompt-injection page is made of them, and being able to study it is the point. They are
recorded as an observation about the source, marked in the artifact header, and cannot admit
a source the policy refuses, approve or promote anything, or change what BRO is permitted to
do. There is no path from acquired text to authority, and the tests prove the absence by
removing each control and watching them go red.

### Autonomy

A mission may acquire before it plans, and once more to close a gap its first pass revealed.
Both are bounded by the acquisition rounds, the item budget and the **existing** stop
conditions — nothing about this extends a mission. An acquisition failure is a note, not a
crashed mission, and with no acquirer wired the runtime behaves exactly as it did before.

Internet acquisition is **off unless an operator turns it on**: `BRO_STUDY_ACQUISITION=1`.

---

## Հայերեն

### Բաժանումը, որի վրա ամեն ինչ հենված է

**Ցանցային ձեռքբերումը և ուսուցողական ընթերցումը տարբեր լիազորություններ են։**
`StudySourceReader`-ը մնում է տեղային, արմատով սահմանափակ ու անցանց։ `study_acquisition`-ը
արտաքին բերման միակ սեփականատերն է, ու ուսուցման runtime-ը այն **չի ներմուծում** — իրեն
*տալիս են* acquirer, ուրեմն դրսին հասնելու լիազորությունը տրվում է միացմամբ ու երևում է
կանչի տեղում, ոչ թե ենթադրվում ներմուծմամբ։

### Bootstrap-ի խնդիրը

Առաջ աղբյուրը պիտի արդեն manifest-ում լիներ, որ ընդհանրապես գնահատվեր — ուրեմն ինքնավար
հայտնաբերումն անհնար էր։ Հիմա screening-ը ստուգում է **`contracts/source_policy.json`**-ի
դեմ՝ բացահայտ, կառավարելի քաղաքականություն, որ գրում է մարդը ու BRO-ն խմբագրել չի կարող։

Սա գիտելիքի կառավարում է, ոչ լիազորության ընդլայնում. ընդունումը որոշում է ի՞նչ կարելի է
**ուսումնասիրել**, ոչ երբեք՝ ի՞նչ կարելի է **կատարել**։

### Շերտերը

**A** — ստանդարտների մարմիններ, պաշտոնական փաստաթղթեր, պետական շրջանակներ. ավտոմատ ընդունվում
են։ **B** — ակադեմիական։ **C** — լավ, բայց երկրորդական ուղեցույցներ. ընդունվում են միայն
մարդու որոշմամբ։ **D** — ֆորում, բլոգ, սոցցանց. **կարող են հուշել, երբեք վկայել**։
**UNCLASSIFIED** — ոչ մի ընտանիք չի հավակնում. մնում է թեկնածու մարդու համար, ու **BRO-ն
երբեք ինքը չի բարձրացնում**, որովհետև սեփական նոր աղբյուրները դասակարգել կարողացող
համակարգը ի վերջո կարող է ամեն ինչ հեղինակավոր հայտարարել։

Նմանակող host-ը ոչինչ չի ժառանգում. `evil-nist.gov`-ը `nist.gov` չէ։

### Բերումը

Միայն HTTPS, առանց credential-ի URL-ում, առանց ոչ-ստանդարտ port-ի, ու **միայն GET** — այլ
բայ ընդհանրապես արտահայտելի չէ, ու gate-ը պահում է մոդուլը ուղիղ մեկ բայի վրա։

Ամեն քայլ վերստուգվում է. և՛ առաջին հարցումը, և՛ ամեն redirect վերաստուգվում են
քաղաքականության դեմ ու վերալուծվում, ու host-ը մերժվում է, եթե թեկուզ **մեկ** հասցե
ոչ-հանրային է։ Թույլատրված host-ը, որ վերահղում է `169.254.169.254`, հենց այն ձևն է, որով
բերողը դառնում է վստահված անձ սեփական ցանցի ներսում։

Չափերը, redirect-ների քանակը, timeout-ը, փորձերն ու host-ի կշռույթը գալիս են
քաղաքականությունից։ Բյուջեի վրա կանգնած ներբեռնումը գրանցվում է որպես **մասնակի**։

### Նորմալացում

Ձեռք բերված HTML-ը դառնում է տեղային իներտ artifact՝ վերնագրերով, ցանկերով ու կոդով, առանց
script-ի, style-ի ու նավիգացիայի։ **STUDY-ն կարդում է artifact-ը, ոչ երբեք կենդանի
բովանդակություն։**

**PDF-ը հիմա իսկապես կարդացվում է, ու մերժվում է, երբ չի կարող։** `pdf_text`-ը կարդում է
իրական օբյեկտների աղյուսակը՝ ներառյալ սեղմված object stream-երը, որ օգտագործում է ամեն
PDF 1.5+, լուծում է ամեն տառատեսակի `/ToUnicode` քարտեզը, ու լայն kerning-ը դարձնում է
բառի բացակ, որովհետև PDF-ը «one two»-ն նկարում է որպես երկու հատված ու մի kern, ոչ թե
բացատ պարունակող տող։

Փակ ձախողվում է **երկու անգամ**․ մեկ՝ երբ glyph-երի 2%-ից ավելին եկել է չքարտեզագրվող
տառատեսակից, մեկ էլ՝ երբ քարտեզագրված արդյունքը լեզու չի կարդացվում։

Մեկ մնացորդ, չափված ու ոչ ենթադրված․ PDF-ը տողի մեջ վերադիրքավորվում է, ու ամեն այդպիսի
շարժը տողադարձ համարելը NIST SP 800-207-ում **328 բառ կիսեց**։ Հիմա միայն **ուղղահայաց**
շարժն է տող սկսում։ Մնացորդը՝ 42 884 բառից 63 (0.15%), ու դա բացատ է, ոչ տողադարձ։

Այս host-ի վրա չափված՝ NIST AI 100-1, NIST SP 800-207 ու «Attention Is All You Need» —
երեքն էլ հիմա տալիս են մաքուր արձակ, `identification`-ը ու `organizations`-ը ամբողջական,
զրո control նիշ։ Առաջին տարբերակը նույն NIST-ի փաստաթղթից տալիս էր **կարդացվող տեսքով**
տեքստ, որտեղ `identification`-ից ընկել էր `fi`-ն — հենց դրա համար են ճշգրտության
դարպասները։ OCR չի փորձվում, ու սկանավորված PDF-ը դեռ մերժվում է։

### Ռելեւանտության դարպաս

**Թույլտվությունը ռելեւանտություն չէ։** Թույլատրված host-ը դեռ հրապարակում է release-ի
հայտարարություններ, ու frontier-ի առաջին տարբերակը մեկը հետևեց transaction isolation-ի
առաքելության մեջ։ Հիմա հղումը պիտի **երևա որ առաքելության թեմայի մասին է** — որոշվում է
դետերմինիստիկ, էջի բյուջե ծախսելուց առաջ, հղման ուղուց ու իր իսկ տեքստից։ Host-ի սեփական
բառերը թեմայի համընկնում չեն, ու առանց օգտակար բառերի առաքելությունը կարծիք չունի, ոչ թե
ամեն ինչ մերժում է։

### Prompt injection

**Ձեռք բերված տեքստը տվյալ է։** Էջը կարող է պարունակել հրահանգի տեսք ունեցող
նախադասություններ — OWASP-ի prompt-injection-ի էջն ամբողջովին դրանցից է, ու հենց դրա
ուսումնասիրելն է իմաստը։ Դրանք գրանցվում են որպես դիտարկում աղբյուրի մասին ու չեն կարող ո՛չ
ընդունել քաղաքականության մերժած աղբյուր, ո՛չ որևէ բան հաստատել, ո՛չ փոխել BRO-ի
թույլատրվածը։

### Ինքնավարություն

Առաքելությունը կարող է ձեռք բերել պլանավորելուց առաջ ու ևս մեկ անգամ՝ բացը փակելու համար։
Երկուսն էլ սահմանափակված են ռաունդներով, item budget-ով ու **գործող** կանգառներով։ Ցանցային
ձեռքբերումն **անջատված է**, մինչև օպերատորը միացնի՝ `BRO_STUDY_ACQUISITION=1`։
