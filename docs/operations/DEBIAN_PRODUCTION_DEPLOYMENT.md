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

### Upgrade

Նույն sequence-ը կրկնել ավելի նոր merged `main` SHA-ի համար։ Release-երը immutable են, իսկ `/opt/bro/current` symlink-ը փոխվում է atomically։

### Rollback

Rollback-ը explicit operator action է․ ընտրվում է նախկին immutable release-ը, `/etc/bro/bro.release.env`-ում դրվում է դրա exact SHA-ն, atomically repoint է արվում `/opt/bro/current`, reinstall է արվում այդ release-ի unit-ը, հետո `systemctl daemon-reload` և restart։ Rollback-ից հետո host readback և acceptance checks-ը կրկին պարտադիր են․ նախկին acceptance-ը ավտոմատ չի փոխանցվում նոր runtime event-ին։
