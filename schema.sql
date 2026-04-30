-- schema.sql -- ShowBuilder SQLite schema.
--
-- SINGLE SOURCE OF TRUTH for ShowBuilder data integrity.
--
-- This file is the authoritative definition of:
--   - table structure and column types
--   - primary keys and uniqueness constraints
--   - foreign key relationships
--   - CHECK constraints on enum-valued columns
--   - indexes for common join/filter patterns
--
-- Code generation (showbuilder/codegen.py) introspects the live database
-- produced from this schema to auto-generate:
--   - Python row validators (validate_row.py)
--   - VBA ValidateRow() procs (injected into the workbook)
--
-- When adding a new column, table, or enum value:
--   1. Update this file.
--   2. Update schema.py (Python dataclasses).
--   3. Update workbook_io.py (_SHEET_COLS + _read_* function).
--   4. Re-run dump_wb.py to refresh the database.
--   5. Re-run codegen.py to regenerate validators.
--
-- Enum-constrained columns have CHECK constraints so SQLite enforces values
-- at dump time AND codegen.py can read them from sqlite_master to generate
-- matching VBA Select Case / Python Literal validators without any separate
-- enum registry.
--
-- Polymorphic FK exception:
--   sequence_entries.target_id references either items(item_id) or
--   sequences(sequence_id) depending on entry_type.  SQLite cannot enforce
--   this natively.  codegen.py emits a special-case check for it.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- formats
-- ---------------------------------------------------------------------------

CREATE TABLE formats (
    format_id   TEXT    PRIMARY KEY,
    name        TEXT    NOT NULL,
    width_px    INTEGER,
    height_px   INTEGER,
    fps         REAL,
    enabled     INTEGER NOT NULL DEFAULT 1
                        CHECK (enabled IN (0, 1)),
    notes       TEXT
);

-- ---------------------------------------------------------------------------
-- assets
-- ---------------------------------------------------------------------------

CREATE TABLE assets (
    asset_id            TEXT    PRIMARY KEY,
    asset_type          TEXT    NOT NULL
                                CHECK (asset_type IN ('image', 'video', 'youtube')),
    src                 TEXT,
    title               TEXT,
    default_duration_ms INTEGER,
    metadata_json       TEXT,
    enabled             INTEGER NOT NULL DEFAULT 1
                                CHECK (enabled IN (0, 1)),
    notes               TEXT
);
CREATE INDEX idx_assets_type ON assets (asset_type);

-- ---------------------------------------------------------------------------
-- styles  (defined before items so items FK resolves)
-- ---------------------------------------------------------------------------

CREATE TABLE styles (
    style_class       TEXT    PRIMARY KEY,
    font_family       TEXT,
    font_size_px      INTEGER,
    font_weight       TEXT,
    color             TEXT,
    bg_color          TEXT,
    padding_px        INTEGER,
    border_radius_px  INTEGER,
    text_shadow       TEXT,
    metadata_json     TEXT,
    enabled           INTEGER NOT NULL DEFAULT 1
                              CHECK (enabled IN (0, 1)),
    notes             TEXT
);

-- ---------------------------------------------------------------------------
-- regions  (defined before items so items FK resolves)
-- ---------------------------------------------------------------------------

CREATE TABLE regions (
    region_id     TEXT    PRIMARY KEY,
    x             REAL,
    y             REAL,
    w             REAL,
    h             REAL,
    anchor        TEXT    CHECK (anchor IN (
                              'top_left', 'top_center', 'top_right',
                              'center_left', 'center', 'center_right',
                              'bottom_left', 'bottom_center', 'bottom_right',
                              NULL, '')),
    metadata_json TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1
                          CHECK (enabled IN (0, 1)),
    notes         TEXT
);

-- ---------------------------------------------------------------------------
-- items
-- ---------------------------------------------------------------------------

CREATE TABLE items (
    item_id                     TEXT    PRIMARY KEY,
    asset_id                    TEXT    REFERENCES assets (asset_id),
    duration_ms                 INTEGER,
    duration_mode               TEXT    CHECK (duration_mode IN ('fixed', 'to_media_end', NULL, '')),
    media_start_s               REAL,
    effect_name                 TEXT,
    effect_params_json          TEXT,
    default_text_set_id         TEXT,   -- FK → text_sets; forward ref, not enforced by SQLite
    region_id                   TEXT    REFERENCES regions (region_id),
    style_class                 TEXT    REFERENCES styles (style_class),
    track_kind                  TEXT    CHECK (track_kind IN (
                                            'video_main', 'video_overlay', 'text_overlay',
                                            NULL, '')),
    media_audio_mode            TEXT    CHECK (media_audio_mode IN ('mute', 'normal', 'ducked', NULL, '')),
    media_audio_gain_db         REAL,
    z_order                     INTEGER,
    fit_mode                    TEXT    CHECK (fit_mode IN ('cover', 'contain', 'stretch', 'none', NULL, '')),
    transition_in               TEXT,
    transition_in_params_json   TEXT,
    transition_out              TEXT,
    transition_out_params_json  TEXT,
    yt_freeze_at_s              REAL,
    yt_freeze_duration_ms       INTEGER,
    metadata_json               TEXT,
    enabled                     INTEGER NOT NULL DEFAULT 1
                                        CHECK (enabled IN (0, 1)),
    notes                       TEXT
);
CREATE INDEX idx_items_asset ON items (asset_id);

-- ---------------------------------------------------------------------------
-- text_sets
-- ---------------------------------------------------------------------------

CREATE TABLE text_sets (
    text_set_id    TEXT    PRIMARY KEY,
    item_id        TEXT    REFERENCES items (item_id),
    text_set_name  TEXT,
    metadata_json  TEXT,
    enabled        INTEGER NOT NULL DEFAULT 1
                           CHECK (enabled IN (0, 1)),
    notes          TEXT
);
CREATE INDEX idx_text_sets_item ON text_sets (item_id);

