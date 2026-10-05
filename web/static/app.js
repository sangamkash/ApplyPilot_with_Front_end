// ApplyPilot - Dynamic Multi-Profile Autonomous Frontend Logic

(function () {
  'use strict';

  // ── Global Application State ─────────────────────────────────────
  const state = {
    currentView: 'home', // 'home' | 'pipeline' | 'monitor'
    profile: 'golang',
    profilesList: [],
    stats: null,
    liveStatus: null,
    pipelineStatus: null,
    allJobs: [],
    appliedJobs: [],
    errorJobs: [],
    selectedScoreFilter: null,
    searchKeyword: '',
    stageFilter: 'all',
    siteFilter: 'all',
    minScoreFilter: '',
    currentTab: 'tab-applied',
    activeResumeFile: null,
    refreshRate: 2000,
    timer: null,
    pipelineTimer: null,
    isPipelineRunning: false,
    deleteTargetProfileId: null,
    profileModalMode: 'create', // 'create' | 'edit'
  };

  // ── DOM Element Cache ────────────────────────────────────────────
  const el = {
    // Navigation & Global Header
    brandLogoBtn: document.getElementById('brandLogoBtn'),
    navViews: document.getElementById('navViews'),
    navBtnHome: document.getElementById('navBtnHome'),
    navBtnPipeline: document.getElementById('navBtnPipeline'),
    navBtnMonitor: document.getElementById('navBtnMonitor'),
    navMonitorBadge: document.getElementById('navMonitorBadge'),
    globalProfileSelect: document.getElementById('globalProfileSelect'),
    btnHeaderNewProfile: document.getElementById('btnHeaderNewProfile'),
    refreshRateSelect: document.getElementById('refreshRateSelect'),
    btnManualRefresh: document.getElementById('btnManualRefresh'),
    livePill: document.getElementById('livePill'),
    liveStatusText: document.getElementById('liveStatusText'),

    // View Containers
    viewHome: document.getElementById('view-home'),
    viewPipeline: document.getElementById('view-pipeline'),
    viewMonitor: document.getElementById('view-monitor'),

    // View 1: Homepage Elements
    spotlightCard: document.getElementById('spotlightCard'),
    spotlightAvatar: document.getElementById('spotlightAvatar'),
    spotlightName: document.getElementById('spotlightName'),
    spotlightProfileId: document.getElementById('spotlightProfileId'),
    spotlightSourceBadge: document.getElementById('spotlightSourceBadge'),
    spotlightRole: document.getElementById('spotlightRole'),
    spotlightMeta: document.getElementById('spotlightMeta'),
    btnSpotlightContinue: document.getElementById('btnSpotlightContinue'),
    btnSpotlightOpenMonitor: document.getElementById('btnSpotlightOpenMonitor'),
    btnSpotlightEdit: document.getElementById('btnSpotlightEdit'),
    btnSpotlightDelete: document.getElementById('btnSpotlightDelete'),
    spotlightDiscoveredCount: document.getElementById('spotlightDiscoveredCount'),
    spotlightScoredCount: document.getElementById('spotlightScoredCount'),
    spotlightTailoredCount: document.getElementById('spotlightTailoredCount'),
    spotlightAppliedCount: document.getElementById('spotlightAppliedCount'),
    spotlightErrorsCount: document.getElementById('spotlightErrorsCount'),
    spotlightErrorCard: document.getElementById('spotlightErrorCard'),
    spotlightSkillsList: document.getElementById('spotlightSkillsList'),
    spotlightQueriesCount: document.getElementById('spotlightQueriesCount'),
    spotlightLocationsCount: document.getElementById('spotlightLocationsCount'),
    profilesCardsGrid: document.getElementById('profilesCardsGrid'),
    btnCreateNewProfileGrid: document.getElementById('btnCreateNewProfileGrid'),

    // View 2: Pipeline Elements
    linkPipelineHome: document.getElementById('linkPipelineHome'),
    pipelineBreadcrumbProfile: document.getElementById('pipelineBreadcrumbProfile'),
    pipelineTargetCandidate: document.getElementById('pipelineTargetCandidate'),
    pipelineTargetRole: document.getElementById('pipelineTargetRole'),
    btnPipelineOpenMonitor: document.getElementById('btnPipelineOpenMonitor'),
    gatewayJobCountText: document.getElementById('gatewayJobCountText'),
    nodeDiscoverCount: document.getElementById('nodeDiscoverCount'),
    nodeEnrichCount: document.getElementById('nodeEnrichCount'),
    nodeScoreCount: document.getElementById('nodeScoreCount'),
    nodeTailorCount: document.getElementById('nodeTailorCount'),
    nodeApplyCount: document.getElementById('nodeApplyCount'),
    nodePlayBtns: document.querySelectorAll('.btn-node-play'),
    btnPlayJobSearch: document.getElementById('btnPlayJobSearch'),
    btnPlayFullPipeline: document.getElementById('btnPlayFullPipeline'),
    btnStopExecution: document.getElementById('btnStopExecution'),
    paramWorkersSelect: document.getElementById('paramWorkersSelect'),
    paramMinScoreSelect: document.getElementById('paramMinScoreSelect'),
    paramDryRunCheckbox: document.getElementById('paramDryRunCheckbox'),
    telemetryStatusBadge: document.getElementById('telemetryStatusBadge'),
    telemetryStage: document.getElementById('telemetryStage'),
    telemetryPid: document.getElementById('telemetryPid'),
    telemetryElapsed: document.getElementById('telemetryElapsed'),
    telemetryCommand: document.getElementById('telemetryCommand'),
    telemetryDbSize: document.getElementById('telemetryDbSize'),
    pipelineTerminalBody: document.getElementById('pipelineTerminalBody'),
    terminalAutoScroll: document.getElementById('terminalAutoScroll'),
    btnClearTerminal: document.getElementById('btnClearTerminal'),

    // View 3: Monitor Elements
    linkMonitorHome: document.getElementById('linkMonitorHome'),
    linkMonitorPipeline: document.getElementById('linkMonitorPipeline'),
    btnMonitorBackToPipeline: document.getElementById('btnMonitorBackToPipeline'),
    monitorErrorBanner: document.getElementById('monitorErrorBanner'),
    bannerErrorCount: document.getElementById('bannerErrorCount'),
    btnBannerViewErrors: document.getElementById('btnBannerViewErrors'),
    kpiDiscovered: document.getElementById('kpiDiscovered'),
    kpiEnrichedSub: document.getElementById('kpiEnrichedSub'),
    kpiScored: document.getElementById('kpiScored'),
    kpiAvgScoreSub: document.getElementById('kpiAvgScoreSub'),
    kpiTailored: document.getElementById('kpiTailored'),
    kpiPendingTailorSub: document.getElementById('kpiPendingTailorSub'),
    kpiReady: document.getElementById('kpiReady'),
    kpiApplied: document.getElementById('kpiApplied'),
    kpiAppliedSub: document.getElementById('kpiAppliedSub'),
    kpiErrors: document.getElementById('kpiErrors'),
    kpiErrorsSub: document.getElementById('kpiErrorsSub'),
    kpiErrorCard: document.getElementById('kpiErrorCard'),
    scoreBarsContainer: document.getElementById('scoreBarsContainer'),
    sourcesList: document.getElementById('sourcesList'),
    totalSitesCount: document.getElementById('totalSitesCount'),
    tabBtns: document.querySelectorAll('.main-tabs .tab-btn'),
    tabPanes: document.querySelectorAll('#view-monitor .tab-pane'),
    tabAppliedCount: document.getElementById('tabAppliedCount'),
    tabErrorsCount: document.getElementById('tabErrorsCount'),
    tabAllJobsCount: document.getElementById('tabAllJobsCount'),
    tabBtnErrors: document.getElementById('tabBtnErrors'),
    appliedJobsGrid: document.getElementById('appliedJobsGrid'),
    appliedSearchInput: document.getElementById('appliedSearchInput'),
    appliedFilterBtns: document.querySelectorAll('#tab-applied .filter-group button'),
    errorBreakdownRow: document.getElementById('errorBreakdownRow'),
    errorsTableBody: document.getElementById('errorsTableBody'),
    jobsTableBody: document.getElementById('jobsTableBody'),
    jobsSearchInput: document.getElementById('jobsSearchInput'),
    filterStageSelect: document.getElementById('filterStageSelect'),
    filterSiteSelect: document.getElementById('filterSiteSelect'),
    filterMinScoreSelect: document.getElementById('filterMinScoreSelect'),
    runningProcessList: document.getElementById('runningProcessList'),
    recentTailoredList: document.getElementById('recentTailoredList'),
    eventStreamLog: document.getElementById('eventStreamLog'),
    btnClearStream: document.getElementById('btnClearStream'),
    configQueryList: document.getElementById('configQueryList'),
    configLocationList: document.getElementById('configLocationList'),

    // Profile Modal
    profileModal: document.getElementById('profileModal'),
    btnCloseProfileModal: document.getElementById('btnCloseProfileModal'),
    btnCancelProfileModal: document.getElementById('btnCancelProfileModal'),
    profileForm: document.getElementById('profileForm'),
    profileModalTitle: document.getElementById('profileModalTitle'),
    profileModalBadge: document.getElementById('profileModalBadge'),
    formProfileId: document.getElementById('formProfileId'),
    formFullName: document.getElementById('formFullName'),
    formPreferredName: document.getElementById('formPreferredName'),
    formEmail: document.getElementById('formEmail'),
    formPhone: document.getElementById('formPhone'),
    formLocation: document.getElementById('formLocation'),
    formLinkedin: document.getElementById('formLinkedin'),
    formGithub: document.getElementById('formGithub'),
    formTargetRole: document.getElementById('formTargetRole'),
    formYearsExp: document.getElementById('formYearsExp'),
    formEducation: document.getElementById('formEducation'),
    formCurrentTitle: document.getElementById('formCurrentTitle'),
    formCurrentCompany: document.getElementById('formCurrentCompany'),
    formSkillsLanguages: document.getElementById('formSkillsLanguages'),
    formSkillsFrameworks: document.getElementById('formSkillsFrameworks'),
    formSkillsDevops: document.getElementById('formSkillsDevops'),
    formSkillsDatabases: document.getElementById('formSkillsDatabases'),
    formSearchQueries: document.getElementById('formSearchQueries'),
    formSearchLocations: document.getElementById('formSearchLocations'),
    formResumeText: document.getElementById('formResumeText'),
    btnSaveProfile: document.getElementById('btnSaveProfile'),

    // Delete Modal
    deleteModal: document.getElementById('deleteModal'),
    btnCloseDeleteModal: document.getElementById('btnCloseDeleteModal'),
    btnCancelDelete: document.getElementById('btnCancelDelete'),
    btnConfirmDelete: document.getElementById('btnConfirmDelete'),
    deleteProfileTargetName: document.getElementById('deleteProfileTargetName'),

    // Resume Modal
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

    // Job Modal
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
    modalJobErrorBox: document.getElementById('modalJobErrorBox'),
    modalJobErrorMsg: document.getElementById('modalJobErrorMsg'),
    modalJobErrorAttempts: document.getElementById('modalJobErrorAttempts'),

    // Toast Container
    toastContainer: document.getElementById('toastContainer'),
  };

  // ── Toast Helper ─────────────────────────────────────────────────
  function showToast(message, type = 'success') {
    if (!el.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const icon = type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️';
    toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
    el.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(20px)';
      toast.style.transition = 'all 0.3s ease-out';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

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

  async function postAPI(endpoint, body = {}) {
    try {
      const res = await fetch(`/api/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      return data;
    } catch (err) {
      console.error(`Error posting to /api/${endpoint}:`, err);
      throw err;
    }
  }

  // ── View Switching & Client-Side Routing ─────────────────────────
  function switchView(viewName) {
    if (!['home', 'pipeline', 'monitor'].includes(viewName)) {
      viewName = 'home';
    }

    state.currentView = viewName;
    window.location.hash = viewName;

    // Toggle view visibility
    el.viewHome.classList.toggle('active', viewName === 'home');
    el.viewPipeline.classList.toggle('active', viewName === 'pipeline');
    el.viewMonitor.classList.toggle('active', viewName === 'monitor');

    // Update navigation buttons
    el.navBtnHome.classList.toggle('active', viewName === 'home');
    el.navBtnPipeline.classList.toggle('active', viewName === 'pipeline');
    el.navBtnMonitor.classList.toggle('active', viewName === 'monitor');

    window.scrollTo({ top: 0, behavior: 'smooth' });

    // Refresh context for target view
    if (viewName === 'home') {
      loadProfiles();
    } else if (viewName === 'pipeline') {
      updatePipelineViewHeader();
      checkPipelineStatus();
    } else if (viewName === 'monitor') {
      refreshData();
    }
  }

  function updatePipelineViewHeader() {
    const prof = state.profilesList.find((p) => p.id === state.profile);
    const candidateName = prof ? prof.candidate_name : 'Candidate';
    const targetRole = prof ? prof.target_role : state.profile.toUpperCase();

    el.pipelineBreadcrumbProfile.textContent = `Profile: ${prof ? prof.display_name : state.profile}`;
    el.pipelineTargetCandidate.textContent = candidateName;
    el.pipelineTargetRole.textContent = targetRole;

    const totalJobs = state.stats ? state.stats.total : 0;
    el.gatewayJobCountText.textContent = `${totalJobs} Jobs Discovered`;
  }

  // ── Profiles Management (CRUD & Spotlight) ───────────────────────
  async function loadProfiles() {
    const data = await fetchAPI('profiles');
    if (!data || !data.profiles) return;

    state.profilesList = data.profiles;

    // Ensure valid active profile
    if (!state.profilesList.some((p) => p.id === state.profile)) {
      state.profile = data.current || state.profilesList[0]?.id || 'golang';
    }

    // Populate dropdowns
    populateProfileDropdown(data.profiles);

    // Render spotlight card
    renderSpotlightCard();

    // Render profiles grid
    renderProfilesGrid(data.profiles);
  }

  function populateProfileDropdown(profiles) {
    const optionsHtml = profiles
      .map(
        (p) =>
          `<option value="${p.id}" ${p.id === state.profile ? 'selected' : ''}>${p.display_name || p.id}</option>`
      )
      .join('');

    el.globalProfileSelect.innerHTML = optionsHtml;
  }

  function renderSpotlightCard() {
    const prof = state.profilesList.find((p) => p.id === state.profile) || state.profilesList[0];
    if (!prof) return;

    const name = prof.candidate_name || 'Applicant';
    const initials = name
      .split(' ')
      .map((w) => w[0])
      .slice(0, 2)
      .join('')
      .toUpperCase();

    el.spotlightAvatar.textContent = initials || 'AP';
    el.spotlightName.textContent = name;
    el.spotlightProfileId.textContent = prof.id;
    el.spotlightSourceBadge.textContent = prof.is_system_default ? 'System Template' : 'Custom User';
    el.spotlightRole.textContent = prof.target_role || 'Target Role';
    el.spotlightMeta.textContent = `📍 ${prof.location || 'Remote'} • 📁 ${prof.path || ''}`;

    const st = prof.stats || {};
    el.spotlightDiscoveredCount.textContent = st.total_jobs || 0;
    el.spotlightScoredCount.textContent = st.scored || 0;
    el.spotlightTailoredCount.textContent = st.tailored || 0;
    el.spotlightAppliedCount.textContent = st.applied || 0;
    el.spotlightErrorsCount.textContent = st.apply_errors || 0;

    // Spotlight error card highlight
    if (st.apply_errors > 0) {
      el.spotlightErrorCard.style.borderColor = 'rgba(244, 63, 94, 0.6)';
    } else {
      el.spotlightErrorCard.style.borderColor = '';
    }

    // Skills tags
    const skills = prof.skills || [];
    if (skills.length > 0) {
      el.spotlightSkillsList.innerHTML = skills
        .map((s) => `<span class="skill-pill">${escapeHTML(s)}</span>`)
        .join('');
    } else {
      el.spotlightSkillsList.innerHTML = '<span class="text-dim">No skills configured</span>';
    }

    el.spotlightQueriesCount.textContent = `${prof.queries_count || 0} Search Queries`;
    el.spotlightLocationsCount.textContent = `${prof.locations_count || 0} Target Regions`;
  }

  function renderProfilesGrid(profiles) {
    if (!el.profilesCardsGrid) return;

    if (!profiles || profiles.length === 0) {
      el.profilesCardsGrid.innerHTML = `
        <div class="empty-state">
          <p>No profiles found. Create your first profile to begin!</p>
        </div>`;
      return;
    }

    el.profilesCardsGrid.innerHTML = profiles
      .map((p) => {
        const isActive = p.id === state.profile;
        const st = p.stats || {};
        return `
          <div class="profile-grid-card ${isActive ? 'active' : ''}" data-profile-id="${p.id}">
            <div class="profile-card-top">
              <div>
                <div class="profile-card-title">${escapeHTML(p.candidate_name || p.id)}</div>
                <div class="profile-card-role">${escapeHTML(p.target_role || 'General Role')}</div>
                <div class="profile-card-meta">📍 ${escapeHTML(p.location || 'Remote')}</div>
              </div>
              <span class="badge ${isActive ? 'badge-accent' : 'badge-dim'}">${p.id}</span>
            </div>

            <div class="profile-card-stats">
              <span><strong>${st.total_jobs || 0}</strong> discovered</span>
              <span><strong>${st.scored || 0}</strong> scored</span>
              <span><strong>${st.tailored || 0}</strong> tailored</span>
              ${st.apply_errors > 0 ? `<span class="text-rose"><strong>${st.apply_errors}</strong> errors</span>` : ''}
            </div>

            <div class="profile-card-actions">
              <button class="btn btn-sm ${isActive ? 'btn-primary' : 'btn-outline'} btn-select-profile" data-profile-id="${p.id}">
                ${isActive ? 'Active Profile' : 'Select Profile'}
              </button>
              <div class="card-action-btns">
                <button class="btn btn-sm btn-ghost btn-card-edit" data-profile-id="${p.id}" title="Edit Profile">
                  ✏️ Edit
                </button>
                <button class="btn btn-sm btn-danger-ghost btn-card-delete" data-profile-id="${p.id}" title="Delete Profile">
                  🗑️
                </button>
              </div>
            </div>
          </div>
        `;
      })
      .join('');

    // Attach card event listeners
    el.profilesCardsGrid.querySelectorAll('.profile-grid-card').forEach((card) => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('.btn-card-edit') || e.target.closest('.btn-card-delete')) return;
        const pid = card.getAttribute('data-profile-id');
        setActiveProfile(pid);
      });
    });

    el.profilesCardsGrid.querySelectorAll('.btn-card-edit').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const pid = btn.getAttribute('data-profile-id');
        openProfileModal('edit', pid);
      });
    });

    el.profilesCardsGrid.querySelectorAll('.btn-card-delete').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const pid = btn.getAttribute('data-profile-id');
        openDeleteModal(pid);
      });
    });
  }

  function setActiveProfile(profileId) {
    if (!profileId) return;
    state.profile = profileId;
    el.globalProfileSelect.value = profileId;

    renderSpotlightCard();
    renderProfilesGrid(state.profilesList);
    updatePipelineViewHeader();

    // Trigger data refresh for new profile
    refreshData();
    checkPipelineStatus();
    showToast(`Switched active profile to: ${profileId}`, 'info');
  }

  // ── Profile Creation & Editing Modal ─────────────────────────────
  async function openProfileModal(mode = 'create', profileId = null) {
    state.profileModalMode = mode;
    el.profileForm.reset();

    if (mode === 'create') {
      el.profileModalTitle.textContent = 'Create Candidate Profile';
      el.profileModalBadge.textContent = 'New Profile';
      el.formProfileId.disabled = false;
      el.formProfileId.value = '';
      el.formYearsExp.value = '3';
      el.formEducation.value = "Bachelor's Degree";
      el.formSearchQueries.value = 'software engineer\nfull stack developer';
      el.formSearchLocations.value = 'Remote\nBerlin, Germany\nUnited States';
      el.profileModal.classList.add('active');
    } else {
      // Edit Mode
      el.profileModalTitle.textContent = `Edit Profile: ${profileId}`;
      el.profileModalBadge.textContent = 'Edit Profile';
      el.formProfileId.value = profileId;
      el.formProfileId.disabled = true;

      // Fetch detail from backend
      const detail = await fetchAPI('profile-detail', { profile: profileId });
      if (!detail) {
        showToast('Could not load profile details', 'error');
        return;
      }

      const pJson = detail.profile_json || {};
      const personal = pJson.personal || {};
      const exp = pJson.experience || {};
      const skills = pJson.skills_boundary || {};

      el.formFullName.value = personal.full_name || '';
      el.formPreferredName.value = personal.preferred_name || '';
      el.formEmail.value = personal.email || '';
      el.formPhone.value = personal.phone || '';
      el.formLocation.value = [personal.city, personal.country].filter(Boolean).join(', ');
      el.formLinkedin.value = personal.linkedin_url || '';
      el.formGithub.value = personal.github_url || '';

      el.formTargetRole.value = exp.target_role || '';
      el.formYearsExp.value = exp.years_of_experience_total || '';
      el.formEducation.value = exp.education_level || '';
      el.formCurrentTitle.value = exp.current_job_title || '';
      el.formCurrentCompany.value = exp.current_company || '';

      el.formSkillsLanguages.value = (skills.languages || []).join(', ');
      el.formSkillsFrameworks.value = (skills.frameworks || []).join(', ');
      el.formSkillsDevops.value = (skills.devops || []).join(', ');
      el.formSkillsDatabases.value = (skills.databases || []).join(', ');

      // Parse queries and locations from YAML or text
      const queries = [];
      const locations = [];
      if (detail.searches_yaml) {
        const lines = detail.searches_yaml.split('\n');
        for (const line of lines) {
          const mQ = line.match(/query:\s*["']?([^"']+)["']?/);
          if (mQ) queries.push(mQ[1]);
          const mL = line.match(/location:\s*["']?([^"']+)["']?/);
          if (mL) locations.push(mL[1]);
        }
      }
      el.formSearchQueries.value = queries.join('\n');
      el.formSearchLocations.value = locations.join('\n');

      el.formResumeText.value = detail.resume_text || '';
      el.profileModal.classList.add('active');
    }
  }

  function closeProfileModal() {
    el.profileModal.classList.remove('active');
  }

  function generateSearchesYaml(queries, locations) {
    let yaml = 'queries:\n';
    queries.forEach((q) => {
      yaml += `  - query: "${q.replace(/"/g, '\\"')}"\n    tier: 1\n`;
    });
    yaml += '\nlocations:\n';
    locations.forEach((loc) => {
      yaml += `  - location: "${loc.replace(/"/g, '\\"')}"\n    remote: ${loc.toLowerCase().includes('remote')}\n`;
    });
    return yaml;
  }

  async function handleProfileFormSubmit(e) {
    e.preventDefault();

    const profileId = el.formProfileId.value.trim().toLowerCase();
    const fullName = el.formFullName.value.trim();
    const targetRole = el.formTargetRole.value.trim();
    const email = el.formEmail.value.trim();
    const resumeText = el.formResumeText.value.trim();

    if (!profileId || !fullName || !targetRole || !email || !resumeText) {
      showToast('Please fill in all required fields.', 'error');
      return;
    }

    const locParts = el.formLocation.value.split(',').map((s) => s.trim());
    const city = locParts[0] || '';
    const country = locParts[1] || '';

    const queries = el.formSearchQueries.value
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);

    const locations = el.formSearchLocations.value
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);

    const profileJson = {
      personal: {
        full_name: fullName,
        preferred_name: el.formPreferredName.value.trim() || fullName,
        email: email,
        phone: el.formPhone.value.trim(),
        city: city,
        country: country,
        linkedin_url: el.formLinkedin.value.trim(),
        github_url: el.formGithub.value.trim(),
      },
      work_authorization: {
        legally_authorized_to_work: 'Yes',
        require_sponsorship: 'No',
      },
      availability: {
        earliest_start_date: 'Immediately',
        available_for_full_time: 'Yes',
      },
      experience: {
        target_role: targetRole,
        years_of_experience_total: el.formYearsExp.value.trim() || '3',
        education_level: el.formEducation.value.trim() || "Bachelor's Degree",
        current_job_title: el.formCurrentTitle.value.trim(),
        current_company: el.formCurrentCompany.value.trim(),
      },
      skills_boundary: {
        languages: el.formSkillsLanguages.value
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        frameworks: el.formSkillsFrameworks.value
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        devops: el.formSkillsDevops.value
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        databases: el.formSkillsDatabases.value
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        tools: ['Git', 'Linux'],
      },
    };

    const searchesYaml = generateSearchesYaml(queries, locations);

    const payload = {
      id: profileId,
      profile_json: profileJson,
      searches_yaml: searchesYaml,
      resume_text: resumeText,
    };

    const endpoint =
      state.profileModalMode === 'create' ? 'profiles/create' : 'profiles/update';

    try {
      el.btnSaveProfile.disabled = true;
      el.btnSaveProfile.textContent = 'Saving Profile...';

      const res = await postAPI(endpoint, payload);
      showToast(res.message || 'Profile saved successfully!', 'success');
      closeProfileModal();

      // Refresh profiles list and activate
      await loadProfiles();
      setActiveProfile(profileId);
    } catch (err) {
      showToast(err.message || 'Failed to save profile', 'error');
    } finally {
      el.btnSaveProfile.disabled = false;
      el.btnSaveProfile.textContent = 'Save Candidate Profile';
    }
  }

  // ── Profile Deletion ─────────────────────────────────────────────
  function openDeleteModal(profileId) {
    state.deleteTargetProfileId = profileId;
    el.deleteProfileTargetName.textContent = profileId;
    el.deleteModal.classList.add('active');
  }

  function closeDeleteModal() {
    el.deleteModal.classList.remove('active');
    state.deleteTargetProfileId = null;
  }

  async function handleConfirmDelete() {
    const profileId = state.deleteTargetProfileId;
    if (!profileId) return;

    try {
      el.btnConfirmDelete.disabled = true;
      el.btnConfirmDelete.textContent = 'Deleting...';

      const res = await postAPI('profiles/delete', { id: profileId });
      showToast(res.message || `Profile '${profileId}' deleted`, 'success');
      closeDeleteModal();

      await loadProfiles();
      if (state.profile === profileId) {
        const next = state.profilesList[0]?.id || 'golang';
        setActiveProfile(next);
      }
    } catch (err) {
      showToast(err.message || 'Failed to delete profile', 'error');
    } finally {
      el.btnConfirmDelete.disabled = false;
      el.btnConfirmDelete.textContent = 'Delete Permanently';
    }
  }

  // ── Pipeline Execution Control ───────────────────────────────────
  async function triggerPipelineRun(action = 'search', stages = '') {
    const workers = parseInt(el.paramWorkersSelect.value, 10) || 2;
    const minScore = parseInt(el.paramMinScoreSelect.value, 10) || 7;
    const dryRun = el.paramDryRunCheckbox.checked;

    try {
      setPipelineUIState(true, action);
      appendTerminalLog(`[LAUNCH] Triggering pipeline action '${action}' for profile '${state.profile}'...`);

      const res = await postAPI('pipeline/run', {
        profile: state.profile,
        action: action,
        workers: workers,
        min_score: minScore,
        dry_run: dryRun,
        stages: stages,
      });

      showToast(`Started ${action.toUpperCase()} pipeline (PID ${res.pid})`, 'info');
      appendTerminalLog(`[PROCESS] Spawned background worker PID ${res.pid}. Monitoring execution...`);

      // Start tight status polling
      startPipelinePolling();
    } catch (err) {
      setPipelineUIState(false);
      showToast(err.message || 'Failed to start pipeline', 'error');
      appendTerminalLog(`[ERROR] Could not start pipeline: ${err.message}`);
    }
  }

  async function stopPipelineRun() {
    try {
      appendTerminalLog(`[STOP] Sending termination signal to active pipeline...`);
      const res = await postAPI('pipeline/stop', { profile: state.profile });
      showToast(res.message || 'Pipeline stopped', 'info');
      setPipelineUIState(false);
      appendTerminalLog(`[STOPPED] Background worker terminated.`);
      checkPipelineStatus();
    } catch (err) {
      showToast(err.message || 'Could not stop pipeline', 'error');
    }
  }

  function setPipelineUIState(isRunning, action = '') {
    state.isPipelineRunning = isRunning;

    el.btnPlayJobSearch.classList.toggle('btn-hidden', isRunning);
    el.btnPlayFullPipeline.classList.toggle('btn-hidden', isRunning);
    el.btnStopExecution.classList.toggle('btn-hidden', !isRunning);

    el.telemetryStatusBadge.textContent = isRunning ? 'RUNNING' : 'IDLE';
    el.telemetryStatusBadge.className = isRunning ? 'badge badge-pulse' : 'badge';
    el.telemetryStage.textContent = isRunning ? `Executing: ${action.toUpperCase()}` : 'Ready to Run';

    // Highlight active nodes
    const nodeDiscover = document.getElementById('node-discover');
    const nodeEnrich = document.getElementById('node-enrich');
    const nodeScore = document.getElementById('node-score');
    const nodeTailor = document.getElementById('node-tailor');
    const nodeApply = document.getElementById('node-apply');

    [nodeDiscover, nodeEnrich, nodeScore, nodeTailor, nodeApply].forEach((n) => {
      if (n) n.classList.remove('running');
    });

    if (isRunning) {
      if (action === 'search') {
        nodeDiscover?.classList.add('running');
        nodeEnrich?.classList.add('running');
      } else if (action === 'score') {
        nodeScore?.classList.add('running');
      } else if (action === 'tailor') {
        nodeTailor?.classList.add('running');
      } else if (action === 'apply') {
        nodeApply?.classList.add('running');
      } else if (action === 'all') {
        nodeDiscover?.classList.add('running');
        nodeScore?.classList.add('running');
      }
    }
  }

  function startPipelinePolling() {
    if (state.pipelineTimer) clearInterval(state.pipelineTimer);
    state.pipelineTimer = setInterval(checkPipelineStatus, 1500);
  }

  async function checkPipelineStatus() {
    const statusData = await fetchAPI('pipeline/status');
    if (!statusData) return;

    state.pipelineStatus = statusData;

    // Update telemetry indicators
    if (statusData.is_running) {
      setPipelineUIState(true, statusData.action || 'pipeline');
      el.telemetryPid.textContent = statusData.pid || '--';
      if (statusData.elapsed_seconds != null) {
        const m = Math.floor(statusData.elapsed_seconds / 60)
          .toString()
          .padStart(2, '0');
        const s = (statusData.elapsed_seconds % 60).toString().padStart(2, '0');
        el.telemetryElapsed.textContent = `00:${m}:${s}`;
      }
    } else {
      if (state.isPipelineRunning) {
        // Was running, now stopped
        setPipelineUIState(false);
        showToast('Pipeline run completed!', 'success');
        refreshData();
      }
      el.telemetryPid.textContent = '--';
      if (!state.isPipelineRunning) {
        el.telemetryElapsed.textContent = '00:00:00';
      }
    }

    // Stream logs into terminal
    if (statusData.log_tail && statusData.log_tail.length > 0) {
      renderTerminalLogs(statusData.log_tail);
    }
  }

  function renderTerminalLogs(lines) {
    if (!el.pipelineTerminalBody) return;
    el.pipelineTerminalBody.innerHTML = lines
      .map((l) => `<div class="log-line">${escapeHTML(l)}</div>`)
      .join('');

    if (el.terminalAutoScroll.checked) {
      el.pipelineTerminalBody.scrollTop = el.pipelineTerminalBody.scrollHeight;
    }
  }

  function appendTerminalLog(msg) {
    if (!el.pipelineTerminalBody) return;
    const time = new Date().toLocaleTimeString();
    const div = document.createElement('div');
    div.className = 'log-line system';
    div.textContent = `[${time}] ${msg}`;
    el.pipelineTerminalBody.appendChild(div);
    if (el.terminalAutoScroll.checked) {
      el.pipelineTerminalBody.scrollTop = el.pipelineTerminalBody.scrollHeight;
    }
  }

  // ── Core Monitor Refresh Cycle ───────────────────────────────────
  async function refreshData() {
    try {
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
        updatePipelineNodeStats(statsData);
        renderErrorDiagnostics(statsData);
      }

      if (liveData) {
        state.liveStatus = liveData;
        renderLiveIndicator(liveData);
        renderLiveFeed(liveData);
      }

      await fetchJobsData();
    } catch (err) {
      console.warn('Error during data refresh:', err);
    }
  }

  function updatePipelineNodeStats(stats) {
    if (!stats) return;
    el.nodeDiscoverCount.textContent = `${stats.total || 0} Jobs`;
    el.nodeEnrichCount.textContent = `${stats.with_description || 0} Enriched`;
    el.nodeScoreCount.textContent = `${stats.scored || 0} Scored`;
    el.nodeTailorCount.textContent = `${stats.tailored || 0} Tailored`;
    el.nodeApplyCount.textContent = `${stats.applied || 0} Applied`;
    el.navMonitorBadge.textContent = stats.total || 0;
    el.gatewayJobCountText.textContent = `${stats.total || 0} Jobs Discovered`;
  }

  function renderKPIs(stats) {
    el.kpiDiscovered.textContent = stats.total || 0;
    el.kpiEnrichedSub.textContent = `${stats.with_description || 0} enriched`;

    el.kpiScored.textContent = stats.scored || 0;
    el.kpiAvgScoreSub.textContent = `Avg Score: ${stats.avg_score || 0}`;

    el.kpiTailored.textContent = stats.tailored || 0;
    el.kpiPendingTailorSub.textContent = `${stats.pending_tailor_7 || 0} pending high-fit`;

    el.kpiReady.textContent = stats.ready_to_apply || 0;

    el.kpiApplied.textContent = stats.applied || 0;
    el.kpiAppliedSub.textContent = `${stats.applied || 0} submissions`;

    // Explicit Application Errors
    const errorsCount = stats.apply_errors || 0;
    el.kpiErrors.textContent = errorsCount;
    el.kpiErrorsSub.textContent = `${errorsCount} issue${errorsCount === 1 ? '' : 's'}`;
    el.tabErrorsCount.textContent = errorsCount;

    // Error Alert Banner
    if (errorsCount > 0) {
      el.monitorErrorBanner.classList.remove('btn-hidden');
      el.bannerErrorCount.textContent = errorsCount;
    } else {
      el.monitorErrorBanner.classList.add('btn-hidden');
    }
  }

  function renderErrorDiagnostics(stats) {
    if (!el.errorBreakdownRow) return;

    const breakdown = stats.error_breakdown || [];
    if (breakdown.length === 0) {
      el.errorBreakdownRow.innerHTML = `
        <div class="empty-state" style="padding: 20px;">
          <p>🎉 Zero application submission errors detected for ${state.profile}!</p>
        </div>`;
      return;
    }

    el.errorBreakdownRow.innerHTML = breakdown
      .map((b) => {
        return `
          <div class="error-summary-card">
            <div class="error-summary-head">
              <span class="error-summary-title" title="${escapeHTML(b.error)}">${escapeHTML(b.error)}</span>
              <span class="error-summary-badge">${b.count} jobs</span>
            </div>
            <div class="error-summary-sub">
              Sample: ${escapeHTML(b.sample_job || '')} (${escapeHTML(b.site || 'portal')})
            </div>
          </div>
        `;
      })
      .join('');
  }

  function renderScoreDistribution(dist) {
    if (!el.scoreBarsContainer) return;
    if (!dist || Object.keys(dist).length === 0) {
      el.scoreBarsContainer.innerHTML = '<div class="empty-state">No scored jobs yet</div>';
      return;
    }

    const maxCount = Math.max(...Object.values(dist), 1);
    let html = '';
    for (let s = 10; s >= 0; s--) {
      const count = dist[s] || 0;
      const pct = Math.round((count / maxCount) * 100);
      const isSelected = state.selectedScoreFilter === s;
      const scoreClass = s >= 8 ? 'high' : s >= 6 ? 'mid' : 'low';

      html += `
        <div class="score-bar-col ${isSelected ? 'selected' : ''}" data-score="${s}" title="Score ${s}: ${count} jobs">
          <span class="bar-count">${count}</span>
          <div class="bar-track">
            <div class="bar-fill score-${scoreClass}" style="height: ${pct}%;"></div>
          </div>
          <span class="bar-label">${s}</span>
        </div>
      `;
    }
    el.scoreBarsContainer.innerHTML = html;

    el.scoreBarsContainer.querySelectorAll('.score-bar-col').forEach((col) => {
      col.addEventListener('click', () => {
        const score = parseInt(col.getAttribute('data-score'), 10);
        state.selectedScoreFilter = state.selectedScoreFilter === score ? null : score;
        fetchJobsData();
      });
    });
  }

  function renderSources(sites) {
    if (!el.sourcesList) return;
    if (!sites || sites.length === 0) {
      el.sourcesList.innerHTML = '<div class="empty-state">No source sites yet</div>';
      return;
    }

    el.totalSitesCount.textContent = `${sites.length} sites`;
    el.sourcesList.innerHTML = sites
      .map(
        (s) => `
        <div class="source-item">
          <div class="source-name">
            <span class="site-tag">${escapeHTML(s.site)}</span>
            <span class="source-applied">${s.applied} applied</span>
          </div>
          <div class="source-meta">
            <span>${s.total} found</span>
            <span class="text-cyan">${s.high_fit} high fit</span>
          </div>
        </div>
      `
      )
      .join('');
  }

  function updateSiteSelect(sites) {
    if (!el.filterSiteSelect) return;
    const current = el.filterSiteSelect.value;
    let opts = '<option value="all">All Sites / Sources</option>';
    if (sites) {
      sites.forEach((s) => {
        opts += `<option value="${escapeHTML(s.site)}" ${current === s.site ? 'selected' : ''}>${escapeHTML(s.site)} (${s.total})</option>`;
      });
    }
    el.filterSiteSelect.innerHTML = opts;
  }

  function renderLiveIndicator(data) {
    const isActive = data.is_active || state.isPipelineRunning;
    el.livePill.classList.toggle('active', isActive);
    el.liveStatusText.textContent = isActive ? 'STREAMING' : 'STANDBY';
  }

  function renderLiveFeed(data) {
    // Running processes
    const tasks = data.running_tasks || [];
    if (tasks.length === 0) {
      el.runningProcessList.innerHTML = '<p class="empty-text">No active background tasks.</p>';
    } else {
      el.runningProcessList.innerHTML = tasks
        .map(
          (t) => `
          <div class="process-item">
            <div class="process-head">
              <span class="badge badge-pulse">PID ${t.pid}</span>
              <span class="mono">${t.stage}</span>
            </div>
            <p class="mono text-dim text-truncate">${escapeHTML(t.command)}</p>
          </div>
        `
        )
        .join('');
    }

    // Recent tailored files
    const files = data.activity?.recent_tailored || [];
    if (files.length === 0) {
      el.recentTailoredList.innerHTML = '<p class="empty-text">No tailored files yet.</p>';
    } else {
      el.recentTailoredList.innerHTML = files
        .map(
          (f) => `
          <div class="recent-file-item" data-file="${escapeHTML(f.name)}">
            <span class="file-name">${escapeHTML(f.name)}</span>
            <span class="file-time">${f.mtime ? new Date(f.mtime).toLocaleTimeString() : ''}</span>
          </div>
        `
        )
        .join('');

      el.recentTailoredList.querySelectorAll('.recent-file-item').forEach((item) => {
        item.addEventListener('click', () => {
          openResumeModal(item.getAttribute('data-file'));
        });
      });
    }
  }

  // ── Fetch & Render Jobs (Applied, All, and Errors) ────────────────
  async function fetchJobsData() {
    const params = {
      limit: 100,
      search: state.searchKeyword,
      site: state.siteFilter,
      min_score: state.selectedScoreFilter != null ? state.selectedScoreFilter : state.minScoreFilter,
    };

    // 1. Fetch all jobs
    const allData = await fetchAPI('jobs', { ...params, stage: state.stageFilter });
    if (allData && allData.jobs) {
      state.allJobs = allData.jobs;
      el.tabAllJobsCount.textContent = allData.total || 0;
      renderJobsTable(allData.jobs);
    }

    // 2. Fetch applied / tailored jobs
    const appliedData = await fetchAPI('jobs', { stage: 'applied', limit: 100 });
    if (appliedData && appliedData.jobs) {
      state.appliedJobs = appliedData.jobs;
      el.tabAppliedCount.textContent = appliedData.total || 0;
      renderAppliedJobsGrid(appliedData.jobs);
    }

    // 3. Fetch error jobs for dedicated error diagnostics tab
    const errorData = await fetchAPI('jobs', { stage: 'errors', limit: 100 });
    if (errorData && errorData.jobs) {
      state.errorJobs = errorData.jobs;
      renderErrorsTable(errorData.jobs);
    }
  }

  function renderAppliedJobsGrid(jobs) {
    if (!el.appliedJobsGrid) return;
    if (!jobs || jobs.length === 0) {
      el.appliedJobsGrid.innerHTML = `
        <div class="empty-state">
          <p>No applied or tailored jobs yet for profile '${state.profile}'.</p>
        </div>`;
      return;
    }

    el.appliedJobsGrid.innerHTML = jobs
      .map((j) => {
        const hasResume = !!j.tailored_filename || !!j.tailored_resume_path;
        const filename = j.tailored_filename || (j.tailored_resume_path ? j.tailored_resume_path.split('/').pop() : '');
        const hasError = !!j.apply_error;

        return `
          <div class="applied-card ${hasError ? 'error-job-card' : ''}">
            <div class="applied-head">
              <span class="score-pill ${j.fit_score >= 8 ? 'score-high' : 'score-mid'}">Score ${j.fit_score || '--'}</span>
              <span class="site-tag">${escapeHTML(j.site || 'portal')}</span>
            </div>
            <h4 class="applied-title" title="${escapeHTML(j.title)}">${escapeHTML(j.title)}</h4>
            <div class="applied-meta">📍 ${escapeHTML(j.location || 'Remote')}</div>

            ${hasError ? `<div class="error-inline-callout">⚠️ Issue: ${escapeHTML(j.apply_error)}</div>` : ''}

            <div class="applied-footer">
              ${hasResume ? `
                <button class="btn btn-sm btn-primary btn-view-resume" data-file="${escapeHTML(filename)}">
                  📄 View Tailored Resume
                </button>
              ` : '<span class="text-dim">Pending resume tailoring</span>'}
              <button class="btn btn-sm btn-ghost btn-view-job" data-url="${escapeHTML(j.url)}">
                Job Details &rarr;
              </button>
            </div>
          </div>
        `;
      })
      .join('');

    el.appliedJobsGrid.querySelectorAll('.btn-view-resume').forEach((btn) => {
      btn.addEventListener('click', () => openResumeModal(btn.getAttribute('data-file')));
    });

    el.appliedJobsGrid.querySelectorAll('.btn-view-job').forEach((btn) => {
      btn.addEventListener('click', () => openJobModal(btn.getAttribute('data-url')));
    });
  }

  function renderErrorsTable(jobs) {
    if (!el.errorsTableBody) return;
    if (!jobs || jobs.length === 0) {
      el.errorsTableBody.innerHTML = `
        <tr><td colspan="6" style="text-align: center; padding: 30px; color: var(--text-dim);">
          No application errors found! All submissions succeeded smoothly.
        </td></tr>`;
      return;
    }

    el.errorsTableBody.innerHTML = jobs
      .map((j) => {
        return `
          <tr>
            <td>
              <span class="score-pill ${j.fit_score >= 8 ? 'score-high' : 'score-mid'}">${j.fit_score || '--'}</span>
            </td>
            <td>
              <div class="job-title-row">
                <a href="#" class="job-link btn-view-job" data-url="${escapeHTML(j.url)}">${escapeHTML(j.title)}</a>
              </div>
              <div class="text-dim text-sm">${escapeHTML(j.location || 'Remote')}</div>
            </td>
            <td><span class="site-tag">${escapeHTML(j.site || 'portal')}</span></td>
            <td>
              <div class="error-badge-cell" title="${escapeHTML(j.apply_error || j.detail_error || 'Unknown error')}">
                ${escapeHTML(j.apply_error || j.detail_error || 'Submission error')}
              </div>
            </td>
            <td><span class="mono">${j.apply_attempts || 1} att.</span></td>
            <td style="text-align: right;">
              <a href="${escapeHTML(j.application_url || j.url)}" target="_blank" class="btn btn-sm btn-primary">
                Apply Manually &rarr;
              </a>
            </td>
          </tr>
        `;
      })
      .join('');

    el.errorsTableBody.querySelectorAll('.btn-view-job').forEach((a) => {
      a.addEventListener('click', (e) => {
        e.preventDefault();
        openJobModal(a.getAttribute('data-url'));
      });
    });
  }

  function renderJobsTable(jobs) {
    if (!el.jobsTableBody) return;
    if (!jobs || jobs.length === 0) {
      el.jobsTableBody.innerHTML = `
        <tr><td colspan="7" style="text-align: center; padding: 40px; color: var(--text-dim);">
          No jobs found matching your filters.
        </td></tr>`;
      return;
    }

    el.jobsTableBody.innerHTML = jobs
      .map((j) => {
        const hasResume = !!j.tailored_filename;
        const filename = j.tailored_filename || '';
        const isApplied = !!j.applied_at;
        const hasError = !!j.apply_error;

        return `
          <tr>
            <td>
              <span class="score-pill ${j.fit_score >= 8 ? 'score-high' : j.fit_score >= 6 ? 'score-mid' : 'score-low'}">
                ${j.fit_score || '--'}
              </span>
            </td>
            <td>
              <div class="job-title-row">
                <a href="#" class="job-link btn-view-job" data-url="${escapeHTML(j.url)}">${escapeHTML(j.title)}</a>
              </div>
              <div class="text-dim text-sm">${escapeHTML(j.salary || '')}</div>
            </td>
            <td><span class="site-tag">${escapeHTML(j.site || 'portal')}</span></td>
            <td><span class="text-dim">${escapeHTML(j.location || 'Remote')}</span></td>
            <td>
              ${hasResume ? `
                <button class="btn btn-sm btn-ghost btn-view-resume" data-file="${escapeHTML(filename)}">
                  📄 Tailored ATS
                </button>
              ` : '<span class="text-dim">--</span>'}
            </td>
            <td>
              ${hasError ? `<span class="badge badge-rose">Error</span>` :
                isApplied ? `<span class="badge badge-emerald">Applied</span>` :
                j.fit_score >= 7 ? `<span class="badge badge-accent">Ready</span>` :
                `<span class="badge badge-dim">Discovered</span>`}
            </td>
            <td style="text-align: right;">
              <button class="btn btn-sm btn-outline btn-view-job" data-url="${escapeHTML(j.url)}">
                View
              </button>
            </td>
          </tr>
        `;
      })
      .join('');

    el.jobsTableBody.querySelectorAll('.btn-view-job').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        openJobModal(btn.getAttribute('data-url'));
      });
    });

    el.jobsTableBody.querySelectorAll('.btn-view-resume').forEach((btn) => {
      btn.addEventListener('click', () => {
        openResumeModal(btn.getAttribute('data-file'));
      });
    });
  }

  // ── Modals Logic ─────────────────────────────────────────────────
  async function openResumeModal(filename) {
    if (!filename) return;
    state.activeResumeFile = filename;
    el.modalResumeFilename.textContent = filename;

    const data = await fetchAPI('resume', { file: filename });
    if (!data) return;

    const parsed = data.parsed || {};
    el.modalResumeTitle.textContent = `${parsed.name || 'Candidate'} - Tailored ATS Resume`;

    // Formatted ATS preview
    let sectionsHtml = '';
    if (parsed.sections) {
      for (const [secTitle, secContent] of Object.entries(parsed.sections)) {
        sectionsHtml += `
          <div class="sheet-section">
            <h3>${escapeHTML(secTitle)}</h3>
            <div class="sheet-section-content">${escapeHTML(secContent)}</div>
          </div>
        `;
      }
    }

    el.resumeFormattedContent.innerHTML = `
      <div class="sheet-header">
        <h1>${escapeHTML(parsed.name || 'Applicant')}</h1>
        <div class="sheet-title">${escapeHTML(parsed.title || '')}</div>
        <div class="sheet-contact">${escapeHTML(parsed.contact || '')}</div>
      </div>
      ${sectionsHtml}
    `;

    el.resumeRawContent.textContent = parsed.raw || '';

    // Download links
    const profileParam = `profile=${state.profile}&file=${encodeURIComponent(filename)}`;
    el.btnDownloadTxt.href = `/api/download-resume?${profileParam}&format=txt`;
    el.btnDownloadMd.href = `/api/download-resume?${profileParam}&format=md`;
    el.btnDownloadPdf.href = `/api/download-resume?${profileParam}&format=pdf`;

    el.resumeModal.classList.add('active');
  }

  function closeResumeModal() {
    el.resumeModal.classList.remove('active');
  }

  async function openJobModal(url) {
    if (!url) return;
    const job = await fetchAPI('job-detail', { url });
    if (!job) return;

    el.modalJobScore.textContent = job.fit_score != null ? job.fit_score : '--';
    el.modalJobTitle.textContent = job.title || 'Job Details';
    el.modalJobMeta.textContent = `${job.site || 'portal'} • ${job.location || 'Remote'}`;
    el.modalJobSite.textContent = job.site || 'Unknown';
    el.modalJobSalary.textContent = job.salary || 'Not specified';
    el.modalJobDiscovered.textContent = job.discovered_at ? new Date(job.discovered_at).toLocaleString() : '--';
    el.modalJobAppliedStatus.textContent = job.applied_at ? `Applied on ${new Date(job.applied_at).toLocaleDateString()}` : 'Not applied yet';
    el.modalJobReasoning.textContent = job.score_reasoning || 'No scoring reasoning provided by LLM.';
    el.modalJobDescription.textContent = job.full_description || 'No full description scraped yet.';
    el.modalJobApplyBtn.href = job.application_url || job.url;

    // Error diagnostics in modal
    if (job.apply_error) {
      el.modalJobErrorBox.classList.remove('btn-hidden');
      el.modalJobErrorMsg.textContent = job.apply_error;
      el.modalJobErrorAttempts.textContent = `${job.apply_attempts || 1} submission attempt(s)`;
    } else {
      el.modalJobErrorBox.classList.add('btn-hidden');
    }

    el.jobModal.classList.add('active');
  }

  function closeJobModal() {
    el.jobModal.classList.remove('active');
  }

  function escapeHTML(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Event Listeners Setup ────────────────────────────────────────
  function setupEventListeners() {
    // View Navigation Buttons
    el.brandLogoBtn?.addEventListener('click', () => switchView('home'));
    el.navBtnHome?.addEventListener('click', () => switchView('home'));
    el.navBtnPipeline?.addEventListener('click', () => switchView('pipeline'));
    el.navBtnMonitor?.addEventListener('click', () => switchView('monitor'));

    // Global Profile Selector
    el.globalProfileSelect?.addEventListener('change', (e) => {
      setActiveProfile(e.target.value);
    });

    el.btnHeaderNewProfile?.addEventListener('click', () => {
      openProfileModal('create');
    });

    // Homepage Action Buttons
    el.btnSpotlightContinue?.addEventListener('click', () => switchView('pipeline'));
    el.btnSpotlightOpenMonitor?.addEventListener('click', () => switchView('monitor'));
    el.btnSpotlightEdit?.addEventListener('click', () => openProfileModal('edit', state.profile));
    el.btnSpotlightDelete?.addEventListener('click', () => openDeleteModal(state.profile));
    el.btnCreateNewProfileGrid?.addEventListener('click', () => openProfileModal('create'));

    // Pipeline Action Buttons
    el.linkPipelineHome?.addEventListener('click', (e) => {
      e.preventDefault();
      switchView('home');
    });
    el.btnPipelineOpenMonitor?.addEventListener('click', () => switchView('monitor'));

    el.btnPlayJobSearch?.addEventListener('click', () => triggerPipelineRun('search'));
    el.btnPlayFullPipeline?.addEventListener('click', () => triggerPipelineRun('all'));
    el.btnStopExecution?.addEventListener('click', stopPipelineRun);

    el.nodePlayBtns?.forEach((btn) => {
      btn.addEventListener('click', () => {
        const action = btn.getAttribute('data-action');
        triggerPipelineRun(action);
      });
    });

    el.btnClearTerminal?.addEventListener('click', () => {
      if (el.pipelineTerminalBody) {
        el.pipelineTerminalBody.innerHTML = '<div class="log-line system">[SYSTEM] Terminal cleared.</div>';
      }
    });

    // Monitor Action Buttons
    el.linkMonitorHome?.addEventListener('click', (e) => {
      e.preventDefault();
      switchView('home');
    });
    el.linkMonitorPipeline?.addEventListener('click', (e) => {
      e.preventDefault();
      switchView('pipeline');
    });
    el.btnMonitorBackToPipeline?.addEventListener('click', () => switchView('pipeline'));

    el.btnBannerViewErrors?.addEventListener('click', () => {
      el.tabBtnErrors?.click();
    });

    el.kpiErrorCard?.addEventListener('click', () => {
      el.tabBtnErrors?.click();
    });

    // Monitor Tabs
    el.tabBtns?.forEach((btn) => {
      btn.addEventListener('click', () => {
        const targetTab = btn.getAttribute('data-tab');
        el.tabBtns.forEach((b) => b.classList.remove('active'));
        el.tabPanes.forEach((p) => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(targetTab)?.classList.add('active');
      });
    });

    // Job Search & Filters
    let debounceTimer;
    el.jobsSearchInput?.addEventListener('input', (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        state.searchKeyword = e.target.value.trim();
        fetchJobsData();
      }, 300);
    });

    el.filterStageSelect?.addEventListener('change', (e) => {
      state.stageFilter = e.target.value;
      fetchJobsData();
    });

    el.filterSiteSelect?.addEventListener('change', (e) => {
      state.siteFilter = e.target.value;
      fetchJobsData();
    });

    el.filterMinScoreSelect?.addEventListener('change', (e) => {
      state.minScoreFilter = e.target.value;
      fetchJobsData();
    });

    // Refresh Controller
    el.btnManualRefresh?.addEventListener('click', () => {
      refreshData();
      checkPipelineStatus();
      showToast('Telemetry refreshed', 'info');
    });

    el.refreshRateSelect?.addEventListener('change', (e) => {
      const ms = parseInt(e.target.value, 10);
      state.refreshRate = ms;
      if (state.timer) clearInterval(state.timer);
      if (ms > 0) {
        state.timer = setInterval(refreshData, ms);
      }
    });

    // Profile Form Modal
    el.btnCloseProfileModal?.addEventListener('click', closeProfileModal);
    el.btnCancelProfileModal?.addEventListener('click', closeProfileModal);
    el.profileForm?.addEventListener('submit', handleProfileFormSubmit);

    // Delete Modal
    el.btnCloseDeleteModal?.addEventListener('click', closeDeleteModal);
    el.btnCancelDelete?.addEventListener('click', closeDeleteModal);
    el.btnConfirmDelete?.addEventListener('click', handleConfirmDelete);

    // Resume Modal
    el.btnCloseResumeModal?.addEventListener('click', closeResumeModal);
    document.querySelectorAll('.modal-tabs .subtab-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const sub = btn.getAttribute('data-subtab');
        document.querySelectorAll('.modal-tabs .subtab-btn').forEach((b) => b.classList.remove('active'));
        document.querySelectorAll('.modal-body .subtab-content').forEach((c) => c.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(`subtab-${sub}`)?.classList.add('active');
      });
    });

    // Job Modal
    el.btnCloseJobModal?.addEventListener('click', closeJobModal);

    // Close Modals on Backdrop Click
    window.addEventListener('click', (e) => {
      if (e.target === el.profileModal) closeProfileModal();
      if (e.target === el.deleteModal) closeDeleteModal();
      if (e.target === el.resumeModal) closeResumeModal();
      if (e.target === el.jobModal) closeJobModal();
    });

    // Hash navigation listener
    window.addEventListener('hashchange', () => {
      const hash = window.location.hash.replace('#', '') || 'home';
      if (hash !== state.currentView) {
        switchView(hash);
      }
    });
  }

  // ── Initialization ──────────────────────────────────────────────
  async function init() {
    setupEventListeners();

    // Determine initial view from hash or default to home
    const initialView = window.location.hash.replace('#', '') || 'home';
    switchView(initialView);

    // Load profiles and refresh data
    await loadProfiles();
    await refreshData();
    await checkPipelineStatus();

    // Start background auto-refresh
    if (state.refreshRate > 0) {
      state.timer = setInterval(refreshData, state.refreshRate);
    }
  }

  // Launch on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
