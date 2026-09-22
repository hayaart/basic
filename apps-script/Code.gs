/*************************************************************
 *  삼성카드 결혼도움방 웨딩홀 "빈자리(취소 자리)" 알림 — Google Apps Script
 *
 *  설정은 코드가 아니라 [프로젝트 설정 > 스크립트 속성]에서 합니다.
 *  (README.md 참고)
 *
 *    EMAIL_TO          이메일 받을 주소. 비워두면 내 구글 계정으로 옵니다.
 *    TELEGRAM_TOKEN    알림 봇 토큰          ─┐ 즉시 푸시를 원하면
 *    TELEGRAM_CHAT_ID  알림 봇 채팅 ID       ─┘ 둘 다 넣으세요
 *
 *    STATUS_TELEGRAM_TOKEN     상태 봇 토큰    ─┐ 살아있음 표시를 따로 받고
 *    STATUS_TELEGRAM_CHAT_ID   상태 봇 채팅 ID ─┘ 싶으면 (선택)
 *    NTFY_TOPIC        ntfy 토픽 이름 (선택)
 *    WEBAPP_URL        텔레그램에서 말을 걸면 답하게 하려면 (README 참고)
 *
 *    HALL_CODE         감시할 예식장 코드. 1 서초사옥 · 3 삼성E&A · 5 삼성금융연수원.
 *                      목록에 없으면 findHallCodes 를 실행해 찾으세요.
 *    HALL_NAME         알림에 쓸 이름
 *    MONTHS            노리는 월. 쉼표로 구분: 2027-05, 2027-06
 *                      비워두면 예약을 받는 달을 스스로 찾아 전부 감시합니다.
 *    MAX_MONTHS_AHEAD  자동 탐색 시 몇 달 앞까지 볼지. 기본 24
 *
 *  알림은 [텔레그램 → ntfy → 이메일] 순으로 시도하고, 하나라도 성공하면 멈춥니다.
 *  이메일은 설정이 없어도 항상 마지막 보루로 동작합니다.
 *************************************************************/

// 아래는 기본값이고, 스크립트 속성에 같은 이름을 넣으면 그쪽이 우선합니다.
var HALL_CODE = prop_('HALL_CODE') || '5';    // 1 서초사옥 · 3 삼성E&A · 5 삼성금융연수원
var HALL_NAME = prop_('HALL_NAME') || '삼성금융연수원';

// 텔레그램에서 이름을 부르면 그때만 조회해 주는 예식장들. (자동 감시는 위의 한 곳만)
var HALLS = [
  { code: '1', name: '서초사옥',      keys: ['서초'] },
  { code: '3', name: '삼성E&A',       keys: ['e&a', 'ena', '이엔에이', '삼성e'] },
  { code: '5', name: '삼성금융연수원', keys: ['금융', '연수원'] }
];
// 월을 지정하지 않으면(기본) 예약을 받는 달을 스스로 찾아 전부 감시한다.
var FIXED_MONTHS = parseMonths_(prop_('MONTHS'));
var MAX_MONTHS_AHEAD = Number(prop_('MAX_MONTHS_AHEAD')) || 24;

/*************************************************************
 *  ▲▲▲ 여기 위쪽만 신경 쓰면 됩니다. 아래는 안 건드려도 돼요 ▲▲▲
 *************************************************************/

var PAGE_URL  = 'https://s-wedding.samsungcard.com/internal/add-apply/UWDDWSWH04M1.jsp';
var SVC_URL   = 'https://s-wedding.samsungcard.com/service/SWDDWSWSWHS03';

var FAIL_ALERT_AFTER = 3;      // 전체 조회가 이만큼 연속 실패하면 '점검 필요' 알림 (3회 = 약 30분)
var PARTIAL_ALERT_AFTER = 12;  // 일부 달만 계속 못 볼 때의 기준 (12회 = 약 2시간)
var HEARTBEAT_HOURS  = 24;     // 이 시간마다 '살아있음' 알림. 0 으로 두면 끕니다.
var MAX_LINES = 30;            // 알림 한 통에 적는 최대 날짜 수
var JITTER_MS = 90 * 1000;     // 매 실행을 0~90초 무작위로 늦춰 규칙적인 패턴을 피한다
var GAP_MS    = 1200;          // 달과 달 사이 간격

// 조회된 날짜의 대부분이 '열림'으로 보이면 파싱이 깨졌을 수 있다. 판단 기준.
var SUSPICIOUS_MIN_DAYS  = 8;
var SUSPICIOUS_RATIO     = 0.8;

// 자동 탐색: 예약을 아예 안 받는 달이 이만큼 연달아 나오면 거기가 끝이라고 본다.
var STOP_AFTER_EMPTY = 3;

// ───────────────────────────────────────────────────────────
//  트리거에서 10분마다 자동 실행되는 함수
// ───────────────────────────────────────────────────────────
function checkOpenings() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) {
    console.log('이전 실행이 아직 돌고 있어 이번 회차는 건너뜁니다.');
    return;
  }
  try {
    Utilities.sleep(Math.floor(Math.random() * JITTER_MS));
    runCheck_();
  } finally {
    lock.releaseLock();
  }
}

