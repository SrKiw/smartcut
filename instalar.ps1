# SmartCut - instalador para Windows 10/11
# Lo ejecuta INSTALAR.bat. Se puede correr varias veces: lo que ya esta instalado lo salta.

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
Set-Location -Path $PSScriptRoot
$Log = Join-Path $PSScriptRoot "instalacion.log"
"SmartCut - instalacion $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Set-Content -Path $Log -Encoding UTF8
$Host.UI.RawUI.WindowTitle = "Instalando SmartCut"

function Anotar($t) { Add-Content -Path $Log -Value $t -Encoding UTF8 }
function Paso($t)  { Write-Host ""; Write-Host "==> $t" -ForegroundColor Yellow; Anotar "==> $t" }
function Bien($t)  { Write-Host "    $t" -ForegroundColor Green; Anotar "    OK $t" }
function Aviso($t) { Write-Host "    $t" -ForegroundColor DarkYellow; Anotar "    AVISO $t" }
function Mal($t)   { Write-Host "    $t" -ForegroundColor Red; Anotar "    ERROR $t" }
function Correr($exe, [string[]]$argumentos) {
    # muestra la salida en pantalla y la guarda en el log
    & $exe @argumentos 2>&1 | ForEach-Object { $l = "$_"; Write-Host $l; Add-Content -Path $Log -Value $l -Encoding UTF8 }
    return $LASTEXITCODE
}

function Refrescar-Path {
    $m = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u;$env:LOCALAPPDATA\Microsoft\WinGet\Links"
}

function Existe($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Instalar-Winget($id, $nombre) {
    Write-Host "    Instalando $nombre con winget (puede pedir permiso)..."
    $extra = @()
    if ($id -like "Python.*") {
        # solo para este usuario, sin pedir permisos de administrador (ni el lanzador "py" para todos)
        $extra = @("--scope", "user", "--override", "/quiet InstallAllUsers=0 InstallLauncherAllUsers=0 PrependPath=1 Include_test=0")
    }
    $null = Correr "winget" (@("install", "-e", "--id", $id, "--accept-source-agreements", "--accept-package-agreements", "--silent") + $extra)
    Refrescar-Path
}

function Buscar-Python311 {
    try {
        $p = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() }
    } catch {}
    $candidatos = @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    foreach ($c in $candidatos) { if (Test-Path $c) { return $c } }
    return $null
}

Write-Host ""
Write-Host "  SmartCut - instalador" -ForegroundColor Red
Write-Host "  Carpeta: $PSScriptRoot"
if ($PSScriptRoot -match "OneDrive") {
    Aviso "Esta carpeta esta dentro de OneDrive. Funciona, pero es mejor moverla a C:\SmartCut (los videos pesan)."
}

# ---------------------------------------------------------------- winget
Paso "Revisando winget"
if (-not (Existe "winget")) {
    Mal "No encuentro winget. Abre Microsoft Store, busca 'Instalador de aplicacion' (App Installer), actualizalo y vuelve a correr INSTALAR.bat"
    Anotar "FIN CON ERROR"; exit 1
}
Bien "winget OK"

# ---------------------------------------------------------------- Python 3.11
Paso "Python 3.11"
$py = Buscar-Python311
if (-not $py) {
    Instalar-Winget "Python.Python.3.11" "Python 3.11"
    $py = Buscar-Python311
}
if (-not $py) { Mal "No pude instalar Python 3.11. Instalalo desde python.org (marca 'Add to PATH') y repite."; Anotar "FIN CON ERROR"; exit 1 }
Bien $py

# ---------------------------------------------------------------- FFmpeg
Paso "FFmpeg (cortar y exportar video)"
Refrescar-Path
if (-not (Existe "ffmpeg")) { Instalar-Winget "Gyan.FFmpeg" "FFmpeg" }
if (Existe "ffmpeg") { Bien "FFmpeg OK" } else { Mal "FFmpeg no quedo en el PATH. Cierra esta ventana, abre otra y corre INSTALAR.bat de nuevo." }

