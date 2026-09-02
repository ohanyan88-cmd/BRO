# First usable BRO interaction surface / BRO-ի առաջին իրական օգտագործելի interaction surface-ը

## English

BRO now has a small human-facing CLI that uses the existing FINAL-1 production intelligent execution path rather than introducing a parallel demo path.

Run `python3 scripts/bro_interact.py "<natural-language request>"` inside the production checkout. The command uses the same production model boundary, specialist selection, governed GitHub provider effect, explicit material-scope confirmation, and independent external readback used by FINAL-1.

Required environment variables are `BRO_MODEL_PROVIDER` (`claude-code-cli`), `BRO_MODEL_NAME`, optionally `BRO_MODEL_CLI_PATH`, `BRO_MODEL_CLI_WORKDIR` and `BRO_MODEL_TIMEOUT_SECONDS`, plus `BRO_GITHUB_TOKEN`, `BRO_GITHUB_OWNER`, `BRO_GITHUB_REPOSITORY`, `BRO_GITHUB_ISSUE`, `BRO_INTELLIGENT_IDEMPOTENCY_KEY`, `BRO_INTELLIGENT_COMMENT_BODY`, and `BRO_INTELLIGENT_CONFIRMED_BY`.

The interaction is intentionally two-stage for material requests: BRO first shows the interpreted scope, constraints, success conditions, and scope digest. No external effect is attempted until the exact digest is confirmed. After execution, the CLI prints the external effect and independent readback/evidence receipt.

This surface is intentionally narrow: its first real action is the already accepted governed GitHub issue-comment capability. It is a usable product surface over production truth, not a claim that arbitrary tools or channels are already wired.

## Հայերեն

BRO-ն հիմա ունի փոքր human-facing CLI, որը աշխատում է արդեն գոյություն ունեցող FINAL-1 production intelligent execution path-ի վրայով և չի ստեղծում առանձին demo execution path։

Production checkout-ի ներսում գործարկվում է `python3 scripts/bro_interact.py "<բնական լեզվով հարցում>"` հրամանով։ Այն օգտագործում է նույն production model boundary-ն, specialist selection-ը, governed GitHub provider effect-ը, material scope-ի explicit confirmation-ը և independent external readback-ը, որոնք օգտագործվում են FINAL-1-ում։

Պահանջվող environment variable-ներն են՝ `BRO_MODEL_PROVIDER` (`claude-code-cli`), `BRO_MODEL_NAME`, ըստ անհրաժեշտության `BRO_MODEL_CLI_PATH`, `BRO_MODEL_CLI_WORKDIR`, `BRO_MODEL_TIMEOUT_SECONDS`, ինչպես նաև `BRO_GITHUB_TOKEN`, `BRO_GITHUB_OWNER`, `BRO_GITHUB_REPOSITORY`, `BRO_GITHUB_ISSUE`, `BRO_INTELLIGENT_IDEMPOTENCY_KEY`, `BRO_INTELLIGENT_COMMENT_BODY`, `BRO_INTELLIGENT_CONFIRMED_BY`։

Material request-ի interaction-ը դիտավորյալ երկփուլ է։ Սկզբում BRO-ն ցույց է տալիս interpreted scope-ը, constraints-ը, success conditions-ը և scope digest-ը։ Մինչև exact digest-ի հաստատումը ոչ մի external effect չի փորձարկվում։ Execution-ից հետո CLI-ն ցույց է տալիս external effect-ի և independent readback/evidence-ի receipt-ը։

Այս surface-ը դիտավորյալ նեղ է․ առաջին իրական action-ը արդեն ընդունված governed GitHub issue-comment capability-ն է։ Սա production truth-ի վրա կառուցված usable product surface է, ոչ թե հայտարարություն, թե arbitrary tools/channels արդեն միացված են։
