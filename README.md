# Algites Orchestrator

A general orchestration tool for declarative Algites automation workflows.

> Public Algites project.

---

## 📦 Overview

**Algites Orchestrator** is a tool for describing, resolving, validating, and applying orchestration workflows in a structured and reusable way.

The project is intentionally designed as a general orchestrator rather than as a tool tied permanently to a single infrastructure use case. Functionality is organized into orchestration domains so that domain-specific configuration, resolution, validation, and execution logic can evolve independently while sharing common orchestration infrastructure.

The first domain is **Deployment**.

Detailed Deployment architecture, configuration-model semantics, examples, resolver behavior, Ansible/NixOS integration, and planned Deployment CLI are documented in:

**[`orchestrator/deployment/README.md`](orchestrator/deployment/README.md)**

The project is part of the Algites ecosystem and is designed around explicit configuration, separation of concerns, reproducibility, validation, and automation.

---

## 🧱 Modules & Structure

The project is organized around reusable orchestration infrastructure and domain-specific modules.

```text
.
├── README.md
├── LICENSE
├── orchestrator/
│   ├── common/
│   └── deployment/
│       └── README.md
├── ansible/
│   └── collection/
├── schemas/
└── tests/
```

The exact physical structure may evolve while the implementation is developed. The architectural boundaries are more important than the final folder layout:

- reusable orchestration logic belongs to the Orchestrator,
- domain-specific business logic belongs to the corresponding orchestration domain,
- external execution/integration technologies should remain adapters rather than becoming the source of orchestration business logic,
- each domain documents its detailed model and behavior in its own README.

For the Deployment domain, see
[`orchestrator/deployment/README.md`](orchestrator/deployment/README.md).

---

## 🚀 Build

The implementation technology and final build tooling are not yet fixed for the complete Orchestrator project.

Build and packaging instructions will be added as the project structure and individual orchestration domains are implemented. Domain-specific implementation details belong to the corresponding domain documentation.

---

## 🔄 Continuous Integration (Algites CI)

This repository uses the **Algites unified GitHub Actions CI pipeline** (build/test/publish rules are centralized).

For exact usage and naming of the branches to utilize fully the defined possibilities, see
https://github.com/Algites-EU/pub.gov.Algites.specs/blob/main/ci/Algites-Github-CI-Policy.md

---

## 📥 Usage

The final Orchestrator CLI is not yet implemented.

Commands are intended to be organized by orchestration domain. Each domain documents its own planned or implemented commands and configuration conventions.

For Deployment usage, see
[`orchestrator/deployment/README.md`](orchestrator/deployment/README.md).

---

## 🛠 Development

Typical workflow:

```bash
git clone https://github.com/Algites-EU/pub.tool.Orchestrator.git
cd pub.tool.Orchestrator
```

Further development and test commands will be documented after the initial project skeleton and implementation technology are finalized.

Domain-specific development information belongs to the corresponding domain README.

---

## 🤝 Contributing

Contributions are welcome.

Please:

- open an issue to discuss changes,
- follow the Algites coding and naming standards,
- preserve clear boundaries between common orchestration infrastructure and domain-specific logic,
- keep domain resolution/business logic independent from execution tooling where practical,
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
