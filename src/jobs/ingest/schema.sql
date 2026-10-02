-- ============================================================================
-- Corpus retrieval schema. Run once, on an empty database, before seeding.
--
--   uv run operonx-run create_schema                    <- this file, once, when the tables are absent
--   uv run operonx-run ingest --set seed=true           <- then the data
--
-- Order matters and the failures are hard ones, not warnings:
--
--   * the seed writes `ON CONFLICT (policy_id)`, which Postgres rejects
--     unless the UNIQUE in PART 2 already exists;
--   * `ADD CONSTRAINT ... UNIQUE` cannot be applied to a table that already
--     holds duplicate `policy_id` values, so it has to precede any data.
--
-- Both parts need the same DDL privilege and run at the same moment, which is
-- why they are one file. They were briefly two — a split that bought a diff
-- against MLE's source doc and cost an extra step whose omission is silent:
-- without PART 2 the seed fails loudly, but retrieval just returns an empty
-- pool. The diff is now a test (tests/contract/test_schema_matches_partner_ddl.py)
-- rather than a thing an operator has to remember.
--
-- PART 1 is extracted verbatim from the ```sql blocks of
--   collection.sentiment_violation.rag/docs/2. ddl_db.md
-- Do not hand-edit it. When MLE change theirs, re-extract and let the test
-- confirm nothing else drifted.
-- ============================================================================


-- ############################################################################
-- PART 1 — MLE's DDL, verbatim. Creates the tables and their indexes.
-- ############################################################################

-- ============================================================
-- 1. Enable PGVector
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- 2. KNOWLEDGE_INFO
-- Master table: Một record = một loại fraud
-- ============================================================

CREATE TABLE knowledge_info (
    id              VARCHAR(100) PRIMARY KEY,

    name            VARCHAR(255) NOT NULL,

    enabled         BOOLEAN NOT NULL DEFAULT TRUE,

    description     TEXT,

    severity        VARCHAR(20),

    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_knowledge_info_severity
        CHECK (
            severity IS NULL
            OR severity IN (
                'SAFE',
                'WARNING',
                'HIGH',
                'CRITICAL'
            )
        )
);

-- ============================================================
-- 3. KNOWLEDGE_POLICY
-- Mỗi record = 1 content/sample.
-- Không lưu JSON array nữa.
-- ============================================================

CREATE TABLE knowledge_policy (
    id              VARCHAR(150) PRIMARY KEY,

    knowledge_id    VARCHAR(100) NOT NULL,

    batch_id        VARCHAR(100),

    sample_type     VARCHAR(20) NOT NULL,

    content         TEXT NOT NULL,

    severity        VARCHAR(20) NOT NULL,

    description     TEXT,

    status          VARCHAR(20) NOT NULL,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_knowledge_policy_knowledge_info
        FOREIGN KEY (knowledge_id)
        REFERENCES knowledge_info(id)
        ON DELETE RESTRICT,

    CONSTRAINT chk_knowledge_policy_type
        CHECK (
            sample_type IN (
                'positive',
                'carveout'
            )
        ),

    CONSTRAINT chk_knowledge_policy_severity
        CHECK (
            severity IN (
                'SAFE',
                'WARNING',
                'HIGH',
                'CRITICAL'
            )
        ),

    CONSTRAINT chk_knowledge_policy_status
        CHECK (
            status IN (
                'NEW',
                'UPDATE',
                'UNCHANGED',
                'OUTDATED'
            )
        )
);

-- ============================================================
-- 4. POSITIVE_EMBEDDING
-- Mỗi row = 1 sample positive, lưu vector tương ứng.
-- ============================================================

CREATE TABLE POSITIVE_EMBEDDING (
    id                  BIGSERIAL PRIMARY KEY,

    policy_id           VARCHAR(150) NOT NULL,

    knowledge_id        VARCHAR(100) NOT NULL,

    sample_type         VARCHAR(20) NOT NULL DEFAULT 'positive',

    severity            VARCHAR(20) NOT NULL,

    embedding_model     VARCHAR(255) NOT NULL,

    embedding_version   VARCHAR(100) NOT NULL,

    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,

    embedding           VECTOR(1024) NOT NULL,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_positive_embedding_policy
        FOREIGN KEY (policy_id)
        REFERENCES knowledge_policy(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_positive_embedding_knowledge
        FOREIGN KEY (knowledge_id)
        REFERENCES knowledge_info(id)
        ON DELETE RESTRICT,

    CONSTRAINT chk_positive_embedding_type
        CHECK (
            sample_type = 'positive'
        ),

    CONSTRAINT chk_positive_embedding_severity
        CHECK (
            severity IN (
                'SAFE',
                'WARNING',
                'HIGH',
                'CRITICAL'
            )
        )
);

-- ============================================================
-- 5. CARVEOUT_EMBEDDING
-- Mỗi row = 1 sample carveout, lưu vector tương ứng.
-- ============================================================

CREATE TABLE CARVEOUT_EMBEDDING (
    id                  BIGSERIAL PRIMARY KEY,

    policy_id           VARCHAR(150) NOT NULL,

    knowledge_id        VARCHAR(100) NOT NULL,

    sample_type         VARCHAR(20) NOT NULL DEFAULT 'carveout',

    severity            VARCHAR(20) NOT NULL,

    embedding_model     VARCHAR(255) NOT NULL,

    embedding_version   VARCHAR(100) NOT NULL,

    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,

    embedding           VECTOR(1024) NOT NULL,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_carveout_embedding_policy
        FOREIGN KEY (policy_id)
        REFERENCES knowledge_policy(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_carveout_embedding_knowledge
        FOREIGN KEY (knowledge_id)
        REFERENCES knowledge_info(id)
        ON DELETE RESTRICT,

    CONSTRAINT chk_carveout_embedding_type
        CHECK (
            sample_type = 'carveout'
        ),

    CONSTRAINT chk_carveout_embedding_severity
        CHECK (
            severity IN (
                'SAFE',
                'WARNING',
                'HIGH',
                'CRITICAL'
            )
        )
);

-- ============================================================
-- INDEX
-- ============================================================

-- Lookup policy theo knowledge
CREATE INDEX idx_knowledge_policy_knowledge_id
ON knowledge_policy(knowledge_id);

-- Filter policy theo type
CREATE INDEX idx_knowledge_policy_type
ON knowledge_policy(sample_type);

-- Filter policy theo status
CREATE INDEX idx_knowledge_policy_status
ON knowledge_policy(status);

-- Lookup positive embedding theo policy
CREATE INDEX idx_positive_embedding_policy_id
ON POSITIVE_EMBEDDING(policy_id);

-- Lookup positive embedding theo knowledge
CREATE INDEX idx_positive_embedding_knowledge_id
ON POSITIVE_EMBEDDING(knowledge_id);

-- Lookup carveout embedding theo policy
CREATE INDEX idx_carveout_embedding_policy_id
ON CARVEOUT_EMBEDDING(policy_id);

-- Lookup carveout embedding theo knowledge
CREATE INDEX idx_carveout_embedding_knowledge_id
ON CARVEOUT_EMBEDDING(knowledge_id);

-- ============================================================
-- PGVector index
-- BGE-M3 embedding dimension cần khớp với model thực tế.
--
-- Nếu model output 1024 dimension:
-- ============================================================

CREATE INDEX idx_positive_embedding_vector
ON POSITIVE_EMBEDDING
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX idx_carveout_embedding_vector
ON CARVEOUT_EMBEDDING
USING hnsw (embedding vector_cosine_ops);


-- ############################################################################
-- PART 2 — what this pipeline needs on top. Ours; idempotent; safe to re-run.
--
--   1. UNIQUE (policy_id) on each embedding table, because the seed upserts
--      with ON CONFLICT (policy_id). Their ER diagram allows policy -> vector
--      1:N; we use it 1:1, since the corpus is flattened to variant grain so
--      one policy row is one phrasing with one vector. Revisit only if a
--      second embedding model must live beside the first — which is what
--      their `embedding_model` / `embedding_version` columns are for.
--
--   2. The `positives` / `carveouts` views. `DocFetchOp` is called with
--      collection="positives" on both backends; on Postgres a collection has
--      to be a relation. They also alias knowledge_id -> group_id and join
--      knowledge_info for group_name, without which the pool renders with no
--      category label.
-- ############################################################################

-- ============================================================================
-- 1. One vector per policy row
--
-- ADD CONSTRAINT has no IF NOT EXISTS before PG 16's syntax for it landed in
-- a form we can rely on across versions, so guard on the catalogue instead.
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'uq_positive_embedding_policy') THEN
        ALTER TABLE positive_embedding
            ADD CONSTRAINT uq_positive_embedding_policy UNIQUE (policy_id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'uq_carveout_embedding_policy') THEN
        ALTER TABLE carveout_embedding
            ADD CONSTRAINT uq_carveout_embedding_policy UNIQUE (policy_id);
    END IF;
END
$$;


-- ============================================================================
-- 2. Collections, as relations
--
-- `sample_type` is deliberately not exposed: it is constant per view, read by
-- nothing, and spelled differently on the two backends — the FAISS sidecar
-- carries "positives", this DDL's CHECK requires "positive". Cheaper to stop
-- returning it than to make two spellings agree.
--
-- NOTE: `positives` / `carveouts` are generic names. Nothing else lives in
-- this database today, but if a future tenant collides, create these in a
-- dedicated schema and put it ahead of public on the connecting role's
-- search_path — the collection name reaching the store is a bare identifier
-- and cannot be schema-qualified.
-- ============================================================================

CREATE OR REPLACE VIEW positives AS
    SELECT p.id,
           p.knowledge_id  AS group_id,
           k.name          AS group_name,
           p.sample_type,
           p.content,
           p.description,
           p.severity
    FROM knowledge_policy p
    JOIN knowledge_info   k ON k.id = p.knowledge_id
    WHERE p.sample_type = 'positive';

CREATE OR REPLACE VIEW carveouts AS
    SELECT p.id,
           p.knowledge_id  AS group_id,
           k.name          AS group_name,
           p.sample_type,
           p.content,
           p.description,
           p.severity
    FROM knowledge_policy p
    JOIN knowledge_info   k ON k.id = p.knowledge_id
    WHERE p.sample_type = 'carveout';


-- ============================================================================
-- 3. Worklist — entries QC has never graded
--
-- The severity map is one-to-one for every tier the corpus currently uses
-- (tich_cuc/warning/cao/nghiem_trong -> SAFE/WARNING/HIGH/CRITICAL), so a graded
-- entry round-trips exactly. An UNGRADED one has no slot left: it is stored as
-- HIGH and reads back as `cao`. The seed keeps the original in metadata, which
-- makes those entries findable rather than lost.
-- ============================================================================

-- SELECT p.id, p.knowledge_id, p.content
-- FROM knowledge_policy p
-- JOIN positive_embedding e ON e.policy_id = p.id
-- WHERE e.metadata->>'severity_src' = 'unknown'
-- GROUP BY p.id, p.knowledge_id, p.content;


-- ============================================================================
-- 4. hnsw.ef_search — set before the planner starts using the HNSW indexes
--
-- The planner picks an access path per query by cost. Scanning the table costs
-- more as it grows; walking an HNSW graph stays roughly flat. Measured on this
-- schema, with 1024-d vectors and one query embedding:
--
--     rows=500    seq scan 21.08    hnsw 1478.98   -> seq scan
--     rows=700    seq scan 29.90    hnsw 1114.50   -> seq scan
--     rows=900    seq scan 37.72    hnsw   32.49   -> hnsw
--     rows=2000   seq scan 80.07    hnsw   33.30   -> hnsw
--
-- So the changeover is around 900-1000 rows, and `carveout_embedding` holds
-- 904 today. Nothing announces the day it flips: a sequential scan computes
-- every distance and is exact, an HNSW walk is approximate, and the results
-- simply start differing from the FAISS backend.
--
-- ef_search is how many candidates that walk keeps. Measured against FAISS
-- over 200 queries: 40 (the default) agreed on 189, 100 on 198, 200 on all
-- 200. Set now so recall is already right whenever the planner switches.
--
-- Written through current_database() so the file stays runnable against any
-- database name. Needs ownership of the database; it is the one statement
-- here that a plain table-creation grant will not cover.
-- ============================================================================

DO $$
BEGIN
    EXECUTE format('ALTER DATABASE %I SET hnsw.ef_search = 200',
                   current_database());
EXCEPTION WHEN insufficient_privilege THEN
    RAISE WARNING 'could not set hnsw.ef_search on %: %',
                  current_database(), SQLERRM;
    RAISE WARNING 'run as the database owner: ALTER DATABASE % SET hnsw.ef_search = 200',
                  current_database();
END $$;

-- NOTE: deliberately NOT setting enable_seqscan = off to force the index
-- early. That would apply to every query in the database, including tables
-- this schema knows nothing about. The planner arriving at HNSW on its own is
-- the intended path; this only makes sure it arrives with the right recall.
