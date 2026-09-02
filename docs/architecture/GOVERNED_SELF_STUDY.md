# BRO Governed Self-Study / BRO-ի կառավարվող ինքնուսուցում

## English

### What "BRO, go learn" does

    study mission → scope and curriculum → source discovery → read → synthesis
      → verification against source → contradiction and staleness check
      → retained knowledge item → durable provenance → next item or a named stop

You do not choose a mode. A message like *"Study our repository and learn the
architecture"* is routed to `STUDY` the same way an ordinary question routes to `TALK`
and a real request routes to `ACT`. `STUDY` needs no confirmation because it changes
nothing.

### Read, think, learn — and nothing else

`GovernedStudyRuntime` has no executor, no provider, no network client, and no writer
outside the one durable learning store. It cannot approve a skill, promote a skill,
widen authority, change governance, merge, deploy or cause any external effect, because
none of those things are reachable from it. `scripts/check_self_study_contract.py`
scans the module for anything that could act — a network call, a subprocess, an
approval or promotion, a direct write — and fails `make check` if one appears.

Sources are read through `StudySourceReader`, which is bounded three ways: rooted (a
path that escapes the declared study root is refused), typed (only readable text
suffixes), and sized (a file is read up to a byte budget, and the digest covers exactly
what was read).

### The line between knowing and being told

Every claim the model proposes must carry the quote that would prove it. A claim is
**VERIFIED_KNOWLEDGE** only when that quote is actually present in the source it names —
long enough to locate, matched on normalized whitespace. A claim the model marks as its
own reasoning is kept as **INFERENCE**. Anything else is kept as **UNVERIFIED_OBSERVATION**.

Confidence follows the kind the runtime determined — 1.0, 0.5, 0.25 — never a number the
model supplied. A verified claim is knowledge; it is never permission.

### What every retained item carries

Source reference, source type, source digest, the evidence quote, verification state,
confidence, topic, mission scope, timestamp, and provenance: which model was configured,
which revision, which environment, which instance. Provenance is recorded and owns
nothing.

### Current truth wins

A knowledge item records the binding facts it depends on — the environment it was
studied in, the study root. When current truth contradicts one, the item is **withheld**
from reuse rather than quietly used, and the contradiction is reported. When the source
file's digest no longer matches, the item is surfaced as **stale**. A mission whose
binding facts drift mid-run stops with `UNRESOLVED_CONTRADICTION` for an operator to
resolve.

### Bounded, and it stops

A mission plans at most `item_budget` curriculum items from sources that already exist —
a planner that names a path outside the discovered set is ignored, and a planner that
produces nothing usable falls back to reading the discovered sources in order, so
"study this" still studies something real. Every mission ends with one named reason:

`CURRICULUM_COMPLETE` · `ITEM_BUDGET_REACHED` · `DIMINISHING_RETURNS` ·
`UNRESOLVED_CONTRADICTION` · `SOURCE_UNAVAILABLE` · `SCOPE_EXHAUSTED`

The report says what was planned, what was studied, what is blocked, what remains, how
much is verified against how much is uncertain, and that no external effect occurred.

### Reuse

Retained knowledge is recalled alongside evidenced execution experience and offered to
later reasoning as advisory context that states, in its own payload, that it grants no
authority. Scope confirmation, authority evaluation, provider restriction and
independent readback remain mandatory and untouched.

### One store

Study knowledge lives in `DurableLearningMemory`, the same authority that holds
conversation, experience, lessons and skill candidates. There is no second knowledge
store and no second execution path. Studying never creates a lesson from an executed
action and never creates a skill candidate: those still require repeated, independently
evidenced execution.

### Not claimed

No model weights are trained. No code is generated and installed. No network research
happens beyond the declared local study root. Correctness of every model-proposed claim
is not claimed — that is exactly why unverified claims stay labelled.

## Հայերեն

