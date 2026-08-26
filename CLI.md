# Algites Orchestrator CLI

This document defines the command-line contract of Algites Orchestrator and the
configuration-discovery rules used by the Deployment domain.

During the initial implementation phase the deployment model remains at
`model_version: 1`. The CLI rules described here do not introduce a released
model-version change.

## 1. Executable and command aliases

The executable is:

```bash
algites-orchestrator
```

Every Orchestrator command has one descriptive long form and one explicit short
alias. The aliases are equivalent; they do not select a different execution
path.

| Long command | Short alias | Purpose |
|---|---|---|
| `create-deployment-plan` | `cdp` | Resolve one deployment and generate a `DeploymentPlan`. |
| `validate-configuration` | `vc` | Validate the complete configuration root or one deployment closure. |

Examples:

```bash
algites-orchestrator create-deployment-plan --deployment=production/main
algites-orchestrator cdp -d=production/main

algites-orchestrator validate-configuration
algites-orchestrator vc
```

## 2. Long and short option forms

Every CLI option has an explicit long and short form. Multi-character short
options such as `-cr` or `-ofn` are single options; they are not groups of POSIX
single-character flags.

Both assignment and separated-value forms are supported:

```bash
--config-root=/srv/algites/config
--config-root /srv/algites/config
-cr=/srv/algites/config
-cr /srv/algites/config
```

Aliases are defined explicitly rather than calculated automatically. This avoids
future alias collisions when new configuration categories are added.

## 3. Commands

### 3.1 `create-deployment-plan` / `cdp`

Syntax:

```bash
algites-orchestrator create-deployment-plan [options] --deployment=<reference>
algites-orchestrator cdp [options] -d=<reference>
```

`--deployment` / `-d` identifies the deployment configuration to resolve. It may
be either an unqualified id or an exact category-relative configuration
reference.

Examples:

```bash
algites-orchestrator cdp \
  -cr=/srv/algites/config \
  -d=production/main

algites-orchestrator cdp \
  -cr=/srv/algites/config \
  -d=production/main \
  -of=/tmp/run-001 \
  -ofn=deployment-plan.yml
```

The command:

1. resolves the requested `GuestDeploymentConfiguration`,
2. resolves its referenced `GuestConfiguration`, `HostConfiguration` and
   `DeploymentEnvironmentConfiguration`,
3. resolves referenced `SharedMountableResourceConfiguration` files,
4. validates every loaded file against its JSON Schema,
5. validates cross-configuration constraints,
6. resolves compute, networks, storage targets, backends and filesystem
   interfaces,
7. evaluates mountable-resource relations,
8. validates the generated `DeploymentPlan` against its schema,
9. writes the plan to stdout or the requested result file.

A `REQUIRED` relation that cannot be proven causes resolution to fail. An
unsatisfied `PREFERRED` relation is retained in the plan with `satisfied: false`
and is also emitted as a warning.

### 3.2 `validate-configuration` / `vc`

Without `--deployment`, the complete configuration root is validated:

```bash
algites-orchestrator vc -cr=/srv/algites/config
```

This checks all discovered `.yml` files, filename/id invariants, JSON Schemas,
cross-file references and resolvability of all deployment configurations.

With `--deployment`, validation is limited to the configuration closure required
by that deployment:

```bash
algites-orchestrator vc \
  -cr=/srv/algites/config \
  -d=production/main
```

Unrelated configuration files are not loaded by closure validation. Discovery
still uses their paths for reference indexing, so an unqualified reference can
correctly report ambiguity without parsing unrelated files.

The command produces a small machine-readable validation report. Successful
validation is also represented by exit code `0`; callers should prefer the exit
code when they only need a yes/no result.

## 4. Common options

| Long option | Short alias | Default | Meaning |
|---|---|---:|---|
| `--config-root` | `-cr` | `.` | Root directory containing configuration-category folders. |
| `--config-folder-deployments-name` | `-cfdn` | `deployments` | Deployment configuration folder below config root. |
| `--config-folder-environments-name` | `-cfen` | `environments` | Environment configuration folder below config root. |
| `--config-folder-guests-name` | `-cfgn` | `guests` | Guest configuration folder below config root. |
| `--config-folder-hosts-name` | `-cfhn` | `hosts` | Host configuration folder below config root. |
| `--config-folder-shared-mountable-resources-name` | `-cfsmrn` | `shared-mountable-resources` | Shared mountable-resource configuration folder below config root. |
| `--output-folder` | `-of` | current directory | Base directory for relative output file paths. |
| `--output-file-name` | `-ofn` | none | Result file. If omitted, the result is written to stdout. |
| `--processing-info-file-name` | `-pifn` | none | Optional persistent copy of the diagnostic stream. |
| `--output-format` | `-ofmt` | `yaml` | Result serialization: `yaml` or `json`. |
| `--log-level` | `-ll` | `INFO` | Diagnostic threshold: `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `--verbose` | `-vb` | off | Equivalent to `--log-level=DEBUG`. |
| `--quiet` | `-q` | off | Equivalent to `--log-level=ERROR`. |
| `--help` | `-h` | — | Show command help. |
| `--version` | `-v` | — | Show Orchestrator version. |

`--log-level`, `--verbose` and `--quiet` are mutually exclusive. This avoids an
ambiguous precedence rule.

There is intentionally no `OFF` log level. Errors remain visible unless the
caller explicitly redirects or discards stderr.

## 5. Configuration directory structure

Configuration-category directories are recursive rather than flat. For example:

```text
config/
├── deployments/
│   ├── production/
│   │   └── main.yml
│   └── testing/
│       └── test01.yml
├── environments/
│   └── dc01.yml
├── hosts/
│   ├── site01/
│   │   ├── hostA.yml
│   │   └── hostB.yml
│   └── site02/
│       └── hostA.yml
├── guests/
│   └── application.yml
└── shared-mountable-resources/
    └── cache.yml
