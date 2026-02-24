/**
 * Medical Record Creator - Fixed JavaScript
 * Version 2.1.2
 *
 * Key Fix:
 * - DO NOT clear <input type="file"> AFTER syncing DataTransfer (it wipes files).
 *
 * Extra Improvements:
 * - Align allowed extensions/types with backend (pdf/jpg/jpeg/png/gif/webp).
 * - Always sync notesRTE -> hidden textarea before submit.
 * - Sync attachment input right before submit.
 * - Safer DataTransfer support checks.
 */

'use strict';

class MedicalRecordCreator {
  constructor() {
    this.DEBUG = false;
    this.VERSION = '2.1.2';
    this.init();
  }

  init() {
    this.cacheElements();

    if (!this.form) {
      console.warn('MedicalRecordCreator: Form not found');
      return;
    }

    this.log('Initializing Medical Record Creator v' + this.VERSION);

    this.initSelect2();
    this.initFileUpload();
    this.initRichText();
    this.initCriticalToggle();
    this.initNotifications();
    this.initCharacterCounters();
    this.initVoiceNote();

    this.initStepNavigation();
    this.initEventListeners();
    this.initFormValidation();

    this.bindFormChanges();

    const initialStep = this.getInitialStep();
    this.goToStep(initialStep, { focus: false });

    this.updateProgress();
    this.setState('initialized');

    this.log('Medical Record Creator initialized successfully');
  }

  // -------------------------
  // State / Cache
  // -------------------------
  setState(state) {
    this.state = state;
    if (this.formState) this.formState.value = state;
    this.log('State changed to:', state);
  }

  cacheElements() {
    this.form = document.getElementById('medicalRecordForm');

    this.submitBtn = document.getElementById('submitBtn');
    this.resetBtn = document.getElementById('resetBtn');
    this.saveDraftBtn = document.getElementById('saveDraftBtn'); // may be absent
    this.cancelBtn = document.getElementById('cancelBtn');

    this.progressFill = document.getElementById('progressFill');
    this.progressText = document.getElementById('progressText');
    this.currentSection = document.getElementById('currentSection');
    this.formState = document.getElementById('formState');

    this.sections = document.querySelectorAll('.form-section');
    this.stepperItems = document.querySelectorAll('.stepper-item');

    // Patient / record fields
    this.patientSelect = document.getElementById('id_patient');
    this.doctorSelect = document.getElementById('id_doctor'); // may be absent
    this.titleInput = document.getElementById('id_title');
    this.typeSelect = document.getElementById('id_archive_type');
    this.descriptionInput = document.getElementById('id_description');

    // Notes (RTE + hidden textarea)
    this.notesInput = document.getElementById('id_notes');
    this.notesRte = document.getElementById('notesRte');

    // Counters
    this.titleCounter = document.getElementById('titleCounter');
    this.notesCounter = document.getElementById('notesCounter');
    this.descCounter = document.getElementById('descCounter');

    // Critical
    this.criticalInput = document.getElementById('id_is_critical');
    this.criticalCard = document.querySelector('.critical-toggle');

    // Upload area
    this.uploadArea = document.getElementById('uploadArea');
    this.uploadPreview = document.getElementById('uploadPreview');
    this.browseBtn = document.getElementById('browseBtn');
    this.fileCount = document.getElementById('fileCount');
    this.totalSize = document.getElementById('totalSize');

    // Attachments file input (inside uploadArea but hidden off-screen)
    this.fileInput = this.uploadArea
      ? (this.uploadArea.querySelector('input[type="file"]') || document.getElementById('id_files'))
      : document.getElementById('id_files');

    // Voice fields
    this.voiceTitleInput =
      document.getElementById('id_voice_title') ||
      document.querySelector('input[name="title"][id*="voice"]') ||
      document.querySelector('input[name="voice_title"]') ||
      null;

    this.voiceAudioInput =
      document.getElementById('id_voice_audio') ||
      document.getElementById('id_audio') ||
      document.querySelector('input[type="file"][name="audio"]') ||
      null;

    this.voiceDurationInput =
      document.getElementById('id_voice_duration') ||
      document.getElementById('id_voice_duration_seconds') ||
      document.getElementById('id_duration_seconds') ||
      document.querySelector('input[name="duration_seconds"]') ||
      null;

    // OUTER voice group
    this.voiceGroupOuter = null;
    if (this.voiceAudioInput) {
      const grid = this.voiceAudioInput.closest('.form-grid');
      this.voiceGroupOuter = (grid && grid.closest('.input-group')) || this.voiceAudioInput.closest('.input-group');
    }

    // Runtime
    this.files = [];
    this.isSubmitting = false;
    this.formChanged = false;
    this.currentStep = 1;
    this.totalSteps = 3;

    // Detect DataTransfer support (needed for curated multi-file UI)
    this.supportsDataTransfer = this._checkDataTransferSupport();

    // Limits (attachments) - aligned with backend
    this.MAX_FILE_SIZE = 10 * 1024 * 1024;
    this.MAX_FILES = 10;

    this.ALLOWED_EXTS = ['pdf', 'jpg', 'jpeg', 'png', 'gif', 'webp'];
    this.ALLOWED_TYPES = [
      'application/pdf',
      'application/x-pdf',
      'image/jpeg',
      'image/jpg',
      'image/pjpeg',
      'image/png',
      'image/x-png',
      'image/gif',
      'image/webp'
    ];

    // Limits (voice)
    this.VOICE_MAX_SIZE = 25 * 1024 * 1024;
    this.VOICE_ALLOWED_EXTS = ['webm', 'ogg', 'wav', 'mp3', 'm4a', 'aac'];

    // Limits (text)
    this.MAX_TITLE_LENGTH = this._readMaxLen(this.titleInput, 200);
    this.MAX_NOTES_LENGTH = this._readMaxLen(this.notesInput, 5000);
    this.MAX_DESC_LENGTH = this._readMaxLen(this.descriptionInput, 500);

    // RTE state
    this._notesLastGoodHtml = '';
    this._notesLimitWarned = false;

    // Voice state
    this.voice = {
      supported: false,
      recording: false,
      mediaRecorder: null,
      stream: null,
      chunks: [],
      startAt: 0,
      timer: null,
      seconds: 0,
      blobUrl: null,
      mimeType: '',
      file: null
    };

    // Voice UI refs
    this.voicePreview = null;
    this.voiceStatus = null;
    this.voiceRecordBtn = null;
    this.voiceStopBtn = null;
    this.voiceClearBtn = null;
    this.voiceDownloadLink = null;
  }

