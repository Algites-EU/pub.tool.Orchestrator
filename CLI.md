# Algites Orchestrator CLI

This document defines the command-line contract of Algites Orchestrator, the
configuration discovery rules used by the Deployment domain, and the portable
`DeploymentBundle` format.

During initial development the deployment model remains at `model_version: 1`.
The changes described here refine the unreleased version-1 model and do not
introduce a new model version.

## 1. Executable and command aliases

The executable is:

```bash
algites-orchestrator
```

Every command has one descriptive long form and one explicit short alias. Both
forms execute the same implementation.

| Long command | Short alias | Purpose |
|---|---|---|
| `create-deployment-plan` | `cdp` | Resolve one guest deployment and serialize one `DeploymentPlan`. |
| `create-deployment-bundle` | `cdb` | Create a portable ZIP containing one or more plans plus all Configuration Entity Packages required by each plan. |
| `validate-configuration` | `vc` | Validate the complete configuration root or one deployment closure. |

Examples:

```bash
algites-orchestrator create-deployment-plan --deployment=production/main
algites-orchestrator cdp -d=production/main

algites-orchestrator create-deployment-bundle -d=production/main -ofn=production.zip
algites-orchestrator cdb -d=production/main -ofn=production.zip

algites-orchestrator validate-configuration
algites-orchestrator vc
```

## 2. Long and short option forms

Every CLI option has an explicit long and short form. Multi-character short
options such as `-cr`, `-ofn` or `-pifn` are single options; they are not groups
of POSIX single-character flags.

Both assignment and separated-value forms are supported:

```bash
--config-root=/srv/algites/config
--config-root /srv/algites/config
-cr=/srv/algites/config
-cr /srv/algites/config
```

Aliases are defined explicitly rather than calculated automatically so future
configuration categories cannot create accidental alias collisions.

## 3. Commands

### 3.1 `create-deployment-plan` / `cdp`

Syntax:

```bash
algites-orchestrator create-deployment-plan [options] --deployment=<reference>
algites-orchestrator cdp [options] -d=<reference>
```

Exactly one deployment reference is accepted. It may be an unqualified id or an
exact category-relative reference.

Examples:

```bash
algites-orchestrator cdp \
  -cr=/srv/algites/config \
  -d=production/main

algites-orchestrator cdp \
  -cr=/srv/algites/config \
  -d=production/main \
  -of=/tmp/run-001 \
  -ofn=deployment-plan.xml \
  -ofmt=xml
```

The command:

1. resolves the requested `GuestDeploymentConfiguration`,
2. resolves its referenced `GuestConfiguration`, `HostConfiguration` and
   `DeploymentEnvironmentConfiguration`,
3. resolves referenced `SharedMountableResourceConfiguration` entities,
4. validates every loaded configuration against its JSON Schema,
5. validates cross-configuration constraints,
6. validates package-relative guest OS configuration paths,
7. resolves compute, networks, storage targets, backends and filesystem
   interfaces,
8. evaluates mountable-resource relations,
9. creates one `DeploymentPlan`,
10. validates that plan against `deployment-plan.schema.yml`,
11. serializes it as YAML, JSON or XML.

A `REQUIRED` relation that cannot be proven causes resolution to fail. An
unsatisfied `PREFERRED` relation is retained in the plan with `satisfied: false`
and is emitted as a warning.

`DeploymentPlan` is intentionally a single resolved data document. It does not
contain the physical attachment files owned by the involved configuration
entities. Use `create-deployment-bundle` when a portable execution artifact is
required.

The plan records the canonical environment and the resolved guest OS contract,
for example:

```yaml
environment: example-environment
resolved_os:
  type: NIXOS
  configuration_path: nixos/
```

`configuration_path` remains relative to the referenced guest Configuration
Entity Package. This keeps an individual plan independent of the absolute path
of the machine on which it was created.

### 3.2 `create-deployment-bundle` / `cdb`

Syntax:

```bash
algites-orchestrator create-deployment-bundle [options] --deployment=<reference> [--deployment=<reference> ...]
algites-orchestrator cdb [options] -d=<reference> [-d=<reference> ...]
```

`--deployment` / `-d` is repeatable. One bundle can therefore contain one or
more deployments:

```bash
algites-orchestrator cdb \
  -cr=/srv/algites/config \
  -d=production/app01 \
  -d=production/app02 \
  -d=infrastructure/cache01 \
  -ofn=production.zip
```

