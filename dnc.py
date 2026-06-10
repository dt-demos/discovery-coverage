#!/usr/bin/env python3
"""
Discovery & Coverage for virtualized platforms on Dynatrace
===========================================================

A standalone companion to the SaaS "Discovery & Coverage" app that works
against both Dynatrace SaaS and Dynatrace Managed. It calls the Dynatrace
Environment API, joins discovered virtual machines against OneAgent-monitored
hosts, and renders an HTML dashboard + a Markdown summary.

This is the UNIFIED engine: one script, many platforms. The per-platform
specifics (VM entity type, property names, column labels, power-state rules,
join strategy) live in a small `Platform` descriptor in the PLATFORMS registry
below. Everything else -- the API client, the join/analysis, the renderers --
is shared, so a fix or feature lands once for every platform.

It replicates the Host / VM coverage feature of the Discovery & Coverage app:
  discovered VMs vs. OneAgent-monitored hosts.

The script reconstructs the app's inputs from the Environment API and joins
them itself. Each platform assumes its vendor extension is installed, which
builds the VM topology entities we read:
      vmware     -> VMware (remote monitoring) extension  (vmware:virtualmachine)
      openshift  -> OpenShift Virtualization extension     (autodetected)
      hyperv     -> Hyper-V extension                      (hyperv:virtual_machine)
      nutanix    -> Nutanix extension                      (nutanix:vm)

  DISCOVERY (what VMs EXIST): the extension's VM topology entities.
  COVERAGE  (what is MONITORED): HOST entities with OneAgent
            (monitoringMode FULL_STACK or CLOUD_INFRASTRUCTURE).
  Joining the two yields the coverage gap and a recommended action per VM.

Usage:
  # SaaS
  export DT_BASE_URL="https://ENVIRONMENT-ID.live.dynatrace.com"
  # Managed
  export DT_BASE_URL="https://your-domain/e/ENVIRONMENT-ID"
  export DT_API_TOKEN="dt0c01.XXXX..."        # scope: entities.read
  python3 dnc.py --platform vmware
  python3 dnc.py --platform openshift
  python3 dnc.py --platform vmware openshift

  # Inspect the entity types your tenant exposes (helps find the VM type):
  python3 dnc.py --platform hyperv --list-entity-types

  # Powered-on VMs only (default includes powered-off too):
  python3 dnc.py --platform vmware --powered-on-only

  # Offline demo with bundled sample data (no tenant required):
  python3 dnc.py --platform vmware --mock
  python3 dnc.py --platform vmware openshift --mock

Required Environment API token scope (Settings > Access tokens):
  - entities.read   (Read entities)   -> Monitored entities API + entity types

Author: reference implementation. Tune each platform's entity type, property
keys, join key, and rule set to match your environment (see PLATFORMS below).
"""

import argparse
import html
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

HTTP_TIMEOUT = 30

# Output file stem (platform is shown in the report title/content, not the name).
OUT_BASENAME = "discovery_coverage"


def _norm(s):
    return (s or "").strip().lower()


def _e(s):
    return html.escape(str(s if s is not None else ""))


def _first(props, keys, default=""):
    """Return the first non-empty value among `keys` in `props`."""
    for k in keys:
        v = props.get(k)
        if v not in (None, ""):
            return v
    return default


# --------------------------------------------------------------------------- #
# Platform descriptors (the only per-platform surface)                        #
# --------------------------------------------------------------------------- #

@dataclass
class Platform:
    key: str                              # CLI value, e.g. "vmware"
    label: str                            # human label -> titles, e.g. "VMware vSphere"
    group_label: str                      # "group" column header, e.g. "Cluster" / "Namespace"
    node_label: str                       # "node" column header, e.g. "ESXi host" / "Node"
    extract_vm: Callable[[dict], dict]    # entity -> normalized VM row
    # entity_type is used verbatim if set; otherwise auto-detected via type_hints.
    vm_entity_type: Optional[str] = None
    type_hints: tuple = ()
    type_exclude: tuple = ("disk", "file", "network", "cluster", "datastore", "nic", "volume")
    # extra Environment-API entity fields needed by extract_vm:
    entity_fields: str = "+properties"
    # server-side selector that restricts to powered-on VMs (or None):
    powered_on_selector: Optional[str] = None


# -- VMware: rich extraction (direct isSameAs->HOST join + runsOn ESXi host) - #
def _extract_vmware(e):
    props = e.get("properties", {}) or {}
    from_rels = e.get("fromRelationships", {}) or {}
    host_id_direct = None
    for rel in from_rels.get("isSameAs", []) or []:
        if rel.get("type") == "HOST":
            host_id_direct = rel.get("id")
            break
    node = ""
    for rel in from_rels.get("runsOn", []) or []:
        if rel.get("type") == "vmware:host":
            node = rel.get("id", "")
            break
    power = props.get("vm_power_state", "")
    return {
        "name": props.get("vm_name") or e.get("displayName", ""),
        "group": props.get("vcenter", ""),
        "node": node,
        "guest_os": props.get("vm_guest_os", ""),
        "phase": "Running" if power == "poweredOn" else (power or "Running"),
        "host_id_direct": host_id_direct,
    }


