# BRO Debian Production Deployment / BRO Debian Production Deployment

## English

This runbook deploys an exact current `main` revision of BRO to Debian 13 as a hardened long-lived systemd service. The repository remains the source of truth. The installer refuses a floating branch, dirty tracked working tree, or any revision that is not the current `origin/main`.

### Truth boundary

A healthy systemd service plus a fresh durable heartbeat proves **HOST_DEPLOYED** only. It does not manufacture external IAM/vault/approval, remote custody/DR, real provider acceptance, or `PRODUCTION_GRADUATED`. Those remain governed by `contracts/final_delivery.json`.

### Layout

- immutable releases: `/opt/bro/releases/<git-sha>`
- active symlink: `/opt/bro/current`
- durable runtime state: `/var/lib/bro/runtime.sqlite3`
- runtime lock: `/run/bro/primary.lock`
- operator config: `/etc/bro/bro.env`
- release identity config: `/etc/bro/bro.release.env`
- systemd unit: `/etc/systemd/system/bro.service`

### Deployment sequence

1. Fetch the repository and check out the exact current `origin/main` SHA.
2. Run `make check` locally on the server checkout.
3. Run `sudo bash scripts/install_debian_production.sh <exact-sha>`.
4. Verify `systemctl is-active bro.service`.
5. Read back the exact runtime revision with `sudo -u bro ... scripts/production_status.py` under the same environment files used by systemd.
6. Run the governed acceptance path (`scripts/run_production_intelligent_acceptance.py`, which requires `BRO_SOURCE_REVISION` and writes it into the record), then bind that evidence to the same exact SHA with `scripts/bind_production_acceptance.py` and read the ledger back with `--verify` before claiming `PRODUCTION_ACCEPTED`. See `docs/operations/PRODUCTION_ACCEPTANCE_BINDING.md`.
7. Satisfy the stronger external identity/vault/approval, remote custody and DR controls before any `PRODUCTION_GRADUATED` claim.

### Running BRO as the service identity

The model backend is the official Claude Code CLI, and the CLI keeps its authenticated
session under `HOME`. Changing user without changing `HOME` — which is what plain
`sudo -u bro` and `setpriv` both do — leaves the CLI looking in the invoking user's home,
where it finds nothing and reports `Not logged in` even though the service identity is
perfectly well authenticated.

Production does not rely on the ambient value: `BRO_MODEL_CLI_HOME=/var/lib/bro` in
`/etc/bro/bro.env` declares it, and the adapter forwards exactly that one variable to the
CLI. An operator invocation should set it too, so the CLI's own commands agree with what
BRO uses:

### Night School settings

| Setting | Production value | What it decides |
|---|---|---|
| `BRO_STUDY_ROOT` | `/var/lib/bro/knowledge` | the corpus STUDY reads; unset means BRO studies its own release, not the library |
| `BRO_STUDY_ITEM_BUDGET` | `30` | curriculum items one mission may study |
| `BRO_STUDY_DIMINISHING_AFTER` | `6` | consecutive barren sources that end a mission |
| `BRO_STUDY_ACQUISITION` | unset (off) | whether STUDY may reach the Internet at all; unset means it cannot |
| `BRO_SOURCE_POLICY` | release `contracts/source_policy.json` | the governed allowlist of host families and tiers |
| `BRO_STUDY_ACQUISITION_BUDGET` | `8` | pages one mission may acquire |

Both limits are at least one, and a malformed value falls back to the default instead of
removing the limit. The corpus is written only by `scripts/bro_acquire_knowledge.py`, run by
an operator — see [`KNOWLEDGE_ACQUISITION.md`](./KNOWLEDGE_ACQUISITION.md).

**Night School-ի կարգավորումները։** `BRO_STUDY_ROOT`-ը ցույց է տալիս corpus-ը (առանց դրա
BRO-ն կարդում է իր սեփական release-ը), `BRO_STUDY_ITEM_BUDGET=30`, `BRO_STUDY_DIMINISHING_AFTER=6`։
Երկու սահմանն էլ առնվազն մեկ են, ու սխալ արժեքը վերադառնում է լռելյայնին։ Corpus-ը գրում է
միայն օպերատորի կանչած `scripts/bro_acquire_knowledge.py`-ն։


```bash
sudo bash -c 'set -a; source /etc/bro/bro.env; source /etc/bro/bro.release.env; set +a
export HOME=/var/lib/bro
exec setpriv --reuid=bro --regid=bro --clear-groups \
  python3 /opt/bro/current/scripts/bro_interact.py "your request"'
```

To check the session itself, as that identity and nothing else:

```bash
sudo -u bro -H /var/lib/bro/.local/bin/claude auth status
```

One-time authentication for the service identity, if it has none. It is the operator's
step, and no credential is ever pasted anywhere:

```bash
sudo -u bro -H /var/lib/bro/.local/bin/claude auth login --claudeai
```

The CLI's state under `/var/lib/bro/.claude` should be `0700 bro:bro` and its install
under `/var/lib/bro/.local` `0750 bro:bro`. The installer creates them with the umask it
inherits, which can leave them group-writable; where a human account shares the `bro`
group that is service state a person can edit, so tighten them after installing.

When session lookup fails, BRO reports the effective `HOME` it used and whether a readable
state directory was visible there. That is what separates "this identity needs the official
login" from "this process inherited the wrong HOME".

### Upgrade

Repeat the same sequence for a newer merged `main` SHA. Releases are immutable and the `/opt/bro/current` symlink is switched atomically.

### Rollback

Rollback is an explicit operator action: select a previously deployed immutable release, update `/etc/bro/bro.release.env` to that exact SHA, atomically repoint `/opt/bro/current`, reinstall that release's unit, run `systemctl daemon-reload`, and restart. A rollback must be followed by the same host readback and acceptance checks; a previously accepted release is not automatically accepted in the new runtime event.