For every requested deployment, `cdb` calls the same internal deployment
resolver used by `cdp`; it does not invoke the CLI command as a subprocess and
does not duplicate deployment business logic.

For each generated plan the builder records the exact configuration dependency
closure accessed while resolving that plan and copies the complete
Configuration Entity Package for every dependency into that deployment's bundle
subtree.

The outer `cdb` result is always a ZIP archive. `--output-format` determines the
format of the structured files *inside* the ZIP:

```text
--output-format=yaml -> manifest.yml and *_deployment-plan.yml
--output-format=json -> manifest.json and *_deployment-plan.json
--output-format=xml  -> manifest.xml and *_deployment-plan.xml
```

The same format is used for the bundle manifest and all DeploymentPlan files in
one bundle. Configuration Entity Package attachments are copied byte-for-byte in
their original source formats; Nix, YAML, scripts, templates and other payload
files are not converted merely because the plan format is XML or JSON.

The same deployment reference may not be specified twice in one invocation.

### 3.3 `validate-configuration` / `vc`

Without `--deployment`, the complete configuration root is validated:

```bash
algites-orchestrator vc -cr=/srv/algites/config
```

Full validation checks:

- Configuration Entity Package layout,
- `.yml` configuration-definition naming,
- package-directory / file-base-name / entity-id invariants,
- JSON Schemas,
- cross-file references,
- package-relative guest OS paths,
- resolvability of every deployment.

With `--deployment`, validation is limited to the configuration closure required
by that deployment:

```bash
algites-orchestrator vc \
  -cr=/srv/algites/config \
  -d=production/main
```

Unrelated entity definitions are not parsed by closure validation. Discovery
still indexes their package identities, so unqualified references can correctly
report ambiguity.

The command produces a machine-readable validation report in YAML, JSON or XML.
Callers that only need success/failure should use the exit code.

## 4. Common options

| Long option | Short alias | Default | Meaning |
|---|---|---:|---|
| `--config-root` | `-cr` | `.` | Root directory containing configuration-category folders. |
| `--config-folder-deployments-name` | `-cfdn` | `deployments` | Deployment configuration folder below config root. |
| `--config-folder-environments-name` | `-cfen` | `environments` | Environment configuration folder below config root. |
| `--config-folder-guests-name` | `-cfgn` | `guests` | Guest configuration folder below config root. |
| `--config-folder-hosts-name` | `-cfhn` | `hosts` | Host configuration folder below config root. |
| `--config-folder-shared-mountable-resources-name` | `-cfsmrn` | `shared-mountable-resources` | Shared mountable-resource configuration folder below config root. |
| `--output-folder` | `-of` | current directory | Base directory for relative result and processing-info paths. |
| `--output-file-name` | `-ofn` | none | Result file. If omitted, the result is written to stdout. |
| `--processing-info-file-name` | `-pifn` | none | Optional persistent copy of the diagnostic stream. |
| `--output-format` | `-ofmt` | `yaml` | Structured serialization: `yaml`, `json` or `xml`. For `cdb`, this controls the manifest and plans inside the ZIP. |
| `--log-level` | `-ll` | `INFO` | Diagnostic threshold: `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `--verbose` | `-vb` | off | Equivalent to `--log-level=DEBUG`. |
| `--quiet` | `-q` | off | Equivalent to `--log-level=ERROR`. |
| `--help` | `-h` | — | Show command help. |
| `--version` | `-v` | — | Show Orchestrator version. |

`--log-level`, `--verbose` and `--quiet` are mutually exclusive. There is
intentionally no `OFF` log level; errors remain visible unless stderr is
explicitly redirected or discarded by the caller.

## 5. Configuration Entity Packages

Every top-level configuration entity is represented by a directory package, not
by a loose YAML file.

The invariant is:

```text
<entity-id>/
├── <entity-id>.yml
└── ... zero or more entity-owned attachment files/directories ...
```

The package directory name, YAML file base name and stable entity `id` must all
be identical.

Example:

```text
config/
├── deployments/
│   ├── production/
│   │   └── main/
│   │       ├── main.yml
│   │       └── templates/
│   └── testing/
│       └── test01/
│           └── test01.yml
├── environments/
│   └── dc01/
│       └── dc01.yml
├── hosts/
│   ├── site01/
│   │   ├── hostA/
│   │   │   ├── hostA.yml
│   │   │   └── scripts/
│   │   └── hostB/
│   │       └── hostB.yml
│   └── site02/
│       └── hostA/
│           └── hostA.yml
├── guests/
│   └── development/
│       └── codex/
│           ├── codex.yml
│           └── nixos/
│               ├── default.nix
│               ├── packages.nix
│               └── services.nix
└── shared-mountable-resources/
    └── cache/
        └── cache.yml
