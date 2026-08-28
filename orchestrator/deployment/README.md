# Algites Orchestrator — Deployment

The **Deployment** domain describes, resolves, validates, and applies deployments of virtualized guests onto deployment hosts.

This directory contains the Deployment model and the implementation-specific logic built around it.

During initial model development, draft revisions keep:

```yaml
model_version: 1
```

The model version is intended to change only when a released model requires a compatibility-breaking successor.

---

## Purpose

Deployment separates reusable guest requirements, physical/shared environment topology, host capabilities, shared resources, and concrete deployment decisions.

The resolved flow is:

```text
DeploymentEnvironmentConfiguration
        +
HostConfiguration
        +
GuestConfiguration
        +
SharedMountableResourceConfiguration(s)
        +
GuestDeploymentConfiguration
        ↓
Deployment Resolver
        ↓
DeploymentPlan
        ↓
Execution / Ansible / guest configuration generation
```

Not every deployment uses a `SharedMountableResourceConfiguration`; it is needed only when a guest resource with `sharing: SHARED` is bound to independently managed shared backing.

The separation prevents:

- host-specific implementation details from leaking into reusable guest definitions,
- deployment-specific CPU, memory, addressing, or capacity values from forcing separate guest types,
- physical topology from being duplicated in every host or guest definition,
- shared storage lifecycle from being tied to an arbitrary reader or writer guest,
- Ansible tasks from becoming the implementation of placement business logic.

---

## Configuration Layers

### DeploymentEnvironmentConfiguration

`DeploymentEnvironmentConfiguration` describes physical/shared topology that spans individual deployment hosts.

It currently defines:

- **sites** — physical locations used by `NO_SHARED_SITE`,
- **hosts** — physical hosts or appliances relevant to storage independence,
- **storage systems** — external or explicitly modeled storage systems.

A deployment host's ordinary local storage normally does **not** need a storage-system entry. Host-local storage is represented by the special value:

```text
HOST_LOCAL_STORAGE
```

`HOST_LOCAL_STORAGE` is an implicit storage-system identity unique to the deployment host.

External storage systems may declare the physical hosts/appliances and sites on which they depend. This allows the resolver to distinguish, for example:

```text
local host storage
        vs.
NAS at the same site
        vs.
remote NAS at another site
        vs.
shared SAN used by several hosts
```

A `Site` represents a physical failure boundary such as a home, office, server room, or datacenter.

---

### HostConfiguration

`HostConfiguration` describes what one concrete deployment host can provide and how those capabilities are implemented.

It currently contains:

- host identity and environment binding,
- a concrete management network-service endpoint for control-node access,
- local physical/logical storage-device topology,
- storage-controller topology,
- `HostStorageTarget`s,
- guest networks,
- filesystem interface providers,
- defaults for guest-visible filesystem interfaces.

A host configuration describes **capability and implementation**. It does not describe what a particular guest requires.

Typical implementation details belong here, for example:

```text
RAID
LVM
QCOW2
raw image files
host directories
libvirt networks
bridges
NFS providers
Samba providers
virtiofs providers
```

Host-specific paths and volume groups also belong here, for example:

```text
/srv/libvirt/PERSISTENT/qemu/images
VG_NVME_RAID1
```

They must not leak into reusable `GuestConfiguration`.

---

### GuestConfiguration

`GuestConfiguration` describes what a reusable guest type requires in order to operate.

It is independent of the concrete host on which the guest is eventually deployed.

It currently describes:

- guest identity,
- operating-system type and configuration reference,
- minimum/default compute requirements,
- logical network interfaces,
- mountable resources,
- relations between mountable resources,
- consumed and provided `ServiceConfiguration` references.

A guest configuration should not contain host-specific values such as:

- concrete deployment host names,
- concrete storage-target names,
- LVM volume groups,
- `/srv/libvirt/...` paths,
- concrete QCOW2 paths,
- concrete deployment IP addresses.

For NixOS guests, `os.type: NIXOS` selects the framework-owned `nixos/` attachment directory; packages, services, users and other settings remain authoritative there rather than being duplicated in YAML. Debian hosts or guests analogously select `debian/`.

---

### SharedMountableResourceConfiguration

