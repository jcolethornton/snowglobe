# Snowglobe — Product Specification

## Overview

**Snowglobe** is a read-only CLI tool that provides **explainable visibility into Snowflake cost and access**.

It answers three core questions:

1. **Where did our Snowflake spend come from?**
2. **Who owns and can access what?**
3. **Who is responsible when cost or access looks wrong?**

Snowglobe does **not** manage, deploy, or enforce Snowflake state.
It observes, explains, and recommends.

---

## Goals

* Make Snowflake cost **understandable and attributable**
* Make Snowflake access **traceable and explainable**
* Provide **human-readable insights**, not raw metadata
* Be safe to run in production (read-only by default)
* Be useful via CLI output alone

---

## Non-Goals (Very Important)

Snowglobe will **not**:

* Modify Snowflake objects or grants
* Apply DDL or manage deployments
* Act as a dashboard or BI tool
* Replace Terraform, dbt, or Snowflake-native controls
* Guarantee “correct” governance decisions

If a feature requires write access, it is **out of scope for v1**.

---

## Target Users

* Analytics Engineers
* Data Engineers
* Data Platform / Enablement teams

Snowglobe is built for **engineers**, not executives.

---

## Supported Environments (v1)

* Snowflake (all editions)
* Python 3.11+
* CLI execution (local, cron, CI, Airflow)

---

## Authentication & Security

* Uses standard Snowflake credentials (password, key pair, SSO)
* Requires **read-only role**
* No data leaves the customer environment by default
* Optional outbound Slack webhook only

---

## Core Concepts

### Cost Visibility

Snowglobe focuses on **cost deltas and attribution**, not billing totals.

Cost is attributed to:

* Warehouse
* Role
* User / service account
* Query type (e.g. COPY, SELECT, TRANSFORM)

Baseline comparisons are used to detect unusual changes.

---

### Access Visibility

Snowglobe explains **why** access exists, not just **that** it exists.

Access explanations include:

* Role inheritance paths
* Ownership chains
* Grant sources (direct vs inherited)
* Future grants

---

### Explainability

Every insight must:

* Show the reasoning path
* Reference concrete Snowflake metadata
* Be reproducible from raw inputs

“No black boxes.”

---

## CLI Interface (v1)

### `snowglobe daily`

Outputs a daily summary combining cost and access insights.

**Includes:**

* Total cost vs baseline
* Top cost contributors
* Notable access risks or anomalies
* Correlated insights (cost + ownership)

---

### `snowglobe cost`

Focused cost analysis.

**Subcommands (initial):**

* `snowglobe cost summary`
* `snowglobe cost top`
* `snowglobe cost delta`

---

### `snowglobe access`

Focused access analysis.

**Subcommands (initial):**

* `snowglobe access explain <role|object>`
* `snowglobe access ownership`
* `snowglobe access diff`

---

## Outputs

Snowglobe supports multiple output formats:

* Rich CLI (default)
* JSON
* CSV
* Optional Slack message (summary only)

---

## Architecture Principles

* Read-only Snowflake queries only
* Clear separation between:

  * Data collection
  * Analysis
  * Insight generation
  * Presentation
* Domain logic must be testable without Snowflake

---

## Testing Strategy

* Unit tests for analyzers and explainers
* Fixtures for Snowflake metadata
* Minimal integration tests for read-only access

---

## Versioning & Evolution

* v1: Visibility + explainability
* v2+: Optional controlled actions (explicit opt-in only)
* No breaking changes without a major version bump

---

## Success Criteria (v1)

Snowglobe is successful if:

* An engineer can explain a cost spike in minutes
* An engineer can trace why access exists without trial-and-error
* The tool can be safely recommended to run in prod

---

## License & Distribution

* Distributed as a Python package
* CLI-first
* Commercial licensing planned (details TBD)

---

## Guiding Principle

> **Snowglobe earns trust by never touching production state.**

