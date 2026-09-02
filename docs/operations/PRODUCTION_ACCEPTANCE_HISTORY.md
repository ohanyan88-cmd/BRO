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