`SharedMountableResourceConfiguration` defines independently-lived storage backing intentionally shared by multiple guest deployments.

It is not owned by any one reader, writer, cache-builder, or other consumer.

The configuration defines infrastructure realization such as:

- stable shared-resource identity,
- storage class,
- representation,
- realization host,
- `HostStorageTarget`,
- optional concrete size,
- optional backend selection,
- optional FILESYSTEM interface provider.

Guest-specific semantics remain in `GuestConfiguration`, including:

- `purpose`,
- `mount_point`,
- `access`,
- `sharing`.

Therefore the same shared backing may be used by different guests with different access modes, for example:

```text
CacheBuilder01        RW
Codex01               RO
Codex02               RO
        \              |              /
         \             |             /
          shared-gradle-cache
```

The lifecycle of `shared-gradle-cache` is independent of the lifecycle of all three guests.

---

### ServiceConfiguration

`ServiceConfiguration` is a reusable versioned definition of a logical service.
Hosts and guests can declare named `consumed_services` and `provided_services`
references to exact service configuration versions. Concrete provider-instance
selection is intentionally not modeled yet.

Every ServiceConfiguration version package has three fixed definition branches,
and each branch contains operating-system-specific implementations:

```text
services/<namespace>/<service-id>/<config-version>/
├── <service-id>_<config-version>.yml
├── common/
│   ├── nixos/
│   └── debian/
├── consumer/
│   ├── nixos/
│   └── debian/
└── provider/
    ├── nixos/
    └── debian/
```

`common/<os>/` contains implementation definitions shared by consumer and provider
roles for that OS. It is optional for a given OS. `consumer/<os>/` and
`provider/<os>/` contain role-specific implementations; the corresponding role
directory must exist when the service is consumed or provided by a target with
that `os.type`. Definition files are not stored directly below `common/`,
`consumer/` or `provider/`. The YAML may define OS-independent
`network_service_bindings` describing transport/port contracts of the service.

The resolver selects service implementation paths independently for each target.
For example, a NixOS guest consuming a service resolves `common/nixos/` (when
present) plus `consumer/nixos/`, while a Debian host consuming the same service
resolves `common/debian/` plus `consumer/debian/`. Provider and consumer systems
do not need to run the same operating system. The selected paths are written
explicitly to `DeploymentPlan.resolved_services`.

---

### GuestDeploymentConfiguration

`GuestDeploymentConfiguration` binds one concrete guest deployment to one concrete deployment host.

It supplies values that belong to the deployment rather than the reusable guest type, including:

- deployment identity,
- selected guest type,
- selected host,
- concrete CPU allocation,
- concrete memory allocation,
- concrete host-network bindings,
- a management network-service binding to one logical guest interface,
- IPv4 and/or IPv6 addresses,
- concrete storage sizes where applicable,
- direct `HostStorageTarget` bindings,
- optional backend/interface overrides,
- bindings from guest `SHARED` resources to `SharedMountableResourceConfiguration`.

For a directly realized resource, the deployment normally supplies:

```yaml
host_storage_target: persistent-nvme
```

and optionally:

```yaml
size: 64GiB
backend: LVM
```

For a shared resource, the deployment instead supplies the shared identity:

```yaml
shared_mountable_resource:
  reference: shared-gradle-cache
  reference_config_version: "1.0"
```

The resolver must validate that the concrete deployment does not weaken or contradict requirements from `GuestConfiguration`.

---

### DeploymentPlan

`DeploymentPlan` is the fully resolved output of the Deployment resolver.

It records canonical source identities and concrete decisions such as:

- exact deployment, guest, host and environment configuration references and versions,
- resolved guest OS type and package-relative OS configuration path,
- resolved CPU and memory,
- resolved host-network bindings,
- IPv4 and IPv6 addresses,
- selected `HostStorageTarget`s,
- resolved storage-system identities,
- selected backends,
- concrete storage paths,
- selected filesystem providers,
- shared-resource identities,
- resolved consumed/provided ServiceConfiguration versions,
- relation results,
- warnings for unsatisfied `PREFERRED` relations.

Execution layers consume the resolved `DeploymentPlan` instead of independently reimplementing placement and resolution rules.

