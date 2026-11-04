// Mandatory labels/values come from actual observations, never model arithmetic.
function renderReadToolAnswer(input, names, mcp) {
  const steps = input.intermediateSteps;
  if (typeof input.output !== 'string' || input.output.length > 3000 ||
      !Array.isArray(steps) || !steps.length || steps.length > 2)
    throw new Error('Invalid model answer or actual tool evidence');
  const model = JSON.parse(input.output);
  if (!model || Array.isArray(model) || Object.keys(model).join() !== 'source_tools' ||
      !Array.isArray(model.source_tools) || !model.source_tools.length ||
      model.source_tools.some(t => typeof t !== 'string') ||
      new Set(model.source_tools).size !== model.source_tools.length)
    throw new Error('Invalid model source-tools schema');
  const bodies = {};
  for (const step of steps) {
    const name = names[step.action?.tool];
    if (!name || bodies[name] || typeof step.observation !== 'string')
      throw new Error('Unknown, repeated or missing actual tool call');
    const values = JSON.parse(step.observation);
    const body = mcp ? values?.[0]?.structuredContent : values?.[0];
    if (!Array.isArray(values) || values.length !== 1 ||
        body?.access !== 'read-only' || body?.schema_version !== 'p2-read-tool-v1' ||
        typeof body.source_file_sha256 !== 'string' || !body.source_file_sha256 ||
        !body.period || body.period.source_file_sha256 !== body.source_file_sha256)
      throw new Error('Invalid read-only tool response');
    bodies[name] = body;
  }
  const actual = Object.keys(bodies).sort();
  if (JSON.stringify([...model.source_tools].sort()) !== JSON.stringify(actual))
    throw new Error('Model source tools do not match actual calls');
  const observations = Object.values(bodies);
  if (observations.some(b => b.source_file_sha256 !== observations[0].source_file_sha256 ||
      JSON.stringify(b.period) !== JSON.stringify(observations[0].period)))
    throw new Error('Tool provenance mismatch');
  const lines = [], facts = [];
  function add(label, value, money, source_tool, field) {
    if (money ? typeof value !== 'string' || !/^-?\d+\.\d{2}$/.test(value) :
        !Number.isSafeInteger(value) || value < 0)
      throw new Error('Missing or invalid mandatory tool fact');
    lines.push(label + ': ' + (money ? 'GBP ' : '') + String(value));
    facts.push({label, value, source_tool, field});
  }
  for (const name of actual) {
    const b = bodies[name];
    if (name === 'Get_Sales_KPIs' || name === 'get_sales_kpis') {
      for (const [label, field, money] of [
        ['Sale rows', 'sale_rows', false],
        ['Net recorded sales', 'net_recorded_sales_gbp', true],
        ['Gross sales', 'sales_value_gbp', true],
        ['Cancellation rows', 'cancellation_rows', false],
        ['Cancellation magnitude', 'cancellation_magnitude_gbp', true]])
        add(label, b.kpis?.[field], money, name, 'kpis.' + field);
    } else {
      add('Quality findings', b.quality?.finding_rows, false, name, 'quality.finding_rows');
      add('Missing customer sale rows', b.missing_customer_sale_rows, false, name, 'missing_customer_sale_rows');
    }
  }
  return {...input, output: lines.join('\n'), raw_model_output: input.output,
    model_response: model, evidenced_facts: facts};
}
