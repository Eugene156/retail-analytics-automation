-- WP2 migration 011. Fixed seven-calendar-day comparison in source time.
DO $guard$
BEGIN
    IF current_database() = 'n8n' THEN
        RAISE EXCEPTION 'Refusing to install business functions in n8n metadata DB';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version = 10) THEN
        RAISE EXCEPTION 'Migration 010 is required first';
    END IF;
END
$guard$;

CREATE FUNCTION retail.deterministic_comparison_report_v1(
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
    current_report jsonb;
    prior_report jsonb;
    changes jsonb;
BEGIN
    -- Both periods use the SAME case cutoff, snapshot and policy. Prior-period
    -- invoice identity is not evaluated against a different historical cutoff.
    current_report := retail.deterministic_period_report_v1(
        p_source_file_sha256, p_start_inclusive, p_end_exclusive,
        p_source_as_of_exclusive);
    prior_report := retail.deterministic_period_report_v1(
        p_source_file_sha256, p_start_inclusive - interval '7 days',
        p_end_exclusive - interval '7 days', p_source_as_of_exclusive);

    WITH metrics(metric_id) AS (
        VALUES ('sales_value_gbp'), ('cancellation_magnitude_gbp'),
               ('net_recorded_sales_gbp'), ('sales_invoice_count'),
               ('active_identified_customers'), ('units_sold')
    ), values_to_compare AS (
        SELECT metric_id,
               (current_report->'kpis'->>metric_id)::numeric AS current_value,
               (prior_report->'kpis'->>metric_id)::numeric AS prior_value
        FROM metrics
    )
    SELECT jsonb_object_agg(metric_id, jsonb_build_object(
        'current_value', current_value,
        'prior_value', prior_value,
        'absolute_change', current_value - prior_value,
        'relative_change', CASE WHEN prior_value <> 0
            THEN (current_value - prior_value) / abs(prior_value) ELSE NULL END,
        'relative_change_status', CASE WHEN prior_value = 0
            THEN 'zero_baseline' ELSE 'available' END
    ) ORDER BY metric_id)
    INTO changes FROM values_to_compare;

    RETURN jsonb_build_object(
        'schema_version', 'deterministic-comparison-report-v1',
        'comparison_rule', 'same-window-seven-calendar-days-earlier',
        'relative_change_formula', '(current-prior)/abs(prior)',
        'source_time_interpretation', 'naive workbook time',
        'current_period', current_report,
        'prior_period', prior_report,
        'changes', changes
    );
END
$function$;

INSERT INTO retail.schema_migrations (version, name)
VALUES (11, 'deterministic_comparison_report_v1');
