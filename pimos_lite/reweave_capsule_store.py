"""Non-active SQLite foundation for the Reweave capsule warehouse.

Phase 1 only: this module is intentionally not imported by the current app,
CLI, frontend, composer, or legacy JSON warehouse.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cache
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

from pimos_lite.reweave_source_registry import state_dir

SCHEMA_VERSION = 1
TARGET_SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION, TARGET_SCHEMA_VERSION})
CANONICALIZATION_VERSION = 1
DATABASE_FILENAME = "capsule_warehouse.sqlite3"
BACKUP_DIRECTORY = "backups"
BUSY_TIMEOUT_MS = 5000
MAX_CAPSULE_ASSET_BYTES = 5 * 1024 * 1024

_ALLOWED_BACKUP_KINDS = frozenset({"auto", "manual", "upgrade", "pre_restore"})
_RETENTION = {"auto": 7, "upgrade": 3}
# ponytail: migrations are rare; one process-wide reentrant barrier avoids a registry.
# Normal operations share it; migration and restore hold it across atomic replacement.
_STORE_OPERATION_LOCK = threading.RLock()
_EXCLUSIVE_DATABASES: set[str] = set()
_SCHEMA_FINGERPRINT_SHA256 = {
    1: "31ca94b97ad9e6539f9d62f5938759232aa1a6f3cdac49950962f03555b48bd1",
    2: "061f95e5228cfbd297f975ea4ba1d2d971b36ae76e197cc673381aa5486d1ec2",
}
_CANONICAL_FIELDS = frozenset(
    {
        "capability_kind",
        "activation",
        "input_contract",
        "output_contract",
        "error_contract",
        "runtime_allowlist",
        "dom_scope",
        "usage_scope",
        "html",
        "css",
        "javascript_modules",
        "assets",
    }
)
_CAPABILITY_KINDS = frozenset({"presentation", "interaction", "computation"})
_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_TABLES = frozenset(
    {
        "warehouse_state",
        "app_settings",
        "source_roots",
        "projects",
        "intake_runs",
        "review_items",
        "capability_groups",
        "capsules",
        "capsule_versions",
        "capsule_sources",
        "capsule_assets",
        "capsule_status_events",
        "product_capsule_usage",
        "legacy_capsule_aliases",
    }
)
_TRIGGERS = frozenset(
    {
        "warehouse_state_update_guard",
        "warehouse_state_no_delete",
        "review_items_source_binding_immutable",
        "review_items_content_decision_once",
        "capability_groups_update_guard",
        "capability_groups_no_delete",
        "capsules_identity_immutable",
        "capsules_no_delete",
        "capsules_insert_not_active",
        "capsules_active_requires_current_version",
        "capsules_current_version_belongs_to_capsule",
        "capsules_status_transition",
        "capsule_versions_no_update",
        "capsule_versions_no_delete",
        "capsule_sources_no_update",
        "capsule_sources_no_delete",
        "capsule_sources_canonical_relationship",
        "capsule_assets_no_update",
        "capsule_assets_no_delete",
        "capsule_status_events_no_update",
        "capsule_status_events_no_delete",
        "capsule_status_events_version_belongs_to_capsule",
        "capsule_status_events_match_state",
        "product_capsule_usage_matches_version",
        "product_capsule_usage_manifest_consistent",
        "product_capsule_usage_no_update",
        "product_capsule_usage_no_delete",
        "legacy_capsule_aliases_no_update",
        "legacy_capsule_aliases_no_delete",
        "legacy_capsule_aliases_target_matches",
        "legacy_capsule_aliases_contract",
    }
)


class CapsuleStoreError(RuntimeError):
    """The non-active warehouse could not satisfy its sealed contract."""


class SchemaVersionError(CapsuleStoreError):
    """The database schema is unsupported or incomplete."""


@dataclass(frozen=True)
class CanonicalCapsule:
    payload: dict[str, Any]
    json_bytes: bytes
    sha256: str


SCHEMA_SQL_V1 = r"""
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA user_version = 1;

CREATE TABLE warehouse_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    warehouse_revision INTEGER NOT NULL DEFAULT 0 CHECK (warehouse_revision >= 0),
    last_backed_up_revision INTEGER NOT NULL DEFAULT 0
        CHECK (
            last_backed_up_revision >= 0
            AND last_backed_up_revision <= warehouse_revision
        )
);

INSERT INTO warehouse_state(singleton_id) VALUES (1);

CREATE TABLE app_settings (
    setting_key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE source_roots (
    root_id TEXT PRIMARY KEY,
    root_kind TEXT NOT NULL CHECK (root_kind IN ('single_project', 'project_collection')),
    current_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('bound', 'source_missing')),
    brand_profile_id TEXT,
    brand_profile_json TEXT,
    brand_profile_digest TEXT,
    brand_profile_version INTEGER NOT NULL DEFAULT 0 CHECK (brand_profile_version >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (
            brand_profile_id IS NULL
            AND brand_profile_json IS NULL
            AND brand_profile_digest IS NULL
            AND brand_profile_version = 0
        )
        OR
        (
            brand_profile_id IS NOT NULL
            AND brand_profile_json IS NOT NULL
            AND brand_profile_digest IS NOT NULL
            AND brand_profile_version >= 1
        )
    )
);

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    source_root_id TEXT NOT NULL REFERENCES source_roots(root_id),
    project_relpath TEXT NOT NULL,
    entry_relpath TEXT NOT NULL,
    display_name TEXT NOT NULL,
    project_state TEXT NOT NULL CHECK (
        project_state IN (
            'discovered_unconfirmed',
            'ready',
            'unsupported_v1',
            'source_missing'
        )
    ),
    discovery_signature TEXT NOT NULL,
    last_snapshot_hash TEXT,
    brand_mode TEXT NOT NULL DEFAULT 'inherit' CHECK (
        brand_mode IN ('inherit', 'extend', 'replace', 'clear')
    ),
    brand_profile_id TEXT,
    brand_profile_json TEXT,
    brand_profile_digest TEXT,
    brand_profile_version INTEGER NOT NULL DEFAULT 0 CHECK (brand_profile_version >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_root_id, project_relpath, entry_relpath),
    CHECK (
        (
            brand_profile_id IS NULL
            AND brand_profile_json IS NULL
            AND brand_profile_digest IS NULL
            AND brand_profile_version = 0
        )
        OR
        (
            brand_profile_id IS NOT NULL
            AND brand_profile_json IS NOT NULL
            AND brand_profile_digest IS NOT NULL
            AND brand_profile_version >= 1
        )
    )
);

CREATE TABLE intake_runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(project_id),
    run_kind TEXT NOT NULL CHECK (
        run_kind IN (
            'refresh_project',
            'refresh_all_child',
            'legacy_import',
            'brand_revalidation'
        )
    ),
    status TEXT NOT NULL CHECK (
        status IN (
            'queued',
            'running',
            'no_change',
            'completed',
            'completed_with_pending',
            'failed',
            'cancelled',
            'interrupted'
        )
    ),
    snapshot_before TEXT,
    snapshot_after TEXT,
    extraction_contract_version TEXT NOT NULL,
    redaction_rules_version TEXT NOT NULL,
    security_rules_version TEXT NOT NULL,
    supervision_rules_version TEXT NOT NULL,
    validation_contract_version TEXT NOT NULL,
    canonicalization_version INTEGER NOT NULL,
    counts_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    legacy_source_path_hash TEXT,
    legacy_source_file_hash TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE review_items (
    review_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES intake_runs(run_id),
    project_id TEXT REFERENCES projects(project_id),
    candidate_id TEXT NOT NULL,
    candidate_status TEXT NOT NULL CHECK (
        candidate_status IN (
            'extracted',
            'waiting_user',
            'waiting_model',
            'waiting_validation',
            'review_required',
            'publishable',
            'published',
            'duplicate',
            'merged',
            'rejected'
        )
    ),
    source_relpath TEXT NOT NULL,
    source_location_json TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    redaction_rules_version TEXT NOT NULL,
    candidate_canonical_hash TEXT,
    sanitized_candidate_json TEXT NOT NULL,
    redaction_summary_json TEXT NOT NULL,
    supervision_result_json TEXT,
    supervision_response_hash TEXT,
    equivalence_comparison_json TEXT,
    sensitivity_decision TEXT CHECK (
        sensitivity_decision IS NULL OR sensitivity_decision IN (
            'confirm_fictional_fixture',
            'confirm_safe_redaction',
            'confirm_real_record_reject'
        )
    ),
    sensitivity_decided_at TEXT,
    brand_decision TEXT CHECK (
        brand_decision IS NULL OR brand_decision IN (
            'remove_brand',
            'retain_brand_limited'
        )
    ),
    brand_decided_at TEXT,
    asset_decision TEXT CHECK (
        asset_decision IS NULL OR asset_decision = 'confirm_assets_contain_no_real_records'
    ),
    asset_decided_at TEXT,
    decision TEXT CHECK (
        decision IS NULL OR decision IN (
            'merge_existing',
            'replace_current',
            'create_variant',
            'semantic_split',
            'publish_general',
            'publish_brand_limited',
            'reject'
        )
    ),
    retained_version_id TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (sensitivity_decision IS NULL AND sensitivity_decided_at IS NULL)
        OR
        (sensitivity_decision IS NOT NULL AND sensitivity_decided_at IS NOT NULL AND project_id IS NOT NULL)
    ),
    CHECK (
        (brand_decision IS NULL AND brand_decided_at IS NULL)
        OR
        (brand_decision IS NOT NULL AND brand_decided_at IS NOT NULL AND project_id IS NOT NULL)
    ),
    CHECK (
        (asset_decision IS NULL AND asset_decided_at IS NULL)
        OR
        (asset_decision IS NOT NULL AND asset_decided_at IS NOT NULL AND project_id IS NOT NULL)
    )
);

CREATE TABLE capability_groups (
    capability_key TEXT PRIMARY KEY CHECK (
        length(capability_key) > 0
        AND capability_key NOT GLOB '*[^a-z0-9_]*'
        AND capability_key NOT GLOB '[0-9]*'
    ),
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE capsules (
    capsule_id TEXT PRIMARY KEY,
    capability_key TEXT NOT NULL REFERENCES capability_groups(capability_key),
    role_key TEXT NOT NULL CHECK (
        length(role_key) > 0
        AND role_key NOT GLOB '*[^a-z0-9_]*'
        AND role_key NOT GLOB '[0-9]*'
    ),
    variant_key TEXT NOT NULL CHECK (
        length(variant_key) > 0
        AND variant_key NOT GLOB '*[^a-z0-9_]*'
        AND variant_key NOT GLOB '[0-9]*'
    ),
    capability_kind TEXT NOT NULL CHECK (
        capability_kind IN ('presentation', 'interaction', 'computation')
    ),
    status TEXT NOT NULL CHECK (
        status IN ('active', 'pending_revalidation', 'disabled')
    ),
    current_version_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(capability_key, role_key, variant_key),
    FOREIGN KEY(current_version_id) REFERENCES capsule_versions(version_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE capsule_versions (
    version_id TEXT PRIMARY KEY,
    capsule_id TEXT NOT NULL REFERENCES capsules(capsule_id),
    version_number INTEGER NOT NULL CHECK (version_number >= 1),
    extraction_contract_version TEXT NOT NULL,
    extraction_summary_json TEXT NOT NULL,
    redaction_rules_version TEXT NOT NULL,
    canonicalization_version INTEGER NOT NULL,
    canonical_hash TEXT NOT NULL,
    activation_json TEXT NOT NULL,
    input_contract_json TEXT NOT NULL,
    output_contract_json TEXT NOT NULL,
    error_contract_json TEXT NOT NULL,
    runtime_allowlist_json TEXT NOT NULL,
    dom_scope_json TEXT NOT NULL,
    usage_scope_json TEXT NOT NULL,
    html_text TEXT NOT NULL DEFAULT '',
    css_text TEXT NOT NULL DEFAULT '',
    javascript_modules_json TEXT NOT NULL DEFAULT '[]',
    cleaning_summary_json TEXT NOT NULL,
    security_rules_version TEXT NOT NULL,
    supervision_rules_version TEXT NOT NULL,
    supervision_model_name TEXT NOT NULL,
    supervision_model_digest TEXT NOT NULL,
    supervised_at TEXT NOT NULL,
    supervision_result_json TEXT NOT NULL,
    supervision_response_hash TEXT NOT NULL,
    validation_contract_version TEXT NOT NULL,
    validation_result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(capsule_id, version_number)
);

CREATE TABLE capsule_sources (
    source_link_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES capsule_versions(version_id),
    project_id TEXT REFERENCES projects(project_id),
    source_identity TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('project', 'legacy_json')),
    source_relpath TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    candidate_canonical_hash TEXT NOT NULL,
    relationship TEXT NOT NULL CHECK (
        relationship IN ('exact', 'human_equivalent', 'published_implementation')
    ),
    read_at TEXT NOT NULL,
    CHECK (
        (
            source_kind = 'project'
            AND project_id IS NOT NULL
            AND source_identity = 'project:' || project_id
        )
        OR
        (
            source_kind = 'legacy_json'
            AND project_id IS NULL
            AND source_identity GLOB 'legacy:?*'
        )
    ),
    UNIQUE(version_id, source_identity, source_relpath, source_hash)
);

CREATE TABLE capsule_assets (
    asset_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES capsule_versions(version_id),
    logical_path TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (
        media_type IN ('image/png', 'image/jpeg', 'image/webp')
    ),
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0 AND size_bytes <= 1048576),
    width INTEGER NOT NULL CHECK (width >= 1 AND width <= 4096),
    height INTEGER NOT NULL CHECK (height >= 1 AND height <= 4096),
    content BLOB NOT NULL,
    UNIQUE(version_id, logical_path)
);

CREATE TABLE capsule_status_events (
    event_id TEXT PRIMARY KEY,
    capsule_id TEXT NOT NULL REFERENCES capsules(capsule_id),
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'enabled',
            'disabled',
            'revalidation_required',
            'current_version_changed',
            'usage_scope_changed'
        )
    ),
    from_status TEXT,
    to_status TEXT,
    version_id TEXT REFERENCES capsule_versions(version_id),
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE product_capsule_usage (
    usage_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    capsule_id TEXT NOT NULL REFERENCES capsules(capsule_id),
    version_id TEXT NOT NULL REFERENCES capsule_versions(version_id),
    capability_key TEXT NOT NULL,
    role_key TEXT NOT NULL,
    variant_key TEXT NOT NULL,
    usage_scope_json TEXT NOT NULL,
    contribution_role TEXT NOT NULL CHECK (
        contribution_role IN (
            'presentation',
            'interaction',
            'computation',
            'asset',
            'wiring'
        )
    ),
    generated_at TEXT NOT NULL,
    UNIQUE(product_id, version_id, contribution_role)
);

