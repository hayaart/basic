# =========================================================
#  삼성 결혼도움방 "잔여 웨딩홀" 빈자리 알림 (윈도우 전용, 설치 불필요)
#
#   check  = 20분마다 자동 확인 + 빈자리 생기면 텔레그램 알림
#   bot    = 텔레그램 "상태"/버튼으로 각 예식장 즉시 조회
#
#  아래 '===== 설정 =====' 부분만 보면 됩니다.
#  ⚠️ 이 파일은 UTF-8 (BOM 포함) 으로 저장해야 한글이 깨지지 않습니다.
# =========================================================

# ===== 설정 =====
# 봇 토큰은 이 파일에 적지 말고 아래 파일에 두는 것을 권합니다 (실수로 공유되는 것을 막기 위해).
#   %LOCALAPPDATA%\wedding-bot.json   →  {"token":"123:ABC","chatId":"8742943902"}
# 그 파일이 없으면 여기 값을 씁니다.
$BotToken = "PUT-YOUR-BOT-TOKEN-HERE"
$ChatId   = "PUT-YOUR-CHAT-ID-HERE"

$HallCode = "5"                 # 자동 감시: 1=서초사옥, 3=삼성E&A, 5=삼성금융연수원
$HallName = "삼성금융연수원"
$Months   = @("2027-05","2027-06","2027-07","2027-08","2027-09","2027-10")
$Halls    = @(
  @{ code="1"; name="서초사옥" },
  @{ code="3"; name="삼성E&A" },
  @{ code="5"; name="삼성금융연수원" }
)
$IntervalMinutes = 20
# ================

$PageUrl   = "https://s-wedding.samsungcard.com/internal/add-apply/UWDDWSWH04M1.jsp"
$SvcUrl    = "https://s-wedding.samsungcard.com/service/SWDDWSWSWHS03"
$UA        = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
$StateFile = Join-Path $env:LOCALAPPDATA "wedding-slot-state.json"
$SecretFile= Join-Path $env:LOCALAPPDATA "wedding-bot.json"
$CheckTask = "WeddingSlotCheck"
$BotTask   = "WeddingSlotBot"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# 토큰을 바깥 파일에 뒀다면 그것을 쓴다.
if (Test-Path $SecretFile) {
  try {
    $sec = Get-Content $SecretFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($sec.token)  { $BotToken = [string]$sec.token }
    if ($sec.chatId) { $ChatId   = [string]$sec.chatId }
  } catch { Write-Host "wedding-bot.json 을 읽지 못했습니다. 스크립트 안의 값을 씁니다." }
}
$Api = "https://api.telegram.org/bot$BotToken"

# ───────── 텔레그램 ─────────

function Keyboard {
  $row = @()
  foreach ($h in $Halls) { $row += @{ text=$h.name; callback_data=("hall:"+$h.code) } }
  return @{ inline_keyboard = @(, $row) }
}