A standalone `DeploymentPlan` is intentionally data-only. It does not embed the NixOS tree, scripts, templates or other files owned by the involved configuration entities.

### DeploymentBundle

`DeploymentBundle` is the portable ZIP execution artifact. It contains one or more DeploymentPlans and, separately for every plan, copies the complete Configuration Entity Packages accessed while resolving that deployment. Each deployment subtree is therefore self-contained even when this duplicates a host, guest, service or shared-resource package used by another plan in the same bundle.

The bundle root also contains a manifest in the same selected structured format as the plans. YAML, JSON and XML are supported for plans and the manifest; entity-owned attachment files remain in their original formats. See `CLI.md` for the authoritative bundle layout and stream contract.

---

## Configuration Entity Versioning

All source configuration entities use one versioning model. Each root entity
contains:

```yaml
id: example
config_version: "1.0"
config_version_state: RELEASED
```

`config_version` identifies an Orchestrator configuration definition; it is not
the runtime version of an application, package, OS or service.
`config_version_state` is a user-defined lifecycle/policy label. Orchestrator
does not assign built-in semantics to values such as `DEVELOPMENT`, `TESTED` or
`RELEASED`.

The repository layout is uniformly:

```text
<category>/<namespace>/<entity-id>/<config-version>/<entity-id>_<config-version>.yml
```

Cross-entity references always identify both the stable entity and exact version:

```yaml
guest:
  reference: application/backend
  reference_config_version: "14.0"
```

There is no implicit `latest` during resolution. Multiple versions of the same
entity may coexist in one configuration repository. The CLI compact form uses
`<reference>@<config_version>`.

---

## MountableResource

A `MountableResource` is storage required by a guest that ultimately appears as a mounted filesystem inside that guest.

It deliberately excludes arbitrary application services.

A mountable resource may be represented to the guest either as:

```text
BLOCK
FILESYSTEM
```

The resource identifier distinguishes independent resources even when their classifications are otherwise identical.

For example:

```yaml
mountable_resources:
  items:

    application-data:
      storage_class: PERSISTENT
      purpose: DATA
      representation: BLOCK
      access: RW
      sharing: EXCLUSIVE
      mount_point: /storage/data

    transaction-log:
      storage_class: PERSISTENT
      purpose: DATA
      representation: BLOCK
      access: RW
      sharing: EXCLUSIVE
      mount_point: /storage/transaction-log
```

These are distinct resources and can therefore be placed independently.

---

## MountableResource Dimensions

### StorageClass

`StorageClass` expresses the abstract storage service expected by the workload.

Current values are:

```text
DISPOSABLE
PERSISTENT
ARCHIVE
```

#### DISPOSABLE

Storage whose loss is acceptable because its content can be rebuilt, regenerated, or downloaded again.

Typical examples:

- reproducible guest root disks,
- temporary build data,
- inexpensive caches.

#### PERSISTENT

Normal operational storage that must survive guest recreation and ordinary failures according to the host's persistent-storage policy.

Typical examples:

- databases,
- application state,
- working data,
- expensive reusable caches.

#### ARCHIVE

Capacity-oriented persistent storage for colder or long-lived data where lower performance may be acceptable.

Typical examples:

- media,
- large datasets,
- archival application data,
- local or remote backup repositories.

`StorageClass` is not a concrete backend. For example, `PERSISTENT` might be NVMe RAID1 on one host and SAN-backed LVM on another.

---

### Purpose

`Purpose` describes what a resource is for.

Current values are:

```text
SYSTEM
DATA
CACHE
BACKUP
```

- `SYSTEM` — guest operating-system or machine state, such as a root filesystem,
- `DATA` — primary application or user data,
- `CACHE` — reusable data that avoids repeated downloads or computation,
- `BACKUP` — recoverable copies of other data.

Purpose is independent of StorageClass.

For example:

```text
DISPOSABLE + CACHE
PERSISTENT + CACHE
ARCHIVE + DATA
ARCHIVE + BACKUP
```

are all meaningful combinations.

---

### Representation

Current representations are:

```text
BLOCK
FILESYSTEM
```

#### BLOCK

The guest receives a block device and mounts a filesystem from it.

Host-side details such as:

