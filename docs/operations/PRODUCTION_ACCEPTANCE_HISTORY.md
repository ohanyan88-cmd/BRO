# Production Acceptance History / Production acceptance-ի պատմությունը

## English

This file records what was true, including where a candidate did not pass. Nothing here
is rewritten to look better later.

### `ff69830a7a2547e2984020cc58ef4698a860d020` — ACCEPTED

Deployed and SHA-bound production-accepted, backed by the temporary Cloudflare provider.
Acceptance run `acceptance:ee83656e-6f89-4561-8755-5e83a50426ed`, external evidence
`github-external-readback:comment:5508460022` on `ohanyan88-cmd/BRO` issue #45, recorded
in the durable release ledger on 2026-09-02.

### `49bfd5f647b8c0140495aae01b061e10e60ad3b4` — DEPLOYED, NEVER ACCEPTED, SUPERSEDED

This revision **was deployed** to the Debian production host and passed `HOST_DEPLOYED`
verification: service active, exact configured revision, healthy heartbeat read back from
durable state.

It was **never SHA-bound production-accepted**, and must never be represented as accepted.

Its acceptance could not complete for a reason outside the revision itself: the temporary
Cloudflare bootstrap provider returned `HTTP 429` with the body *"you have used up your
daily free allocation of 10,000 neurons"*. That is a daily account quota, not a transient
throttle, so the governed acceptance path — which needs the model for interpretation and
specialist selection — could not run at all. Fifteen probes over fifteen minutes and
further probes hours later all returned 429.

It has now been **intentionally superseded by product decision**. Cloudflare was a
bootstrap provider used to prove BRO could run against a real external model; it is not an
intended production dependency, and no Cloudflare capacity was purchased to make this
historical candidate pass. The acceptance target moved to the cleaned, Claude-Code-backed
revision that follows it.

The requirement to accept this candidate is closed by that decision, not by evidence.

### Night School v1 — ACCEPTED

The governed knowledge library, the fifty-document corpus, cross-language recall, and the
correction that made `APPROVED_FOR_STUDY` mean what it says.

Accepted on the established isolated governed ACT path: the runtime interpreted the request,
the interpreted scope was read and confirmed against its own digest before any external
effect was attempted, one comment was posted to the configured isolated issue, and a
**separate** external read confirmed it. `ProductionControlPlane.activate` recorded the
result behind an acceptance run carrying both the external-system check and the host
exact-revision readback.

This entry names no revision, on purpose. Writing it is itself a commit, so deploying it
moves the deployed SHA — the first draft of the previous entry said "production runs
918c80d4" and was false on arrival. The live answer is `/etc/bro/bro.release.env` and the
ledger itself:

    bind_production_acceptance.py --verify   →  state ACTIVE, matches_configured_revision true

What holds: **the accepted revision and the deployed revision are the same**, and acceptance
is bound to that exact SHA. It never travels to a later one; the next revision starts its own
acceptance from nothing.

Two things this does **not** claim. It is not `PRODUCTION_GRADUATED`, which still needs the
identity, custody and DR blocks in `contracts/final_delivery.json`. And it says nothing about
whether a person read the fifty study documents — nobody has; every source in the corpus
reads `NOT_HUMAN_REVIEWED`, which is the accurate value.

## Հայերեն

Այս ֆայլը գրանցում է այն, ինչ եղել է, ներառյալ այնտեղ, ուր թեկնածուն չի անցել։ Այստեղ
ոչինչ հետո չի գեղեցկացվում։

### `ff69830a…` — ԸՆԴՈՒՆՎԱԾ

Deployed ու SHA-կապված ընդունված՝ ժամանակավոր Cloudflare provider-ով, acceptance run
`acceptance:ee83656e…`, արտաքին ապացույց՝ issue #45-ի comment 5508460022։

### `49bfd5f6…` — DEPLOYED, ԵՐԲԵՔ ՉԸՆԴՈՒՆՎԱԾ, ՓՈԽԱՐԻՆՎԱԾ

Այս revision-ը **deploy արվել է** ու անցել է `HOST_DEPLOYED` ստուգումը՝ active service,
ճշգրիտ configured revision, healthy heartbeat durable state-ից։

Այն **երբեք SHA-կապված ընդունված չի եղել** ու երբեք չպետք է ներկայացվի որպես ընդունված։

Acceptance-ը չկարողացավ ավարտվել revision-ից դուրս պատճառով․ ժամանակավոր Cloudflare
provider-ը վերադարձնում էր `HTTP 429`՝ «you have used up your daily free allocation of
10,000 neurons»։ Դա օրական հաշվի քվոտա է, ոչ անցողիկ throttle, ուստի governed acceptance
ուղին ընդհանրապես չէր կարող վազել։

Հիմա այն **միտումնավոր փոխարինված է product որոշմամբ**։ Cloudflare-ը bootstrap provider
էր ու production կախվածություն չէ. այս պատմական թեկնածուն անցկացնելու համար Cloudflare
capacity չի գնվել։ Ընդունման թիրախը տեղափոխվել է մաքրված, Claude-Code-ով աշխատող
revision-ին։

Այս թեկնածուն ընդունելու պահանջը փակվում է որոշմամբ, ոչ թե ապացույցով։

### Night School v1 — ԸՆԴՈՒՆՎԱԾ

Կառավարվող գիտելիքի գրադարանը, հիսուն փաստաթղթանոց corpus-ը, խաչ-լեզվային recall-ը ու այն
ուղղումը, որից հետո `APPROVED_FOR_STUDY`-ն նշանակում է հենց այն, ինչ ասում է։

Ընդունվել է սահմանված մեկուսացված governed ACT ուղով․ runtime-ը մեկնաբանել է հարցումը,
մեկնաբանված շրջանակը կարդացվել ու հաստատվել է իր digest-ով **նախքան** որևէ արտաքին էֆեկտ,
մեկ comment է գրվել կարգավորված մեկուսացված issue-ում, ու **առանձին** արտաքին ընթերցում
հաստատել է այն։

Այս գրառումը միտումնավոր revision չի անվանում։ Այն գրելը ինքը commit է, ուրեմն deploy-ը
շարժում է SHA-ն — նախորդ գրառման առաջին տարբերակը գրում էր «production runs 918c80d4» ու
կեղծ էր ժամանելուն պես։ Կենդանի պատասխանը `/etc/bro/bro.release.env`-ն է ու ledger-ը՝
`bind_production_acceptance.py --verify` → `state ACTIVE`, `matches_configured_revision true`։

Ինչը մնում է ճշմարիտ՝ **ընդունված revision-ը և deploy արվածը նույնն են**, ու acceptance-ը
կապված է հենց այդ SHA-ին։ Այն երբեք չի փոխանցվում հաջորդին։

Երկու բան, որ սա **չի** պնդում։ Սա `PRODUCTION_GRADUATED` չէ — դրան դեռ պետք են
`contracts/final_delivery.json`-ի identity, custody ու DR բլոկները։ Ու սա ոչինչ չի ասում այն
մասին, թե մարդ կարդացե՞լ է հիսուն ուսումնական փաստաթուղթը — ոչ ոք չի կարդացել, ու corpus-ի
ամեն աղբյուր գրված է `NOT_HUMAN_REVIEWED`, ինչը ճշգրիտ արժեքն է։