```

A directory `X` is recognized as a Configuration Entity Package when it directly
contains `X.yml`. Once discovered, the complete subtree below that directory is
owned by the entity and is **not** recursively scanned for additional
Orchestrator entities. This allows arbitrary future attachment trees such as
NixOS modules, templates, scripts and auxiliary YAML files.

Directories that do not contain a same-named `.yml` definition are namespaces.

Loose configuration YAML files outside a Configuration Entity Package are
invalid. The `.yaml` spelling is not accepted for the entity-definition file.

Category folder options are relative paths below `--config-root`. Absolute
category-folder paths and `.` / `..` components are rejected. Entity definitions
reached through symlinks must still resolve below the corresponding category
root.

## 6. Package-relative attachments

An entity may refer to files or directories owned by its own package.

For example a NixOS guest can contain:

```text
guests/development/codex/
├── codex.yml
└── nixos/
    ├── default.nix
    └── services.nix
```

with:

```yaml
os:
  type: NIXOS
  configuration_path: nixos/
```

Package-relative paths:

- use `/`,
- may not be absolute,
- may not contain `.` or `..` components,
- may not escape the Configuration Entity Package,
- must exist when referenced by the current model.

A DeploymentBundle copies the entire entity package, not only the explicitly
referenced path. This makes the bundle forward-compatible with additional
entity-owned deployment inputs.

## 7. Configuration references and namespaces

Cross-file references use `ConfigurationReference`, separate from the stable
entity `Identifier`.

### 7.1 Exact qualified reference

```yaml
host: site01/hostA
```

This resolves only to the entity package:

```text
<config-root>/<hosts-folder>/site01/hostA/hostA.yml
```

If that package does not exist, resolution fails. There is no fuzzy fallback.

### 7.2 Unqualified reference

```yaml
host: hostA
```

The complete category tree is indexed by entity package id.

Resolution rules are deterministic:

```text
0 matches  -> unresolved reference error
1 match    -> use that entity package
2+ matches -> ambiguous reference error
```

For example:

```text
hosts/site01/hostA/hostA.yml
hosts/site02/hostA/hostA.yml
```

makes `host: hostA` ambiguous while `host: site01/hostA` resolves exactly.

This rule applies uniformly to deployments, environments, hosts, guests and
shared mountable resources.

### 7.3 Reference syntax restrictions

Configuration references are logical category-relative paths, not arbitrary
filesystem paths. They:

- use `/` as separator,
- are case-sensitive,
- cannot start with `/`,
- cannot contain `.` or `..` components,
- cannot escape their configuration category.

Generated plans store canonical category-relative references so their entity
identities remain unambiguous.

## 8. DeploymentPlan

A `DeploymentPlan` is the resolved data model for one concrete guest deployment.
It represents the resolved combination of the deployment, guest, host,
environment and any referenced shared resources.

It remains intentionally independent from the physical location of the source
configuration repository.

A plan includes, among other data:

```text
model_version
deployment
guest
host
environment
resolved_os
resolved_compute
resolved_network_interfaces
resolved_mountable_resources
relation_results
warnings
```

A plan can be generated and inspected independently with `cdp`; attachment files
are not embedded in this document.

## 9. DeploymentBundle

A `DeploymentBundle` is the portable execution artifact produced by `cdb`.

It is a ZIP archive with this root:

```text
deployment-bundle/
```

For a deployment reference:

```text
aaa/bbb/my-guest-deployment
```

the YAML variant is conceptually:

```text
deployment-bundle/
├── manifest.yml
└── deployments/
    └── aaa/
        └── bbb/
            └── my-guest-deployment/
                ├── my-guest-deployment_deployment-plan.yml
                ├── environment/
                │   └── <canonical-environment-reference>/
                │       ├── <environment-id>.yml
                │       └── ... attachments ...
                ├── host/
                │   └── <canonical-host-reference>/
                │       ├── <host-id>.yml
                │       └── ... attachments ...
                ├── guest/
                │   └── <canonical-guest-reference>/
                │       ├── <guest-id>.yml
                │       ├── nixos/
                │       └── ...
                ├── guest-deployment/
                │   └── aaa/bbb/my-guest-deployment/
                │       ├── my-guest-deployment.yml
                │       └── ... attachments ...
                └── shared-mountable-resource/
                    └── <canonical-resource-reference>/
                        ├── <resource-id>.yml
                        └── ... attachments ...