```text
QCOW2
LVM
RAW_FILE
virtio-blk
virtio-scsi
```

are implementation details rather than guest-level representation values.

#### FILESYSTEM

The guest receives a filesystem/share that can be mounted directly.

Possible guest-visible interfaces currently include:

```text
SAMBA
NFS
VIRTIOFS
```

Arbitrary services are intentionally not `MountableResource`s. For example, an HTTP Nix binary cache is a service and would belong to a future service-dependency model rather than being represented as a `FILESYSTEM` resource.

---

### Access

`access` is mandatory and describes the relationship between one guest and one resource.

Current values are:

```text
RO
RW
```

- `RO` — the guest must not be able to modify the resource through the selected interface,
- `RW` — the guest may modify it.

Access is not an immutable property of shared backing.

The same `SharedMountableResourceConfiguration` can therefore be consumed by one guest as `RW` and another as `RO`.

---

### Sharing

`sharing` is mandatory.

Current values are:

```text
EXCLUSIVE
SHARED
```

#### EXCLUSIVE

The backing resource must not be concurrently used by another consumer in a way that violates exclusivity.

An `EXCLUSIVE` guest resource is normally realized directly by its `GuestDeploymentConfiguration`.

#### SHARED

The resource is intentionally shared with other consumers.

The selected representation, interface, and backend must safely support the requested concurrent usage.

A `SHARED` guest resource is bound to a separately defined `SharedMountableResourceConfiguration`.

There is deliberately no `EITHER` mode. Sharing semantics are part of the guest contract and are not selected arbitrarily by the resolver.

---

### Interface

A guest-visible interface is relevant to `FILESYSTEM` representation.

Current interface types are:

```text
SAMBA
NFS
VIRTIOFS
```

Normally the guest specifies only:

```yaml
representation: FILESYSTEM
```

and the resolver chooses a concrete interface supported by the host.

A guest may optionally require a specific interface if it genuinely cannot operate through alternatives.

The selected interface affects both sides of the deployment contract. For example, resolving a filesystem resource to NFS implies:

```text
host
    configure/export NFS filesystem
    configure relevant network/firewall access

guest
    configure NFS mount
```

For `BLOCK`, guest-visible hypervisor transports such as virtio-blk or virtio-scsi are intentionally treated as implementation details rather than `MountableResourceInterfaceType`s.

---

### Backend

A backend describes how the host physically realizes a resource.

Current backend types are:

```text
BLOCK:
    QCOW2
    RAW_FILE
    LVM

FILESYSTEM:
    DIRECTORY
```

Backend configuration is host-side information and normally does not belong in reusable `GuestConfiguration`.

Each backend carries type-specific host configuration. For example:

```yaml
type: QCOW2
directory: /srv/libvirt/PERSISTENT/qemu/images
```

or:

```yaml
type: LVM
volume_group: VG_NVME_RAID1
```

There is deliberately no generic backend `root` property because path semantics differ by backend type.

---

## HostStorageTarget

A `HostStorageTarget` is a concrete placement target offered by a deployment host.

It is distinct from `StorageClass`:

```text
StorageClass
    abstract guest requirement

HostStorageTarget
    concrete capability offered by a host

MountableResource
    logical guest resource
```

A host may provide multiple targets implementing the same storage class.

A target currently declares:

- `storage_class`,
- `storage_system`,
- optional `impacted_devices`,
- optional `impacted_controllers`,
- supported representations,
- supported backends for each representation.

Example conceptually:

```yaml
storage_targets:

  persistent-nvme:
    storage_class: PERSISTENT
    storage_system: HOST_LOCAL_STORAGE
    impacted_devices:
      - nvme-a
      - nvme-b
      - nvme-persistent-raid1
    impacted_controllers:
      - nvme-controller
    supported_representations:
      - type: BLOCK
        supported_backends:
          - type: QCOW2
            directory: /srv/libvirt/PERSISTENT/qemu/images
          - type: LVM
            volume_group: VG_NVME_RAID1
```

A missing `impacted_devices` or `impacted_controllers` property means **unknown topology**, not an empty dependency set.

That distinction matters for `REQUIRED` placement relations: a requirement must be provably satisfied.

---

## Storage Systems and Physical Independence