CREATE TABLE legacy_capsule_aliases (
    alias_id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL REFERENCES intake_runs(run_id),
    legacy_file_hash TEXT NOT NULL,
    legacy_capsule_id TEXT NOT NULL,
    relationship TEXT NOT NULL CHECK (
        relationship IN (
            'exact',
            'cleaned_successor',
            'merged',
            'variant',
            'rejected',
            'pending'
        )
    ),
    new_capsule_id TEXT REFERENCES capsules(capsule_id),
    new_version_id TEXT REFERENCES capsule_versions(version_id),
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (
        (new_capsule_id IS NULL AND new_version_id IS NULL)
        OR
        (new_capsule_id IS NOT NULL AND new_version_id IS NOT NULL)
    ),
    UNIQUE(import_run_id, legacy_capsule_id)
);

CREATE INDEX idx_projects_root ON projects(source_root_id);
CREATE INDEX idx_intake_runs_project ON intake_runs(project_id, created_at);
CREATE INDEX idx_review_items_status ON review_items(candidate_status, created_at);
CREATE INDEX idx_review_content_decision ON review_items(
    project_id,
    source_relpath,
    source_hash,
    redaction_rules_version
);
CREATE INDEX idx_capsules_group ON capsules(capability_key, role_key, variant_key);
CREATE INDEX idx_capsule_versions_hash ON capsule_versions(canonical_hash);
CREATE INDEX idx_capsule_versions_capsule ON capsule_versions(capsule_id, version_number);
CREATE INDEX idx_capsule_sources_project ON capsule_sources(project_id);
CREATE INDEX idx_usage_product ON product_capsule_usage(product_id);

CREATE TRIGGER warehouse_state_update_guard
BEFORE UPDATE ON warehouse_state
WHEN NEW.singleton_id <> OLD.singleton_id
  OR NEW.warehouse_revision < OLD.warehouse_revision
  OR NEW.last_backed_up_revision < OLD.last_backed_up_revision
BEGIN
    SELECT RAISE(ABORT, 'warehouse_state_must_be_monotonic');
END;

CREATE TRIGGER warehouse_state_no_delete
BEFORE DELETE ON warehouse_state
BEGIN
    SELECT RAISE(ABORT, 'warehouse_state_delete_forbidden');
END;

CREATE TRIGGER review_items_source_binding_immutable
BEFORE UPDATE ON review_items
WHEN NEW.project_id IS NOT OLD.project_id
  OR NEW.source_relpath <> OLD.source_relpath
  OR NEW.source_hash <> OLD.source_hash
  OR NEW.redaction_rules_version <> OLD.redaction_rules_version
BEGIN
    SELECT RAISE(ABORT, 'review_source_binding_immutable');
END;

CREATE TRIGGER review_items_content_decision_once
BEFORE UPDATE ON review_items
WHEN (OLD.sensitivity_decision IS NOT NULL AND NEW.sensitivity_decision IS NOT OLD.sensitivity_decision)
  OR (OLD.sensitivity_decided_at IS NOT NULL AND NEW.sensitivity_decided_at IS NOT OLD.sensitivity_decided_at)
  OR (OLD.brand_decision IS NOT NULL AND NEW.brand_decision IS NOT OLD.brand_decision)
  OR (OLD.brand_decided_at IS NOT NULL AND NEW.brand_decided_at IS NOT OLD.brand_decided_at)
  OR (OLD.asset_decision IS NOT NULL AND NEW.asset_decision IS NOT OLD.asset_decision)
  OR (OLD.asset_decided_at IS NOT NULL AND NEW.asset_decided_at IS NOT OLD.asset_decided_at)
BEGIN
    SELECT RAISE(ABORT, 'review_content_decision_immutable');
END;

CREATE TRIGGER capability_groups_update_guard
BEFORE UPDATE ON capability_groups
WHEN NEW.capability_key <> OLD.capability_key
  OR NEW.created_at <> OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'capability_group_only_display_name_mutable');
END;

CREATE TRIGGER capability_groups_no_delete
BEFORE DELETE ON capability_groups
BEGIN
    SELECT RAISE(ABORT, 'capability_group_delete_forbidden');
END;

CREATE TRIGGER capsules_identity_immutable
BEFORE UPDATE ON capsules
WHEN NEW.capsule_id <> OLD.capsule_id
  OR NEW.capability_key <> OLD.capability_key
  OR NEW.role_key <> OLD.role_key
  OR NEW.variant_key <> OLD.variant_key
  OR NEW.capability_kind <> OLD.capability_kind
  OR NEW.created_at <> OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'capsule_identity_immutable');
END;

CREATE TRIGGER capsules_no_delete
BEFORE DELETE ON capsules
BEGIN
    SELECT RAISE(ABORT, 'capsule_delete_forbidden');
END;

CREATE TRIGGER capsules_insert_not_active
BEFORE INSERT ON capsules
WHEN NEW.status = 'active' OR NEW.current_version_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'new_capsule_requires_version_before_activation');
END;

CREATE TRIGGER capsules_active_requires_current_version
BEFORE UPDATE ON capsules
WHEN NEW.status = 'active' AND NEW.current_version_id IS NULL
BEGIN
    SELECT RAISE(ABORT, 'active_capsule_requires_current_version');
END;

CREATE TRIGGER capsules_current_version_belongs_to_capsule
BEFORE UPDATE OF current_version_id ON capsules
WHEN NEW.current_version_id IS NOT NULL
 AND NOT EXISTS (
     SELECT 1
     FROM capsule_versions v
     WHERE v.version_id = NEW.current_version_id
       AND v.capsule_id = NEW.capsule_id
 )
BEGIN
    SELECT RAISE(ABORT, 'current_version_capsule_mismatch');
END;

CREATE TRIGGER capsules_status_transition
BEFORE UPDATE OF status ON capsules
WHEN NEW.status <> OLD.status
 AND NOT (
     (OLD.status = 'active' AND NEW.status IN ('pending_revalidation', 'disabled'))
     OR
     (OLD.status = 'pending_revalidation' AND NEW.status IN ('active', 'disabled'))
     OR
     (OLD.status = 'disabled' AND NEW.status = 'active')
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid_capsule_status_transition');
END;

CREATE TRIGGER capsule_versions_no_update
BEFORE UPDATE ON capsule_versions
BEGIN
    SELECT RAISE(ABORT, 'capsule_version_immutable');
END;

CREATE TRIGGER capsule_versions_no_delete
BEFORE DELETE ON capsule_versions
BEGIN
    SELECT RAISE(ABORT, 'capsule_version_delete_forbidden');
END;

CREATE TRIGGER capsule_sources_no_update
BEFORE UPDATE ON capsule_sources
BEGIN
    SELECT RAISE(ABORT, 'capsule_source_immutable');
END;

CREATE TRIGGER capsule_sources_no_delete
BEFORE DELETE ON capsule_sources
BEGIN
    SELECT RAISE(ABORT, 'capsule_source_delete_forbidden');
END;

CREATE TRIGGER capsule_sources_canonical_relationship
BEFORE INSERT ON capsule_sources
WHEN NEW.relationship IN ('exact', 'published_implementation')
 AND NOT EXISTS (
     SELECT 1
     FROM capsule_versions v
     WHERE v.version_id = NEW.version_id
       AND v.canonical_hash = NEW.candidate_canonical_hash
 )
BEGIN
    SELECT RAISE(ABORT, 'capsule_source_canonical_mismatch');
END;

CREATE TRIGGER capsule_assets_no_update
BEFORE UPDATE ON capsule_assets
BEGIN
    SELECT RAISE(ABORT, 'capsule_asset_immutable');
END;

CREATE TRIGGER capsule_assets_no_delete
BEFORE DELETE ON capsule_assets
BEGIN
    SELECT RAISE(ABORT, 'capsule_asset_delete_forbidden');
END;

CREATE TRIGGER capsule_status_events_no_update
BEFORE UPDATE ON capsule_status_events
BEGIN
    SELECT RAISE(ABORT, 'capsule_status_event_immutable');
END;

CREATE TRIGGER capsule_status_events_no_delete
BEFORE DELETE ON capsule_status_events
BEGIN
    SELECT RAISE(ABORT, 'capsule_status_event_delete_forbidden');
END;

CREATE TRIGGER capsule_status_events_version_belongs_to_capsule
BEFORE INSERT ON capsule_status_events
WHEN NEW.version_id IS NOT NULL
 AND NOT EXISTS (
     SELECT 1
     FROM capsule_versions v
     WHERE v.version_id = NEW.version_id
       AND v.capsule_id = NEW.capsule_id
 )
BEGIN
    SELECT RAISE(ABORT, 'status_event_version_capsule_mismatch');
END;

CREATE TRIGGER capsule_status_events_match_state
BEFORE INSERT ON capsule_status_events
WHEN NOT EXISTS (
    SELECT 1
    FROM capsules c
    WHERE c.capsule_id = NEW.capsule_id
      AND c.status = NEW.to_status
      AND (
          (NEW.event_type = 'enabled'
           AND NEW.from_status IN ('pending_revalidation', 'disabled')
           AND NEW.to_status = 'active')
          OR
          (NEW.event_type = 'disabled'
           AND NEW.from_status IN ('active', 'pending_revalidation')
           AND NEW.to_status = 'disabled')
          OR
          (NEW.event_type = 'revalidation_required'
           AND NEW.from_status = 'active'
           AND NEW.to_status = 'pending_revalidation')
          OR
          (NEW.event_type = 'current_version_changed'
           AND NEW.from_status IN ('active', 'pending_revalidation', 'disabled')
           AND NEW.to_status = 'active')
          OR
          (NEW.event_type = 'usage_scope_changed'
           AND NEW.from_status IN ('active', 'pending_revalidation')
           AND NEW.to_status = NEW.from_status
           AND NEW.to_status = c.status)
      )
      AND NEW.version_id = c.current_version_id
)
BEGIN
    SELECT RAISE(ABORT, 'status_event_state_mismatch');
END;

CREATE TRIGGER product_capsule_usage_matches_version
BEFORE INSERT ON product_capsule_usage
WHEN NOT EXISTS (
    SELECT 1
    FROM capsules c
    JOIN capsule_versions v ON v.capsule_id = c.capsule_id
    WHERE c.capsule_id = NEW.capsule_id
      AND v.version_id = NEW.version_id
      AND c.current_version_id = NEW.version_id
      AND c.status = 'active'
      AND c.capability_key = NEW.capability_key
      AND c.role_key = NEW.role_key
      AND c.variant_key = NEW.variant_key
      AND v.usage_scope_json = NEW.usage_scope_json
)
BEGIN
    SELECT RAISE(ABORT, 'product_usage_not_generation_eligible');
END;

CREATE TRIGGER product_capsule_usage_manifest_consistent
BEFORE INSERT ON product_capsule_usage
WHEN EXISTS (
    SELECT 1
    FROM product_capsule_usage u
    WHERE u.product_id = NEW.product_id
      AND u.manifest_digest <> NEW.manifest_digest
)
BEGIN
    SELECT RAISE(ABORT, 'product_manifest_digest_mismatch');
END;

CREATE TRIGGER product_capsule_usage_no_update
BEFORE UPDATE ON product_capsule_usage
BEGIN
    SELECT RAISE(ABORT, 'product_usage_immutable');
END;

CREATE TRIGGER product_capsule_usage_no_delete
BEFORE DELETE ON product_capsule_usage
BEGIN
    SELECT RAISE(ABORT, 'product_usage_delete_forbidden');
END;

CREATE TRIGGER legacy_capsule_aliases_no_update
BEFORE UPDATE ON legacy_capsule_aliases
BEGIN
    SELECT RAISE(ABORT, 'legacy_alias_immutable');
END;

CREATE TRIGGER legacy_capsule_aliases_no_delete
BEFORE DELETE ON legacy_capsule_aliases
BEGIN
    SELECT RAISE(ABORT, 'legacy_alias_delete_forbidden');
END;

CREATE TRIGGER legacy_capsule_aliases_target_matches
BEFORE INSERT ON legacy_capsule_aliases
WHEN NEW.new_version_id IS NOT NULL
 AND NOT EXISTS (
     SELECT 1
     FROM capsule_versions v
     WHERE v.version_id = NEW.new_version_id
       AND v.capsule_id = NEW.new_capsule_id
 )
BEGIN
    SELECT RAISE(ABORT, 'legacy_alias_version_capsule_mismatch');
END;

CREATE TRIGGER legacy_capsule_aliases_contract
BEFORE INSERT ON legacy_capsule_aliases
WHEN NOT EXISTS (
    SELECT 1
    FROM intake_runs r
    WHERE r.run_id = NEW.import_run_id
      AND r.run_kind = 'legacy_import'
      AND r.legacy_source_file_hash = NEW.legacy_file_hash
)
 OR NOT (
    (
        NEW.relationship IN ('exact', 'cleaned_successor', 'merged', 'variant')
        AND NEW.new_capsule_id IS NOT NULL
        AND NEW.new_version_id IS NOT NULL
    )
    OR
    (
        NEW.relationship IN ('rejected', 'pending')
        AND NEW.new_capsule_id IS NULL
        AND NEW.new_version_id IS NULL
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'legacy_alias_contract_mismatch');
END;
"""

SCHEMA_TABLES_SQL_V2 = r"""
CREATE TABLE warehouse_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    warehouse_revision INTEGER NOT NULL DEFAULT 0 CHECK (warehouse_revision >= 0),
    last_backed_up_revision INTEGER NOT NULL DEFAULT 0
        CHECK (
            last_backed_up_revision >= 0
            AND last_backed_up_revision <= warehouse_revision
        )
);

CREATE TABLE app_settings (
    setting_key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE source_roots (
    root_id TEXT PRIMARY KEY,
    root_kind TEXT NOT NULL CHECK (root_kind IN ('single_project', 'project_collection')),
    current_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('bound', 'source_missing')),
    brand_profile_id TEXT,
    brand_profile_json TEXT,
    brand_profile_digest TEXT,
    brand_profile_version INTEGER NOT NULL DEFAULT 0 CHECK (brand_profile_version >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (
            brand_profile_id IS NULL
            AND brand_profile_json IS NULL
            AND brand_profile_digest IS NULL
            AND brand_profile_version = 0
        )
        OR
        (
            brand_profile_id IS NOT NULL
            AND brand_profile_json IS NOT NULL
            AND brand_profile_digest IS NOT NULL
            AND brand_profile_version >= 1
        )
    )
);

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    source_root_id TEXT NOT NULL REFERENCES source_roots(root_id),
    source_type TEXT NOT NULL CHECK (
        source_type IN ('static_web', 'javascript_computation_source')
    ),
    project_relpath TEXT NOT NULL,
    entry_relpath TEXT,
    display_name TEXT NOT NULL,
    project_state TEXT NOT NULL CHECK (
        project_state IN (
            'discovered_unconfirmed',
            'ready',
            'unsupported_v1',
            'source_missing'
        )
    ),
    discovery_signature TEXT NOT NULL,
    last_snapshot_hash TEXT,
    brand_mode TEXT NOT NULL DEFAULT 'inherit' CHECK (
        brand_mode IN ('inherit', 'extend', 'replace', 'clear')
    ),
    brand_profile_id TEXT,
    brand_profile_json TEXT,
    brand_profile_digest TEXT,
    brand_profile_version INTEGER NOT NULL DEFAULT 0 CHECK (
        brand_profile_version >= 0
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (
            source_type = 'static_web'
            AND entry_relpath IS NOT NULL
            AND length(entry_relpath) > 0
        )
        OR
        (
            source_type = 'javascript_computation_source'
            AND entry_relpath IS NULL
        )
    ),
    CHECK (
        (
            brand_profile_id IS NULL
            AND brand_profile_json IS NULL
            AND brand_profile_digest IS NULL
            AND brand_profile_version = 0
        )
        OR
        (
            brand_profile_id IS NOT NULL
            AND brand_profile_json IS NOT NULL
            AND brand_profile_digest IS NOT NULL
            AND brand_profile_version >= 1
        )
    )
);

