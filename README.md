# Algites Orchestrator

A general orchestration tool for declarative Algites automation workflows.

> Public Algites project.

---

## 📦 Overview

**Algites Orchestrator** is a tool for describing, resolving, validating, and applying orchestration workflows in a structured and reusable way.

The project is intentionally designed as a general orchestrator rather than as a tool tied permanently to a single infrastructure use case. Its first domain is **Deployment**, which focuses on deploying virtualized guests onto host systems while keeping guest requirements, host capabilities, and deployment-specific decisions clearly separated.

The Deployment domain is intended to support environments such as:

- Debian-based virtualization hosts using QEMU/KVM and libvirt,
- NixOS guests with declarative guest configuration,
- Ansible-based host-side orchestration,
- multiple storage classes and storage backends,
- host-specific network and firewall configuration,
- reusable guest definitions deployable to different hosts,
- explicit placement constraints between guest data resources,
- generated deployment plans that can be validated before they are applied.

The project is part of the Algites ecosystem and is designed around explicit configuration, separation of concerns, reproducibility, validation, and automation.

---

## 🧱 Modules & Structure

The project is expected to be structured by orchestration domain. The first domain is `deployment`.

```text
.
├── README.md
├── LICENSE
├── orchestrator/
│   ├── common/
│   │   ├── configuration/
│   │   ├── validation/
│   │   └── execution/
│   │
│   └── deployment/
│       ├── model/
│       ├── resolver/
│       ├── placement/
│       ├── validation/
│       ├── ansible/
│       ├── nixos/
│       └── cli/
│
├── ansible_collections/
│   └── algites/
│       └── orchestrator/
│           ├── plugins/
│           │   ├── filter/
│           │   ├── action/
│           │   └── plugin_utils/
│           └── roles/
│
├── schemas/
│   └── deployment/
│
└── tests/
    └── deployment/
```

The exact physical structure may evolve while the first implementation is developed. The architectural boundary is more important than the final folder layout:

- reusable orchestration logic belongs to the Orchestrator,
- deployment-specific logic belongs to the `deployment` domain,
- Ansible integration is an adapter/execution layer rather than the source of deployment business logic,
- guest operating-system configuration remains owned by the guest definition, for example by NixOS modules or flakes.

---

# Deployment

## Purpose

The Deployment domain describes and applies the deployment of a guest onto a host.

Its central design principle is that three different configuration concerns must remain separate:

```text
HostConfiguration
        +
GuestConfiguration
        +
GuestDeploymentConfiguration
        ↓
Deployment Resolver
        ↓
DeploymentPlan
        ↓
Execution / Ansible
```

This prevents host-specific implementation details from leaking into reusable guest definitions and prevents deployment-specific sizing or addressing from forcing the creation of separate guest types.

---

## Configuration Model

### HostConfiguration

`HostConfiguration` describes what a concrete host provides and how its infrastructure is implemented.

Typical host-specific information includes:

- available storage classes,
- concrete storage targets,
- physical or logical storage topology,
- RAID, LVM, filesystem, qcow2, or other backend information,
- root paths for storage areas,
- libvirt networks,
- bridge names,
- address ranges,
- DHCP configuration,
- NAT or routed networking,
- firewall rules,
- external-to-internal address mappings,
- supported guest interfaces such as Samba, NFS, virtio block, or other mechanisms,
- host capabilities relevant to guest placement.

A host configuration describes implementation capability. It does not describe what a particular guest requires.

Example:

```yaml
host: artning

storage_classes:
  PERSISTENT:
    root: /srv/libvirt/PERSISTENT

  DISPOSABLE:
    root: /srv/libvirt/DISPOSABLE

  ARCHIVE:
    root: /srv/libvirt/ARCHIVE

networks:
  vm:
    bridge: virbr-vm
    subnet: 172.27.122.0/24
```

---

### GuestConfiguration

`GuestConfiguration` describes what a reusable guest type requires in order to run.

It must remain independent of the concrete host on which the guest will eventually be deployed.

Typical information includes:

- required guest operating system,
- minimum or default CPU and memory requirements,
- required data resources,
- storage-class requirements,
- representation requirements,
- access requirements,
- minimum or default storage capacities where they are true workload requirements,
- placement relations between data resources,
- references to guest operating-system configuration such as NixOS modules or flakes.

A guest configuration should not contain host-specific values such as:

- concrete host names,
- physical volume groups,
- `/srv/libvirt/...` paths,
- concrete qcow2 paths,
- host-specific IP addresses,
- concrete storage target names.

Example:

