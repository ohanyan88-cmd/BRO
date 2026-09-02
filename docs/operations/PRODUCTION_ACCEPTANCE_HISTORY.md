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

### `918c80d4…` — DEPLOYED, NOT YET ACCEPTED

Night School v1: the governed knowledge library, the fifty-document corpus and
cross-language recall. **Deployed and verified as `HOST_DEPLOYED`** — active service, exact
configured revision, healthy heartbeat from durable state, corpus containment `PASS` on 50
documents, and `STUDY` reading exactly those 50 and still refusing to escape its root.

It is **not accepted**, and the release ledger says so itself: the `ACTIVE` acceptance still
names `d9522ea2…` and reports `matches_configured_revision: false`. Acceptance is
SHA-bound and is never transferred between revisions, so the accepted baseline stays where
its evidence is until a real external governed ACT is performed on this revision and read
back independently. That needs an authorised external write, which this work package did
not carry.

Read plainly: production runs `918c80d4…`, production's last *accepted* revision is
`d9522ea2…`, and those are two different sentences.

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

### `918c80d4…` — DEPLOYED, ԴԵՌ ՉԸՆԴՈՒՆՎԱԾ

Night School v1՝ կառավարվող գիտելիքի գրադարանը, հիսուն փաստաթղթանոց corpus-ը ու
խաչ-լեզվային recall-ը։ **Deploy արված ու ստուգված որպես `HOST_DEPLOYED`** — active
service, ճշգրիտ configured revision, healthy heartbeat durable state-ից, corpus-ի
պարունակման `PASS` 50 փաստաթղթի վրա, ու `STUDY`-ն կարդում է հենց այդ 50-ը ու շարունակում
է մերժել իր արմատից դուրս գալը։

**Ընդունված չէ**, ու դա ասում է հենց release ledger-ը․ `ACTIVE` acceptance-ը դեռ կրում է
`d9522ea2…` անունը ու հայտնում `matches_configured_revision: false`։ Acceptance-ը
SHA-կապված է ու երբեք չի փոխանցվում revision-ից revision, ուրեմն ընդունված baseline-ը
մնում է այնտեղ, ուր իր ապացույցն է, մինչև այս revision-ի վրա կատարվի իրական արտաքին
governed ACT ու անկախ readback։ Դրա համար պետք է թույլատրված արտաքին գրառում, որը այս
աշխատանքային փաթեթը չի կրել։

Ուղիղ՝ production-ը վազում է `918c80d4…`, production-ի վերջին **ընդունված** revision-ը
`d9522ea2…` է, ու սրանք երկու տարբեր նախադասություն են։
