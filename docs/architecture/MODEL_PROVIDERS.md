# BRO's Inference Boundary / BRO-ի inference սահմանը

## English

### One boundary, one owner, one active backend

Everything BRO is lives above the boundary: identity, TALK/THINK/STUDY/ACT routing, the
prompts and behavioural instructions, conversation semantics, memory, durable learning,
skills, governance, authority, approval, evidence, current-truth handling, contradiction
and staleness handling, and execution semantics. A backend below it does exactly one
thing — turn a conversation into text.

    BRO
      → bro_runtime.inference.BROInference        BRO's prompts and bounded retry
        → model_provider.build_model(env)         one line of configuration
          → ClaudeCodeCLIModel._complete          the only method a backend supplies
            → claude --print (authenticated CLI session)

A backend implements `_complete` and nothing else. It does not restate a prompt, define a
mode, or decide what BRO refuses. `scripts/check_inference_boundary.py` enforces that:
each of BRO's sentences may have exactly one owner in the runtime, a backend that
redefines any behavioural method fails the gate, and a retired backend that reappears in
the tree fails it too.

### Why the rule is a gate and not a convention

It was broken once, silently. The Anthropic adapter carried its own copy of BRO's prompts
and drifted a whole interaction mode behind the product: its router still offered only
TALK, THINK and ACT with no STUDY, and its conversational path had no durable-record
message. Nothing failed; it simply answered a slightly older question. That adapter has
been removed, and the gate now makes the same drift impossible to reintroduce quietly.

### The active backend: Claude Code CLI

Configuration is `BRO_MODEL_PROVIDER=claude-code-cli` and `BRO_MODEL_NAME`, with optional
`BRO_MODEL_CLI_PATH`, `BRO_MODEL_CLI_WORKDIR` and `BRO_MODEL_TIMEOUT_SECONDS`. There is
no API key, because there is no API: the official CLI owns its own authenticated session.

The invocation is the narrowest supported shape for model-response behaviour: `--print`,
`--output-format json`, `--restricted` (no command- or code-running tools and no web
fetch), `--strict-mcp-config`, an explicit `--disallowed-tools` deny list, and an explicit
`--model`. The prompt travels on **stdin** and the argument vector is a list, so no user
text ever reaches a command line and no shell is involved.

**Authentication is the CLI's and stays the CLI's.** BRO reads no credential, stores none,
prints none and derives none; the adapter's configuration has no credential field, and a
subscription is never converted into an API key. `--bare` is deliberately unused, because
it would force API-key authentication instead of the session the CLI owns.

Claude Code is not BRO's hands, memory, approval authority or source of truth. Scope
confirmation, authority evaluation, provider restriction, independent readback, durable
learning and the study boundary are untouched by which model answered.

### Failure is reported, not hidden

Throttling, gateway faults and timeouts are transient and share one bounded retry defined
on the boundary: doubling backoff, `Retry-After` honoured within a cap, and an error that
says how many attempts were spent. A CLI with no session says so by name rather than being
retried into silence. A truncated or failed turn is never treated as an answer. Malformed
output fails closed with the offending text truncated.

### Replaceable, without a shelf of unused adapters

Replaceability is the seam, not an inventory. A future backend implements `BROInference`
and gains a case in the factory; nothing about BRO's memory, learning, governance or
identity changes, because none of it lives below the boundary. Unused provider
implementations are not kept for that day — Git history is the history.

Automatic fallback between backends is **not** implemented. It remains the next narrow
step, and it is deliberately separate: falling back mid-request has ambiguous semantics
for an ACT whose interpretation and specialist selection would come from different models.

### One Unicode-scalar boundary before transport

A lone UTF-16 surrogate is not a character. It exists in a Python string only because
something decoded bytes that were not valid UTF-8 — and Python decodes **argv, the
environment and the standard streams with `surrogateescape`**, so a truncated paste or a
terminal that is not sending UTF-8 produces one without anyone doing anything wrong.
Handed to `subprocess.run(..., text=True)`, it raises `UnicodeEncodeError` **inside
subprocess**, before the model call starts.

Every prompt therefore crosses `BROInference.complete()`, which refuses a message carrying
lone surrogates and names which one carried it — the role, the message index, the code
point and the position — so a future occurrence is diagnosable rather than mysterious.
A backend still implements only `_complete` and never calls it itself; the gate holds
`_complete` to exactly one caller, because a second one is a way around the check.

