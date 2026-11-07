# Clean Architecture & DDD Publishing Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor OpenMontage's publishing and scheduling pipeline to adhere to Clean Architecture & Domain-Driven Design (DDD) principles: establishing pure domain entities, abstract outbound ports (`typing.Protocol`), modular interface adapters, and decomposing oversized modules (`scripts/publish_active_projects.py` and `tools/publish_store.py`) to well under the 450-line target with 100% test coverage and zero backward-compatibility regressions.

**Architecture:** Dependencies flow strictly inward: Domain Core (Entities & Invariants) $\leftarrow$ Application Layer (Use Cases & Ports via `typing.Protocol`) $\leftarrow$ Interface Adapters (Social Publishers & Persistence Adapters) $\leftarrow$ Frameworks & Drivers (CLI entrypoints & Cron jobs). Infrastructure types and wire transports never leak into domain models.

**Tech Stack:** Python 3.10+, `typing.Protocol`, `@dataclass(frozen=True)`, `pytest`.

**Spec:** OpenMontage Clean Architecture & Domain-Driven Design Standard (`AGENTS.md` & `references/python_clean_architecture.md`).

---

## Global Constraints

- **Inward Dependency Rule**: Domain and application modules must never import external transport or third-party SDKs (`google.auth`, `requests`, `facebook_scraper`, `subprocess`).
- **Module Ceilings**: Target under 450 lines per module; strict hard ceiling of 800 lines maximum.
- **Fail-Closed Validation**: All external inputs must be validated into domain Value Objects or Entities at the boundary before use-case execution.
- **Zero Regressions**: 100% backward compatibility for existing entrypoints (`scripts/publish_active_projects.py`, `tools/publish_store.py`, `tools/publishers/youtube_publisher.py`).
- **Test Integrity**: All existing tests (35+ test suite) and new unit tests must pass.

---

## Component & File Structure

```text
OpenMontage/
├── lib/
│   ├── domain/
│   │   └── publishing/
│   │       ├── __init__.py           # Facade re-exports for domain entities & errors (<50 lines)
│   │       ├── entities.py           # Pure Value Objects & Entities: PublishJob, PublishSlot, PlatformType (<250 lines)
│   │       └── exceptions.py         # Domain errors: QuotaExceeded, ConcurrencyConflict (<100 lines)
│   └── application/
│       └── publishing/
│           ├── __init__.py           # Facade re-exports for ports & use cases (<50 lines)
│           ├── ports.py              # Outbound Protocols: SocialPublisherPort, PublishStorePort (<150 lines)
│           └── use_cases.py          # Orchestrators: PublishActiveSlotUseCase, ManualPublishUseCase (<300 lines)
├── tools/
│   ├── system_media_utils.py         # Extracted OS & binary discovery utilities: _ffmpeg, etc. (<100 lines)
│   ├── storage/
│   │   ├── __init__.py               # Storage transport exports (<20 lines)
│   │   └── datastore_transport.py    # Isolated Google Datastore REST transport (<250 lines)
│   ├── publish_store.py              # Decomposed clean store preserving exact API (<350 lines)
│   └── publishers/
│       ├── adapters/
│       │   ├── __init__.py           # Adapter exports & factory (<50 lines)
│       │   ├── youtube_adapter.py    # Implements SocialPublisherPort (<200 lines)
│       │   ├── facebook_adapter.py   # Implements SocialPublisherPort (<200 lines)
│       │   └── tiktok_adapter.py     # Implements SocialPublisherPort (<200 lines)
│       └── ...
├── scripts/
│   └── publish_active_projects.py    # Thin CLI composition root (<300 lines)
└── tests/
    ├── domain/
    │   └── test_publishing_domain.py # Unit tests for entities & value objects
    └── application/
        └── test_publishing_use_cases.py # Unit tests for use cases with in-memory test doubles
```

---

## Tasks

### Task 1: Domain Core for Publishing (`lib/domain/publishing/`)

**Files:**
- Create: `lib/domain/publishing/entities.py`
- Create: `lib/domain/publishing/exceptions.py`
- Create: `lib/domain/publishing/__init__.py`
- Test: `tests/domain/test_publishing_domain.py`

