# Solution Design — Discovery & Coverage

## The problem

Dynatrace SaaS ships a **Discovery & Coverage** app that shows which virtual
machines exist versus which are actually monitored by OneAgent, and recommends
an action for each gap. That app is an AppEngine application built on
Grail/DQL. It cannot be run as a standalone tool.

What *can* be reproduced is its **outcome**: a report that compares what exists
against what is monitored, flags the gaps, and prescribes a recommended action.
The script reads the same two facts from the Environment API and renders the
view itself. That is what [`dnc.py`](dnc.py) does — it only calls the
Dynatrace Environment API; it never talks to the hypervisor or scrapes anything
itself. It works against both Dynatrace SaaS and Dynatrace Managed.

## Approach

One script, many platforms. The core model is simply:

```
DISCOVERED VMs  −  MONITORED hosts  =  COVERAGE GAP
```

Everything platform-specific (the VM entity type, property names, column
labels, power-state rule, join strategy) lives in a small `Platform`
descriptor. The API client, the join/analysis, and the renderers are shared, so
a fix or a new rule lands once for every platform.

## Foundation: the vendor extension

The approach assumes the relevant Dynatrace **extension is already installed**
for your platform. The extension discovers the VMs and represents each as a
first-class **topology entity** — that is the "discovered" population the report
measures coverage against. The script reads those entities; it does no
discovery of its own.

| Platform | Extension | VM entity type |
|---|---|---|
| VMware vSphere | VMware (remote monitoring) — agentless, ActiveGate → vCenter | `vmware:virtualmachine` |
| OpenShift Virtualization | OpenShift Virtualization — Operator scrapes KubeVirt metrics | auto-detected |
| Microsoft Hyper-V | Hyper-V | `hyperv:virtual_machine` |
| Nutanix AHV | Nutanix | `nutanix:vm` |

> The Hyper-V and Nutanix per-VM property mappings in `dnc.py` are best-effort
> defaults; confirm them against your tenant with `--list-entity-types` and
> adjust the platform descriptor if needed.

## How it works

The report is built from two Environment-API reads, then a join.

1. **Discovery — what VMs exist.** Query the extension's VM topology entities
   (`type("<vm-entity-type>")`). Each entity is one discovered VM; identity and
   placement come from its `displayName` and properties. Powered-off VMs are
   recognized from the platform's power/phase signal so they aren't counted as
   coverage gaps.

2. **Coverage — what is monitored.** Query `type(HOST)`. A VM with OneAgent in
   its guest OS appears as a HOST entity with `monitoringMode` of `FULL_STACK`
   or `CLOUD_INFRASTRUCTURE`. A matched host with no monitoring mode is a
   *monitoring candidate* (known to Dynatrace but no OneAgent) and is treated as
   unmonitored.

**The join.** Monitored hosts are indexed by display name and
`oneAgentCustomHostName`; each VM is matched either by a direct
entity relationship (VMware) or by name. The outcome per VM:

- **No matching host** → coverage gap → *Install OneAgent*.
- **Matched, `CLOUD_INFRASTRUCTURE`** → *Consider Full-Stack*.
- **Matched, `FULL_STACK`** → *No action*.

> **Join-key caveat.** Name matching assumes the guest hostname equals the VM's
> inventory name, which is common but not guaranteed (most often a mismatch on
> VMware). A more robust key is the guest IP matched against the host's
> `ipAddress`, or a direct VM↔HOST relationship where the extension publishes
> one. Adjust `build_host_index()` if your naming is inconsistent.

## Scope and limitations

The report is **read-only and advisory**. It reproduces the coverage model,
coverage percentage and gap count, per-VM recommended actions, and the database
and service depth signals. It does **not** automate remediation.

## Extending it

- **More depth rules:** add technology types to `DATABASE_TECHS` /
  `SERVICE_TECHS`, or add rule blocks in `analyze()`.
- **A new platform:** add a `Platform(...)` entry to the `PLATFORMS` registry.
- **IP-based join:** key `build_host_index()` on `properties.ipAddress`.
- **Trend over time:** persist each run's summary and chart coverage across runs.