**It rejects rather than substituting `U+FFFD`.** BRO acts on the scope it was given, and
quietly rewriting a character of a request is quietly changing what it was asked to do —
the same reason materiality is owned by the runtime and never lowered downstream.
`InferenceRejected` is already a reported, non-fatal boundary failure, so the person sees a
sentence and no traceback. Every valid character passes through untouched: Armenian,
Cyrillic and emoji are carried byte-for-byte.

**Մեկ Unicode-ի սահման փոխադրումից առաջ։** Միայնակ UTF-16 surrogate-ը նիշ չէ. այն
հայտնվում է միայն այն ժամանակ, երբ ինչ-որ բան ապակոդավորել է բայթեր, որոնք վավեր UTF-8 չեն
— իսկ Python-ը argv-ն, միջավայրն ու ստանդարտ հոսքերը ապակոդավորում է `surrogateescape`-ով։
`subprocess`-ին տալիս՝ սա տապալվում է հենց subprocess-ի ներսում, մոդելի կանչից առաջ։ Ամեն
prompt անցնում է `BROInference.complete()`-ով, որը մերժում է ու անվանում, թե որ մասն էր
կրում սխալը։ **Մերժում է, ոչ թե փոխարինում** — օգտվողի բառը լուռ վերաշարադրելը նշանակում է
լուռ փոխել այն, ինչ խնդրված է։ Բոլոր վավեր նիշերն անցնում են անփոփոխ։

## Հայերեն

### Մեկ սահման, մեկ սեփականատեր, մեկ ակտիվ backend

Այն ամենը, ինչ BRO-ն է, ապրում է սահմանից վեր՝ ինքնություն, TALK/THINK/STUDY/ACT routing,
prompt-ներ, խոսակցության իմաստաբանություն, հիշողություն, durable learning, skills,
governance, authority, հաստատում, ապացույց, ընթացիկ ճշմարտություն, հակասություն ու
հնացում, կատարման իմաստաբանություն։ Սահմանից ներքև գտնվողը անում է ուղիղ մեկ բան՝
խոսակցությունը դարձնում է տեքստ։

Backend-ը իրականացնում է `_complete` ու ուրիշ ոչինչ։ Gate-ը դա պարտադրում է․ BRO-ի ամեն
նախադասություն կարող է ունենալ ուղիղ մեկ սեփականատեր runtime-ում։

### Ինչու սա gate է, ոչ պայմանավորվածություն

Այն մեկ անգամ արդեն լուռ խախտվել էր։ Anthropic adapter-ը կրում էր BRO-ի prompt-ների իր
պատճենը ու հետ էր մնացել մի ամբողջ ռեժիմով՝ իր router-ը դեռ առաջարկում էր միայն
TALK/THINK/ACT առանց STUDY-ի։ Ոչինչ չէր ձախողվում. պարզապես պատասխանում էր մի փոքր ավելի
հին հարցի։ Այդ adapter-ը հանված է, ու gate-ը հիմա նույն շեղումը լուռ վերադառնալ թույլ չի
տալիս։

### Ակտիվ backend-ը՝ Claude Code CLI

`BRO_MODEL_PROVIDER=claude-code-cli` ու `BRO_MODEL_NAME`։ API key չկա, որովհետև API չկա —
պաշտոնական CLI-ն ինքն է տիրում իր աութենտիֆիկացված սեսիային։ Կանչը ամենանեղ ձևով է՝
`--print --output-format json --restricted --strict-mcp-config`, բացահայտ deny ցուցակ,
prompt-ը **stdin**-ով, argv-ն ցուցակ, shell ընդհանրապես չկա։

**Աութենտիֆիկացիան CLI-ինն է ու մնում է CLI-ինը։** BRO-ն ոչ մի credential չի կարդում, չի
պահում, չի ածանցում։ Claude Code-ը BRO-ի HANDS-ը, հիշողությունը կամ authority-ն չէ։

### Փոխարինելի՝ առանց չօգտագործվող adapter-ների դարակի

Փոխարինելիությունը սահմանն է, ոչ թե պաշարը։ Ապագա backend-ը իրականացնում է `BROInference`
ու ստանում մեկ case factory-ում։ Չօգտագործվող իրականացումները չեն պահվում «այդ օրվա
համար» — պատմությունը Git-ում է։

Backend-ների միջև ավտոմատ fallback-ը **իրականացված չէ** ու մնում է հաջորդ նեղ քայլը։
