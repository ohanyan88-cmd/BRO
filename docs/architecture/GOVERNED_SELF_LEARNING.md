# BRO Governed Self-Learning / BRO-ի կառավարվող ինքնուսուցում

## English

### The loop

    experience → outcome/evidence → lesson → validation → repeated evidence
      → skill candidate → explicit approval → explicit promotion → reuse → new outcome

Every step is durable, inspectable SQLite state that belongs to BRO.

### One learning entry

`bro_runtime.learning_boundary.GovernedLearningBoundary` is the single place an action
outcome becomes experience. Both production ACT paths submit to it: the conversational
surface (`scripts/bro_interact.py`) and the canonical acceptance script
(`scripts/run_production_intelligent_acceptance.py`). The boundary executes nothing,
authorises nothing and owns no storage — it applies the evidence rules and files the
outcome in `DurableLearningMemory`. `scripts/check_learning_contract.py` refuses any
other production module that writes a lesson, so a second learning authority cannot
appear quietly.

### What BRO learns

An outcome may become a **lesson** only when the governed receipt carries external-system
(or production) assurance, a real effect reference, an independent readback reference and
an evidence reference, and the readback is not the execution self-attesting. Anything else
is kept as **experience** and nothing more.

A lesson separates two kinds of content:

- **observations** — facts the runtime derived from the receipt: the capability that acted,
  the assurance class, the effect/readback/evidence references, the specialist that was
  chosen, the revision it happened on. Never model prose.
- **guidance** — the reusable inference: what worked, the procedure, the trigger. This is
  the only part a model produces.

Facts recorded under the `binding:` prefix are claims that must still hold for the lesson
to apply — the environment, the capability, the external target it was bound to.

### What BRO does not learn

No model weights are trained or fine-tuned. No code is generated and installed. A skill
candidate is structured knowledge — trigger, intended outcome, preconditions, procedure,
required authority, verification expectations, known failure modes, provenance and
supporting executions — not executable arbitrary code. Learning grants no authority.

### The model is provenance, never the owner

The reasoning model proposes guidance. It does not decide the pattern a lesson is filed
under, the observations that support it, the evidence references, or the confidence: those
are derived by the runtime from the receipt. The pattern key is a digest of the normalized
request plus the **capability class** taken from the provider reference — a runtime-owned
identity — so replacing the model does not fragment BRO's learned state. Only whitelisted
receipt fields ever reach the extractor; credentials and provider payloads never do.

Storage is ordinary SQLite with no provider-specific semantics. A lesson learned while one
model was configured is retrieved and reinforced under another, with the earlier model kept
as provenance.

### Confidence, contradiction and staleness

Confidence is `successes / (successes + failures)` over independently evidenced outcomes.
A failure recorded against a learned pattern raises its failure count, lowers its
confidence, and disputes the lesson below 0.6. A lesson can also be marked `STALE` or
`RETIRED` by an explicit operator transition. Retired lessons are never retrieved.

Current truth always outranks remembered truth. When a lesson's binding facts contradict
the current environment, capability or configured target, the lesson is **withheld** from
reuse and the contradiction is recorded in `bro_learning_contradictions` — BRO does not
silently prefer what it remembers. A later revision is not a contradiction: history is not
a claim about now.

### Reuse

Retrieval is deterministic: term overlap against a lesson's identity and body, weighted by
confidence and evidenced successes, with retired lessons excluded and disputed lessons
ranked last. What comes back is offered to planning and specialist selection as advisory
context that states, in the payload itself, that it grants no authority. Scope
confirmation, authority evaluation, provider restriction and independent readback remain
mandatory and unchanged.

### Candidate lifecycle

    CANDIDATE → APPROVED → PROMOTED

A candidate appears only after the configured threshold of independently evidenced
successes for the same BRO-owned pattern. BRO cannot approve or promote it: approval
requires an explicit named actor, promotion requires a prior approval and a separate
explicit transition, and every transition is appended to
`bro_skill_candidate_transitions`.