---

## Հայերեն

Այս runbook-ը BRO-ի current `main`-ի **ճշգրիտ commit SHA**-ն տեղադրում է Debian 13-ի վրա՝ որպես hardened long-lived systemd service։ Repository-ն մնում է source-of-truth։ Installer-ը մերժում է floating branch, dirty tracked working tree կամ այն revision-ը, որը տվյալ պահին current `origin/main`-ը չէ։

### Truth boundary

Healthy systemd service-ը և durable state-ից fresh heartbeat-ը ապացուցում են միայն **HOST_DEPLOYED** վիճակը։ Դրանք ինքնուրույն չեն ստեղծում external IAM/vault/approval, remote custody/DR, real provider acceptance կամ `PRODUCTION_GRADUATED` փաստ։ Դրանք շարունակում են կառավարվել `contracts/final_delivery.json`-ով։

### Տեղաբաշխում

- immutable release-եր՝ `/opt/bro/releases/<git-sha>`
- active symlink՝ `/opt/bro/current`
- durable runtime state՝ `/var/lib/bro/runtime.sqlite3`
- runtime lock՝ `/run/bro/primary.lock`
- operator config՝ `/etc/bro/bro.env`
- release identity config՝ `/etc/bro/bro.release.env`
- systemd unit՝ `/etc/systemd/system/bro.service`

### Deployment sequence

1. Fetch անել repository-ն և checkout անել current `origin/main`-ի exact SHA-ն։
2. Server checkout-ի վրա աշխատացնել `make check`։
3. Աշխատացնել `sudo bash scripts/install_debian_production.sh <exact-sha>`։
4. Ստուգել `systemctl is-active bro.service`։
5. systemd-ի նույն environment file-երով durable runtime-ից read back անել exact source revision-ը `scripts/production_status.py`-ով։
6. Աշխատացնել governed acceptance ուղին (`scripts/run_production_intelligent_acceptance.py`, որը պահանջում է `BRO_SOURCE_REVISION` և գրում է այն record-ի մեջ), հետո `scripts/bind_production_acceptance.py`-ով կապել evidence-ը նույն exact SHA-ին և `--verify`-ով ledger-ը կարդալ հետ՝ մինչև `PRODUCTION_ACCEPTED` հայտարարելը։ Տես `docs/operations/PRODUCTION_ACCEPTANCE_BINDING.md`։
7. `PRODUCTION_GRADUATED` հայտարարելուց առաջ բավարարել ավելի ուժեղ external identity/vault/approval, remote custody և DR control-ները։

### BRO-ի գործարկումը service-ի ինքնությամբ

Model backend-ը պաշտոնական Claude Code CLI-ն է, ու CLI-ն իր աութենտիֆիկացված սեսիան
պահում է `HOME`-ի տակ։ Օգտատերը փոխելը առանց `HOME`-ը փոխելու — ինչը անում են և՛ պարզ
`sudo -u bro`-ն, և՛ `setpriv`-ը — CLI-ին թողնում է կանչողի home-ում փնտրելիս, որտեղ ոչինչ
չկա, ու այն գրում է `Not logged in`, թեև service-ի ինքնությունը լիովին աութենտիֆիկացված է։

Production-ը միջավայրի պատահական արժեքին չի ապավինում․ `/etc/bro/bro.env`-ում
`BRO_MODEL_CLI_HOME=/var/lib/bro`-ն այն հայտարարում է, ու adapter-ը CLI-ին փոխանցում է
հենց այդ մեկ փոփոխականը։ Operator-ի կանչում նույնպես դրիր՝

```bash
sudo bash -c 'set -a; source /etc/bro/bro.env; source /etc/bro/bro.release.env; set +a
export HOME=/var/lib/bro
exec setpriv --reuid=bro --regid=bro --clear-groups \
  python3 /opt/bro/current/scripts/bro_interact.py "քո հարցումը"'
```

Սեսիան ստուգելու համար՝ `sudo -u bro -H /var/lib/bro/.local/bin/claude auth status`։
Մեկանգամյա մուտքը՝ `sudo -u bro -H /var/lib/bro/.local/bin/claude auth login --claudeai`,
ու դա operator-ի քայլն է. ոչ մի credential ոչ մի տեղ չի փակցվում։

`/var/lib/bro/.claude`-ը պիտի լինի `0700 bro:bro`, `/var/lib/bro/.local`-ը՝ `0750 bro:bro`։
Installer-ը դրանք ստեղծում է ժառանգած umask-ով ու կարող է թողնել group-writable։

Երբ սեսիան չի գտնվում, BRO-ն հայտնում է գործող `HOME`-ը ու արդյոք այնտեղ տեսանելի էր
կարդացվող state directory — հենց դա է տարբերում «պետք է պաշտոնական login» դեպքը «process-ը
սխալ HOME է ժառանգել» դեպքից։

### Upgrade

Նույն sequence-ը կրկնել ավելի նոր merged `main` SHA-ի համար։ Release-երը immutable են, իսկ `/opt/bro/current` symlink-ը փոխվում է atomically։

### Rollback

Rollback-ը explicit operator action է․ ընտրվում է նախկին immutable release-ը, `/etc/bro/bro.release.env`-ում դրվում է դրա exact SHA-ն, atomically repoint է արվում `/opt/bro/current`, reinstall է արվում այդ release-ի unit-ը, հետո `systemctl daemon-reload` և restart։ Rollback-ից հետո host readback և acceptance checks-ը կրկին պարտադիր են․ նախկին acceptance-ը ավտոմատ չի փոխանցվում նոր runtime event-ին։