function Send-Telegram([string]$text, $withButtons=$false) {
  if ($BotToken -like "PUT-YOUR-*") { Write-Host "봇 토큰이 설정되지 않았습니다."; return }
  $p = @{ chat_id=$ChatId; text=$text; disable_web_page_preview=$true }
  if ($withButtons) { $p.reply_markup = (Keyboard) }
  $bytes = [Text.Encoding]::UTF8.GetBytes(($p | ConvertTo-Json -Depth 8 -Compress))
  try {
    Invoke-RestMethod -Uri "$Api/sendMessage" -Method Post `
      -ContentType "application/json; charset=utf-8" -Body $bytes -TimeoutSec 35 | Out-Null
  } catch { Write-Host ("텔레그램 전송 실패: " + $_.Exception.Message) }
}

# ───────── 사이트 조회 ─────────

function Valid-Date([int]$y, [int]$m, [int]$d) {
  if ($d -lt 1 -or $d -gt 31) { return $false }
  try { [void][datetime]::new($y, $m, $d); return $true } catch { return $false }
}

function Weekday($ymd) {
  @("일","월","화","수","목","금","토")[[int]([datetime]::ParseExact($ymd,"yyyy-MM-dd",[cultureinfo]::InvariantCulture)).DayOfWeek]
}

function Fetch-Hall($code) {
  # 세션 객체를 미리 만든다. 달력 페이지 열기가 실패해도 아래 조회가 멈추지 않게.
  # (-SessionVariable 로 받으면 실패 시 $null 이 되어 -WebSession 바인딩부터 터진다)
  $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
  $session.UserAgent = $UA
  try {
    Invoke-WebRequest -Uri $PageUrl -UseBasicParsing -UserAgent $UA `
      -WebSession $session -TimeoutSec 20 | Out-Null
  } catch { }

  $open = New-Object System.Collections.Generic.List[string]
  $okMonths = @()
  $failed = @()
  $totalDays = 0

  foreach ($ym in $Months) {
    $y = [int]$ym.Substring(0,4); $mm = [int]$ym.Substring(5,2)
    $now = Get-Date
    $sn = $now.ToString("HHmmss") + ("{0:D3}" -f $now.Millisecond) + ("{0:D5}" -f (Get-Random -Max 100000))
    $common = @{ dlngEvnDvC="S"; scrnId="UWDDWSWH04M1"; stdEtxtCrtDt=$now.ToString("yyyyMMdd");
                 stdEtxtCrtSysNm="P0000000"; stdEtxtSn=$sn; stdEtxtPrgDvNo=0; stdEtxtPrgNo=0;
                 indvInfIncYn="N"; usid=" " }
    $payload = @{ wedgHllC=$code; wedgEtblfmPsbY=$ym.Substring(0,4);
                  wedgEtblfmPsbMm=$ym.Substring(5,2); wedgAplcBooStc="4"; common=$common } |
               ConvertTo-Json -Depth 5 -Compress
    $headers = @{ "X-Requested-With"="XMLHttpRequest"; "Referer"=$PageUrl;
                  "Accept"="application/json, text/javascript, */*; q=0.01";
                  "Accept-Language"="ko-KR,ko;q=0.9" }
    try {
      $resp = Invoke-WebRequest -Uri $SvcUrl -Method Post -UseBasicParsing -UserAgent $UA `
        -WebSession $session -Headers $headers -ContentType "application/json; charset=UTF-8" `
        -Body ([Text.Encoding]::UTF8.GetBytes($payload)) -TimeoutSec 20
      $j = $resp.Content | ConvertFrom-Json
      $rs = [Net.WebUtility]::HtmlDecode([string]$j.rs).Replace('"true"','true').Replace('"false"','false')
      $days = ($rs | ConvertFrom-Json).days
      if ($days) {
        foreach ($p in $days.PSObject.Properties) {
          $d = 0
          if (-not [int]::TryParse($p.Name, [ref]$d)) { continue }
          if (-not (Valid-Date $y $mm $d)) { continue }
          $totalDays++
          if ($p.Value.closed -ne $true) { $open.Add(("{0}-{1:D2}" -f $ym, $d)) }
        }
      }
      $okMonths += $ym
    } catch {
      $failed += $ym
    }
    Start-Sleep -Milliseconds 900
  }

  return @{ open=@($open.ToArray() | Sort-Object -Unique); okMonths=@($okMonths);
            failed=@($failed); totalDays=$totalDays }
}

function Group-ByMonth($dates) {
  $m = [ordered]@{}
  foreach ($d in $dates) {
    $k = $d.Substring(0,7)
    if (-not $m.Contains($k)) { $m[$k] = @() }
    $m[$k] += ("{0}({1})" -f [int]$d.Substring(8,2), (Weekday $d))
  }
  $out = foreach ($k in $m.Keys) {
    ("{0}년 {1}월: " -f [int]$k.Substring(0,4), [int]$k.Substring(5,2)) + ($m[$k] -join ", ")
  }
  return ($out -join "`n")
}

# 조회된 날의 대부분이 열림으로 보이면 응답 형식이 바뀐 것일 수 있다.
# 그렇다고 입을 다물면 진짜 기회를 놓치므로, 알리되 제목을 달리한다.
function Looks-Suspicious($r) {
  return ($r.totalDays -gt 0 -and $r.open.Count -ge 8 -and $r.open.Count -gt ($r.totalDays * 0.8))
}

# ───────── 상태 파일 ─────────

