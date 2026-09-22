/*************************************************************
 *  삼성 금융연수원 웨딩홀 "빈자리(취소 자리)" 알림 — Google Apps Script
 *
 *  ▼▼▼ 설정: 아래 세 줄만 확인하세요 ▼▼▼
 *************************************************************/

// 폰 ntfy 앱에서 구독할 '나만의 토픽 이름'.
// 권장: 여기를 비워 두고 [프로젝트 설정 > 스크립트 속성]에 NTFY_TOPIC 으로 저장하세요.
//       (이 파일은 공개 저장소에 올라가므로 토픽을 적어 두면 남에게 노출됩니다.)
var NTFY_TOPIC_FALLBACK = '';

var HALL_CODE = '5';                                             // 5 = 삼성금융연수원
var MONTHS    = ['2027-05', '2027-06', '2027-09', '2027-10', '2027-11'];

/*************************************************************
 *  ▲▲▲ 여기 위쪽만 신경 쓰면 됩니다. 아래는 안 건드려도 돼요 ▲▲▲
 *************************************************************/

var HALL_NAME = '삼성금융연수원';
var PAGE_URL  = 'https://s-wedding.samsungcard.com/internal/add-apply/UWDDWSWH04M1.jsp';
var SVC_URL   = 'https://s-wedding.samsungcard.com/service/SWDDWSWSWHS03';

var FAIL_ALERT_AFTER = 3;      // 이만큼 연속으로 문제가 생기면 '점검 필요' 알림 (3회 = 약 30분)
var HEARTBEAT_HOURS  = 24;     // 이 시간마다 '살아있음' 알림. 0 으로 두면 끕니다.
var MAX_OPEN_PER_MONTH = 20;   // 한 달에 이보다 많이 열리면 응답 형식이 바뀐 것으로 의심
var MAX_LINES = 30;            // 알림 한 통에 적는 최대 날짜 수
var JITTER_MS = 90 * 1000;     // 매 실행을 0~90초 무작위로 늦춰 규칙적인 패턴을 피한다
var GAP_MS    = 1200;          // 달과 달 사이 간격

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
  var prev = readOpenSet_(props);
  var prevSet = toSet_(prev);

  var scan = scanMonths_();

  // 모든 달이 실패했다면 상태를 건드리지 않는다.
  // (여기서 openSet 을 비우면 다음에 성공했을 때 전부 '새 빈자리'로 다시 알림이 간다.)
  if (scan.failed.length === MONTHS.length) {
    console.warn('전체 조회 실패: ' + scan.errors.join(' | '));
    recordFailure_(props, scan.errors.join(' | '));
    return;
  }

  // 열린 날이 비정상적으로 많으면 파싱이 깨진 것으로 본다. 날짜 150개를 쏟아내지 않고 점검 알림만 보낸다.
  var okCount = MONTHS.length - scan.failed.length;
  if (scan.open.length > okCount * MAX_OPEN_PER_MONTH) {
    var why = '열린 날이 ' + scan.open.length + '건으로 비정상적으로 많습니다. 응답 형식이 바뀐 것 같습니다.';
    console.warn(why);
    recordFailure_(props, why);
    return;
  }

  // 실패한 달은 이전 상태를 그대로 이어받는다 → 일시적 실패가 중복 알림으로 번지지 않게.
  var carried = prev.filter(function (d) { return scan.failed.indexOf(d.slice(0, 7)) !== -1; });
  var openNow = dedupeSorted_(scan.open.concat(carried));

  var newly = openNow.filter(function (d) { return !prevSet[d]; });
  if (newly.length) {
    pushNtfy_('🎉 ' + HALL_NAME + ' 빈자리 ' + newly.length + '건', buildSlotMessage_(newly), 'urgent');
  }

  props.setProperty('openSet', JSON.stringify(openNow));

  if (scan.failed.length) {
    // 일부 달만 실패: 알림은 정상적으로 보냈지만 반쪽짜리 결과이므로 실패로 센다.
    console.warn('일부 조회 실패: ' + scan.errors.join(' | '));
    recordFailure_(props, scan.errors.join(' | '));
  } else {
    recordSuccess_(props);
    maybeHeartbeat_(props, openNow.length);
  }

  console.log('현재 열린 날: ' + (openNow.length ? openNow.join(', ') : '없음') +
              ' / 새로 알린 날: ' + (newly.length ? newly.join(', ') : '없음') +
              (scan.failed.length ? ' / 조회 실패한 달: ' + scan.failed.join(', ') : ''));
}

/** 대상 월을 모두 조회한다. 일부가 실패해도 나머지는 진행한다. */
function scanMonths_() {
  var result = { open: [], failed: [], errors: [] };

  var cookie;
  try {
    cookie = getCookie_();
  } catch (e) {
    // 쿠키를 못 받으면 어느 달도 조회할 수 없다.
    result.failed = MONTHS.slice();
    result.errors.push(e.message);
    return result;
  }

  MONTHS.forEach(function (ym, i) {
    if (i) Utilities.sleep(GAP_MS);
    try {
      result.open = result.open.concat(fetchOpenDays_(cookie, ym));
    } catch (e) {
      result.failed.push(ym);
      result.errors.push(ym + ': ' + e.message);
    }
  });
  return result;
}

