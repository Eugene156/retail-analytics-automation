-- Permission and invalid-boundary checks; no fixture or fact mutation.
BEGIN;
SET LOCAL ROLE raa_wp2_api;
DO $negative$
BEGIN
    BEGIN
        PERFORM count(*) FROM retail.source_rows;
        RAISE EXCEPTION 'API role can read raw rows';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
    BEGIN
        DELETE FROM retail.invoice_lines WHERE false;
        RAISE EXCEPTION 'API role has direct DML permission';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
    BEGIN
        PERFORM retail.deterministic_comparison_report_v1(
            'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980',
            '2011-01-28 09:00', '2011-01-28 10:00', '2011-01-28 10:00');
        RAISE EXCEPTION 'API role bypassed restricted wrapper';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
    BEGIN
        PERFORM retail.api_comparison_report_v1('wrong', '2011-01-28 09:00',
            '2011-01-28 10:00', '2011-01-28 10:00');
        RAISE EXCEPTION 'Unpinned source accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
    BEGIN
        PERFORM retail.api_comparison_report_v1(
            'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980',
            '2009-12-03 09:00', '2009-12-03 10:00', '2009-12-03 10:00');
        RAISE EXCEPTION 'Prior outside archive accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
    BEGIN
        PERFORM retail.api_comparison_report_v1(
            'BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980',
            '2011-12-09 12:00', '2011-12-09 13:00', '2011-12-09 13:00');
        RAISE EXCEPTION 'Partial last source hour accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
END
$negative$;
SELECT 'PASS|api-role|no-raw-read|no-direct-dml|no-wrapper-bypass|pin|prior-range|partial-last-hour';
ROLLBACK;