function runCheck_() {
  var props = PropertiesService.getScriptProperties();
  forgetIfHallChanged_(props);
  var prev = readOpenSet_(props);
  var prevSet = toSet_(prev);

  var scan = scanMonths_();

  // 한 달도 확인하지 못했다면 상태를 건드리지 않는다.
  // (여기서 openSet 을 비우면 다음에 성공했을 때 전부 '새 빈자리'로 다시 알림이 간다.)
  if (scan.fatal || (scan.checked && scan.failed.length === scan.checked)) {
    console.warn('전체 조회 실패: ' + scan.errors.join(' | '));
    recordFailure_(props, scan.errors.join(' | '));
    updateStatusMessage_(props, scan, prev);
    return;
  }

  // 이번에 확인하지 못한 달은 이전 상태를 이어받는다 → 일시적 실패가 중복 알림으로 번지지 않게.
  // 이미 지나간 달은 그대로 버린다.
  var thisMonth = currentMonth_();
  var carried = prev.filter(function (d) {
    var ym = d.slice(0, 7);
    return !scan.ok[ym] && ym >= thisMonth;
  });
  var openNow = dedupeSorted_(scan.open.concat(carried));

  var newly = openNow.filter(function (d) { return !prevSet[d]; });
  if (newly.length) {
    if (isSuspicious_(scan)) {
      // 응답 형식이 바뀐 것일 수 있다. 그렇다고 입을 다물면 진짜 기회를 놓치므로,
      // 알리되 제목을 다르게 해서 '직접 확인하라'고 말한다.
      notify_('⚠️ 확인 필요 — ' + HALL_NAME + ' ' + newly.length + '건',
              '조회된 날짜가 거의 전부 열림으로 나옵니다. 사이트 응답 형식이 바뀐 것일 수 있으니 ' +
              '진짜 빈자리인지 직접 확인해 보세요.\n\n' + buildSlotMessage_(newly), 'high');
    } else {
      notify_('🎉 ' + HALL_NAME + ' 빈자리 ' + newly.length + '건', buildSlotMessage_(newly), 'urgent');
    }
  }

  props.setProperty('openSet', JSON.stringify(openNow));

  if (scan.failed.length) {
    // 일부 달만 실패한 것은 감시가 멈춘 것과 다르다. 따로 세고, 오래 이어질 때만 알린다.
    recordPartial_(props, scan.failed, scan.errors);
  } else {
    recordSuccess_(props);
    maybeHeartbeat_(props, openNow.length);
  }

  updateStatusMessage_(props, scan, openNow);

  console.log('확인한 달 ' + scan.checked + '개 (' + Object.keys(scan.ok).join(', ') + ')' +
              ' / 현재 열린 날: ' + (openNow.length ? openNow.join(', ') : '없음') +
              ' / 새로 알린 날: ' + (newly.length ? newly.join(', ') : '없음') +
              (scan.failed.length ? ' / 조회 실패한 달: ' + scan.failed.join(', ') : ''));
}

/**
 * 대상 월을 모두 조회한다. 일부가 실패해도 나머지는 진행한다.
 *
 * MONTHS 를 지정했으면 그 달만 본다. 지정하지 않았으면 이번 달부터 앞으로 가면서,
 * 예약을 아예 안 받는 달이 연달아 나오는 지점을 예약 가능 구간의 끝으로 보고 멈춘다.
 */
function scanMonths_(hallCode) {
  var result = { open: [], total: 0, failed: [], errors: [], ok: {}, checked: 0, fatal: false };

  var cookie;
  try {
    cookie = getCookie_();
  } catch (e) {
    // 쿠키를 못 받으면 어느 달도 조회할 수 없다.
    result.fatal = true;
    result.errors.push(e.message);
    return result;
  }

  if (FIXED_MONTHS) {
    FIXED_MONTHS.forEach(function (ym, i) {
      if (i) Utilities.sleep(GAP_MS);
      checkMonth_(cookie, ym, result, hallCode);
    });
    return result;
  }

  var ym = currentMonth_();
  var empty = 0;
  for (var i = 0; i < MAX_MONTHS_AHEAD && empty < STOP_AFTER_EMPTY; i++) {
    if (i) Utilities.sleep(GAP_MS);
    var before = result.total;
    checkMonth_(cookie, ym, result, hallCode);
    if (!result.ok[ym]) {
      // 조회 실패는 '빈 달'이 아니다. 여기서 멈추면 뒤쪽 달을 통째로 놓친다.
    } else if (result.total === before) {
      empty++;
    } else {
      empty = 0;
    }
    ym = addMonths_(ym, 1);
  }
  return result;
}

/** 한 달을 조회해 결과에 합친다. */
function checkMonth_(cookie, ym, result, hallCode) {
  result.checked++;
  try {
    var month = fetchOpenDays_(cookie, ym, false, hallCode);
    result.open = result.open.concat(month.open);
    result.total += month.total;
    result.ok[ym] = true;
  } catch (e) {
    result.failed.push(ym);
    result.errors.push(ym + ': ' + e.message);
  }
}

/** 조회된 날짜의 대부분이 열림으로 보이는가? (파싱이 깨졌을 때의 신호) */
function isSuspicious_(scan) {
  return scan.open.length >= SUSPICIOUS_MIN_DAYS &&
         scan.open.length > scan.total * SUSPICIOUS_RATIO;
}

// ───────────────────────────────────────────────────────────
//  처음에 한 번 눌러 확인하는 함수
// ───────────────────────────────────────────────────────────
function sendTestPush() {
  var names = enabledChannels_().map(function (c) { return c.name; });
  console.log('설정된 알림 채널: ' + names.join(' → '));

  var ok = notify_('🔔 테스트', '테스트 알림입니다. 이 메시지가 도착하면 연결 성공! 🎉', 'high');
  console.log(ok ? '알림 전송 성공' : '모든 채널 전송 실패 — 위 로그를 확인하세요.');

  var cookie;
  try {
    cookie = getCookie_();
    console.log('세션 쿠키 발급 성공');
  } catch (e) {
    console.log('세션 쿠키 발급 실패 → ' + e.message);
    return;
  }

  var scan = scanMonths_();
  Object.keys(scan.ok).forEach(function (ym) { console.log('  확인한 달: ' + ym); });
  console.log('확인한 달 ' + scan.checked + '개 / 열린 날 ' + scan.open.length + '개' +
              (scan.open.length ? ': ' + scan.open.join(', ') : ''));
  if (scan.failed.length) console.log('조회 실패: ' + scan.errors.join(' | '));
}

/** 10분마다 실행되는 트리거를 만든다 (이미 있으면 새로 만든다). */
function createTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'checkOpenings') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('checkOpenings').timeBased().everyMinutes(10).create();
  console.log('10분마다 실행되는 트리거를 만들었습니다.');
}

/** 기억해 둔 상태를 지운다. 다음 실행에서 현재 열린 날을 전부 새 빈자리로 다시 알립니다. */
function resetState() {
  var props = PropertiesService.getScriptProperties();
  ['openSet', 'hallCode', 'statusMsgId', 'statusMsgChat', 'failCount', 'failAlerted',
   'partialCount', 'partialAlerted', 'lastError', 'lastSuccessAt', 'lastHeartbeatAt']
    .forEach(function (k) { props.deleteProperty(k); });
  console.log('상태를 초기화했습니다.');
}

