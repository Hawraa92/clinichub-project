document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('passwordForm');
  if (!form) return;

  const cfg = {
    minLength: parseInt(form.getAttribute('data-min-length') || '8', 10),
    checkReuse: (form.getAttribute('data-check-reuse') || 'true').toLowerCase() === 'true',
    normalize: (form.getAttribute('data-normalize') || 'true').toLowerCase() === 'true'
  };

  const isArabic = (document.documentElement.lang || 'en').toLowerCase().startsWith('ar');
  const STR = (isArabic ? {
    mismatch: '❌ كلمة المرور الجديدة والتأكيد غير متطابقين.',
    strength: 'القوة',
    reuseWarn: 'تجنّبي استخدام نفس كلمة المرور الحالية.',
    show: 'إظهار',
    hide: 'إخفاء',
    saving: 'جارٍ الحفظ...',
    levels: ['', 'ضعيفة', 'متوسطة', 'جيدة', 'قوية', 'ممتازة'],
    tooShort: length => `الطول أقل من ${length} أحرف.`
  } : {
    mismatch: '❌ Passwords do not match.',
    strength: 'Strength',
    reuseWarn: 'Avoid reusing the current password.',
    show: 'Show',
    hide: 'Hide',
    saving: 'Saving...',
    levels: ['', 'Weak', 'Fair', 'Good', 'Strong', 'Excellent'],
    tooShort: length => `Length below ${length} chars.`
  });

  const currentPw  = form.querySelector('input[name="current_password"]');
  const newPw      = form.querySelector('input[name="new_password"]');
  const confirmPw  = form.querySelector('input[name="confirm_new_password"]');
  const submitBtn  = form.querySelector('button[type="submit"]');
  const strengthEl = document.getElementById('passwordStrength');
  if (strengthEl) {
    strengthEl.setAttribute('aria-live','polite');
    strengthEl.setAttribute('aria-atomic','true');
  }

  let mismatchMsg = null;
  let debounceTimer = null;

  function ensureMismatchMsg() {
    if (!mismatchMsg && confirmPw && confirmPw.parentElement) {
      mismatchMsg = document.createElement('div');
      mismatchMsg.className = 'invalid-feedback d-block';
      mismatchMsg.style.display = 'none';
      mismatchMsg.setAttribute('aria-live', 'polite');
      mismatchMsg.textContent = STR.mismatch;
      confirmPw.parentElement.appendChild(mismatchMsg);
    }
  }

  function normalizeValue(val) {
    if (!cfg.normalize) return val;
    return val.replace(/[\u200B-\u200D\u200E\u200F\uFEFF]/g, '');
  }

  function evaluateStrength(v) {
    if (!v) return {score:0,label:'', issues:[]};
    let s=0;
    if (v.length >= cfg.minLength) s++;
    if (/[A-Z]/.test(v)) s++;
    if (/[a-z]/.test(v)) s++;
    if (/\d/.test(v)) s++;
    if (/[^A-Za-z0-9]/.test(v)) s++;

    const issues = [];
    if (v.length < cfg.minLength) issues.push(STR.tooShort(cfg.minLength));

    return {score:s,label:STR.levels[s], issues};
  }

  function renderStrength() {
    if (!strengthEl || !newPw) return;
    const {score,label,issues} = evaluateStrength(newPw.value);
    strengthEl.dataset.level = score;
    let text = label ? `${STR.strength}: ${label}` : '';
    if (issues.length) {
      text += (text ? ' – ' : '') + issues.join(' | ');
    }
    if (cfg.checkReuse && currentPw && newPw.value && currentPw.value && currentPw.value === newPw.value) {
      text += (text ? ' – ' : '') + STR.reuseWarn;
    }
    strengthEl.textContent = text;
  }

  function validateMatch() {
    if (!newPw || !confirmPw) return true;
    const aRaw = newPw.value;
    const bRaw = confirmPw.value;

    if (!aRaw || !bRaw) {
      hideMismatch();
      return true;
    }
    const a = normalizeValue(aRaw);
    const b = normalizeValue(bRaw);

    if (a !== b) {
      showMismatch();
      return false;
    }
    hideMismatch();
    return true;
  }

  function showMismatch() {
    ensureMismatchMsg();
    confirmPw.classList.add('is-invalid');
    mismatchMsg.style.display='block';
  }
  function hideMismatch() {
    confirmPw.classList.remove('is-invalid');
    if (mismatchMsg) mismatchMsg.style.display='none';
  }

  function debounce(fn, delay=150) {
    return (...args) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => fn.apply(null,args), delay);
    };
  }

  function attachToggle(input) {
    if (!input) return;
    if (input.parentElement.querySelector('.pw-toggle-btn')) return;

    const parent = input.parentElement;
    const needsWrap = !parent.classList.contains('pw-wrapper') &&
                      !getComputedStyle(parent).position.match(/relative|absolute|fixed/);

    let wrapper = parent;
    if (needsWrap) {
      wrapper = document.createElement('div');
      wrapper.className = 'pw-wrapper position-relative';
      parent.insertBefore(wrapper, input);
      wrapper.appendChild(input);
    } else {
      parent.classList.add('pw-wrapper','position-relative');
    }

    input.style.direction = 'ltr';
    input.style.unicodeBidi = 'plaintext';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pw-toggle-btn btn btn-sm btn-outline-secondary';
    btn.textContent = STR.show;
    btn.setAttribute('aria-label', STR.show);
    btn.setAttribute('aria-pressed','false');

    Object.assign(btn.style, {
      position: 'absolute',
      top: '50%',
      right: isArabic ? 'auto' : '.55rem',
      left: isArabic ? '.55rem' : 'auto',
      transform: 'translateY(-50%)',
      fontSize: '.65rem',
      padding: '.25rem .55rem'
    });

    btn.addEventListener('click', () => {
      const showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      btn.textContent = showing ? STR.show : STR.hide;
      btn.setAttribute('aria-label', showing ? STR.show : STR.hide);
      btn.setAttribute('aria-pressed', String(!showing));
    });

    wrapper.appendChild(btn);
  }

  const strengthDebounced = debounce(renderStrength, 160);

  [newPw, confirmPw].forEach(el => {
    if (!el) return;
    ['input','change','blur','keyup','paste'].forEach(ev => {
      el.addEventListener(ev, () => {
        validateMatch();
        if (el === newPw) strengthDebounced();
      });
    });
  });

  newPw && renderStrength();
  validateMatch();

  attachToggle(currentPw);
  attachToggle(newPw);
  attachToggle(confirmPw);

  form.addEventListener('submit', e => {
    if (!validateMatch()) {
      e.preventDefault();
      confirmPw && confirmPw.focus();
      return;
    }
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.dataset.originalHtml = submitBtn.innerHTML;
      submitBtn.innerHTML =
        `<span class="spinner-border spinner-border-sm me-1"></span> ${STR.saving}`;
      setTimeout(() => {
        if (document.body.contains(submitBtn) && submitBtn.disabled) {
          submitBtn.disabled = false;
          if (submitBtn.dataset.originalHtml) {
            submitBtn.innerHTML = submitBtn.dataset.originalHtml;
          }
        }
      }, 12000);
    }
  });

  window.PasswordSettingsHelper = {
    evaluate: evaluateStrength,
    forceValidate: validateMatch,
    renderStrength,
    config: cfg
  };
});
