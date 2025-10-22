// === Queue Display Enhanced Script (Hardened) ===
class QueueSystem {
  constructor() {
    const cfg = window.APP_CONFIG || {};
    this.config = {
      QUEUE_API: cfg.QUEUE_API || '/appointments/queue-number-api/',
      CALL_NEXT_API: cfg.CALL_NEXT_API || '/appointments/call-next/0/',
      REFRESH_INTERVAL: cfg.REFRESH_INTERVAL || 15000,
      NOW_SERVING_INTERVAL: cfg.NOW_SERVING_INTERVAL || 5000,
    };
    this.csrfToken = cfg.CSRF_TOKEN || this.getCookie('csrftoken') || '';

    this.doctors = [];
    this.filteredDoctors = [];
    this.currentServingIndex = 0;

    this._fetchController = null;
    this._rotatorTimer = null;
    this._refreshTimer = null;
    this._clockTimer = null;
    this._duringCall = new Set();

    this.dom = {
      queueGrid:        document.getElementById('queue-grid'),
      searchInput:      document.getElementById('search-input'),
      doctorCount:      document.getElementById('doctor-count'),
      currentTime:      document.getElementById('current-time'),
      updateTime:       document.getElementById('update-time'),
      emptyState:       document.getElementById('empty-state'),
      refreshTimestamp: document.getElementById('refresh-timestamp'),
      nowServing:       document.getElementById('now-serving-display'),
      nowServingLive:   document.getElementById('now-serving-live')
    };

    this.init();
  }

