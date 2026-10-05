// ApplyPilot Live Dashboard - Dynamic Real-Time Frontend Logic

(function () {
  'use strict';

  // State Management
  const state = {
    profile: 'golang',
    refreshRate: 2000,
    timer: null,
    stats: null,
    liveStatus: null,
    allJobs: [],
    appliedJobs: [],
    selectedScoreFilter: null,
    searchKeyword: '',
    stageFilter: 'all',
    siteFilter: 'all',
    minScoreFilter: '',
    currentTab: 'tab-applied',
    activeResumeFile: null,
  };

  // DOM Elements
  const el = {
    profileSelect: document.getElementById('profileSelect'),
    refreshRateSelect: document.getElementById('refreshRateSelect'),
    btnManualRefresh: document.getElementById('btnManualRefresh'),
    livePill: document.getElementById('livePill'),
    liveStatusText: document.getElementById('liveStatusText'),

    // Live activity banner
    processStatusBadge: document.getElementById('processStatusBadge'),
    activeProcessTitle: document.getElementById('activeProcessTitle'),
    activityElapsed: document.getElementById('activityElapsed'),
    activityPid: document.getElementById('activityPid'),
    activeStageVal: document.getElementById('activeStageVal'),
    activeQueriesVal: document.getElementById('activeQueriesVal'),
    activeRegionsVal: document.getElementById('activeRegionsVal'),
    latestEventVal: document.getElementById('latestEventVal'),

    // KPI cards
    kpiDiscovered: document.getElementById('kpiDiscovered'),
    kpiEnrichedSub: document.getElementById('kpiEnrichedSub'),
    kpiScored: document.getElementById('kpiScored'),
    kpiAvgScoreSub: document.getElementById('kpiAvgScoreSub'),
    kpiTailored: document.getElementById('kpiTailored'),
    kpiPendingTailorSub: document.getElementById('kpiPendingTailorSub'),
    kpiReady: document.getElementById('kpiReady'),
    kpiApplied: document.getElementById('kpiApplied'),
    kpiAppliedSub: document.getElementById('kpiAppliedSub'),

    // Analytics
    scoreBarsContainer: document.getElementById('scoreBarsContainer'),
    sourcesList: document.getElementById('sourcesList'),
    totalSitesCount: document.getElementById('totalSitesCount'),

    // Tabs
    tabBtns: document.querySelectorAll('.tab-btn'),
    tabPanes: document.querySelectorAll('.tab-pane'),
    tabAppliedCount: document.getElementById('tabAppliedCount'),
    tabAllJobsCount: document.getElementById('tabAllJobsCount'),

    // Applied jobs view
    appliedJobsGrid: document.getElementById('appliedJobsGrid'),
    appliedSearchInput: document.getElementById('appliedSearchInput'),
    appliedFilterBtns: document.querySelectorAll('#tab-applied .filter-group button'),

    // All jobs view
    jobsTableBody: document.getElementById('jobsTableBody'),
    jobsSearchInput: document.getElementById('jobsSearchInput'),
    filterStageSelect: document.getElementById('filterStageSelect'),
    filterSiteSelect: document.getElementById('filterSiteSelect'),
    filterMinScoreSelect: document.getElementById('filterMinScoreSelect'),

    // Live stream & processes
    runningProcessList: document.getElementById('runningProcessList'),
    recentTailoredList: document.getElementById('recentTailoredList'),
    eventStreamLog: document.getElementById('eventStreamLog'),
    btnClearStream: document.getElementById('btnClearStream'),

    // Config tab
    configQueryList: document.getElementById('configQueryList'),
    configLocationList: document.getElementById('configLocationList'),

    // Modals
    resumeModal: document.getElementById('resumeModal'),
    btnCloseResumeModal: document.getElementById('btnCloseResumeModal'),
    modalResumeTitle: document.getElementById('modalResumeTitle'),
    modalResumeFilename: document.getElementById('modalResumeFilename'),
    resumeFormattedContent: document.getElementById('resumeFormattedContent'),
    resumeRawContent: document.getElementById('resumeRawContent'),
    resumeReportContent: document.getElementById('resumeReportContent'),
    btnDownloadTxt: document.getElementById('btnDownloadTxt'),
    btnDownloadMd: document.getElementById('btnDownloadMd'),
    btnDownloadPdf: document.getElementById('btnDownloadPdf'),

    jobModal: document.getElementById('jobModal'),
    btnCloseJobModal: document.getElementById('btnCloseJobModal'),
    modalJobScore: document.getElementById('modalJobScore'),
    modalJobTitle: document.getElementById('modalJobTitle'),
    modalJobMeta: document.getElementById('modalJobMeta'),
    modalJobSite: document.getElementById('modalJobSite'),
    modalJobSalary: document.getElementById('modalJobSalary'),
    modalJobDiscovered: document.getElementById('modalJobDiscovered'),
    modalJobAppliedStatus: document.getElementById('modalJobAppliedStatus'),
    modalJobReasoning: document.getElementById('modalJobReasoning'),
    modalJobDescription: document.getElementById('modalJobDescription'),
    modalJobApplyBtn: document.getElementById('modalJobApplyBtn'),
  };

  // ── Network Helpers ──────────────────────────────────────────────
  async function fetchAPI(endpoint, params = {}) {
    const query = new URLSearchParams({ profile: state.profile, ...params }).toString();
    const url = `/api/${endpoint}?${query}`;
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn(`Error fetching ${url}:`, err);
      return null;
    }
  }

  // ── Core Refresh Cycle ──────────────────────────────────────────
  async function refreshData() {
    try {
      // 1. Fetch Stats & Live Status concurrently
      const [statsData, liveData] = await Promise.all([
        fetchAPI('stats'),
        fetchAPI('live-status'),
      ]);

      if (statsData) {
        state.stats = statsData;
        renderKPIs(statsData);
        renderScoreDistribution(statsData.score_distribution);
        renderSources(statsData.sites);
        updateSiteSelect(statsData.sites);
      }

      if (liveData) {
        state.liveStatus = liveData;
        renderLiveBanner(liveData);
        renderLiveStream(liveData);
      }

      // 2. Fetch Jobs data for views
      await fetchJobsData();
    } catch (e) {
      console.error('Refresh loop failed:', e);
    }
  }

  async function fetchJobsData() {
    // Fetch all jobs for table
    const jobsResp = await fetchAPI('jobs', {
      stage: state.stageFilter,
      site: state.siteFilter,
      min_score: state.selectedScoreFilter !== null ? state.selectedScoreFilter : state.minScoreFilter,
      search: state.searchKeyword,
      limit: 150,
    });

    if (jobsResp && jobsResp.jobs) {
      state.allJobs = jobsResp.jobs;
      renderJobsTable(jobsResp.jobs);
      renderAppliedGrid(jobsResp.jobs);
      el.tabAllJobsCount.textContent = jobsResp.total;
    }
  }

  // ── Render KPIs ─────────────────────────────────────────────────
  function renderKPIs(s) {
    el.kpiDiscovered.textContent = s.total || 0;
    el.kpiEnrichedSub.textContent = `${s.with_description || 0} enriched full details`;

    el.kpiScored.textContent = s.scored || 0;
    el.kpiAvgScoreSub.textContent = `Avg Score: ${s.avg_score || 0} / 10`;

    el.kpiTailored.textContent = s.tailored || 0;
    el.kpiPendingTailorSub.textContent = `${s.pending_tailor_7 || 0} high-fit ready for tailoring`;

    el.kpiReady.textContent = s.ready_to_apply || 0;

    el.kpiApplied.textContent = s.applied || 0;
    el.kpiAppliedSub.textContent = s.applied > 0 ? `${s.applied} applications submitted` : 'Pending auto-apply';
  }

  // ── Render Live Banner ──────────────────────────────────────────
  function renderLiveBanner(live) {
    const isRunning = live.is_active && live.running_tasks.length > 0;
    const act = live.activity || {};

    if (isRunning) {
      const topTask = live.running_tasks[0];
      el.processStatusBadge.className = 'badge badge-pulse text-emerald';
      el.processStatusBadge.textContent = '● ACTIVE PIPELINE RUNNING';
      el.activeProcessTitle.textContent = `ApplyPilot Engine: Stage [${topTask.stage.toUpperCase()}]`;
      el.activityElapsed.textContent = `Runtime: ${topTask.elapsed}`;
      el.activityPid.textContent = `PID: ${topTask.pid} (CPU: ${topTask.cpu}%)`;
      el.activeStageVal.textContent = `Stage: ${topTask.stage} (${topTask.command.slice(0, 80)}...)`;
    } else {
      el.processStatusBadge.className = 'badge badge-pulse';
      el.processStatusBadge.textContent = 'STANDBY / IDLE';
      el.activeProcessTitle.textContent = 'Ready for Next Pipeline Run';
      el.activityElapsed.textContent = 'Engine Status: Idle';
      el.activityPid.textContent = 'PID: None';
      el.activeStageVal.textContent = 'All background tasks completed';
    }

    if (act.searches_configured && act.searches_configured.length > 0) {
      el.activeQueriesVal.textContent = act.searches_configured.slice(0, 3).map(q => `"${q}"`).join(', ');
      renderConfigTab(act.searches_configured, act.locations_configured);
    }

    if (act.locations_configured && act.locations_configured.length > 0) {
      el.activeRegionsVal.textContent = act.locations_configured.slice(0, 4).join(', ');
    }

    if (act.latest_event) {
      el.latestEventVal.textContent = act.latest_event;
    } else if (act.active_log_line) {
      el.latestEventVal.textContent = act.active_log_line;
    }
  }

  // ── Render Score Distribution ───────────────────────────────────
  function renderScoreDistribution(dist) {
    if (!dist) return;
    const scores = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0];
    const counts = scores.map(sc => dist[sc] || 0);
    const maxVal = Math.max(...counts, 1);

    let html = '';
    scores.forEach(s => {
      const count = dist[s] || 0;
      const pct = Math.round((count / maxVal) * 100);
      const isSelected = state.selectedScoreFilter === s;
      html += `
        <div class="score-bar-row ${isSelected ? 'selected' : ''}" data-score="${s}" title="Click to filter score ${s}">
          <span class="score-bar-pill score-${s}">${s}</span>
          <div class="bar-track">
            <div class="bar-fill score-${s}" style="width: ${pct}%;"></div>
          </div>
          <span class="score-count">${count}</span>
        </div>
      `;
    });

    el.scoreBarsContainer.innerHTML = html;

    // Attach click events
    el.scoreBarsContainer.querySelectorAll('.score-bar-row').forEach(row => {
      row.addEventListener('click', () => {
        const sc = parseInt(row.getAttribute('data-score'), 10);
        if (state.selectedScoreFilter === sc) {
          state.selectedScoreFilter = null; // toggle off
        } else {
          state.selectedScoreFilter = sc;
        }
        fetchJobsData();
      });
    });
  }

  // ── Render Sources ──────────────────────────────────────────────
  function renderSources(sites) {
    if (!sites || sites.length === 0) return;
    el.totalSitesCount.textContent = `${sites.length} portals`;

    let html = '';
    sites.forEach(s => {
      html += `
        <div class="source-item">
          <div class="source-name">${escapeHTML(s.site)}</div>
          <div class="source-stats">
            <span class="text-cyan">${s.total} jobs</span>
            <span class="text-emerald" title="Score 7+">${s.high_fit} high-fit</span>
            <span class="text-dim">Avg: ${s.avg_score}</span>
          </div>
        </div>
      `;
    });
    el.sourcesList.innerHTML = html;
  }

  function updateSiteSelect(sites) {
    if (!sites) return;
    const currentVal = el.filterSiteSelect.value;
    let html = '<option value="all">All Sites / Sources</option>';
    sites.forEach(s => {
      html += `<option value="${escapeHTML(s.site)}">${escapeHTML(s.site)} (${s.total})</option>`;
    });
    el.filterSiteSelect.innerHTML = html;
    el.filterSiteSelect.value = currentVal;
  }

  // ── Render Applied & Tailored Grid ──────────────────────────────
  function renderAppliedGrid(jobs) {
    // Show jobs that are applied or have tailored resumes or score >= 7
    const appliedList = jobs.filter(j => 
      j.applied_at || j.apply_status || j.tailored_resume_path || j.tailored_filename || j.fit_score >= 7
    );

    el.tabAppliedCount.textContent = appliedList.length;

    if (appliedList.length === 0) {
      el.appliedJobsGrid.innerHTML = `
        <div class="loading-state">
          <p>No applied jobs or tailored resumes generated yet for this filter.</p>
        </div>
      `;
      return;
    }

    let html = '';
    appliedList.forEach(job => {
      const score = job.fit_score !== null ? job.fit_score : '-';
      const isApplied = !!job.applied_at || (job.apply_status === 'applied');
      const hasTailored = !!job.tailored_filename || !!job.tailored_resume_path;

      let badgeClass = 'pending';
      let badgeText = 'Tailoring Eligible';
      if (isApplied) {
        badgeClass = 'applied';
        badgeText = 'Applied';
      } else if (hasTailored) {
        badgeClass = 'ready';
        badgeText = 'Resume Tailored';
      }

      const tailoredFile = job.tailored_filename || (job.tailored_resume_path ? job.tailored_resume_path.split('/').pop() : null);

      html += `
        <div class="applied-job-card">
          <div class="card-top-badges">
            <span class="applied-status-badge ${badgeClass}">${badgeText}</span>
            <div class="score-badge score-${score}">${score}</div>
          </div>

          <h3 class="job-card-title">${escapeHTML(job.title)}</h3>
          <div class="job-card-meta">
            <strong>${escapeHTML(job.site || 'Direct')}</strong> &bull;
            <span>${escapeHTML(job.location || 'Remote')}</span>
          </div>

          ${tailoredFile ? `
            <div class="tailored-file-box">
              <span class="tailored-file-name" title="${tailoredFile}">📄 ${tailoredFile}</span>
            </div>
          ` : `
            <div class="tailored-file-box" style="opacity: 0.6;">
              <span class="tailored-file-name">⏳ Pending Resume Tailoring</span>
            </div>
          `}

          <div class="card-actions">
            ${tailoredFile ? `
              <button class="btn btn-primary btn-sm btn-view-resume" data-file="${tailoredFile}" data-title="${escapeHTML(job.title)}">
                View Tailored Resume
              </button>
              <a href="/api/download-resume?file=${encodeURIComponent(tailoredFile)}&profile=${state.profile}&format=pdf" target="_blank" class="btn btn-secondary btn-sm" title="Print or Save PDF">
                PDF
              </a>
            ` : ''}
            <button class="btn btn-secondary btn-sm btn-view-job" data-url="${encodeURIComponent(job.url)}">
              Job Info
            </button>
          </div>
        </div>
      `;
    });

    el.appliedJobsGrid.innerHTML = html;

    // Attach actions
    el.appliedJobsGrid.querySelectorAll('.btn-view-resume').forEach(btn => {
      btn.addEventListener('click', () => {
        openResumeModal(btn.getAttribute('data-file'), btn.getAttribute('data-title'));
      });
    });

    el.appliedJobsGrid.querySelectorAll('.btn-view-job').forEach(btn => {
      btn.addEventListener('click', () => {
        openJobModal(decodeURIComponent(btn.getAttribute('data-url')));
      });
    });
  }

  // ── Render Jobs Table ───────────────────────────────────────────
  function renderJobsTable(jobs) {
    if (jobs.length === 0) {
      el.jobsTableBody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 40px; color: var(--text-dim);">No jobs found matching criteria.</td></tr>`;
      return;
    }

    let html = '';
    jobs.forEach(job => {
      const score = job.fit_score !== null ? job.fit_score : '-';
      const tailoredFile = job.tailored_filename || (job.tailored_resume_path ? job.tailored_resume_path.split('/').pop() : null);

      let statusBadge = '<span class="applied-status-badge pending">Discovered</span>';
      if (job.applied_at) {
        statusBadge = '<span class="applied-status-badge applied">Applied</span>';
      } else if (tailoredFile) {
        statusBadge = '<span class="applied-status-badge ready">Tailored</span>';
      } else if (job.fit_score >= 7) {
        statusBadge = '<span class="applied-status-badge ready">High Fit</span>';
      }

      html += `
        <tr>
          <td><span class="score-bar-pill score-${score}">${score}</span></td>
          <td>
            <div class="job-title-cell">
              <span>${escapeHTML(job.title)}</span>
              <span class="company">${escapeHTML(job.site || '')}</span>
            </div>
          </td>
          <td>${escapeHTML(job.site || 'Direct')}</td>
          <td>${escapeHTML(job.location || 'Remote')}</td>
          <td>
            ${tailoredFile ? `
              <button class="btn btn-secondary btn-sm btn-view-resume" data-file="${tailoredFile}" data-title="${escapeHTML(job.title)}">
                📄 View Resume
              </button>
            ` : '<span class="text-dim">--</span>'}
          </td>
          <td>${statusBadge}</td>
          <td style="text-align: right;">
            <button class="btn btn-outline btn-sm btn-view-job" data-url="${encodeURIComponent(job.url)}">
              Details
            </button>
          </td>
        </tr>
      `;
    });

    el.jobsTableBody.innerHTML = html;

    el.jobsTableBody.querySelectorAll('.btn-view-resume').forEach(btn => {
      btn.addEventListener('click', () => {
        openResumeModal(btn.getAttribute('data-file'), btn.getAttribute('data-title'));
      });
    });

    el.jobsTableBody.querySelectorAll('.btn-view-job').forEach(btn => {
      btn.addEventListener('click', () => {
        openJobModal(decodeURIComponent(btn.getAttribute('data-url')));
      });
    });
  }

  // ── Render Live Stream & Processes ──────────────────────────────
  function renderLiveStream(live) {
    if (!live) return;

    // Running processes
    if (live.running_tasks && live.running_tasks.length > 0) {
      let procHtml = '';
      live.running_tasks.forEach(t => {
        procHtml += `
          <div class="process-item">
            <div style="display:flex; justify-content:space-between; margin-bottom: 4px;">
              <strong class="text-emerald">Stage: ${t.stage.toUpperCase()}</strong>
              <span class="mono">PID ${t.pid}</span>
            </div>
            <div style="font-size: 11px; color: var(--text-dim);">${escapeHTML(t.command)}</div>
            <div style="font-size: 11px; color: var(--color-cyan); margin-top: 4px;">Elapsed: ${t.elapsed} | CPU: ${t.cpu}%</div>
          </div>
        `;
      });
      el.runningProcessList.innerHTML = procHtml;
    } else {
      el.runningProcessList.innerHTML = `<p class="empty-text">No active background tasks running right now.</p>`;
    }

    // Recent files
    const act = live.activity || {};
    if (act.recent_tailored && act.recent_tailored.length > 0) {
      let fHtml = '';
      act.recent_tailored.forEach(f => {
        fHtml += `
          <div class="recent-file-item">
            <span class="mono" style="color: #38bdf8;">${f.name}</span>
            <span class="mono text-dim">${f.size} B</span>
          </div>
        `;
      });
      el.recentTailoredList.innerHTML = fHtml;
    }

    // Telemetry log stream line
    if (act.latest_event && act.latest_event !== state.lastLoggedEvent) {
      state.lastLoggedEvent = act.latest_event;
      appendLog(act.latest_event, 'info');
    }
    if (act.active_log_line && act.active_log_line !== state.lastLoggedLog) {
      state.lastLoggedLog = act.active_log_line;
      appendLog(act.active_log_line, 'system');
    }
  }

  function appendLog(msg, type = 'info') {
    const timeStr = new Date().toLocaleTimeString();
    const line = document.createElement('div');
    line.className = `log-line ${type}`;
    line.textContent = `[${timeStr}] ${msg}`;
    el.eventStreamLog.appendChild(line);
    el.eventStreamLog.scrollTop = el.eventStreamLog.scrollHeight;
  }

  // ── Config Tab ──────────────────────────────────────────────────
  function renderConfigTab(queries, locations) {
    if (queries && queries.length > 0) {
      el.configQueryList.innerHTML = queries.map(q => `<li><strong>${escapeHTML(q)}</strong></li>`).join('');
    }
    if (locations && locations.length > 0) {
      el.configLocationList.innerHTML = locations.map(l => `<li>${escapeHTML(l)}</li>`).join('');
    }
  }

  // ── Modals: Resume & Job Details ────────────────────────────────
  async function openResumeModal(filename, jobTitle) {
    state.activeResumeFile = filename;
    el.modalResumeTitle.textContent = jobTitle || 'Tailored Resume';
    el.modalResumeFilename.textContent = filename;

    // Set download URLs
    const baseDownload = `/api/download-resume?file=${encodeURIComponent(filename)}&profile=${state.profile}`;
    el.btnDownloadTxt.href = `${baseDownload}&format=txt`;
    el.btnDownloadMd.href = `${baseDownload}&format=md`;
    el.btnDownloadPdf.href = `${baseDownload}&format=pdf`;

    el.resumeFormattedContent.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Loading tailored resume...</p></div>`;
    el.resumeModal.classList.add('open');

    const data = await fetchAPI('resume', { file: filename });
    if (!data || !data.parsed) {
      el.resumeFormattedContent.innerHTML = `<p class="text-rose">Failed to load resume file.</p>`;
      return;
    }

    const p = data.parsed;

    // Formatted ATS Resume HTML
    let formattedHtml = `
      <h1>${escapeHTML(p.name)}</h1>
      <div class="subtitle">${escapeHTML(p.title)}</div>
      <div class="contact">${escapeHTML(p.contact)}</div>
    `;

    for (const [sec, text] of Object.entries(p.sections || {})) {
      formattedHtml += `
        <h2>${escapeHTML(sec)}</h2>
        <pre>${escapeHTML(text)}</pre>
      `;
    }

    el.resumeFormattedContent.innerHTML = formattedHtml;
    el.resumeRawContent.textContent = p.raw || '';

    // Report
    if (data.report) {
      el.resumeReportContent.innerHTML = `
        <pre class="raw-code">${escapeHTML(JSON.stringify(data.report, null, 2))}</pre>
      `;
    } else {
      el.resumeReportContent.innerHTML = `<p class="text-dim">No validator report JSON available for this file.</p>`;
    }
  }

  async function openJobModal(url) {
    el.modalJobTitle.textContent = 'Loading Job...';
    el.modalJobScore.textContent = '--';
    el.modalJobDescription.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Fetching full job description...</p></div>`;
    el.jobModal.classList.add('open');

    const job = await fetchAPI('job-detail', { url });
    if (!job) {
      el.modalJobTitle.textContent = 'Error Loading Job';
      return;
    }

    el.modalJobScore.textContent = job.fit_score !== null ? job.fit_score : '-';
    el.modalJobScore.className = `score-badge-large score-${job.fit_score || 0}`;
    el.modalJobTitle.textContent = job.title;
    el.modalJobMeta.textContent = `${job.site || 'Site'} • ${job.location || 'Location'}`;
    el.modalJobSite.textContent = job.site || 'Unknown';
    el.modalJobSalary.textContent = job.salary || 'Not specified';
    el.modalJobDiscovered.textContent = job.discovered_at || '--';
    el.modalJobAppliedStatus.textContent = job.applied_at ? `Applied on ${job.applied_at}` : 'Not applied';
    el.modalJobReasoning.textContent = job.score_reasoning || 'No scoring reasoning available.';
    el.modalJobDescription.innerHTML = `<pre style="font-family: inherit; white-space: pre-wrap; line-height: 1.6;">${escapeHTML(job.full_description || job.description || 'No description found.')}</pre>`;
    el.modalJobApplyBtn.href = job.application_url || job.url;
  }

  function escapeHTML(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g, tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;',
    }[tag] || tag));
  }

  // ── Event Handlers & Initialization ─────────────────────────────
  function setupEventListeners() {
    // Profile Switcher
    el.profileSelect.addEventListener('change', e => {
      state.profile = e.target.value;
      refreshData();
    });

    // Auto-refresh interval
    el.refreshRateSelect.addEventListener('change', e => {
      state.refreshRate = parseInt(e.target.value, 10);
      setupTimer();
    });

    el.btnManualRefresh.addEventListener('click', () => {
      refreshData();
    });

    // Tab buttons
    el.tabBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        el.tabBtns.forEach(b => b.classList.remove('active'));
        el.tabPanes.forEach(p => p.classList.remove('active'));

        btn.classList.add('active');
        const tabId = btn.getAttribute('data-tab');
        document.getElementById(tabId).classList.add('active');
        state.currentTab = tabId;
      });
    });

    // Modal subtabs
    document.querySelectorAll('.modal-tabs .subtab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.modal-tabs .subtab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.subtab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        const subId = `subtab-${btn.getAttribute('data-subtab')}`;
        document.getElementById(subId).classList.add('active');
      });
    });

    // Modal closers
    el.btnCloseResumeModal.addEventListener('click', () => el.resumeModal.classList.remove('open'));
    el.btnCloseJobModal.addEventListener('click', () => el.jobModal.classList.remove('open'));

    window.addEventListener('click', e => {
      if (e.target === el.resumeModal) el.resumeModal.classList.remove('open');
      if (e.target === el.jobModal) el.jobModal.classList.remove('open');
    });

    // Search and filters
    el.jobsSearchInput.addEventListener('input', e => {
      state.searchKeyword = e.target.value;
      fetchJobsData();
    });

    el.filterStageSelect.addEventListener('change', e => {
      state.stageFilter = e.target.value;
      fetchJobsData();
    });

    el.filterSiteSelect.addEventListener('change', e => {
      state.siteFilter = e.target.value;
      fetchJobsData();
    });

    el.filterMinScoreSelect.addEventListener('change', e => {
      state.minScoreFilter = e.target.value;
      state.selectedScoreFilter = null;
      fetchJobsData();
    });

    el.appliedSearchInput.addEventListener('input', e => {
      const q = e.target.value.toLowerCase();
      document.querySelectorAll('.applied-job-card').forEach(card => {
        const text = card.textContent.toLowerCase();
        card.style.display = text.includes(q) ? 'flex' : 'none';
      });
    });

    el.btnClearStream.addEventListener('click', () => {
      el.eventStreamLog.innerHTML = '<div class="log-line system">[SYSTEM] Log stream cleared.</div>';
    });
  }

  function setupTimer() {
    if (state.timer) clearInterval(state.timer);
    if (state.refreshRate > 0) {
      state.timer = setInterval(refreshData, state.refreshRate);
      el.livePill.style.opacity = '1';
      el.liveStatusText.textContent = 'LIVE MONITORING';
    } else {
      el.livePill.style.opacity = '0.5';
      el.liveStatusText.textContent = 'PAUSED';
    }
  }

  // Initialize
  setupEventListeners();
  refreshData();
  setupTimer();
})();
