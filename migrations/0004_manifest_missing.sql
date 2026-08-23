-- Tracks L3 coverage gaps: a repo starts marked manifest_missing so gaps are visible
-- rather than silently treated as "no dependencies." Defaults true until L3 ingestion
-- checks each repo.
alter table projects add column manifest_missing boolean not null default true;
