-- WP2 migration 010. A bounded, deterministic SQL report payload.
-- No case persistence, AI, display rounding, or external action is implied.
DO $guard$
BEGIN
    IF current_database() = 'n8n' THEN
        RAISE EXCEPTION 'Refusing to install business functions in n8n metadata DB';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version = 9) THEN
        RAISE EXCEPTION 'Migration 009 is required first';
    END IF;
END
$guard$;

CREATE FUNCTION retail.deterministic_period_report_v1(
    p_source_file_sha256 text,
    p_start_inclusive timestamp without time zone,
    p_end_exclusive timestamp without time zone,
    p_source_as_of_exclusive timestamp without time zone
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
    kpi_payload jsonb;
    finding_mismatches bigint;
    flagged_source_rows bigint;
    finding_rows bigint;
    findings_by_code jsonb;
BEGIN
    -- The KPI function validates arguments, full-source integrity, invoice
    -- identity, and the source-time cutoff before quality is reported.
    SELECT to_jsonb(k) INTO kpi_payload
    FROM retail.canonical_period_kpis_asof_v1(
        p_source_file_sha256, p_start_inclusive, p_end_exclusive,
        p_source_as_of_exclusive) k;
    IF kpi_payload IS NULL THEN
        RAISE EXCEPTION 'Canonical as-of KPI result is missing';
    END IF;

    WITH selected AS (
        SELECT l.worksheet, l.source_row_number, l.invoice_no,
               l.stock_code, l.description, l.quantity,
               l.invoice_datetime_raw, l.unit_price_gbp,
               l.customer_id, l.classification
        FROM retail.invoice_lines l
        WHERE l.source_file_sha256 = p_source_file_sha256
          AND l.policy_version = 'v1'
          AND l.invoice_datetime_raw >= p_start_inclusive
          AND l.invoice_datetime_raw < p_end_exclusive
          AND l.invoice_datetime_raw < p_source_as_of_exclusive
          AND (
              (l.worksheet = 'Year 2009-2010'
               AND l.invoice_datetime_raw < timestamp '2010-12-01 00:00:00')
              OR (l.worksheet = 'Year 2010-2011'
                  AND l.invoice_datetime_raw >= timestamp '2010-12-01 00:00:00')
          )
    ), expected AS (
        SELECT l.worksheet, l.source_row_number, rule.finding_code
        FROM selected l
        CROSS JOIN LATERAL (VALUES
            ('missing_invoice', l.invoice_no IS NULL),
            ('missing_stock_code', l.stock_code IS NULL),
            ('invalid_invoice_datetime', l.invoice_datetime_raw IS NULL),
            ('invalid_quantity', l.quantity IS NULL),
            ('invalid_unit_price', l.unit_price_gbp IS NULL),
            ('negative_unit_price', l.unit_price_gbp < 0),
            ('zero_quantity', l.classification = 'zero_quantity_non_sales'),
            ('negative_quantity_without_c',
                l.classification = 'other_adjustment'
                AND upper(l.invoice_no) NOT LIKE 'C%' AND l.quantity < 0),
            ('c_invoice_non_negative_quantity',
                l.classification = 'other_adjustment'
                AND upper(l.invoice_no) LIKE 'C%' AND l.quantity >= 0),
            ('missing_customer_id', l.customer_id IS NULL),
            ('missing_description', l.description IS NULL),
            ('zero_price_sale',
                l.classification = 'sale' AND l.unit_price_gbp = 0)
        ) AS rule(finding_code, applies)
        WHERE rule.applies
    ), actual AS (
        SELECT f.worksheet, f.source_row_number, f.finding_code
        FROM selected l
        JOIN retail.quality_findings f
          ON f.source_file_sha256 = p_source_file_sha256
         AND f.worksheet = l.worksheet
         AND f.source_row_number = l.source_row_number
         AND f.policy_version = 'v1'
    ), mismatch AS (
        SELECT * FROM (
            SELECT * FROM expected EXCEPT SELECT * FROM actual
        ) missing
        UNION ALL
        SELECT * FROM (
            SELECT * FROM actual EXCEPT SELECT * FROM expected
        ) unexpected
    ), codes(finding_code) AS (
        VALUES ('missing_invoice'), ('missing_stock_code'),
               ('invalid_invoice_datetime'), ('invalid_quantity'),
               ('invalid_unit_price'), ('negative_unit_price'),
               ('zero_quantity'), ('negative_quantity_without_c'),
               ('c_invoice_non_negative_quantity'),
               ('missing_customer_id'), ('missing_description'),
               ('zero_price_sale')
    ), grouped AS (
        SELECT a.finding_code, count(*) AS n
        FROM actual a GROUP BY a.finding_code
    )
    SELECT (SELECT count(*) FROM mismatch),
           (SELECT count(DISTINCT (worksheet, source_row_number)) FROM actual),
           (SELECT count(*) FROM actual),
           (SELECT jsonb_object_agg(c.finding_code, coalesce(g.n, 0)
                                    ORDER BY c.finding_code)
            FROM codes c LEFT JOIN grouped g USING (finding_code))
    INTO finding_mismatches, flagged_source_rows,
         finding_rows, findings_by_code;

    IF finding_mismatches <> 0 THEN
        RAISE EXCEPTION 'Period quality findings differ from policy v1: % mismatch(es)',
            finding_mismatches;
    END IF;

    RETURN jsonb_build_object(
        'schema_version', 'deterministic-period-report-v1',
        'source_file_sha256', p_source_file_sha256,
        'policy_version', 'v1',
        'period_start_inclusive',
            to_char(p_start_inclusive, 'YYYY-MM-DD"T"HH24:MI:SS.US'),
        'period_end_exclusive',
            to_char(p_end_exclusive, 'YYYY-MM-DD"T"HH24:MI:SS.US'),
        'source_as_of_exclusive',
            to_char(p_source_as_of_exclusive, 'YYYY-MM-DD"T"HH24:MI:SS.US'),
        'kpis', kpi_payload,
        'quality', jsonb_build_object(
            'flagged_source_rows', flagged_source_rows,
            'finding_rows', finding_rows,
            'finding_rows_by_code', findings_by_code
        )
    );
END
$function$;

INSERT INTO retail.schema_migrations (version, name)
VALUES (10, 'deterministic_period_report_v1');