def make_extractor(group_keys, node_keys, guest_keys=(), phase_keys=(),
                   powered_on_tokens=None):
    """Property-key extractor for platforms that join by name (no direct HOST rel).

    `powered_on_tokens` is a set of lowercased phase/power values that mean
    "running"; matching values are normalized to "Running" so analyze() treats
    them as candidates. If a platform exposes no phase property, rows default to
    "Running" (mere existence == discovered).
    """
    def extract(e):
        props = e.get("properties", {}) or {}
        raw = _first(props, phase_keys, "Running")
        if powered_on_tokens is not None and _norm(raw) in powered_on_tokens:
            phase = "Running"
        else:
            phase = raw or "Running"
        return {
            "name": e.get("displayName", ""),
            "group": _first(props, group_keys),
            "node": _first(props, node_keys),
            "guest_os": _first(props, guest_keys),
            "phase": phase,
            "host_id_direct": None,
        }
    return extract


PLATFORMS = {
    "vmware": Platform(
        key="vmware", label="VMware vSphere",
        group_label="Cluster", node_label="ESXi host",
        vm_entity_type="vmware:virtualmachine",
        type_hints=("vmware:vm", "vmware_vm", "vsphere vm", "virtual machine", "vmware vm"),
        type_exclude=("host", "esxi", "cluster", "datastore", "disk", "datacenter",
                      "volume", "nic", "network"),
        entity_fields="+properties,+fromRelationships.isSameAs,+fromRelationships.runsOn",
        powered_on_selector='properties.vm_power_state("poweredOn")',
        extract_vm=_extract_vmware,
    ),
    "openshift": Platform(
        key="openshift", label="OpenShift Virtualization",
        group_label="Namespace", node_label="Node",
        vm_entity_type=None,  # auto-detect
        type_hints=("openshift_vm", "openshift virtualization", "ocp_vm",
                    "ocp virtualization vm", "vmi"),
        extract_vm=make_extractor(
            group_keys=("namespace",), node_keys=("node",),
            guest_keys=("guestOS", "guest_os"),
            phase_keys=("phase",), powered_on_tokens={"running"}),
    ),
    "hyperv": Platform(
        key="hyperv", label="Microsoft Hyper-V",
        group_label="Cluster", node_label="Hyper-V host",
        vm_entity_type="hyperv:virtual_machine",
        type_hints=("hyperv:virtual_machine", "hyper-v virtual machine",
                    "hyperv vm", "hyper-v vm"),
        # Property keys are best-effort; tune to your extension via --list-entity-types.
        extract_vm=make_extractor(
            group_keys=("cluster", "failover_cluster"),
            node_keys=("host", "hyperv_host", "hypervisor"),
            guest_keys=("guestOS", "guest_os", "os"),
            phase_keys=("state", "power_state", "vm_state"),
            powered_on_tokens={"running", "on", "poweredon", "2"}),
    ),
    "nutanix": Platform(
        key="nutanix", label="Nutanix AHV",
        group_label="Cluster", node_label="AHV host",
        vm_entity_type="nutanix:vm",
        type_hints=("nutanix:vm", "nutanix virtual machine", "nutanix vm", "ahv vm"),
        # Property keys are best-effort; tune to your extension via --list-entity-types.
        extract_vm=make_extractor(
            group_keys=("ClusterUuid", "cluster", "nutanix_cluster"),
            node_keys=("HostUuid", "host", "ahv_host", "hypervisor"),
            guest_keys=("guestOS", "guest_os", "os"),
            phase_keys=("power_state", "state", "vm_state"),
            powered_on_tokens={"on", "poweredon", "running"}),
    ),
}


# --------------------------------------------------------------------------- #
# Thin Environment API client (stdlib only, with nextPageKey pagination)      #
# --------------------------------------------------------------------------- #