Placement independence is modeled through several distinct kinds of shared dependency:

```text
DEVICE
CONTROLLER
STORAGE_SYSTEM
HOST
SITE
```

### HOST_LOCAL_STORAGE

For ordinary local host storage:

```yaml
storage_system: HOST_LOCAL_STORAGE
```

is sufficient.

No corresponding environment storage-system definition is required.

The resolver expands it to an implicit identity unique to the deployment host. Consequently, two different local targets on the same host may have different devices and controllers but still share:

```text
STORAGE_SYSTEM
HOST
SITE
```

For example, local NVMe and local SATA may satisfy:

```text
NO_SHARED_DEVICE
NO_SHARED_CONTROLLER
```

while failing:

```text
NO_SHARED_STORAGE_SYSTEM
NO_SHARED_HOST
NO_SHARED_SITE
```

### External StorageSystem

External systems such as a NAS or SAN are declared in `DeploymentEnvironmentConfiguration`.

This enables distinctions such as:

```text
primary data on host-local storage
backup on NAS at same site

NO_SHARED_STORAGE_SYSTEM   satisfied
NO_SHARED_HOST             satisfied
NO_SHARED_SITE             not satisfied
```

and:

```text
primary data on host-local storage
backup on remote NAS

NO_SHARED_STORAGE_SYSTEM   satisfied
NO_SHARED_HOST             satisfied
NO_SHARED_SITE             satisfied
```

---

## Placement Relations

Placement requirements are business requirements of a guest and belong to `GuestConfiguration`.

They are stored under:

```yaml
mountable_resources:
  items:
    ...
  relations:
    ...
```

A relation may contain two or more resource identifiers.

Example:

```yaml
relations:

  - description: >
      Prefer independent I/O paths for application data and transaction log.
    mountable_resources:
      - application-data
      - transaction-log
    relations:
      - NO_SHARED_DEVICE
      - NO_SHARED_CONTROLLER
    requirement: PREFERRED
```

Current relation types are:

```text
NO_SHARED_DEVICE
NO_SHARED_CONTROLLER
NO_SHARED_STORAGE_SYSTEM
NO_SHARED_HOST
NO_SHARED_SITE
```

### NO_SHARED_DEVICE

The resolved targets must have no common identifiers in their `impacted_devices` sets.

### NO_SHARED_CONTROLLER

The resolved targets must have no common identifiers in their `impacted_controllers` sets.

### NO_SHARED_STORAGE_SYSTEM

The resources must not use the same storage system.

`HOST_LOCAL_STORAGE` is expanded to an implicit storage-system identity unique to its host.

### NO_SHARED_HOST

The backing storage systems must not depend on the same physical host or appliance.

Host-local storage depends on the deployment host itself. External storage-system dependencies are resolved through the environment.

### NO_SHARED_SITE

The backing storage systems must not depend on the same physical site.

Host-local storage inherits the deployment host's site. External storage-system dependencies are resolved through the environment.

### Requirement

Current enforcement levels are:

```text
REQUIRED
PREFERRED
```

- `REQUIRED` — deployment fails if the resolver cannot prove the relation is satisfied,
- `PREFERRED` — the resolver should prefer satisfying placement but may continue with an explicit warning if it cannot.

Relations containing more than two resources are evaluated pairwise across the complete group.

---

## Network Model

`GuestConfiguration` declares named logical network interfaces without binding
them to host-specific networks.

Example:

```yaml
network_interfaces:
  items:
    primary:
      description: Primary application network.
      required: true
    management:
      description: Optional management network.
      required: false
```

`GuestDeploymentConfiguration` binds those interfaces to concrete host networks
and assigns IPv4 and/or IPv6 addresses.

```yaml
network_interfaces:
  items:
    management:
      host_network: private-management
      ipv4: 172.27.130.50
```

Network services use three reusable common structures:

```text
NetworkServiceBinding
    application_protocol
    transport_protocol
    port

NetworkServiceEndpoint
    service_binding
    address

NetworkServiceInterfaceBinding
    service_binding
    network_interface
    address_family (optional)
```

