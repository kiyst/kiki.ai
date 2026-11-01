param([string]$Model, [int]$N = 40, [int]$Ctx = 4096)
function Commit { $p = Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue; [math]::Round((($p | Measure-Object PagedMemorySize64 -Sum).Sum)/1MB) }
function Free { [math]::Round((Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory/1MB,1) }
Invoke-RestMethod -Uri http://127.0.0.1:11434/api/generate -Method Post -Body (@{model=$Model;keep_alive=0}|ConvertTo-Json) | Out-Null
Start-Sleep 3
$topics = 'sorting','a linked list','binary search','a stack','a queue','fibonacci','a palindrome check','prime numbers','a word counter','matrix addition'
$marks = @()
foreach ($i in 1..$N) {
  $prompt = "Request $i of $N. Write a short Python function about $($topics[$i % $topics.Count]) and name it task_$i."
  $body = @{model=$Model;stream=$false;think=$false;messages=@(@{role='user';content=$prompt});options=@{num_ctx=$Ctx;num_predict=150;temperature=0}} | ConvertTo-Json -Depth 5
  Invoke-RestMethod -Uri http://127.0.0.1:11434/api/chat -Method Post -Body $body -ContentType 'application/json' | Out-Null
  if ($i -in 1,10,20,30,40) { $marks += "after $i`: $(Commit) MB (system free commit $(Free) GB)" }
}
"$Model, $N different requests:"; $marks | ForEach-Object { "   $_" }
Invoke-RestMethod -Uri http://127.0.0.1:11434/api/generate -Method Post -Body (@{model=$Model;keep_alive=0}|ConvertTo-Json) | Out-Null
