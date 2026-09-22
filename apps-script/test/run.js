/**
 * Code.gs 회귀 테스트.
 *
 * Apps Script 런타임(PropertiesService / UrlFetchApp / MailApp / LockService / …)을
 * 흉내 내서 Code.gs 를 그대로 돌린다. 확인하는 것은 두 가지다.
 *
 *   1. 조회가 실패했을 때 상태를 어떻게 다루는가
 *      → 깨지면 같은 날짜를 반복해서 알리거나, 감시가 조용히 죽는다.
 *   2. 알림 채널 하나가 막혔을 때 다른 채널로 넘어가는가
 *      → 깨지면 빈자리가 나와도 아무 데도 도착하지 않는다.
 *
 * 실행:  node apps-script/test/run.js
 */

'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const CODE = fs.readFileSync(path.join(__dirname, '..', 'Code.gs'), 'utf8');

/** 가짜 사이트 + 가짜 구글 런타임. 보낸 알림을 모아서 돌려준다. */
function createRuntime(site, store) {
  const sent = [];
  const ctx = {
    console: { log() {}, warn() {}, error() {} },
    PropertiesService: {
      getScriptProperties: () => ({
        getProperty: k => (k in store ? store[k] : null),
        setProperty: (k, v) => { store[k] = String(v); },
        deleteProperty: k => { delete store[k]; },
      }),
    },
    LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock() {} }) },
    Session: { getEffectiveUser: () => ({ getEmail: () => 'me@example.com' }) },
    MailApp: {
      sendEmail(opts) {
        if (site.emailOk === false) throw new Error('Service invoked too many times');
        sent.push({ channel: 'email', title: opts.subject, body: opts.body });
      },
    },
    Utilities: {
      sleep() {},
      formatDate: () => '20260101',
      base64Encode: s => Buffer.from(s, 'utf8').toString('base64'),
      Charset: { UTF_8: 'utf8' },
    },
    UrlFetchApp: {
      fetch(url, opts) {
        if (url.indexOf('api.telegram.org') !== -1) {
          if (site.telegramStatus !== 200) {
            return { getResponseCode: () => site.telegramStatus, getContentText: () => '{"ok":false}' };
          }
          const body = JSON.parse(opts.payload);
          sent.push({ channel: 'telegram', title: body.text.split('\n')[0], body: body.text });
          return { getResponseCode: () => 200, getContentText: () => '{"ok":true}' };
        }
        if (url.indexOf('ntfy') !== -1) {
          if (site.ntfyStatus !== 200) {
            return {
              getResponseCode: () => site.ntfyStatus,
              getContentText: () => '{"code":42908,"error":"daily message quota reached"}',
            };
          }
          sent.push({
            channel: 'ntfy',
            title: decodeHeader(opts.headers.Title),
            body: opts.payload,
            priority: opts.headers.Priority,
          });
          return { getResponseCode: () => 200, getContentText: () => '{"id":"x"}' };
        }
        if (url.indexOf('.jsp') !== -1) {
          return {
            getResponseCode: () => (site.cookieOk ? 200 : 302),
            getAllHeaders: () => (site.cookieOk ? { 'Set-Cookie': ['JSESSIONID=abc; Path=/'] } : {}),
          };
        }
        const body = JSON.parse(opts.payload);
        const ym = body.wedgEtblfmPsbY + '-' + body.wedgEtblfmPsbMm;
        site.requested.push(body.wedgHllC + '/' + ym);
        if (site.failMonths.indexOf(ym) !== -1) {
          return { getResponseCode: () => 500, getContentText: () => 'Internal Server Error' };
        }
        return { getResponseCode: () => 200, getContentText: () => JSON.stringify({ rs: buildRs(site, ym) }) };
      },
    },
  };
  vm.createContext(ctx);
  vm.runInContext(CODE, ctx);
  return { ctx, sent };
}

/**
 * 실제 응답을 그대로 흉내 낸다. 사이트는 그 달의 주말만 목록에 싣고,
 * true/false 를 따옴표로 감싼 JSON 을 HTML 이스케이프해서 rs 에 넣어 보낸다.
 */