```

The exact set of copied package categories is derived from the transitive
configuration dependency closure actually accessed while resolving the plan.
This also covers shared resources whose backing is located on another host or in
another environment. Physical sites are currently nested entities of
`DeploymentEnvironmentConfiguration`, so their source data travels inside the
`environment/` package. If sites later become independent configuration entities,
the same dependency-closure mechanism can add their packages without changing
the bundle principle.

Every `deployments/<reference>/` subtree is self-contained. If multiple plans
use the same host, guest or other dependency, that package is deliberately
copied into every affected deployment subtree. The duplication is intentional:
a single deployment directory can be extracted and processed independently.

Current version 1 creates guest deployment plans only. A future host-deployment
plan can use the same bundle concept with a different dependency closure; host
deployment is not implemented yet.

## 10. Bundle manifest

The bundle root contains one manifest in the same structured format as the
plans. YAML example:

```yaml
bundle_version: 1
model_version: 1
deployment_plan_format: yaml
deployments:
  - id: my-guest-deployment
    reference: aaa/bbb/my-guest-deployment
    deployment_plan: deployments/aaa/bbb/my-guest-deployment/my-guest-deployment_deployment-plan.yml
    attachments:
      - category: deployments
        reference: aaa/bbb/my-guest-deployment
        path: deployments/aaa/bbb/my-guest-deployment/guest-deployment/aaa/bbb/my-guest-deployment
      - category: guests
        reference: development/codex
        path: deployments/aaa/bbb/my-guest-deployment/guest/development/codex
```

All manifest paths are relative to `deployment-bundle/` and therefore remain
valid after the ZIP is moved to another machine or extracted below an arbitrary
control-node directory.

The manifest is validated against
`deployment-bundle-manifest.schema.yml` before it is serialized.

## 11. YAML, JSON and XML serialization

Structured outputs support three formats:

```bash
algites-orchestrator cdp ... --output-format=yaml
algites-orchestrator cdp ... --output-format=json
algites-orchestrator cdp ... --output-format=xml
```

YAML is the default.

The resolver always produces one Python object model first. YAML, JSON and XML
are serialization adapters over that same resolved structure; placement and
validation logic are not format-specific.

The XML representation follows a deterministic direct mapping:

- an object property becomes an XML element with the same name,
- an object keyed by an Orchestrator `Identifier` uses that identifier as the
  child element name,
- array values are represented by repeated `<item>` elements,
- booleans are serialized as `true` / `false`,
- scalar values are serialized as element text.

For example:

```yaml
resolved_compute:
  cpu: 4
  memory: 8GiB
```

becomes:

```xml
<resolved_compute>
  <cpu>4</cpu>
  <memory>8GiB</memory>
</resolved_compute>
```

The model ships an XSD 1.0 companion schema set for all deployment-model
structures:

```text
orchestrator/deployment/model/common.xsd
orchestrator/deployment/model/deployment-environment-configuration.xsd
orchestrator/deployment/model/host-configuration.xsd
orchestrator/deployment/model/guest-configuration.xsd
orchestrator/deployment/model/shared-mountable-resource-configuration.xsd
orchestrator/deployment/model/guest-deployment-configuration.xsd
orchestrator/deployment/model/deployment-plan.xsd
orchestrator/deployment/model/deployment-bundle-manifest.xsd
orchestrator/deployment/model/validation-report.xsd
```

The XSD files use the same deterministic XML representation as CLI XML output.
Input configuration remains YAML-based in model version 1; configuration XSDs
are companion XML schemas for tooling, analysis and interchange rather than an
alternative CLI configuration-input syntax.

XSD 1.0 is used deliberately for broad IDE/tool compatibility. Because XSD 1.0
cannot assign a declared complex type to an arbitrary element name used as a
dynamic map key, identifier-keyed map containers are necessarily less strict in
XSD than in the JSON Schemas. Full map-entry, cross-field and cross-entity
semantics are enforced by the Orchestrator validator.

## 12. Result output versus diagnostic output

The CLI uses a strict stream contract:

```text
stdout (1) = command result
stderr (2) = diagnostics / processing information
```

For `cdp` and `vc`, stdout is textual YAML, JSON or XML.

For `cdb`, stdout is a **binary ZIP stream**:

```bash
algites-orchestrator cdb \
  -cr=config \
  -d=production/app01 \
  -d=production/app02 \
  > deployment-bundle.zip \
  2> processing.log
