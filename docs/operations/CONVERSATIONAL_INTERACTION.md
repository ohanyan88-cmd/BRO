# BRO Conversational Interaction / BRO զրույցային փոխազդեցություն

## English

BRO has one natural-language entrypoint and routes each turn to one of three modes:

- **TALK** — ordinary conversation and discussion. No external effect is allowed.
- **THINK** — analysis, comparison, planning, and reasoning. No external effect is allowed in this first slice.
- **ACT** — a request to change an external system or cause a real-world effect. ACT delegates to the existing governed `IntelligentInteractionRuntime` path and preserves explicit material-scope confirmation, specialist selection, real provider execution, and independent readback.

The user does not choose a mode manually. The model routes the latest message using bounded in-session conversation history. When routing is uncertain between conversational reasoning and action, the model is instructed to choose TALK or THINK rather than infer permission to act.

Action-provider credentials are loaded only when ACT reaches execution. Missing GitHub action credentials therefore do not prevent TALK or THINK from working.

This change does not add durable memory or autonomous learning. Conversation history is in-memory for the current CLI session only. Durable memory, learning from outcomes, and reusable skill promotion are separate controlled capabilities.

## Հայերեն

BRO-ն ունի մեկ բնական լեզվով մուտք և յուրաքանչյուր հաղորդագրություն ավտոմատ ուղղում է երեք ռեժիմներից մեկին․

- **TALK** — սովորական զրույց և քննարկում։ Արտաքին գործողություն չի թույլատրվում։
- **THINK** — վերլուծություն, համեմատություն, պլանավորում և մտածում։ Այս առաջին տարբերակում արտաքին գործողություն չի թույլատրվում։
- **ACT** — արտաքին համակարգում փոփոխություն կամ իրական ազդեցություն պահանջող գործողություն։ ACT-ը փոխանցվում է արդեն գոյություն ունեցող governed `IntelligentInteractionRuntime` ճանապարհին և պահպանում է material scope-ի explicit confirmation-ը, specialist selection-ը, իրական provider execution-ը և անկախ readback-ը։

Օգտատերը ռեժիմը ձեռքով չի ընտրում։ Model-ը որոշում է ռեժիմը՝ օգտագործելով ընթացիկ session-ի սահմանափակ conversation history-ն։ Եթե TALK/THINK և ACT միջև վստահություն չկա, router-ը պետք է ընտրի TALK կամ THINK և երբեք ինքնուրույն չեզրակացնի գործողության թույլտվություն։

Action provider-ի credential-ները բեռնվում են միայն այն պահին, երբ ACT-ը հասնում է execution-ի։ Հետևաբար GitHub action credential-ի բացակայությունը չի խանգարում TALK կամ THINK ռեժիմներին։

Այս փոփոխությունը դեռ durable memory կամ autonomous learning չի ավելացնում։ Conversation history-ն միայն ընթացիկ CLI session-ի memory-ն է։ Durable memory-ն, արդյունքներից սովորելը և reusable skill promotion-ը առանձին governed capability-ներ են։
