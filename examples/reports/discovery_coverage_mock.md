# Discovery & Coverage

_Generated 2026-06-10 15:35 UTC · --platform vmware nutanix hyperv openshift --mock_

## Summary

- **Environment:** mock data
- **Total VMs:** 28 (4 powered off, 24 powered on)
- **Monitored (powered on):** 12 (50.0% coverage)
- **Coverage gap (no OneAgent):** 12
- **Full-Stack:** 4 (16.7%)

## Coverage by Cluster

| Platform | Cluster | Total VMs | Powered Off | Monitored | Full-Stack | Gap | Coverage |
|----------|---------|-----------|-------------|-----------|------------|-----|----------|
| Microsoft Hyper-V | PROD-CL1 | 4 | 1 | 3 | 1 | 0 | 100.0% |
| Microsoft Hyper-V | PROD-CL2 | 3 | 0 | 0 | 0 | 3 | 0.0% |
| Nutanix AHV | PROD-CL1 | 4 | 1 | 3 | 1 | 0 | 100.0% |
| Nutanix AHV | PROD-CL2 | 3 | 0 | 0 | 0 | 3 | 0.0% |
| OpenShift Virtualization | PROD-CL1 | 4 | 1 | 3 | 1 | 0 | 100.0% |
| OpenShift Virtualization | PROD-CL2 | 3 | 0 | 0 | 0 | 3 | 0.0% |
| VMware vSphere | PROD-CL1 | 4 | 1 | 3 | 1 | 0 | 100.0% |
| VMware vSphere | PROD-CL2 | 3 | 0 | 0 | 0 | 3 | 0.0% |
| | **Total** | **28** | **4** | **12** | **4** | **12** | **50.0%** |

## Discovery — VMware vSphere

### VM / Host coverage

| Cluster | Cluster Node | VM Name | Entity ID | Mode | Recommended action |
|---------|--------------|---------|-----------|------|--------------------|
| PROD-CL1 | node-01 | decommissioned-vm-x | VM-007 | POWERED_OFF | Powered off — no action needed |
| PROD-CL2 | node-01 | batch-vm-01 | VM-005 | NONE | Install OneAgent |
| PROD-CL2 | node-03 | db-vm-02 | VM-004 | NONE | Install OneAgent |
| PROD-CL2 | node-03 | legacy-vm-09 | VM-006 | NONE | Install OneAgent |
| PROD-CL1 | node-02 | db-vm-01 | VM-003 | CLOUD_INFRASTRUCTURE | Consider Full-Stack |
| PROD-CL1 | node-01 | web-vm-01 | VM-001 | FULL_STACK | No action |
| PROD-CL1 | node-02 | web-vm-02 | VM-002 | CLOUD_INFRASTRUCTURE | Consider Full-Stack |

### Monitored hosts not matched to a VM (1)

_1 monitored host(s) did not join to a discovered VMware vSphere VM (likely hosts from other platforms). Re-run with `--show-unmatched-hosts` to list them._

## Discovery — Nutanix AHV

### VM / Host coverage

| Cluster | Cluster Node | VM Name | Entity ID | Mode | Recommended action |
|---------|--------------|---------|-----------|------|--------------------|
| PROD-CL1 | node-01 | decommissioned-vm-x | VM-007 | POWERED_OFF | Powered off — no action needed |
| PROD-CL2 | node-01 | batch-vm-01 | VM-005 | NONE | Install OneAgent |
| PROD-CL2 | node-03 | db-vm-02 | VM-004 | NONE | Install OneAgent |
| PROD-CL2 | node-03 | legacy-vm-09 | VM-006 | NONE | Install OneAgent |
| PROD-CL1 | node-02 | db-vm-01 | VM-003 | CLOUD_INFRASTRUCTURE | Consider Full-Stack |
| PROD-CL1 | node-01 | web-vm-01 | VM-001 | FULL_STACK | No action |
| PROD-CL1 | node-02 | web-vm-02 | VM-002 | CLOUD_INFRASTRUCTURE | Consider Full-Stack |

### Monitored hosts not matched to a VM (1)

_1 monitored host(s) did not join to a discovered Nutanix AHV VM (likely hosts from other platforms). Re-run with `--show-unmatched-hosts` to list them._

## Discovery — Microsoft Hyper-V

### VM / Host coverage

| Cluster | Cluster Node | VM Name | Entity ID | Mode | Recommended action |
|---------|--------------|---------|-----------|------|--------------------|
| PROD-CL1 | node-01 | decommissioned-vm-x | VM-007 | POWERED_OFF | Powered off — no action needed |
| PROD-CL2 | node-01 | batch-vm-01 | VM-005 | NONE | Install OneAgent |
| PROD-CL2 | node-03 | db-vm-02 | VM-004 | NONE | Install OneAgent |
| PROD-CL2 | node-03 | legacy-vm-09 | VM-006 | NONE | Install OneAgent |
| PROD-CL1 | node-02 | db-vm-01 | VM-003 | CLOUD_INFRASTRUCTURE | Consider Full-Stack |
| PROD-CL1 | node-01 | web-vm-01 | VM-001 | FULL_STACK | No action |
| PROD-CL1 | node-02 | web-vm-02 | VM-002 | CLOUD_INFRASTRUCTURE | Consider Full-Stack |

### Monitored hosts not matched to a VM (1)

_1 monitored host(s) did not join to a discovered Microsoft Hyper-V VM (likely hosts from other platforms). Re-run with `--show-unmatched-hosts` to list them._

## Discovery — OpenShift Virtualization

### VM / Host coverage

| Namespace | Cluster Node | VM Name | Entity ID | Mode | Recommended action |
|---------|--------------|---------|-----------|------|--------------------|
| PROD-CL1 | node-01 | decommissioned-vm-x | VM-007 | POWERED_OFF | Powered off — no action needed |
| PROD-CL2 | node-01 | batch-vm-01 | VM-005 | NONE | Install OneAgent |
| PROD-CL2 | node-03 | db-vm-02 | VM-004 | NONE | Install OneAgent |
| PROD-CL2 | node-03 | legacy-vm-09 | VM-006 | NONE | Install OneAgent |
| PROD-CL1 | node-02 | db-vm-01 | VM-003 | CLOUD_INFRASTRUCTURE | Consider Full-Stack |
| PROD-CL1 | node-01 | web-vm-01 | VM-001 | FULL_STACK | No action |
| PROD-CL1 | node-02 | web-vm-02 | VM-002 | CLOUD_INFRASTRUCTURE | Consider Full-Stack |

### Monitored hosts not matched to a VM (1)

_1 monitored host(s) did not join to a discovered OpenShift Virtualization VM (likely hosts from other platforms). Re-run with `--show-unmatched-hosts` to list them._