// ───────────────────────────────────────────────────────────
//  텔레그램에서 말을 걸면 답하기 (웹훅)
// ───────────────────────────────────────────────────────────

/** 텔레그램이 보내오는 요청을 받는 자리. 절대 예외를 밖으로 던지지 않는다. */
function doPost(e) {
  try {
    handleTelegramUpdate_(e);
  } catch (err) {
    console.error('텔레그램 메시지 처리 실패: ' + err.message);
  }
  // 텔레그램에는 항상 200 을 준다. 안 그러면 같은 메시지를 계속 다시 보낸다.
  return ContentService.createTextOutput('');
}

function handleTelegramUpdate_(e) {
  // 웹앱 주소는 공개 주소라서, 주소 뒤에 붙인 비밀값이 맞을 때만 응답한다.
  var secret = prop_('WEBHOOK_SECRET');
  if (!secret || !e || !e.parameter || e.parameter.s !== secret) return;
  if (!e.postData || !e.postData.contents) return;

  // 봇이 둘이면 주소 뒤의 b= 로 구분한다. 받은 봇으로 답해야 하기 때문이다.
  var which = e.parameter.b === 'status' ? 'status' : 'main';

  var update = JSON.parse(e.postData.contents);
  // 답이 늦으면 텔레그램이 같은 메시지를 다시 보낸다. 같은 것에 두 번 답하지 않는다.
  if (!isNewUpdate_(which, update.update_id)) return;

  var msg = update.message || update.edited_message;
  if (!msg || !msg.chat || !msg.text) return;
  // 내 대화방에서 온 것만 받는다.
  if (String(msg.chat.id) !== tgChat_(which)) return;

  var text = String(msg.text).trim();
  var hall = matchHall_(text);

  if (hall) {
    reply_(which, '🔎 ' + hall.name + ' 을(를) 지금 찾아보고 있습니다. 20초쯤 걸립니다…');
    reply_(which, lookupHallText_(hall));
  } else if (/^\/?(확인|체크|check|refresh)/i.test(text)) {
    reply_(which, '🔎 지금 확인하고 있습니다. 20초쯤 걸립니다…');
    reply_(which, runOnDemand_());
  } else if (/^\/?(도움|help|start)/i.test(text)) {
    var names = HALLS.map(function (h) { return '• ' + h.keys[0] + ' — ' + h.name + ' 지금 찾아보기'; });
    reply_(which, ['보낼 수 있는 말:', '',
                   '• 상태 — 지금 상태 보기 (자동 감시: ' + HALL_NAME + ')',
                   '• 확인 — 감시 대상을 지금 바로 다시 확인'].concat(names).concat(
                  ['', '아무 말이나 보내도 상태를 알려드립니다.']).join('\n'));
  } else {
    reply_(which, storedStatusText_());
  }
}

/** 메시지에 예식장 이름이 들어 있으면 그 예식장을 돌려준다. */
function matchHall_(text) {
  var lower = String(text).toLowerCase();
  for (var i = 0; i < HALLS.length; i++) {
    for (var j = 0; j < HALLS[i].keys.length; j++) {
      if (lower.indexOf(HALLS[i].keys[j]) !== -1) return HALLS[i];
    }
  }
  return null;
}

/**
 * 물어본 예식장을 그 자리에서 조회한다.
 * 기억해 둔 상태는 건드리지 않는다. 그 상태는 자동 감시 대상의 것이기 때문이다.
 */
function lookupHallText_(hall) {
  var scan;
  try {
    scan = scanMonths_(hall.code);
  } catch (e) {
    return '❌ ' + hall.name + ' 조회 중 오류: ' + e.message;
  }
  if (scan.fatal || (scan.checked && scan.failed.length === scan.checked)) {
    return '❌ ' + hall.name + ' 을(를) 확인하지 못했습니다.\n' +
           String(scan.errors.join(' | ')).slice(0, 300);
  }

  var open = dedupeSorted_(scan.open);
  var lines = [];
  lines.push((open.length ? '🎉 ' : '🔍 ') + hall.name + ' — ' +
             (open.length ? '빈자리 ' + open.length + '건' : '빈자리 없음'));
  lines.push('확인한 달: ' + Object.keys(scan.ok).length + '개' +
             (scan.failed.length ? ' (' + scan.failed.length + '개는 못 봄)' : ''));
  if (open.length) {
    lines.push('');
    groupByMonth_(open).forEach(function (row) { lines.push(row); });
  }
  lines.push('');
  lines.push(PAGE_URL);
  return lines.join('\n');
}

/** ['2027-07-03', …] 를 '2027년 7월: 3(토), 4(일)' 처럼 달별로 묶는다. */
function groupByMonth_(dates) {
  var order = [], byMonth = {};
  dates.forEach(function (d) {
    var ym = d.slice(0, 7);
    if (!byMonth[ym]) { byMonth[ym] = []; order.push(ym); }
    byMonth[ym].push(Number(d.slice(8, 10)) + '(' + weekday_(d).charAt(0) + ')');
  });
  return order.map(function (ym) {
    return Number(ym.slice(0, 4)) + '년 ' + Number(ym.slice(5, 7)) + '월: ' + byMonth[ym].join(', ');
  });
}

/** 이미 처리한 메시지인가? 텔레그램의 재전송을 걸러낸다. */
function isNewUpdate_(which, id) {
  if (typeof id !== 'number') return true;
  var key = 'lastUpdateId_' + which;
  var props = PropertiesService.getScriptProperties();
  if (id <= Number(props.getProperty(key) || 0)) return false;
  // 처리 전에 먼저 기록한다. 도중에 실패하더라도 같은 메시지로 계속 돌지 않게.
  props.setProperty(key, String(id));
  return true;
}

function reply_(which, text) {
  telegramApi_('sendMessage', {
    chat_id: tgChat_(which), text: text, disable_web_page_preview: true
  }, which);
}

