// 暨大学生助手前端：hash 路由 + 三页 render + FastAPI 后端调用。

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const ROUTES = ['chat', 'cards', 'history'];

function getRoute() {
  const hash = location.hash || '#/chat';
  return hash.replace(/^#\//, '').split('?')[0];
}

function getQueryParam(name) {
  const qs = location.hash.split('?')[1];
  if (!qs) return null;
  return new URLSearchParams(qs).get(name);
}

function setActiveNav() {
  const route = getRoute();
  $$('#nav a').forEach(a => a.classList.toggle('active', a.dataset.route === route));
}

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

async function render() {
  const view = $('#view');
  const route = getRoute();
  if (route === 'cards') return renderCards(view);
  if (route === 'history') return renderHistory(view);
  return renderChat(view);
}

// ============ 问答页 ============
function renderChat(view) {
  view.innerHTML = `
    <div class="ask-box">
      <div class="ask-row">
        <input class="ask-input" id="q-input" type="text" placeholder="试试问：怎么选课 / 算 GPA / 国奖条件" autocomplete="off" />
        <button class="btn" id="q-btn">问</button>
      </div>
      <div class="hint">按 <kbd>Ctrl</kbd>+<kbd>Enter</kbd> 发送</div>
    </div>
    <div class="examples" id="examples">
      <h3>试试这些问题：</h3>
      <div class="example-chips">
        <button class="chip" data-q="国奖申请条件是什么">国奖申请条件</button>
        <button class="chip" data-q="学生证丢了怎么补办">补办学生证</button>
        <button class="chip" data-q="期末考试什么时候">期末考试时间</button>
        <button class="chip" data-q="今天广州天气怎么样">超出范围的闲聊（拒答演示）</button>
      </div>
    </div>
    <div id="answer-area"></div>
  `;

  const input = $('#q-input');
  const btn = $('#q-btn');

  // 卡片页跳转过来时预填
  const preset = getQueryParam('q');
  if (preset) input.value = preset;

  btn.addEventListener('click', sendQuestion);
  input.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') sendQuestion();
  });
  input.focus();

  $$('.chip').forEach(c => {
    c.addEventListener('click', () => {
      input.value = c.dataset.q;
      input.focus();
    });
  });
}