  _checkDataTransferSupport() {
    try {
      const dt = new DataTransfer();
      return !!dt && !!dt.items;
    } catch (_) {
      return false;
    }
  }

  _readMaxLen(inputEl, fallback) {
    try {
      if (!inputEl) return fallback;
      const ml = parseInt(inputEl.getAttribute('maxlength') || '', 10);
      return Number.isFinite(ml) && ml > 0 ? ml : fallback;
    } catch (_) {
      return fallback;
    }
  }

  // -------------------------
  // Initial Step Logic
  // -------------------------
  getInitialStep() {
    for (let s = 1; s <= this.totalSteps; s++) {
      const sec = document.querySelector(`[data-section="${s}"]`);
      if (!sec) continue;
      if (sec.querySelector('.input-group.error, .form-error, .error-text')) return s;
    }
    const raw = this.currentSection?.value;
    const step = parseInt(raw, 10);
    return Number.isFinite(step) && step >= 1 && step <= this.totalSteps ? step : 1;
  }

  // -------------------------
  // Select2
  // -------------------------
  initSelect2() {
    if (!window.$?.fn?.select2) return;

    const dropdownParent = $(document.body);

    const initSelect = (selector, options = {}) => {
      const $el = $(selector);
      if (!$el.length) return;
      if ($el.hasClass('select2-hidden-accessible')) return;

      const config = {
        width: '100%',
        placeholder: options.placeholder || 'Select...',
        allowClear: !$el.prop('required'),
        minimumResultsForSearch: 6,
        dropdownParent,
        ...options
      };

      $el.select2(config);

      $el.on('change.select2', () => {
        this.clearClientError($el[0]);
        this.markFormChanged();
        this.updateProgress();
        this.validateSection(this.currentStep);
      });
    };

    initSelect('#id_patient', { placeholder: 'Search patient by name or ID...', minimumResultsForSearch: 0 });
    initSelect('#id_doctor', { placeholder: 'Select responsible physician...', minimumResultsForSearch: 0 });
    initSelect('#id_archive_type', { placeholder: 'Select record type...', minimumResultsForSearch: 0 });
  }

