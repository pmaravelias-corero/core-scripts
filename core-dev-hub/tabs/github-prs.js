// ── GitHub PRs tab ────────────────────────────────────────────────────────────

const ORG   = 'corero-eng';
const REPOS = [
  'corelet-ta',
  'corelet-ztac',
  'corelet-auth-mgmt',
  'corelet-user-settings',
  'corelet-tenant-provisioning',
  'corelet-audit-log-viewer',
  'corelet-shell',
];

// ── data fetching ─────────────────────────────────────────────────────────────

async function fetchPRsToReview() {
  const q = `is:pr review-requested:@me -label:dependencies state:open archived:false sort:updated-desc org:${ORG}`;
  const data = await gh('/search/issues', { q, per_page: 30 });
  return data.items;
}

async function fetchMyOpenPRs() {
  const q = `is:pr author:@me state:open archived:false sort:updated-desc org:${ORG}`;
  const data = await gh('/search/issues', { q, per_page: 30 });
  return data.items;
}

async function fetchDependabotPRs() {
  const all = [];
  await Promise.all(REPOS.map(async repo => {
    try {
      const prs = await gh(`/repos/${ORG}/${repo}/pulls`, { state: 'open', per_page: 50 });
      const depPRs = prs
        .filter(pr => pr.user?.login === 'dependabot[bot]' || pr.user?.login === 'dependabot')
        .map(pr => ({ ...pr, _repo: repo }));
      all.push(...depPRs);
    } catch { /* repo may not exist or no access */ }
  }));
  return all;
}

async function fetchCheckStatus(pr) {
  try {
    const [owner, repo] = pr.repository_url.split('/').slice(-2);
    const data = await gh(
      `/repos/${owner}/${repo}/commits/${pr.head?.sha || pr.pull_request?.url?.split('/').pop()}/check-runs`,
      { per_page: 1 }
    );
    if (!data.check_runs?.length) return null;
    const statuses = data.check_runs.map(r => r.conclusion || r.status);
    if (statuses.includes('failure') || statuses.includes('error')) return 'failure';
    if (statuses.includes('pending') || statuses.includes('in_progress')) return 'pending';
    return 'success';
  } catch { return null; }
}

// ── rendering ─────────────────────────────────────────────────────────────────

function prRow(pr, checkStatus) {
  const repo   = pr.repository_url?.split('/').pop() || pr._repo || '';
  const labels = (pr.labels || []).map(labelChip).join('');
  return `
    <li class="pr-item">
      <div class="pr-avatar">
        <img src="${pr.user?.avatar_url || ''}" alt="${pr.user?.login}" loading="lazy">
      </div>
      <div class="pr-body">
        <a class="pr-title" href="${pr.html_url}" target="_blank" title="${pr.title}">${pr.title}</a>
        <div class="pr-meta">
          <span class="pr-repo">${repo}</span>
          <span>#${pr.number}</span>
          <span>by ${pr.user?.login}</span>
          ${ageLabel(pr.created_at)}
        </div>
        ${labels ? `<div class="pr-labels">${labels}</div>` : ''}
      </div>
      <div class="pr-checks">${checkDot(checkStatus)}</div>
    </li>`;
}

let reviewGrouped = false;
let _reviewPRs = [], _reviewChecks = [];

function renderPRCard(id, icon, title, prs, checkStatuses) {
  const count    = prs.length;
  const badgeCls = count > 0 ? 'alert' : 'ok';
  const isReview = id === 'review-card';

  if (isReview) { _reviewPRs = prs; _reviewChecks = checkStatuses; }

  const groupBtn = isReview
    ? `<button class="secondary" style="font-size:11px;padding:4px 10px" onclick="toggleReviewGroup()">
        ${reviewGrouped ? 'Flat' : 'By repo'}
       </button>`
    : '';

  let body;
  if (count === 0) {
    body = `<div class="state-box"><div class="icon">✅</div>All clear</div>`;
  } else if (isReview && reviewGrouped) {
    const byRepo = {};
    prs.forEach((pr, i) => {
      const repo = pr.repository_url?.split('/').pop() || '?';
      if (!byRepo[repo]) byRepo[repo] = [];
      byRepo[repo].push({ pr, i });
    });
    body = Object.entries(byRepo).map(([repo, items]) => `
      <div class="dep-group">
        <div class="dep-group-header" onclick="toggleGroup(this)">
          <span class="dep-group-name">${repo}</span>
          <span class="dep-group-count">${items.length} PR${items.length > 1 ? 's' : ''} ▸</span>
        </div>
        <div class="dep-group-body">
          <ul class="pr-list">${items.map(({ pr, i }) => prRow(pr, checkStatuses[i])).join('')}</ul>
        </div>
      </div>`).join('');
  } else {
    body = `<ul class="pr-list">${prs.map((pr, i) => prRow(pr, checkStatuses[i])).join('')}</ul>`;
  }

  document.getElementById(id).innerHTML = `
    <div class="card-header">
      <div class="card-title"><span class="icon">${icon}</span>${title}</div>
      <div style="display:flex;align-items:center;gap:8px">
        ${groupBtn}
        <span class="badge ${badgeCls}">${count}</span>
      </div>
    </div>
    ${body}`;
}