CREATE TABLE project_file_index (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    logical_path TEXT NOT NULL,
    entry_kind TEXT NOT NULL
        CHECK (entry_kind IN ('javascript_module', 'symlink')),
    size_bytes INTEGER,
    content_sha256 TEXT,
    PRIMARY KEY (project_id, logical_path),
    CHECK (
        (
            entry_kind = 'javascript_module'
            AND size_bytes IS NOT NULL
            AND size_bytes >= 0
            AND content_sha256 IS NOT NULL
            AND length(content_sha256) = 64
            AND content_sha256 NOT GLOB '*[^0-9a-f]*'
        )
        OR
        (
            entry_kind = 'symlink'
            AND size_bytes IS NULL
            AND content_sha256 IS NULL
        )
    )
);

CREATE TABLE intake_runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(project_id),
    run_kind TEXT NOT NULL CHECK (
        run_kind IN (
            'refresh_project',
            'refresh_all_child',
            'legacy_import',
            'brand_revalidation',
            'javascript_computation_scan',
            'javascript_computation_capture'
        )
    ),
    status TEXT NOT NULL CHECK (
        status IN (
            'queued',
            'running',
            'no_change',
            'completed',
            'completed_with_pending',
            'failed',
            'cancelled',
            'interrupted'
        )
    ),
    snapshot_before TEXT,
    snapshot_after TEXT,
    extraction_contract_version TEXT NOT NULL,
    redaction_rules_version TEXT NOT NULL,
    security_rules_version TEXT NOT NULL,
    supervision_rules_version TEXT NOT NULL,
    validation_contract_version TEXT NOT NULL,
    canonicalization_version INTEGER NOT NULL,
    counts_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    legacy_source_path_hash TEXT,
    legacy_source_file_hash TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE review_items (
    review_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES intake_runs(run_id),
    project_id TEXT REFERENCES projects(project_id),
    candidate_id TEXT NOT NULL,
    candidate_status TEXT NOT NULL CHECK (
        candidate_status IN (
            'extracted',
            'waiting_user',
            'waiting_model',
            'waiting_validation',
            'review_required',
            'publishable',
            'published',
            'duplicate',
            'merged',
            'rejected'
        )
    ),
    source_relpath TEXT NOT NULL,
    source_location_json TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    redaction_rules_version TEXT NOT NULL,
    candidate_canonical_hash TEXT,
    sanitized_candidate_json TEXT NOT NULL,
    redaction_summary_json TEXT NOT NULL,
    supervision_result_json TEXT,
    supervision_response_hash TEXT,
    equivalence_comparison_json TEXT,
    sensitivity_decision TEXT CHECK (
        sensitivity_decision IS NULL OR sensitivity_decision IN (
            'confirm_fictional_fixture',
            'confirm_safe_redaction',
            'confirm_real_record_reject'
        )
    ),
    sensitivity_decided_at TEXT,
    brand_decision TEXT CHECK (
        brand_decision IS NULL OR brand_decision IN (
            'remove_brand',
            'retain_brand_limited'
        )
    ),
    brand_decided_at TEXT,
    asset_decision TEXT CHECK (
        asset_decision IS NULL
        OR asset_decision = 'confirm_assets_contain_no_real_records'
    ),
    asset_decided_at TEXT,
    enum_decision TEXT CHECK (
        enum_decision IS NULL
        OR enum_decision = 'confirm_selected_string_enumeration'
    ),
    enum_decision_binding_sha256 TEXT CHECK (
        enum_decision_binding_sha256 IS NULL
        OR (
            length(enum_decision_binding_sha256) = 64
            AND enum_decision_binding_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    enum_decided_at TEXT,
    decision TEXT CHECK (
        decision IS NULL OR decision IN (
            'merge_existing',
            'replace_current',
            'create_variant',
            'semantic_split',
            'publish_general',
            'publish_brand_limited',
            'reject'
        )
    ),
    retained_version_id TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (sensitivity_decision IS NULL AND sensitivity_decided_at IS NULL)
        OR
        (
            sensitivity_decision IS NOT NULL
            AND sensitivity_decided_at IS NOT NULL
            AND project_id IS NOT NULL
        )
    ),
    CHECK (
        (brand_decision IS NULL AND brand_decided_at IS NULL)
        OR
        (
            brand_decision IS NOT NULL
            AND brand_decided_at IS NOT NULL
            AND project_id IS NOT NULL
        )
    ),
    CHECK (
        (asset_decision IS NULL AND asset_decided_at IS NULL)
        OR
        (
            asset_decision IS NOT NULL
            AND asset_decided_at IS NOT NULL
            AND project_id IS NOT NULL
        )
    ),
    CHECK (
        (
            enum_decision IS NULL
            AND enum_decision_binding_sha256 IS NULL
            AND enum_decided_at IS NULL
        )
        OR
        (
            enum_decision = 'confirm_selected_string_enumeration'
            AND enum_decision_binding_sha256 IS NOT NULL
            AND enum_decided_at IS NOT NULL
            AND project_id IS NOT NULL
        )
    )
);

CREATE TABLE capability_groups (
    capability_key TEXT PRIMARY KEY CHECK (
        length(capability_key) > 0
        AND capability_key NOT GLOB '*[^a-z0-9_]*'
        AND capability_key NOT GLOB '[0-9]*'
    ),
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE capsules (
    capsule_id TEXT PRIMARY KEY,
    capability_key TEXT NOT NULL REFERENCES capability_groups(capability_key),
    role_key TEXT NOT NULL CHECK (
        length(role_key) > 0
        AND role_key NOT GLOB '*[^a-z0-9_]*'
        AND role_key NOT GLOB '[0-9]*'
    ),
    variant_key TEXT NOT NULL CHECK (
        length(variant_key) > 0
        AND variant_key NOT GLOB '*[^a-z0-9_]*'
        AND variant_key NOT GLOB '[0-9]*'
    ),
    capability_kind TEXT NOT NULL CHECK (
        capability_kind IN ('presentation', 'interaction', 'computation')
    ),
    status TEXT NOT NULL CHECK (
        status IN ('active', 'pending_revalidation', 'disabled')
    ),
    current_version_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(capability_key, role_key, variant_key),
    FOREIGN KEY(current_version_id) REFERENCES capsule_versions(version_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE capsule_versions (
    version_id TEXT PRIMARY KEY,
    capsule_id TEXT NOT NULL REFERENCES capsules(capsule_id),
    version_number INTEGER NOT NULL CHECK (version_number >= 1),
    extraction_contract_version TEXT NOT NULL,
    extraction_summary_json TEXT NOT NULL,
    redaction_rules_version TEXT NOT NULL,
    canonicalization_version INTEGER NOT NULL,
    canonical_hash TEXT NOT NULL,
    activation_json TEXT NOT NULL,
    input_contract_json TEXT NOT NULL,
    output_contract_json TEXT NOT NULL,
    error_contract_json TEXT NOT NULL,
    runtime_allowlist_json TEXT NOT NULL,
    dom_scope_json TEXT NOT NULL,
    usage_scope_json TEXT NOT NULL,
    html_text TEXT NOT NULL DEFAULT '',
    css_text TEXT NOT NULL DEFAULT '',
    javascript_modules_json TEXT NOT NULL DEFAULT '[]',
    cleaning_summary_json TEXT NOT NULL,
    security_rules_version TEXT NOT NULL,
    supervision_rules_version TEXT NOT NULL,
    supervision_model_name TEXT NOT NULL,
    supervision_model_digest TEXT NOT NULL,
    supervised_at TEXT NOT NULL,
    supervision_result_json TEXT NOT NULL,
    supervision_response_hash TEXT NOT NULL,
    validation_contract_version TEXT NOT NULL,
    validation_result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(capsule_id, version_number)
);

CREATE TABLE capsule_sources (
    source_link_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES capsule_versions(version_id),
    project_id TEXT REFERENCES projects(project_id),
    source_identity TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('project', 'legacy_json')),
    source_relpath TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    candidate_canonical_hash TEXT NOT NULL,
    relationship TEXT NOT NULL CHECK (
        relationship IN ('exact', 'human_equivalent', 'published_implementation')
    ),
    read_at TEXT NOT NULL,
    CHECK (
        (
            source_kind = 'project'
            AND project_id IS NOT NULL
            AND source_identity = 'project:' || project_id
        )
        OR
        (
            source_kind = 'legacy_json'
            AND project_id IS NULL
            AND source_identity GLOB 'legacy:?*'
        )
    ),
    UNIQUE(version_id, source_identity, source_relpath, source_hash)
);

CREATE TABLE capsule_assets (
    asset_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES capsule_versions(version_id),
    logical_path TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (
        media_type IN ('image/png', 'image/jpeg', 'image/webp')
    ),
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0 AND size_bytes <= 1048576),
    width INTEGER NOT NULL CHECK (width >= 1 AND width <= 4096),
    height INTEGER NOT NULL CHECK (height >= 1 AND height <= 4096),
    content BLOB NOT NULL,
    UNIQUE(version_id, logical_path)
);

CREATE TABLE capsule_status_events (
    event_id TEXT PRIMARY KEY,
    capsule_id TEXT NOT NULL REFERENCES capsules(capsule_id),
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'enabled',
            'disabled',
            'revalidation_required',
            'current_version_changed',
            'usage_scope_changed'
        )
    ),
    from_status TEXT,
    to_status TEXT,
    version_id TEXT REFERENCES capsule_versions(version_id),
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE product_capsule_usage (
    usage_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    capsule_id TEXT NOT NULL REFERENCES capsules(capsule_id),
    version_id TEXT NOT NULL REFERENCES capsule_versions(version_id),
    capability_key TEXT NOT NULL,
    role_key TEXT NOT NULL,
    variant_key TEXT NOT NULL,
    usage_scope_json TEXT NOT NULL,
    contribution_role TEXT NOT NULL CHECK (
        contribution_role IN (
            'presentation',
            'interaction',
            'computation',
            'asset',
            'wiring'
        )
    ),
    generated_at TEXT NOT NULL,
    UNIQUE(product_id, version_id, contribution_role)
);

CREATE TABLE legacy_capsule_aliases (
    alias_id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL REFERENCES intake_runs(run_id),
    legacy_file_hash TEXT NOT NULL,
    legacy_capsule_id TEXT NOT NULL,
    relationship TEXT NOT NULL CHECK (
        relationship IN (
            'exact',
            'cleaned_successor',
            'merged',
            'variant',
            'rejected',
            'pending'
        )
    ),
    new_capsule_id TEXT REFERENCES capsules(capsule_id),
    new_version_id TEXT REFERENCES capsule_versions(version_id),
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (
        (new_capsule_id IS NULL AND new_version_id IS NULL)
        OR
        (new_capsule_id IS NOT NULL AND new_version_id IS NOT NULL)
    ),
    UNIQUE(import_run_id, legacy_capsule_id)
);
"""

SCHEMA_SEED_SQL_V2 = r"""
INSERT INTO warehouse_state(singleton_id) VALUES (1);
"""

SCHEMA_INDEXES_SQL_V2 = r"""
CREATE INDEX idx_projects_root ON projects(source_root_id);
CREATE UNIQUE INDEX idx_projects_static_entry
ON projects(source_root_id, project_relpath, entry_relpath)
WHERE source_type = 'static_web';
CREATE UNIQUE INDEX idx_projects_js_scope
ON projects(source_root_id, project_relpath)
WHERE source_type = 'javascript_computation_source';
CREATE INDEX idx_intake_runs_project ON intake_runs(project_id, created_at);
CREATE INDEX idx_review_items_status ON review_items(candidate_status, created_at);
CREATE INDEX idx_review_content_decision ON review_items(
    project_id, source_relpath, source_hash, redaction_rules_version
);
CREATE INDEX idx_capsules_group ON capsules(capability_key, role_key, variant_key);
CREATE INDEX idx_capsule_versions_hash ON capsule_versions(canonical_hash);
CREATE INDEX idx_capsule_versions_capsule
ON capsule_versions(capsule_id, version_number);
CREATE INDEX idx_capsule_sources_project ON capsule_sources(project_id);
CREATE INDEX idx_usage_product ON product_capsule_usage(product_id);
"""

SCHEMA_TRIGGERS_SQL_V2 = r"""
CREATE TRIGGER warehouse_state_update_guard
BEFORE UPDATE ON warehouse_state
WHEN NEW.singleton_id <> OLD.singleton_id
  OR NEW.warehouse_revision < OLD.warehouse_revision
  OR NEW.last_backed_up_revision < OLD.last_backed_up_revision
BEGIN
    SELECT RAISE(ABORT, 'warehouse_state_must_be_monotonic');
END;

CREATE TRIGGER warehouse_state_no_delete
BEFORE DELETE ON warehouse_state
BEGIN
    SELECT RAISE(ABORT, 'warehouse_state_delete_forbidden');
END;

CREATE TRIGGER review_items_source_binding_immutable
BEFORE UPDATE ON review_items
WHEN NEW.project_id IS NOT OLD.project_id
  OR NEW.source_relpath <> OLD.source_relpath
  OR NEW.source_hash <> OLD.source_hash
  OR NEW.redaction_rules_version <> OLD.redaction_rules_version
BEGIN
    SELECT RAISE(ABORT, 'review_source_binding_immutable');
END;

CREATE TRIGGER review_items_content_decision_once
BEFORE UPDATE ON review_items
WHEN (OLD.sensitivity_decision IS NOT NULL
      AND NEW.sensitivity_decision IS NOT OLD.sensitivity_decision)
  OR (OLD.sensitivity_decided_at IS NOT NULL
      AND NEW.sensitivity_decided_at IS NOT OLD.sensitivity_decided_at)
  OR (OLD.brand_decision IS NOT NULL
      AND NEW.brand_decision IS NOT OLD.brand_decision)
  OR (OLD.brand_decided_at IS NOT NULL
      AND NEW.brand_decided_at IS NOT OLD.brand_decided_at)
  OR (OLD.asset_decision IS NOT NULL
      AND NEW.asset_decision IS NOT OLD.asset_decision)
  OR (OLD.asset_decided_at IS NOT NULL
      AND NEW.asset_decided_at IS NOT OLD.asset_decided_at)
  OR (OLD.enum_decision IS NOT NULL
      AND NEW.enum_decision IS NOT OLD.enum_decision)
  OR (OLD.enum_decision_binding_sha256 IS NOT NULL
      AND NEW.enum_decision_binding_sha256
          IS NOT OLD.enum_decision_binding_sha256)
  OR (OLD.enum_decided_at IS NOT NULL
      AND NEW.enum_decided_at IS NOT OLD.enum_decided_at)
BEGIN
    SELECT RAISE(ABORT, 'review_content_decision_immutable');
END;

CREATE TRIGGER projects_source_identity_immutable
BEFORE UPDATE ON projects
WHEN NEW.project_id <> OLD.project_id
  OR NEW.source_root_id <> OLD.source_root_id
  OR NEW.source_type <> OLD.source_type
  OR NEW.project_relpath <> OLD.project_relpath
  OR NEW.entry_relpath IS NOT OLD.entry_relpath
BEGIN
    SELECT RAISE(ABORT, 'project_source_identity_immutable');
END;

CREATE TRIGGER project_file_index_owner_insert
BEFORE INSERT ON project_file_index
WHEN NOT EXISTS (
    SELECT 1
    FROM projects p
    WHERE p.project_id = NEW.project_id
      AND p.source_type = 'javascript_computation_source'
)
BEGIN
    SELECT RAISE(ABORT, 'project_file_index_owner_mismatch');
END;

CREATE TRIGGER project_file_index_owner_update
BEFORE UPDATE ON project_file_index
WHEN NEW.project_id <> OLD.project_id
   OR NOT EXISTS (
       SELECT 1
       FROM projects p
       WHERE p.project_id = NEW.project_id
         AND p.source_type = 'javascript_computation_source'
   )
BEGIN
    SELECT RAISE(ABORT, 'project_file_index_owner_mismatch');
END;

CREATE TRIGGER capability_groups_update_guard
BEFORE UPDATE ON capability_groups
WHEN NEW.capability_key <> OLD.capability_key
  OR NEW.created_at <> OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'capability_group_only_display_name_mutable');