```yaml
guest: PostgreSQL

resources:
  cpu:
    minimum: 2

  memory:
    minimum: 2G
    default: 8G

data_resources:
  system-root:
    storage_class: DISPOSABLE
    purpose: SYSTEM
    representation: BLOCK
    capacity:
      minimum: 20G

  database-data:
    storage_class: PERSISTENT
    purpose: DATA
    representation: BLOCK

  database-wal:
    storage_class: PERSISTENT
    purpose: DATA
    representation: BLOCK

  backup-repository:
    storage_class: ARCHIVE
    purpose: BACKUP
    representation: FILE_SHARE
```

---

### GuestDeploymentConfiguration

`GuestDeploymentConfiguration` connects one concrete guest deployment to one concrete host.

It contains values that are specific to a particular deployment rather than to the reusable guest type.

Typical information includes:

- concrete guest instance name,
- selected host,
- CPU and memory allocation,
- concrete IP addresses,
- network bindings,
- concrete data-resource capacities,
- explicit storage target bindings where required,
- deployment-specific overrides,
- bindings to shared or global data resources.

Example:

```yaml
deployment: PostgreSQL01

guest: PostgreSQL
host: artning

resources:
  cpu: 4
  memory: 8G

network:
  network: vm
  ipv4: 172.27.122.30

data_resources:
  system-root:
    size: 40G

  database-data:
    size: 500G

  database-wal:
    size: 100G

  backup-repository:
    size: 2T
```

A concrete capacity therefore normally belongs to the deployment configuration. The guest definition may still declare a minimum or default capacity if the workload genuinely requires one.

---

## DataResource

A `DataResource` is a uniquely identified logical data resource required by a guest or shared between guests.

The term is intentionally broader than `DiskResource`, because a data resource may be exposed as a block device, a file share, or a service.

A guest may define any number of data resources with the same category values. The resource identifier distinguishes them.

For example:

```yaml
data_resources:
  database-data:
    storage_class: PERSISTENT
    purpose: DATA
    representation: BLOCK

  database-wal:
    storage_class: PERSISTENT
    purpose: DATA
    representation: BLOCK

  web-media:
    storage_class: ARCHIVE
    purpose: DATA
    representation: FILE_SHARE

  gradle-cache:
    storage_class: DISPOSABLE
    purpose: CACHE
    representation: FILE_SHARE
```

`database-data` and `database-wal` are separate resources even though their classifications are otherwise identical. This allows deployment to place them on different physical or logical devices when required.

---

## DataResource Dimensions

A DataResource is described through several independent dimensions rather than through a growing number of combined resource types.

### StorageClass

`StorageClass` describes the abstract storage service required by the workload.

Initial classes are:

```text
DISPOSABLE
PERSISTENT
ARCHIVE
```

Their exact physical implementation is host-specific.

Typical meanings are:

- `DISPOSABLE` — data may be lost and recreated; suitable for temporary systems, caches, builds, and other reproducible data,
- `PERSISTENT` — normal operational data that must survive guest recreation or ordinary storage failure scenarios,
- `ARCHIVE` — high-capacity persistent storage where lower performance may be acceptable, for example media, long-lived datasets, or backup repositories.

A StorageClass is not a fixed physical backend. For example, `PERSISTENT` may be implemented by NVMe RAID1 on one host and by another replicated or mirrored backend on another host.

---

### Purpose

`Purpose` describes what the data is for.

Initial purposes are:

```text
SYSTEM
DATA
CACHE
BACKUP
```

Typical meanings are:

- `SYSTEM` — state belonging to the guest operating system itself, such as its root filesystem,
- `DATA` — primary application or user data,
- `CACHE` — reproducible auxiliary data used to reduce download, build, or processing cost,
- `BACKUP` — backup copies or backup repositories.

Purpose is independent of StorageClass. For example, a cache may be `DISPOSABLE` on one host but deliberately `PERSISTENT` on another if rebuilding it is expensive.

---

### Representation

`Representation` describes what the consumer logically receives.

Initial representations include:

```text
BLOCK
FILE_SHARE
SERVICE
```

Examples:

- `BLOCK` — the guest receives an exclusive virtual block device,
- `FILE_SHARE` — the guest accesses a shared filesystem namespace,
- `SERVICE` — the data is exposed through a service or protocol, for example a Nix binary cache.

The earlier conceptual distinction between guest-owned `RUN` storage and shared storage is therefore expressed more precisely by representation and purpose rather than by a separate `RUN` purpose.

---

### Access

Access is a relation between a consumer and a DataResource, not an immutable property of the resource itself.