class DynatraceClient:
    def __init__(self, base_url, token, verify_tls=True):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._ctx = ssl.create_default_context()
        if not verify_tls:
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE

    def _get(self, path, params=None):
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Api-Token {self.token}")
        req.add_header("Accept", "application/json")
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=self._ctx) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:  # throttled
                    time.sleep(2 ** attempt)
                    continue
                body = e.read().decode("utf-8", "replace")
                raise RuntimeError(f"HTTP {e.code} for {url}\n{body}") from None
            except urllib.error.URLError as e:
                raise RuntimeError(f"Connection error for {url}: {e}") from None
        raise RuntimeError(f"Giving up after retries: {url}")

    def get_paged(self, path, params, items_key):
        """GET with Dynatrace nextPageKey pagination. Returns a flat list."""
        params = dict(params or {})
        out = []
        while True:
            data = self._get(path, params)
            out.extend(data.get(items_key, []))
            npk = data.get("nextPageKey")
            if not npk:
                break
            params = {"nextPageKey": npk}  # all other params must be dropped
        return out

    # -- Entity-type discovery (find the extension's VM type) ----------------
    def fetch_entity_types(self):
        return self.get_paged("/api/v2/entityTypes", {"pageSize": 500}, "types")

    def detect_vm_entity_type(self, platform):
        """Auto-detect the platform's VM entity type via its hints/excludes."""
        for t in self.fetch_entity_types():
            blob = _norm(t.get("type")) + " " + _norm(t.get("displayName"))
            if any(x in blob for x in platform.type_exclude):
                continue
            if any(hint in blob for hint in platform.type_hints):
                return t.get("type")
        return None

    # -- Discovery: VM inventory via the extension's topology entities -------
    def fetch_discovered_vms(self, platform, vm_entity_type, all_vms=True):
        selector = f'type("{vm_entity_type}")'
        if not all_vms and platform.powered_on_selector:
            selector += "," + platform.powered_on_selector
        params = {
            "entitySelector": selector,
            "fields": platform.entity_fields,
            "pageSize": 500,
            "from": "now-3d",
        }
        entities = self.get_paged("/api/v2/entities", params, "entities")
        vms = []
        for e in entities:
            row = platform.extract_vm(e)
            row["entity_id"] = e.get("entityId", "")
            row["_raw"] = e
            vms.append(row)
        return vms

    # -- Coverage: monitored HOST entities -----------------------------------
    def fetch_hosts(self):
        params = {
            "entitySelector": "type(HOST)",
            "fields": "+properties.monitoringMode,+properties.oneAgentCustomHostName,"
                      "+properties.ipAddress,+properties.state",
            "pageSize": 500,
            "from": "now-3d",
        }
        return self.get_paged("/api/v2/entities", params, "entities")


# --------------------------------------------------------------------------- #
# Join + analysis (platform-agnostic)                                         #
# --------------------------------------------------------------------------- #

def build_host_index(hosts):
    """Index monitored hosts by candidate join keys (custom name, display name)."""
    by_name = {}
    for h in hosts:
        props = h.get("properties", {})
        keys = set()
        if h.get("displayName"):
            keys.add(_norm(h["displayName"]))
        if props.get("oneAgentCustomHostName"):
            keys.add(_norm(props["oneAgentCustomHostName"]))
        for k in keys:
            by_name.setdefault(k, h)
    return by_name


def analyze(vms, hosts, include_powered_off=True):
    host_index = build_host_index(hosts)
    host_by_id = {h["entityId"]: h for h in hosts}

    matched_host_ids = set()
    vm_rows = []
    for vm in vms:
        powered_off = vm.get("phase") and _norm(vm["phase"]) != "running"
        if powered_off:
            if not include_powered_off:
                continue
            vm_rows.append({
                **vm, "monitored": False, "monitoring_mode": "POWERED_OFF",
                "host_id": None, "host_state": "",
                "recommended": "Powered off — no action needed",
            })
            continue
        host_id_direct = vm.get("host_id_direct")
        host = (host_by_id.get(host_id_direct) if host_id_direct
                else host_index.get(_norm(vm["name"])))
        if host:
            matched_host_ids.add(host["entityId"])
            props = host.get("properties", {})
            mode = props.get("monitoringMode")
            state = props.get("state", "")
            if not mode:
                # Matched a HOST entity, but it has no monitoringMode -> this is a
                # monitoring *candidate* (known to Dynatrace, often via the vendor
                # extension, but OneAgent isn't installed/reporting). Treat it as
                # unmonitored rather than the ambiguous "UNKNOWN".
                vm_rows.append({
                    **vm, "monitored": False, "monitoring_mode": "NONE",
                    "host_id": None, "host_state": state,
                    "recommended": "Install OneAgent",
                })
                continue
            recommended = "No action" if mode == "FULL_STACK" else \
                "Consider Full-Stack" if mode == "CLOUD_INFRASTRUCTURE" else "Review host"
            vm_rows.append({
                **vm, "monitored": True, "monitoring_mode": mode,
                "host_id": host["entityId"], "host_state": state,
                "recommended": recommended,
            })
        else:
            vm_rows.append({
                **vm, "monitored": False, "monitoring_mode": "NONE",
                "host_id": None, "host_state": "",
                "recommended": "Install OneAgent",
            })

    powered_off = sum(1 for v in vm_rows if v["monitoring_mode"] == "POWERED_OFF")
    candidates = len(vm_rows) - powered_off  # powered-on VMs only
    monitored = sum(1 for v in vm_rows if v["monitored"])
    full_stack = sum(1 for v in vm_rows if v["monitoring_mode"] == "FULL_STACK")
    summary = {
        "total_vms": len(vm_rows),
        "powered_off_vms": powered_off,
        "candidate_vms": candidates,
        "monitored_vms": monitored,
        "unmonitored_vms": candidates - monitored,
        "full_stack_vms": full_stack,
        "coverage_pct": round(100 * monitored / candidates, 1) if candidates else 0.0,
        "full_stack_pct": round(100 * full_stack / candidates, 1) if candidates else 0.0,
        "orphan_hosts": [h for hid, h in host_by_id.items() if hid not in matched_host_ids],
    }
    return summary, vm_rows