END;

CREATE TRIGGER capability_groups_no_delete
BEFORE DELETE ON capability_groups
BEGIN
    SELECT RAISE(ABORT, 'capability_group_delete_forbidden');
END;

CREATE TRIGGER capsules_identity_immutable
BEFORE UPDATE ON capsules
WHEN NEW.capsule_id <> OLD.capsule_id
  OR NEW.capability_key <> OLD.capability_key
  OR NEW.role_key <> OLD.role_key
  OR NEW.variant_key <> OLD.variant_key
  OR NEW.capability_kind <> OLD.capability_kind
  OR NEW.created_at <> OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'capsule_identity_immutable');
END;

CREATE TRIGGER capsules_no_delete
BEFORE DELETE ON capsules
BEGIN
    SELECT RAISE(ABORT, 'capsule_delete_forbidden');
END;

CREATE TRIGGER capsules_insert_not_active
BEFORE INSERT ON capsules
WHEN NEW.status = 'active' OR NEW.current_version_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'new_capsule_requires_version_before_activation');
END;

CREATE TRIGGER capsules_active_requires_current_version
BEFORE UPDATE ON capsules
WHEN NEW.status = 'active' AND NEW.current_version_id IS NULL
BEGIN
    SELECT RAISE(ABORT, 'active_capsule_requires_current_version');
END;

CREATE TRIGGER capsules_current_version_belongs_to_capsule
BEFORE UPDATE OF current_version_id ON capsules
WHEN NEW.current_version_id IS NOT NULL
 AND NOT EXISTS (
     SELECT 1
     FROM capsule_versions v
     WHERE v.version_id = NEW.current_version_id
       AND v.capsule_id = NEW.capsule_id
 )
BEGIN
    SELECT RAISE(ABORT, 'current_version_capsule_mismatch');
END;