/** 요청을 받아 지금 바로 한 번 확인한다. 결과 문장을 돌려준다. */
function runOnDemand_() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(3000)) return '이미 확인이 돌고 있습니다. 잠시 뒤 다시 물어봐 주세요.';
  try {
    runCheck_();          // 정기 실행과 같은 길. 여기서는 기다리게 하지 않으려고 지터를 건너뛴다.
  } catch (err) {
    return '확인 중 오류가 났습니다: ' + err.message;
  } finally {
    lock.releaseLock();
  }
  return storedStatusText_();
}

/** 사이트를 다시 부르지 않고, 기억해 둔 것만으로 상태를 적는다. */
function storedStatusText_() {
  var props = PropertiesService.getScriptProperties();
  var open = readOpenSet_(props);
  var fails = Number(props.getProperty('failCount') || 0);
  var partial = Number(props.getProperty('partialCount') || 0);
  var last = props.getProperty('lastSuccessAt');

  var lines = [];
  lines.push(fails ? '🔴 확인 실패 ' + fails + '회 연속'
                   : (partial ? '🟡 일부 달만 확인됨 (' + partial + '회 연속)' : '🟢 감시 중'));
  lines.push('');
  lines.push('예식장: ' + HALL_NAME);
  lines.push('마지막 성공: ' + (last ? ago_(last) : '아직 없음'));
  lines.push('현재 빈자리: ' + (open.length ? open.length + '건' : '없음'));
  if (open.length) lines.push('  ' + open.slice(0, 10).join(', ') + (open.length > 10 ? ' 외' : ''));

  var error = props.getProperty('lastError');
  if ((fails || partial) && error) lines.push('', '원인: ' + error.slice(0, 200));

  var on = ScriptApp.getProjectTriggers().some(function (t) {
    return t.getHandlerFunction() === 'checkOpenings';
  });
  if (!on) lines.push('', '⚠️ 자동 실행이 꺼져 있습니다. 편집기에서 createTrigger 를 실행하세요.');

  lines.push('', '"확인" 이라고 보내면 지금 바로 다시 봅니다.');
  return lines.join('\n');
}

/** ISO 시각을 '3분 전 (18:52)' 처럼. */
function ago_(iso) {
  var then = new Date(iso);
  var minutes = Math.round((Date.now() - then.getTime()) / 60000);
  var when = Utilities.formatDate(then, 'Asia/Seoul', 'M월 d일 HH:mm');
  if (minutes < 1) return '방금 (' + when + ')';
  if (minutes < 60) return minutes + '분 전 (' + when + ')';
  if (minutes < 60 * 24) return Math.round(minutes / 60) + '시간 전 (' + when + ')';
  return Math.round(minutes / 1440) + '일 전 (' + when + ')';
}

/** 텔레그램에서 말을 걸면 답하도록 켠다. WEBAPP_URL 을 먼저 넣어야 한다. */
function setupTelegramCommands() {
  if (!hasTelegram_('main')) {
    console.log('먼저 TELEGRAM_TOKEN 과 TELEGRAM_CHAT_ID 를 넣으세요.');
    return;
  }
  var url = prop_('WEBAPP_URL');
  if (!url) {
    console.log('스크립트 속성 WEBAPP_URL 에 웹앱 주소를 넣으세요. ' +
                '(배포 > 새 배포 > 웹 앱 > 액세스 권한 "모든 사용자" 로 배포하면 나오는 주소)');
    return;
  }
  var props = PropertiesService.getScriptProperties();
  var secret = props.getProperty('WEBHOOK_SECRET');
  if (!secret) {
    secret = Utilities.getUuid().replace(/-/g, '');
    props.setProperty('WEBHOOK_SECRET', secret);
  }
  var bots = hasStatusBot_() ? ['main', 'status'] : ['main'];
  bots.forEach(function (which) {
    var hook = url + (url.indexOf('?') === -1 ? '?' : '&') + 's=' + secret + '&b=' + which;
    var res = telegramApi_('setWebhook', { url: hook, allowed_updates: ['message'] }, which);
    if (!res.ok) {
      console.log((which === 'main' ? '알림 봇' : '상태 봇') + ' 설정 실패: ' +
                  JSON.stringify(res).slice(0, 300));
      return;
    }
    try {
      telegramApi_('setMyCommands', { commands: [
        { command: 'status', description: '지금 상태 보기' },
        { command: 'check', description: '지금 바로 확인' }
      ]}, which);
    } catch (e) { /* 메뉴 등록 실패는 동작에 지장 없다 */ }
    console.log((which === 'main' ? '알림 봇' : '상태 봇') + ' 켰습니다.');
  });
  console.log('텔레그램에서 봇에게 "상태" 라고 보내보세요.');
}

/** 메시지 응답을 끈다. (findTelegramChatId 를 다시 쓰려면 꺼야 한다) */
function removeTelegramCommands() {
  ['main', 'status'].forEach(function (which) {
    if (which === 'status' && !hasStatusBot_()) return;
    try { telegramApi_('deleteWebhook', {}, which); }
    catch (e) { console.log(which + ' 끄기 실패: ' + e.message); }
  });
  console.log('메시지 응답을 껐습니다.');
}

/** 상태 봇의 채팅 ID 를 찾아준다. STATUS_TELEGRAM_TOKEN 을 먼저 넣으세요. */
function findStatusTelegramChatId() {
  findChatId_('status', 'STATUS_TELEGRAM_TOKEN', 'STATUS_TELEGRAM_CHAT_ID');
}