def _combine_summaries(results):
    """Aggregate per-platform summaries into a single combined summary."""
    total = powered_off = candidates = monitored = full_stack = 0
    for _, s, *_ in results:
        total += s["total_vms"]
        powered_off += s["powered_off_vms"]
        candidates += s["candidate_vms"]
        monitored += s["monitored_vms"]
        full_stack += s["full_stack_vms"]
    return {
        "total_vms": total,
        "powered_off_vms": powered_off,
        "candidate_vms": candidates,
        "monitored_vms": monitored,
        "unmonitored_vms": candidates - monitored,
        "full_stack_vms": full_stack,
        "coverage_pct": round(100 * monitored / candidates, 1) if candidates else 0.0,
        "full_stack_pct": round(100 * full_stack / candidates, 1) if candidates else 0.0,
    }


# --------------------------------------------------------------------------- #
# Group-stats helpers (used by both full and summary-only renderers)          #
# --------------------------------------------------------------------------- #

def _group_stats(vm_rows):
    """Return sorted list of (platform_label, group, total_vms, monitored, full_stack, powered_off).

    total_vms includes powered-off VMs; powered_on = total_vms - powered_off.
    """
    from collections import defaultdict
    buckets = defaultdict(lambda: [0, 0, 0, 0])  # [powered_on, monitored, full_stack, powered_off]
    for v in vm_rows:
        key = (v.get("platform_label", ""), v["group"])
        if v["monitoring_mode"] == "POWERED_OFF":
            buckets[key][3] += 1
            continue
        buckets[key][0] += 1
        if v["monitored"]:
            buckets[key][1] += 1
        if v["monitoring_mode"] == "FULL_STACK":
            buckets[key][2] += 1
    result = []
    for (pl, grp), (powered_on, monitored, full_stack, powered_off) in buckets.items():
        result.append((pl, grp, powered_on + powered_off, monitored, full_stack, powered_off))
    return sorted(result)


def _group_table_html(vm_rows, combined_summary):
    rows = []
    for pl, grp, total, monitored, full_stack, powered_off in _group_stats(vm_rows):
        powered_on = total - powered_off
        pct = round(100 * monitored / powered_on, 1) if powered_on else 0.0
        rows.append(
            f"<tr><td>{_e(pl)}</td><td>{_e(grp)}</td><td>{total}</td><td>{powered_off}</td><td>{monitored}</td>"
            f"<td>{full_stack}</td><td>{powered_on - monitored}</td><td>{pct}%</td></tr>"
        )
    t = combined_summary["total_vms"]
    rows.append(
        f"<tr style='font-weight:700;border-top:2px solid var(--line)'>"
        f"<td></td><td>Total</td><td>{t}</td><td>{combined_summary['powered_off_vms']}</td>"
        f"<td>{combined_summary['monitored_vms']}</td>"
        f"<td>{combined_summary['full_stack_vms']}</td><td>{combined_summary['unmonitored_vms']}</td>"
        f"<td>{combined_summary['coverage_pct']}%</td></tr>"
    )
    body = "\n".join(rows)
    return ('<h2>Coverage by Cluster</h2>\n'
            '<table><thead><tr><th>Platform</th><th>Cluster</th><th>Total VMs</th><th>Powered Off</th>'
            '<th>Monitored</th><th>Full-Stack</th><th>Gap</th><th>Coverage</th></tr></thead>'
            f'<tbody>\n{body}\n</tbody></table>')


def _group_table_md(vm_rows, combined_summary):
    lines = ["## Coverage by Cluster\n",
             "| Platform | Cluster | Total VMs | Powered Off | Monitored | Full-Stack | Gap | Coverage |",
             "|----------|---------|-----------|-------------|-----------|------------|-----|----------|"]
    for pl, grp, total, monitored, full_stack, powered_off in _group_stats(vm_rows):
        powered_on = total - powered_off
        pct = round(100 * monitored / powered_on, 1) if powered_on else 0.0
        lines.append(f"| {pl} | {grp} | {total} | {powered_off} | {monitored} | {full_stack} | {powered_on - monitored} | {pct}% |")
    t = combined_summary["total_vms"]
    lines.append(f"| | **Total** | **{t}** | **{combined_summary['powered_off_vms']}** | "
                 f"**{combined_summary['monitored_vms']}** | "
                 f"**{combined_summary['full_stack_vms']}** | **{combined_summary['unmonitored_vms']}** | "
                 f"**{combined_summary['coverage_pct']}%** |")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Rendering (platform labels come from the Platform descriptor)               #