### Truth boundary

Repository implementation and its tests are not production evidence. Production learning
is claimed only after the revision is deployed, read back at the exact SHA, and a live
governed ACT with independent external evidence has produced a durable record.

## Հայերեն

### Ցիկլը

    փորձ → արդյունք/ապացույց → դաս → վավերացում → կրկնվող ապացույց
      → skill candidate → բացահայտ հաստատում → բացահայտ promotion → վերաօգտագործում

Ամեն քայլ durable SQLite վիճակ է, որը պատկանում է BRO-ին։

### Մեկ մուտք ուսուցման մեջ

`GovernedLearningBoundary`-ն այն միակ տեղն է, որտեղ գործողության արդյունքը դառնում է
փորձ։ Երկու production ACT ուղիներն էլ ուղարկում են այնտեղ՝ conversational CLI-ն ու
canonical acceptance script-ը։ Boundary-ն ոչինչ չի կատարում, ոչ մի իրավունք չի տալիս ու
պահեստ չունի։ `check_learning_contract.py`-ն մերժում է ցանկացած ուրիշ production module,
որը դաս է գրում — երկրորդ learning authority չի կարող լուռ հայտնվել։

### Ի՞նչ է սովորում BRO-ն

Արդյունքը կարող է դառնալ **դաս** միայն այն դեպքում, երբ governed receipt-ը կրում է
external-system assurance, իրական effect reference, անկախ readback reference և evidence
reference, ու readback-ը execution-ի ինքնավկայությունը չէ։ Մնացած ամեն ինչ մնում է որպես
**փորձ**, ոչ ավելին։

Դասը տարանջատում է **observations**-ը (runtime-ի կողմից receipt-ից բխեցրած փաստեր) և
**guidance**-ը (վերաօգտագործելի եզրակացություն, միակ մասը, որ model-ն է տալիս)։

### Ի՞նչ չի սովորում BRO-ն

Ոչ մի model weight չի մարզվում։ Ոչ մի կոդ չի գեներացվում ու չի տեղադրվում։ Skill
candidate-ը կառուցվածքային գիտելիք է, ոչ թե կամայական կատարվող կոդ։ Ուսուցումը իրավունք
չի տալիս։

### Model-ը provenance է, ոչ սեփականատեր

Model-ը առաջարկում է guidance։ Pattern-ի ինքնությունը, observations-ը, evidence-ը և
confidence-ը որոշում է runtime-ը՝ receipt-ից։ Pattern key-ն նորմալացված հարցման ու
**capability class**-ի digest-ն է, ուստի model փոխելը BRO-ի սովորածը չի կոտրում։
Պահեստը սովորական SQLite է՝ առանց provider-ի հատուկ իմաստաբանության։

### Confidence, հակասություն և հնացում

Confidence-ը `successes / (successes + failures)` է։ Ձախողումը իջեցնում է այն, ու 0.6-ից
ցածր դասը դառնում է DISPUTED։ Operator-ը կարող է դասը նշել `STALE` կամ `RETIRED`։

Ընթացիկ ճշմարտությունը միշտ գերակա է հիշվածին։ Երբ դասի binding փաստերը հակասում են
ընթացիկ միջավայրին կամ configured target-ին, դասը **պահվում է կողքի**, ու հակասությունը
գրանցվում է։ Նոր revision-ը հակասություն չէ։

### Candidate-ի կենսացիկլ

    CANDIDATE → APPROVED → PROMOTED

BRO-ն ինքն իրեն չի կարող հաստատել կամ promote անել. հաստատումը պահանջում է անուն ունեցող
actor, promotion-ը՝ նախապես տրված հաստատում և առանձին բացահայտ անցում, ու ամեն անցում
գրվում է append-only աղյուսակում։

### Truth boundary

Repository-ի իրականացումը production ապացույց չէ։ Production ուսուցումը հայտարարվում է
միայն deploy-ից, ճշգրիտ SHA-ի readback-ից և իրական governed ACT-ից հետո։