/** 지금 설정이 어떻게 돼 있는지 보여준다. 비밀값은 '설정됨' 으로만 찍는다. */
function showSettings() {
  var props = PropertiesService.getScriptProperties();
  var months = prop_('MONTHS');
  console.log('예식장: ' + HALL_CODE + ' = ' + HALL_NAME);
  console.log('감시할 달: ' + (months ? months + ' (직접 지정)' :
              '열린 달 전부 자동 (최대 ' + MAX_MONTHS_AHEAD + '달 앞까지)'));
  console.log('알림 채널: ' + enabledChannels_().map(function (c) { return c.name; }).join(' → '));
  console.log('  텔레그램(알림): ' + (hasTelegram_('main') ? '설정됨' : '없음'));
  console.log('  텔레그램(상태): ' + (hasStatusBot_() ? '따로 설정됨' : '알림 봇이 겸함'));
  console.log('  ntfy: ' + (prop_('NTFY_TOPIC') ? '설정됨' : '없음'));
  console.log('  이메일: ' + (prop_('EMAIL_TO') ? '설정됨' : '내 구글 계정'));
  console.log('기억 중인 빈자리: ' + readOpenSet_(props).length + '건');
  console.log('마지막 성공: ' + (props.getProperty('lastSuccessAt') || '없음') +
              ' / 연속 실패: ' + (props.getProperty('failCount') || '0') + '회');
  var last = props.getProperty('lastError');
  if (last) console.log('마지막 오류: ' + last);
  var triggers = ScriptApp.getProjectTriggers().filter(function (t) {
    return t.getHandlerFunction() === 'checkOpenings';
  });
  console.log('자동 실행 트리거: ' + (triggers.length ? '켜짐' : '꺼짐 — createTrigger 를 실행하세요'));
  console.log('텔레그램 메시지 응답: ' + (prop_('WEBHOOK_SECRET') ? '켜짐' : '꺼짐'));
}

/** 감시 대상을 기본값(삼성금융연수원)으로 되돌린다. */
function useDefaultHall() {
  var props = PropertiesService.getScriptProperties();
  props.deleteProperty('HALL_CODE');
  props.deleteProperty('HALL_NAME');
  console.log('자동 감시를 삼성금융연수원으로 되돌렸습니다. ' +
              '다른 예식장은 텔레그램에서 이름을 불러 확인하세요.');
}

/** 달 지정을 지우고 '열린 달 전부' 로 되돌린다. */
function useAllMonths() {
  PropertiesService.getScriptProperties().deleteProperty('MONTHS');
  console.log('달 지정을 지웠습니다. 이제 예약을 받는 달을 전부 자동으로 감시합니다.');
}

/**
 * 예식장 코드를 찾아준다. 1~15 번을 한 달치씩 훑어서 결과를 찍는다.
 * 원하는 예식장 번호를 찾으면 스크립트 속성 HALL_CODE 에 넣으세요.
 */
function findHallCodes() {
  var ym = (FIXED_MONTHS && FIXED_MONTHS[0]) || currentMonth_();
  var cookie;
  try { cookie = getCookie_(); }
  catch (e) { console.log('세션 쿠키 발급 실패 → ' + e.message); return; }

  console.log(ym + ' 기준으로 예식장 코드 1~15 를 훑어봅니다. (현재 설정: ' +
              HALL_CODE + ' = ' + HALL_NAME + ')');
  var showedKeys = false;
  for (var code = 1; code <= 15; code++) {
    if (code > 1) Utilities.sleep(GAP_MS);
    try {
      var month = fetchOpenDays_(cookie, ym, false, String(code));
      console.log('코드 ' + code + ' → 조회된 날 ' + month.total + '개 / 열린 날 ' +
                  month.open.length + '개' +
                  (month.open.length ? ': ' + month.open.join(', ') : ''));
      if (!showedKeys && month.total) {
        // 응답 어딘가에 예식장 이름이 들어 있을 수 있어서 한 번만 훑어본다.
        console.log('   (응답 항목: ' + Object.keys(month.raw).join(', ') + ')');
        showedKeys = true;
      }
    } catch (e) {
      console.log('코드 ' + code + ' → ' + e.message);
    }
  }
  console.log('열린 날이 있는 코드가 찾는 예식장일 가능성이 큽니다.');
}

/**
 * 텔레그램 채팅 ID 를 찾아준다.
 * 봇을 만든 뒤 텔레그램에서 그 봇에게 아무 말이나 보내고 이 함수를 실행하세요.
 */
function findTelegramChatId() {
  findChatId_('main', 'TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID');
}

function findChatId_(which, tokenKey, chatKey) {
  var token = prop_(tokenKey);
  if (!token) {
    console.log('먼저 스크립트 속성에 ' + tokenKey + ' 을 넣으세요.');
    return;
  }
  var res = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/getUpdates',
                              { muteHttpExceptions: true });
  var data;
  try { data = JSON.parse(res.getContentText()); }
  catch (e) { console.log('응답을 읽지 못했습니다: ' + res.getContentText().slice(0, 200)); return; }

  if (!data.ok) {
    if (/webhook/i.test(String(data.description || ''))) {
      console.log('메시지 응답이 켜져 있어서 이 방법을 쓸 수 없습니다. ' +
                  'removeTelegramCommands 를 먼저 실행하세요.');
    } else {
      console.log('텔레그램이 거절했습니다. 토큰이 맞는지 확인하세요: ' + JSON.stringify(data).slice(0, 200));
    }
    return;
  }
  var updates = data.result || [];
  if (!updates.length) {
    console.log('아직 받은 메시지가 없습니다. 텔레그램에서 봇에게 아무 말이나 보낸 뒤 다시 실행하세요.');
    return;
  }
  var ids = {};
  updates.forEach(function (u) {
    var msg = u.message || u.edited_message || u.channel_post;
    if (msg && msg.chat) ids[msg.chat.id] = (msg.chat.title || msg.chat.first_name || '');
  });
  Object.keys(ids).forEach(function (id) {
    console.log('채팅 ID: ' + id + '  (' + ids[id] + ')  ← 이 숫자를 ' + chatKey + ' 에 넣으세요');
  });
}

// ───────── 사이트 조회 ─────────

/**
 * 'Address unavailable' 처럼 서버에 닿지도 못하는 일시적 오류는 한 번 쉬었다 다시 해본다.
 * 한 회차에 20번 가까이 부르다 보면 그중 하나는 이런 식으로 튕기는데, 그때마다
 * 감시가 고장난 것처럼 구는 건 과민반응이다.
 */
function fetchWithRetry_(url, options) {
  try {
    return UrlFetchApp.fetch(url, options);
  } catch (e) {
    Utilities.sleep(2000);
    return UrlFetchApp.fetch(url, options);
  }
}