function Load-State {
  if (Test-Path $StateFile) {
    try { return (Get-Content $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { }
  }
  return $null
}

function Save-State($open, $blockedAt) {
  (@{ open=@($open); blockedNotifiedAt=$blockedAt; at=(Get-Date).ToString("o") } |
    ConvertTo-Json -Depth 5 -Compress) | Set-Content -Path $StateFile -Encoding UTF8
}

# ───────── 20분마다 하는 일 ─────────

function Do-Check {
  Start-Sleep -Seconds (Get-Random -Max 10)
  $st = Load-State
  $prev = @(); if ($st -and $st.open) { $prev = @($st.open) | Where-Object { $_ } }
  $r = Fetch-Hall $HallCode

  # 전부 실패: 상태를 건드리지 않는다. 여기서 비우면 다음에 성공했을 때 전부 '새 빈자리'가 된다.
  if ($r.okMonths.Count -eq 0) {
    $last = if ($st) { $st.blockedNotifiedAt } else { $null }
    $should = $true
    if ($last) { if (((Get-Date) - [datetime]$last).TotalHours -lt 6) { $should = $false } }
    if ($should) { Send-Telegram "⚠️ 빈자리 지킴이: 사이트 접근이 막혔어요(차단 의심). 확인이 안 되고 있어요." }
    $blockedAt = if ($should) { (Get-Date).ToString("o") } else { $last }
    Save-State $prev $blockedAt
    return
  }

  # 이번에 확인하지 못한 달은 이전 기록을 이어받는다.
  # 그러지 않으면 그 달의 날짜들이 기록에서 사라져, 다음 회차에 전부 '새 빈자리'로 다시 알림이 간다.
  $carried = @($prev | Where-Object { $r.okMonths -notcontains $_.Substring(0,7) })
  $openNow = @((@($r.open) + @($carried)) | Sort-Object -Unique)

  $set = @{}; foreach ($x in $prev) { $set[$x] = $true }
  $newly = @($openNow | Where-Object { -not $set.ContainsKey($_) })

  if ($newly.Count -gt 0) {
    if (Looks-Suspicious $r) {
      Send-Telegram ("⚠️ 확인 필요 — $HallName " + $newly.Count + "건`n" +
        "조회된 날이 거의 전부 열림으로 나옵니다. 사이트 응답이 바뀐 것일 수 있으니 직접 확인해 보세요.`n`n" +
        (Group-ByMonth $newly) + "`n`n" + $PageUrl)
    } else {
      Send-Telegram ("🎉 $HallName 빈자리 " + $newly.Count + "건!`n" +
        (Group-ByMonth $newly) + "`n`n지금 신청: " + $PageUrl)
    }
  }
  Save-State $openNow $null
}

# ───────── 텔레그램 대화 ─────────

function Hall-Report($code, $name) {
  $r = Fetch-Hall $code
  if ($r.okMonths.Count -eq 0) {
    return "❌ $name — 확인 실패(차단 의심). 집에서 브라우저로 열리는지 확인해 보세요."
  }
  $note = if ($r.failed.Count) { "`n(" + $r.failed.Count + "개 달은 확인 못 했습니다)" } else { "" }
  if ($r.open.Count -eq 0) { return "🔍 $name — 지금 빈자리 없음 (전부 마감)" + $note }
  return "🎉 $name — 빈자리 " + $r.open.Count + "건" + $note + "`n" +
         (Group-ByMonth $r.open) + "`n`n" + $PageUrl
}

function Status-Text {
  $on = $false
  try { $on = ((Get-ScheduledTask -TaskName $CheckTask -ErrorAction Stop).State -ne "Disabled") } catch { }
  $s = if ($on) { "🟢 켜짐" } else { "🔴 꺼짐" }
  $st = Load-State
  $when = if ($st -and $st.at) { ([datetime]$st.at).ToString("M월 d일 HH:mm") } else { "아직 없음" }
  $cnt  = if ($st -and $st.open) { @($st.open).Count } else { 0 }
  return "자동 감시($HallName, $IntervalMinutes분마다): $s`n" +
         "마지막 확인: $when`n" +
         "기억 중인 빈자리: $cnt건`n`n" +
         "아래 버튼으로 각 예식장을 지금 바로 조회할 수 있어요."
}

function Match-Hall([string]$text) {
  $t = $text.ToLower()
  if ($t -match "서초")                 { return $Halls[0] }
  if ($t -match "e&a|ena|이엔에이")      { return $Halls[1] }
  if ($t -match "금융|연수원")           { return $Halls[2] }
  return $null
}

function Run-Bot {
  # 예전에 걸어둔 웹훅이 남아 있으면 getUpdates 를 쓸 수 없다.
  try { Invoke-RestMethod -Uri "$Api/deleteWebhook?drop_pending_updates=true" -TimeoutSec 20 | Out-Null } catch { }
  $offset = 0
  try {
    $a = @((Invoke-RestMethod -Uri "$Api/getUpdates?timeout=0" -TimeoutSec 20).result)
    if ($a.Count) { $offset = $a[-1].update_id + 1 }
  } catch { }
  Write-Host "대화봇 실행 중… (이 창을 닫으면 멈춰요) 텔레그램에서 '상태' 를 보내보세요."

  while ($true) {
    try {
      $u = Invoke-RestMethod -Uri "$Api/getUpdates?timeout=25&offset=$offset" -TimeoutSec 35
      foreach ($upd in @($u.result)) {
        $offset = $upd.update_id + 1

        if ($upd.callback_query) {
          $cb = $upd.callback_query
          try {
            $cbb = [Text.Encoding]::UTF8.GetBytes((@{ callback_query_id=$cb.id } | ConvertTo-Json -Compress))
            Invoke-RestMethod -Uri "$Api/answerCallbackQuery" -Method Post `
              -ContentType "application/json; charset=utf-8" -Body $cbb -TimeoutSec 20 | Out-Null
          } catch { }
          if ([string]$cb.message.chat.id -ne $ChatId) { continue }
          if ([string]$cb.data -like "hall:*") {
            $code = ([string]$cb.data).Split(":")[1]
            $name = ($Halls | Where-Object { $_.code -eq $code } | Select-Object -First 1).name
            Send-Telegram "🔎 $name 조회 중… 10초쯤 걸려요"
            Send-Telegram (Hall-Report $code $name) $true
          }
        }
        elseif ($upd.message -and $upd.message.text) {
          if ([string]$upd.message.chat.id -ne $ChatId) { continue }
          # 버튼을 누르는 것과 이름을 적어 보내는 것이 같게 동작하도록.
          $hall = Match-Hall ([string]$upd.message.text)
          if ($hall) {
            Send-Telegram ("🔎 " + $hall.name + " 조회 중… 10초쯤 걸려요")
            Send-Telegram (Hall-Report $hall.code $hall.name) $true
          } else {
            Send-Telegram (Status-Text) $true
          }
        }
      }
    } catch { Start-Sleep -Seconds 5 }
  }
}

# ───────── 설치 / 해제 ─────────

function Install-All {
  $self = $PSCommandPath
  $aCheck = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$self`" check"
  # RepetitionDuration 을 주지 않으면 반복이 하루 만에 끝나는 윈도우가 있다. 넉넉히 잡아 둔다.
  $tCheck = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
  $sCheck = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName $CheckTask -Action $aCheck -Trigger $tCheck -Settings $sCheck -Force | Out-Null

  $aBot = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$self`" bot"
  $tBot = New-ScheduledTaskTrigger -AtLogOn
  $sBot = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName $BotTask -Action $aBot -Trigger $tBot -Settings $sBot -Force | Out-Null
  Start-ScheduledTask -TaskName $BotTask

  Send-Telegram "✅ 설치 완료 — $IntervalMinutes분마다 $HallName 자동 확인 + '상태'/버튼 조회 켜졌어요."
  Write-Host "설치 완료: $IntervalMinutes분 자동 확인 + 대화봇 둘 다 켰습니다."
}

function Uninstall-All {
  foreach ($t in @($CheckTask, $BotTask)) {
    try { Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue } catch { }
    try { Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction Stop; Write-Host "$t 제거" } catch { }
  }
  Write-Host "전체 해제 완료."
}

function Run-Test {
  Send-Telegram "🔔 테스트 — 빈자리 지킴이. 이 메시지가 오면 연결 성공!"
  $r = Fetch-Hall $HallCode
  Write-Host ("결과 → 확인한 달={0} 실패={1} 조회된 날={2} 빈자리={3}" -f `
    $r.okMonths.Count, $r.failed.Count, $r.totalDays, (($r.open) -join ", "))
  if ($r.okMonths.Count -eq 0) {
    Write-Host "⚠️ 전부 실패했습니다. 브라우저로 사이트가 열리는지 확인해 보세요."
  } elseif (Looks-Suspicious $r) {
    Write-Host "⚠️ 조회된 날이 거의 전부 열림으로 나옵니다. 응답 형식이 바뀌었을 수 있습니다."
  }
}

$mode = if ($args.Count -ge 1) { [string]$args[0] } else { "check" }
switch ($mode) {
  "bot"       { Run-Bot }
  "install"   { Install-All }
  "uninstall" { Uninstall-All }
  "test"      { Run-Test }
  default     { Do-Check }
}
