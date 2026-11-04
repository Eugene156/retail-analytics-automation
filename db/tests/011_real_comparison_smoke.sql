-- Read-only smoke against the pinned archive; WP1 source counts are frozen.
-- Prior monetary values are SQL observations, NOT independent XLSX evidence.
BEGIN READ ONLY;
DO $smoke$
DECLARE
    fixture record;
    p jsonb;
BEGIN
    FOR fixture IN SELECT * FROM (VALUES
        ('M02', timestamp '2011-01-28 09:00', timestamp '2011-01-28 10:00', 74, 43, 1349.45::numeric),
        ('M03', timestamp '2011-10-06 20:00', timestamp '2011-10-06 21:00', 67, 0, 0::numeric),
        ('M10', timestamp '2011-01-01 00:00', timestamp '2011-01-01 01:00', 0, 0, 0::numeric)
    ) v(case_id, start_at, end_at, current_rows, prior_rows, current_sales)
    LOOP
        p := retail.deterministic_comparison_report_v1(
            'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980',
            fixture.start_at, fixture.end_at, fixture.end_at);
        IF (p->'current_period'->'kpis'->>'period_source_rows')::int
                IS DISTINCT FROM fixture.current_rows
           OR (p->'prior_period'->'kpis'->>'period_source_rows')::int
                IS DISTINCT FROM fixture.prior_rows
           OR (p->'changes'->'sales_value_gbp'->>'current_value')::numeric
                IS DISTINCT FROM fixture.current_sales THEN
            RAISE EXCEPTION 'Frozen source-count/current-sales mismatch: %', fixture.case_id;
        END IF;
        IF fixture.prior_rows = 0 AND EXISTS (
            SELECT 1 FROM jsonb_each(p->'changes') m
            WHERE (m.value->>'prior_value')::numeric IS DISTINCT FROM 0
               OR m.value->'relative_change' IS DISTINCT FROM 'null'::jsonb
               OR m.value->>'relative_change_status' IS DISTINCT FROM 'zero_baseline'
        ) THEN
            RAISE EXCEPTION 'Empty baseline mismatch: %', fixture.case_id;
        END IF;
        RAISE NOTICE 'REAL_COMPARISON|%|current_rows=%|prior_rows=%|changes=%',
            fixture.case_id, fixture.current_rows, fixture.prior_rows, p->'changes';
    END LOOP;
END
$smoke$;
SELECT 'PASS|real-comparison|M02|M03|M10';
ROLLBACK;
