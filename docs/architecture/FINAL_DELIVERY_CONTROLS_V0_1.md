# BRO Final Delivery Controls v0.1 / BRO Final Delivery Controls v0.1

## English

The final audit identified three remaining delivery blocks after the previously merged runtime and production-control work. This package closes the **repository-side executable seams** for those blocks without claiming that repository CI can manufacture production evidence.

### 1. Intelligent interaction + real capability execution
`IntelligentInteractionRuntime` accepts a production model boundary, converts natural-language requests into explicit interpreted scope and success conditions, requires digest-bound human confirmation for material scope, selects a specialist, executes through a provider boundary, and requires independent external-system readback before returning a capability receipt. Repository-only assurance and self-attested readback fail closed.

### 2. Production service + identity + human loop + resilience
`ProductionServiceControl` requires each production instance to bind an external workload identity, external vault backend, and external approval channel. It provides a durable single-primary lease with monotonic fencing tokens. A second instance cannot become primary while a live lease exists; failover after expiry produces a newer fencing token and invalidates the previous writer.

This complements, rather than replaces, the existing persistent scheduler/worker, secret mediation, notification/human loop, incidents, heartbeat and production activation components.

### 3. Durable truth + DR + production graduation
`DurableTruthCustody` records append-only hash-chained receipts for evidence placed in remote custody. Production graduation additionally requires a valid production service fence, externally assured real-capability receipt, remote backup/restore evidence with `production` assurance, explicit production acceptance evidence, a valid custody chain, and zero unresolved material contradictions.

### Truth boundary
The code proves the controls fail closed. It **does not** prove that an IAM, vault, approval service, object store, DR environment, model service, business provider or production deployment actually exists. Those facts must enter through externally attested evidence. Only then may the graduation control emit `PRODUCTION_GRADUATED`.

---

## Հայերեն

Final audit-ը նախկինում merge արված runtime և production-control աշխատանքներից հետո առանձնացրել է երեք մնացած delivery block։ Այս փաթեթը փակում է դրանց **repository-side executable seam-երը**՝ առանց ձևացնելու, թե repository CI-ն կարող է ինքնուրույն ստեղծել production evidence։

### 1. Intelligent interaction + real capability execution
`IntelligentInteractionRuntime`-ը ընդունում է production model boundary, բնական լեզվով request-ը դարձնում է explicit interpreted scope և success conditions, material scope-ի համար պահանջում է digest-bound human confirmation, ընտրում է specialist, կատարում է գործողությունը provider boundary-ով և capability receipt վերադարձնելուց առաջ պարտադիր պահանջում է independent external-system readback։ Repository-only assurance-ը և self-attested readback-ը fail closed են։

### 2. Production service + identity + human loop + resilience
`ProductionServiceControl`-ը production instance-ի համար պահանջում է external workload identity, external vault backend և external approval channel։ Այն ապահովում է durable single-primary lease և monotonic fencing token։ Երկրորդ instance-ը չի կարող primary դառնալ, քանի դեռ առաջինի live lease-ը գործում է, իսկ lease expiry-ից հետո failover-ը ստանում է ավելի նոր fencing token և հին writer-ը դառնում է անվավեր։

Սա լրացնում է արդեն գոյություն ունեցող persistent scheduler/worker, secret mediation, notification/human loop, incident, heartbeat և production activation բաղադրիչները, ոչ թե փոխարինում դրանց։

### 3. Durable truth + DR + production graduation
`DurableTruthCustody`-ն պահպանում է remote custody-ում գտնվող evidence-ի append-only hash-chained receipt-երը։ Production graduation-ը լրացուցիչ պահանջում է valid production service fence, externally assured real-capability receipt, remote backup/restore evidence՝ `production` assurance-ով, explicit production acceptance evidence, valid custody chain և zero unresolved material contradictions։

### Truth boundary
Կոդը ապացուցում է, որ control-ները fail closed են։ Այն **չի ապացուցում**, որ իրական IAM, vault, approval service, object store, DR environment, model service, business provider կամ production deployment արդեն գոյություն ունի։ Այդ փաստերը պետք է մտնեն externally attested evidence-ով։ Միայն դրանից հետո graduation control-ը կարող է վերադարձնել `PRODUCTION_GRADUATED`։