`application_protocol` is an extensible symbolic identifier rather than a closed
enum. `transport_protocol` is explicit (`TCP`, `UDP` or `SCTP`) and `port` is also
explicit. Tooling may suggest conventional values such as SSH/TCP/22, but those
values remain visible configuration data. This also gives the execution layer
enough transport information to derive firewall requirements without encoding
firewall implementation details in guest configuration.

A deployment host has a concrete endpoint because the control node must know how
to reach it:

```yaml
management_endpoint:
  service_binding:
    application_protocol: SSH
    transport_protocol: TCP
    port: 22
  address: 192.0.2.10
```

A guest deployment instead binds its management service to a logical guest
interface so the IP address is not duplicated:

```yaml
management_endpoint_interface_binding:
  service_binding:
    application_protocol: SSH
    transport_protocol: TCP
    port: 22
  network_interface: management
  address_family: IPV4
```

The resolver combines the interface binding with the resolved interface address
and writes a concrete endpoint to the DeploymentPlan:

```yaml
resolved_management_endpoint:
  service_binding:
    application_protocol: SSH
    transport_protocol: TCP
    port: 22
  address: 172.27.130.50
```

`address_family` may be omitted when the selected interface has an address in
exactly one IP family. A dual-stack interface requires `IPV4` or `IPV6` explicitly
so the resolver never guesses which management address to use.

The intended execution topology is that the Ansible control node reaches the
deployment host through `HostConfiguration.management_endpoint`; guest-side
management (for example a NixOS update over SSH) is then performed through/from
that deployment host. The guest management network therefore need not be routed
or exposed to the control node or other external systems.

Host networks may be IPv4-only, IPv6-only or dual-stack. Network implementation
details such as libvirt bridge names and network mode remain in
`HostConfiguration`.

---

## Shared Mountable Resources

A shared backing resource has its own configuration and lifecycle.

Example conceptually:

```yaml
shared_mountable_resource:
  id: shared-gradle-cache

storage_class: DISPOSABLE
representation: FILESYSTEM

host:
  reference: example-host
  reference_config_version: "1.0"
host_storage_target: disposable-nvme
backend: DIRECTORY
host_mountable_resource_interface: nfs-vm
```

A consumer guest may declare:

```yaml
gradle-cache:
  storage_class: DISPOSABLE
  purpose: CACHE
  representation: FILESYSTEM
  access: RO
  sharing: SHARED
  mount_point: /storage/cache/gradle
```

while a cache-management guest may declare the same logical shared backing with:

```yaml
access: RW
sharing: SHARED
```

Their deployment configurations both bind to:

```yaml
shared_mountable_resource:
  reference: shared-gradle-cache
  reference_config_version: "1.0"
```

This keeps:

```text
guest requirement
shared backing identity
shared backing lifecycle
guest-specific access
```

as separate concepts.

---

## Placement Resolution

The deployment resolver combines the applicable configurations and produces a `DeploymentPlan`.

The conceptual phases are:

```text
1. Validate configuration structure and cross-file references
2. Resolve environment and host topology
3. Validate guest requirements against deployment values
4. Resolve direct and shared MountableResource bindings
5. Discover compatible HostStorageTarget/backend/interface candidates
6. Apply explicit deployment choices
7. Eliminate candidates violating REQUIRED relations
8. Search remaining placement combinations
9. Prefer combinations satisfying PREFERRED relations
10. Resolve concrete interfaces and backends
11. Generate DeploymentPlan
```

If a host cannot satisfy a `REQUIRED` relation, deployment must fail explicitly rather than silently weaken the guest requirement.

If a `PREFERRED` relation cannot be satisfied, deployment may continue but the resulting plan must record the unsatisfied preference.

A straightforward backtracking/search implementation is sufficient initially. The declarative configuration model must remain independent of the internal solving algorithm so that a different constraint solver can replace it later.

---

## Ansible Integration

Ansible is the host-side orchestration and execution layer, not the implementation language of deployment placement logic.

The core resolver should be ordinary testable code, initially expected to be Python.

Conceptually:

```python
def resolve_deployment(
    environment_configuration,
    host_configuration,
    guest_configuration,
    shared_mountable_resource_configurations,
    guest_deployment_configuration,
):
    ...
    return deployment_plan
```

The resolver should avoid unnecessary Ansible dependencies.