# --------------------------------------------------------------------------- #

_HTML_STYLE = """
  :root { --bg:#0f1419; --card:#1b2733; --line:#2a3947; --txt:#e6edf3;
           --muted:#8b9aa8; --ok:#4caf78; --warn:#e0a93b; --crit:#e0533b; --accent:#4a9eff; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
          background:var(--bg); color:var(--txt); padding:32px; }
  h1 { font-size:22px; margin:0 0 4px; }
  h2 { font-size:18px; margin:40px 0 12px; border-bottom:2px solid var(--line); padding-bottom:6px; }
  h3 { font-size:13px; margin:24px 0 8px; border-bottom:1px solid var(--line); padding-bottom:4px;
       color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }
  .sub { color:var(--muted); margin:0 0 24px; }
  .cards { display:flex; gap:16px; flex-wrap:wrap; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px;
           padding:18px 22px; min-width:160px; }
  .card .n { font-size:30px; font-weight:700; }
  .card .l { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
  .bar { position:relative; background:#0a0e13; border:1px solid var(--line);
          border-radius:6px; height:26px; margin:6px 0 18px; overflow:hidden; }
  .bar .fill { height:100%; }
  .bar span { position:absolute; right:10px; top:3px; font-weight:600; }
  table { width:100%; border-collapse:collapse; background:var(--card);
           border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  th,td { text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); }
  th { background:#16212c; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  tr:last-child td { border-bottom:none; }
  .tag { padding:2px 8px; border-radius:20px; font-size:12px; font-weight:600; }
  .tag.ok { background:rgba(76,175,120,.18); color:var(--ok); }
  .tag.warn { background:rgba(224,169,59,.18); color:var(--warn); }
  .tag.crit { background:rgba(224,83,59,.18); color:var(--crit); }
  .muted { color:var(--muted); }"""


def render_html(results, combined_summary, generated, show_orphans=False, base_url="", cli_opts="", max_vm_rows=500):
    all_vm_rows = [row for _, _, rows in results for row in rows]

    def bar(pct, color):
        return (f'<div class="bar"><div class="fill" style="width:{pct}%;'
                f'background:{color}"></div><span>{pct}%</span></div>')

    def vm_table(vm_rows):
        sorted_rows = sorted(vm_rows, key=lambda x: (x["monitored"], x["group"], x["name"]))
        limit = max_vm_rows if max_vm_rows > 0 else len(sorted_rows)
        truncated = len(sorted_rows) - limit
        rows = []
        for v in sorted_rows[:limit]:
            badge = ("ok" if v["monitoring_mode"] == "FULL_STACK"
                     else "warn" if v["monitored"] else "crit")
            rows.append(
                f"<tr><td>{_e(v['group'])}</td><td>{_e(v['node'])}</td>"
                f"<td>{_e(v['name'])}</td><td>{_e(v['entity_id'])}</td>"
                f"<td><span class='tag {badge}'>{_e(v['monitoring_mode'])}</span></td>"
                f"<td>{_e(v['recommended'])}</td></tr>"
            )
        if truncated > 0:
            rows.append(
                f"<tr><td colspan='6' class='muted' style='text-align:center;font-style:italic'>"
                f"&#8230; {truncated} more VM(s) not shown &mdash; "
                f"use <code>--max-vm-rows 0</code> to display all, "
                f"or <code>--summary-only</code> for large environments.</td></tr>"
            )
        return "\n".join(rows)

    platform_sections = []
    for platform, summary, vm_rows in results:
        if not vm_rows:
            continue
        gl = _e(platform.group_label)
        orphan_count = len(summary["orphan_hosts"])
        if show_orphans:
            orphan_rows = "".join(
                f"<tr><td>{_e(h.get('displayName'))}</td><td>{_e(h.get('entityId'))}</td>"
                f"<td>{_e(h.get('properties', {}).get('monitoringMode'))}</td></tr>"
                for h in summary["orphan_hosts"]
            ) or "<tr><td colspan='3' class='muted'>None.</td></tr>"
            orphan_html = (
                f'<h3>Monitored hosts not matched to a VM ({orphan_count})</h3>\n'
                '<p class="sub">Hosts with OneAgent that did not join to a discovered VM '
                '(check the join key, or they are non-VM hosts).</p>\n'
                '<table><thead><tr><th>Host</th><th>Entity ID</th><th>Mode</th></tr></thead>'
                f'<tbody>\n{orphan_rows}\n</tbody></table>'
            )
        else:
            orphan_html = (
                f'<h3>Monitored hosts not matched to a VM ({orphan_count})</h3>\n'
                f'<p class="sub">{orphan_count} monitored host(s) did not join to a discovered '
                f'{_e(platform.label)} VM (likely hosts from other platforms). '
                'Re-run with --show-unmatched-hosts to list them.</p>'
            )

        platform_sections.append(f"""
<h2>Discovery &mdash; {_e(platform.label)}</h2>

<h3>VM / Host coverage</h3>
<table><thead><tr><th>{gl}</th><th>Cluster Node</th><th>VM Name</th><th>Entity ID</th>
<th>Mode</th><th>Recommended action</th></tr></thead><tbody>
{vm_table(vm_rows)}
</tbody></table>

{orphan_html}""")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Discovery &amp; Coverage</title>
<style>{_HTML_STYLE}
</style></head><body>
<h1>Discovery &amp; Coverage</h1>
<p class="sub">Generated {_e(generated)} &middot; {_e(cli_opts)}</p>