**Interfaces:**
- Consumes: Standard library (`dataclasses`, `enum`, `datetime`, `typing`, `zoneinfo`)
- Produces: `PlatformType`, `PublishStatus`, `PublishSlot`, `PublishJob`, `PublishResult`, `PublishDomainError`

- [ ] **Step 1: Write unit tests for domain entities and value objects**
  - Verify `PublishSlot` parses schedule times and computes UTC ISO strings with trailing `Z`.
  - Verify `PublishJob` enforces immutability (`frozen=True`) and transitions status via pure methods (`with_status(...)`).
  - Verify `PlatformType` and `PublishStatus` enumerations.

- [ ] **Step 2: Run test to verify failure**
  - Run: `pytest -o cache_dir=/tmp/.pytest_cache tests/domain/test_publishing_domain.py`
  - Expected: FAIL (`ModuleNotFoundError: No module named 'lib.domain'`)

- [ ] **Step 3: Implement domain exceptions and entities**
  - Implement `lib/domain/publishing/exceptions.py`.
  - Implement `lib/domain/publishing/entities.py`.
  - Implement `lib/domain/publishing/__init__.py` facade re-exports.

- [ ] **Step 4: Run test to verify passing**
  - Run: `pytest -o cache_dir=/tmp/.pytest_cache tests/domain/test_publishing_domain.py`
  - Expected: PASS

- [ ] **Step 5: Commit Task 1**

---

### Task 2: Application Layer & Outbound Ports (`lib/application/publishing/`)

**Files:**
- Create: `lib/application/publishing/ports.py`
- Create: `lib/application/publishing/use_cases.py`
- Create: `lib/application/publishing/__init__.py`
- Test: `tests/application/test_publishing_use_cases.py`

**Interfaces:**
- Consumes: `lib/domain/publishing/`
- Produces: `SocialPublisherPort(Protocol)`, `PublishStorePort(Protocol)`, `PublishActiveSlotUseCase`, `ManualPublishUseCase`

- [ ] **Step 1: Write unit tests for use cases using in-memory test doubles**
  - Test `PublishActiveSlotUseCase.execute(...)` with mock publishers and an in-memory `PublishStorePort`.
  - Test idempotency: skipped if already published or scheduled.
  - Test overdue inclusion handling and error capture without thread abortion.

- [ ] **Step 2: Run test to verify failure**
  - Run: `pytest -o cache_dir=/tmp/.pytest_cache tests/application/test_publishing_use_cases.py`
  - Expected: FAIL (`ModuleNotFoundError: No module named 'lib.application'`)

- [ ] **Step 3: Implement application ports and use cases**
  - Implement `ports.py` with `SocialPublisherPort` and `PublishStorePort`.
  - Implement `use_cases.py` with `PublishActiveSlotUseCase` and `ManualPublishUseCase`.
  - Implement `__init__.py` facade re-exports.

- [ ] **Step 4: Run test to verify passing**
  - Run: `pytest -o cache_dir=/tmp/.pytest_cache tests/application/test_publishing_use_cases.py`
  - Expected: PASS

- [ ] **Step 5: Commit Task 2**

---

### Task 3: Publisher Interface Adapters (`tools/publishers/adapters/`)

**Files:**
- Create: `tools/publishers/adapters/__init__.py`
- Create: `tools/publishers/adapters/youtube_adapter.py`
- Create: `tools/publishers/adapters/facebook_adapter.py`
- Create: `tools/publishers/adapters/tiktok_adapter.py`
- Test: `tests/tools/test_publisher_adapters.py`

**Interfaces:**
- Consumes: `tools/publishers/{youtube,facebook,tiktok}_publisher.py`, `lib/application/publishing/ports.py`
- Produces: `YouTubeAdapter`, `FacebookAdapter`, `TikTokAdapter`, `create_publisher_registry()`

- [ ] **Step 1: Write unit tests for adapters**
  - Test that all three adapters adhere to `isinstance(adapter, SocialPublisherPort)`.
  - Test mapping of `PublishJob` to concrete publisher payloads.
  - Test error handling converts platform exceptions into `PublishResult(success=False, ...)`.

- [ ] **Step 2: Run test to verify failure**
  - Run: `pytest -o cache_dir=/tmp/.pytest_cache tests/tools/test_publisher_adapters.py`
  - Expected: FAIL

