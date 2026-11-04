-- Read-only policy-v1 parser edge checks. No source or derived rows are written.
DO $test$
BEGIN
    IF retail.try_numeric('1.25') <> 1.25::numeric
       OR retail.try_numeric('1e2') <> 100::numeric
       OR retail.try_numeric('NaN') IS NOT NULL
       OR retail.try_numeric('not-a-number') IS NOT NULL
       OR retail.try_source_timestamp('2011-03-01T10:00:00')
          <> '2011-03-01T10:00:00'::timestamp
       OR retail.try_source_timestamp('2011-02-30T10:00:00') IS NOT NULL
       OR retail.try_source_timestamp('2011-03-01T10:00:00+03:00') IS NOT NULL THEN
        RAISE EXCEPTION 'Policy-v1 safe parsing failed';
    END IF;
END
$test$;
