-- WP2 migration 008. Aggregate selected source lines, never per-sheet ratios.
-- The complete annual-sheet guards run before any canonical KPI is returned.
DO $guard$
BEGIN
    IF current_database() = 'n8n' THEN
        RAISE EXCEPTION 'Refusing to install business functions in n8n metadata DB';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version = 7) THEN
        RAISE EXCEPTION 'Migration 007 is required first';
    END IF;
END
$guard$;

CREATE FUNCTION retail.canonical_period_kpis_v1(
    p_source_file_sha256 text,
    p_start_inclusive timestamp without time zone,
    p_end_exclusive timestamp without time zone
)
RETURNS TABLE (
    period_source_rows bigint,
    sale_rows bigint,
    cancellation_rows bigint,
    other_adjustment_rows bigint,
    zero_quantity_rows bigint,
    invalid_rows bigint,
    sales_value_gbp numeric,
    cancellation_magnitude_gbp numeric,
    net_recorded_sales_gbp numeric,
    other_adjustment_signed_gbp numeric,
    invalid_signed_gbp numeric,
    invalid_value_calculable_rows bigint,
    sales_invoice_count bigint,
    average_sales_invoice_value_exact numeric,
    active_identified_customers bigint,
    missing_customer_sale_rows bigint,
    customer_coverage_exact numeric,
    units_sold numeric,
    zero_price_sale_rows bigint,
    cancellation_to_sales_value_ratio_exact numeric
)
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
    conflicting_invoices bigint;
BEGIN
    IF p_source_file_sha256 IS NULL OR p_start_inclusive IS NULL
       OR p_end_exclusive IS NULL OR p_start_inclusive >= p_end_exclusive THEN
        RAISE EXCEPTION 'A snapshot and non-empty [start, end) period are required';
    END IF;
    PERFORM retail.assert_uci_502_sheet_domain_v1(p_source_file_sha256);
    PERFORM retail.assert_uci_502_overlap_v1(p_source_file_sha256);

    WITH period_invoices AS (
        SELECT DISTINCT l.invoice_no
        FROM retail.invoice_lines l
        WHERE l.source_file_sha256 = p_source_file_sha256
          AND l.policy_version = 'v1'
          AND l.classification = 'sale'
          AND l.invoice_datetime_raw >= p_start_inclusive
          AND l.invoice_datetime_raw < p_end_exclusive
          AND (
              (l.worksheet = 'Year 2009-2010'
               AND l.invoice_datetime_raw < timestamp '2010-12-01 00:00:00')
              OR (l.worksheet = 'Year 2010-2011'
                  AND l.invoice_datetime_raw >= timestamp '2010-12-01 00:00:00')
          )
    ), invoice_groups AS (
        SELECT l.invoice_no
        FROM retail.invoice_lines l
        JOIN period_invoices p ON p.invoice_no = l.invoice_no
        WHERE l.source_file_sha256 = p_source_file_sha256
          AND l.policy_version = 'v1'
          AND l.classification = 'sale'
          AND (
              (l.worksheet = 'Year 2009-2010'
               AND l.invoice_datetime_raw < timestamp '2010-12-01 00:00:00')
              OR (l.worksheet = 'Year 2010-2011'
                  AND l.invoice_datetime_raw >= timestamp '2010-12-01 00:00:00')
          )
        GROUP BY l.invoice_no
        HAVING count(DISTINCT l.worksheet) > 1
            OR count(DISTINCT l.customer_id) > 1
            OR count(DISTINCT l.country) > 1
    )
    SELECT count(*) INTO conflicting_invoices FROM invoice_groups;
    IF conflicting_invoices > 0 THEN
        RAISE EXCEPTION 'Canonical sale invoice conflict: % affected invoice(s)',
            conflicting_invoices;
    END IF;

    RETURN QUERY
    WITH totals AS (
        SELECT
            count(*) AS source_count,
            count(*) FILTER (WHERE l.classification = 'sale') AS sale_count,
            count(*) FILTER (WHERE l.classification = 'cancellation') AS cancellation_count,
            count(*) FILTER (WHERE l.classification = 'other_adjustment') AS adjustment_count,
            count(*) FILTER (WHERE l.classification = 'zero_quantity_non_sales') AS zero_count,
            count(*) FILTER (WHERE l.classification = 'invalid') AS invalid_count,
            coalesce(sum(l.signed_line_value_gbp) FILTER
                (WHERE l.classification = 'sale'), 0::numeric) AS sales_sum,
            -coalesce(sum(l.signed_line_value_gbp) FILTER
                (WHERE l.classification = 'cancellation'), 0::numeric) AS cancellation_sum,
            coalesce(sum(l.signed_line_value_gbp) FILTER
                (WHERE l.classification = 'other_adjustment'), 0::numeric) AS adjustment_sum,
            coalesce(sum(l.signed_line_value_gbp) FILTER
                (WHERE l.classification = 'invalid'), 0::numeric) AS invalid_sum,
            count(*) FILTER (WHERE l.classification = 'invalid'
                AND l.signed_line_value_gbp IS NOT NULL) AS invalid_calculable_count,
            count(DISTINCT l.invoice_no) FILTER
                (WHERE l.classification = 'sale') AS invoice_count,
            count(DISTINCT l.customer_id) FILTER
                (WHERE l.classification = 'sale') AS identified_count,
            count(*) FILTER (WHERE l.classification = 'sale'
                AND l.customer_id IS NULL) AS missing_customer_count,
            coalesce(sum(l.quantity) FILTER
                (WHERE l.classification = 'sale'), 0::numeric) AS units_sum,
            count(*) FILTER (WHERE l.classification = 'sale'
                AND l.unit_price_gbp = 0) AS zero_price_count
        FROM retail.invoice_lines l
        WHERE l.source_file_sha256 = p_source_file_sha256
          AND l.policy_version = 'v1'
          AND l.invoice_datetime_raw >= p_start_inclusive
          AND l.invoice_datetime_raw < p_end_exclusive
          AND (
              (l.worksheet = 'Year 2009-2010'
               AND l.invoice_datetime_raw < timestamp '2010-12-01 00:00:00')
              OR (l.worksheet = 'Year 2010-2011'
                  AND l.invoice_datetime_raw >= timestamp '2010-12-01 00:00:00')
          )
    )
    SELECT
        t.source_count, t.sale_count, t.cancellation_count,
        t.adjustment_count, t.zero_count, t.invalid_count,
        t.sales_sum, t.cancellation_sum, t.sales_sum - t.cancellation_sum,
        t.adjustment_sum, t.invalid_sum, t.invalid_calculable_count,
        t.invoice_count,
        CASE WHEN t.invoice_count = 0 THEN NULL
             ELSE t.sales_sum / t.invoice_count END,
        t.identified_count, t.missing_customer_count,
        CASE WHEN t.sale_count = 0 THEN NULL
             ELSE (t.sale_count - t.missing_customer_count)::numeric / t.sale_count END,
        t.units_sum, t.zero_price_count,
        CASE WHEN t.sales_sum = 0 THEN NULL
             ELSE t.cancellation_sum / t.sales_sum END
    FROM totals t;
END
$function$;

INSERT INTO retail.schema_migrations (version, name)
VALUES (8, 'canonical_period_kpis_v1');