Initial access modes are expected to include:

```text
NONE
RO
RW
```

The model should remain extensible for additional semantics such as:

```text
APPEND_ONLY
ADMIN
```

Example:

```yaml
access:
  CacheBuilder01: RW
  Codex01: RO
  Codex02: RO
  host: NONE
```

This allows one guest to populate a shared cache while other guests consume it read-only, without requiring the virtualization host to perform application-level work.

---

### Interface

`Interface` describes how the guest accesses a resolved DataResource.

Examples include:

```text
VIRTIO_BLOCK
SAMBA
NFS
HTTP
NIX_BINARY_CACHE
```

Interface is part of the host/guest deployment contract and therefore cannot be treated as a host-only implementation detail.

For example, if a `FILE_SHARE` is resolved to Samba, the host must configure the Samba export and the guest must configure a CIFS mount. If the same logical resource is resolved to NFS on another host, both sides must be configured accordingly.

The guest type may request only a representation while leaving the concrete interface to deployment resolution, provided that the resolved interface is supported by the guest.

---

### Implementation / Backend

`Implementation` describes how the selected host physically realizes a resource.

This is host-side information and should normally not leak into reusable guest configuration.

Examples include:

```text
QCOW2
LVM
DIRECTORY
raw block device
host filesystem path
```

For example:

```text
Representation: BLOCK
Interface:      VIRTIO_BLOCK
Backend:        QCOW2
```

or:

```text
Representation: FILE_SHARE
Interface:      SAMBA
Backend:        DIRECTORY
```

A different host may use LVM instead of qcow2 while exposing the same `VIRTIO_BLOCK` interface to the guest.

---

## StorageTarget

A `StorageTarget` is a concrete placement target provided by a host.

It is distinct from `StorageClass`:

```text
StorageClass
    abstract requirement requested by the guest

StorageTarget
    concrete target offered by the host

DataResource
    logical resource required by the guest
```

A host may provide multiple StorageTargets implementing the same StorageClass.

Example:

```yaml
storage_targets:
  nvme-main:
    storage_class: PERSISTENT
    backend:
      type: QCOW2
      root: /srv/libvirt/PERSISTENT
    topology:
      device: nvme-raid1-main
      controller: nvme-controller-0
      failure_domain: host-local-nvme

  nvme-secondary:
    storage_class: PERSISTENT
    backend:
      type: QCOW2
      root: /srv/libvirt/PERSISTENT-SECONDARY
    topology:
      device: nvme-raid1-secondary
      controller: nvme-controller-1
      failure_domain: host-local-nvme-secondary
```

A deployment can explicitly bind a DataResource to a StorageTarget, or it can allow the resolver to choose a suitable target.

---

## Placement Relations

Placement requirements are business requirements of the guest and therefore belong to `GuestConfiguration`.

They are defined separately from individual DataResources because placement is a relation between resources rather than a property of one resource.

A relation may include two or more DataResources.

Example:

```yaml
placement_relations:
  - resources:
      - database-data
      - database-wal
    relation: ALL_DIFFERENT_DEVICE
    strength: PREFERRED

  - resources:
      - primary-data
      - local-backup
      - recovery-copy
    relation: ALL_DIFFERENT_FAILURE_DOMAIN
    strength: REQUIRED
```

### Strength

Initial strengths are:

```text
REQUIRED
PREFERRED
```

Semantics:

- `REQUIRED` — the deployment must fail if the relation cannot be satisfied,
- `PREFERRED` — the resolver should try to satisfy the relation, but deployment may continue with a warning if it cannot.

### Relation Types

Expected relation types may include:

```text
ALL_DIFFERENT_STORAGE_TARGET
ALL_DIFFERENT_DEVICE
ALL_DIFFERENT_CONTROLLER
ALL_DIFFERENT_FAILURE_DOMAIN
SAME_STORAGE_TARGET
SAME_DEVICE
SAME_FAILURE_DOMAIN
```

The model should remain extensible for constraints such as maximum resources per device or other future placement policies.

A relation containing more than two resources naturally expresses requirements such as placing three replicas in three different failure domains.

---

## Placement Resolution

The deployment resolver combines:

```text
HostConfiguration
GuestConfiguration
GuestDeploymentConfiguration
```

and produces a resolved `DeploymentPlan`.

The resolver is expected to perform the following phases:

```text
1. Configuration validation
2. Candidate StorageTarget discovery
3. Application of explicit deployment bindings
4. Elimination of candidates violating REQUIRED constraints
5. Placement search
6. Maximization of satisfied PREFERRED constraints
7. Interface resolution
8. Backend resolution
9. DeploymentPlan generation
```

