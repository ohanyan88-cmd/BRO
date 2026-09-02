# BRO Model Providers / BRO-ի model provider-ները

## English

### A model is a backend, never the authority

BRO owns its prompts, memory, evidence, governance and authority. A provider answers
questions and nothing else. Switching provider changes one thing in the record — the
provenance of who reasoned — and nothing else at all.

    BRO → model_provider.build_model(env) → one of:
        claude-code-cli   the locally authenticated Claude Code CLI
        anthropic         the Anthropic Messages API
        cloudflare / any  an OpenAI-compatible chat-completions endpoint

Selection is configuration: `BRO_MODEL_PROVIDER`, `BRO_MODEL_NAME`, and whatever that
provider needs. Adding a backend means adding a case to one factory. Both production
entrypoints call that factory, so they cannot drift apart.

### One set of prompts

Every provider inherits BRO's prompt layer rather than restating it. Routing, scope
interpretation, specialist selection, the durable-record system message, study planning
and study extraction are defined once. A provider overrides only the step that turns a
conversation into text.

This matters because it has already gone wrong: the Anthropic adapter carries its own
copy of those prompts and has fallen behind — its router still offers only TALK, THINK
and ACT, with no STUDY, and its conversational path has no durable-record message. A
provider that restates BRO's prompts is a provider that will eventually answer a
different question. The Claude Code adapter does not restate them, and a test asserts
that its shared methods are literally BRO's.

### Claude Code CLI

The official CLI is invoked non-interactively in the narrowest supported shape:
`--print`, `--output-format json`, `--restricted` (no command- or code-running tools and
no web fetch), `--strict-mcp-config`, an explicit `--disallowed-tools` deny list, and an
explicit `--model`. The prompt travels on **stdin** and the argument vector is a list, so
no user text is ever concatenated into a command line and no shell is involved.

**Authentication is the CLI's, and stays the CLI's.** BRO reads no credential, stores
none, prints none, and derives none; there is no credential field in the adapter's
configuration, and a Claude subscription is never converted into an API key. `--bare` is
deliberately not used, because it would force API-key authentication instead of the
session the CLI owns.

Claude Code is not BRO's hands, memory, approval authority or source of truth. Scope
confirmation, authority evaluation, provider restriction, independent readback, durable
learning and the study boundary are untouched by which model answered.

### Failure is reported, not hidden

Every provider shares the same bounded retry: throttling and gateway faults are worth one
more try with backoff, and a configuration or authentication fact is not. When attempts
are spent the error says how many were spent. A CLI that has no session says so by name
instead of being retried into silence, and a truncated or failed turn is never treated as
an answer.

### Not yet claimed

An ordered provider chain with automatic fallback is **not** implemented. It is the next
narrow step, and it is deliberately separate: falling back mid-request has ambiguous
semantics for an ACT whose interpretation and specialist selection would then come from
different models, and any such chain must preserve provenance, stay bounded, and never
replay an external effect.

## Հայերեն

### Model-ը backend է, ոչ երբեք authority

BRO-ն տիրում է իր prompt-ներին, հիշողությանը, ապացույցներին, governance-ին ու
authority-ին։ Provider-ը միայն պատասխանում է հարցերին։ Provider փոխելը գրառման մեջ փոխում
է մեկ բան՝ ով է դատողություն արել, ու ուրիշ ոչինչ։

Ընտրությունը կոնֆիգուրացիա է՝ `BRO_MODEL_PROVIDER`, `BRO_MODEL_NAME`։ Նոր backend
ավելացնելը նշանակում է մեկ factory-ում մեկ case ավելացնել։

### Մեկ հավաքածու prompt

Ամեն provider ժառանգում է BRO-ի prompt շերտը, ոչ թե վերաշարադրում։ Դա արդեն մեկ անգամ
սխալ է գնացել․ Anthropic adapter-ը ունի իր սեփական պատճենը ու հետ է մնացել — իր router-ը
դեռ առաջարկում է միայն TALK/THINK/ACT առանց STUDY-ի։ Prompt-ները վերաշարադրող provider-ը
վաղ թե ուշ այլ հարցի է պատասխանելու։

### Claude Code CLI

Կանչվում է ոչ-ինտերակտիվ ու ամենանեղ ձևով՝ `--print`, `--output-format json`,
`--restricted`, `--strict-mcp-config`, բացահայտ deny ցուցակ, բացահայտ `--model`։ Prompt-ը
գնում է **stdin**-ով, argv-ն ցուցակ է, ուստի ոչ մի օգտատիրոջ տեքստ չի կպչում հրամանի
տողին ու shell ընդհանրապես չկա։

**Աութենտիֆիկացիան CLI-ինն է ու մնում է CLI-ինը։** BRO-ն ոչ մի credential չի կարդում, չի
պահում, չի տպում ու չի ածանցում, ու բաժանորդագրությունը երբեք API key չի դառնում։

Claude Code-ը BRO-ի HANDS-ը, հիշողությունը, հաստատող authority-ն կամ ճշմարտության
աղբյուրը չէ։

### Ինչ դեռ չի հայտարարվում

Ավտոմատ fallback-ով provider-ների շղթան **իրականացված չէ**։ Դա հաջորդ նեղ քայլն է ու
դիտմամբ առանձին․ ACT-ի կեսին provider փոխելը երկիմաստ իմաստաբանություն է ստեղծում։
