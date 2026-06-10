# Discovery & Coverage Report

A standalone companion to the **Discovery & Coverage** app that works against
both Dynatrace SaaS and Dynatrace Managed. It calls the Dynatrace Environment
API, joins discovered virtual machines against OneAgent-monitored hosts, and
renders an HTML dashboard plus a Markdown summary showing coverage gaps and a
recommended action for each VM.

One script ([`dnc.py`](dnc.py)) covers multiple virtualization platforms, each
selected with `--platform`:

| Platform | `--platform` | Required extension |
|---|---|---|
| VMware vSphere | `vmware` | VMware (remote monitoring) |
| OpenShift Virtualization | `openshift` | OpenShift Virtualization |
| Microsoft Hyper-V | `hyperv` | Hyper-V |
| Nutanix AHV | `nutanix` | Nutanix |

See [SOLUTION_DESIGN.md](SOLUTION_DESIGN.md) for how it works and why.

## Install

No dependencies — Python 3.9+ standard library only. Nothing to `pip install`.

Requirements:

- The relevant **vendor extension installed** for your platform (it builds the
  VM topology entities the script reads).
- A Dynatrace **API Access token** with scope `entities.read`.

## Usage

```bash
# SaaS
export DT_BASE_URL="https://ENVIRONMENT-ID.live.dynatrace.com"
# Managed
export DT_BASE_URL="https://your-domain/e/ENVIRONMENT-ID"

export DT_API_TOKEN="dt0c01.XXXX..."

python3 dnc.py --platform vmware
python3 dnc.py --platform vmware nutanix
```

Outputs `discovery_coverage.html` (self-contained dashboard) and
`discovery_coverage.md` (wiki/ticket-friendly summary) into `reports/` by
default. Schedule it (cron) to keep a living report.

### Offline demo (no tenant needed)

```bash
python3 dnc.py --platform vmware --mock
python3 dnc.py --platform vmware nutanix --mock
```

Sample output from `--mock` is pre-generated in [examples/reports/](examples/reports/) so you can preview the HTML dashboard and Markdown summary without a tenant.

### Options

| Flag | Default | Description |
|---|---|---|
| `--platform` | _required_ | One or more of: `vmware` `openshift` `hyperv` `nutanix` — space-separate for multiple |
| `--out-dir` | `reports/` | Directory for the report files |
| `--powered-on-only` | off | Restrict to powered-on VMs (default includes powered-off) |
| `--show-unmatched-hosts` | off | List the full table of monitored hosts that didn't match a VM (count is always shown) |
| `--max-vm-rows N` | `500` | Max VM rows in the detail table; `0` = unlimited. A truncation notice is shown when the limit is hit |
| `--summary-only` | off | Output a grouped-counts-only report (no VM detail) |
| `--list-entity-types` | — | List all entity types in the tenant and exit — `--platform` not required |
| `--insecure` | off | Skip TLS verification (self-signed certs) |
| `--mock` | off | Use bundled sample data (no tenant) |

```bash
# Find the VM entity type your tenant exposes:
python3 dnc.py --platform hyperv --list-entity-types
```