function getCookie_() {
  var res = fetchWithRetry_(PAGE_URL, { muteHttpExceptions: true, followRedirects: false });
  var headers = res.getAllHeaders();
  var sc = headers['Set-Cookie'] || headers['set-cookie'] || [];
  if (typeof sc === 'string') sc = [sc];
  var cookie = sc.map(function (c) { return c.split(';')[0]; })
                 .filter(function (c) { return c; })
                 .join('; ');
  if (!cookie) {
    // 쿠키 없이 그냥 진행하면 전부 로그인 페이지를 받아 조용히 실패한다. 여기서 끊는 편이 낫다.
    throw new Error('세션 쿠키를 받지 못했습니다 (HTTP ' + res.getResponseCode() +
                    '). 사이트가 Google 서버 IP를 막았을 수 있습니다.');
  }
  return cookie;
}

/**
 * 한 달을 조회해 { open: [날짜…], total: 조회된 날 수, raw: 응답 원본 } 을 돌려준다.
 * hallCode 를 주면 그 홀을, 안 주면 설정된 홀을 본다.
 */
function fetchOpenDays_(cookie, ym, verbose, hallCode) {
  var y = ym.slice(0, 4), m = ym.slice(5, 7);
  var body = {
    wedgHllC: hallCode || HALL_CODE, wedgEtblfmPsbY: y, wedgEtblfmPsbMm: m, wedgAplcBooStc: '4',
    common: buildCommon_()
  };
  var res = fetchWithRetry_(SVC_URL, {
    method: 'post',
    contentType: 'application/json; charset=UTF-8',
    headers: { 'Cookie': cookie, 'X-Requested-With': 'XMLHttpRequest', 'Referer': PAGE_URL },
    payload: JSON.stringify(body),
    muteHttpExceptions: true, followRedirects: true
  });

  var code = res.getResponseCode();
  var text = res.getContentText('UTF-8');
  if (code !== 200) throw new Error('HTTP ' + code + ': ' + text.slice(0, 120));

  var j;
  try { j = JSON.parse(text); }
  catch (e) { throw new Error('응답이 JSON이 아님(차단 의심): ' + text.slice(0, 120)); }
  if (j.rs === undefined || j.rs === null) {
    throw new Error("응답에 'rs' 가 없습니다: " + text.slice(0, 120));
  }

  // rs 는 HTML 이스케이프된 JSON 문자열이고, 그 안의 true/false 가 따옴표로 묶여 있다.
  var rsStr = htmlUnescape_(j.rs).replace(/"true"/g, 'true').replace(/"false"/g, 'false');
  var parsed, days;
  try {
    parsed = JSON.parse(rsStr);
    days = parsed.days || {};
  } catch (e) { throw new Error('rs 안쪽을 해석하지 못했습니다: ' + rsStr.slice(0, 120)); }
  if (typeof days !== 'object') throw new Error("'days' 가 객체가 아닙니다: " + typeof days);

  if (verbose) console.log(ym + ' 원본 days: ' + JSON.stringify(days).slice(0, 400));

  var result = { open: [], total: 0, raw: parsed };
  Object.keys(days).forEach(function (d) {
    var day = parseInt(d, 10);
    if (!validDate_(parseInt(y, 10), parseInt(m, 10), day)) return;
    result.total++;
    var info = days[d];
    // 명시적으로 closed:true 인 날만 제외한다. 빈자리를 놓치는 것보다 한 번 더 알리는 쪽이 낫다.
    if (info && info.closed === true) return;
    result.open.push(ym + '-' + ('0' + day).slice(-2));
  });
  return result;
}

function buildCommon_() {
  var now = new Date();
  var sn = Utilities.formatDate(now, 'Asia/Seoul', 'HHmmssSSS') +
           ('0000' + Math.floor(Math.random() * 100000)).slice(-5);
  return {
    // 캡처한 실제 요청의 값. 서비스 ID(SWDDWSWSWHS03) 11번째 글자에서 온 값이라 'S' 로 고정한다.
    dlngEvnDvC: 'S', scrnId: 'UWDDWSWH04M1',
    stdEtxtCrtDt: Utilities.formatDate(now, 'Asia/Seoul', 'yyyyMMdd'),
    stdEtxtCrtSysNm: 'P0000000', stdEtxtSn: sn,
    stdEtxtPrgDvNo: 0, stdEtxtPrgNo: 0, indvInfIncYn: 'N', usid: ' '
  };
}

// ───────── 알림 (여러 채널 + 자동 폴백) ─────────

/**
 * 설정된 채널을 순서대로 시도하고 하나라도 성공하면 멈춘다.
 *
 * 한 채널만 쓰면 그 채널이 막히는 순간(ntfy 의 IP 공유 할당량 등) 조용히 알림이 끊긴다.
 * 그래서 이메일을 항상 마지막 보루로 둔다.
 */
function notify_(title, message, priority) {
  var channels = enabledChannels_();
  var errors = [];

  for (var i = 0; i < channels.length; i++) {
    try {
      if (channels[i].send(title, message, priority)) {
        if (errors.length) {
          console.warn('앞 채널 실패 후 ' + channels[i].name + ' 로 보냈습니다: ' + errors.join(' | '));
        }
        return true;
      }
      errors.push(channels[i].name + ': 전송 실패');
    } catch (e) {
      errors.push(channels[i].name + ': ' + e.message);
    }
  }
  console.error('모든 알림 채널 실패: ' + (errors.length ? errors.join(' | ') : '설정된 채널 없음'));
  return false;
}

function enabledChannels_() {
  var channels = [];
  if (prop_('TELEGRAM_TOKEN') && prop_('TELEGRAM_CHAT_ID')) {
    channels.push({ name: '텔레그램', send: sendTelegram_ });
  }
  if (prop_('NTFY_TOPIC')) {
    channels.push({ name: 'ntfy', send: sendNtfy_ });
  }
  // 이메일은 설정이 없어도 내 구글 계정으로 보낼 수 있으므로 항상 마지막에 둔다.
  channels.push({ name: '이메일', send: sendEmail_ });
  return channels;
}

function telegramApi_(method, payload, which) {
  var res = UrlFetchApp.fetch(
    'https://api.telegram.org/bot' + tgToken_(which) + '/' + method,
    {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });
  var code = res.getResponseCode();
  var text = res.getContentText();
  if (code < 200 || code >= 300) throw new Error('HTTP ' + code + ' ' + text.slice(0, 200));
  return JSON.parse(text);
}

