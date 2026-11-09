# Requirements Specification

> Defines the features the system offers, organized by module and expressed through functional requirements and their corresponding user stories, establishing the expected behavior of the application from a business perspective.

## Table of Contents

- [Project Summary](#project-summary)
- [System Requirements](#system-requirements)
    - [Non-Functional Requirements](#non-functional-requirements)
    - [Functional Requirements](#functional-requirements)
- [User Stories](#user-stories)
- [Data Models](#data-models)
    - [Persistence Models](#persistence-models)
    - [Cache Structures - Redis](#cache-structures---redis)

---
## Project Summary

- **Project name:**

- **Short description:**

- **Detailed description:**

- **Main objective:**

- **Real problem it solves:**

- **Involved actors:**

- **Architecture type:**

- **Initial tech stack:**
    - Language:
    - Framework:
    - Database:
    - Others:

---

## System Requirements

### Non-Functional Requirements

### Functional Requirements

#### Module X - :

---

## User Stories

### Module X - :

#### US-RF-XXX: [User story title]

**As** [role/actor],
**I want** [action or function],
**So that** [benefit or reason].

**Endpoint (Optional):**
**Tasks (Optional):**
**Scheduler (Optional):**
**Requires Authentication (Optional):**
**Publishes/Consumes Event (Optional):**
**Cache (Optional):**

**Priority:** [High (P0) / Medium (P1) / Low (P2)]
**Size**: [XS, … , XL]
**Estimate**: [1 - 10]

**Acceptance criteria:**

- [ ] Applicable RNF: [RNF-XXX, RNF-XXX]

**Input Validation**

> Defines the conditions that incoming data must satisfy and the expected behavior when it is invalid, incomplete, or does not meet the specified constraints.
>
> Example: An organization's name must contain between 3 and 150 characters after leading and trailing whitespace is removed.

- Acceptance Criterion 1.
- Acceptance Criterion 2.
- etc.

**Business Rules**

> Defines the domain-specific constraints, conditions, and decisions that determine when an operation is permitted and how the system must behave.
>
> Example: The user who creates an organization must automatically become its owner (`OWNER`).

- Acceptance Criterion 1.
- Acceptance Criterion 2.
- etc.

**Persistence and Integrity**

- Acceptance Criterion 1.
- Acceptance Criterion 2.
- etc.

**Security**

> Establishes the authentication, authorization, organization isolation, and information protection requirements that must be enforced during an operation.
>
> Example: The creator's identity must be obtained from the validated token rather than from an identifier provided by the client.

- Acceptance Criterion 1.
- Acceptance Criterion 2.
- etc.

**HTTP Responses**

> Defines the observable behavior of the HTTP interface, including output data, status codes, and the structure of successful and error responses.
>
> Example: `500`: Unexpected error, with no stack traces or internal details.

---

## Data Models

### Persistence Models

#### Data model ``name``

| Field | Type | Constraints | Description |
| ----- | ---- | ----------- | ----------- |
|       |      |             |             |

### Cache Structures - Redis

| Key | Type | Value | TTL | Purpose |
| --- | ---- | ----- | --- | ------- |
|     |      |       |     |         |
