-- Private repos stay ingested but are visible only to privileged readers.
--
-- Enforced with row-level security rather than a WHERE clause in the query code:
-- the SQL node runs LLM-generated statements, so an application-level filter is
-- bypassable by a sufficiently creative generated query. app_ro_public sees only
-- rows belonging to public projects, whatever SQL it runs.

do $$
begin
    if not exists (select from pg_roles where rolname = 'app_ro_public') then
        create role app_ro_public with login password '${APP_RO_PUBLIC_PASSWORD}';
    else
        alter role app_ro_public with password '${APP_RO_PUBLIC_PASSWORD}';
    end if;
end
$$;

grant usage on schema public to app_ro_public;
grant select on all tables in schema public to app_ro_public;
alter default privileges in schema public grant select on tables to app_ro_public;

alter table projects            enable row level security;
alter table documents           enable row level security;
alter table code_chunks         enable row level security;
alter table commits             enable row level security;
alter table exposed_interfaces  enable row level security;
alter table dependencies        enable row level security;
alter table project_technologies enable row level security;
alter table secret_scan_findings enable row level security;
alter table ingestion_log       enable row level security;

-- Ingestion and privileged reads are unrestricted; only app_ro_public is filtered.
create policy projects_privileged on projects
    for all to app_rw, app_ro using (true) with check (true);
create policy documents_privileged on documents
    for all to app_rw, app_ro using (true) with check (true);
create policy code_chunks_privileged on code_chunks
    for all to app_rw, app_ro using (true) with check (true);
create policy commits_privileged on commits
    for all to app_rw, app_ro using (true) with check (true);
create policy exposed_interfaces_privileged on exposed_interfaces
    for all to app_rw, app_ro using (true) with check (true);
create policy dependencies_privileged on dependencies
    for all to app_rw, app_ro using (true) with check (true);
create policy project_technologies_privileged on project_technologies
    for all to app_rw, app_ro using (true) with check (true);
create policy secret_scan_findings_privileged on secret_scan_findings
    for all to app_rw, app_ro using (true) with check (true);
create policy ingestion_log_privileged on ingestion_log
    for all to app_rw, app_ro using (true) with check (true);

-- Child-table policies resolve the parent through projects, which is itself
-- filtered for this role - a private project is unreachable from either side.
create policy projects_public on projects
    for select to app_ro_public using (is_private = false);

create policy documents_public on documents
    for select to app_ro_public using (
        exists (select 1 from projects p where p.id = documents.project_id)
    );
create policy code_chunks_public on code_chunks
    for select to app_ro_public using (
        exists (select 1 from projects p where p.id = code_chunks.project_id)
    );
create policy commits_public on commits
    for select to app_ro_public using (
        exists (select 1 from projects p where p.id = commits.project_id)
    );
create policy exposed_interfaces_public on exposed_interfaces
    for select to app_ro_public using (
        exists (select 1 from projects p where p.id = exposed_interfaces.project_id)
    );
create policy dependencies_public on dependencies
    for select to app_ro_public using (
        exists (select 1 from projects p where p.id = dependencies.consumer_project_id)
    );
create policy project_technologies_public on project_technologies
    for select to app_ro_public using (
        exists (select 1 from projects p where p.id = project_technologies.project_id)
    );

-- Findings and ingestion history name private paths and repos: privileged only.
create policy secret_scan_findings_public on secret_scan_findings
    for select to app_ro_public using (false);
create policy ingestion_log_public on ingestion_log
    for select to app_ro_public using (false);