function sendTelegram_(title, message) {
  telegramApi_('sendMessage', {
    chat_id: prop_('TELEGRAM_CHAT_ID'),
    text: title + '\n\n' + message + '\n\n' + PAGE_URL,
    disable_web_page_preview: true
  });
  return true;
}

/**
 * 봇은 둘까지 쓴다.
 *   main   - 빈자리·실패 알림. 꼭 봐야 하는 것만 온다.
 *   status - 살아있음 표시와 하트비트. 설정하지 않으면 main 이 겸한다.
 * 나눠 두면 알림 대화방이 조용해서, 진짜 알림이 묻히지 않는다.
 */
function tgToken_(which) {
  if (which === 'status') return prop_('STATUS_TELEGRAM_TOKEN') || prop_('TELEGRAM_TOKEN');
  return prop_('TELEGRAM_TOKEN');
}

function tgChat_(which) {
  if (which === 'status') return prop_('STATUS_TELEGRAM_CHAT_ID') || prop_('TELEGRAM_CHAT_ID');
  return prop_('TELEGRAM_CHAT_ID');
}

function hasTelegram_(which) {
  return !!(tgToken_(which) && tgChat_(which));
}

/** 상태 전용 봇을 따로 뒀는가? */
function hasStatusBot_() {
  return !!(prop_('STATUS_TELEGRAM_TOKEN') && prop_('STATUS_TELEGRAM_CHAT_ID'));
}

/** 운영 신호(하트비트 등). 상태 봇이 있으면 그쪽으로, 없으면 평소 알림 경로로. */
function notifyStatus_(title, message) {
  if (hasStatusBot_()) {
    try {
      telegramApi_('sendMessage', {
        chat_id: tgChat_('status'), text: title + '\n\n' + message, disable_web_page_preview: true
      }, 'status');
      return true;
    } catch (e) {
      console.log('상태 봇 전송 실패, 평소 경로로 보냅니다: ' + e.message);
    }
  }
  return notify_(title, message, 'min');
}

/**
 * 텔레그램에 '살아있음' 메시지를 하나 두고 매 회차 고쳐 쓴다.
 *
 * 알림이 안 오는 상태가 '빈자리가 없어서'인지 '감시가 멈춰서'인지 폰에서 바로 구분하려면,
 * 아무 일이 없을 때도 눈에 보이는 무언가가 있어야 한다. 고쳐 쓰기라 알림은 울리지 않는다.
 */
function updateStatusMessage_(props, scan, openNow) {
  if (!hasTelegram_('status')) return;
  var chat = tgChat_('status');
  // 상태 봇을 바꿨다면 예전 대화방의 메시지 번호는 쓸 수 없다.
  if (props.getProperty('statusMsgChat') !== String(chat)) {
    props.deleteProperty('statusMsgId');
    props.setProperty('statusMsgChat', String(chat));
  }

  var text = buildStatusText_(scan, openNow);
  var id = props.getProperty('statusMsgId');

  if (id) {
    try {
      telegramApi_('editMessageText', {
        chat_id: chat, message_id: Number(id),
        text: text, disable_web_page_preview: true
      }, 'status');
      return;
    } catch (e) {
      // 메시지를 지웠거나 너무 오래됐을 수 있다. 아래에서 새로 만든다.
      console.log('상태 메시지 갱신 실패, 새로 만듭니다: ' + e.message);
    }
  }
  try {
    var res = telegramApi_('sendMessage', {
      chat_id: chat, text: text,
      disable_web_page_preview: true, disable_notification: true
    }, 'status');
    if (res && res.result && res.result.message_id) {
      props.setProperty('statusMsgId', String(res.result.message_id));
    }
  } catch (e) {
    console.log('상태 메시지 생성 실패: ' + e.message);
  }
}

function buildStatusText_(scan, openNow) {
  var allFailed = scan.fatal || (scan.checked && scan.failed.length === scan.checked);
  var lines = [];
  lines.push(allFailed ? '🔴 감시 멈춤 — 확인이 안 되고 있습니다'
                       : (scan.failed.length ? '🟡 일부만 확인됨' : '🟢 감시 중'));
  lines.push('');
  lines.push('예식장: ' + HALL_NAME);
  lines.push('마지막 확인: ' + Utilities.formatDate(new Date(), 'Asia/Seoul', 'M월 d일 (EEE) HH:mm'));
  if (!allFailed) {
    lines.push('확인한 달: ' + Object.keys(scan.ok).length + '개' +
               (scan.failed.length ? ' (' + scan.failed.length + '개 실패)' : ''));
  }
  lines.push('현재 빈자리: ' + (openNow.length ? openNow.length + '건' : '없음'));
  if (openNow.length) {
    lines.push('  ' + openNow.slice(0, 10).join(', ') + (openNow.length > 10 ? ' 외' : ''));
  }
  if (allFailed) {
    lines.push('');
    lines.push('원인: ' + String(scan.errors.join(' | ')).slice(0, 200));
  }
  lines.push('');
  lines.push('10분마다 이 메시지가 갱신됩니다. 시각이 안 바뀌면 멈춘 것입니다.');
  return lines.join('\n');
}

function sendNtfy_(title, message, priority) {
  var server = (prop_('NTFY_SERVER') || 'https://ntfy.sh').replace(/\/+$/, '');
  var headers = {
    // ntfy 헤더는 latin-1 만 허용하므로 한글·이모지 제목은 RFC2047 로 인코딩한다.
    'Title': encodeHeader_(title),
    'Priority': priority || 'high',
    'Tags': 'wedding_ring',
    'Click': PAGE_URL
  };
  var token = prop_('NTFY_TOKEN');
  if (token) headers['Authorization'] = 'Bearer ' + token;

  var res = UrlFetchApp.fetch(server + '/' + prop_('NTFY_TOPIC'), {
    method: 'post', payload: message, headers: headers, muteHttpExceptions: true
  });
  var code = res.getResponseCode();
  if (code >= 200 && code < 300) return true;
  throw new Error('HTTP ' + code + ' ' + res.getContentText().slice(0, 200));
}

function sendEmail_(title, message) {
  var to = prop_('EMAIL_TO') || Session.getEffectiveUser().getEmail();
  if (!to) throw new Error('받을 주소를 찾지 못했습니다. 스크립트 속성 EMAIL_TO 를 넣으세요.');
  MailApp.sendEmail({ to: to, subject: title, body: message + '\n\n' + PAGE_URL });
  return true;
}

