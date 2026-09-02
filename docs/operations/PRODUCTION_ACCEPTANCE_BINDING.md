# BRO Production Acceptance Binding / Production acceptance-ի կապումը revision-ին

## English

Two controls in front of a real external effect were declared but not enforced, and the evidence produced by the governed ACT path had nowhere durable to land. This change closes both without adding a second execution or acceptance path.

**Materiality is owned by the runtime, not the model.** `IntelligentInteractionRuntime` interpreted the request through the configured external model and then let that same model's `material` boolean decide whether the explicit scope confirmation applied. A model answering `material: false` therefore removed the human confirmation standing in front of a real external write. Materiality is now a runtime property, `material_floor`, defaulting to `True`: model output may raise a governance requirement and may never lower one. Lowering the floor is a deliberate composition decision made in code by the caller that wires the executor, never by model output.

**Declared contract requirements are executed.** `contracts/interaction_surface.json` had no gate at all and `scripts/check_final_delivery_contract.py` was referenced by nothing — neither the Makefile nor CI. `make check` now runs both. `scripts/check_interaction_surface_contract.py` binds every declared requirement to a source marker, verifies that action credentials are demanded only inside the governed ACT closures, and fails closed when a requirement is declared without an enforcement mapping.

**Acceptance evidence is owned by the exact deployed revision.** `scripts/run_production_intelligent_acceptance.py` now requires `BRO_SOURCE_REVISION` and writes it into the acceptance record. `scripts/bind_production_acceptance.py` reads that record, refuses it if it names another revision, lacks external-system assurance, or self-attests; reads the host back so the live release link must resolve to that revision's directory; runs the canonical acceptance checks with `require_external=True`; and records the result through `ProductionControlPlane.activate`, which already refuses anything but an independently read-back PROMOTED deployment plus a PASS run carrying external evidence. `--verify` reads the ledger back without writing.

The binder creates no acceptance authority of its own and upgrades no assurance. Host deployment, heartbeat health and a bound acceptance record together are `PRODUCTION_ACCEPTED`; they remain separate from `PRODUCTION_GRADUATED`, which still requires the identity, custody and DR blocks in `contracts/final_delivery.json`.

## Հայերեն

Իրական արտաքին էֆեկտի դիմաց կանգնած երկու վերահսկողություն հայտարարված էր, բայց ոչ մի բան չէր կատարում դրանք, իսկ governed ACT ուղու տված evidence-ը durable տեղ չուներ։ Այս փոփոխությունը փակում է երկուսն էլ՝ առանց երկրորդ execution կամ acceptance ուղի ավելացնելու։

**Materiality-ն runtime-ինն է, ոչ թե model-ինը։** `IntelligentInteractionRuntime`-ը հարցումը մեկնաբանում էր արտաքին model-ով, ու հետո թողնում էր որ նույն model-ի `material` դաշտը որոշի՝ պե՞տք է explicit scope confirmation, թե ոչ։ `material: false` պատասխանող model-ը հանում էր իրական արտաքին գրառման դիմաց կանգնած մարդկային հաստատումը։ Հիմա materiality-ն runtime-ի հատկություն է՝ `material_floor`, default-ը `True`. model-ի ելքը կարող է պահանջը բարձրացնել, բայց երբեք իջեցնել։ Floor-ն իջեցնելը կոդում կայացվող գիտակցված որոշում է, ոչ թե model-ի ելք։

**Հայտարարված contract-ի պահանջները հիմա իրոք վազում են։** `contracts/interaction_surface.json`-ը ընդհանրապես gate չուներ, իսկ `scripts/check_final_delivery_contract.py`-ին ոչ Makefile-ը, ոչ CI-ը չէր կանչում։ `make check`-ը հիմա վազեցնում է երկուսն էլ։

**Acceptance evidence-ը պատկանում է ճշգրիտ deploy արված revision-ին։** Acceptance record-ը հիմա կրում է `BRO_SOURCE_REVISION`, իսկ `scripts/bind_production_acceptance.py`-ն մերժում է այն, եթե ուրիշ revision է անվանում, external assurance չունի կամ ինքն իրեն է վկայում, ապա host-ը կարդում է հետ և գրանցում `ProductionControlPlane.activate`-ով։ `--verify`-ը ledger-ը կարդում է առանց գրելու։

Binder-ը սեփական acceptance authority չի ստեղծում և ոչ մի assurance չի բարձրացնում։ `PRODUCTION_GRADUATED`-ը մնում է առանձին ու դեռ պահանջում է `contracts/final_delivery.json`-ի identity, custody և DR բլոկները։