### Ի՞նչ է անում «BRO, գնա սովորի»-ն

    study mission → scope ու curriculum → աղբյուրների հայտնաբերում → ընթերցում
      → սինթեզ → աղբյուրի դեմ վավերացում → հակասության ու հնացման ստուգում
      → պահված գիտելիք → durable provenance → հաջորդ քայլ կամ անվանված կանգ

Ռեժիմ ընտրել պետք չէ։ «Ուսումնասիրիր մեր repository-ն» հաղորդագրությունը ինքնաբերաբար
գնում է `STUDY`, ինչպես սովորական հարցը՝ `TALK`, իսկ իրական խնդրանքը՝ `ACT`։ `STUDY`-ն
հաստատում չի պահանջում, որովհետև ոչինչ չի փոխում։

### Կարդալ, մտածել, սովորել — ուրիշ ոչինչ

`GovernedStudyRuntime`-ը չունի executor, provider, ցանցի client, ու ոչինչ չի գրում մեկ
durable store-ից դուրս։ Չի կարող skill հաստատել կամ promote անել, authority ընդլայնել,
governance փոխել, merge կամ deploy անել, արտաքին էֆեկտ ստեղծել։ Gate-ը սկանավորում է
module-ը ու կարմրում, եթե այնտեղ հայտնվի ցանցի կանչ, subprocess, approve/promote կամ
ուղիղ գրառում։

Աղբյուրները կարդացվում են `StudySourceReader`-ով, որը սահմանափակ է երեք ձևով՝ արմատով
(root-ից դուրս ելնող path մերժվում է), տեսակով և չափով։

### Սահմանը իմանալու ու ասված լինելու միջև

Model-ի ամեն պնդում պիտի կրի այն մեջբերումը, որը կապացուցի այն։ Պնդումը դառնում է
**VERIFIED_KNOWLEDGE** միայն այն դեպքում, երբ մեջբերումը իրոք առկա է իր անվանած աղբյուրում։
Model-ի սեփական դատողությունը պահվում է որպես **INFERENCE**, մնացածը՝
**UNVERIFIED_OBSERVATION**։ Confidence-ը որոշում է runtime-ը, ոչ թե model-ը։ Վավերացված
պնդումը գիտելիք է, երբեք՝ թույլտվություն։

### Ընթացիկ ճշմարտությունը գերակա է

Երբ ընթացիկ ճշմարտությունը հակասում է պահված գիտելիքի binding փաստին, այդ գիտելիքը
**պահվում է կողքի**, ոչ թե լուռ օգտագործվում։ Երբ աղբյուրի digest-ը փոխվել է, տարրը
ցուցադրվում է որպես **stale**։ Ընթացքում շեղված mission-ը կանգնում է
`UNRESOLVED_CONTRADICTION`-ով՝ operator-ի որոշման համար։

### Սահմանափակ է, ու կանգնում է

Ամեն mission-ն ավարտվում է մեկ անվանված պատճառով՝ `CURRICULUM_COMPLETE`,
`ITEM_BUDGET_REACHED`, `DIMINISHING_RETURNS`, `UNRESOLVED_CONTRADICTION`,
`SOURCE_UNAVAILABLE`, `SCOPE_EXHAUSTED`։ Անվերջ ինքնավար հետազոտության ցիկլ չկա։

### Մեկ պահեստ

Study գիտելիքը ապրում է `DurableLearningMemory`-ում՝ նույն authority-ում։ Զուգահեռ
գիտելիքի պահեստ չկա։ Ուսումնասիրելը երբեք չի ստեղծում executed-action lesson ու երբեք
skill candidate — դրանք դեռ պահանջում են կրկնվող, անկախ ապացուցված կատարում։

### Ինչ չի հայտարարվում

Model weight չի մարզվում։ Կոդ չի գեներացվում ու չի տեղադրվում։ Հայտարարված study root-ից
դուրս ցանցային հետազոտություն չկա։ Ամեն model-ի առաջարկած պնդման ճշտությունը չի
հայտարարվում — հենց դրա համար են չվավերացվածները մնում պիտակված։
