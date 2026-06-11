# Actualiza o instala el módulo connector_prestashop en Odoo (Docker)
param(
    [string]$Module = "connector_prestashop",
    [string]$Database = "stylesync",
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# Cargar POSTGRES_DB desde .env si existe
$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*POSTGRES_DB\s*=\s*(.+)\s*$') {
            $Database = $Matches[1].Trim()
        }
    }
}

Set-Location $ProjectRoot

Write-Host "`n[1/3] Deteniendo Odoo..." -ForegroundColor Cyan
docker compose stop odoo

$OdooArgs = @("-d", $Database, "--stop-after-init")
if ($Install) {
    $OdooArgs = @("-i", $Module) + $OdooArgs
    Write-Host "[2/3] Instalando modulo $Module en base '$Database'..." -ForegroundColor Cyan
} else {
    $OdooArgs = @("-u", $Module) + $OdooArgs
    Write-Host "[2/3] Actualizando modulo $Module en base '$Database'..." -ForegroundColor Cyan
}

docker compose run --rm odoo odoo @OdooArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error al actualizar el modulo." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "[3/3] Reiniciando Odoo..." -ForegroundColor Cyan
docker compose up -d odoo

Write-Host "`nModulo $Module listo. Odoo: http://localhost:8069`n" -ForegroundColor Green