# ---------------------------------------------------------------- Deno (lo pide yt-dlp para YouTube)
Paso "Deno (lo necesita yt-dlp para bajar de YouTube)"
if (-not (Existe "deno")) { Instalar-Winget "DenoLand.Deno" "Deno" }
if (Existe "deno") { Bien "Deno OK" } else { Aviso "Deno no quedo instalado; los links de YouTube podrian fallar (los archivos locales funcionan igual)." }

# ---------------------------------------------------------------- entorno Python
Paso "Creando el entorno de Python (.venv)"
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    & $py -m venv .venv
}
if (-not (Test-Path $venvPy)) { Mal "No se pudo crear .venv"; Anotar "FIN CON ERROR"; exit 1 }
Bien "OK"

Paso "Instalando librerias (5-10 minutos la primera vez)"
$null = Correr $venvPy @("-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check", "-q")
$rc = Correr $venvPy @("-m", "pip", "install", "-r", "requirements.txt", "--disable-pip-version-check", "--progress-bar", "off")
if ($rc -ne 0) { Mal "Fallo la instalacion de librerias. Revisa tu internet y corre INSTALAR.bat otra vez."; Anotar "FIN CON ERROR"; exit 1 }
Bien "Librerias OK"

# ---------------------------------------------------------------- GPU NVIDIA
Paso "Tarjeta de video"
$tieneNvidia = $false
if (Existe "nvidia-smi") {
    $gpu = (& nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
    if ($gpu) { $tieneNvidia = $true; Bien "NVIDIA detectada: $gpu" }
}
if ($tieneNvidia) {
    Write-Host "    Bajando cuBLAS y cuDNN para transcribir con la GPU (~1.2 GB)..."
    $rc = Correr $venvPy @("-m", "pip", "install", "-r", "requirements-gpu.txt", "--disable-pip-version-check", "--progress-bar", "off")
    if ($rc -eq 0) { Bien "Librerias de GPU OK" } else { Aviso "No se pudieron instalar; transcribira con el procesador (mas lento)." }
} else {
    Aviso "No veo tarjeta NVIDIA: transcribira con el procesador (funciona, pero mas lento)."
}

# ---------------------------------------------------------------- API key
Paso "API key de Claude"
$envFile = Join-Path $PSScriptRoot ".env"
if ((Test-Path $envFile) -and ((Get-Content $envFile -Raw) -match "ANTHROPIC_API_KEY=sk-")) {
    Bien "Ya hay una key guardada"
} else {
    Aviso "Sin key por ahora (opcional). Ponla en la app > Configuracion. Sin ella elige clips por risas y ritmo."
}

# ---------------------------------------------------------------- prueba + modelo
Paso "Probando todo y bajando el modelo de transcripcion (~1.6 GB, solo la primera vez)"
$null = Correr $venvPy @("miopusclip.py", "diagnostico", "--probar-gpu")

# ---------------------------------------------------------------- acceso directo
Paso "Acceso directo en el escritorio"
try {
    $escritorio = [Environment]::GetFolderPath("Desktop")
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path $escritorio "SmartCut.lnk"))
    $lnk.TargetPath = Join-Path $PSScriptRoot "ABRIR SmartCut.bat"
    $lnk.WorkingDirectory = $PSScriptRoot
    $lnk.IconLocation = "$env:SystemRoot\System32\imageres.dll,18"
    $lnk.Save()
    Bien "Creado: SmartCut en el escritorio"
} catch { Aviso "No se pudo crear el acceso directo (no pasa nada)." }

Write-Host ""
Write-Host "  Listo. Abre 'SmartCut' en el escritorio o 'ABRIR SmartCut.bat'." -ForegroundColor Green
Anotar "FIN $(Get-Date -Format 'HH:mm:ss')"
Write-Host ""