function toggleReviewGroup() {
  reviewGrouped = !reviewGrouped;
  renderPRCard('review-card', '👀', 'PRs to Review', _reviewPRs, _reviewChecks);
}

let depGrouped = true;
let _depPRs = [];

function depItem(pr) {
  const m       = pr.title.match(/bump (.+?) from ([\d.]+) to ([\d.]+)/i);
  const name    = m ? m[1] : pr.title;
  const fromVer = m ? m[2] : '';
  const toVer   = m ? m[3] : '';
  return `
    <div class="dep-item">
      <span class="dep-name">${name}</span>
      <div style="display:flex;align-items:center;gap:10px">
        ${fromVer
          ? `<span class="dep-bump"><span>${fromVer}</span><span class="arrow">→</span><span class="new-ver">${toVer}</span></span>`
          : ''}
        ${!depGrouped ? `<span class="pr-repo">${pr._repo}</span>` : ''}
        <a class="dep-link" href="${pr.html_url}" target="_blank">#${pr.number}</a>
      </div>
    </div>`;
}

function renderDependabot(prs) {
  if (prs) _depPRs = prs;
  const el    = document.getElementById('depbot-card');
  const count = _depPRs.length;

  if (count === 0) {
    el.innerHTML = `
      <div class="card-header">
        <div class="card-title"><span class="icon">🤖</span>Dependabot</div>
        <span class="badge ok">0</span>
      </div>
      <div class="state-box"><div class="icon">✅</div>No pending bumps</div>`;
    return;
  }

  const groupBtn = `<button class="secondary" style="font-size:11px;padding:4px 10px" onclick="toggleDepGroup()">
    ${depGrouped ? 'Flat' : 'By repo'}
  </button>`;

  let body;
  if (depGrouped) {
    const byRepo = {};
    _depPRs.forEach(pr => {
      if (!byRepo[pr._repo]) byRepo[pr._repo] = [];
      byRepo[pr._repo].push(pr);
    });
    body = Object.entries(byRepo).map(([repo, rprs]) => `
      <div class="dep-group">
        <div class="dep-group-header" onclick="toggleGroup(this)">
          <span class="dep-group-name">${repo}</span>
          <span class="dep-group-count">${rprs.length} bump${rprs.length > 1 ? 's' : ''} ▸</span>
        </div>
        <div class="dep-group-body">${rprs.map(depItem).join('')}</div>
      </div>`).join('');
  } else {
    body = `<div>${_depPRs.map(depItem).join('')}</div>`;
  }

  el.innerHTML = `
    <div class="card-header">
      <div class="card-title"><span class="icon">🤖</span>Dependabot</div>
      <div style="display:flex;align-items:center;gap:8px">
        ${groupBtn}
        <span class="badge ${count > 5 ? 'alert' : ''}">${count}</span>
      </div>
    </div>
    ${body}`;
}

function toggleDepGroup() {
  depGrouped = !depGrouped;
  renderDependabot(null);
}

function toggleGroup(header) {
  const body = header.nextElementSibling;
  const isOpen = body.classList.toggle('open');
  header.querySelector('.dep-group-count').textContent =
    header.querySelector('.dep-group-count').textContent
      .replace(isOpen ? '▸' : '▾', isOpen ? '▾' : '▸');
}

// ── loader ────────────────────────────────────────────────────────────────────

async function loadGithubPRs() {
  const btn = document.getElementById('refresh-btn');
  btn.disabled = true;
  btn.textContent = 'Loading…';

  document.getElementById('github-prs-grid').innerHTML = `
    <div class="card" id="my-prs-card"></div>
    <div class="card" id="review-card"></div>
    <div class="card col-full" id="depbot-card"></div>`;

  loadingCard('my-prs-card', '🔀', 'My Open PRs');
  loadingCard('review-card',  '👀', 'PRs to Review');
  loadingCard('depbot-card',  '🤖', 'Dependabot');

  const [reviewPRs, myPRs, depPRs] = await Promise.all([
    fetchPRsToReview() .catch(e => { errorCard('review-card',  '👀', 'PRs to Review', e); return null; }),
    fetchMyOpenPRs()   .catch(e => { errorCard('my-prs-card', '🔀', 'My Open PRs',   e); return null; }),
    fetchDependabotPRs().catch(e => { errorCard('depbot-card', '🤖', 'Dependabot',   e); return null; }),
  ]);

  if (reviewPRs) {
    const checks = await Promise.all(reviewPRs.map(fetchCheckStatus));
    renderPRCard('review-card', '👀', 'PRs to Review', reviewPRs, checks);
  }
  if (myPRs) {
    const checks = await Promise.all(myPRs.map(fetchCheckStatus));
    renderPRCard('my-prs-card', '🔀', 'My Open PRs', myPRs, checks);
  }
  if (depPRs) renderDependabot(depPRs);

  document.getElementById('last-refresh').textContent =
    `Last refreshed ${new Date().toLocaleTimeString()}`;

  btn.disabled = false;
  btn.textContent = 'Refresh';

  const t = document.getElementById('token-input').value.trim();
  if (t) localStorage.setItem('gh_token', t);
}

registerTab('github-prs', loadGithubPRs);