```

Category folder options are relative paths below `--config-root`. Absolute
category-folder paths and `.` / `..` path components are rejected. Files reached
through a symlink must still resolve below the corresponding category root.

Only `.yml` is a supported configuration extension. `.yaml` is deliberately not
accepted, preventing two spellings of the same logical configuration file.

## 6. File name and entity id invariant

Every configuration file name, without `.yml`, must exactly equal the stable
technical `id` of the top-level entity defined by the file.

Example:

```text
hosts/site01/hostA.yml
```

must contain:

```yaml
host:
  id: hostA
```

A file named `hostA.yml` containing `id: hostB` is invalid.

The directory path is not part of the entity `id`. It forms the namespace of the
configuration reference.

## 7. Configuration references and namespaces

Cross-file references use `ConfigurationReference`, separate from the stable
entity `Identifier`.

A reference has one of two forms.

### 7.1 Exact qualified reference

```yaml
host: site01/hostA
```

This is resolved only as:

```text
<config-root>/<hosts-folder>/site01/hostA.yml
```

If that exact configuration does not exist, resolution fails. There is no fuzzy
fallback search.

### 7.2 Unqualified reference

```yaml
host: hostA
```

The complete host-category tree is searched by file base name.

Resolution rules are deterministic:

```text
0 matches  -> unresolved reference error
1 match    -> use that configuration
2+ matches -> ambiguous reference error
```

For example, with:

```text
hosts/site01/hostA.yml
hosts/site02/hostA.yml
```

`host: hostA` fails with an ambiguity diagnostic listing both candidates, while
`host: site01/hostA` resolves exactly.

This rule applies uniformly to deployments, environments, hosts, guests and
shared mountable resources.

### 7.3 Reference syntax restrictions

Configuration references are logical category-relative paths, not arbitrary
filesystem paths. They:

- use `/` as the separator,
- are case-sensitive,
- cannot start with `/`,
- cannot contain `.` or `..` path components,
- cannot escape their configuration category.

A generated `DeploymentPlan` records resolved cross-file identities using their
canonical category-relative references, so a plan remains unambiguous even when
short ids are duplicated in different namespaces.

## 8. Result output versus diagnostic output

The CLI follows a strict stream contract:

```text
stdout (1) = command result / machine-readable data
stderr (2) = diagnostics / processing information
```

Diagnostics include `ERROR`, `WARNING`, `INFO`, `DEBUG` and `TRACE` messages
according to the selected log level. They never contaminate the structured
result written to stdout.

This makes shell composition safe:

```bash
algites-orchestrator cdp -cr=config -d=production/main | another-command
```

and makes conventional redirection useful:

```bash
algites-orchestrator cdp -cr=config -d=production/main \
  > deployment-plan.yml \
  2> processing.log
```

## 9. Result file path resolution

`--output-file-name` / `-ofn` may be a simple file name, a relative path, or an
absolute path.

Path resolution is:

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

-of=/tmp/run -ofn=plans/production.yml
# /tmp/run/plans/production.yml

-of=/tmp/run -ofn=/var/lib/algites/production.yml
# /var/lib/algites/production.yml; -of does not alter an absolute path
```

Parent directories required by a requested result path are created
automatically.

## 10. Processing information file

`--processing-info-file-name` / `-pifn` writes a persistent copy of the same
filtered diagnostic stream that is written to stderr.

It does **not** replace or suppress stderr.

```bash
algites-orchestrator cdp \
  -cr=config \
  -d=production/main \
  -pifn=processing.log
```

Diagnostics therefore go both to stderr and `processing.log`.

If the caller wants only the file copy, ordinary shell redirection is used:

```bash
algites-orchestrator cdp ... -pifn=processing.log 2>/dev/null
```

A relative processing-info path follows the same `--output-folder` rule as a
relative result path. An absolute processing-info path ignores
`--output-folder`. The processing-info file is a per-invocation log and is
replaced when a new invocation starts.

The result file and processing-info file may not resolve to the same path.

## 11. Output format

Structured command results can be serialized as YAML or JSON:

```bash
algites-orchestrator cdp ... --output-format=yaml
algites-orchestrator cdp ... -ofmt=json
```

YAML is the default.

The internal deployment resolver produces a Python object model first; YAML and
JSON are serialization adapters rather than separate resolution implementations.

## 12. Exit codes

Exit codes are part of the stable CLI automation contract.

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

## 13. Implementation boundaries

The CLI is a thin adapter around reusable Python code:

```text
filesystem
    ↓
configuration discovery/index
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
    ↓
YAML/JSON output adapter
```

Core resolution logic has no Ansible dependency. Ansible remains an execution
adapter consuming the resolved `DeploymentPlan`, rather than reimplementing
configuration or placement business logic.

## 14. Current source-tree entry points

From a source checkout:

```bash
python3 -m orchestrator cdp -cr=examples/config -d=example-guest-deployment
python3 -m orchestrator vc -cr=examples/config
```

After installation as a Python package:

```bash
algites-orchestrator cdp -cr=examples/config -d=example-guest-deployment
```

The package requires Python 3.11 or newer, PyYAML and jsonschema.