Ansible integration can be provided through an Algites Ansible Collection. When planning and execution are separated, a `DeploymentBundle` is the preferred transport boundary because it carries both resolved plans and all required entity-owned files to the control node. Direct Python API integration can still be used when the Orchestrator and Ansible share the same source configuration repository.

The resolved plan from each bundle deployment can then be applied through ordinary idempotent roles, for example:

```text
DeploymentPlan
    ├── storage realization
    ├── libvirt domain configuration
    ├── network configuration
    ├── firewall configuration
    ├── filesystem export configuration
    └── guest configuration/deployment
```

Typical execution responsibilities include:

- creation of QCOW2 images or LVM volumes,
- creation of directories for filesystem resources,
- generation/application of libvirt domains,
- creation of libvirt networks,
- firewall/NAT configuration,
- NFS or Samba exports,
- permissions,
- generated guest deployment configuration,
- NixOS installation/update.

The execution layer should not independently reinterpret placement business rules already resolved into `DeploymentPlan`.

---

## NixOS Guest Integration

For NixOS guests, software dependencies and operating-system configuration belong to the guest definition itself.

Conceptually:

```text
guests/
└── codex/
    └── 1.0/
        ├── codex_1.0.yml
        └── nixos/
            ├── default.nix
            ├── packages.nix
            ├── services.nix
            └── ...
```

The guest YAML declares only `os.type: NIXOS`; the `nixos/` path is a framework
convention and is not repeated in YAML. The same convention applies to hosts.
For Debian, `os.type: DEBIAN` selects `debian/`. A Debian implementation may
contain `debian/apt/packages.list`, one APT package selection per non-comment
line; the future execution layer will install missing listed packages and upgrade
listed installed packages to newer configured candidate versions.

For example, packages remain authoritative in Nix:

```nix
environment.systemPackages = with pkgs; [
  git
  gradle
  temurin-bin-17
];
```

Deployment-specific information is generated from `DeploymentPlan`.

Examples include:

- host name,
- IPv4/IPv6 addresses,
- resolved NFS/Samba endpoints,
- read-only/read-write mount options,
- filesystem mount points,
- block-device/mount configuration.

Conceptually:

```text
Reusable guest NixOS configuration
            +
Generated deployment configuration
            ↓
Concrete deployed NixOS guest
```

This allows one reusable guest definition to be deployed repeatedly to different hosts.

---

## Host and Guest Responsibilities

The virtualization host should remain focused on infrastructure responsibilities whenever practical.

Typical host responsibilities:

```text
QEMU/KVM/libvirt
storage
networking
firewall
filesystem transport/export
orchestration runtime
host monitoring
```

Application-specific work should normally remain in guests.

For example, a cache-management guest may have `RW` access to a shared Gradle cache while consumer guests have `RO` access. The host provides storage and transport but does not need to run Gradle or perform dependency downloads itself.

---

## Storage and Backup Model

The current abstract storage classes are:

```text
DISPOSABLE
PERSISTENT
ARCHIVE
```

Typical usage:

```text
DISPOSABLE
    reproducible root disks
    build output
    inexpensive/rebuildable caches

PERSISTENT
    databases
    application state
    working data
    expensive caches

ARCHIVE
    high-capacity application data
    media
    long-lived datasets
    backup repositories
```

`ARCHIVE` may contain both operational archival data and backups. `Purpose` distinguishes, for example:

```text
ARCHIVE + DATA
ARCHIVE + BACKUP
```

A backup is not considered independent merely because it has `purpose: BACKUP`.

Required independence from primary data is expressed explicitly with placement relations such as:

```text
NO_SHARED_STORAGE_SYSTEM
NO_SHARED_HOST
NO_SHARED_SITE
```

Application-consistent backup behavior for databases is a separate operational concern and should not be approximated by blindly copying live block images.

---

## Shared Caches

Shared caches use ordinary `MountableResource` semantics plus an independently defined `SharedMountableResourceConfiguration`.

For example, a Gradle dependency cache can be:

```text
StorageClass:    DISPOSABLE
Purpose:         CACHE
Representation:  FILESYSTEM
Sharing:         SHARED
```

while a more expensive filesystem cache can use:

```text
StorageClass:    PERSISTENT
Purpose:         CACHE
Representation:  FILESYSTEM
Sharing:         SHARED
```

A writer/cache-management guest may use `RW`; consumers may use `RO`.

An HTTP Nix binary cache is not modeled as a `MountableResource`, because it is a service rather than a mounted filesystem. A future service-dependency model may represent such infrastructure services.

Directly sharing `/nix/store` between guests is not the intended Nix caching model.

---

## Model Files

The Deployment model is defined by JSON Schema documents written in YAML syntax.

Conceptually:

```text
orchestrator/deployment/
├── README.md
├── model/
│   ├── model.yml
│   ├── common.schema.yml
│   ├── deployment-environment-configuration.schema.yml
│   ├── host-configuration.schema.yml
│   ├── guest-configuration.schema.yml
│   ├── service-configuration.schema.yml
│   ├── shared-mountable-resource-configuration.schema.yml
│   ├── guest-deployment-configuration.schema.yml
│   ├── deployment-plan.schema.yml
│   ├── deployment-bundle-manifest.schema.yml
│   ├── common.xsd
│   ├── deployment-environment-configuration.xsd
│   ├── host-configuration.xsd
│   ├── guest-configuration.xsd
│   ├── service-configuration.xsd
│   ├── shared-mountable-resource-configuration.xsd
│   ├── guest-deployment-configuration.xsd
│   ├── deployment-plan.xsd
│   ├── deployment-bundle-manifest.xsd
│   └── validation-report.xsd
├── config/
│   ├── environments/
│   ├── hosts/
│   ├── guests/
│   ├── services/
│   ├── shared-mountable-resources/
│   └── deployments/
└── example-plans/
```

The JSON Schemas are the authoritative machine-readable definition of the YAML/JSON object shape. The XSD 1.0 files are the companion XML schema layer for the same structures. XSD 1.0 is intentionally used for broad tool compatibility; identifier-keyed dynamic maps are validated less strictly by XSD and receive their full semantic validation from the Orchestrator validator. This README explains the intended architecture and semantics.

---

## CLI

The current Deployment CLI provides:

```bash
algites-orchestrator create-deployment-plan    # cdp
algites-orchestrator create-deployment-bundle  # cdb
algites-orchestrator validate-configuration    # vc
```

`cdp` creates one resolved DeploymentPlan in YAML, JSON or XML. `cdb` creates a
portable ZIP containing one or more plans plus the complete Configuration Entity
Packages required by each plan. `vc` validates the full configuration repository
or one deployment closure. See the repository-level `CLI.md` for the authoritative
CLI contract, package-discovery rules and DeploymentBundle layout.

---

## Development

The initial Deployment resolver is expected to be implemented as normal Python code and integrated with Ansible through a thin adapter/collection layer.

Likely implementation areas include:

```text
model
validation
resolver
placement
errors
execution adapters
```

Core model validation and resolution should be directly unit-testable without requiring an Ansible runtime.

---

## Future Deployment Capabilities

The current model intentionally leaves room for future deployment capabilities without prematurely encoding them into version 1.

Potential areas include:

- automatic host selection,
- migration between hosts,
- resource-capacity-aware scheduling,
- richer placement constraints,
- declarative backup policy,
- additional shared-resource types,
- service dependencies and service exports,
- remote storage backends,
- multiple hypervisor implementations,
- deployment lifecycle management,
- generated deployment diffs,
- dry-run/planning output,
- destroy/undeploy operations,
- nested virtualization,
- infrastructure-service guests such as cache, backup, monitoring, or build services.

Future capabilities should be added without weakening the separation between reusable guest requirements, physical environment topology, host capabilities, shared resource lifecycle, concrete deployment bindings, and resolved execution plans.

---

## Command-line interface

The Deployment resolver is exposed through the reusable Python package and the
`algites-orchestrator` command. The complete command, configuration-discovery,
namespace, stream, logging and exit-code contract is documented in the repository
root [`CLI.md`](../../CLI.md).

Typical source-tree usage:

```bash
python3 -m orchestrator cdp -cr=examples/config -d=example-guest-deployment@1.0
python3 -m orchestrator vc -cr=examples/config
```
