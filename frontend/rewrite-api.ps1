$root = Join-Path (Get-Location) "src"
if(!(Test-Path $root)){ throw "Can't find src folder at $root. Run this from frontend root." }

$files = Get-ChildItem -Path $root -Recurse -File -Include *.js,*.jsx

$repls = @(
  @{ name="fetch dq";   pat='fetch\("\/api';          rep='fetch((process.env.REACT_APP_API_BASE || "") + "/api' },
  @{ name="fetch sq";   pat="fetch\('\/api";          rep='fetch((process.env.REACT_APP_API_BASE || "") + "/api' },
  @{ name="axios.get";  pat='axios\.get\("\/api';     rep='axios.get((process.env.REACT_APP_API_BASE || "") + "/api' },
  @{ name="axios.post"; pat='axios\.post\("\/api';    rep='axios.post((process.env.REACT_APP_API_BASE || "") + "/api' },
  @{ name="axios.put";  pat='axios\.put\("\/api';     rep='axios.put((process.env.REACT_APP_API_BASE || "") + "/api' },
  @{ name="axios.del";  pat='axios\.delete\("\/api';  rep='axios.delete((process.env.REACT_APP_API_BASE || "") + "/api' }
)

$changed = 0
foreach($f in $files){
  $c = Get-Content $f.FullName -Raw
  $n = $c
  foreach($r in $repls){
    $n = [regex]::Replace($n, $r.pat, $r.rep)
  }
  if($n -ne $c){
    Set-Content -Path $f.FullName -Value $n -Encoding UTF8 -NoNewline
    $changed++
    Write-Host "updated:" $f.FullName
  }
}

Write-Host "`nDONE. Files changed:" $changed
