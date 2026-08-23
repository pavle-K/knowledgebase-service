create extension if not exists vector;
create extension if not exists pgcrypto;

create table projects (
    id             uuid primary key default gen_random_uuid(),
    name           text not null,
    repo_url       text unique,
    description    text,
    source         text not null default 'github',
    default_branch text,
    is_private     boolean default false,
    created_at     timestamptz default now(),
    updated_at     timestamptz default now()
);

create table technologies (
    id       uuid primary key default gen_random_uuid(),
    name     text unique not null,
    category text
);

create table project_technologies (
    project_id    uuid references projects(id) on delete cascade,
    technology_id uuid references technologies(id) on delete cascade,
    primary key (project_id, technology_id)
);

-- L1: documents
create table documents (
    id           uuid primary key default gen_random_uuid(),
    project_id   uuid references projects(id) on delete cascade,
    doc_type     text not null,
    source_path  text not null,
    chunk_index  int not null default 0,
    content      text not null,
    embedding    vector(1536),
    content_hash text not null,
    created_at   timestamptz default now(),
    unique (project_id, source_path, chunk_index)
);

-- L2: code chunks
create table code_chunks (
    id           uuid primary key default gen_random_uuid(),
    project_id   uuid references projects(id) on delete cascade,
    file_path    text not null,
    symbol_name  text,
    symbol_type  text,
    language     text,
    start_line   int,
    end_line     int,
    content      text not null,
    docstring    text,
    embedding    vector(1536),
    content_hash text not null,
    created_at   timestamptz default now(),
    unique (project_id, file_path, symbol_name, start_line)
);

-- L3: dependency graph
create table exposed_interfaces (
    id          uuid primary key default gen_random_uuid(),
    project_id  uuid references projects(id) on delete cascade,
    kind        text not null,
    identifier  text not null,
    contract    jsonb,
    source      text not null,
    file_path   text,
    created_at  timestamptz default now(),
    unique (project_id, kind, identifier)
);

create table dependencies (
    id                   uuid primary key default gen_random_uuid(),
    consumer_project_id  uuid references projects(id) on delete cascade,
    provider_project_id  uuid references projects(id) on delete set null,
    kind                 text not null,
    identifier           text not null,
    external_name        text,
    version_constraint   text,
    source               text not null,
    file_path            text,
    created_at           timestamptz default now(),
    unique (consumer_project_id, kind, identifier)
);

-- L4: commit history
create table commits (
    id            uuid primary key default gen_random_uuid(),
    project_id    uuid references projects(id) on delete cascade,
    sha           text not null,
    message       text,
    author        text,
    committed_at  timestamptz,
    files_changed text[],
    additions     int,
    deletions     int,
    diff_summary  text,
    embedding     vector(1536),
    created_at    timestamptz default now(),
    unique (project_id, sha)
);

create table ingestion_log (
    id         uuid primary key default gen_random_uuid(),
    source     text not null,
    project_id uuid references projects(id) on delete set null,
    layer      text,
    status     text not null,
    detail     jsonb,
    created_at timestamptz default now()
);

create table secret_scan_findings (
    id         uuid primary key default gen_random_uuid(),
    project_id uuid references projects(id) on delete cascade,
    file_path  text not null,
    rule_id    text not null,
    created_at timestamptz default now()
);

create index on dependencies (provider_project_id, identifier);
create index on exposed_interfaces (project_id, kind);

-- HNSW vector indexes intentionally omitted: not worth it below ~1k rows.
-- Add via a later migration once real row counts justify it.
