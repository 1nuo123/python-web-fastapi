param(
  [Parameter(Mandatory = $true)][string]$InputPath
)
if (-not $env:AZURE_KEY_VAULT_URL -or -not $env:AZURE_CERTIFICATE_NAME) {
  throw "Managed signing configuration is missing."
}
$azureCli = Get-Command az -ErrorAction SilentlyContinue
if ($null -eq $azureCli) {
  throw "Azure CLI is required after the OIDC login step."
}
& $azureCli.Source account show --output none --only-show-errors
if ($LASTEXITCODE -ne 0) {
  throw "Azure CLI is not authenticated by the OIDC login step."
}
$azureSignToolVersion = "6.0.1"
$toolPath = Join-Path $PSScriptRoot ".tools"
$toolExecutable = Join-Path $toolPath "AzureSignTool.exe"
if (-not (Test-Path -LiteralPath $toolExecutable -PathType Leaf)) {
  dotnet tool install AzureSignTool --tool-path $toolPath --version $azureSignToolVersion
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to install the pinned AzureSignTool version."
  }
}
& $toolExecutable sign `
  -kvu $env:AZURE_KEY_VAULT_URL `
  -kvm `
  -kvc $env:AZURE_CERTIFICATE_NAME `
  -tr "http://timestamp.digicert.com" `
  -td sha256 `
  -fd sha256 `
  $InputPath
if ($LASTEXITCODE -ne 0) {
  throw "Authenticode signing failed."
}
