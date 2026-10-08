#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact='Medium')]
param(
    [Parameter(Mandatory=$true)][string]$SiteName,
    [Parameter(Mandatory=$true)][string]$StaticRoot,
    [Parameter(Mandatory=$true)][string]$MediaRoot,
    [ValidatePattern('^http://127\.0\.0\.1:\d+$')][string]$BackendUrl = 'http://127.0.0.1:8000'
)
$ErrorActionPreference = 'Stop'
foreach ($directory in @($StaticRoot, $MediaRoot)) {
    if (-not [IO.Path]::IsPathRooted($directory) -or -not (Test-Path -LiteralPath $directory -PathType Container)) {
        throw "La ruta debe ser absoluta y existir: $directory"
    }
}
$StaticRoot = (Resolve-Path -LiteralPath $StaticRoot).ProviderPath
$MediaRoot = (Resolve-Path -LiteralPath $MediaRoot).ProviderPath
Add-Type -Path "$env:windir\System32\inetsrv\Microsoft.Web.Administration.dll"
$manager = New-Object Microsoft.Web.Administration.ServerManager
try {
    $site = $manager.Sites[$SiteName]
    if ($null -eq $site) { throw "No existe el sitio IIS: $SiteName" }
    $application = $site.Applications['/']
    foreach ($alias in @('/static', '/media')) {
        if ($null -ne $site.Applications[$alias]) { throw "$alias ya es una aplicación IIS; revisar antes de aplicar." }
    }
    $config = $manager.GetApplicationHostConfiguration()
    # These lookups also validate that ARR and URL Rewrite are installed.
    $proxy = $config.GetSection('system.webServer/proxy')
    $rewrite = $config.GetSection('system.webServer/rewrite/rules', $SiteName)
    Write-Output "Sitio: $SiteName; /static -> $StaticRoot; /media -> $MediaRoot; proxy -> $BackendUrl"
    Write-Output 'Se reemplazan las reglas inbound del sitio; se habilita ARR proxy a nivel servidor.'
    if (-not $PSCmdlet.ShouldProcess($SiteName, 'Respaldar IIS y configurar directorios virtuales y proxy')) { return }
    $backupName = 'NovaDesk-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-ffff')
    & "$env:windir\System32\inetsrv\appcmd.exe" add backup $backupName
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo respaldar IIS; no se aplica configuración.' }
    $proxy['enabled'] = $true
    foreach ($entry in @(@('/static', $StaticRoot), @('/media', $MediaRoot))) {
        $alias = $entry[0]
        $virtualDirectory = $application.VirtualDirectories[$alias]
        if ($null -eq $virtualDirectory) {
            $virtualDirectory = $application.VirtualDirectories.Add($alias, $entry[1])
        } else { $virtualDirectory.PhysicalPath = $entry[1] }
        # Uploaded files must only be served by StaticFileModule, never executed.
        $location = $SiteName + $alias
        $handlers = $config.GetSection('system.webServer/handlers', $location).GetCollection()
        $handlers.Clear()
        $handler = $handlers.CreateElement('add')
        $handler['name'] = 'NovaDeskStaticFile'
        $handler['path'] = '*'
        $handler['verb'] = 'GET,HEAD'
        $handler['modules'] = 'StaticFileModule'
        $handler['resourceType'] = 'File'
        $handler['requireAccess'] = 'Read'
        $handlers.Add($handler)
        $config.GetSection('system.webServer/directoryBrowse', $location)['enabled'] = $false
    }
    $rules = $rewrite.GetCollection()
    $rules.Clear()
    $staticRule = $rules.CreateElement('rule')
    $staticRule['name'] = 'NovaDesk static and media'
    $staticRule['stopProcessing'] = $true
    $staticRule.GetChildElement('match')['url'] = '^(static|media)(/|$)'
    $staticRule.GetChildElement('match')['ignoreCase'] = $true
    $staticRule.GetChildElement('action')['type'] = 'None'
    $rules.Add($staticRule)
    $proxyRule = $rules.CreateElement('rule')
    $proxyRule['name'] = 'NovaDesk Django'
    $proxyRule['stopProcessing'] = $true
    $proxyRule.GetChildElement('match')['url'] = '(.*)'
    $action = $proxyRule.GetChildElement('action')
    $action['type'] = 'Rewrite'
    $action['url'] = "$BackendUrl/{R:1}"
    $action['appendQueryString'] = $true
    $rules.Add($proxyRule)
    $manager.CommitChanges()
    Write-Output "Configuración aplicada. Respaldo IIS: $backupName"
} finally { $manager.Dispose() }