- [ ] **Step 3: Implement publisher adapters**
  - Implement `youtube_adapter.py` delegating to `YouTubePublisher`.
  - Implement `facebook_adapter.py` delegating to `FacebookPublisher`.
  - Implement `tiktok_adapter.py` delegating to `TikTokPublisher`.
  - Implement `create_publisher_registry()` in `tools/publishers/adapters/__init__.py`.

- [ ] **Step 4: Run test to verify passing**
  - Run: `pytest -o cache_dir=/tmp/.pytest_cache tests/tools/test_publisher_adapters.py`
  - Expected: PASS

- [ ] **Step 5: Commit Task 3**

---

### Task 4: Decompose `tools/publish_store.py` (< 350 lines)

**Files:**
- Create: `tools/system_media_utils.py` (extract `_ffmpeg()` and related system checks)
- Create: `tools/storage/datastore_transport.py` (extract Google Datastore HTTP client)
- Modify: `tools/publish_store.py` (refactor to delegate to transport and media utils, reducing from 489 lines to < 350 lines while preserving 100% backward compatibility)
- Test: `tests/test_publish_cleanup.py`, `tests/test_publish_completion.py`

**Interfaces:**
- Consumes: `tools/system_media_utils.py`, `tools/storage/datastore_transport.py`
- Produces: `PublishStore` (backward compatible), `FirestorePublishStoreAdapter` implementing `PublishStorePort`

- [ ] **Step 1: Extract `_ffmpeg` to `tools/system_media_utils.py`**
- [ ] **Step 2: Extract Datastore REST HTTP transport to `tools/storage/datastore_transport.py`**
- [ ] **Step 3: Refactor `tools/publish_store.py` into a focused store (< 350 lines)**
- [ ] **Step 4: Implement `PublishStorePort` on `PublishStore` or via `FirestorePublishStoreAdapter`**
- [ ] **Step 5: Verify all existing store tests pass with zero regressions**
  - Run: `pytest -o cache_dir=/tmp/.pytest_cache tests/test_publish_cleanup.py tests/test_publish_active_projects.py`
  - Expected: PASS

- [ ] **Step 6: Commit Task 4**

---

### Task 5: Slim CLI Composition Root `scripts/publish_active_projects.py` (< 300 lines)

**Files:**
- Modify: `scripts/publish_active_projects.py` (delegate workflow execution to `PublishActiveSlotUseCase`, slimming from 706 lines to < 300 lines)
- Test: `tests/test_publish_active_projects.py`, `tests/test_strict_schedule_only.py`

**Interfaces:**
- Consumes: `lib/application/publishing/use_cases.py`, `tools/publishers/adapters/`
- Produces: CLI script with unchanged argument parsing and exit codes

- [ ] **Step 1: Refactor `scripts/publish_active_projects.py` to wire dependencies and invoke `PublishActiveSlotUseCase`**
- [ ] **Step 2: Preserve all CLI flags (`--slot`, `--include-overdue`, `--dry-run`, `--platform`, `--project-id`)**
- [ ] **Step 3: Run existing schedule & publish test suite**
  - Run: `pytest -o cache_dir=/tmp/.pytest_cache tests/test_publish_active_projects.py tests/test_schedule_today_native.py tests/test_strict_schedule_only.py`
  - Expected: PASS

- [ ] **Step 4: Line count audit: verify `scripts/publish_active_projects.py` < 300 lines**
  - Run: `wc -l scripts/publish_active_projects.py`
  - Expected: < 300 lines (adheres to 450-line target)

- [ ] **Step 5: Commit Task 5**

---

### Task 6: Comprehensive Verification & Remote Synchronization

**Files:**
- Sync to remote server: `sandbox-video`
- Verify tests on remote container: `openmontage_scheduler`

- [ ] **Step 1: Run full local test suite**
  - Run: `pytest -o cache_dir=/tmp/.pytest_cache tests/domain/ tests/application/ tests/tools/ tests/test_publish_active_projects.py tests/test_schedule_today_native.py tests/test_strict_schedule_only.py`
  - Expected: 100% PASS

- [ ] **Step 2: Push commit to `origin/main`**
- [ ] **Step 3: Pull to `sandbox-video` and execute test suite inside `openmontage_scheduler`**
- [ ] **Step 4: Verify container health and log stability**