If a host cannot satisfy a `REQUIRED` placement relation, deployment must fail explicitly rather than silently degrading the guest's requirements.

If only a `PREFERRED` relation cannot be satisfied, deployment may continue but the resulting plan must report the unsatisfied preference.

The initial implementation can use a straightforward backtracking/search algorithm. The declarative model should not depend on the internal solving algorithm, allowing a more advanced constraint solver to replace it later if needed.

---

## DeploymentPlan

`DeploymentPlan` is the resolved output of the deployment engine and the primary input to the execution layer.

It contains concrete decisions such as:

- selected StorageTargets,
- concrete storage paths,
- qcow2 or LVM backend selection,
- virtual block interfaces,
- resolved Samba/NFS/service interfaces,
- concrete host-side exports,
- guest-side mount configuration,
- network bindings,
- IP addresses,
- warnings for unsatisfied `PREFERRED` relations.

Conceptual example:

```yaml
deployment_plan:
  guest: PostgreSQL01
  host: artning

  network:
    network: vm
    ipv4: 172.27.122.30

  data_resources:
    database-data:
      storage_target: nvme-main
      implementation:
        backend: QCOW2
        path: /srv/libvirt/PERSISTENT/qemu/images/PostgreSQL01/database-data.qcow2
      interface:
        type: VIRTIO_BLOCK

    backup-repository:
      storage_target: archive-main
      implementation:
        backend: DIRECTORY
        path: /srv/libvirt/ARCHIVE/backup/PostgreSQL01
      interface:
        type: SAMBA

  warnings: []
```

Execution roles should consume the resolved DeploymentPlan rather than reimplementing placement business logic independently.

---

## Ansible Integration

Ansible is the orchestration and execution layer, but it is not intended to contain the core placement/resolution algorithm in YAML tasks.

The deployment resolver should be implemented as normal testable code, initially expected to be Python.

Conceptual structure:

```text
resolver.py
placement.py
validation.py
model.py
errors.py
```

The core API may conceptually resemble:

```python
def resolve_deployment(
    host_configuration,
    guest_configuration,
    deployment_configuration,
):
    ...
    return deployment_plan
```

The core resolver should avoid unnecessary Ansible dependencies so it can be unit-tested and potentially reused outside Ansible.

Ansible integration may then be implemented through an Algites Ansible Collection.

A thin filter or action plugin can expose the resolver to Ansible. For example:

```yaml
- name: Resolve deployment
  ansible.builtin.set_fact:
    deployment_plan: >-
      {{
        guest_configuration
        | algites.orchestrator.resolve_deployment(
            host_configuration,
            deployment_configuration
          )
      }}
```

The resulting DeploymentPlan is then applied by ordinary idempotent Ansible roles, for example:

```text
DeploymentPlan
    ├── storage role
    ├── libvirt role
    ├── network role
    ├── firewall role
    ├── file-share role
    └── guest configuration role
```

Typical responsibilities include:

- creation of qcow2 images or LVM volumes,
- generation and application of libvirt domain definitions,
- creation of libvirt networks,
- firewall and NAT configuration,
- Samba or NFS exports,
- host directory and permission management,
- generation of guest deployment configuration,
- installation or update of NixOS guests.

This separation keeps Ansible focused on reaching the desired state while keeping placement and deployment decisions in normal program code.

---

## NixOS Guest Integration

For NixOS guests, software dependencies and operating-system configuration belong to the guest definition itself.

For example:

```text
guests/
└── codex/
    ├── guest.yml
    └── nixos/
        ├── default.nix
        ├── packages.nix
        ├── services.nix
        └── ...
```

The guest YAML should reference the NixOS configuration but should not duplicate package lists already maintained in Nix.

For example, packages remain authoritative in Nix:

```nix
environment.systemPackages = with pkgs; [
  git
  gradle
  temurin-bin-17
];
```

Deployment-specific values that cannot be known by the reusable guest definition are generated from the DeploymentPlan.

Examples include:

- concrete host name,
- IP address,
- resolved Samba or NFS endpoints,
- read-only/read-write mount options,
- virtual disk labels and mount points.

A generated deployment module may then be imported by the reusable guest NixOS configuration.

Conceptually:

```text
Reusable guest NixOS configuration
            +
Generated deployment configuration
            ↓
Concrete deployed NixOS guest
```

This allows the same guest definition to be deployed repeatedly to different hosts without duplicating the guest operating-system configuration.

---

## Host and Guest Responsibilities

