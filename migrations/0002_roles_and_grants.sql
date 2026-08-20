do $$
begin
    if not exists (select from pg_roles where rolname = 'app_rw') then
        create role app_rw with login password '${APP_RW_PASSWORD}';
    else
        alter role app_rw with password '${APP_RW_PASSWORD}';
    end if;

    if not exists (select from pg_roles where rolname = 'app_ro') then
        create role app_ro with login password '${APP_RO_PASSWORD}';
    else
        alter role app_ro with password '${APP_RO_PASSWORD}';
    end if;
end
$$;

grant usage on schema public to app_rw, app_ro;

grant select, insert, update, delete on all tables in schema public to app_rw;
grant usage, select on all sequences in schema public to app_rw;
alter default privileges in schema public grant select, insert, update, delete on tables to app_rw;
alter default privileges in schema public grant usage, select on sequences to app_rw;

grant select on all tables in schema public to app_ro;
alter default privileges in schema public grant select on tables to app_ro;
