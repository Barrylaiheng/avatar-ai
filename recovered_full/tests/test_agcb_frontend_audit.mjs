/**
 * 「配置 › 连接与绑定」面板 · 前端审计（真跑代码，不是字符串匹配）
 *
 * 做法：把 app/web/index.html 里那个 IIFE 模块原样抽出来，用 new Function 注入
 *       window / document / pyqtBridge 等桩，然后在 Node 里真实调用它的对外方法，
 *       拦截它发给桥接层的每一条 call/on，最后断言行为。
 *
 * 覆盖：
 *   B  冲突提示链路（后端回报 conflicts → 弹 toast；无冲突/失败不弹）
 *   C  渠道矩阵归一（wechat→wcf 等 5 渠道：拉取命令 + 读取渠道 + 保存渠道）
 *   D  正式版闸门锁行为（免费版灰态 + 点击弹激活 + 锁定区 off；正式版默认可开关）
 *   E  筛选组合（已绑定/全部/全选/搜索/刷新 × 主人开关）
 *   F  群聊 / 群消息排除出候选（拉取回包过滤 + 回退缓存过滤）
 *   G  切换智能体后重新回填管理者（渠道选中态是会话级全局 → 换智能体必须重读，且标记不串号）
 *   H  渠道锁定（配置里选定的连接渠道 = 该智能体唯一渠道：进入面板即回填该渠道、残留勾选清空、
 *      未配渠道的老数据不被覆盖、查不到智能体时安全兜底）
 *
 * 跑法：node tests/test_agcb_frontend_audit.mjs
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const HTML_PATH = path.join(ROOT, 'app', 'web', 'index.html');

let failed = 0;
let total = 0;
function check(cond, label) {
  total++;
  if (cond) {
    console.log(`  [OK] ${label}`);
  } else {
    failed++;
    console.log(`  [FAIL] ${label}`);
  }
}
function section(t) { console.log(`\n===== ${t} =====`); }

// ------------------------------------------------------------------
// 1. 抽出模块
// ------------------------------------------------------------------
const HTML = fs.readFileSync(HTML_PATH, 'utf8');
const MARK = '智能体配置：「连接与绑定」tab';
const iMark = HTML.indexOf(MARK);
if (iMark < 0) { console.error(`[FATAL] index.html 里找不到模块标记「${MARK}」`); process.exit(1); }
const iFn = HTML.indexOf('(function () {', iMark);
if (iFn < 0) { console.error('[FATAL] 标记之后找不到 IIFE 起点'); process.exit(1); }
const iEnd = HTML.indexOf('})();', iFn);
if (iEnd < 0) { console.error('[FATAL] 找不到 IIFE 终点'); process.exit(1); }
const MODULE = HTML.slice(iFn, iEnd + 5);
if (!MODULE.includes('window.agcbRefresh') || !MODULE.includes('window.initAgcbGate')) {
  console.error('[FATAL] 抽出来的模块不完整（缺 agcbRefresh / initAgcbGate）');
  process.exit(1);
}
console.log(`[提取] AGCB 模块 ${MODULE.split('\n').length} 行`);

// ------------------------------------------------------------------
// 2. 桩：DOM / 桥接层 / 全局依赖
// ------------------------------------------------------------------
function makeClassList() {
  const set = new Set();
  return {
    add: (c) => { set.add(c); },
    remove: (c) => { set.delete(c); },
    contains: (c) => set.has(c),
    toggle: (c, force) => {
      const on = (force === undefined) ? !set.has(c) : !!force;
      if (on) set.add(c); else set.delete(c);
      return on;
    },
  };
}
function makeEl(id) {
  const attrs = {};
  return {
    id,
    _html: '',
    value: '',
    checked: false,
    textContent: '',
    dataset: {},
    style: {},
    children: [],
    parentNode: null,
    classList: makeClassList(),
    querySelectorAll: () => [],
    closest: () => null,
    setAttribute: (k, v) => { attrs[k] = String(v); },
    getAttribute: (k) => (k in attrs ? attrs[k] : null),
    removeAttribute: (k) => { delete attrs[k]; },
    hasAttribute: (k) => k in attrs,
    addEventListener: () => {},
    appendChild: (c) => { this.children.push(c); return c; },
    removeChild: () => {},
    focus: () => {},
    select: () => {},
    blur: () => {},
    click: () => {},
    insertAdjacentHTML: () => {},
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = v; },
  };
}

const CHANS = ['wechat', 'oa', 'wecom', 'feishu', 'dingtalk'];

// 渠道选择已改为下拉单选（#agcbChanSelect，与「使用模型」同款），桩一个 select 即可
const chanSelect = makeEl('agcbChanSelect');

const chipNodes = ['all', 'on'].map((m) => { const n = makeEl('chip-' + m); n.dataset.filter = m; return n; });
const chipWrap = makeEl('agcbMgrChips');
chipWrap.querySelectorAll = (sel) => (sel === '.chip' ? chipNodes : []);

const els = {};
function reg(id, el) { els[id] = el || makeEl(id); return els[id]; }
reg('agcbList');
els['agcbChanSelect'] = chanSelect;
chipWrap.parentNode = null;
els['agcbMgrChips'] = chipWrap;
const toggleEl = reg('agcbMgrToggle');
const labelEl = reg('agcbMgrLabel');
const lockEl = reg('agcbLockArea');
const searchEl = reg('agcbSearchInput');
reg('agcbMgrCount');
const bodyEl = makeEl('body');

const documentStub = {
  body: bodyEl,
  getElementById: (id) => els[id] || null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => makeEl('tmp'),
};

const calls = [];
const callbacks = {};
const toasts = [];
const timers = [];
let activationOpened = 0;

const pyqtBridge = {
  _callbacks: callbacks,
  call(action, payload) {
    calls.push({ action, payload });
    // 忠实模拟一次「请求 → 回包」往返：真实的桥会把回包丢回同名 handler
    if (FETCH_CMDS.includes(action) && typeof callbacks[action] === 'function') {
      callbacks[action]({ ok: true, data: { ok: true, contacts: [] } });
    }
  },
  on(action, fn) { callbacks[action] = fn; },   // 覆盖式注册，与真实实现一致
};
// 预置既有 handler（验证 wrap 不会顶掉它们）
const FETCH_CMDS = ['fetch_wcf_contacts', 'fetch_oa_contacts', 'fetch_wecom_contacts',
                    'fetch_feishu_contacts', 'fetch_dingtalk_contacts'];
[...FETCH_CMDS, 'list_channel_bindings'].forEach((c) => {
  callbacks[c] = function (d) { calls.push({ action: '__原handler__:' + c, payload: d }); };
});

let statusOf = () => ({});   // 占位，下面会被重建
function rebuildWindow() {
  const w = {};
  w.pyqtBridge = pyqtBridge;
  w._activationState = { activated: false };
  return w;
}
let currentAgentId = 'agent-1';
const wcfFriends = [];
const oaFriends = [];
const _wecomContacts = [];
const _feishuContacts = [];
const _dingtalkContacts = [];

function loadModule(win) {
  const factory = new Function(
    'window', 'document', 'console', 'setTimeout',
    'showToast', 'escapeHtml', 'escapeAttr', 'peerAvatarColor',
    'wcfFriends', 'oaFriends', '_wecomContacts', '_feishuContacts', '_dingtalkContacts',
    'openActivationModal', '_getCurrentAgentId',
    MODULE + '\nreturn window;\n'
  );
  return factory(
    win, documentStub, console,
    (fn, ms) => { timers.push(ms); return 0; },
    (m) => { toasts.push(String(m)); },
    (s) => String(s === undefined || s === null ? '' : s),
    (s) => String(s === undefined || s === null ? '' : s),
    () => '#abcdef',
    wcfFriends, oaFriends, _wecomContacts, _feishuContacts, _dingtalkContacts,
    () => { activationOpened++; },
    () => currentAgentId
  );
}

let win = loadModule(rebuildWindow());
const W = win;   // 模块把状态挂在传入的 window 上，直接用这个对象

function rowCount() {
  const html = els['agcbList'].innerHTML || '';
  return (html.match(/agcb-row/g) || []).length;
}
function rowPeers() {
  const html = els['agcbList'].innerHTML || '';
  return [...html.matchAll(/data-peer="([^"]*)"/g)].map((m) => m[1]);
}
function lastCall(action) {
  for (let i = calls.length - 1; i >= 0; i--) if (calls[i].action === action) return calls[i];
  return null;
}
function resetLogs() { calls.length = 0; toasts.length = 0; }

// ------------------------------------------------------------------
// B：冲突提示链路
// ------------------------------------------------------------------
section('B 冲突提示链路（前端 toast）');
{
  resetLogs();
  const onSave = callbacks['save_agent_managers'];
  check(typeof onSave === 'function', 'B1 模块注册了 save_agent_managers 回执处理器');
  check(onSave !== undefined && !onSave.__agcbWrapped, 'B2 该处理器不是被 wrap 出来的（不会被别的东西顶掉）');

  onSave({ ok: true, data: { conflicts: [
    { peer_id: 'px', peer_name: '张三', agent_name: '智能体B' },
    { peer_id: 'py', peer_name: '李四', agent_name: '智能体C' },
  ] } });
  check(toasts.length === 1, 'B3 有冲突 → 弹 1 条 toast');
  check(/已被其他智能体占用/.test(toasts[0] || ''), 'B4 toast 文案说明「已被其他智能体占用」');
  check((toasts[0] || '').includes('张三') && (toasts[0] || '').includes('李四'), 'B5 toast 带上了冲突者姓名');
  check((toasts[0] || '').includes('2 位'), 'B6 toast 带上了冲突人数');

  resetLogs();
  onSave({ ok: true, data: { conflicts: [] } });
  check(toasts.length === 0, 'B7 无冲突 → 不打扰用户（不弹）');

  resetLogs();
  onSave({ ok: false });
  check(toasts.length === 0, 'B8 后端失败（ok:false）→ 不弹');

  resetLogs();
  onSave({ ok: true, data: {} });
  check(toasts.length === 0, 'B9 回执缺 conflicts 字段 → 不崩、不弹');
}

// ------------------------------------------------------------------
// C：渠道矩阵归一
// ------------------------------------------------------------------
section('C 渠道矩阵归一（面板键 → 后端渠道号）');
{
  const EXPECT = {
    wechat:   { fetch: 'fetch_wcf_contacts',      api: 'wcf' },
    oa:       { fetch: 'fetch_oa_contacts',       api: 'oa' },
    wecom:    { fetch: 'fetch_wecom_contacts',    api: 'wecom' },
    feishu:   { fetch: 'fetch_feishu_contacts',   api: 'feishu' },
    dingtalk: { fetch: 'fetch_dingtalk_contacts', api: 'dingtalk' },
  };
  currentAgentId = 'agent-1';
  W._activationState = { activated: true };
  W.initAgcbGate();

  Object.keys(EXPECT).forEach((chan) => {
    resetLogs();
    chanSelect.value = chan;
    W.agcbPickChannelSelect(chanSelect);

    check(chanSelect.value === chan, `C[${chan}] 选中后 select 值回填同步`);

    const f = lastCall(EXPECT[chan].fetch);
    check(!!f, `C[${chan}] 选渠道即拉取，用的是 ${EXPECT[chan].fetch}`);

    const lb = lastCall('list_channel_bindings');
    check(!!lb && lb.payload && lb.payload.channel === EXPECT[chan].api,
      `C[${chan}] 读取管理者时 channel 归一为 ${EXPECT[chan].api}（实得 ${lb && lb.payload && lb.payload.channel}）`);
    check(!!lb && lb.payload && lb.payload.agent_id === 'agent-1',
      `C[${chan}] 读取管理者带上了当前 agent_id`);

    const orig = lastCall('__原handler__:' + EXPECT[chan].fetch);
    check(!!orig, `C[${chan}] 既有连接管理的 handler 仍被正常调用（没被顶掉）`);
  });

  // 保存链路同样必须归一
  resetLogs();
  W._agcbSaveQueue = { agentId: 'agent-1', chans: { wechat: [{ peer_id: 'p1', peer_name: '甲', peer_type: 'friend' }] } };
  W._agcbCommitManagers('agent-1');
  const sv = lastCall('save_agent_managers');
  check(!!sv && sv.payload.channel === 'wcf', `C[save] 保存渠道归一为 wcf（实得 ${sv && sv.payload && sv.payload.channel}）`);

  // 选回占位项「— 请选择 —」= 清空选择，不允许发任何拉取
  resetLogs();
  chanSelect.value = '';
  W.agcbPickChannelSelect(chanSelect);
  const anyFetch = calls.filter((c) => FETCH_CMDS.includes(c.action) || c.action === 'list_channel_bindings');
  check(anyFetch.length === 0 && W._agcbChan === '', 'C[empty] 选回占位项 → 清空渠道且不发拉取');
  check(!!sv && JSON.stringify(sv.payload.managers) === JSON.stringify([{ peer_id: 'p1', peer_name: '甲', peer_type: 'friend' }]),
    'C[save] managers 原样透传');
  check(W._agcbSaveQueue === null, 'C[save] 提交后清空队列（不会重复提交）');

  resetLogs();
  W._agcbCommitManagers('agent-1');
  check(calls.length === 0, 'C[save] 无待提交队列时不发请求');
}

// ------------------------------------------------------------------
// D：正式版闸门锁行为
// ------------------------------------------------------------------
section('D 正式版闸门（免费版锁定 / 正式版可开关）');
{
  // --- 免费版 ---
  W._activationState = { activated: false };
  W._agcbOn = null;
  W.initAgcbGate();
  check(W._agcbOn === false, 'D1 免费版：主开关强制为关');
  check(toggleEl.checked === false, 'D2 免费版：开关控件 unchecked');
  check(labelEl.textContent === '升级正式版启用 →', `D3 免费版：文案是升级引导（实得「${labelEl.textContent}」）`);
  check(bodyEl.classList.contains('agcb-gated'), 'D4 免费版：body 打上 agcb-gated（开关视觉灰化）');
  check(lockEl.classList.contains('off'), 'D5 免费版：锁定区 off（名单/筛选不可点）');

  W._agcbPicked = { 'wechat:someone': true };
  W.initAgcbGate();
  check(Object.keys(W._agcbPicked).length === 0, 'D6 免费版：重新进入时清掉残留勾选');

  const before = activationOpened;
  W.agcbToggleGate();
  check(activationOpened === before + 1, 'D7 免费版：点主开关 → 弹激活弹窗');
  check(W._agcbOn === false, 'D8 免费版：点完开关状态不变（不能白嫖）');

  // --- 正式版 ---
  W._activationState = { activated: true };
  W._agcbOn = null;
  W.initAgcbGate();
  check(W._agcbOn === true, 'D9 正式版：默认「启用」');
  check(labelEl.textContent === '启用', `D10 正式版：文案为「启用」（实得「${labelEl.textContent}」）`);
  check(!bodyEl.classList.contains('agcb-gated'), 'D11 正式版：去掉 agcb-gated 灰化');
  check(!lockEl.classList.contains('off'), 'D12 正式版：解锁锁定区，可勾可选');

  // 已经手动关过，重进面板不能被掰回「启用」
  W._agcbOn = false;
  W.initAgcbGate();
  check(W._agcbOn === false, 'D13 正式版：用户关过之后重进面板保持关闭（不被重置为启用）');
  check(lockEl.classList.contains('off'), 'D14 关闭态：锁定区 off');

  W.agcbToggleGate();
  check(W._agcbOn === true && labelEl.textContent === '启用' && !lockEl.classList.contains('off'),
    'D15 正式版：再次点击 → 开启并解锁');
  W.agcbToggleGate();
  check(W._agcbOn === false && labelEl.textContent === '已关闭' && lockEl.classList.contains('off'),
    'D16 正式版：关闭 → 文案变「已关闭」且锁定区 off');
}

// ------------------------------------------------------------------
// E：筛选组合（已绑定 / 全部 / 全选 / 搜索 / 刷新）
// ------------------------------------------------------------------
section('E 筛选组合与主人开关');
{
  const CHAN = 'dingtalk';
  W._activationState = { activated: true };
  currentAgentId = 'agent-1';
  W.initAgcbGate();

  W._agcbChan = CHAN;
  W._agcbFetch[CHAN] = { fetched: true, loading: false, error: '' };
  W._agcbContacts[CHAN] = [
    { peer_id: 'u1', peer_name: '张三', remark: '同事' },
    { peer_id: 'u2', peer_name: '李四', remark: '' },
    { peer_id: 'u3', peer_name: '王五', remark: '' },
  ];
  W._agcbMgr = {}; W._agcbPicked = {}; W._agcbSync = {};
  W._agcbQ = ''; W._agcbChip = 'all';

  W.initAgcbGate();
  check(rowCount() === 3, `E1 「全部」视图列出 3 人（实得 ${rowCount()}）`);

  W.agcbFilter('李');
  check(rowCount() === 1 && rowPeers()[0] === 'u2', `E2 按姓名搜索「李」→ 命中 1 人（实得 ${JSON.stringify(rowPeers())}）`);

  W.agcbFilter('u3');
  check(rowCount() === 1 && rowPeers()[0] === 'u3', 'E3 按 peer_id 搜索也能命中');

  W.agcbFilter('');
  check(rowCount() === 3, 'E4 清空搜索 → 回到 3 人');

  // 已绑定 chip
  W._agcbMgr = { 'dingtalk:u1': true };
  chipWrap.parentNode = { querySelectorAll: () => chipNodes };
  W.agcbPickChip(chipNodes[1], 'on');
  check(rowCount() === 1 && rowPeers()[0] === 'u1', `E5 「已绑定」视图只留管理者（实得 ${JSON.stringify(rowPeers())}）`);
  check(W._agcbChip === 'on', 'E6 chip 状态已切换');

  const pickedBefore = Object.keys(W._agcbPicked).length;
  W.agcbSelectAll();
  check(Object.keys(W._agcbPicked).length === pickedBefore, 'E7 「已绑定」视图下全选被禁用（对齐既有实现）');

  W.agcbPickChip(chipNodes[0], 'all');
  check(rowCount() === 3, 'E8 切回「全部」→ 3 人');

  W.agcbSelectAll();
  check(Object.keys(W._agcbPicked).length === 3, `E9 全选 → 3 人勾上（实得 ${Object.keys(W._agcbPicked).length}）`);
  W.agcbSelectAll();
  check(Object.keys(W._agcbPicked).length === 0, 'E10 再点全选 → 反选清空（幂等切换）');

  // 批量开关：勾 2 人 → 翻任意一个开关 → 整批生效 + 勾选清空 + 渠道纳入提交范围
  W._agcbPicked = { 'dingtalk:u2': true, 'dingtalk:u3': true };
  W._agcbSync = {};
  W.agcbToggleMgr({ checked: true, closest: () => ({ dataset: { peer: 'u2' } }) }, null);
  check(!!W._agcbMgr['dingtalk:u2'] && !!W._agcbMgr['dingtalk:u3'],
    'E11 批量开关：勾选的所有人整批变管理者');
  check(Object.keys(W._agcbPicked).length === 0, 'E12 批量生效后清空勾选');
  check(W._agcbSync.dingtalk === 'agent-1', 'E13 用户表态后该渠道纳入保存提交范围');

  // 没勾人 → 只改当前行
  W.agcbToggleMgr({ checked: true, closest: () => ({ dataset: { peer: 'u1' } }) }, null);
  check(!!W._agcbMgr['dingtalk:u1'], 'E14 没勾人时只改当前行');
  check(!!W._agcbMgr['dingtalk:u2'], 'E15 没勾人时不影响其它行');

  // 提交汇总
  const payload = W._agcbCollectManagers();
  check(Array.isArray(payload.dingtalk) && payload.dingtalk.length === 3,
    `E16 汇总提交 3 位管理者（实得 ${payload.dingtalk && payload.dingtalk.length}）`);
  check(payload.dingtalk.every((m) => m.peer_type === 'friend' && m.peer_id),
    'E17 汇总里带 peer_type / peer_id');
  check(payload.dingtalk.find((m) => m.peer_id === 'u1').peer_name === '张三',
    'E18 汇总时从联系人缓存补回 peer_name');

  // 关掉一个人
  W.agcbToggleMgr({ checked: false, closest: () => ({ dataset: { peer: 'u1' } }) }, null);
  check(!W._agcbMgr['dingtalk:u1'], 'E19 关掉单个管理者生效');
  const p2 = W._agcbCollectManagers();
  check(p2.dingtalk.length === 2 && !p2.dingtalk.some((m) => m.peer_id === 'u1'),
    'E20 关掉的人不再出现在提交名单里（全量覆盖语义正确）');

  // 刷新
  resetLogs();
  W.agcbRefresh();
  check(!!lastCall('fetch_dingtalk_contacts'), 'E21 刷新 → 重新拉取当前渠道成员');
  check(toasts.some((t) => t.includes('刷新')), 'E22 刷新给出即时反馈 toast');
  check(timers.includes(15000), 'E23 拉取挂了 15s 兜底超时（不会一直转圈）');

  resetLogs();
  W._agcbChan = '';
  W.agcbRefresh();
  check(calls.length === 0 && toasts.some((t) => t.includes('请先选择连接渠道')),
    'E24 没选渠道时刷新 → 只提示，不发请求');
}

// ------------------------------------------------------------------
// F：群聊 / 群消息排除出候选
// ------------------------------------------------------------------
section('F 群聊排除出候选');
{
  const CHAN = 'dingtalk';
  W._activationState = { activated: true };
  W._agcbChan = CHAN;
  W._agcbContacts = {}; W._agcbFetch = {}; W._agcbMgr = {}; W._agcbPicked = {}; W._agcbQ = ''; W._agcbChip = 'all';

  // F1 拉取回包过滤（后端故意把群也返回，因为老「连接管理」需要群）
  resetLogs();
  const hook = callbacks['fetch_dingtalk_contacts'];
  check(typeof hook === 'function' && hook.__agcbWrapped === true, 'F1 拉取命令已被包一层（wrap 生效）');
  hook({ ok: true, data: { ok: true, contacts: [
    { peer_id: 'u9', peer_name: '客户A', peer_type: 'friend' },
    { peer_id: 'g1', peer_name: '公司大群', peer_type: 'group' },
    { peer_id: '', peer_name: '坏数据', peer_type: 'friend' },
  ] } });
  const got = W._agcbContacts[CHAN] || [];
  check(got.length === 1 && got[0].peer_id === 'u9', `F2 回包里的群聊与空 id 被整条剔除（实得 ${JSON.stringify(got.map((c) => c.peer_id))}）`);
  check(!JSON.stringify(got).includes('公司大群'), 'F3 群聊名字不会进入候选池');
  check(!!lastCall('__原handler__:fetch_dingtalk_contacts'), 'F4 过滤的同时既有 handler 仍拿到完整原始数据');

  W.initAgcbGate();
  check(rowCount() === 1 && rowPeers()[0] === 'u9', 'F5 列表里只剩真成员');

  // F6 回退路径：模块自己还没拉过 → 用既有弹窗的全局缓存，同样要排除群
  W._agcbFetch[CHAN] = { fetched: false };
  _dingtalkContacts.length = 0;
  _dingtalkContacts.push(
    { peer_id: 'd1', peer_name: '丁成员', peer_type: 'friend' },
    { peer_id: 'dg', peer_name: '丁群', peer_type: 'group' },
  );
  W._agcbChan = CHAN;
  W._agcbQ = '';
  W.initAgcbGate();
  check(rowCount() === 1 && rowPeers()[0] === 'd1', `F7 回退缓存里的群聊被排除（实得 ${JSON.stringify(rowPeers())}）`);

  // F7 微信回退路径：type === 'group'
  W._agcbChan = 'wechat';
  W._agcbFetch.wechat = { fetched: false };
  wcfFriends.length = 0;
  wcfFriends.push(
    { id: 'wx1', name: '微信好友', type: 'friend' },
    { id: 'wxg', name: '微信群', type: 'group' },
  );
  W._agcbQ = '';
  W.initAgcbGate();
  check(rowCount() === 1 && rowPeers()[0] === 'wx1', `F8 微信回退缓存里的群（type=group）被排除（实得 ${JSON.stringify(rowPeers())}）`);

  // F9 企微回退路径
  W._agcbChan = 'wecom';
  W._agcbFetch.wecom = { fetched: false };
  _wecomContacts.length = 0;
  _wecomContacts.push(
    { peer_id: 'w1', peer_name: '企微成员', peer_type: 'friend' },
    { peer_id: 'wg', peer_name: '企微群', peer_type: 'group' },
  );
  W._agcbQ = '';
  W.initAgcbGate();
  check(rowCount() === 1 && rowPeers()[0] === 'w1', `F9 企微回退缓存里的群被排除（实得 ${JSON.stringify(rowPeers())}）`);
}

// ------------------------------------------------------------------
// G：切换智能体后必须重新回填管理者（缓存 bug 回归）
// ------------------------------------------------------------------
section('G 切智能体后重新回填管理者');
{
  const CHAN = 'dingtalk';
  const RESPOND = (bindings) => ({ ok: true, data: { channel: 'dingtalk', bindings, occupants: [] } });
  W._activationState = { activated: true };
  W._agcbOn = true;
  W._agcbMgr = {}; W._agcbPicked = {}; W._agcbSync = {}; W._agcbPending = null;
  W._agcbQ = ''; W._agcbChip = 'all';
  W._agcbFetch = {}; W._agcbContacts = {};
  W._agcbFetch[CHAN] = { fetched: true, loading: false, error: '' };
  W._agcbContacts[CHAN] = [
    { peer_id: 'p151', peer_name: '151******27', remark: '' },
    { peer_id: 'pLai', peer_name: '赖恒', remark: '' },
  ];
  const mgr151 = [{ peer_id: 'p151', peer_name: '151******27', is_manager: 1, enabled: 1 }];

  // --- A：进入面板 → 选钉钉 → 后端回报 151 是管理者 → 勾上 ---
  currentAgentId = 'agent-A';
  W.initAgcbGate();
  resetLogs();
  chanSelect.value = CHAN;
  W.agcbPickChannelSelect(chanSelect);
  // 选渠道即开拉；真实桥会把回包丢回同名 handler → 这里补齐这次「请求 → 回包」往返
  callbacks['fetch_dingtalk_contacts']({ ok: true, data: { ok: true, contacts: [
    { peer_id: 'p151', peer_name: '151******27', peer_type: 'friend' },
    { peer_id: 'pLai', peer_name: '赖恒', peer_type: 'friend' },
  ] } });
  const lbA = lastCall('list_channel_bindings');
  check(!!lbA && lbA.payload.agent_id === 'agent-A', 'G1 选渠道时以当前智能体 A 的身份读取管理者');
  callbacks['list_channel_bindings'](RESPOND(mgr151));
  check(!!W._agcbMgr['dingtalk:p151'], 'G2 A 的管理者回填成功（151 勾上）');
  check(rowCount() === 2, `G3 A 的名单列出 2 人（实得 ${rowCount()}）`);

  // --- 切到 B：标记必须整体重置，且必须重新读 B 的 ---
  currentAgentId = 'agent-B';
  resetLogs();
  W.initAgcbGate();
  check(!W._agcbMgr['dingtalk:p151'], 'G4 切到 B 后 A 的管理者标记被清掉（不会串到 B 身上）');
  const lbB = lastCall('list_channel_bindings');
  check(!!lbB && lbB.payload.agent_id === 'agent-B',
    `G5 切到 B 后自动重新读取 B 的管理者（实得 agent_id=${lbB && lbB.payload && lbB.payload.agent_id}）`);
  check(!!lbB && lbB.payload.channel === 'dingtalk', 'G6 重新读取用的还是「已选中」的那个渠道');
  callbacks['list_channel_bindings'](RESPOND([]));
  check(!W._agcbMgr['dingtalk:p151'], 'G7 B 没绑人 → 151 保持关（正确状态）');

  // --- 切回 A：必须把 A 的 151 重新勾回来（正是用户遇到的 bug）---
  currentAgentId = 'agent-A';
  resetLogs();
  W.initAgcbGate();
  const lbA2 = lastCall('list_channel_bindings');
  check(!!lbA2 && lbA2.payload.agent_id === 'agent-A', 'G8 切回 A 后重新读取 A 的管理者');
  callbacks['list_channel_bindings'](RESPOND(mgr151));
  check(!!W._agcbMgr['dingtalk:p151'], 'G9 切回 A → 151 重新勾上（缓存 bug 已修复）');
  check(W._agcbSync.dingtalk === 'agent-A', 'G10 回填后该渠道状态可信，允许保存提交');
  check(rowCount() === 2, `G11 切回 A 名单仍是 2 人（实得 ${rowCount()}）`);

  // --- 同一个智能体重复进入：不重复打扰后端 ---
  resetLogs();
  W.initAgcbGate();
  check(lastCall('list_channel_bindings') === null, 'G12 同一智能体重复进入不重复拉取（不做无谓请求）');
}

// ------------------------------------------------------------------
// H：渠道锁定（配置里选定连接渠道 → 整条前端交互链只认这一个渠道）
// ------------------------------------------------------------------
section('H 渠道锁定（一个智能体对一个渠道）');
{
  // 换算器已挂到 window 上，供「连接 / 历史」弹窗复用
  check(typeof W.agcbChanToApi === 'function' && W.agcbChanToApi('wechat') === 'wcf',
    `H1 面板键 → 后端号：wechat → wcf（实得 ${typeof W.agcbChanToApi === 'function' ? W.agcbChanToApi('wechat') : 'N/A'}）`);
  check(W.agcbChanToApi('wecom') === 'wecom' && W.agcbChanToApi('feishu') === 'feishu' && W.agcbChanToApi('dingtalk') === 'dingtalk',
    'H2 其余渠道键本身就是后端号 → 原样透传');
  check(typeof W.agcbChanFromApi === 'function' && W.agcbChanFromApi('wcf') === 'wechat',
    `H3 后端号 → 面板键：wcf → wechat（实得 ${typeof W.agcbChanFromApi === 'function' ? W.agcbChanFromApi('wcf') : 'N/A'}）`);
  check(W.agcbChanFromApi('dingtalk') === 'dingtalk', 'H4 反向换算：dingtalk 透传');
  check(W.agcbChanFromApi('') === '' && W.agcbChanFromApi('__unknown__') === '__unknown__',
    'H5 空值 / 未知渠道换算不炸（空进空出、未知原样返回）');

  // 真实页面里 _agents / _agentEditingId 是脚本级变量，模块按裸标识符读取；
  // 这里挂到 globalThis 上，模拟「另一个脚本声明的全局」这一解析路径。
  globalThis._agents = [];
  globalThis._agentEditingId = '';

  // 打开「配置 → 连接与绑定」= 调 initAgcbGate；下面每个 gate() 就是一次「进入面板」
  const gate = (agentId, rows, chan) => {
    currentAgentId = agentId;
    globalThis._agentEditingId = agentId;
    globalThis._agents = rows;
    if (chan !== undefined) W._agcbChan = chan;
    W._activationState = { activated: true };
    W._agcbOn = true;
    W.initAgcbGate();
  };

  // --- 老数据：channel 为空 → 不锁定，保持原样（不能把用户手动点的渠道抹掉）---
  gate('agent-L0', [{ id: 'agent-L0', channel: '' }], 'feishu');
  check(W._agcbChan === 'feishu',
    `H6 该智能体没配渠道 → 不锁定、不覆盖当前选择（实得「${W._agcbChan}」）`);

  // --- 配的是钉钉：面板渠道必须被锁到钉钉，且残留勾选/搜索词要清干净 ---
  W._agcbPicked = { 'wechat:someone': true };
  W._agcbQ = '赖';
  resetLogs();
  gate('agent-L1', [{ id: 'agent-L1', channel: 'dingtalk' }], 'wechat');
  check(W._agcbChan === 'dingtalk', `H7 配的是钉钉 → 面板渠道锁定为 dingtalk（实得「${W._agcbChan}」）`);
  check(Object.keys(W._agcbPicked).length === 0, 'H8 锁定换渠道 → 清掉上一个渠道的残留勾选');
  check(W._agcbQ === '', 'H9 锁定换渠道 → 清空搜索词');
  const lbL1 = lastCall('list_channel_bindings');
  check(!!lbL1 && lbL1.payload.channel === 'dingtalk' && lbL1.payload.agent_id === 'agent-L1',
    `H10 锁定后按钉钉渠道重新回填该智能体的管理者（实得 ${lbL1 && lbL1.payload && lbL1.payload.channel} / ${lbL1 && lbL1.payload && lbL1.payload.agent_id}）`);

  // --- 配的是微信：后端存的是 wcf，面板必须用 wechat 这把键 ---
  resetLogs();
  gate('agent-L2', [{ id: 'agent-L2', channel: 'wcf' }], 'dingtalk');
  check(W._agcbChan === 'wechat', `H11 配的是微信（后端 wcf）→ 面板渠道是 wechat（实得「${W._agcbChan}」）`);
  const lbL2 = lastCall('list_channel_bindings');
  check(!!lbL2 && lbL2.payload.channel === 'wcf',
    `H12 微信锁定回填时 channel 归一为 wcf（实得 ${lbL2 && lbL2.payload && lbL2.payload.channel}）`);

  // --- 同一个智能体、同一个渠道，重复进入面板 → 不重复打扰后端 ---
  resetLogs();
  gate('agent-L2', [{ id: 'agent-L2', channel: 'wcf' }]);
  check(lastCall('list_channel_bindings') === null, 'H13 同一智能体同一渠道重复进入 → 不重复拉取');

  // --- 换到另一个配了别的渠道的智能体 → 渠道必须跟着换（不串台）---
  resetLogs();
  gate('agent-L3', [{ id: 'agent-L2', channel: 'wcf' }, { id: 'agent-L3', channel: 'feishu' }]);
  check(W._agcbChan === 'feishu', `H14 换智能体 → 渠道跟着它自己配的走（实得「${W._agcbChan}」）`);
  const lbL3 = lastCall('list_channel_bindings');
  check(!!lbL3 && lbL3.payload.channel === 'feishu' && lbL3.payload.agent_id === 'agent-L3',
    'H15 换智能体后按新渠道 + 新 agent_id 重新回填');

  // --- 兜底：列表里查不到该智能体 / 根本没在编辑智能体 → 一律不锁定 ---
  gate('agent-X', [{ id: 'agent-L9', channel: 'feishu' }], 'oa');
  check(W._agcbChan === 'oa', `H16 列表里查不到该智能体 → 不锁定（实得「${W._agcbChan}」）`);

  currentAgentId = '';
  globalThis._agentEditingId = '';
  globalThis._agents = [{ id: 'agent-L1', channel: 'dingtalk' }];
  W._agcbChan = 'oa';
  W.initAgcbGate();
  check(W._agcbChan === 'oa', `H17 没有正在编辑的智能体 → 不锁定（实得「${W._agcbChan}」）`);

  delete globalThis._agents;
  delete globalThis._agentEditingId;
  W._agcbChan = 'dingtalk';
  W.initAgcbGate();
  check(W._agcbChan === 'dingtalk', 'H18 全局变量缺失时安全兜底（不锁定、不抛异常）');
}

// ------------------------------------------------------------------
console.log(`\n===== SUMMARY: ${total - failed}/${total} PASS =====`);
process.exit(failed === 0 ? 0 : 1);