```

Diagnostics include `ERROR`, `WARNING`, `INFO`, `DEBUG` and `TRACE` messages
according to the selected log level. They never contaminate the command-result
stream.

Typical plan piping therefore remains possible:

```bash
algites-orchestrator cdp -cr=config -d=production/main | another-command
```

while a bundle can be redirected or piped to a binary-aware consumer.

## 13. Result file path resolution

`--output-file-name` / `-ofn` may be a simple file name, a relative path or an
absolute path.

```text
absolute output file path
    -> use it directly

relative output file path + output folder
    -> output-folder / relative-output-file-path

relative output file path without output folder
    -> current-working-directory / relative-output-file-path

no output file name
    -> write result to stdout
```

Examples:

```bash
-of=/tmp/run -ofn=plan.yml
# /tmp/run/plan.yml

-of=/tmp/run -ofn=plans/production.xml
# /tmp/run/plans/production.xml

-of=/tmp/run -ofn=/var/lib/algites/production.zip
# /var/lib/algites/production.zip; -of does not alter an absolute path
```

Parent directories required by the requested result path are created
automatically.

For `cdb`, `.zip` is the conventional result extension, but the CLI writes ZIP
content based on the command rather than inferring it from the file name.

## 14. Processing information file

`--processing-info-file-name` / `-pifn` writes a persistent copy of the same
filtered diagnostic stream that is written to stderr. It does **not** replace or
suppress stderr.

```bash
algites-orchestrator cdp \
  -cr=config \
  -d=production/main \
  -pifn=processing.log
```

If the caller wants only the file copy, ordinary shell redirection is used:

```bash
algites-orchestrator cdp ... -pifn=processing.log 2>/dev/null
```

A relative processing-info path follows the same `--output-folder` rule as a
relative result path. An absolute processing-info path ignores
`--output-folder`. The file is replaced for every invocation.

The result file and processing-info file may not resolve to the same path.

## 15. Exit codes

Exit codes are part of the CLI automation contract.

| Code | Meaning |
|---:|---|
| `0` | Success. |
| `1` | Unexpected/general failure. |
| `2` | Invalid CLI arguments. |
| `3` | Invalid configuration or schema/cross-configuration validation failure. |
| `4` | Unresolved configuration reference. |
| `5` | Ambiguous configuration reference. |
| `6` | Result/processing-output write failure. |
| `7` | Deployment resolution failure, for example an unsatisfied `REQUIRED` relation. |
| `130` | Interrupted by the user. |

An error message is written to stderr for non-zero Orchestrator failures unless
the caller explicitly redirects stderr.

## 16. Implementation boundaries

The CLI remains a thin adapter around reusable Python code:

```text
filesystem
    ↓
Configuration Entity Package discovery/index
    ↓
JSON Schema validation
    ↓
reference resolution
    ↓
cross-configuration validation
    ↓
resolved configuration graph
    ↓
deployment resolver
    ↓
DeploymentPlan
    ├── YAML / JSON / XML serializer -> cdp
    └── dependency closure + package copier
             ↓
         DeploymentBundle ZIP -> cdb
```

`cdb` and `cdp` call the same deployment resolver. The bundle builder never
reimplements placement or resolution rules.

The core resolution logic has no Ansible dependency. A DeploymentBundle is the
portable boundary intended for execution on a potentially separate Ansible
control node, while the direct Python API remains available when planning and
execution happen in one process/environment.

## 17. Current source-tree entry points

From a source checkout:

```bash
python3 -m orchestrator cdp -cr=examples/config -d=example-guest-deployment
python3 -m orchestrator cdp -cr=examples/config -d=example-guest-deployment -ofmt=xml
python3 -m orchestrator cdb -cr=examples/config -d=example-guest-deployment -ofn=example.zip
python3 -m orchestrator vc -cr=examples/config
```

After installation as a Python package:

```bash
algites-orchestrator cdp -cr=examples/config -d=example-guest-deployment
```

The package requires Python 3.11 or newer, PyYAML and jsonschema. XML
serialization uses the Python standard library and introduces no additional
runtime dependency.