  // ------------- Utilities -------------
  getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return decodeURIComponent(parts.pop().split(';').shift());
    return '';
  }

  debounce(fn, delay) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn.apply(this, args), delay); };
  }

  abortFetch() {
    if (this._fetchController) {
      this._fetchController.abort();
      this._fetchController = null;
    }
  }

  timeoutPromise(ms) {
    return new Promise((_, rej) => setTimeout(() => rej(new Error('Request timed out')), ms));
  }

  // ------------- Init -------------
  init() {
    if (!this.dom.queueGrid) {
      console.warn('[QueueSystem] Missing DOM.');
      return;
    }

    if (!this.dom.nowServingLive) {
      const live = document.createElement('div');
      live.id = 'now-serving-live';
      live.setAttribute('aria-live', 'polite');
      live.setAttribute('aria-atomic', 'true');
      live.style.position = 'absolute';
      live.style.left = '-9999px';
      document.body.appendChild(live);
      this.dom.nowServingLive = live;
    }

    this.dom.searchInput?.addEventListener('input', this.debounce(() => this.filterDoctors(), 300));

    this.updateClock();
    this._clockTimer = setInterval(() => this.updateClock(), 1000);

    this.fetchQueueData({ showLoading: true });
    this._refreshTimer = setInterval(() => this.fetchQueueData(), this.config.REFRESH_INTERVAL);
    this._rotatorTimer  = setInterval(() => this.rotateNowServing(), this.config.NOW_SERVING_INTERVAL);

    window.addEventListener('visibilitychange', () => {
      if (document.hidden) this.abortFetch();
      else this.fetchQueueData();
    });
  }

  // ------------- Clock -------------
  updateClock() {
    if (!this.dom.currentTime) return;
    const now = new Date();
    window.requestAnimationFrame(() => {
      this.dom.currentTime.textContent = now.toLocaleTimeString([], {
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      });
    });
  }

  // ------------- Data Fetch -------------
  async fetchQueueData({ showLoading = false } = {}) {
    if (showLoading) this.renderSkeleton();

    this.abortFetch();
    this._fetchController = new AbortController();
    const { signal } = this._fetchController;

    try {
      const fetchPromise = fetch(this.config.QUEUE_API, { signal });
      const res = await Promise.race([fetchPromise, this.timeoutPromise(10000)]);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();

      // Normalize shape to what UI expects
      this.doctors = (json.queues || []).map(item => {
        const waiting_list = Array.isArray(item.waiting_list)
          ? item.waiting_list
          : (typeof item.waiting === 'number'
              ? Array.from({ length: item.waiting }, (_, i) => ({ number: (item.next_queue || 0) + 1 + i }))
              : []);
        const current_patient = item.current_patient || (item.next_queue
          ? { number: item.next_queue, patient_name: item.current_patient_name || '' }
          : null);
        return {
          doctor_id: item.doctor_id ?? item.id ?? item.doctor ?? null,
          doctor_name: item.doctor_name ?? item.name ?? 'Unknown',
          doctor_specialty: item.doctor_specialty ?? item.specialty ?? 'General Practitioner',
          status: item.status ?? (waiting_list.length ? 'available' : (current_patient ? 'busy' : 'available')),
          waiting_list,
          current_patient,
          avg_time: item.avg_time ?? 0,
        };
      });

      this.currentServingIndex = 0;
      if (this.dom.doctorCount) this.dom.doctorCount.textContent = this.doctors.length;
      this.filterDoctors();

      const now = new Date();
      this.dom.updateTime && (this.dom.updateTime.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
      this.dom.refreshTimestamp && (this.dom.refreshTimestamp.textContent = `Last refresh: ${now.toLocaleTimeString([], { hour: '2-digit' })}`);
      this.updateNowServing();
    } catch (err) {
      if (err.name === 'AbortError') return;
      console.error('Queue fetch error:', err);
      this.showNotification('System Error', 'Failed to load queue data', 'critical');
      if (this.dom.queueGrid && !this.doctors.length) {
        this.dom.queueGrid.innerHTML =
          `<div class="error-state"><p>⚠ Unable to load queue data. <button class="retry-btn">Retry</button></p></div>`;
        this.dom.queueGrid.querySelector('.retry-btn')
          ?.addEventListener('click', () => this.fetchQueueData({ showLoading: true }));
      }
    } finally {
      this._fetchController = null;
    }
  }

  // ------------- Now Serving -------------
  getServingPatients() {
    const arr = this.doctors
      .filter(d => d.current_patient)
      .map(d => ({
        doctor: d.doctor_name,
        patient: d.current_patient.patient_name || '',
        number: d.current_patient.number
      }));
    return arr.length ? arr : [{ doctor: '', patient: 'No active patients', number: '' }];
  }

  rotateNowServing() {
    const list = this.getServingPatients();
    if (!list.length) return;
    this.currentServingIndex = (list.length === 1) ? 0 : (this.currentServingIndex + 1) % list.length;
    this.updateNowServing();
  }

  updateNowServing() {
    if (!this.dom.nowServing) return;
    const patients = this.getServingPatients();
    const cur = patients[this.currentServingIndex] || patients[0];
    const text = (cur.patient === 'No active patients')
      ? cur.patient
      : `${cur.number ?? ''} - ${cur.patient} (${cur.doctor})`;
    this.dom.nowServing.textContent = text;
    this.dom.nowServingLive && (this.dom.nowServingLive.textContent = `Now serving: ${text}`);
  }

  // ------------- Filter & Render -------------
  filterDoctors() {
    const term = (this.dom.searchInput?.value || '').trim().toLowerCase();
    this.filteredDoctors = this.doctors.filter(d =>
      !term ||
      (d.doctor_name && d.doctor_name.toLowerCase().includes(term)) ||
      (d.doctor_specialty && d.doctor_specialty.toLowerCase().includes(term))
    );
    this.renderQueue();
  }

  renderSkeleton(count = 4) {
    if (!this.dom.queueGrid) return;
    this.dom.queueGrid.innerHTML = '';
    const frag = document.createDocumentFragment();
    for (let i = 0; i < count; i++) {
      const s = document.createElement('div');
      s.className = 'queue-card skeleton';
      s.innerHTML = `
        <div class="queue-card-header">
          <div class="doctor-avatar shimmer"></div>
          <div class="doctor-info">
            <div class="skeleton-line w-60 shimmer"></div>
            <div class="skeleton-line w-40 shimmer mt-1"></div>
          </div>
          <div class="status-badge skeleton-badge shimmer"></div>
        </div>
        <div class="queue-card-body">
          <div class="skeleton-line w-80 shimmer mb-2"></div>
          <div class="skeleton-line w-50 shimmer mb-3"></div>
          <div class="waiting-info">
            <div class="info-box skeleton-box shimmer"></div>
            <div class="info-box skeleton-box shimmer"></div>
          </div>
          <div class="skeleton-btn shimmer"></div>
        </div>`;
      frag.appendChild(s);
    }
    this.dom.queueGrid.appendChild(frag);
    this.dom.emptyState && (this.dom.emptyState.hidden = true);
  }

  renderQueue() {
    if (!this.dom.queueGrid) return;
    if (!this.filteredDoctors.length) {
      this.dom.queueGrid.innerHTML = '';
      this.dom.emptyState && (this.dom.emptyState.hidden = false);
      return;
    }
    this.dom.emptyState && (this.dom.emptyState.hidden = true);
    const frag = document.createDocumentFragment();
    this.filteredDoctors.forEach(d => frag.appendChild(this.createDoctorCard(d)));
    this.dom.queueGrid.innerHTML = '';
    this.dom.queueGrid.appendChild(frag);
  }

  buildStatus(d) {
    if (d.status === 'available') return ['status-available', 'Available'];
    if (d.status === 'busy') return ['status-busy', 'In Consultation'];
    return ['status-offline', 'Offline'];
  }

  buildCurrentPatient(d) {
    if (!d.current_patient) return `<div class="current-patient no-patient">No current patient</div>`;
    const num = d.current_patient.number ?? '';
    const name = d.current_patient.patient_name ?? '';
    return `<div class="current-patient"><span class="patient-number">${num}</span><span class="patient-name">${name}</span></div>`;
  }

  buildWaitingStats(d) {
    const waitingLen = Array.isArray(d.waiting_list) ? d.waiting_list.length : 0;
    return `
      <div class="waiting-info">
        <div class="info-box" aria-label="Waiting count">
          <div class="info-value">${waitingLen}</div>
          <div class="info-label">Waiting</div>
        </div>
        <div class="info-box" aria-label="Average wait minutes">
          <div class="info-value">${d.avg_time || 0}</div>
          <div class="info-label">Avg. Wait (min)</div>
        </div>
      </div>`;
  }

  createDoctorCard(d) {
    const [statusClass, statusLabel] = this.buildStatus(d);
    const card = document.createElement('div');
    card.className = 'queue-card';
    card.setAttribute('role', 'article');
    card.setAttribute(
      'aria-label',
      `Doctor ${d.doctor_name}${d.doctor_specialty ? ', ' + d.doctor_specialty : ''}`
    );

    const canCall = (Array.isArray(d.waiting_list) && d.waiting_list.length > 0 && d.status === 'available' && d.doctor_id);

    card.innerHTML = `
      <div class="queue-card-header">
        <div class="doctor-avatar" aria-hidden="true">${(d.doctor_name || '?').charAt(0)}</div>
        <div class="doctor-info">
          <div class="doctor-name">${d.doctor_name || 'Unknown'}</div>
          <div class="doctor-specialty">${d.doctor_specialty || 'General Practitioner'}</div>
        </div>
        <div class="status-badge ${statusClass}" aria-label="Status: ${statusLabel}">${statusLabel}</div>
      </div>
      <div class="queue-card-body">
        <div class="section-title">Current Patient</div>
        ${this.buildCurrentPatient(d)}
        ${this.buildWaitingStats(d)}
        <button class="call-next-btn" type="button"
          ${canCall ? '' : 'disabled'}
          aria-disabled="${canCall ? 'false' : 'true'}"
          aria-label="Call next patient for ${d.doctor_name}"
          data-doctor-id="${d.doctor_id ?? ''}">
          ${canCall ? 'Call Next Patient' : 'Unavailable'}
        </button>
      </div>`;

    const btn = card.querySelector('.call-next-btn');
    if (btn && canCall) {
      btn.addEventListener('click', () => this.callNextPatient(d.doctor_id, btn));
    }
    return card;
  }

  // ------------- Call Next -------------
  buildCallNextUrl(id) {
    const tmpl = this.config.CALL_NEXT_API;
    if (id === undefined || id === null) return tmpl;

    // 1) حالتك الشائعة: .../api/queue/0/next/
    if (tmpl.includes('/0/next/')) {
      return tmpl.replace('/0/next/', `/${id}/next/`);
    }
    // 2) حالة: .../call-next/0/
    if (tmpl.includes('/0/')) {
      return tmpl.replace('/0/', `/${id}/`);
    }
    // 3) احتياط: أول رقم بين شرطات
    return tmpl.replace(/\/\d+(?=\/|$)/, `/${id}`);
  }

  async callNextPatient(id, btnEl) {
    if (this._duringCall.has(id)) return;
    this._duringCall.add(id);
    if (btnEl) {
      btnEl.disabled = true;
      btnEl.textContent = 'Calling...';
      btnEl.classList.add('loading');
    }

    try {
      const url = this.buildCallNextUrl(id);
      const res = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin', // لضمان إرسال كوكي csrftoken
        headers: {
          'X-CSRFToken': this.csrfToken,
          'Accept': 'application/json',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({})
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Unknown error');

      this.doctors = json.queues || this.doctors;
      this.currentServingIndex = 0;
      this.filterDoctors();
      this.updateNowServing();
      this.showNotification('Success', 'Next patient called', 'success');
    } catch (err) {
      console.error('Call next error:', err);
      this.showNotification('Error', 'Failed to call next', 'critical');
      if (btnEl) {
        btnEl.disabled = false;
        btnEl.textContent = 'Call Next Patient';
        btnEl.classList.remove('loading');
      }
    } finally {
      this._duringCall.delete(id);
    }
  }

  // ------------- Notifications -------------
  showNotification(title, msg, type = 'info') {
    // لاحقًا يمكن ربط Toast UI
    console.log(`[${type.toUpperCase()}] ${title}: ${msg}`);
  }

  // ------------- Cleanup -------------
  destroy() {
    this.abortFetch();
    clearInterval(this._clockTimer);
    clearInterval(this._refreshTimer);
    clearInterval(this._rotatorTimer);
  }
}

// تهيئة عند التحميل
document.addEventListener('DOMContentLoaded', () => {
  window.__queueSystemInstance = new QueueSystem();
});
