// Toggle password visibility
document.querySelectorAll('.toggle-password').forEach(button => {
  button.addEventListener('click', function() {
    const input = this.parentElement.querySelector('input');
    const icon = this.querySelector('i');
    if (input.type === 'password') {
      input.type = 'text';
      icon.classList.replace('fa-eye', 'fa-eye-slash');
    } else {
      input.type = 'password';
      icon.classList.replace('fa-eye-slash', 'fa-eye');
    }
  });
});

// Password strength and requirements live update
const passwordInput = document.querySelector('input[name="new_password1"]');
if (passwordInput) {
  const strengthFill = document.getElementById('strength-fill');
  passwordInput.addEventListener('input', function() {
    const password = this.value;
    updateRequirements(password);
    updateStrengthMeter(password);
  });

  function updateRequirements(password) {
    toggleRequirement('length-req', password.length >= 8);
    toggleRequirement('uppercase-req', /[A-Z]/.test(password));
    toggleRequirement('number-req', /\d/.test(password));
    toggleRequirement('special-req', /[!@#$%^&*(),.?":{}|<>]/.test(password));
  }

  function toggleRequirement(id, isValid) {
    const req = document.getElementById(id);
    if (req) req.classList.toggle('valid', isValid);
  }

  function updateStrengthMeter(password) {
    let strength = 0;
    if (password.length >= 8) strength += 25;
    if (/[A-Z]/.test(password)) strength += 25;
    if (/\d/.test(password)) strength += 25;
    if (/[!@#$%^&*(),.?":{}|<>]/.test(password)) strength += 25;
    if (strengthFill) {
      strengthFill.style.width = strength + '%';
      if (strength < 50) {
        strengthFill.style.background = '#dc3545';
      } else if (strength < 75) {
        strengthFill.style.background = '#ffc107';
      } else {
        strengthFill.style.background = '#28a745';
      }
    }
  }
}

// Form submission loading
const form = document.getElementById('password-reset-form');
if (form) {
  const submitBtn = document.getElementById('submit-btn');
  form.addEventListener('submit', function() {
    const loadingDots = submitBtn.querySelector('.loading-dots');
    const btnText = submitBtn.querySelector('.btn-text');
    if (submitBtn && loadingDots && btnText) {
      submitBtn.disabled = true;
      btnText.style.opacity = '0';
      loadingDots.style.display = 'flex';
    }
  });
}
