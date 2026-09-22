/**
 * Code.gs 회귀 테스트.
 *
 * Apps Script 런타임(PropertiesService / UrlFetchApp / LockService / Utilities)을 흉내 내서
 * Code.gs 를 그대로 돌린다. 특히 "조회가 실패했을 때 상태를 어떻게 다루는가"를 확인한다.
 * 이 부분이 깨지면 같은 날짜를 반복해서 알리거나, 감시가 조용히 죽는다.
 *
 * 실행:  node apps-script/test/run.js
 */

'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const CODE = fs.readFileSync(path.join(__dirname, '..', 'Code.gs'), 'utf8');

/** 가짜 사이트 + 가짜 구글 런타임. */
function createRuntime(site, store) {
  const pushes = [];
  const ctx = {
    console: { log() {}, warn() {} },
    PropertiesService: {
      getScriptProperties: () => ({
        getProperty: k => (k in store ? store[k] : null),
        setProperty: (k, v) => { store[k] = String(v); },
        deleteProperty: k => { delete store[k]; },
      }),
    },
    LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock() {} }) },
    Utilities: {
      sleep() {},
      formatDate: () => '20260101',
      base64Encode: s => Buffer.from(s, 'utf8').toString('base64'),
      Charset: { UTF_8: 'utf8' },
    },
    UrlFetchApp: {
      fetch(url, opts) {
        if (url.indexOf('ntfy.sh') !== -1) {
          pushes.push({
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
        if (site.failMonths.indexOf(ym) !== -1) {
          return { getResponseCode: () => 500, getContentText: () => 'Internal Server Error' };
        }
        return { getResponseCode: () => 200, getContentText: () => JSON.stringify({ rs: buildRs(site, ym) }) };
      },
    },
  };
  vm.createContext(ctx);
  vm.runInContext(CODE, ctx);
  return { ctx, pushes };
}

/** 실제 응답처럼 HTML 이스케이프된, true/false 가 따옴표로 묶인 JSON 문자열을 만든다. */
function buildRs(site, ym) {
  const days = {};
  for (let d = 1; d <= 30; d++) days[String(d)] = { closed: 'true' };
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

const site = { cookieOk: true, failMonths: [], open: { '2027-05': [3, 15] } };
const store = { NTFY_TOPIC: 'test-topic' };

/** 한 회차를 돌리고 그동안 나간 알림을 돌려준다. */
function tick() {
  const { ctx, pushes } = createRuntime(site, store);
  ctx.checkOpenings();
  return pushes;
}

const isSlotAlert = p => p.title.indexOf('빈자리 ') !== -1 && p.priority === 'urgent';

console.log('\n첫 실행 — 지금 열려 있는 날을 알린다');
let sent = tick();
check('알림 1통', sent.length === 1, JSON.stringify(sent));
check('두 날짜 모두 포함',
  sent[0] && /2027-05-03/.test(sent[0].body) && /2027-05-15/.test(sent[0].body), sent[0] && sent[0].body);
check('상태 저장됨', store.openSet === '["2027-05-03","2027-05-15"]', store.openSet);

console.log('\n변화가 없으면 다시 알리지 않는다');
check('알림 0통', tick().length === 0);

console.log('\n새 날짜가 생기면 그 날짜만 알린다');
site.open['2027-06'] = [7];
sent = tick();
check('알림 1통', sent.length === 1, JSON.stringify(sent));
check('새 날짜만 언급',
  sent[0] && /2027-06-07/.test(sent[0].body) && !/2027-05-03/.test(sent[0].body), sent[0] && sent[0].body);

console.log('\n일부 달만 조회 실패 — 그 달의 상태를 잃지 않는다');
site.failMonths = ['2027-05'];
sent = tick();
check('중복 빈자리 알림 없음', !sent.some(isSlotAlert), JSON.stringify(sent));
check('실패한 달의 날짜가 상태에 남아있음', store.openSet.indexOf('2027-05-03') !== -1, store.openSet);
check('실패 1회로 기록', store.failCount === '1', store.failCount);

console.log('\n실패했던 달이 복구돼도 재알림이 가지 않는다');
site.failMonths = [];
check('알림 0통', tick().length === 0);
check('실패 횟수 초기화', store.failCount === '0', store.failCount);

console.log('\n전체 실패가 이어지면 점검 알림이 한 번만 간다');
site.cookieOk = false;
const snapshot = store.openSet;
check('1회차 조용함', tick().length === 0);
check('2회차 조용함', tick().length === 0);
sent = tick();
check('3회차에 점검 알림', sent.length === 1 && sent[0].priority === 'high', JSON.stringify(sent));
check('점검 알림에 원인 포함', sent[0] && /세션 쿠키/.test(sent[0].body), sent[0] && sent[0].body);
check('4회차는 중복 알림 없음', tick().length === 0);
check('상태는 그대로 보존', store.openSet === snapshot, store.openSet);

console.log('\n복구되면 복구 알림이 간다');
site.cookieOk = true;
sent = tick();
check('복구 알림 포함', sent.some(p => p.priority === 'low'), JSON.stringify(sent.map(p => p.title)));
check('그 다음 회차는 조용함', tick().length === 0);

console.log('\n응답 형식이 깨져 전부 열림으로 보이면 날짜를 쏟아내지 않는다');
for (const k in store) if (k !== 'NTFY_TOPIC') delete store[k];
site.failMonths = [];
site.open = {};
['2027-05', '2027-06', '2027-09', '2027-10', '2027-11'].forEach(ym => {
  site.open[ym] = Array.from({ length: 30 }, (_, i) => i + 1);
});
sent = tick();
check('빈자리 알림 없음', !sent.some(isSlotAlert), JSON.stringify(sent.map(p => p.title)));
check('실패로 기록', store.failCount === '1', store.failCount);
check('상태를 건드리지 않음', store.openSet === undefined, store.openSet);

console.log('\n' + (failures ? failures + '개 실패' : '전부 통과'));
process.exit(failures ? 1 : 0);