<div class="cards">
  <div class="card"><div class="n">{combined_summary['total_vms']}</div><div class="l">Total VMs</div></div>
  <div class="card"><div class="n">{combined_summary['powered_off_vms']}</div><div class="l">Powered off</div></div>
  <div class="card"><div class="n">{combined_summary['monitored_vms']}</div><div class="l">Monitored (powered on)</div></div>
  <div class="card"><div class="n">{combined_summary['unmonitored_vms']}</div><div class="l">Coverage gap</div></div>
  <div class="card"><div class="n">{combined_summary['full_stack_vms']}</div><div class="l">Full-Stack</div></div>
</div>
<p class="sub" style="margin-top:8px">Environment: {_e(base_url)}</p>

<h2>OneAgent coverage</h2>
{bar(combined_summary['coverage_pct'], 'var(--ok)')}
<h2>Full-Stack depth</h2>
{bar(combined_summary['full_stack_pct'], 'var(--accent)')}

{_group_table_html(all_vm_rows, combined_summary)}
{"".join(platform_sections)}
</body></html>"""


def render_markdown(results, combined_summary, generated, show_orphans=False, base_url="", cli_opts="", max_vm_rows=500):
    all_vm_rows = [row for _, _, rows in results for row in rows]
    lines = []
    lines.append("# Discovery & Coverage\n")
    lines.append(f"_Generated {generated} · {cli_opts}_\n")
    lines.append("## Summary\n")
    lines.append(f"- **Environment:** {base_url}")
    lines.append(f"- **Total VMs:** {combined_summary['total_vms']} "
                 f"({combined_summary['powered_off_vms']} powered off, "
                 f"{combined_summary['candidate_vms']} powered on)")
    lines.append(f"- **Monitored (powered on):** {combined_summary['monitored_vms']} "
                 f"({combined_summary['coverage_pct']}% coverage)")
    lines.append(f"- **Coverage gap (no OneAgent):** {combined_summary['unmonitored_vms']}")
    lines.append(f"- **Full-Stack:** {combined_summary['full_stack_vms']} "
                 f"({combined_summary['full_stack_pct']}%)\n")

    lines.append(_group_table_md(all_vm_rows, combined_summary))

    for platform, summary, vm_rows in results:
        if not vm_rows:
            continue
        gl = platform.group_label
        lines.append(f"## Discovery — {platform.label}\n")

        sorted_rows = sorted(vm_rows, key=lambda x: (x["monitored"], x["group"], x["name"]))
        limit = max_vm_rows if max_vm_rows > 0 else len(sorted_rows)
        truncated = len(sorted_rows) - limit

        lines.append(f"### VM / Host coverage\n")
        lines.append(f"| {gl} | Cluster Node | VM Name | Entity ID | Mode | Recommended action |")
        lines.append("|---------|--------------|---------|-----------|------|--------------------|")
        for v in sorted_rows[:limit]:
            lines.append(f"| {v['group']} | {v['node']} | {v['name']} | "
                         f"{v['entity_id']} | {v['monitoring_mode']} | {v['recommended']} |")
        if truncated > 0:
            lines.append(f"| | | _… {truncated} more VM(s) not shown_ | | | "
                         f"_Use `--max-vm-rows 0` or `--summary-only`_ |")
        lines.append("")

        orphan_count = len(summary["orphan_hosts"])
        lines.append(f"### Monitored hosts not matched to a VM ({orphan_count})\n")
        if show_orphans and orphan_count:
            lines.append("| Host | Entity ID | Mode |")
            lines.append("|------|-----------|------|")
            for h in summary["orphan_hosts"]:
                lines.append(f"| {h.get('displayName')} | {h.get('entityId')} | "
                             f"{h.get('properties', {}).get('monitoringMode')} |")
        else:
            lines.append(f"_{orphan_count} monitored host(s) did not join to a discovered "
                         f"{platform.label} VM (likely hosts from other platforms). Re-run with "
                         "`--show-unmatched-hosts` to list them._")
        lines.append("")

    return "\n".join(lines)


def render_html_summary_only(results, combined_summary, generated, base_url="", cli_opts=""):
    all_vm_rows = [row for _, _, rows in results for row in rows]
    platform_labels = _e(", ".join(plat.label for plat, *_ in results))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Discovery &amp; Coverage Summary</title>
<style>{_HTML_STYLE}
</style></head><body>
<h1>Discovery &amp; Coverage Summary &mdash; {platform_labels}</h1>
<p class="sub">Generated {_e(generated)} &middot; {_e(cli_opts)}</p>
<p class="sub">Environment: {_e(base_url)}</p>

{_group_table_html(all_vm_rows, combined_summary)}
</body></html>"""


