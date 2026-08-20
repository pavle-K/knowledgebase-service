-- Tracks coverage gaps per CLAUDE.md section 5: "mark the project as manifest_missing
-- so I can see coverage gaps." Defaults true until L3 ingestion checks each repo.
alter table projects add column manifest_missing boolean not null default true;
