$ErrorActionPreference = "Stop"
# ⚠️ 安全提示：原文件曾硬编码明文 GitHub Personal Access Token (gho_LWig...)。
# 该 token 已暴露，请立即在 GitHub → Settings → Developer settings → Personal access tokens 吊销。
# 后续推送请使用 git push（HTTPS + credential manager 或 SSH key），不要再用此脚本。
# 如需恢复使用，请通过环境变量传入 token：
#   $token = $env:GITHUB_TOKEN
#   if (-not $token) { throw "请设置 GITHUB_TOKEN 环境变量" }
$token = $env:GITHUB_TOKEN
if (-not $token) {
    Write-Error "此脚本已弃用。请使用 'git push origin main' 推送。如需恢复，请设置 GITHUB_TOKEN 环境变量。"
    exit 1
}
$headers = @{Authorization="Bearer $token"; Accept="application/vnd.github+json"}
$repo = "JamesTanyi/CardioAI"
$gitRoot = "e:\桌面\心血管健康监测APP"

$branch = Invoke-RestMethod "https://api.github.com/repos/$repo/git/refs/heads/main" -Headers $headers
$baseSha = $branch.object.sha
Write-Host "Remote HEAD: $baseSha"

$baseCommit = Invoke-RestMethod "https://api.github.com/repos/$repo/git/commits/$baseSha" -Headers $headers
$baseTree = $baseCommit.tree.sha
Write-Host "Base tree: $baseTree"

# Only Dockerfile changed
$file = "Dockerfile"
$bytes = [IO.File]::ReadAllBytes((Join-Path $gitRoot $file))
$b64 = [Convert]::ToBase64String($bytes)
$treeItem = @{path=$file; mode="100644"; type="blob"; content=$b64}

$treeJson = @{base_tree=$baseTree; tree=@($treeItem)} | ConvertTo-Json -Depth 4 -Compress
Write-Host "Tree JSON: $($treeJson.Length) bytes"

$newTree = Invoke-RestMethod "https://api.github.com/repos/$repo/git/trees" -Method Post -Headers $headers -Body $treeJson -ContentType "application/json"
Write-Host "Tree: $($newTree.sha)"

$commitJson = @{
    message = "修复: 精简Dockerfile，移除apt-get编译依赖"
    tree = $newTree.sha
    parents = @($baseSha)
} | ConvertTo-Json

$newCommit = Invoke-RestMethod "https://api.github.com/repos/$repo/git/commits" -Method Post -Headers $headers -Body $commitJson -ContentType "application/json"
Write-Host "Commit: $($newCommit.sha)"

$refJson = @{sha=$newCommit.sha; force=$false} | ConvertTo-Json
Invoke-RestMethod "https://api.github.com/repos/$repo/git/refs/heads/main" -Method Patch -Headers $headers -Body $refJson -ContentType "application/json"
Write-Host "DONE"
