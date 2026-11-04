param(
    [string[]]$Paths = @('docs/WP1_AS_IS.bpmn', 'docs/WP1_TO_BE.bpmn')
)

$ErrorActionPreference = 'Stop'
$flowNodeTypes = @('startEvent', 'endEvent', 'task', 'exclusiveGateway', 'boundaryEvent')

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

foreach ($path in $Paths) {
    [xml]$doc = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    $processes = @($doc.SelectNodes("//*[local-name()='process']"))
    Assert-True ($processes.Count -eq 1) "${path}: expected one process"
    $process = $processes[0]
    Assert-True ($process.GetAttribute('isExecutable') -eq 'false') "${path}: design process must not claim to be executable"

    $ids = @{}
    foreach ($element in $doc.SelectNodes('//*[@id]')) {
        $id = $element.GetAttribute('id')
        Assert-True (-not $ids.ContainsKey($id)) "${path}: duplicate id $id"
        $ids[$id] = $element
    }

    $nodes = @($process.ChildNodes | Where-Object { $_.LocalName -in $flowNodeTypes })
    $flows = @($process.ChildNodes | Where-Object { $_.LocalName -eq 'sequenceFlow' })
    $lanes = @($process.SelectNodes("./*[local-name()='laneSet']/*[local-name()='lane']"))
    Assert-True (($nodes | Where-Object LocalName -eq 'startEvent').Count -eq 1) "${path}: expected one start event"
    Assert-True (($nodes | Where-Object LocalName -eq 'endEvent').Count -ge 1) "${path}: expected an end event"
    Assert-True ($lanes.Count -ge 3) "${path}: analyst, reviewer and system lanes required"

    $nodeIds = @{}; foreach ($node in $nodes) { $nodeIds[$node.GetAttribute('id')] = $node }
    $flowIds = @{}; foreach ($flow in $flows) { $flowIds[$flow.GetAttribute('id')] = $flow }
    $laneRefs = @{}
    foreach ($lane in $lanes) {
        foreach ($ref in $lane.SelectNodes("./*[local-name()='flowNodeRef']")) {
            $id = $ref.InnerText
            Assert-True ($nodeIds.ContainsKey($id)) "${path}: lane refers to missing node $id"
            Assert-True (-not $laneRefs.ContainsKey($id)) "${path}: node $id belongs to multiple lanes"
            $laneRefs[$id] = $lane.GetAttribute('id')
        }
    }
    foreach ($node in $nodes) {
        $id = $node.GetAttribute('id')
        Assert-True ($laneRefs.ContainsKey($id)) "${path}: node $id has no lane"
        if ($node.LocalName -eq 'boundaryEvent') {
            $attached = $node.GetAttribute('attachedToRef')
            Assert-True ($nodeIds.ContainsKey($attached)) "${path}: boundary $id has no valid attached task"
        }
    }

    $adjacency = @{}; foreach ($id in $nodeIds.Keys) { $adjacency[$id] = @() }
    foreach ($flow in $flows) {
        $id = $flow.GetAttribute('id'); $source = $flow.GetAttribute('sourceRef'); $target = $flow.GetAttribute('targetRef')
        Assert-True ($nodeIds.ContainsKey($source) -and $nodeIds.ContainsKey($target)) "${path}: $id has invalid endpoints"
        $adjacency[$source] = @($adjacency[$source]) + $target
        Assert-True ($nodeIds[$source].SelectNodes("./*[local-name()='outgoing' and text()='$id']").Count -eq 1) "${path}: $source is missing outgoing $id"
        Assert-True ($nodeIds[$target].SelectNodes("./*[local-name()='incoming' and text()='$id']").Count -eq 1) "${path}: $target is missing incoming $id"
    }

    $plane = @($doc.SelectNodes("//*[local-name()='BPMNPlane']"))
    Assert-True ($plane.Count -eq 1 -and $plane[0].GetAttribute('bpmnElement') -eq $process.GetAttribute('id')) "${path}: missing process diagram plane"
    $shapeRefs = @{}; foreach ($shape in $plane[0].SelectNodes("./*[local-name()='BPMNShape']")) {
        $ref = $shape.GetAttribute('bpmnElement')
        Assert-True (-not $shapeRefs.ContainsKey($ref)) "${path}: duplicate shape for $ref"
        Assert-True ($null -ne $shape.SelectSingleNode("./*[local-name()='Bounds']")) "${path}: missing shape bounds for $ref"
        $shapeRefs[$ref] = $true
    }
    foreach ($id in @($nodeIds.Keys) + @($lanes | ForEach-Object { $_.GetAttribute('id') })) {
        Assert-True ($shapeRefs.ContainsKey($id)) "${path}: missing diagram shape for $id"
    }
    $edgeRefs = @{}; foreach ($edge in $plane[0].SelectNodes("./*[local-name()='BPMNEdge']")) {
        $ref = $edge.GetAttribute('bpmnElement')
        Assert-True (-not $edgeRefs.ContainsKey($ref)) "${path}: duplicate edge for $ref"
        Assert-True ($edge.SelectNodes("./*[local-name()='waypoint']").Count -ge 2) "${path}: edge $ref needs two waypoints"
        $edgeRefs[$ref] = $true
    }
    foreach ($id in $flowIds.Keys) { Assert-True ($edgeRefs.ContainsKey($id)) "${path}: missing diagram edge for $id" }

    if ($path -like '*TO_BE*') {
        Assert-True ($nodeIds['T_Timeout'].SelectNodes("./*[local-name()='timerEventDefinition']").Count -eq 1) "${path}: model timeout missing"
        Assert-True ($nodeIds['T_PublishError'].SelectNodes("./*[local-name()='errorEventDefinition']").Count -eq 1) "${path}: publish failure boundary missing"
        Assert-True ($adjacency['T_PublishError'] -contains 'T_Reconcile') "${path}: uncertain publish must reconcile"
        Assert-True ($adjacency['T_Reconcile'] -contains 'T_Retry') "${path}: recovery decision must follow reconciliation"
        Assert-True ($adjacency['T_Timeout'] -contains 'T_Fallback') "${path}: model timeout must use deterministic fallback"
        Assert-True ($adjacency['T_Reject'] -contains 'T_RejectedEnd') "${path}: rejection must end without publication"
    }
    Write-Output "PASS ${path}: $($nodes.Count) nodes, $($flows.Count) flows, $($lanes.Count) lanes, complete diagram references"
}
