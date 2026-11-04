-- WP2 migration 003. PL/pgSQL exception blocks create subtransactions and
-- cannot be invoked inside PostgreSQL parallel workers. Keep parsing serial.
DO $guard$
BEGIN
    IF current_database() = 'n8n' THEN
        RAISE EXCEPTION 'Refusing to modify business functions in n8n metadata DB';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version = 2) THEN
        RAISE EXCEPTION 'Migration 002 is required first';
    END IF;
END
$guard$;

ALTER FUNCTION retail.try_numeric(text) PARALLEL UNSAFE;
ALTER FUNCTION retail.try_source_timestamp(text) PARALLEL UNSAFE;

INSERT INTO retail.schema_migrations (version, name)
VALUES (3, 'safe_parse_execution');