CREATE TRIGGER capsules_status_transition
BEFORE UPDATE OF status ON capsules
WHEN NEW.status <> OLD.status
 AND NOT (
     (OLD.status = 'active' AND NEW.status IN ('pending_revalidation', 'disabled'))
     OR
     (OLD.status = 'pending_revalidation' AND NEW.status IN ('active', 'disabled'))
     OR
     (OLD.status = 'disabled' AND NEW.status = 'active')
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid_capsule_status_transition');
END;

CREATE TRIGGER capsule_versions_no_update
BEFORE UPDATE ON capsule_versions
BEGIN
    SELECT RAISE(ABORT, 'capsule_version_immutable');
END;

CREATE TRIGGER capsule_versions_no_delete
BEFORE DELETE ON capsule_versions
BEGIN
    SELECT RAISE(ABORT, 'capsule_version_delete_forbidden');
END;

CREATE TRIGGER capsule_sources_no_update
BEFORE UPDATE ON capsule_sources
BEGIN
    SELECT RAISE(ABORT, 'capsule_source_immutable');
END;

CREATE TRIGGER capsule_sources_no_delete
BEFORE DELETE ON capsule_sources
BEGIN
    SELECT RAISE(ABORT, 'capsule_source_delete_forbidden');
END;

CREATE TRIGGER capsule_sources_canonical_relationship
BEFORE INSERT ON capsule_sources
WHEN NEW.relationship IN ('exact', 'published_implementation')
 AND NOT EXISTS (
     SELECT 1
     FROM capsule_versions v
     WHERE v.version_id = NEW.version_id
       AND v.canonical_hash = NEW.candidate_canonical_hash
 )
BEGIN
    SELECT RAISE(ABORT, 'capsule_source_canonical_mismatch');
END;

CREATE TRIGGER capsule_assets_no_update
BEFORE UPDATE ON capsule_assets
BEGIN
    SELECT RAISE(ABORT, 'capsule_asset_immutable');
END;

CREATE TRIGGER capsule_assets_no_delete
BEFORE DELETE ON capsule_assets
BEGIN
    SELECT RAISE(ABORT, 'capsule_asset_delete_forbidden');
END;

CREATE TRIGGER capsule_status_events_no_update
BEFORE UPDATE ON capsule_status_events
BEGIN
    SELECT RAISE(ABORT, 'capsule_status_event_immutable');
END;

CREATE TRIGGER capsule_status_events_no_delete
BEFORE DELETE ON capsule_status_events
BEGIN
    SELECT RAISE(ABORT, 'capsule_status_event_delete_forbidden');
END;

CREATE TRIGGER capsule_status_events_version_belongs_to_capsule
BEFORE INSERT ON capsule_status_events
WHEN NEW.version_id IS NOT NULL
 AND NOT EXISTS (
     SELECT 1
     FROM capsule_versions v
     WHERE v.version_id = NEW.version_id
       AND v.capsule_id = NEW.capsule_id
 )
BEGIN
    SELECT RAISE(ABORT, 'status_event_version_capsule_mismatch');
END;

CREATE TRIGGER capsule_status_events_match_state
BEFORE INSERT ON capsule_status_events
WHEN NOT EXISTS (
    SELECT 1
    FROM capsules c
    WHERE c.capsule_id = NEW.capsule_id
      AND c.status = NEW.to_status
      AND (
          (NEW.event_type = 'enabled'
           AND NEW.from_status IN ('pending_revalidation', 'disabled')
           AND NEW.to_status = 'active')
          OR
          (NEW.event_type = 'disabled'
           AND NEW.from_status IN ('active', 'pending_revalidation')
           AND NEW.to_status = 'disabled')
          OR
          (NEW.event_type = 'revalidation_required'
           AND NEW.from_status = 'active'
           AND NEW.to_status = 'pending_revalidation')
          OR
          (NEW.event_type = 'current_version_changed'
           AND NEW.from_status IN ('active', 'pending_revalidation', 'disabled')
           AND NEW.to_status = 'active')
          OR
          (NEW.event_type = 'usage_scope_changed'
           AND NEW.from_status IN ('active', 'pending_revalidation')
           AND NEW.to_status = NEW.from_status
           AND NEW.to_status = c.status)
      )
      AND NEW.version_id = c.current_version_id
)
BEGIN
    SELECT RAISE(ABORT, 'status_event_state_mismatch');
END;

CREATE TRIGGER product_capsule_usage_matches_version
BEFORE INSERT ON product_capsule_usage
WHEN NOT EXISTS (
    SELECT 1
    FROM capsules c
    JOIN capsule_versions v ON v.capsule_id = c.capsule_id
    WHERE c.capsule_id = NEW.capsule_id
      AND v.version_id = NEW.version_id
      AND c.current_version_id = NEW.version_id
      AND c.status = 'active'
      AND c.capability_key = NEW.capability_key
      AND c.role_key = NEW.role_key
      AND c.variant_key = NEW.variant_key
      AND v.usage_scope_json = NEW.usage_scope_json
)
BEGIN
    SELECT RAISE(ABORT, 'product_usage_not_generation_eligible');
END;

CREATE TRIGGER product_capsule_usage_manifest_consistent
BEFORE INSERT ON product_capsule_usage
WHEN EXISTS (
    SELECT 1
    FROM product_capsule_usage u
    WHERE u.product_id = NEW.product_id
      AND u.manifest_digest <> NEW.manifest_digest
)
BEGIN
    SELECT RAISE(ABORT, 'product_manifest_digest_mismatch');
END;

CREATE TRIGGER product_capsule_usage_no_update
BEFORE UPDATE ON product_capsule_usage
BEGIN
    SELECT RAISE(ABORT, 'product_usage_immutable');
END;

CREATE TRIGGER product_capsule_usage_no_delete
BEFORE DELETE ON product_capsule_usage
BEGIN
    SELECT RAISE(ABORT, 'product_usage_delete_forbidden');
END;

CREATE TRIGGER legacy_capsule_aliases_no_update
BEFORE UPDATE ON legacy_capsule_aliases
BEGIN
    SELECT RAISE(ABORT, 'legacy_alias_immutable');
END;

CREATE TRIGGER legacy_capsule_aliases_no_delete
BEFORE DELETE ON legacy_capsule_aliases
BEGIN
    SELECT RAISE(ABORT, 'legacy_alias_delete_forbidden');
END;

CREATE TRIGGER legacy_capsule_aliases_target_matches
BEFORE INSERT ON legacy_capsule_aliases
WHEN NEW.new_version_id IS NOT NULL
 AND NOT EXISTS (
     SELECT 1
     FROM capsule_versions v
     WHERE v.version_id = NEW.new_version_id
       AND v.capsule_id = NEW.new_capsule_id
 )
BEGIN
    SELECT RAISE(ABORT, 'legacy_alias_version_capsule_mismatch');
END;

CREATE TRIGGER legacy_capsule_aliases_contract
BEFORE INSERT ON legacy_capsule_aliases
WHEN NOT EXISTS (
    SELECT 1
    FROM intake_runs r
    WHERE r.run_id = NEW.import_run_id
      AND r.run_kind = 'legacy_import'
      AND r.legacy_source_file_hash = NEW.legacy_file_hash
)
 OR NOT (
    (
        NEW.relationship IN ('exact', 'cleaned_successor', 'merged', 'variant')
        AND NEW.new_capsule_id IS NOT NULL
        AND NEW.new_version_id IS NOT NULL
    )
    OR
    (
        NEW.relationship IN ('rejected', 'pending')
        AND NEW.new_capsule_id IS NULL
        AND NEW.new_version_id IS NULL
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'legacy_alias_contract_mismatch');
END;
"""

SCHEMA_SQL = SCHEMA_SQL_V1
SCHEMA_SQL_V2 = "\n".join(
    (
        SCHEMA_TABLES_SQL_V2,
        SCHEMA_SEED_SQL_V2,
        SCHEMA_INDEXES_SQL_V2,
        SCHEMA_TRIGGERS_SQL_V2,
    )
)

MIGRATE_V1_TO_V2_COPY_SQL = r"""
INSERT INTO main.warehouse_state (
    singleton_id, warehouse_revision, last_backed_up_revision
)
SELECT singleton_id, warehouse_revision, last_backed_up_revision
FROM v1.warehouse_state;

INSERT INTO main.app_settings (setting_key, value_json, updated_at)
SELECT setting_key, value_json, updated_at
FROM v1.app_settings;

INSERT INTO main.source_roots (
    root_id, root_kind, current_path, status, brand_profile_id,
    brand_profile_json, brand_profile_digest, brand_profile_version,
    created_at, updated_at
)
SELECT
    root_id, root_kind, current_path, status, brand_profile_id,
    brand_profile_json, brand_profile_digest, brand_profile_version,
    created_at, updated_at
FROM v1.source_roots;

INSERT INTO main.projects (
    project_id, source_root_id, source_type, project_relpath, entry_relpath,
    display_name, project_state, discovery_signature, last_snapshot_hash,
    brand_mode, brand_profile_id, brand_profile_json, brand_profile_digest,
    brand_profile_version, created_at, updated_at
)
SELECT
    project_id, source_root_id, 'static_web', project_relpath, entry_relpath,
    display_name, project_state, discovery_signature, last_snapshot_hash,
    brand_mode, brand_profile_id, brand_profile_json, brand_profile_digest,
    brand_profile_version, created_at, updated_at
FROM v1.projects;

INSERT INTO main.intake_runs (
    run_id, project_id, run_kind, status, snapshot_before, snapshot_after,
    extraction_contract_version, redaction_rules_version,
    security_rules_version, supervision_rules_version,
    validation_contract_version, canonicalization_version, counts_json,
    error_code, legacy_source_path_hash, legacy_source_file_hash,
    started_at, completed_at, created_at
)
SELECT
    run_id, project_id, run_kind, status, snapshot_before, snapshot_after,
    extraction_contract_version, redaction_rules_version,
    security_rules_version, supervision_rules_version,
    validation_contract_version, canonicalization_version, counts_json,
    error_code, legacy_source_path_hash, legacy_source_file_hash,
    started_at, completed_at, created_at
FROM v1.intake_runs;

INSERT INTO main.review_items (
    review_id, run_id, project_id, candidate_id, candidate_status,
    source_relpath, source_location_json, source_hash,
    redaction_rules_version, candidate_canonical_hash,
    sanitized_candidate_json, redaction_summary_json,
    supervision_result_json, supervision_response_hash,
    equivalence_comparison_json, sensitivity_decision,
    sensitivity_decided_at, brand_decision, brand_decided_at,
    asset_decision, asset_decided_at, enum_decision,
    enum_decision_binding_sha256, enum_decided_at, decision,
    retained_version_id, decided_at, created_at, updated_at
)
SELECT
    review_id, run_id, project_id, candidate_id, candidate_status,
    source_relpath, source_location_json, source_hash,
    redaction_rules_version, candidate_canonical_hash,
    sanitized_candidate_json, redaction_summary_json,
    supervision_result_json, supervision_response_hash,
    equivalence_comparison_json, sensitivity_decision,
    sensitivity_decided_at, brand_decision, brand_decided_at,
    asset_decision, asset_decided_at, NULL, NULL, NULL, decision,
    retained_version_id, decided_at, created_at, updated_at
FROM v1.review_items;

INSERT INTO main.capability_groups (
    capability_key, display_name, created_at, updated_at
)
SELECT capability_key, display_name, created_at, updated_at
FROM v1.capability_groups;

INSERT INTO main.capsules (
    capsule_id, capability_key, role_key, variant_key, capability_kind,
    status, current_version_id, created_at
)
SELECT
    capsule_id, capability_key, role_key, variant_key, capability_kind,
    status, current_version_id, created_at
FROM v1.capsules;

INSERT INTO main.capsule_versions (
    version_id, capsule_id, version_number, extraction_contract_version,
    extraction_summary_json, redaction_rules_version,
    canonicalization_version, canonical_hash, activation_json,
    input_contract_json, output_contract_json, error_contract_json,
    runtime_allowlist_json, dom_scope_json, usage_scope_json, html_text,
    css_text, javascript_modules_json, cleaning_summary_json,
    security_rules_version, supervision_rules_version,
    supervision_model_name, supervision_model_digest, supervised_at,
    supervision_result_json, supervision_response_hash,
    validation_contract_version, validation_result_json, created_at
)
SELECT
    version_id, capsule_id, version_number, extraction_contract_version,
    extraction_summary_json, redaction_rules_version,
    canonicalization_version, canonical_hash, activation_json,
    input_contract_json, output_contract_json, error_contract_json,
    runtime_allowlist_json, dom_scope_json, usage_scope_json, html_text,
    css_text, javascript_modules_json, cleaning_summary_json,
    security_rules_version, supervision_rules_version,
    supervision_model_name, supervision_model_digest, supervised_at,
    supervision_result_json, supervision_response_hash,
    validation_contract_version, validation_result_json, created_at
FROM v1.capsule_versions;

INSERT INTO main.capsule_sources (
    source_link_id, version_id, project_id, source_identity, source_kind,
    source_relpath, source_hash, candidate_canonical_hash, relationship,
    read_at
)
SELECT
    source_link_id, version_id, project_id, source_identity, source_kind,
    source_relpath, source_hash, candidate_canonical_hash, relationship,
    read_at
FROM v1.capsule_sources;

INSERT INTO main.capsule_assets (
    asset_id, version_id, logical_path, media_type, sha256, size_bytes,
    width, height, content
)
SELECT
    asset_id, version_id, logical_path, media_type, sha256, size_bytes,
    width, height, content
FROM v1.capsule_assets;

INSERT INTO main.capsule_status_events (
    event_id, capsule_id, event_type, from_status, to_status, version_id,
    reason_code, created_at
)
SELECT
    event_id, capsule_id, event_type, from_status, to_status, version_id,
    reason_code, created_at
FROM v1.capsule_status_events;

INSERT INTO main.product_capsule_usage (
    usage_id, product_id, manifest_digest, capsule_id, version_id,
    capability_key, role_key, variant_key, usage_scope_json,
    contribution_role, generated_at
)
SELECT
    usage_id, product_id, manifest_digest, capsule_id, version_id,
    capability_key, role_key, variant_key, usage_scope_json,
    contribution_role, generated_at
FROM v1.product_capsule_usage;

INSERT INTO main.legacy_capsule_aliases (
    alias_id, import_run_id, legacy_file_hash, legacy_capsule_id,
    relationship, new_capsule_id, new_version_id, reason_code, created_at
)
SELECT
    alias_id, import_run_id, legacy_file_hash, legacy_capsule_id,
    relationship, new_capsule_id, new_version_id, reason_code, created_at
FROM v1.legacy_capsule_aliases;
"""



def capsule_database_path() -> Path:
    return state_dir() / DATABASE_FILENAME


def capsule_backup_dir() -> Path:
    return state_dir() / BACKUP_DIRECTORY


def canonicalize_capsule(payload: dict[str, Any]) -> CanonicalCapsule:
    if type(payload) is not dict:
        raise ValueError("canonical payload must be an object")
    missing = _CANONICAL_FIELDS - payload.keys()
    extra = payload.keys() - _CANONICAL_FIELDS
    if missing or extra:
        raise ValueError(
            f"canonical payload fields mismatch: missing={sorted(missing)}, extra={sorted(extra)}"
        )

    normalized = _normalize_json(payload, "$")
    if normalized["capability_kind"] not in _CAPABILITY_KINDS:
        raise ValueError("invalid capability_kind")
    for key in (
        "activation",
        "input_contract",
        "output_contract",
        "error_contract",
        "dom_scope",
        "usage_scope",
    ):
        if type(normalized[key]) is not dict:
            raise ValueError(f"{key} must be an object")
    for key in ("html", "css"):
        if type(normalized[key]) is not str:
            raise ValueError(f"{key} must be a string")
        normalized[key] = _normalize_source_text(normalized[key])

    normalized["runtime_allowlist"] = _sorted_unique_strings(
        normalized["runtime_allowlist"], "runtime_allowlist"
    )
    dom_scope = normalized["dom_scope"]
    for key in ("selectors", "classes", "attributes", "events"):
        dom_scope[key] = _sorted_unique_strings(dom_scope.get(key, []), f"dom_scope.{key}")

    entry_module = normalized["activation"].get("entry_module")
    if entry_module is not None:
        _validate_logical_path(entry_module, "activation.entry_module")

    normalized["input_contract"] = _normalize_contract(normalized["input_contract"])
    normalized["output_contract"] = _normalize_contract(normalized["output_contract"])
    normalized["error_contract"] = _normalize_contract(normalized["error_contract"])
    normalized["javascript_modules"] = _normalize_modules(normalized["javascript_modules"])
    normalized["assets"] = _normalize_assets(normalized["assets"])

    try:
        json_bytes = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ValueError("canonical payload is not strict UTF-8 JSON") from exc
    return CanonicalCapsule(
        payload=normalized,
        json_bytes=json_bytes,
        sha256=hashlib.sha256(json_bytes).hexdigest(),
    )


def _normalize_json(value: Any, location: str) -> Any:
    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        raise ValueError(f"float is forbidden at {location}")
    if type(value) is str:
        return value
    if type(value) is list:
        return [_normalize_json(item, f"{location}[{index}]") for index, item in enumerate(value)]
    if type(value) is dict:
        out: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"non-string key at {location}")
            if _contains_forbidden_control(key):
                raise ValueError(f"control character in key at {location}")
            normalized_key = key.replace("\r\n", "\n").replace("\r", "\n")
            if normalized_key in out:
                raise ValueError(f"normalized key collision at {location}")
            out[normalized_key] = _normalize_json(item, f"{location}.{normalized_key}")
        return out
    raise ValueError(f"non-JSON value at {location}: {type(value).__name__}")


def _normalize_contract(value: Any) -> Any:
    if type(value) is list:
        return [_normalize_contract(item) for item in value]
    if type(value) is not dict:
        return value
    out = {key: _normalize_contract(item) for key, item in value.items()}
    if "required" in out:
        out["required"] = _sorted_unique_strings(out["required"], "contract.required")
    if "enum" in out:
        if type(out["enum"]) is not list:
            raise ValueError("contract.enum must be an array")
        by_json: dict[str, Any] = {}
        for item in out["enum"]:
            encoded = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            by_json[encoded] = item
        out["enum"] = [by_json[key] for key in sorted(by_json)]
    return out


def _sorted_unique_strings(value: Any, location: str) -> list[str]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise ValueError(f"{location} must be an array of strings")
    if any(_contains_forbidden_control(item) for item in value):
        raise ValueError(f"{location} contains a control character")
    return sorted(set(value))


def _contains_forbidden_control(value: str) -> bool:
    return any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)


def _normalize_source_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_modules(value: Any) -> list[dict[str, str]]:
    if type(value) is not list:
        raise ValueError("javascript_modules must be an array")
    modules: list[dict[str, str]] = []
    paths: set[str] = set()
    for item in value:
        if type(item) is not dict or set(item) != {"path", "source"}:
            raise ValueError("each JavaScript module must contain only path and source")
        path = item["path"]
        source = item["source"]
        _validate_logical_path(path, "javascript_modules.path")
        if type(source) is not str:
            raise ValueError("javascript_modules.source must be a string")
        if path in paths:
            raise ValueError(f"duplicate JavaScript module path: {path}")
        paths.add(path)
        modules.append({"path": path, "source": _normalize_source_text(source)})
    return sorted(modules, key=lambda item: item["path"])


def _normalize_assets(value: Any) -> list[dict[str, str]]:
    if type(value) is not list:
        raise ValueError("assets must be an array")
    assets: list[dict[str, str]] = []
    paths: set[str] = set()
    for item in value:
        if type(item) is not dict or set(item) != {"logical_path", "media_type", "sha256"}:
            raise ValueError("each asset must contain logical_path, media_type, and sha256")
        logical_path = item["logical_path"]
        media_type = item["media_type"]
        digest = item["sha256"]
        _validate_logical_path(logical_path, "assets.logical_path")
        if media_type not in _MEDIA_TYPES:
            raise ValueError(f"invalid asset media_type: {media_type}")
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("asset sha256 must be 64 lowercase hexadecimal characters")
        if logical_path in paths:
            raise ValueError(f"duplicate asset path: {logical_path}")
        paths.add(logical_path)
        assets.append(
            {"logical_path": logical_path, "media_type": media_type, "sha256": digest}
        )
    return sorted(
        assets,
        key=lambda item: (item["logical_path"], item["media_type"], item["sha256"]),
    )


def _validate_logical_path(value: Any, location: str) -> None:
    if (
        type(value) is not str
        or not value
        or _contains_forbidden_control(value)
        or "\\" in value
        or value.startswith("/")
    ):
        raise ValueError(f"invalid logical path at {location}")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"invalid logical path at {location}")


def _database_operation_key(path: Path) -> str:
    return str(path.resolve())


@contextmanager
def _normal_database_operation(path: Path) -> Iterator[None]:
    key = _database_operation_key(path)
    with _STORE_OPERATION_LOCK:
        if key in _EXCLUSIVE_DATABASES:
            raise CapsuleStoreError("exclusive warehouse operation in progress")
        yield


@contextmanager
def _exclusive_database_operation(path: Path) -> Iterator[None]:
    key = _database_operation_key(path)
    with _STORE_OPERATION_LOCK:
        if key in _EXCLUSIVE_DATABASES:
            raise CapsuleStoreError("exclusive warehouse operation in progress")
        _EXCLUSIVE_DATABASES.add(key)
        try:
            yield
        finally:
            _EXCLUSIVE_DATABASES.remove(key)


class CapsuleWarehouseStore:
    """One concrete SQLite implementation; no repository interface or factory."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser().resolve() if path else capsule_database_path()

    def initialize(self) -> Path:
        with _STORE_OPERATION_LOCK:
            _ensure_private_directory(self.path.parent)
            connection = self._connect()
            try:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                tables = _object_names(connection, "table")
                if version == 0:
                    if tables:
                        raise SchemaVersionError(
                            "schema version 0 with existing tables has no tested migration path"
                        )
                    try:
                        connection.executescript(f"BEGIN IMMEDIATE;\n{SCHEMA_SQL}\nCOMMIT;")
                    except BaseException:
                        if connection.in_transaction:
                            connection.rollback()
                        raise
                    version = SCHEMA_VERSION
                elif version not in SUPPORTED_SCHEMA_VERSIONS:
                    raise SchemaVersionError(
                        f"unsupported schema version {version}; "
                        f"expected one of {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
                    )

                mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                if mode == "wal":
                    mode = str(
                        connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
                    ).lower()
                if mode == "wal":
                    raise CapsuleStoreError("WAL mode is forbidden for the warehouse")
                _assert_schema_objects(connection, expected_version=version)
                if version == TARGET_SCHEMA_VERSION:
                    _assert_persistent_data_invariants(connection)
            finally:
                connection.close()
            _ensure_private_file(self.path)
            return self.path

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        with _normal_database_operation(self.path):
            self.initialize()
            connection = _open_read_only(self.path)
            try:
                yield connection
            finally:
                connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with _normal_database_operation(self.path):
            self.initialize()
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                _assert_schema_objects(connection)
                version = int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                )
                if version == TARGET_SCHEMA_VERSION:
                    _assert_persistent_data_invariants(connection)
                foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
                if foreign_keys:
                    raise CapsuleStoreError("foreign_key_check failed")
                connection.commit()
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()

    def current_revision(self) -> int:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT warehouse_revision FROM warehouse_state WHERE singleton_id = 1"
            ).fetchone()
            return int(row[0])

    @staticmethod
    def bump_revision(connection: sqlite3.Connection) -> int:
        connection.execute(
            "UPDATE warehouse_state "
            "SET warehouse_revision = warehouse_revision + 1 "
            "WHERE singleton_id = 1"
        )
        row = connection.execute(
            "SELECT warehouse_revision FROM warehouse_state WHERE singleton_id = 1"
        ).fetchone()
        return int(row[0])

    def migrate_v1_to_v2(self) -> dict[str, Any]:
        """Explicitly migrate this database; normal initialize never calls this."""

        with _exclusive_database_operation(self.path):
            _ensure_private_directory(self.path.parent)
            _assert_no_database_sidecars(self.path)
            source_info = _verify_database(self.path)
            if int(source_info["user_version"]) == TARGET_SCHEMA_VERSION:
                digest = _sha256_file(self.path)
                return {
                    "migrated": False,
                    "from_version": TARGET_SCHEMA_VERSION,
                    "to_version": TARGET_SCHEMA_VERSION,
                    "source_sha256": digest,
                    "target_sha256": digest,
                    "upgrade_backup_path": None,
                    "upgrade_backup_sha256": None,
                }
            if int(source_info["user_version"]) != SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"no tested migration from schema {source_info['user_version']}"
                )
            source_sha256 = _sha256_file(self.path)
            upgrade_backup = self._create_backup_locked("upgrade")
            rollback = _temporary_database_path(self.path.parent, "v1-rollback")
            candidate = _temporary_database_path(self.path.parent, "v2-candidate")
            replaced = False
            keep_rollback = False
            try:
                _copy_file_bytes(self.path, rollback)
                _ensure_private_file(rollback)
                _fsync_file(rollback)
                if _sha256_file(rollback) != source_sha256:
                    raise CapsuleStoreError("migration rollback bytes do not match source")
                _verify_database(rollback, expected_version=SCHEMA_VERSION)

                _create_v2_candidate(rollback, candidate)
                _verify_database(candidate, expected_version=TARGET_SCHEMA_VERSION)
                _assert_v1_v2_equivalent(rollback, candidate)
                _assert_no_database_sidecars(self.path)
                if _sha256_file(self.path) != source_sha256:
                    raise CapsuleStoreError("active database changed during migration")

                _fsync_file(candidate)
                _fsync_directory(candidate.parent)
                os.replace(candidate, self.path)
                replaced = True
                _ensure_private_file(self.path)
                _fsync_file(self.path)
                _fsync_directory(self.path.parent)
                target_info = _verify_database(
                    self.path, expected_version=TARGET_SCHEMA_VERSION
                )
                _assert_v1_v2_equivalent(rollback, self.path)
            except BaseException as exc:
                if replaced:
                    recovery = _temporary_database_path(
                        self.path.parent, "migration-recovery"
                    )
                    try:
                        _copy_file_bytes(rollback, recovery)
                        _ensure_private_file(recovery)
                        _fsync_file(recovery)
                        _fsync_directory(recovery.parent)
                        os.replace(recovery, self.path)
                        _ensure_private_file(self.path)
                        _fsync_file(self.path)
                        _fsync_directory(self.path.parent)
                        if _sha256_file(self.path) != source_sha256:
                            raise CapsuleStoreError(
                                "migration rollback SHA-256 does not match source"
                            )
                        _verify_database(
                            self.path, expected_version=SCHEMA_VERSION
                        )
                    except BaseException as recovery_exc:
                        keep_rollback = True
                        raise CapsuleStoreError(
                            "migration failed and recovery failed; "
                            f"rollback preserved at {rollback}: {recovery_exc}"
                        ) from exc
                    finally:
                        recovery.unlink(missing_ok=True)
                elif self.path.is_file() and _sha256_file(self.path) != source_sha256:
                    raise CapsuleStoreError(
                        "migration aborted; active database changed and was not replaced"
                    ) from exc
                raise CapsuleStoreError(
                    "migration failed; original database preserved"
                ) from exc
            finally:
                candidate.unlink(missing_ok=True)
                if not keep_rollback:
                    rollback.unlink(missing_ok=True)

            return {
                "migrated": True,
                "from_version": source_info["user_version"],
                "to_version": target_info["user_version"],
                "source_sha256": source_sha256,
                "target_sha256": _sha256_file(self.path),
                "upgrade_backup_path": upgrade_backup["path"],
                "upgrade_backup_sha256": upgrade_backup["sha256"],
            }

    def create_backup(self, kind: str = "manual") -> dict[str, Any]:
        with _normal_database_operation(self.path):
            self.initialize()
            return self._create_backup_locked(kind)

    def _create_backup_locked(self, kind: str) -> dict[str, Any]:
        if kind not in _ALLOWED_BACKUP_KINDS:
            raise ValueError(f"invalid backup kind: {kind}")
        backup_root = self.path.parent / BACKUP_DIRECTORY
        _ensure_private_directory(backup_root)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = backup_root / (
            f"capsule_warehouse.{kind}.{stamp}.{uuid.uuid4().hex[:8]}.sqlite3"
        )
        source = self._connect()
        destination = sqlite3.connect(str(path))
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        _ensure_private_file(path)
        _fsync_file(path)
        _fsync_directory(path.parent)
        info = _verify_database(path)
        revision = int(info["warehouse_revision"])
        digest = _sha256_file(path)
        if kind not in {"pre_restore", "upgrade"}:
            with self.transaction() as connection:
                connection.execute(
                    "UPDATE warehouse_state "
                    "SET last_backed_up_revision = "
                    "MAX(last_backed_up_revision, MIN(warehouse_revision, ?)) "
                    "WHERE singleton_id = 1",
                    (revision,),
                )
        self._apply_retention(kind)
        return {
            "path": str(path),
            "kind": kind,
            "sha256": digest,
            "user_version": info["user_version"],
            "warehouse_revision": revision,
        }

    def list_backups(self) -> list[dict[str, Any]]:
        backup_root = self.path.parent / BACKUP_DIRECTORY
        if not backup_root.is_dir():
            return []
        result: list[dict[str, Any]] = []
        for path in sorted(
            backup_root.glob("capsule_warehouse.*.sqlite3"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        ):
            row: dict[str, Any] = {
                "path": str(path),
                "sha256": _sha256_file(path),
                "valid": True,
            }
            try:
                row.update(_verify_database(path))
            except (OSError, sqlite3.Error, CapsuleStoreError) as exc:
                row["valid"] = False
                row["error"] = str(exc)
            result.append(row)
        return result

    def inspect_restore(self, backup_path: str | Path) -> dict[str, Any]:
        with _normal_database_operation(self.path):
            backup = _resolve_backup_path(backup_path, self.path)
            return self._inspect_restore_locked(backup, reported_path=backup)

    def _inspect_restore_locked(
        self, backup: Path, *, reported_path: Path
    ) -> dict[str, Any]:
        info = _verify_database(backup)
        restored = {
            "capsules": self._read_ids(backup, "capsules", "capsule_id"),
            "versions": self._read_ids(backup, "capsule_versions", "version_id"),
            "usage": self._read_ids(backup, "product_capsule_usage", "usage_id"),
        }
        current_available = True
        try:
            current_info = _verify_database(self.path)
            current = {
                "capsules": self._read_ids(self.path, "capsules", "capsule_id"),
                "versions": self._read_ids(self.path, "capsule_versions", "version_id"),
                "usage": self._read_ids(self.path, "product_capsule_usage", "usage_id"),
            }
        except (OSError, sqlite3.Error, CapsuleStoreError):
            current_available = False
            current_info = None
            current = None
        return {
            "path": str(reported_path),
            "sha256": _sha256_file(backup),
            "user_version": info["user_version"],
            "current_database_available": current_available,
            "current_user_version": (
                current_info["user_version"] if current_info is not None else None
            ),
            "capsules_removed": (
                len(current["capsules"] - restored["capsules"])
                if current is not None
                else None
            ),
            "versions_removed": (
                len(current["versions"] - restored["versions"])
                if current is not None
                else None
            ),
            "product_usage_removed": (
                len(current["usage"] - restored["usage"])
                if current is not None
                else None
            ),
        }

    def restore_backup(
        self, backup_path: str | Path, *, expected_sha256: str
    ) -> dict[str, Any]:
        with _exclusive_database_operation(self.path):
            return self._restore_backup_locked(
                backup_path, expected_sha256=expected_sha256
            )

    def _restore_backup_locked(
        self, backup_path: str | Path, *, expected_sha256: str
    ) -> dict[str, Any]:
        if not expected_sha256:
            raise CapsuleStoreError("restore confirmation digest does not match backup")
        backup = _resolve_backup_path(backup_path, self.path)
        confirmed_backup = _temporary_database_path(
            self.path.parent, "confirmed-backup"
        )
        try:
            _copy_file_bytes(backup, confirmed_backup)
            _ensure_private_file(confirmed_backup)
            _fsync_file(confirmed_backup)
            if _sha256_file(confirmed_backup) != expected_sha256:
                raise CapsuleStoreError(
                    "restore confirmation digest does not match backup"
                )
            preview = self._inspect_restore_locked(
                confirmed_backup, reported_path=backup
            )
            if preview["sha256"] != expected_sha256:
                raise CapsuleStoreError(
                    "restore confirmation digest does not match backup"
                )
            return self._restore_confirmed_backup_locked(
                confirmed_backup, preview=preview, expected_sha256=expected_sha256
            )
        finally:
            confirmed_backup.unlink(missing_ok=True)

    def _restore_confirmed_backup_locked(
        self,
        backup: Path,
        *,
        preview: dict[str, Any],
        expected_sha256: str,
    ) -> dict[str, Any]:
        target_version = (
            int(preview["current_user_version"])
            if preview["current_user_version"] is not None
            else int(preview["user_version"])
        )
        backup_version = int(preview["user_version"])
        if backup_version > target_version:
            raise SchemaVersionError(
                f"backup schema {backup_version} is newer than active schema {target_version}"
            )
        if backup_version < target_version and (
            backup_version != SCHEMA_VERSION
            or target_version != TARGET_SCHEMA_VERSION
        ):
            raise SchemaVersionError(
                f"no tested restore migration from {backup_version} to {target_version}"
            )
        pre_restore = (
            self._create_backup_locked("pre_restore")
            if preview["current_database_available"]
            else self._preserve_current_database_bytes()
        )
        candidate = _temporary_database_path(self.path.parent, "restore")
        replaced = False
        try:
            if backup_version == target_version:
                _copy_database(backup, candidate)
            else:
                _create_v2_candidate(backup, candidate)
                _assert_v1_v2_equivalent(backup, candidate)
            _prepare_database_file(candidate)
            candidate_info = _verify_database(candidate)
            if int(candidate_info["user_version"]) != target_version:
                raise SchemaVersionError(
                    f"restore candidate schema {candidate_info['user_version']} "
                    f"does not match target {target_version}"
                )
            if (
                backup_version == target_version
                and _sha256_file(candidate) != expected_sha256
            ):
                raise CapsuleStoreError("restore candidate does not match confirmed backup")
            _fsync_directory(candidate.parent)
            os.replace(candidate, self.path)
            replaced = True
            _ensure_private_file(self.path)
            _fsync_file(self.path)
            _fsync_directory(self.path.parent)
            restored_info = _verify_database(self.path)
            if int(restored_info["user_version"]) != target_version:
                raise SchemaVersionError(
                    f"restored schema {restored_info['user_version']} "
                    f"does not match target {target_version}"
                )
        except BaseException as exc:
            if replaced:
                rollback = _temporary_database_path(self.path.parent, "rollback")
                try:
                    if pre_restore.get("raw_bytes", False):
                        _copy_file_bytes(Path(pre_restore["path"]), rollback)
                        _ensure_private_file(rollback)
                        _fsync_file(rollback)
                    else:
                        _copy_database(Path(pre_restore["path"]), rollback)
                        _prepare_database_file(rollback)
                    _fsync_directory(rollback.parent)
                    os.replace(rollback, self.path)
                    _ensure_private_file(self.path)
                    _fsync_file(self.path)
                    _fsync_directory(self.path.parent)
                    if pre_restore.get("raw_bytes", False):
                        if _sha256_file(self.path) != pre_restore["sha256"]:
                            raise CapsuleStoreError("raw rollback bytes do not match")
                    else:
                        _verify_database(self.path)
                except BaseException as rollback_exc:
                    raise CapsuleStoreError(
                        f"restore failed and recovery failed: {rollback_exc}"
                    ) from exc
                finally:
                    rollback.unlink(missing_ok=True)
            raise CapsuleStoreError("restore failed; original database preserved") from exc
        finally:
            candidate.unlink(missing_ok=True)
        return {
            **preview,
            "restored": True,
            "restored_user_version": target_version,
            "pre_restore_backup_path": pre_restore["path"],
            "pre_restore_backup_is_raw": bool(pre_restore.get("raw_bytes", False)),
        }

    def _preserve_current_database_bytes(self) -> dict[str, Any]:
        if not self.path.is_file():
            raise CapsuleStoreError("current database is unavailable and has no bytes to preserve")
        backup_root = self.path.parent / BACKUP_DIRECTORY
        _ensure_private_directory(backup_root)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = backup_root / (
            f"capsule_warehouse.pre_restore.{stamp}.{uuid.uuid4().hex[:8]}.sqlite3.raw"
        )
        _copy_file_bytes(self.path, path)
        _ensure_private_file(path)
        _fsync_file(path)
        _fsync_directory(path.parent)
        return {
            "path": str(path),
            "sha256": _sha256_file(path),
            "raw_bytes": True,
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            timeout=BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        return connection

    def _read_ids(self, path: Path, table: str, column: str) -> set[str]:
        connection = _open_read_only(path)
        try:
            return {str(row[0]) for row in connection.execute(f"SELECT {column} FROM {table}")}
        finally:
            connection.close()

    def _apply_retention(self, kind: str) -> None:
        keep = _RETENTION.get(kind)
        if keep is None:
            return
        backup_root = self.path.parent / BACKUP_DIRECTORY
        matches = sorted(
            backup_root.glob(f"capsule_warehouse.{kind}.*.sqlite3"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
        for path in matches[keep:]:
            path.unlink()


def _object_names(connection: sqlite3.Connection, object_type: str) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = ? AND name NOT LIKE 'sqlite_%'",
            (object_type,),
        )
    }


def _assert_schema_objects(
    connection: sqlite3.Connection, *, expected_version: int | None = None
) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if expected_version is not None and version != expected_version:
        raise SchemaVersionError(
            f"unsupported schema version {version}; expected {expected_version}"
        )
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SchemaVersionError(
            f"unsupported schema version {version}; "
            f"expected one of {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )
    expected_rows = _expected_schema_rows(version)
    expected_fingerprint = _SCHEMA_FINGERPRINT_SHA256[version]
    if _schema_fingerprint_sha256(expected_rows) != expected_fingerprint:
        raise SchemaVersionError(
            f"SCHEMA_SQL_V{version} does not match its frozen fingerprint"
        )
    expected_tables = {row[1] for row in expected_rows if row[0] == "table"}
    expected_triggers = {row[1] for row in expected_rows if row[0] == "trigger"}
    actual_tables = _object_names(connection, "table")
    actual_triggers = _object_names(connection, "trigger")
    missing_tables = expected_tables - actual_tables
    missing_triggers = expected_triggers - actual_triggers
    if missing_tables or missing_triggers:
        raise SchemaVersionError(
            f"incomplete schema: tables={sorted(missing_tables)}, "
            f"triggers={sorted(missing_triggers)}"
        )
    actual_rows = _schema_rows(connection)
    if actual_rows != expected_rows:
        raise SchemaVersionError(
            f"schema fingerprint does not match SCHEMA_SQL_V{version}"
        )
    if _schema_fingerprint_sha256(actual_rows) != expected_fingerprint:
        raise SchemaVersionError(
            f"schema fingerprint does not match frozen V{version} fingerprint"
        )
    _warehouse_revisions(connection)


def _schema_rows(connection: sqlite3.Connection) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (str(row[0]), str(row[1]), str(row[2]), str(row[3]))
        for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL "
            "ORDER BY type, name"
        )
    )


def _schema_fingerprint_sha256(
    rows: tuple[tuple[str, str, str, str], ...]
) -> str:
    payload = json.dumps(
        rows,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@cache
def _expected_schema_rows(
    version: int = SCHEMA_VERSION,
) -> tuple[tuple[str, str, str, str], ...]:
    if version == SCHEMA_VERSION:
        schema_sql = SCHEMA_SQL_V1
    elif version == TARGET_SCHEMA_VERSION:
        schema_sql = (
            "PRAGMA foreign_keys=ON;\n"
            + SCHEMA_SQL_V2
            + f"\nPRAGMA user_version={TARGET_SCHEMA_VERSION};"
        )
    else:
        raise SchemaVersionError(f"unsupported schema version {version}")
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(schema_sql)
        return _schema_rows(connection)
    finally:
        connection.close()


def _verify_database(
    path: Path, *, expected_version: int | None = None
) -> dict[str, Any]:
    connection = _open_read_only(path)
    try:
        _assert_schema_objects(connection, expected_version=expected_version)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise CapsuleStoreError(f"integrity_check failed: {integrity}")
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        if foreign_keys:
            raise CapsuleStoreError("foreign_key_check failed")
        _assert_persistent_data_invariants(connection)
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if journal_mode == "wal":
            raise CapsuleStoreError("WAL backup is unsupported")
        warehouse_revision, last_backed_up_revision = _warehouse_revisions(connection)
        return {
            "user_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
            "journal_mode": journal_mode,
            "warehouse_revision": warehouse_revision,
            "last_backed_up_revision": last_backed_up_revision,
        }
    finally:
        connection.close()


def _assert_persistent_data_invariants(connection: sqlite3.Connection) -> None:
    checks = (
        (
            "capsule_current_version",
            """
            SELECT 1
            FROM capsules c
            LEFT JOIN capsule_versions v
              ON v.version_id = c.current_version_id
             AND v.capsule_id = c.capsule_id
            WHERE c.current_version_id IS NULL
               OR (c.current_version_id IS NOT NULL AND v.version_id IS NULL)
            LIMIT 1
            """,
        ),
        (
            "capsule_source_identity",
            """
            SELECT 1
            FROM capsule_sources s
            WHERE NOT (
                (
                    s.source_kind = 'project'
                    AND s.project_id IS NOT NULL
                    AND s.source_identity = 'project:' || s.project_id
                )
                OR
                (
                    s.source_kind = 'legacy_json'
                    AND s.project_id IS NULL
                    AND length(s.source_identity) > 7
                    AND substr(s.source_identity, 1, 7) = 'legacy:'
                )
            )
            LIMIT 1
            """,
        ),
        (
            "capsule_source_canonical",
            """
            SELECT 1
            FROM capsule_sources s
            JOIN capsule_versions v ON v.version_id = s.version_id
            WHERE s.relationship IN ('exact', 'published_implementation')
              AND s.candidate_canonical_hash <> v.canonical_hash
            LIMIT 1
            """,
        ),
        (
            "capsule_status_event",
            """
            SELECT 1
            FROM capsule_status_events e
            LEFT JOIN capsule_versions v
              ON v.version_id = e.version_id
             AND v.capsule_id = e.capsule_id
            WHERE v.version_id IS NULL
               OR NOT (
                    (
                        e.event_type = 'enabled'
                        AND e.from_status IN ('pending_revalidation', 'disabled')
                        AND e.to_status = 'active'
                    )
                    OR
                    (
                        e.event_type = 'disabled'
                        AND e.from_status IN ('active', 'pending_revalidation')
                        AND e.to_status = 'disabled'
                    )
                    OR
                    (
                        e.event_type = 'revalidation_required'
                        AND e.from_status = 'active'
                        AND e.to_status = 'pending_revalidation'
                    )
                    OR
                    (
                        e.event_type = 'current_version_changed'
                        AND e.from_status IN ('active', 'pending_revalidation', 'disabled')
                        AND e.to_status = 'active'
                    )
                    OR
                    (
                        e.event_type = 'usage_scope_changed'
                        AND e.from_status IN ('active', 'pending_revalidation')
                        AND e.to_status = e.from_status
                    )
               )
            LIMIT 1
            """,
        ),
        (
            "product_capsule_usage",
            """
            SELECT 1
            FROM product_capsule_usage u
            LEFT JOIN capsule_versions v ON v.version_id = u.version_id
            LEFT JOIN capsules c ON c.capsule_id = u.capsule_id
            WHERE v.version_id IS NULL
               OR c.capsule_id IS NULL
               OR v.capsule_id <> u.capsule_id
               OR c.capability_key <> u.capability_key
               OR c.role_key <> u.role_key
               OR c.variant_key <> u.variant_key
               OR v.usage_scope_json <> u.usage_scope_json
            LIMIT 1
            """,
        ),
        (
            "product_manifest_digest",
            """
            SELECT 1
            FROM product_capsule_usage
            GROUP BY product_id
            HAVING COUNT(DISTINCT manifest_digest) > 1
            LIMIT 1
            """,
        ),
        (
            "legacy_capsule_alias",
            """
            SELECT 1
            FROM legacy_capsule_aliases a
            LEFT JOIN intake_runs r ON r.run_id = a.import_run_id
            LEFT JOIN capsule_versions v
              ON v.version_id = a.new_version_id
             AND v.capsule_id = a.new_capsule_id
            WHERE r.run_id IS NULL
               OR r.run_kind <> 'legacy_import'
               OR r.legacy_source_file_hash IS NULL
               OR r.legacy_source_file_hash <> a.legacy_file_hash
               OR (a.new_capsule_id IS NULL) <> (a.new_version_id IS NULL)
               OR (a.new_version_id IS NOT NULL AND v.version_id IS NULL)
               OR (
                    a.relationship IN ('exact', 'cleaned_successor', 'merged', 'variant')
                    AND a.new_version_id IS NULL
               )
               OR (
                    a.relationship IN ('rejected', 'pending')
                    AND a.new_version_id IS NOT NULL
               )
            LIMIT 1
            """,
        ),
    )
    for name, query in checks:
        if connection.execute(query).fetchone() is not None:
            raise CapsuleStoreError(f"persistent data invariant failed: {name}")
    if int(connection.execute("PRAGMA user_version").fetchone()[0]) == TARGET_SCHEMA_VERSION:
        _assert_project_file_index_invariants(connection)
    _assert_canonical_versions(connection)


def _assert_project_file_index_invariants(connection: sqlite3.Connection) -> None:
    projects = connection.execute(
        "SELECT project_id, source_type, last_snapshot_hash FROM projects "
        "ORDER BY project_id"
    ).fetchall()
    for project in projects:
        project_id = project["project_id"]
        source_type = project["source_type"]
        rows = connection.execute(
            "SELECT logical_path, entry_kind, size_bytes, content_sha256 "
            "FROM project_file_index WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        if source_type == "static_web":
            if rows:
                raise CapsuleStoreError(
                    "persistent data invariant failed: project_file_index_owner"
                )
            continue
        if source_type != "javascript_computation_source":
            raise CapsuleStoreError(
                "persistent data invariant failed: project_source_type"
            )

        path_keys: tuple[set[str], ...] = (set(), set(), set(), set())
        modules: list[dict[str, Any]] = []
        symlinks: list[dict[str, str]] = []
        for row in sorted(rows, key=lambda item: str(item["logical_path"]).encode("utf-8")):
            logical_path = row["logical_path"]
            try:
                _validate_logical_path(logical_path, "project_file_index.logical_path")
            except ValueError as exc:
                raise CapsuleStoreError(
                    "persistent data invariant failed: project_file_index_path"
                ) from exc
            collision_keys = (
                logical_path,
                logical_path.casefold(),
                unicodedata.normalize("NFC", logical_path),
                unicodedata.normalize("NFC", logical_path).casefold(),
            )
            if any(key in seen for key, seen in zip(collision_keys, path_keys)):
                raise CapsuleStoreError(
                    "persistent data invariant failed: project_file_index_path_collision"
                )
            for key, seen in zip(collision_keys, path_keys):
                seen.add(key)

            entry_kind = row["entry_kind"]
            size_bytes = row["size_bytes"]
            content_sha256 = row["content_sha256"]
            if entry_kind == "javascript_module":
                if (
                    type(size_bytes) is not int
                    or size_bytes < 0
                    or not _is_lower_sha256(content_sha256)
                ):
                    raise CapsuleStoreError(
                        "persistent data invariant failed: project_file_index_module"
                    )
                modules.append(
                    {
                        "path": logical_path,
                        "size": size_bytes,
                        "sha256": content_sha256,
                    }
                )
            elif entry_kind == "symlink":
                if size_bytes is not None or content_sha256 is not None:
                    raise CapsuleStoreError(
                        "persistent data invariant failed: project_file_index_symlink"
                    )
                symlinks.append({"path": logical_path})
            else:
                raise CapsuleStoreError(
                    "persistent data invariant failed: project_file_index_kind"
                )

        last_snapshot_hash = project["last_snapshot_hash"]
        if not rows:
            if last_snapshot_hash is not None:
                raise CapsuleStoreError(
                    "persistent data invariant failed: javascript_scope_snapshot"
                )
            continue
        snapshot_bytes = json.dumps(
            {
                "version": "javascript_scope_snapshot.v1",
                "javascript_modules": modules,
                "symlinks": symlinks,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        expected = hashlib.sha256(snapshot_bytes).hexdigest()
        if last_snapshot_hash != expected:
            raise CapsuleStoreError(
                "persistent data invariant failed: javascript_scope_snapshot"
            )


def _is_lower_sha256(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _assert_canonical_versions(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT v.*, c.capability_kind FROM capsule_versions v "
        "JOIN capsules c ON c.capsule_id = v.capsule_id ORDER BY v.version_id"
    )
    for row in rows:
        version_id = str(row["version_id"])
        if (
            type(row["canonicalization_version"]) is not int
            or int(row["canonicalization_version"]) != CANONICALIZATION_VERSION
        ):
            raise CapsuleStoreError(
                "persistent data invariant failed: capsule_version_canonicalization_version"
            )

        assets: list[dict[str, str]] = []
        total_size = 0
        for asset in connection.execute(
            "SELECT logical_path, media_type, sha256, size_bytes, width, height, content "
            "FROM capsule_assets WHERE version_id = ? ORDER BY logical_path",
            (version_id,),
        ):
            content = asset["content"]
            size_bytes = asset["size_bytes"]
            if type(content) is not bytes or type(size_bytes) is not int:
                raise CapsuleStoreError(
                    "persistent data invariant failed: capsule_asset_storage_type"
                )
            if size_bytes < 0 or size_bytes > 1_048_576:
                raise CapsuleStoreError(
                    "persistent data invariant failed: capsule_asset_size_limit"
                )
            if len(content) != size_bytes:
                raise CapsuleStoreError(
                    "persistent data invariant failed: capsule_asset_size"
                )
            if hashlib.sha256(content).hexdigest() != asset["sha256"]:
                raise CapsuleStoreError(
                    "persistent data invariant failed: capsule_asset_sha256"
                )
            if (
                type(asset["width"]) is not int
                or type(asset["height"]) is not int
                or not 1 <= asset["width"] <= 4096
                or not 1 <= asset["height"] <= 4096
                or asset["width"] * asset["height"] > 16_777_216
            ):
                raise CapsuleStoreError(
                    "persistent data invariant failed: capsule_asset_pixels"
                )
            total_size += size_bytes
            if total_size > MAX_CAPSULE_ASSET_BYTES:
                raise CapsuleStoreError(
                    "persistent data invariant failed: capsule_asset_total_size"
                )
            assets.append(
                {
                    "logical_path": asset["logical_path"],
                    "media_type": asset["media_type"],
                    "sha256": asset["sha256"],
                }
            )

        try:
            canonical = canonicalize_capsule(
                {
                    "capability_kind": row["capability_kind"],
                    "activation": _load_strict_json(row["activation_json"]),
                    "input_contract": _load_strict_json(row["input_contract_json"]),
                    "output_contract": _load_strict_json(row["output_contract_json"]),
                    "error_contract": _load_strict_json(row["error_contract_json"]),
                    "runtime_allowlist": _load_strict_json(row["runtime_allowlist_json"]),
                    "dom_scope": _load_strict_json(row["dom_scope_json"]),
                    "usage_scope": _load_strict_json(row["usage_scope_json"]),
                    "html": row["html_text"],
                    "css": row["css_text"],
                    "javascript_modules": _load_strict_json(
                        row["javascript_modules_json"]
                    ),
                    "assets": assets,
                }
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CapsuleStoreError(
                "persistent data invariant failed: capsule_version_canonical_payload"
            ) from exc
        if type(row["canonical_hash"]) is not str or row["canonical_hash"] != canonical.sha256:
            raise CapsuleStoreError(
                "persistent data invariant failed: capsule_version_canonical_hash"
            )


def _load_strict_json(raw: Any) -> Any:
    if type(raw) is not str:
        raise ValueError("stored JSON must be text")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate stored JSON key: {key}")
            value[key] = item
        return value

    return json.loads(raw, object_pairs_hook=reject_duplicate_keys)


def _open_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise CapsuleStoreError(f"database file not found: {path}")
    uri_path = quote(path.resolve().as_posix(), safe="/:")
    connection = sqlite3.connect(
        f"file:{uri_path}?mode=ro",
        uri=True,
        timeout=BUSY_TIMEOUT_MS / 1000,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA query_only = ON")
    return connection


def _warehouse_revisions(connection: sqlite3.Connection) -> tuple[int, int]:
    rows = connection.execute(
        "SELECT singleton_id, warehouse_revision, last_backed_up_revision, "
        "typeof(singleton_id), typeof(warehouse_revision), "
        "typeof(last_backed_up_revision) FROM warehouse_state"
    ).fetchall()
    if len(rows) != 1 or tuple(rows[0][3:]) != ("integer", "integer", "integer"):
        raise SchemaVersionError("warehouse_state must contain one integer singleton row")
    singleton_id, warehouse_revision, last_backed_up_revision = map(int, rows[0][:3])
    if (
        singleton_id != 1
        or warehouse_revision < 0
        or last_backed_up_revision < 0
        or last_backed_up_revision > warehouse_revision
    ):
        raise SchemaVersionError("warehouse_state invariants are invalid")
    return warehouse_revision, last_backed_up_revision


def _resolve_backup_path(path: str | Path, database_path: Path) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise CapsuleStoreError("backup symlinks are forbidden")
    resolved = raw.resolve()
    if resolved == database_path.resolve():
        raise CapsuleStoreError("cannot restore the active database as a backup")
    if not resolved.is_file():
        raise CapsuleStoreError(f"backup not found: {resolved}")
    return resolved


def _assert_no_database_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            raise CapsuleStoreError(f"database sidecar blocks migration: {sidecar.name}")


def _create_v2_candidate(source_path: Path, destination_path: Path) -> None:
    _verify_database(source_path, expected_version=SCHEMA_VERSION)
    if destination_path.exists():
        raise CapsuleStoreError("migration candidate already exists")
    connection = sqlite3.connect(
        str(destination_path),
        uri=True,
        timeout=BUSY_TIMEOUT_MS / 1000,
        isolation_level=None,
    )
    attached = False
    try:
        mode = str(
            connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        ).lower()
        if mode == "wal":
            raise CapsuleStoreError("could not prepare migration candidate")
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        uri_path = quote(source_path.resolve().as_posix(), safe="/:")
        connection.execute(
            "ATTACH DATABASE ? AS v1",
            (f"file:{uri_path}?mode=ro",),
        )
        attached = True
        connection.executescript(
            "BEGIN IMMEDIATE;\n"
            + SCHEMA_TABLES_SQL_V2
            + "\n"
            + MIGRATE_V1_TO_V2_COPY_SQL
            + "\n"
            + SCHEMA_INDEXES_SQL_V2
            + "\n"
            + SCHEMA_TRIGGERS_SQL_V2
            + f"\nPRAGMA user_version={TARGET_SCHEMA_VERSION};\nCOMMIT;"
        )
        connection.execute("DETACH DATABASE v1")
        attached = False
        connection.execute("PRAGMA foreign_keys=ON")
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        if attached:
            try:
                connection.execute("DETACH DATABASE v1")
            except sqlite3.Error:
                pass
        connection.close()
    _ensure_private_file(destination_path)
    _fsync_file(destination_path)


def _assert_v1_v2_equivalent(source_path: Path, target_path: Path) -> None:
    _verify_database(source_path, expected_version=SCHEMA_VERSION)
    _verify_database(target_path, expected_version=TARGET_SCHEMA_VERSION)
    source = _open_read_only(source_path)
    target = _open_read_only(target_path)
    try:
        for table in sorted(_TABLES):
            source_info = source.execute(
                f"PRAGMA table_info({_quote_identifier(table)})"
            ).fetchall()
            columns = [str(row[1]) for row in source_info]
            primary_key = [
                str(row[1])
                for row in sorted(source_info, key=lambda item: int(item[5]))
                if int(row[5]) > 0
            ]
            if not primary_key:
                raise CapsuleStoreError(
                    f"migration equivalence has no primary key for {table}"
                )
            projection = ", ".join(
                f"{_quote_identifier(column)}, "
                f"typeof({_quote_identifier(column)})"
                for column in columns
            )
            order_by = ", ".join(_quote_identifier(column) for column in primary_key)
            query = (
                f"SELECT {projection} FROM {_quote_identifier(table)} "
                f"ORDER BY {order_by}"
            )
            source_rows = [tuple(row) for row in source.execute(query)]
            target_rows = [tuple(row) for row in target.execute(query)]
            if source_rows != target_rows:
                raise CapsuleStoreError(
                    f"migration changed v1 data in table {table}"
                )

        if target.execute(
            "SELECT 1 FROM projects WHERE source_type <> 'static_web' LIMIT 1"
        ).fetchone() is not None:
            raise CapsuleStoreError("migration project source_type backfill failed")
        if target.execute(
            "SELECT 1 FROM review_items WHERE enum_decision IS NOT NULL "
            "OR enum_decision_binding_sha256 IS NOT NULL "
            "OR enum_decided_at IS NOT NULL LIMIT 1"
        ).fetchone() is not None:
            raise CapsuleStoreError("migration review enum backfill failed")
        if target.execute("SELECT 1 FROM project_file_index LIMIT 1").fetchone() is not None:
            raise CapsuleStoreError("migration project_file_index must start empty")
    finally:
        target.close()
        source.close()


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _copy_database(source_path: Path, destination_path: Path) -> None:
    source = _open_read_only(source_path)
    destination = sqlite3.connect(str(destination_path))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def _copy_file_bytes(source_path: Path, destination_path: Path) -> None:
    with source_path.open("rb") as source, destination_path.open("xb") as destination:
        shutil.copyfileobj(source, destination, length=1024 * 1024)


def _prepare_database_file(path: Path) -> None:
    connection = sqlite3.connect(str(path), isolation_level=None)
    try:
        mode = str(connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).lower()
        if mode == "wal":
            raise CapsuleStoreError("could not disable WAL mode")
    finally:
        connection.close()
    _ensure_private_file(path)
    _fsync_file(path)


def _temporary_database_path(directory: Path, prefix: str) -> Path:
    _ensure_private_directory(directory)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{DATABASE_FILENAME}.{prefix}.",
        suffix=".tmp",
        dir=directory,
    )
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)


def _ensure_private_file(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