The virtualization host should remain focused on infrastructure responsibilities whenever practical.

Typical host responsibilities:

```text
QEMU/KVM/libvirt
storage
networking
firewall
share transport
orchestration runtime
host monitoring
```

Application-specific activities should normally live in guests rather than on the virtualization host.

For example, a shared Nix or Gradle cache may be populated by a dedicated guest with `RW` access while other guests receive `RO` access. The host provides storage and transport but does not need to perform package download or application build work itself.

---

## Storage and Backup Model

The current storage model distinguishes three abstract StorageClasses:

```text
DISPOSABLE
PERSISTENT
ARCHIVE
```

Typical usage:

```text
DISPOSABLE
    temporary root disks
    build output
    reproducible caches

PERSISTENT
    databases
    application state
    working data

ARCHIVE
    high-capacity application data
    media
    long-lived datasets
    local backup repositories
```

`ARCHIVE` may contain both operational archival data and backup repositories. These are distinguished by `Purpose`, for example `DATA` versus `BACKUP`.

A local backup stored on the same physical failure domain as the primary data is not considered a complete independent backup. Placement relations can express hard requirements for separate failure domains where needed.

Backup behavior should eventually become part of declarative deployment policy rather than a manual operational procedure.

---

## Shared Caches

Shared caches are represented as ordinary DataResources rather than as a separate StorageClass.

For example:

```yaml
gradle-cache:
  storage_class: DISPOSABLE
  purpose: CACHE
  representation: FILE_SHARE
```

while a more expensive cache may use:

```yaml
nix-cache:
  storage_class: PERSISTENT
  purpose: CACHE
  representation: SERVICE
```

Access is assigned per consumer, allowing patterns such as:

```yaml
access:
  NixCache01: RW
  Codex01: RO
  Codex02: RO
  host: NONE
```

For Nix, a shared binary cache is preferred over directly sharing `/nix/store` between guests.

For Gradle, a shared read-only dependency cache can be exposed to multiple guests while a designated builder or cache-management guest is responsible for populating it.

---

## Future Deployment Capabilities

The model is intentionally designed to leave room for additional capabilities without changing existing guest definitions unnecessarily.

Potential future areas include:

- migration between hosts,
- automatic host selection,
- resource-capacity-aware scheduling,
- richer placement constraints,
- backup policy resolution,
- multiple failure-domain levels,
- remote storage backends,
- multiple hypervisor implementations,
- deployment lifecycle management,
- generated deployment diffs,
- dry-run / planning output,
- destroy / undeploy operations,
- nested virtualization hosts,
- infrastructure service guests such as cache, backup, monitoring, or build services.

---

## 🚀 Build

The implementation technology and final build tooling are not yet fixed.

The initial deployment resolver is expected to be implemented in Python and integrated with Ansible through an Algites Ansible Collection. NixOS guest definitions remain native Nix configuration.

Build and packaging instructions will be added once the initial implementation is established.

---

## 🔄 Continuous Integration (Algites CI)

This repository uses the **Algites unified GitHub Actions CI pipeline** (build/test/publish rules are centralized).

For exact usage and naming of the branches to utilize fully the defined possibilities, see
https://github.com/Algites-EU/pub.gov.Algites.specs/blob/main/ci/Algites-Github-CI-Policy.md

---

## 📥 Usage

The final CLI is not yet implemented.

The intended command structure is based on orchestration domains. For Deployment, a possible interface is:

```bash
algites-orchestrator deployment validate
algites-orchestrator deployment plan
algites-orchestrator deployment apply
algites-orchestrator deployment destroy
```

The exact command names and configuration file layout may evolve during implementation.

---

## 🛠 Development

Typical workflow:

```bash
git clone https://github.com/Algites-EU/pub.tool.Orchestrator.git
cd pub.tool.Orchestrator
```

Further development and test commands will be documented after the initial project skeleton and implementation technology are finalized.

---

## 🤝 Contributing

Contributions are welcome.

Please:

- open an issue to discuss changes,
- follow the Algites coding and naming standards,
- preserve the separation between host, guest, and deployment configuration concerns,
- keep deployment resolution logic independent from execution tooling where practical,
- ensure CI passes before submitting a PR.

---

## 📜 License

Copyright Artur Linhart, Algites.

Licensed under the **Apache License, Version 2.0**.

See the `LICENSE` file for the complete license text.

---

## 🌍 About Algites

Algites develops platforms, tools, and applications based on strong governance,
modeling, and automation principles.

See:
- https://github.com/Algites-EU/pub.gov.Algites

---

**© Algites**
