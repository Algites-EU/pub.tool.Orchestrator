# Algites Orchestrator Application Component Profile

**Status:** Draft product profile  
**Base architecture:** `Application-Component-Architecture-Governance.md`  
**Capability contracts:** `Application-Component-Capability-Contract-Specification.md`  
**Lifecycle:** `Application-Component-Lifecycle-and-Provisioning-Specification.md`  
**Context/configuration/entitlement:** `Application-Component-Context-Configuration-and-Entitlement-Specification.md`  
**UI:** `Application-Component-UI-Specification.md`

---

# I. Purpose

This profile defines the Algites Orchestrator-specific identities and conventions layered on the generic Application Component Architecture and the Algites Application Components (AAC) reference framework. Generic framework behavior belongs to the Application Component specifications, not here.

# II. Reserved namespaces

AAC framework-owned public contracts use:

```text
_AAC.*
```

Algites Orchestrator-owned product contracts and stable product identities use:

```text
_AO.*
```

Third-party components MUST NOT define unrelated identities in either reserved namespace.

Examples of Orchestrator-owned capability identities include:

```text
_AO.vcs.repository
_AO.vcs.status
_AO.configuration.change-plan
_AO.deployment.plan
```

Generic capability observation is **not** an Orchestrator contract; it is provided by AAC as:

```text
_AAC.capability.observation / 1
```

# III. Predefined and example identities

Orchestrator reserved predefined/example namespaces use dot-qualified names:

```text
_AO.predefs
_AO.examples
```

These replace the older `_AO_predefs` and `_AO_examples` forms. Stable references use immutable entity IDs; names and display names remain mutable metadata.

# IV. Packaging profile

Orchestrator-distributed predefinitions and examples SHOULD reside under the Orchestrator package root so a single installable/distributable package can contain code plus product-owned data. Physical package paths are implementation details; `_AO.predefs` and `_AO.examples` are logical product namespaces rather than filesystem identity.

# V. Tracing/diagnostic plugin

The initial Orchestrator integration test profile should include a simple tracing component that can provide `_AAC.capability.observation/v1`. Its provider instances receive Core-owned observation bindings and print normalized, redacted observation envelopes to stdout or another configured destination.

If a separate dummy provider is used to exercise an Orchestrator VCS capability, it MUST return results valid under that VCS contract and MUST NOT falsely report that irreversible side effects occurred. Generic tracing should normally use the AAC observation contract rather than pretending to be an authoritative VCS provider.

# VI. Instance graph rule

Orchestrator follows the generic baseline: component/provider-definition declarations may appear cyclic, but concrete extension provider-instance bindings resolved by Core MUST form a DAG.

For example, components A and B may mutually declare consumed/provided capabilities while actual bindings resolve `A1 -> B1` and `B2 -> A2`. A concrete cycle such as `A1 -> B1 -> A1` is invalid.

# VII. Context and extension-data storage

Orchestrator adopts the generic AAC contextual model. `SYSTEM`, `USER`, and `WORKSPACE` remain well-known **configuration-scope** types; additional configuration-scope types are profile/deployment-defined. Entitlement licensing scopes are a separate open component contract: plugins declare their own licensing-scope types and display metadata, while Orchestrator or another infrastructure component supplies registered licensing-scope resolvers for types it can establish from current state. Orchestrator MUST NOT hard-code `SYSTEM`, `USER`, or `WORKSPACE` as the complete licensing vocabulary. A `WORKSPACE` licensing scope may use an Orchestrator-managed/database-backed workspace identity; a `SOURCE_REPOSITORY` scope may be supplied by a VCS-aware resolver and use repository-lineage evidence. Generic AAC entitlement evidence may bundle grants for multiple components under one issuer, licensing scope, and subject. The Orchestrator profile intentionally does not yet prescribe the physical representation of component-owned workspace extension data; AAC defines the logical envelope/preservation semantics while Orchestrator Core owns persistence mapping.

## Authentication/configuration provider profile

Orchestrator may bind generic AAC configuration-providers to local files or remote services. It MUST use the generic AAC separation of authentication profile, secret-provider reference, and Core authorization rather than storing provider passwords/tokens directly in Orchestrator project configuration. Installation/bootstrap authentication required before project configuration is available must come from product-supplied bootstrap-safe sources.

# IX. Built-in Orchestrator Component and Core Capabilities

The Orchestrator host registers a trusted built-in AAC component with stable product-owned identity. The recommended baseline identity is:

```text
_AO.core
```

Ordinary Orchestrator component configuration and product entitlement use the same AAC mechanisms as extension components once bootstrap has established them.

Orchestrator MAY expose Core-domain and standard-UI services as `_AO.*` capabilities. For example:

