// File: static/js/appointments/secretary_settings.js

document.addEventListener('DOMContentLoaded', () => {
  // -----------------------
  // Helpers
  // -----------------------
  const $ = (sel, root = document) => root.querySelector(sel);

  const isArabic = (document.documentElement.lang || 'en').toLowerCase().startsWith('ar');
  const STR = isArabic
    ? {
        mismatch: '❌ كلمة المرور الجديدة والتأكيد غير متطابقين.',
        matchOk: '✓ كلمات المرور متطابقة',
        strength: 'القوة',
        reuseWarn: 'تجنّبي استخدام نفس كلمة المرور الحالية.',
        show: 'إظهار',
        hide: 'إخفاء',
        saving: 'جارٍ الحفظ...',
        weakConfirm: 'كلمة المرور ضعيفة. هل تريدين المتابعة؟',
        levels: ['', 'ضعيفة', 'متوسطة', 'جيدة', 'قوية', 'ممتازة'],
        tooShort: (len) => `الطول أقل من ${len} أحرف.`,
        crackTime: (t) => `وقت كسر تقديري: ${t}`,
        alertWeak: 'كلمة المرور ضعيفة.'
      }
    : {
        mismatch: '❌ Passwords do not match.',
        matchOk: '✓ Passwords match',
        strength: 'Strength',
        reuseWarn: 'Avoid reusing the current password.',
        show: 'Show',
        hide: 'Hide',
        saving: 'Saving...',
        weakConfirm: 'Your password is weak. Continue?',
        levels: ['', 'Weak', 'Fair', 'Good', 'Strong', 'Excellent'],
        tooShort: (len) => `Length below ${len} chars.`,
        crackTime: (t) => `Estimated crack time: ${t}`,
        alertWeak: 'Weak password.'
      };

  function normalizeValue(val, normalize = true) {
    if (!normalize) return val;
    return (val || '').replace(/[\u200B-\u200D\u200E\u200F\uFEFF]/g, '');
  }

  function setBtnLoading(btn, text) {
    if (!btn) return;
    btn.classList.add('loading');
    btn.disabled = true;
    btn.dataset.originalHtml = btn.dataset.originalHtml || btn.innerHTML;
    btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span> ${text}`;
  }

  function clearBtnLoading(btn) {
    if (!btn) return;
    btn.classList.remove('loading');
    btn.disabled = false;
    if (btn.dataset.originalHtml) btn.innerHTML = btn.dataset.originalHtml;
  }

  function updateCriteriaItem(el, ok) {
    if (!el) return;
    el.classList.toggle('valid', !!ok);
    el.classList.toggle('invalid', !ok);
    const icon = el.querySelector('.bi');
    if (icon) {
      icon.className = ok
        ? 'bi bi-check-circle-fill criteria-icon text-success'
        : 'bi bi-x-circle criteria-icon text-danger';
    }
  }

  // -----------------------
  // Floating alert (global)
  // -----------------------
  window.showAlert = function showAlert(message, type = 'success') {
    const alert = $('#floatingAlert');
    const alertMessage = $('#alertMessage');
    if (!alert || !alertMessage) return;

    alert.className = `floating-alert alert alert-${type} animate__animated animate__fadeInRight`;
    alertMessage.textContent = message || '';
    alert.classList.remove('d-none');

    setTimeout(window.hideAlert, 5000);
  };

  window.hideAlert = function hideAlert() {
    const alert = $('#floatingAlert');
    if (!alert) return;

    alert.classList.add('animate__fadeOutRight');
    setTimeout(() => {
      alert.classList.add('d-none');
      alert.classList.remove('animate__fadeOutRight');
    }, 450);
  };

  // -----------------------
  // Help modal (global)
  // -----------------------
  window.showHelpModal = function showHelpModal() {
    const modalEl = $('#helpModal');
    if (!modalEl) return;

    if (window.bootstrap && window.bootstrap.Modal) {
      const m = new window.bootstrap.Modal(modalEl);
      m.show();
    } else {
      // fallback
      modalEl.classList.add('show');
      modalEl.style.display = 'block';
    }
  };

  // -----------------------
  // Tooltips init (optional)
  // -----------------------
  try {
    if (window.bootstrap && window.bootstrap.Tooltip) {
      [...document.querySelectorAll('[data-bs-toggle="tooltip"]')].forEach((el) => {
        // eslint-disable-next-line no-new
        new window.bootstrap.Tooltip(el);
      });
    }
  } catch (e) {}

  // -----------------------
  // Profile form loading
  // -----------------------
  const profileForm = $('#profileForm');
  const profileSubmitBtn = $('#profileSubmitBtn');
  if (profileForm && profileSubmitBtn) {
    profileForm.addEventListener('submit', () => {
      setBtnLoading(profileSubmitBtn, STR.saving);
    });
  }

  // -----------------------
  // Password form logic
  // -----------------------
  const form = $('#passwordForm');
  if (!form) return;

  const cfg = {
    minLength: parseInt(form.getAttribute('data-min-length') || '8', 10),
    checkReuse: (form.getAttribute('data-check-reuse') || 'true').toLowerCase() === 'true',
    normalize: (form.getAttribute('data-normalize') || 'true').toLowerCase() === 'true'
  };

  const currentPw  = $('input[name="current_password"]', form);
  const newPw      = $('input[name="new_password"]', form);
  const confirmPw  = $('input[name="confirm_new_password"]', form);
  const submitBtn  = $('button[type="submit"]', form);

  const strengthEl = $('#passwordStrength');
  const matchEl    = $('#passwordMatch');

  const criteriaEls = {
    length: $('#criteria-length'),
    uppercase: $('#criteria-uppercase'),
    lowercase: $('#criteria-lowercase'),
    number: $('#criteria-number'),
    special: $('#criteria-special')
  };

  if (strengthEl) {
    strengthEl.setAttribute('aria-live', 'polite');
    strengthEl.setAttribute('aria-atomic', 'true');
  }

  function attachToggle(input) {
    if (!input) return;
    if (input.parentElement && input.parentElement.querySelector('.pw-toggle-btn')) return;

    const parent = input.parentElement;
    if (!parent) return;

    parent.classList.add('pw-wrapper', 'position-relative');

    // Password should be LTR
    input.style.direction = 'ltr';
    input.style.unicodeBidi = 'plaintext';

    // Avoid overlapping the right-side icon in your HTML
    input.style.paddingLeft = '4.2rem';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pw-toggle-btn btn btn-sm btn-outline-secondary';
    btn.textContent = STR.show;
    btn.setAttribute('aria-label', STR.show);
    btn.setAttribute('aria-pressed', 'false');

    Object.assign(btn.style, {
      position: 'absolute',
      top: '50%',
      left: '.6rem',
      transform: 'translateY(-50%)',
      fontSize: '.65rem',
      padding: '.25rem .55rem',
      zIndex: 6
    });

    btn.addEventListener('click', () => {
      const showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      btn.textContent = showing ? STR.show : STR.hide;
      btn.setAttribute('aria-label', showing ? STR.show : STR.hide);
      btn.setAttribute('aria-pressed', String(!showing));
    });

    parent.appendChild(btn);
  }

  function evalBasic(password) {
    const v = password || '';
    const hasLength = v.length >= cfg.minLength;
    const hasUppercase = /[A-Z]/.test(v);
    const hasLowercase = /[a-z]/.test(v);
    const hasNumber = /\d/.test(v);
    const hasSpecial = /[^A-Za-z0-9]/.test(v);

    updateCriteriaItem(criteriaEls.length, hasLength);
    updateCriteriaItem(criteriaEls.uppercase, hasUppercase);
    updateCriteriaItem(criteriaEls.lowercase, hasLowercase);
    updateCriteriaItem(criteriaEls.number, hasNumber);
    updateCriteriaItem(criteriaEls.special, hasSpecial);

    const basicScore = [hasLength, hasUppercase, hasLowercase, hasNumber, hasSpecial].filter(Boolean).length;
    const issues = [];
    if (!hasLength) issues.push(STR.tooShort(cfg.minLength));
    return { basicScore, issues, hasLength, hasUppercase, hasLowercase, hasNumber, hasSpecial };
  }

  function evaluateStrength(password) {
    const v = password || '';
    if (!v) return { score: 0, label: '', issues: [], crack: '' };

    const basic = evalBasic(v);

    // If zxcvbn exists, enhance score
    let advScore = 0;
    let crack = '';
    if (typeof window.zxcvbn === 'function') {
      const r = window.zxcvbn(v);
      advScore = (r && typeof r.score === 'number') ? r.score : 0; // 0..4
      crack = r?.crack_times_display?.offline_slow_hashing_1e4_per_second || '';
    }

    // Merge: keep range 0..5 (like your CSS data-level)
    const merged = Math.max(basic.basicScore, advScore + 1);
    const score = Math.max(0, Math.min(5, merged));
    const label = STR.levels[score] || '';

    return { score, label, issues: basic.issues, crack };
  }

  function renderStrength() {
    if (!strengthEl || !newPw) return;

    const { score, label, issues, crack } = evaluateStrength(newPw.value);
    strengthEl.dataset.level = String(score);

    let parts = [];
    if (label) parts.push(`${STR.strength}: ${label}`);
    if (issues.length) parts.push(issues.join(' | '));

    if (cfg.checkReuse && currentPw && currentPw.value && newPw.value && currentPw.value === newPw.value) {
      parts.push(STR.reuseWarn);
    }

    // show crack time (if zxcvbn available)
    if (crack) parts.push(STR.crackTime(crack));

    strengthEl.textContent = parts.join(' – ');
  }

  function setMatchState(ok, msg) {
    if (!matchEl) return;
    matchEl.textContent = msg || '';
    matchEl.className = ok ? 'password-match valid' : 'password-match invalid';
  }

  function validateMatch() {
    if (!newPw || !confirmPw) return true;

    const aRaw = newPw.value;
    const bRaw = confirmPw.value;

    if (!aRaw || !bRaw) {
      confirmPw.classList.remove('is-invalid');
      if (matchEl) {
        matchEl.textContent = '';
        matchEl.className = 'password-match';
      }
      return true;
    }

    const a = normalizeValue(aRaw, cfg.normalize);
    const b = normalizeValue(bRaw, cfg.normalize);

    if (a !== b) {
      confirmPw.classList.add('is-invalid');
      setMatchState(false, STR.mismatch);
      return false;
    }

    confirmPw.classList.remove('is-invalid');
    setMatchState(true, STR.matchOk);
    return true;
  }

  // Bind events
  const debounce = (fn, delay = 160) => {
    let t = null;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), delay);
    };
  };

  const strengthDebounced = debounce(renderStrength, 160);

  if (newPw) {
    ['input', 'change', 'blur', 'keyup', 'paste'].forEach(ev => {
      newPw.addEventListener(ev, () => {
        strengthDebounced();
        validateMatch();
      });
    });
  }

  if (confirmPw) {
    ['input', 'change', 'blur', 'keyup', 'paste'].forEach(ev => {
      confirmPw.addEventListener(ev, validateMatch);
    });
  }

  // toggles
  attachToggle(currentPw);
  attachToggle(newPw);
  attachToggle(confirmPw);

  // initial render
  renderStrength();
  validateMatch();

  // Submit behavior
  form.addEventListener('submit', (e) => {
    if (!validateMatch()) {
      e.preventDefault();
      confirmPw && confirmPw.focus();
      window.showAlert(STR.mismatch, 'danger');
      return;
    }

    // Weak confirm
    const { score } = evaluateStrength(newPw ? newPw.value : '');
    if (score < 2) {
      if (!confirm(STR.weakConfirm)) {
        e.preventDefault();
        return;
      }
    }

    setBtnLoading(submitBtn, STR.saving);

    // safety fallback in case of client-side hang
    setTimeout(() => {
      if (document.body.contains(submitBtn) && submitBtn.disabled) {
        clearBtnLoading(submitBtn);
      }
    }, 12000);
  });

  // Reset password form
  const resetPasswordBtn = $('#resetPasswordBtn');
  if (resetPasswordBtn) {
    resetPasswordBtn.addEventListener('click', () => {
      if (strengthEl) {
        strengthEl.textContent = '';
        strengthEl.dataset.level = '0';
      }
      if (matchEl) {
        matchEl.textContent = '';
        matchEl.className = 'password-match';
      }
      Object.values(criteriaEls).forEach((el) => {
        if (!el) return;
        el.classList.remove('valid');
        el.classList.add('invalid');
        const icon = el.querySelector('.bi');
        if (icon) icon.className = 'bi bi-x-circle criteria-icon text-danger';
      });
    });
  }

  // Expose helper (optional)
  window.PasswordSettingsHelper = {
    evaluateStrength,
    validateMatch,
    renderStrength,
    config: cfg
  };
});
