#!/usr/bin/env pwsh
# Phase 1 verification: wait for DBs, seed, print counts, run Cypher gate
$ErrorActionPreference = "Stop"
$LocalRoot = Split-Path -Parent $PSScriptRoot
Set-Location $LocalRoot

Write-Host "== Waiting for docker compose health =="
docker compose up -d
$deadline = (Get-Date).AddMinutes(3)
do {
    Start-Sleep -Seconds 5
    $ps = docker compose ps --format json | ConvertFrom-Json
    if ($ps -isnot [array]) { $ps = @($ps) }
    $healthy = ($ps | Where-Object { $_.Health -eq "healthy" }).Count
    Write-Host "Healthy services: $healthy / $($ps.Count)"
    if ($healthy -ge 3) { break }
} while ((Get-Date) -lt $deadline)

if ($healthy -lt 3) {
    Write-Host "FAIL: databases not healthy in time"
    docker compose ps
    exit 1
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

Write-Host "== Installing Python deps (if needed) =="
python -m pip install -q -r requirements.txt

Write-Host "== Running loader =="
$env:PYTHONPATH = $LocalRoot
python -m backend.db.sample_data
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: loader exited $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "== Redis PING =="
docker compose exec -T redis redis-cli ping

Write-Host "== Critical Cypher (Z96.641 / MCARE_A) =="
docker compose exec -T neo4j cypher-shell -u neo4j -p intakeai_dev "
MATCH (d:Diagnosis {icdCode: 'Z96.641'})-[r:REQUIRES]->(s:ServiceType)
OPTIONAL MATCH (s)-[n:NEEDS_CERTIFICATION]->(c:CertificationType)
RETURN d.icdCode, s.name, r.priority, collect(c.name) AS certs;
MATCH (p:InsurancePlan {code: 'MCARE_A'})-[cov:COVERS]->(s:ServiceType)
WHERE s.name IN ['skilled_nursing', 'physical_therapy']
RETURN p.code, s.name, cov.priorAuthRequired, cov.requiredDocs;
"

Write-Host "== PASS: Phase 1 seed verification complete =="
