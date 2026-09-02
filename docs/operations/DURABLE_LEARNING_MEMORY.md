# BRO Durable Learning Memory / BRO-ի երկարաժամկետ ուսուցման հիշողություն

## English

BRO now has a repository-side durable memory and outcome-learning boundary for the conversational interaction surface.

The runtime persists recent conversation messages in SQLite, records ACT outcomes, accumulates reusable lessons only from externally evidenced successful actions, and can surface a reusable skill candidate after repeated success. Learned lessons may be reused as context for later discussion and specialist selection.

Learning never grants authority. A candidate starts as `CANDIDATE`; BRO cannot promote it directly. Promotion requires an explicit approval transition followed by a separate explicit promotion transition with recorded actors. Existing ACT scope confirmation, authority, provider execution, and independent readback remain unchanged.

The production CLI uses `BRO_MEMORY_DB_PATH` when set and otherwise uses `/var/lib/bro/runtime.sqlite3`, allowing the Debian interaction surface to reuse the durable production database.

This change does not claim automatic skill code generation, automatic installation, or production deployment until the new revision is deployed and read back on the host.

## Հայերեն

BRO-ի conversational interaction surface-ը հիմա ունի repository-side durable memory և outcome-learning սահման։

Runtime-ը SQLite-ում պահպանում է վերջին խոսակցությունները, գրանցում է ACT արդյունքները, reusable lesson է կուտակում միայն այն հաջող գործողություններից, որոնք ունեն արտաքին evidence, և կրկնվող հաջողությունից հետո կարող է ստեղծել reusable skill candidate։ Այդ lesson-ները հետագայում կարող են օգտագործվել քննարկման և specialist ընտրության context-ում։

Սովորելը authority չի ավելացնում։ Candidate-ը սկսվում է `CANDIDATE` վիճակից, և BRO-ն ինքն իրեն promote անել չի կարող։ Promotion-ի համար անհրաժեշտ է առանձին explicit approval transition և դրանից հետո առանձին explicit promotion transition՝ գրանցված actor-ներով։ Existing ACT scope confirmation-ը, authority-ն, provider execution-ը և independent readback-ը չեն շրջանցվում։

Production CLI-ն օգտագործում է `BRO_MEMORY_DB_PATH`, եթե այն սահմանված է, հակառակ դեպքում՝ `/var/lib/bro/runtime.sqlite3`, որպեսզի Debian interaction surface-ը կարողանա օգտագործել durable production database-ը։

Այս փոփոխությունը չի հայտարարում automatic skill-code generation, automatic installation կամ production deployment, մինչև նոր revision-ը իրական host-ում deploy և readback չարվի։