```text
_AO.core.siteManagement / 1
_AO.core.siteUi / 1
```

A third-party Site-map component can store its own coordinates/layout in its Site component-extension payload while consuming `siteManagement` to change Core-owned Site attributes. A double-click can consume `siteUi` to invoke the same standard Site editor used by built-in Orchestrator UI.

The Site-management capability may define authorization vocabulary such as `VIEW_SITE` and `EDIT_SITE`; operation requirements and presentation metadata belong to the canonical contract. The consumer requests only the permissions it needs and Orchestrator/Core grants/enforces the approved subset.

Generated Java and Python bindings use version-qualified generated type names such as `AIig..._N` and `AIcgd..._N`; `g` marks generated types and the optional `d` marks only explicit data objects/DTOs. Generated bindings retain canonical source ID/version provenance and, where available, the canonical resource path. The canonical contract/schema, not hand-written annotations, is authoritative.



## Package-store profile

The Orchestrator product supplies its own user/product root to AAC package management. The recommended initial layout is conceptually:

```text
<orchestrator-user-root>/
  plugins/
    downloaded/
    installed/
    obsolete/
  aac-state/
    active-package-set.json
    active-transaction.json
    transactions/
      <transaction-uuid>/
```

The relative names are not architectural identities and MAY be changed by the product profile. `aac-state` is Core-owned durable state rather than package payload storage. Mutable Core-owned records use the generic AAC `record_revision` contract; the active package-set record uses a monotonic-integer revision and is atomically replaced as one complete selection. Transaction UUIDs are opaque correlation identities rather than revisions or version numbers. The Core-owned state domain uses a short-lived inter-process `core.lock` only around commit/cutover and revalidates transaction read-set revisions after acquiring it. On restart, an unfinished journal restores source Core state if the source active-set record remains authoritative, or completes target cleanup if the target revision/transaction identity was durably committed.

Multiple immutable versions/digests may coexist physically while candidates are staged, but within one Orchestrator Core-managed runtime/package-selection domain only one artifact version of a component identity may be active/selected. Component replacement uses the AAC complete target-state transaction model and classifies persisted configuration/semantic-data contributions as `DIRECT`, `TRANSFORMED`, or `UNSUPPORTED` without writing providers/stores during tentative activation. Unsupported contributions are preserved and may produce fallback/`UNDEFINED`/degraded readiness rather than automatically blocking the target. After a successful replacement, the superseded unselected artifact is moved to `obsolete` according to Orchestrator retention policy. Returning to that artifact later is simply a new replacement transaction evaluated against then-current graph and resolved inputs; the prior replacement transaction is closed after commit.


## Catalog profile

Orchestrator uses the generic AAC Catalog contract for extension discovery. Catalog queries are always scoped by a stable Orchestrator product identifier plus the implementation technology. The Orchestrator product identifier is `eu.algites.app.orchestrator`; the Python binding uses technology identifier `PYTHON`. The same component ID/version in another technology scope is an independent catalog release.

The Orchestrator profile may register multiple catalog sources (for example public Algites, organization-internal, and local development catalogs). Catalog source priority/provenance does not make catalog metadata authoritative over the downloaded component descriptor. Filesystem/HTTP catalog providers are baseline transports; artifact locators may use independent authentication and may later be served by technology-specific repository adapters. Runtime entitlement/licensing remains separate from catalog discovery; `entitlement_info_url` is informational and installation of an artifact does not itself grant entitlement.


## Readiness profile

Orchestrator adopts the AAC baseline `READY / DEGRADED / NOT_READY` model. Lifecycle activation and readiness remain separate. Orchestrator administration UI should display readiness for provider instances/capabilities and retain structured reasons. Replacement preflight readiness is advisory by default; Orchestrator may later define stricter minimum-readiness policies for specific production workflows without changing the generic AAC semantics.


## Target-state solver profile

Orchestrator adopts the generic AAC automatic target-state solver policy. Solver queries remain scoped by `product_id = eu.algites.app.orchestrator` plus the active implementation technology. Explicit requested releases and workspace component requirements/locks are hard constraints.

For requested upgrades, Orchestrator prefers the newest compatible no-downgrade release branch inside the causal mandatory-capability closure and does not opportunistically upgrade unrelated components. Downgrade solutions are never recommended; they may appear only as explicit alternatives when all relevant persistent component/provider configuration and entity-extension schema identities/write versions remain unchanged, and the user must explicitly select such an alternative.

Entitlement diagnostics and projected readiness degradation remain visible but do not by themselves turn a technically compatible target state into an incompatible one. Artifact download/install and the final crash-safe replacement transaction remain separate from solver planning.