function buildRs(site, ym) {
  const [y, m] = ym.split('-').map(Number);
  const days = {};
  for (let d = 1; d <= new Date(y, m, 0).getDate(); d++) {
    const wd = new Date(y, m - 1, d).getDay();
    if (wd === 0 || wd === 6) days[String(d)] = { closed: 'true' };
  }
  (site.open[ym] || []).forEach(d => { days[String(d)] = { closed: 'false' }; });
  return JSON.stringify({ days }).replace(/"/g, '&quot;');
}

function decodeHeader(value) {
  const m = /^=\?UTF-8\?B\?(.*)\?=$/.exec(value);
  return m ? Buffer.from(m[1], 'base64').toString('utf8') : value;
}

let failures = 0;
function check(name, condition, detail) {
  if (condition) {
    console.log('  ok   ' + name);
  } else {
    failures++;
    console.log('  FAIL ' + name + (detail === undefined ? '' : '  → ' + detail));
  }
}

// ───────────────────────────────────────────────────────────

const site = {
  cookieOk: true,
  failMonths: [],
  open: { '2027-05': [1, 2] },   // 2027-05-01(토), 05-02(일)
  ntfyStatus: 200,
  telegramStatus: 200,
  emailOk: true,
  requested: [],
};
const store = { NTFY_TOPIC: 'test-topic' };

/** 한 회차를 돌리고 그동안 나간 알림을 돌려준다. */
function tick() {
  site.requested = [];
  const { ctx, sent } = createRuntime(site, store);
  ctx.checkOpenings();
  return sent;
}

const isSlotAlert = p => p.title.indexOf('빈자리 ') !== -1;
const clearState = () => { for (const k in store) delete store[k]; };

console.log('\n[상태] 첫 실행 — 지금 열려 있는 날을 알린다');
let out = tick();
check('알림 1통', out.length === 1, JSON.stringify(out));
check('두 날짜 모두 포함',
  out[0] && /2027-05-01/.test(out[0].body) && /2027-05-02/.test(out[0].body), out[0] && out[0].body);
check('상태 저장됨', store.openSet === '["2027-05-01","2027-05-02"]', store.openSet);

console.log('\n[상태] 변화가 없으면 다시 알리지 않는다');
check('알림 0통', tick().length === 0);

console.log('\n[상태] 새 날짜가 생기면 그 날짜만 알린다');
site.open['2027-06'] = [5];
out = tick();
check('알림 1통', out.length === 1, JSON.stringify(out));
check('새 날짜만 언급',
  out[0] && /2027-06-05/.test(out[0].body) && !/2027-05-01/.test(out[0].body), out[0] && out[0].body);

console.log('\n[상태] 일부 달만 조회 실패 — 그 달의 상태를 잃지 않는다');
site.failMonths = ['2027-05'];
out = tick();
check('중복 빈자리 알림 없음', !out.some(isSlotAlert), JSON.stringify(out));
check('실패한 달의 날짜가 상태에 남아있음', store.openSet.indexOf('2027-05-01') !== -1, store.openSet);
check('실패 1회로 기록', store.failCount === '1', store.failCount);

console.log('\n[상태] 실패했던 달이 복구돼도 재알림이 가지 않는다');
site.failMonths = [];
check('알림 0통', tick().length === 0);
check('실패 횟수 초기화', store.failCount === '0', store.failCount);

console.log('\n[상태] 전체 실패가 이어지면 점검 알림이 한 번만 간다');
site.cookieOk = false;
const snapshot = store.openSet;
check('1회차 조용함', tick().length === 0);
check('2회차 조용함', tick().length === 0);
out = tick();
check('3회차에 점검 알림', out.length === 1 && /확인 실패/.test(out[0].title), JSON.stringify(out));
check('점검 알림에 원인 포함', out[0] && /세션 쿠키/.test(out[0].body), out[0] && out[0].body);
check('4회차는 중복 알림 없음', tick().length === 0);
check('상태는 그대로 보존', store.openSet === snapshot, store.openSet);

console.log('\n[상태] 복구되면 복구 알림이 간다');
site.cookieOk = true;
out = tick();
check('복구 알림 포함', out.some(p => /복구/.test(p.title)), JSON.stringify(out.map(p => p.title)));
check('그 다음 회차는 조용함', tick().length === 0);

console.log('\n[상태] 조회된 날이 거의 전부 열림이면 — 막지 않고 경고로 알린다');
clearState();
store.NTFY_TOPIC = 'test-topic';
site.failMonths = [];
site.open = {};
['2027-05', '2027-06', '2027-09', '2027-10', '2027-11'].forEach(ym => {
  site.open[ym] = Array.from({ length: 31 }, (_, i) => i + 1);
});
out = tick();
check('알림은 간다', out.length === 1, JSON.stringify(out.map(p => p.title)));
check('평소와 다른 제목으로 경고', out[0] && /확인 필요/.test(out[0].title), out[0] && out[0].title);
check('직접 확인하라고 안내', out[0] && /직접 확인/.test(out[0].body));
check('상태를 저장해 한 번만 알림', tick().length === 0);

// ───────── 알림 채널 ─────────

function channelSetup(props) {
  clearState();
  Object.keys(props).forEach(k => { store[k] = props[k]; });
  site.failMonths = [];
  site.open = { '2027-05': [1] };
  site.ntfyStatus = 200;
  site.telegramStatus = 200;
  site.emailOk = true;
}

function settingsSetup(props) {
  clearState();
  Object.keys(props).forEach(k => { store[k] = props[k]; });
  site.failMonths = [];
  site.ntfyStatus = 200;
  site.telegramStatus = 200;
  site.emailOk = true;
}

console.log('\n[채널] ntfy 만 설정하면 ntfy 로 간다');
channelSetup({ NTFY_TOPIC: 'test-topic' });
out = tick();
check('ntfy 1통', out.length === 1 && out[0].channel === 'ntfy', JSON.stringify(out.map(p => p.channel)));

console.log('\n[채널] ntfy 가 429 로 막히면 이메일로 넘어간다 (실제로 겪은 상황)');
channelSetup({ NTFY_TOPIC: 'test-topic' });
site.ntfyStatus = 429;
out = tick();
check('이메일로 도착', out.length === 1 && out[0].channel === 'email', JSON.stringify(out.map(p => p.channel)));
check('내용은 그대로', out[0] && /2027-05-01/.test(out[0].body), out[0] && out[0].body);

console.log('\n[채널] 아무것도 설정 안 해도 이메일로 간다');
channelSetup({});
out = tick();
check('이메일로 도착', out.length === 1 && out[0].channel === 'email', JSON.stringify(out.map(p => p.channel)));

console.log('\n[채널] 텔레그램이 있으면 텔레그램을 먼저 쓴다');
channelSetup({ TELEGRAM_TOKEN: 't', TELEGRAM_CHAT_ID: '1', NTFY_TOPIC: 'test-topic' });
out = tick();
check('텔레그램 1통', out.length === 1 && out[0].channel === 'telegram', JSON.stringify(out.map(p => p.channel)));

console.log('\n[채널] 텔레그램이 죽으면 ntfy → 이메일 순으로 내려간다');
channelSetup({ TELEGRAM_TOKEN: 't', TELEGRAM_CHAT_ID: '1', NTFY_TOPIC: 'test-topic' });
site.telegramStatus = 401;
out = tick();
check('ntfy 로 도착', out.length === 1 && out[0].channel === 'ntfy', JSON.stringify(out.map(p => p.channel)));

channelSetup({ TELEGRAM_TOKEN: 't', TELEGRAM_CHAT_ID: '1', NTFY_TOPIC: 'test-topic' });
site.telegramStatus = 401;
site.ntfyStatus = 429;
out = tick();
check('둘 다 죽으면 이메일로 도착', out.length === 1 && out[0].channel === 'email',
  JSON.stringify(out.map(p => p.channel)));

console.log('\n[채널] 모든 채널이 죽어도 감시 자체는 멈추지 않는다');
channelSetup({ TELEGRAM_TOKEN: 't', TELEGRAM_CHAT_ID: '1', NTFY_TOPIC: 'test-topic' });
site.telegramStatus = 401;
site.ntfyStatus = 429;
site.emailOk = false;
out = tick();
check('알림 0통', out.length === 0);
check('그래도 상태는 기록됨', store.openSet === '["2027-05-01"]', store.openSet);

// ───────── 설정 (예식장 / 월) ─────────

console.log('\n[설정] MONTHS 속성이 있으면 그 달만 조회한다');
settingsSetup({ MONTHS: '2027-05, 잘못된값, 2027-09' });
site.open = { '2027-05': [1] };
tick();
check('두 달만 조회', site.requested.length === 2, JSON.stringify(site.requested));
check('잘못된 값은 무시', site.requested.every(r => /2027-05|2027-09/.test(r)), JSON.stringify(site.requested));

console.log('\n[설정] HALL_CODE 속성이 요청에 실린다');
settingsSetup({ HALL_CODE: '9', MONTHS: '2027-05' });
site.open = { '2027-05': [1] };
tick();
check('홀 9 로 조회', site.requested[0] === '9/2027-05', JSON.stringify(site.requested));
check('기억해 둔 홀도 9', store.hallCode === '9', store.hallCode);

console.log('\n[설정] 예식장을 바꾸면 이전 홀의 기억이 새 홀 알림을 막지 않는다');
settingsSetup({ HALL_CODE: '5', MONTHS: '2027-05' });
site.open = { '2027-05': [1] };
out = tick();
check('홀 5 에서 알림 1통', out.length === 1, JSON.stringify(out.map(p => p.title)));
check('같은 홀에서는 재알림 없음', tick().length === 0);

store.HALL_CODE = '9';
out = tick();
check('홀을 바꾸니 같은 날짜라도 다시 알림', out.length === 1, JSON.stringify(out.map(p => p.title)));
check('바뀐 홀이 기록됨', store.hallCode === '9', store.hallCode);

console.log('\n[설정] HALL_NAME 이 알림 제목에 쓰인다');
settingsSetup({ HALL_CODE: '9', HALL_NAME: '서초사옥', MONTHS: '2027-05' });
site.open = { '2027-05': [1] };
out = tick();
check('제목에 서초사옥', out[0] && /서초사옥/.test(out[0].title), out[0] && out[0].title);

console.log('\n' + (failures ? failures + '개 실패' : '전부 통과'));
process.exit(failures ? 1 : 0);