// ───────────────────────────────────────────────────────────
//  처음에 한 번 눌러 확인하는 함수 (폰 알림 테스트 + 현재 상태 + 응답 형식 점검)
// ───────────────────────────────────────────────────────────
function sendTestPush() {
  var ok = pushNtfy_('🔔 테스트', '테스트 알림입니다. 이 메시지가 폰에 뜨면 연결 성공! 🎉', 'high');
  console.log(ok ? 'ntfy 전송 성공' : 'ntfy 전송 실패 — 위 로그의 응답 코드를 확인하세요.');

  var cookie;
  try {
    cookie = getCookie_();
    console.log('세션 쿠키 발급 성공');
  } catch (e) {
    console.log('세션 쿠키 발급 실패 → ' + e.message);
    return;
  }

  MONTHS.forEach(function (ym, i) {
    if (i) Utilities.sleep(GAP_MS);
    try {
      var open = fetchOpenDays_(cookie, ym, true);
      console.log(ym + ' → 열린 날: ' + (open.length ? open.join(', ') : '없음(전부 마감)'));
    } catch (e) {
      console.log(ym + ' → 읽기 실패: ' + e.message);
    }
  });
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
  ['openSet', 'failCount', 'failAlerted', 'lastError', 'lastSuccessAt', 'lastHeartbeatAt']
    .forEach(function (k) { props.deleteProperty(k); });
  console.log('상태를 초기화했습니다.');
}

// ───────── 아래는 내부 동작 (안 건드려도 됨) ─────────

function getCookie_() {
  var res = UrlFetchApp.fetch(PAGE_URL, { muteHttpExceptions: true, followRedirects: false });
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

function fetchOpenDays_(cookie, ym, verbose) {
  var y = ym.slice(0, 4), m = ym.slice(5, 7);
  var body = {
    wedgHllC: HALL_CODE, wedgEtblfmPsbY: y, wedgEtblfmPsbMm: m, wedgAplcBooStc: '4',
    common: buildCommon_()
  };
  var res = UrlFetchApp.fetch(SVC_URL, {
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
  var days;
  try { days = (JSON.parse(rsStr).days) || {}; }
  catch (e) { throw new Error('rs 안쪽을 해석하지 못했습니다: ' + rsStr.slice(0, 120)); }
  if (typeof days !== 'object') throw new Error("'days' 가 객체가 아닙니다: " + typeof days);

  if (verbose) console.log(ym + ' 원본 days: ' + JSON.stringify(days).slice(0, 400));

  var open = [];
  Object.keys(days).forEach(function (d) {
    var day = parseInt(d, 10);
    if (!validDate_(parseInt(y, 10), parseInt(m, 10), day)) return;
    var info = days[d];
    // 명시적으로 closed:true 인 날만 제외한다. 빈자리를 놓치는 것보다 한 번 더 알리는 쪽이 낫다.
    // (형식이 바뀌어 전부 '열림'으로 보이는 경우는 MAX_OPEN_PER_MONTH 가 걸러낸다.)
    if (info && info.closed === true) return;
    open.push(ym + '-' + ('0' + day).slice(-2));
  });
  return open;
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

// ───────── 알림 ─────────

function buildSlotMessage_(dates) {
  var lines = [HALL_NAME + ' 예약 가능 날짜가 새로 나왔습니다.', ''];
  dates.slice(0, MAX_LINES).forEach(function (d) {
    lines.push('• ' + d + ' (' + weekday_(d) + ')');
  });
  if (dates.length > MAX_LINES) lines.push('• … 외 ' + (dates.length - MAX_LINES) + '건');
  lines.push('', '지금 바로 신청하세요.');
  return lines.join('\n');
}

function pushNtfy_(title, message, priority) {
  var res = UrlFetchApp.fetch('https://ntfy.sh/' + ntfyTopic_(), {
    method: 'post',
    payload: message,
    headers: {
      // ntfy 헤더는 latin-1 만 허용하므로 한글·이모지 제목은 RFC2047 로 인코딩한다.
      'Title': encodeHeader_(title),
      'Priority': priority || 'high',
      'Tags': 'wedding_ring',
      'Click': PAGE_URL
    },
    muteHttpExceptions: true
  });
  var code = res.getResponseCode();
  console.log('ntfy 응답: ' + code + ' / ' + res.getContentText());
  return code >= 200 && code < 300;
}

function ntfyTopic_() {
  var topic = PropertiesService.getScriptProperties().getProperty('NTFY_TOPIC') || NTFY_TOPIC_FALLBACK;
  if (!topic) {
    throw new Error('ntfy 토픽이 설정되지 않았습니다. [프로젝트 설정 > 스크립트 속성]에 ' +
                    'NTFY_TOPIC 을 추가하세요. (README 참고)');
  }
  return topic;
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
    var sent = pushNtfy_('⚠️ 빈자리 확인 실패 ' + count + '회 연속',
                         '빈자리 확인이 계속 실패하고 있습니다. 알림이 안 오는 것이 아니라 ' +
                         '확인 자체가 안 되고 있는 상태입니다.\n\n' + String(message).slice(0, 600),
                         'high');
    if (sent) props.setProperty('failAlerted', 'true');
  }
}

function recordSuccess_(props) {
  if (props.getProperty('failAlerted') === 'true') {
    pushNtfy_('✅ 감시 복구됨', '빈자리 확인이 다시 정상 동작합니다.', 'low');
  }
  props.setProperty('failCount', '0');
  props.setProperty('failAlerted', 'false');
  props.setProperty('lastSuccessAt', new Date().toISOString());
}

function maybeHeartbeat_(props, openCount) {
  if (!HEARTBEAT_HOURS) return;
  var last = Number(props.getProperty('lastHeartbeatAt') || 0);
  var now = Date.now();
  if (last && now - last < HEARTBEAT_HOURS * 3600 * 1000) return;
  props.setProperty('lastHeartbeatAt', String(now));
  if (!last) return;  // 처음 실행에서는 보내지 않고 기준 시각만 잡는다.
  pushNtfy_('💓 ' + HALL_NAME + ' 감시 중',
            '감시는 정상 동작 중입니다. 현재 열린 날 ' + openCount + '건.', 'min');
}

// ───────── 잡다한 도우미 ─────────

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