def render_markdown_summary_only(results, combined_summary, generated, base_url="", cli_opts=""):
    all_vm_rows = [row for _, _, rows in results for row in rows]
    platform_labels = ", ".join(plat.label for plat, *_ in results)
    lines = []
    lines.append(f"# Discovery & Coverage Summary — {platform_labels}\n")
    lines.append(f"_Generated {generated} · {cli_opts}_\n")
    lines.append(f"- **Environment:** {base_url}")
    lines.append(f"- **Total VMs (powered on):** {combined_summary['candidate_vms']}  "
                 f"Monitored: {combined_summary['monitored_vms']} ({combined_summary['coverage_pct']}%)  "
                 f"Gap: {combined_summary['unmonitored_vms']}  "
                 f"Full-Stack: {combined_summary['full_stack_vms']} ({combined_summary['full_stack_pct']}%)\n")
    lines.append(_group_table_md(all_vm_rows, combined_summary))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Mock data (offline demo / self-test) -- already in normalized row form      #
# --------------------------------------------------------------------------- #

def mock_data():
    vms = [
        {"name": "web-vm-01", "group": "PROD-CL1", "node": "node-01", "guest_os": "RHEL 9", "phase": "Running", "host_id_direct": None, "entity_id": "VM-001"},
        {"name": "web-vm-02", "group": "PROD-CL1", "node": "node-02", "guest_os": "RHEL 9", "phase": "Running", "host_id_direct": None, "entity_id": "VM-002"},
        {"name": "db-vm-01", "group": "PROD-CL1", "node": "node-02", "guest_os": "RHEL 8", "phase": "Running", "host_id_direct": None, "entity_id": "VM-003"},
        {"name": "db-vm-02", "group": "PROD-CL2", "node": "node-03", "guest_os": "RHEL 8", "phase": "Running", "host_id_direct": None, "entity_id": "VM-004"},
        {"name": "batch-vm-01", "group": "PROD-CL2", "node": "node-01", "guest_os": "Ubuntu 22.04", "phase": "Running", "host_id_direct": None, "entity_id": "VM-005"},
        {"name": "legacy-vm-09", "group": "PROD-CL2", "node": "node-03", "guest_os": "Windows 2019", "phase": "Running", "host_id_direct": None, "entity_id": "VM-006"},
        {"name": "decommissioned-vm-x", "group": "PROD-CL1", "node": "node-01", "guest_os": "RHEL 8", "phase": "Powered Off", "host_id_direct": None, "entity_id": "VM-007"},
    ]
    hosts = [
        {"entityId": "HOST-001", "displayName": "web-vm-01",
         "properties": {"monitoringMode": "FULL_STACK", "state": "RUNNING"}},
        {"entityId": "HOST-002", "displayName": "web-vm-02",
         "properties": {"monitoringMode": "CLOUD_INFRASTRUCTURE", "state": "RUNNING"}},
        {"entityId": "HOST-003", "displayName": "db-vm-01",
         "properties": {"monitoringMode": "CLOUD_INFRASTRUCTURE", "state": "RUNNING"}},
        {"entityId": "HOST-099", "displayName": "bare-metal-build-server",
         "properties": {"monitoringMode": "FULL_STACK", "state": "RUNNING"}},
    ]
    return vms, hosts


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description="Discovery & Coverage report for virtualized platforms on Dynatrace.")
    ap.add_argument("--platform", nargs="+", default=None, metavar="PLATFORM",
                    help=f"Platform(s) to report on. Repeat or space-separate for multiple "
                         f"(e.g. --platform vmware nutanix). Valid: {', '.join(sorted(PLATFORMS))}. "
                         f"Not required with --list-entity-types.")
    ap.add_argument("--out-dir", default="reports", help="Directory for report files (default: reports/).")
    ap.add_argument("--list-entity-types", action="store_true",
                    help="List all entity types in the tenant and exit. --platform not required.")
    ap.add_argument("--powered-on-only", action="store_true", default=False,
                    help="Restrict the report to powered-on VMs only "
                         "(default: include powered-off VMs too).")
    ap.add_argument("--show-unmatched-hosts", action="store_true", default=False,
                    help="List the full table of monitored hosts that didn't match a VM "
                         "(default: off — only a count is shown).")
    ap.add_argument("--summary-only", action="store_true", default=False,
                    help="Output a grouped-counts-only report (no VM detail).")
    ap.add_argument("--max-vm-rows", type=int, default=500, metavar="N",
                    help="Max VM rows in the detail table (default: 500). Use 0 for unlimited. "
                         "When the limit is reached a truncation notice is shown; "
                         "use --summary-only for large environments.")
    ap.add_argument("--mock", action="store_true", help="Use bundled sample data (no tenant).")
    ap.add_argument("--insecure", action="store_true",
                    help="Skip TLS verification (self-signed certs).")
    args = ap.parse_args()

    if not args.platform and not args.list_entity_types:
        ap.error("--platform is required unless --list-entity-types is used.")

    platform_keys = args.platform or []
    for k in platform_keys:
        if k not in PLATFORMS:
            sys.exit(f"Unknown platform '{k}'. Valid: {', '.join(sorted(PLATFORMS))}")
    platforms = [PLATFORMS[k] for k in platform_keys]

    include_powered_off = not args.powered_on_only

    opts = [f"--platform {' '.join(platform_keys)}"]
    if args.summary_only:
        opts.append("--summary-only")
    if args.powered_on_only:
        opts.append("--powered-on-only")
    if args.show_unmatched_hosts:
        opts.append("--show-unmatched-hosts")
    if args.mock:
        opts.append("--mock")
    cli_opts = " ".join(opts)

    results = []

    if args.mock:
        base_url = "mock data"
        raw_vms, hosts = mock_data()
        for plat in platforms:
            s, rows = analyze(raw_vms, hosts, include_powered_off=include_powered_off)
            for row in rows:
                row["platform_label"] = plat.label
            results.append((plat, s, rows))
    else:
        base = os.environ.get("DT_BASE_URL")
        base_url = base
        token = os.environ.get("DT_API_TOKEN")
        missing = []
        if not base:
            missing.append(
                "  DT_BASE_URL   SaaS:    https://ENVIRONMENT-ID.live.dynatrace.com\n"
                "               Managed: https://your-domain/e/ENVIRONMENT-ID"
            )
        if not token:
            missing.append(
                "  DT_API_TOKEN  e.g. dt0c01.XXXX...   (required scope: entities.read)"
            )
        if missing:
            sys.exit(
                "Missing required environment variables:\n\n"
                + "\n\n".join(missing)
                + "\n\nOr run offline with: --mock"
            )
        client = DynatraceClient(base, token, verify_tls=not args.insecure)

        if args.list_entity_types:
            for t in client.fetch_entity_types():
                print(f"{t.get('type'):40}  {t.get('displayName', '')}")
            return

        print("Fetching monitored hosts (HOST entities)...", file=sys.stderr)
        hosts = client.fetch_hosts()
        print(f"  {len(hosts)} hosts", file=sys.stderr)

        for plat in platforms:
            vm_type = plat.vm_entity_type or client.detect_vm_entity_type(plat)
            if not vm_type:
                print(f"WARNING: Could not determine the {plat.label} VM entity type — skipping. "
                      "Run --list-entity-types to check. (Is the platform's extension installed?)",
                      file=sys.stderr)
                continue
            print(f"Using VM entity type: {vm_type} ({plat.label})", file=sys.stderr)
            print(f"Fetching {plat.label} VMs...", file=sys.stderr)
            vms = client.fetch_discovered_vms(plat, vm_type, all_vms=include_powered_off)
            print(f"  {len(vms)} VMs", file=sys.stderr)
            s, rows = analyze(vms, hosts, include_powered_off=include_powered_off)
            for row in rows:
                row["platform_label"] = plat.label
            results.append((plat, s, rows))

    combined_summary = _combine_summaries(results)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    os.makedirs(args.out_dir, exist_ok=True)
    basename = OUT_BASENAME + ("_summary" if args.summary_only else "") + ("_mock" if args.mock else "")
    html_path = os.path.join(args.out_dir, basename + ".html")
    md_path = os.path.join(args.out_dir, basename + ".md")

    with open(html_path, "w", encoding="utf-8") as f:
        if args.summary_only:
            f.write(render_html_summary_only(results, combined_summary, generated,
                                             base_url=base_url, cli_opts=cli_opts))
        else:
            f.write(render_html(results, combined_summary, generated,
                                show_orphans=args.show_unmatched_hosts,
                                base_url=base_url, cli_opts=cli_opts,
                                max_vm_rows=args.max_vm_rows))
    with open(md_path, "w", encoding="utf-8") as f:
        if args.summary_only:
            f.write(render_markdown_summary_only(results, combined_summary, generated,
                                                 base_url=base_url, cli_opts=cli_opts))
        else:
            f.write(render_markdown(results, combined_summary, generated,
                                    show_orphans=args.show_unmatched_hosts,
                                    base_url=base_url, cli_opts=cli_opts,
                                    max_vm_rows=args.max_vm_rows))

    print(f"\nCoverage: {combined_summary['coverage_pct']}%  "
          f"({combined_summary['monitored_vms']}/{combined_summary['candidate_vms']} powered-on VMs monitored)")
    print(f"HTML : {html_path}")
    print(f"MD   : {md_path}")


if __name__ == "__main__":
    main()
