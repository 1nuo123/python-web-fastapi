param(
  [Parameter(Mandatory = $true)][string]$InputPath
)
if (-not $env:AZURE_KEY_VAULT_URL -or -not $env:AZURE_CERTIFICATE_NAME) {
  throw "缺少托管签名服务配置。"
}
dotnet tool update --global AzureSignTool
AzureSignTool sign `
  -kvu $env:AZURE_KEY_VAULT_URL `
  -kvc $env:AZURE_CERTIFICATE_NAME `
  -tr "http://timestamp.digicert.com" `
  -td sha256 `
  -fd sha256 `
  $InputPath