async function sendQuestion() {
  const input = $('#q-input');
  const btn = $('#q-btn');
  const q = (input.value || '').trim();
  if (!q) return;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>思考中…';

  try {
    const data = await api('/api/chat', { method: 'POST', body: JSON.stringify({ question: q }) });
    $('#examples')?.remove();
    renderAnswer(q, data);
  } catch (e) {
    $('#answer-area').innerHTML = `<div class="global-banner error">网络出错：${escapeHtml(e.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '问';
  }
}

function renderAnswer(question, data) {
  const area = $('#answer-area');
  const isReject = data.route === 'reject';
  const isRetry = (data.round || 0) > 0;
  const refl = data.reflection;

  area.innerHTML = `
    <div class="answer-block">
      <div class="qa-q"><span class="tag">Q</span>${escapeHtml(question)}</div>
      <div class="qa-a ${isReject ? 'reject' : ''}">
        ${isReject ? '<span class="reject-tag">⛔ 超出服务范围</span>' : ''}
        ${escapeHtml(data.answer || '')}
      </div>
      ${data.tool_output ? `<div class="tool-box"><strong>📊 工具计算</strong>${escapeHtml(data.tool_output)}</div>` : ''}
      ${isRetry ? `<div class="retry-note">⚠ 第一次答案不满意，自动重写 ${data.round} 次后交付</div>` : ''}

      ${(data.matches || []).length > 0 ? `
        <details class="fold matches" open>
          <summary>引用来源（${data.matches.length} 条）</summary>
          ${data.matches.map((m, i) => renderMatch(m, i)).join('')}
        </details>
      ` : ''}

      <div class="trace">
        <div class="trace-line">
          <span>Route: <b>${escapeHtml(data.route || '?')}</b></span>
          <span>Round: <b>${data.round || 0}</b></span>
          <span>Latency: <b>${((data.latency_ms || 0) / 1000).toFixed(1)}s</b></span>
          <span>Reflection: <b class="${refl?.ok ? 'ok' : 'no'}">${
            refl ? (refl.ok ? '✓ ' + escapeHtml(refl.reason || '') : '✗ ' + escapeHtml(refl.reason || '')) : '-'
          }</b></span>
        </div>
        ${data.analysis && data.analysis !== data.answer
          ? `<div class="trace-draft"><b>反思前的草稿：</b><br>${escapeHtml(data.analysis)}</div>`
          : ''}
      </div>
    </div>
  `;

  $$('.match-head', area).forEach(head => {
    head.addEventListener('click', () => head.parentElement.classList.toggle('open'));
  });
}

function renderMatch(m) {
  const type = m.type || 'text';
  const badgeText = type === 'table' ? '表格' : type === 'figure' ? '图' : '正文';
  return `
    <div class="match">
      <div class="match-head">
        <span class="badge badge-${type}">${badgeText}</span>
        <span class="match-source">${escapeHtml(m.source || '')}</span>
        <span class="match-score">相似度 ${(m.score || 0).toFixed(2)}</span>
        <span class="match-toggle">展开</span>
      </div>
      <div class="match-body">
        <div class="match-content">${escapeHtml(m.content || '')}</div>
      </div>
    </div>
  `;
}

// ============ 卡片页 ============
async function renderCards(view) {
  view.innerHTML = `<div class="loading"><span class="spinner"></span>加载卡片…</div>`;
  try {
    const data = await api('/api/cards');
    if (!data.groups || data.groups.length === 0) {
      view.innerHTML = `<div class="empty">暂无服务卡片。</div>`;
      return;
    }
    view.innerHTML = data.groups.map(g => `
      <div class="section-title">${escapeHtml(g.name)}（${g.cards.length} 张）</div>
      <div class="card-grid">
        ${g.cards.map(renderCard).join('')}
      </div>
    `).join('');
    $$('[data-ask]', view).forEach(b => {
      b.addEventListener('click', () => {
        location.hash = '#/chat?q=' + encodeURIComponent(b.dataset.ask);
      });
    });
  } catch (e) {
    view.innerHTML = `<div class="global-banner error">加载失败：${escapeHtml(e.message)}</div>`;
  }
}

function renderCard(c) {
  return `
    <div class="card">
      <h4>${escapeHtml(c.title)}</h4>
      <p>${escapeHtml(c.desc || '')}</p>
      <div class="card-foot">
        <span class="card-id">${escapeHtml(c.id)}</span>
        <button class="btn btn-ghost" data-ask="${escapeHtml(c.sample_q || c.title)}">问它 →</button>
      </div>
    </div>
  `;
}

// ============ 历史页 ============
async function renderHistory(view) {
  view.innerHTML = `<div class="loading"><span class="spinner"></span>加载历史…</div>`;
  try {
    const rows = await api('/api/history?limit=50');
    if (!rows || rows.length === 0) {
      view.innerHTML = `<div class="empty">还没有问答记录，去<a href="#/chat">问答页</a>试试 →</div>`;
      return;
    }
    view.innerHTML = rows.map(renderHistoryItem).join('');
    $$('.history-head', view).forEach(head => {
      head.addEventListener('click', () => head.parentElement.classList.toggle('open'));
    });
    // 历史项里的 match 折叠
    $$('.history-body .match-head', view).forEach(head => {
      head.addEventListener('click', e => {
        e.stopPropagation();
        head.parentElement.classList.toggle('open');
      });
    });
  } catch (e) {
    view.innerHTML = `<div class="global-banner error">加载失败：${escapeHtml(e.message)}</div>`;
  }
}

function renderHistoryItem(row) {
  const pillClass = row.route === 'reject' ? 'pill reject' : 'pill';
  const refl = row.reflection;
  const reflHtml = refl
    ? (refl.ok ? `<span class="ok">✓ ${escapeHtml(refl.reason || '')}</span>` : `<span class="no">✗ ${escapeHtml(refl.reason || '')}</span>`)
    : '-';
  const matchesHtml = (row.matches || []).map(m => {
    const type = m.type || 'text';
    const badgeText = type === 'table' ? '表格' : type === 'figure' ? '图' : '正文';
    return `
      <div class="match">
        <div class="match-head">
          <span class="badge badge-${type}">${badgeText}</span>
          <span class="match-source">${escapeHtml(m.source || '')}</span>
          <span class="match-score">${(m.score || 0).toFixed(2)}</span>
        </div>
        <div class="match-body">
          <div class="match-content">${escapeHtml(m.content || '')}</div>
        </div>
      </div>
    `;
  }).join('');

  return `
    <div class="history-item">
      <div class="history-head">
        <div class="history-top">
          <span class="history-id">#${row.id}</span>
          <span class="history-time">${escapeHtml(row.created_at || '')}</span>
          <span class="${pillClass}">${escapeHtml(row.route || '?')}</span>
        </div>
        <div class="history-q">${escapeHtml(row.question || '')}</div>
        <div class="history-meta">
          <span>Round: ${row.round || 0}</span>
          <span>Latency: ${((row.latency_ms || 0) / 1000).toFixed(1)}s</span>
          <span>Reflection: ${reflHtml}</span>
        </div>
        <div class="history-preview">${escapeHtml((row.answer || '').slice(0, 80))}${(row.answer || '').length > 80 ? '…' : ''}</div>
      </div>
      <div class="history-body">
        <div class="qa-a">${escapeHtml(row.answer || '')}</div>
        ${row.tool_output ? `<div class="tool-box"><strong>📊 工具</strong>${escapeHtml(row.tool_output)}</div>` : ''}
        ${row.analysis && row.analysis !== row.answer
          ? `<div class="trace-draft"><b>反思前的草稿：</b><br>${escapeHtml(row.analysis)}</div>`
          : ''}
        ${matchesHtml ? `<div class="matches">${matchesHtml}</div>` : ''}
      </div>
    </div>
  `;
}

// ============ 启动 ============
window.addEventListener('hashchange', () => {
  setActiveNav();
  render();
});
window.addEventListener('DOMContentLoaded', () => {
  if (!location.hash) location.hash = '#/chat';
  setActiveNav();
  render();
});