-- ---------------------------------------------------------------------------
-- text_overlays
-- ---------------------------------------------------------------------------

CREATE TABLE text_overlays (
    text_id             TEXT    PRIMARY KEY,
    text_set_id         TEXT    REFERENCES text_sets (text_set_id),
    sequence_no         INTEGER,
    content             TEXT,
    start_ms            INTEGER,
    duration_ms         INTEGER,
    position_mode       TEXT    CHECK (position_mode IN ('preset', 'coords', NULL, '')),
    position_preset     TEXT    CHECK (position_preset IN (
                                    'top_left', 'top_center', 'top_right',
                                    'center_left', 'center', 'center_right',
                                    'bottom_left', 'bottom_center', 'bottom_right',
                                    NULL, '')),
    pos_x               REAL,
    pos_y               REAL,
    anchor              TEXT    CHECK (anchor IN (
                                    'top_left', 'top_center', 'top_right',
                                    'center_left', 'center', 'center_right',
                                    'bottom_left', 'bottom_center', 'bottom_right',
                                    NULL, '')),
    width_norm          REAL,
    align               TEXT    CHECK (align IN ('left', 'center', 'right', NULL, '')),
    region_id           TEXT    REFERENCES regions (region_id),
    effect_name         TEXT,
    effect_params_json  TEXT,
    style_class         TEXT    REFERENCES styles (style_class),
    metadata_json       TEXT,
    enabled             INTEGER NOT NULL DEFAULT 1
                                CHECK (enabled IN (0, 1)),
    notes               TEXT,
    UNIQUE (text_set_id, sequence_no)
);
CREATE INDEX idx_text_overlays_set ON text_overlays (text_set_id);

-- ---------------------------------------------------------------------------
-- sequences
-- ---------------------------------------------------------------------------

CREATE TABLE sequences (
    sequence_id    TEXT    PRIMARY KEY,
    sequence_name  TEXT    NOT NULL,
    sequence_type  TEXT    NOT NULL
                           CHECK (sequence_type IN ('show', 'block', 'playlist')),
    format_id      TEXT    REFERENCES formats (format_id),
    timing_mode    TEXT    CHECK (timing_mode IN ('serial', 'parallel', NULL, '')),
    description    TEXT,
    metadata_json  TEXT,
    enabled        INTEGER NOT NULL DEFAULT 1
                           CHECK (enabled IN (0, 1))
);

-- ---------------------------------------------------------------------------
-- sequence_entries
-- ---------------------------------------------------------------------------

CREATE TABLE sequence_entries (
    sequence_entry_id           TEXT    PRIMARY KEY,
    sequence_id                 TEXT    NOT NULL REFERENCES sequences (sequence_id),
    sequence_no                 INTEGER,
    entry_type                  TEXT    NOT NULL
                                        CHECK (entry_type IN ('item', 'sequence')),
    -- target_id is polymorphic: FK → items(item_id) when entry_type='item',
    --                                → sequences(sequence_id) when entry_type='sequence'.
    -- SQLite cannot enforce this natively.
    -- codegen.py emits a special-case validator for this column.
    target_id                   TEXT    NOT NULL,
    track_kind                  TEXT    CHECK (track_kind IN (
                                            'video_main', 'video_overlay', 'text_overlay',
                                            NULL, '')),
    local_start_ms              INTEGER,
    override_duration_ms        INTEGER,
    override_media_start_s      REAL,
    override_effect_name        TEXT,
    override_effect_params_json TEXT,
    override_text_set_id        TEXT,
    override_z_order            INTEGER,
    override_style_class        TEXT,
    metadata_json               TEXT,
    enabled                     INTEGER NOT NULL DEFAULT 1
                                        CHECK (enabled IN (0, 1)),
    notes                       TEXT,
    UNIQUE (sequence_id, sequence_no)
);
CREATE INDEX idx_seq_entries_seq    ON sequence_entries (sequence_id);
CREATE INDEX idx_seq_entries_target ON sequence_entries (target_id);

-- ---------------------------------------------------------------------------
-- enums
-- ---------------------------------------------------------------------------

CREATE TABLE enums (
    enum_type  TEXT NOT NULL,
    value      TEXT NOT NULL,
    label      TEXT,
    notes      TEXT,
    PRIMARY KEY (enum_type, value)
);
CREATE INDEX idx_enums_type ON enums (enum_type);

-- ---------------------------------------------------------------------------
-- icloud_accounts
-- ---------------------------------------------------------------------------

CREATE TABLE icloud_accounts (
    account_alias  TEXT    PRIMARY KEY,
    apple_id       TEXT,
    enabled        INTEGER NOT NULL DEFAULT 1
                           CHECK (enabled IN (0, 1)),
    notes          TEXT
);

-- ---------------------------------------------------------------------------
-- icloud_photos
-- ---------------------------------------------------------------------------

CREATE TABLE icloud_photos (
    icloud_photo_id  TEXT    PRIMARY KEY,
    account_alias    TEXT    REFERENCES icloud_accounts (account_alias),
    filename         TEXT,
    created_date     TEXT,
    media_type       TEXT    CHECK (media_type IN ('image', 'video', NULL, '')),
    album            TEXT,
    local_path       TEXT,
    local_hash       TEXT,
    asset_id         TEXT,   -- nullable FK → assets; empty string means unregistered
    last_synced      TEXT,
    notes            TEXT
);
CREATE INDEX idx_icloud_photos_account ON icloud_photos (account_alias);
CREATE INDEX idx_icloud_photos_asset   ON icloud_photos (asset_id) WHERE asset_id != '';