  // -------------------------
  // File Upload
  // -------------------------
  initFileUpload() {
    if (!this.uploadArea || !this.fileInput) return;

    this.uploadArea.addEventListener('click', (e) => {
      if (e.target.closest('.file-remove')) return;
      if (e.target.closest('#browseBtn')) return;
      this.fileInput.click();
    });

    this.uploadArea.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        this.fileInput.click();
      }
    });

    this.browseBtn?.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.fileInput.click();
    });

    // Drag events
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((eventName) => {
      this.uploadArea.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
      });
    });

    ['dragenter', 'dragover'].forEach((eventName) => {
      this.uploadArea.addEventListener(eventName, () => this.uploadArea.classList.add('dragover'));
    });

    ['dragleave', 'drop'].forEach((eventName) => {
      this.uploadArea.addEventListener(eventName, () => this.uploadArea.classList.remove('dragover'));
    });

    this.uploadArea.addEventListener('drop', (e) => {
      const files = Array.from(e.dataTransfer.files || []);
      if (files.length) this.handleFiles(files);
    });

    // ✅ IMPORTANT FIX: DO NOT clear fileInput.value AFTER handleFiles()
    // because handleFiles() will sync DataTransfer -> input.files.
    // Clearing afterward wipes it.
    this.fileInput.addEventListener('change', (e) => {
      const picked = Array.from(e.target.files || []);
      if (!picked.length) return;

      // Optional: allow selecting the same file again later
      // Clear BEFORE we process (only safe if DataTransfer is supported)
      if (this.supportsDataTransfer) {
        try { this.fileInput.value = ''; } catch (_) {}
      }

      this.handleFiles(picked);
    });
  }

  handleFiles(newFiles) {
    if (!newFiles.length) return;

    const errors = [];
    const validFiles = [];

    const remainingSlots = this.MAX_FILES - this.files.length;
    if (remainingSlots <= 0) {
      this.showNotification(`Maximum ${this.MAX_FILES} files allowed`, 'error');
      return;
    }

    if (newFiles.length > remainingSlots) {
      newFiles = newFiles.slice(0, remainingSlots);
      this.showNotification(`Limited to ${remainingSlots} files (max ${this.MAX_FILES})`, 'warning');
    }

    for (const file of newFiles) {
      const validation = this.validateFile(file);
      if (!validation.valid) {
        errors.push(validation.error);
        continue;
      }

      const isDuplicate = this.files.some(
        (f) => f.name === file.name && f.size === file.size && f.lastModified === file.lastModified
      );

      if (!isDuplicate) validFiles.push(file);
      else errors.push(`"${file.name}" is already added`);
    }

    errors.forEach((m) => this.showNotification(m, 'error'));

    if (validFiles.length) {
      this.files.push(...validFiles);

      // Keep input.files in sync
      this.syncFileInput();

      this.renderFilePreviews();
      this.updateFileStats();
      this.markFormChanged();
      this.updateProgress();

      this.showNotification(`${validFiles.length} file(s) added successfully`, 'success');
    }
  }

  validateFile(file) {
    if (file.size > this.MAX_FILE_SIZE) {
      return { valid: false, error: `"${file.name}" exceeds ${this.formatFileSize(this.MAX_FILE_SIZE)} limit` };
    }

    const ext = file.name.split('.').pop()?.toLowerCase() || '';
    const type = String(file.type || '').toLowerCase();

    const typeOk = type ? this.ALLOWED_TYPES.includes(type) : false;
    const extOk = this.ALLOWED_EXTS.includes(ext);

    // Accept if either is OK (browsers sometimes give empty/odd MIME)
    if (!typeOk && !extOk) {
      return { valid: false, error: `"${file.name}" has unsupported type. Allowed: ${this.ALLOWED_EXTS.join(', ')}` };
    }

    const dangerousExts = ['exe', 'bat', 'cmd', 'sh', 'js', 'vbs', 'scr', 'msi', 'dmg', 'app'];
    if (dangerousExts.includes(ext)) {
      return { valid: false, error: `"${file.name}" is not allowed for security reasons` };
    }

    return { valid: true };
  }

  syncFileInput() {
    if (!this.fileInput) return;

    // If DataTransfer is not supported, we cannot curate input.files reliably
    if (!this.supportsDataTransfer) {
      this.showNotification('Your browser does not support advanced multi-file syncing. Please select files once before submit.', 'warning');
      return;
    }

    try {
      const dt = new DataTransfer();
      this.files.forEach((f) => dt.items.add(f));
      this.fileInput.files = dt.files;
    } catch (err) {
      this.log('syncFileInput failed:', err);
    }
  }

  renderFilePreviews() {
    if (!this.uploadPreview) return;

    this.uploadPreview.innerHTML = '';
    if (this.files.length === 0) return;

    const frag = document.createDocumentFragment();
    this.files.forEach((file, idx) => frag.appendChild(this.createFileCard(file, idx)));
    this.uploadPreview.appendChild(frag);
  }

  createFileCard(file, index) {
    const card = document.createElement('div');
    card.className = 'file-card';
    card.setAttribute('role', 'listitem');

    let iconClass = 'fa-file';
    if (String(file.type || '').toLowerCase().includes('pdf')) iconClass = 'fa-file-pdf';
    else if (String(file.type || '').toLowerCase().startsWith('image/')) iconClass = 'fa-file-image';

    const size = this.formatFileSize(file.size);
    const name = this.escapeHtml(file.name);

    card.innerHTML = `
      <div class="file-icon" aria-hidden="true"><i class="fas ${iconClass}"></i></div>
      <div class="file-info">
        <h4 title="${name}">${name}</h4>
        <p>${size}</p>
      </div>
      <button type="button" class="file-remove" aria-label="Remove ${name}" data-index="${index}">
        <i class="fas fa-times" aria-hidden="true"></i>
      </button>
    `;

    card.querySelector('.file-remove').addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.removeFile(index);
    });

    return card;
  }

  removeFile(index) {
    if (index < 0 || index >= this.files.length) return;

    const removed = this.files.splice(index, 1)[0];

    this.syncFileInput();
    this.renderFilePreviews();
    this.updateFileStats();

    this.markFormChanged();
    this.updateProgress();
    this.showNotification(`"${removed.name}" removed`, 'info');
  }

  updateFileStats() {
    if (!this.fileCount || !this.totalSize) return;
    const totalBytes = this.files.reduce((s, f) => s + f.size, 0);
    this.fileCount.textContent = `${this.files.length} file${this.files.length !== 1 ? 's' : ''}`;
    this.totalSize.textContent = this.formatFileSize(totalBytes);
  }

  // -------------------------
  // Rich Text (RTE)
  // -------------------------
  initRichText() {
    if (this.notesRte && this.notesInput) {
      this.initNotesRte();
      return;
    }
  }

  initNotesRte() {
    const tools = document.querySelector('.editor-tools');
    if (!tools) return;

    const initial = (this.notesInput.value || '').trim();
    this.notesRte.innerHTML = initial || '';
    this._notesLastGoodHtml = this.notesRte.innerHTML;

    const syncAndUpdate = () => {
      this.syncNotesToTextarea();
      this.updateNotesCounterFromRte();
      this.markFormChanged();
      this.updateProgress();
    };

    this.notesRte.addEventListener('input', () => {
      const len = this.getNotesPlainLength();

      if (len <= this.MAX_NOTES_LENGTH) {
        this._notesLastGoodHtml = this.notesRte.innerHTML;
        this._notesLimitWarned = false;
      } else {
        this.notesRte.innerHTML = this._notesLastGoodHtml;
        this.placeCaretAtEnd(this.notesRte);

        if (!this._notesLimitWarned) {
          this._notesLimitWarned = true;
          this.showNotification(`Clinical notes max is ${this.MAX_NOTES_LENGTH} characters`, 'warning');
        }
      }

      syncAndUpdate();
    });

    // toolbar
    tools.addEventListener('mousedown', (e) => {
      if (e.target.closest('.tool-btn')) e.preventDefault();
    });

    tools.addEventListener('click', (e) => {
      const btn = e.target.closest('.tool-btn');
      if (!btn) return;
      e.preventDefault();

      const cmd = btn.dataset.command;
      if (!cmd) return;

      this.notesRte.focus();

      if (cmd === 'h3') document.execCommand('formatBlock', false, 'h3');
      else if (cmd === 'clear') {
        document.execCommand('removeFormat');
        document.execCommand('formatBlock', false, 'p');
      } else {
        document.execCommand(cmd, false, null);
      }

      syncAndUpdate();
    });

    this.syncNotesToTextarea();
    this.updateNotesCounterFromRte();
  }

  syncNotesToTextarea() {
    if (!this.notesInput) return;
    if (this.notesRte) this.notesInput.value = (this.notesRte.innerHTML || '').trim();
  }

  getNotesPlainText() {
    if (this.notesRte) return (this.notesRte.innerText || '').replace(/\u00A0/g, ' ');
    return this.notesInput?.value || '';
  }

  getNotesPlainLength() {
    return this.getNotesPlainText().trimEnd().length;
  }

  updateNotesCounterFromRte() {
    if (!this.notesCounter) return;
    const len = this.getNotesPlainLength();
    this.notesCounter.textContent = `${len}/${this.MAX_NOTES_LENGTH}`;
  }

  placeCaretAtEnd(el) {
    try {
      el.focus();
      const range = document.createRange();
      range.selectNodeContents(el);
      range.collapse(false);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    } catch (_) {}
  }

  // -------------------------
  // Critical Toggle
  // -------------------------
  initCriticalToggle() {
    if (!this.criticalInput) return;

    const card = this.criticalCard || this.criticalInput.closest('.critical-toggle');
    if (!card) return;

    card.addEventListener('click', (e) => {
      if (e.target.closest('input, label')) return;
      this.criticalInput.checked = !this.criticalInput.checked;
      this.criticalInput.dispatchEvent(new Event('change', { bubbles: true }));
    });

    this.criticalInput.addEventListener('change', () => {
      this.markFormChanged();
      this.updateProgress();
    });
  }

  // -------------------------
  // Voice Note (Upload + Record)  (kept minimal but compatible)
  // -------------------------
  initVoiceNote() {
    if (!this.voiceAudioInput || !this.voiceGroupOuter) return;

    if (this.voiceGroupOuter.getAttribute('data-voice-initialized') === '1') return;
    this.voiceGroupOuter.setAttribute('data-voice-initialized', '1');

    this.voice.supported = !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);

    // UI
    const ui = document.createElement('div');
    ui.className = 'voice-ui';

    const row = document.createElement('div');
    row.style.display = 'flex';
    row.style.gap = '10px';
    row.style.flexWrap = 'wrap';

    const recordBtn = document.createElement('button');
    recordBtn.type = 'button';
    recordBtn.className = 'btn btn-secondary';
    recordBtn.innerHTML = `<i class="fas fa-microphone"></i><span>Record</span>`;

    const stopBtn = document.createElement('button');
    stopBtn.type = 'button';
    stopBtn.className = 'btn btn-secondary';
    stopBtn.disabled = true;
    stopBtn.innerHTML = `<i class="fas fa-stop"></i><span>Stop</span>`;

    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'btn btn-outline';
    clearBtn.innerHTML = `<i class="fas fa-trash"></i><span>Clear</span>`;

    row.appendChild(recordBtn);
    row.appendChild(stopBtn);
    row.appendChild(clearBtn);

    const preview = document.createElement('audio');
    preview.controls = true;
    preview.style.width = '100%';
    preview.style.marginTop = '10px';
    preview.hidden = true;

    const status = document.createElement('div');
    status.style.marginTop = '8px';
    status.style.fontSize = '12px';
    status.style.color = 'var(--gray-600)';

    ui.appendChild(row);
    ui.appendChild(preview);
    ui.appendChild(status);

    this.voiceGroupOuter.appendChild(ui);

    this.voicePreview = preview;
    this.voiceStatus = status;
    this.voiceRecordBtn = recordBtn;
    this.voiceStopBtn = stopBtn;
    this.voiceClearBtn = clearBtn;

    if (!this.voice.supported) {
      recordBtn.disabled = true;
      status.textContent = 'Recording not supported in this browser. You can upload an audio file instead.';
    }

    // Validate uploaded voice
    this.voiceAudioInput.addEventListener('change', () => {
      const f = this.voiceAudioInput.files?.[0];
      if (!f) return;

      const ok = this.validateVoiceFile(f);
      if (!ok.valid) {
        this.showNotification(ok.error, 'error');
        this.voiceAudioInput.value = '';
        this.clearVoicePreview();
        return;
      }

      const url = URL.createObjectURL(f);
      this.voice.blobUrl = url;
      this.voicePreview.src = url;
      this.voicePreview.hidden = false;
      status.textContent = `Selected: ${f.name}`;

      this.voicePreview.onloadedmetadata = () => {
        const dur = Number.isFinite(this.voicePreview.duration) ? Math.round(this.voicePreview.duration) : 0;
        if (this.voiceDurationInput) this.voiceDurationInput.value = dur ? String(dur) : '';
      };

      this.markFormChanged();
      this.updateProgress();
    });

    recordBtn.addEventListener('click', (e) => {
      e.preventDefault();
      this.startVoiceRecording();
    });

    stopBtn.addEventListener('click', (e) => {
      e.preventDefault();
      this.stopVoiceRecording();
    });

    clearBtn.addEventListener('click', (e) => {
      e.preventDefault();
      this.clearVoiceAll();
    });

    window.addEventListener('pagehide', () => this.cleanupVoiceResources());
  }

  validateVoiceFile(file) {
    if (!file) return { valid: true };

    if (file.size > this.VOICE_MAX_SIZE) {
      return { valid: false, error: `Voice file exceeds ${this.formatFileSize(this.VOICE_MAX_SIZE)} limit` };
    }

    const ext = (file.name.split('.').pop() || '').toLowerCase();
    const type = String(file.type || '').toLowerCase();

    const extOk = this.VOICE_ALLOWED_EXTS.includes(ext);
    const typeOk = type.startsWith('audio/') || type === 'video/webm' || type === 'video/mp4';

    if (!extOk && !typeOk) {
      return { valid: false, error: `Unsupported voice type. Allowed: ${this.VOICE_ALLOWED_EXTS.join(', ')}` };
    }

    return { valid: true };
  }

  getBestAudioMimeType() {
    if (!window.MediaRecorder?.isTypeSupported) return '';
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/ogg', 'audio/mp4'];
    for (const t of candidates) {
      if (MediaRecorder.isTypeSupported(t)) return t;
    }
    return '';
  }

  async startVoiceRecording() {
    if (!this.voice.supported || this.voice.recording) return;

    try {
      this.voiceStatus.textContent = 'Requesting microphone permission...';

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = this.getBestAudioMimeType();

      let recorder;
      try {
        recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      } catch (_) {
        recorder = new MediaRecorder(stream);
      }

      this.voice.stream = stream;
      this.voice.mediaRecorder = recorder;
      this.voice.chunks = [];
      this.voice.mimeType = recorder.mimeType || mimeType || '';

      recorder.ondataavailable = (ev) => {
        if (ev.data && ev.data.size > 0) this.voice.chunks.push(ev.data);
      };

      recorder.onstop = () => this.finalizeVoiceRecording();

      recorder.start(250);
      this.voice.recording = true;
      this.voice.startAt = Date.now();
      this.voice.seconds = 0;

      this.voiceRecordBtn.disabled = true;
      this.voiceStopBtn.disabled = false;

      this.voiceStatus.textContent = 'Recording...';
      this.voice.timer = setInterval(() => {
        this.voice.seconds += 1;
        this.voiceStatus.textContent = `Recording... ${this.voice.seconds}s`;
      }, 1000);

      this.markFormChanged();
      this.updateProgress();
    } catch (err) {
      this.voiceStatus.textContent = 'Microphone permission denied or unavailable.';
      this.showNotification('Cannot access microphone. Please allow permission or upload an audio file.', 'error');
      this.log('Voice getUserMedia error:', err);
    }
  }

  stopVoiceRecording() {
    if (!this.voice.mediaRecorder || !this.voice.recording) return;

    try { this.voice.mediaRecorder.stop(); } catch (_) {}

    this.voice.recording = false;
    this.voiceStopBtn.disabled = true;
    this.voiceRecordBtn.disabled = false;

    if (this.voice.timer) {
      clearInterval(this.voice.timer);
      this.voice.timer = null;
    }

    this.voiceStatus.textContent = 'Processing recording...';
  }

  finalizeVoiceRecording() {
    try { this.voice.stream?.getTracks?.().forEach((t) => t.stop()); } catch (_) {}

    const mime = this.voice.mimeType || 'audio/webm';
    const blob = new Blob(this.voice.chunks, { type: mime });

    const duration = this.voice.seconds || Math.round((Date.now() - this.voice.startAt) / 1000);
    if (this.voiceDurationInput) this.voiceDurationInput.value = duration ? String(duration) : '';

    const name = `voice-note-${Date.now()}.webm`;
    let file = null;
    try { file = new File([blob], name, { type: mime }); } catch (_) {}

    if (file) {
      const ok = this.validateVoiceFile(file);
      if (!ok.valid) {
        this.showNotification(ok.error, 'error');
        this.voiceStatus.textContent = 'Recording rejected by client rules.';
        return;
      }
      this._setFileInputFiles(this.voiceAudioInput, [file]);
      this.voice.file = file;
    }

    // preview
    if (this.voice.blobUrl) {
      try { URL.revokeObjectURL(this.voice.blobUrl); } catch (_) {}
      this.voice.blobUrl = null;
    }

    const url = URL.createObjectURL(blob);
    this.voice.blobUrl = url;
    this.voicePreview.src = url;
    this.voicePreview.hidden = false;

    if (this.voiceTitleInput && !String(this.voiceTitleInput.value || '').trim()) {
      this.voiceTitleInput.value = `Voice Note - ${new Date().toLocaleString()}`;
      this.voiceTitleInput.setAttribute('data-auto', '1');
    }

    this.voiceStatus.textContent = `Recorded: ${name} (${duration}s)`;

    this.markFormChanged();
    this.updateProgress();
    this.showNotification('Voice note recorded successfully', 'success');
  }

  _setFileInputFiles(input, files) {
    if (!input) return;
    if (!this.supportsDataTransfer) return;

    try {
      const dt = new DataTransfer();
      (files || []).forEach((f) => dt.items.add(f));
      input.files = dt.files;
    } catch (e) {
      this.log('Unable to set file input programmatically:', e);
    }
  }

  cleanupVoiceResources() {
    try { this.voice.stream?.getTracks?.().forEach((t) => t.stop()); } catch (_) {}
    this.voice.stream = null;
    this.voice.mediaRecorder = null;
    this.voice.chunks = [];
  }

  clearVoicePreview() {
    if (this.voice.blobUrl) {
      try { URL.revokeObjectURL(this.voice.blobUrl); } catch (_) {}
      this.voice.blobUrl = null;
    }
    if (this.voicePreview) {
      try { this.voicePreview.pause?.(); } catch (_) {}
      this.voicePreview.removeAttribute('src');
      try { this.voicePreview.load?.(); } catch (_) {}
      this.voicePreview.hidden = true;
    }
    if (this.voiceDurationInput) this.voiceDurationInput.value = '';
    if (this.voiceStatus) this.voiceStatus.textContent = '';
    this.voice.file = null;
  }

  clearVoiceAll() {
    if (this.voice.recording) this.stopVoiceRecording();
    this.cleanupVoiceResources();

    if (this.voiceAudioInput) this.voiceAudioInput.value = '';
    if (this.voiceDurationInput) this.voiceDurationInput.value = '';

    if (this.voiceTitleInput && this.voiceTitleInput.getAttribute('data-auto') === '1') {
      this.voiceTitleInput.value = '';
      this.voiceTitleInput.removeAttribute('data-auto');
    }

    this.clearVoicePreview();
    this.markFormChanged();
    this.updateProgress();
    this.showNotification('Voice note cleared', 'info');
  }

  // -------------------------
  // Character Counters
  // -------------------------
  initCharacterCounters() {
    if (this.titleInput && this.titleCounter) {
      this.titleInput.addEventListener('input', () => {
        this.updateCharacterCounter(this.titleInput, this.titleCounter, this.MAX_TITLE_LENGTH);
        this.markFormChanged();
        this.updateProgress();
      });
      this.updateCharacterCounter(this.titleInput, this.titleCounter, this.MAX_TITLE_LENGTH);
    }

    if (this.descriptionInput && this.descCounter) {
      this.descriptionInput.addEventListener('input', () => {
        this.updateCharacterCounter(this.descriptionInput, this.descCounter, this.MAX_DESC_LENGTH);
        this.markFormChanged();
        this.updateProgress();
      });
      this.updateCharacterCounter(this.descriptionInput, this.descCounter, this.MAX_DESC_LENGTH);
    }
  }

  updateCharacterCounter(input, counterEl, max) {
    if (!input || !counterEl) return;
    const len = input.value.length;
    counterEl.textContent = `${len}/${max}`;
  }

  // -------------------------
  // Step Navigation
  // -------------------------
  initStepNavigation() {
    this.stepperItems.forEach((item) => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const step = parseInt(item.dataset.step, 10);
        this.goToStep(step);
      });
    });

    document.querySelectorAll('.btn-next').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const nextStep = parseInt(btn.dataset.next, 10);
        if (this.validateSection(this.currentStep)) this.goToStep(nextStep);
      });
    });

    document.querySelectorAll('.btn-prev').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const prev = parseInt(btn.dataset.prev, 10);
        this.goToStep(prev);
      });
    });
  }

  goToStep(step, opts = {}) {
    if (step < 1 || step > this.totalSteps) return;
    const { focus = true } = opts;

    this.currentStep = step;
    if (this.currentSection) this.currentSection.value = String(step);

    this.sections.forEach((sec) => {
      const s = parseInt(sec.dataset.section, 10);
      const active = s === step;
      sec.classList.toggle('active', active);
      sec.setAttribute('aria-hidden', active ? 'false' : 'true');
    });

    this.stepperItems.forEach((item) => {
      const s = parseInt(item.dataset.step, 10);
      item.classList.toggle('active', s <= step);
      if (s === step) item.setAttribute('aria-current', 'step');
      else item.removeAttribute('aria-current');
    });

    if (focus) {
      const activeSection = document.querySelector(`[data-section="${step}"]`);
      const first = activeSection?.querySelector('input:not([type="hidden"]), select, textarea, [contenteditable="true"], button');
      first?.focus?.();
    }

    this.updateProgress();
  }

  // -------------------------
  // Client Errors (simple)
  // -------------------------
  clearAllClientErrors(scope) {
    if (!scope) return;
    scope.querySelectorAll('[data-client-error="1"]').forEach((el) => el.remove());
    scope.querySelectorAll('.input-group[data-client-error-group="1"]').forEach((g) => {
      g.classList.remove('error');
      g.removeAttribute('data-client-error-group');
    });
  }

  markClientError(element, message) {
    const group = element?.closest?.('.input-group');
    if (!group) return;

    group.classList.add('error');
    group.setAttribute('data-client-error-group', '1');

    group.querySelectorAll('[data-client-error="1"]').forEach((el) => el.remove());

    const div = document.createElement('div');
    div.className = 'error-text';
    div.textContent = message;
    div.setAttribute('data-client-error', '1');
    div.setAttribute('role', 'alert');
    group.appendChild(div);
  }

  clearClientError(element) {
    const group = element?.closest?.('.input-group');
    if (!group) return;

    group.querySelectorAll('[data-client-error="1"]').forEach((el) => el.remove());

    if (group.getAttribute('data-client-error-group') === '1') {
      group.classList.remove('error');
      group.removeAttribute('data-client-error-group');
    }
  }

  scrollToFirstError(container) {
    const first = container.querySelector('.input-group.error');
    if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  validateSection(section) {
    let ok = true;
    const sec = document.querySelector(`[data-section="${section}"]`);
    if (!sec) return true;

    this.clearAllClientErrors(sec);
    this.syncNotesToTextarea();

    if (section === 1) {
      if (this.patientSelect && !String(this.patientSelect.value || '').trim()) {
        this.markClientError(this.patientSelect, 'Patient selection is required');
        ok = false;
      }
    }

    if (section === 2) {
      if (this.titleInput && !String(this.titleInput.value || '').trim()) {
        this.markClientError(this.titleInput, 'Record title is required');
        ok = false;
      }
      if (this.typeSelect && !String(this.typeSelect.value || '').trim()) {
        this.markClientError(this.typeSelect, 'Record type is required');
        ok = false;
      }
      if (this.getNotesPlainLength() > this.MAX_NOTES_LENGTH) {
        this.markClientError(this.notesRte || this.notesInput, `Notes must be <= ${this.MAX_NOTES_LENGTH} characters`);
        ok = false;
      }
    }

    if (section === 3) {
      if (this.descriptionInput && this.descriptionInput.value.length > this.MAX_DESC_LENGTH) {
        this.markClientError(this.descriptionInput, `Description must be <= ${this.MAX_DESC_LENGTH} characters`);
        ok = false;
      }
      if (this.voice?.recording) {
        this.showNotification('Please stop voice recording first', 'warning');
        ok = false;
      }
    }

    if (!ok) {
      this.showNotification('Please fix the errors before continuing', 'error');
      this.scrollToFirstError(sec);
    }

    return ok;
  }

  // -------------------------
  // Submit Validation
  // -------------------------
  initFormValidation() {
    this.form.addEventListener('submit', (e) => {
      this.syncNotesToTextarea();

      // Ensure attachments input matches our curated list
      this.syncFileInput();

      if (this.voice?.recording) {
        e.preventDefault();
        this.goToStep(3);
        this.showNotification('Stop voice recording before submitting', 'error');
        return;
      }

      if (this.isSubmitting) {
        e.preventDefault();
        this.showNotification('Form is already being submitted', 'warning');
        return;
      }

      let ok = true;
      for (let i = 1; i <= this.totalSteps; i++) {
        if (!this.validateSection(i)) {
          ok = false;
          this.goToStep(i);
          break;
        }
      }

      if (this.files.length > this.MAX_FILES) {
        ok = false;
        this.showNotification(`Maximum ${this.MAX_FILES} files allowed`, 'error');
        this.goToStep(3);
      }

      if (!ok) {
        e.preventDefault();
        this.showNotification('Please fix all errors before submitting', 'error');
        return;
      }

      this.setState('submitting');
      this.setLoadingState(true);
    });
  }

  // -------------------------
  // Event Listeners
  // -------------------------
  initEventListeners() {
    this.resetBtn?.addEventListener('click', (e) => {
      e.preventDefault();
      this.confirmReset();
    });

    this.cancelBtn?.addEventListener('click', (e) => {
      if (this.formChanged) {
        e.preventDefault();
        if (confirm('You have unsaved changes. Are you sure you want to cancel?')) {
          window.location.href = this.cancelBtn.href;
        }
      }
    });

    window.addEventListener('beforeunload', (e) => {
      if (this.formChanged && !this.isSubmitting) {
        e.preventDefault();
        e.returnValue = 'You have unsaved changes. Are you sure you want to leave?';
      }
    });
  }

  bindFormChanges() {
    const inputs = this.form.querySelectorAll('input, select, textarea');

    inputs.forEach((input) => {
      const isSelect = input.tagName === 'SELECT';
      const isFile = input.type === 'file';
      const isCheck = input.type === 'checkbox' || input.type === 'radio';
      const ev = (isSelect || isFile || isCheck) ? 'change' : 'input';

      input.addEventListener(ev, () => {
        this.markFormChanged();
        this.updateProgress();
        this.clearClientError(input);
      });
    });

    if (this.notesRte) {
      this.notesRte.addEventListener('input', () => {
        this.markFormChanged();
        this.updateProgress();
      });
    }
  }

  markFormChanged() {
    if (!this.formChanged) {
      this.formChanged = true;
      this.form.dataset.unsaved = 'true';
      this.setState('dirty');
    }
  }

  // -------------------------
  // Reset
  // -------------------------
  confirmReset() {
    if (!this.formChanged) return this.resetForm();
    if (confirm('Are you sure you want to reset the form? All entered data will be lost.')) this.resetForm();
  }

  resetForm() {
    if (this.voice?.recording) this.stopVoiceRecording();

    this.form.reset();

    if (window.$?.fn?.select2) {
      ['#id_patient', '#id_doctor', '#id_archive_type'].forEach((sel) => {
        const $el = $(sel);
        if ($el.length && $el.hasClass('select2-hidden-accessible')) $el.val(null).trigger('change.select2');
      });
    }

    if (this.notesRte) {
      this.notesRte.innerHTML = '';
      this._notesLastGoodHtml = '';
      this._notesLimitWarned = false;
      this.syncNotesToTextarea();
      this.updateNotesCounterFromRte();
    }

    this.files = [];
    this.syncFileInput();
    this.renderFilePreviews();
    this.updateFileStats();

    if (this.voiceAudioInput) this.clearVoiceAll();

    this.clearAllClientErrors(this.form);
    this.setLoadingState(false);

    this.formChanged = false;
    delete this.form.dataset.unsaved;

    this.goToStep(1);
    this.updateProgress();
    this.setState('reset');

    this.showNotification('Form reset successfully', 'info');
  }

  // -------------------------
  // Progress
  // -------------------------
  updateProgress() {
    if (!this.progressFill || !this.progressText) return;

    let total = 3;
    let done = 0;

    if (String(this.patientSelect?.value || '').trim()) done++;
    if (String(this.titleInput?.value || '').trim()) done++;
    if (String(this.typeSelect?.value || '').trim()) done++;

    const pct = total ? Math.round((done / total) * 100) : 100;
    this.progressFill.style.width = `${pct}%`;
    this.progressText.textContent = `${pct}% complete`;
  }

  // -------------------------
  // Notifications
  // -------------------------
  initNotifications() {
    this.ensureMessageContainer();

    document.addEventListener('click', (e) => {
      const closeBtn = e.target.closest('.message-close');
      if (!closeBtn) return;
      const msg = closeBtn.closest('.message');
      if (msg) this.closeNotification(msg);
    });

    document.querySelectorAll('.message').forEach((msg) => {
      if (!msg.classList.contains('message-error')) this.autoDismissNotification(msg);
    });
  }

  ensureMessageContainer() {
    let c = document.querySelector('.message-container');
    if (c) return c;

    c = document.createElement('div');
    c.className = 'message-container';
    c.setAttribute('aria-live', 'polite');
    c.setAttribute('aria-atomic', 'true');

    const root = document.querySelector('.medical-record-creator') || document.body;
    root.insertBefore(c, root.firstChild);
    return c;
  }

  showNotification(message, type = 'info', duration = 5000) {
    const container = this.ensureMessageContainer();

    const n = document.createElement('div');
    n.className = `message message-${type}`;
    n.setAttribute('role', 'alert');

    const icon = {
      success: 'check-circle',
      error: 'exclamation-circle',
      warning: 'exclamation-triangle',
      info: 'info-circle'
    }[type] || 'info-circle';

    n.innerHTML = `
      <i class="fas fa-${icon}" aria-hidden="true"></i>
      <span>${this.escapeHtml(String(message))}</span>
      <button type="button" class="message-close" aria-label="Close notification">
        <i class="fas fa-times" aria-hidden="true"></i>
      </button>
    `;

    container.appendChild(n);

    if (type !== 'error') this.autoDismissNotification(n, duration);
  }

  closeNotification(n) {
    n.classList.add('fading');
    setTimeout(() => n.remove(), 250);
  }

  autoDismissNotification(n, duration = 5000) {
    setTimeout(() => {
      if (n.parentNode) this.closeNotification(n);
    }, duration);
  }

  // -------------------------
  // Loading State
  // -------------------------
  setLoadingState(loading) {
    this.isSubmitting = loading;
    this.form.classList.toggle('loading', loading);

    const buttons = this.form.querySelectorAll('button');
    buttons.forEach((btn) => {
      if (btn === this.submitBtn) return;
      btn.disabled = loading;
    });

    if (this.submitBtn) {
      this.submitBtn.disabled = loading;

      if (loading) {
        this.submitBtn.dataset.originalHTML = this.submitBtn.innerHTML;
        this.submitBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i><span>Saving...</span>`;
      } else {
        this.submitBtn.innerHTML = this.submitBtn.dataset.originalHTML || this.submitBtn.innerHTML;
      }
    }
  }

  // -------------------------
  // Utility
  // -------------------------
  formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  log(...args) {
    if (this.DEBUG) console.log('[MedicalRecordCreator]', ...args);
  }
}

// Init
document.addEventListener('DOMContentLoaded', () => {
  if (!document.getElementById('medicalRecordForm')) return;

  try {
    new MedicalRecordCreator();
    console.log('Medical Record Creator loaded successfully');
  } catch (err) {
    console.error('Failed to initialize Medical Record Creator:', err);
  }
});
