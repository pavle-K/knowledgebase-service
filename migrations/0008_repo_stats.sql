-- Generic per-repo stats already present on every GitHub repo API response -
-- no new API call needed, just capturing fields list_repos() was discarding.
-- repo_created_at/repo_pushed_at are deliberately separate from this table's
-- own created_at/updated_at, which track when *we* ingested the row, not
-- GitHub's own repo timeline.
alter table projects add column repo_created_at timestamptz;
alter table projects add column repo_pushed_at timestamptz;
alter table projects add column stargazers_count int;
alter table projects add column language text;
alter table projects add column forks_count int;
alter table projects add column open_issues_count int;