function buildSlotMessage_(dates) {
  var lines = [HALL_NAME + ' 예약 가능 날짜가 새로 나왔습니다.', ''];
  dates.slice(0, MAX_LINES).forEach(function (d) {
    lines.push('• ' + d + ' (' + weekday_(d) + ')');
  });
  if (dates.length > MAX_LINES) lines.push('• … 외 ' + (dates.length - MAX_LINES) + '건');
  lines.push('', '지금 바로 신청하세요.');
  return lines.join('\n');
}

function encodeHeader_(value) {
  if (/^[\x00-\x7F]*$/.test(value)) return value;
  return '=?UTF-8?B?' + Utilities.base64Encode(value, Utilities.Charset.UTF_8) + '?=';
}

// ───────── 실패 감지 ─────────

function recordFailure_(props, message) {
  var count = Number(props.getProperty('failCount') || 0) + 1;
  props.setProperty('failCount', String(count));
  props.setProperty('lastError', String(message).slice(0, 500));

  if (count >= FAIL_ALERT_AFTER && props.getProperty('failAlerted') !== 'true') {
    // 조용히 죽는 것이 가장 위험하다. 확인이 안 되고 있다는 사실 자체를 알린다.
    var sent = notify_('⚠️ 빈자리 확인 실패 ' + count + '회 연속',
                       '빈자리 확인이 계속 실패하고 있습니다. 알림이 안 오는 것이 아니라 ' +
                       '확인 자체가 안 되고 있는 상태입니다.\n\n' + String(message).slice(0, 600),
                       'high');
    if (sent) props.setProperty('failAlerted', 'true');
  }
}

/** 일부 달만 못 본 경우. 오래 이어지면 그때 한 번 알린다. */
function recordPartial_(props, failed, errors) {
  var count = Number(props.getProperty('partialCount') || 0) + 1;
  props.setProperty('partialCount', String(count));
  props.setProperty('lastError', String(errors.join(' | ')).slice(0, 500));
  console.warn('일부 조회 실패 (' + count + '회 연속): ' + errors.join(' | '));

  if (count >= PARTIAL_ALERT_AFTER && props.getProperty('partialAlerted') !== 'true') {
    var sent = notify_('⚠️ 일부 달을 계속 못 보고 있습니다',
                       failed.join(', ') + ' 을 ' + count + '회 연속 확인하지 못했습니다. ' +
                       '나머지 달은 정상 감시 중입니다.\n\n' + String(errors.join(' | ')).slice(0, 400),
                       'high');
    if (sent) props.setProperty('partialAlerted', 'true');
  }
}

function recordSuccess_(props) {
  if (props.getProperty('failAlerted') === 'true' || props.getProperty('partialAlerted') === 'true') {
    notify_('✅ 감시 복구됨', '빈자리 확인이 다시 정상 동작합니다.', 'low');
  }
  props.setProperty('failCount', '0');
  props.setProperty('failAlerted', 'false');
  props.setProperty('partialCount', '0');
  props.setProperty('partialAlerted', 'false');
  props.setProperty('lastSuccessAt', new Date().toISOString());
}

function maybeHeartbeat_(props, openCount) {
  if (!HEARTBEAT_HOURS) return;
  var last = Number(props.getProperty('lastHeartbeatAt') || 0);
  var now = Date.now();
  if (last && now - last < HEARTBEAT_HOURS * 3600 * 1000) return;
  props.setProperty('lastHeartbeatAt', String(now));
  if (!last) return;  // 처음 실행에서는 보내지 않고 기준 시각만 잡는다.
  notifyStatus_('💓 ' + HALL_NAME + ' 감시 중',
                '감시는 정상 동작 중입니다. 현재 열린 날 ' + openCount + '건.');
}

// ───────── 잡다한 도우미 ─────────

function prop_(key) {
  var value = PropertiesService.getScriptProperties().getProperty(key);
  return value ? String(value).trim() : '';
}

/** 서울 기준 이번 달 ('2026-09'). */
function currentMonth_() {
  return Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM');
}

/** '2026-11' 에서 n 달 뒤. */
function addMonths_(ym, n) {
  var y = parseInt(ym.slice(0, 4), 10);
  var m = parseInt(ym.slice(5, 7), 10) - 1 + n;
  y += Math.floor(m / 12);
  m = ((m % 12) + 12) % 12;
  return y + '-' + ('0' + (m + 1)).slice(-2);
}

/** 쉼표로 구분된 '2027-05, 2027-06' 을 배열로. 쓸 수 있는 값이 없으면 null. */
function parseMonths_(text) {
  if (!text) return null;
  var list = String(text).split(',')
    .map(function (s) { return s.trim(); })
    .filter(function (s) { return /^\d{4}-(0[1-9]|1[0-2])$/.test(s); });
  return list.length ? list : null;
}

/** 감시할 예식장이 바뀌었으면 이전 홀의 기록을 지운다. */
function forgetIfHallChanged_(props) {
  if (props.getProperty('hallCode') === HALL_CODE) return;
  // 날짜만 기억하기 때문에, 그대로 두면 이전 홀에서 봤던 날짜가 새 홀의 알림을 가로막는다.
  props.deleteProperty('openSet');
  props.setProperty('hallCode', HALL_CODE);
}

function readOpenSet_(props) {
  try {
    var parsed = JSON.parse(props.getProperty('openSet') || '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    return [];
  }
}

function toSet_(list) {
  var set = {};
  list.forEach(function (k) { set[k] = 1; });
  return set;
}

function dedupeSorted_(list) {
  return Object.keys(toSet_(list)).sort();
}

function validDate_(y, m, d) {
  if (!d || isNaN(d)) return false;
  var dt = new Date(y, m - 1, d);
  return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d;
}

function htmlUnescape_(s) {
  return String(s).replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
}

function weekday_(k) {
  var p = k.split('-'), wd = ['일', '월', '화', '수', '목', '금', '토'];
  return wd[new Date(+p[0], +p[1] - 1, +p[2]).getDay()] + '요일';
}
