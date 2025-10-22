// static/js/accounts/password_reset_form.js
document.addEventListener('DOMContentLoaded', function() {
  const form = document.getElementById('password-reset-form');
  const submitBtn = document.getElementById('submit-btn');
  const spinner = document.getElementById('spinner');
  const btnContent = submitBtn.querySelector('.btn-content');

  if (form) {
    form.addEventListener('submit', function(e) {
      // Show loading state
      submitBtn.classList.add('loading');
      submitBtn.disabled = true;
      spinner.classList.remove('hidden'); // إظهار الـ spinner
      btnContent.classList.add('hidden'); // إخفاء محتوى الزر

      // Create ripple effect
      const ripple = document.createElement('span');
      ripple.classList.add('ripple');
      submitBtn.appendChild(ripple);

      // Position ripple
      const rect = submitBtn.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height);
      ripple.style.width = ripple.style.height = `${size}px`;
      ripple.style.left = `${e.clientX - rect.left - size / 2}px`;
      ripple.style.top = `${e.clientY - rect.top - size / 2}px`;

      // Remove ripple after animation
      setTimeout(() => ripple.remove(), 600);

      // Simulate network delay (احذف هذا الجزء إذا كان الفرم سيرسل فعلياً)
      setTimeout(() => {
        // Restore button state
        submitBtn.classList.remove('loading');
        submitBtn.disabled = false;
        spinner.classList.add('hidden');    // إخفاء الـ spinner
        btnContent.classList.remove('hidden'); // إظهار محتوى الزر
      }, 1800);
    });

    // Floating label initial state
    const emailInput = document.querySelector('#id_email');
    const floatingLabel = document.querySelector('.floating-input label');

    // إذا الحقل فيه قيمة مسبقاً
    if (emailInput.value.trim() !== '') {
      floatingLabel.classList.add('active');
    }

    // عند الكتابة في الحقل
    emailInput.addEventListener('input', function() {
      if (this.value.trim() !== '') {
        floatingLabel.classList.add('active');
      } else {
        floatingLabel.classList.remove('active');
      }
    });

    // Add focus/blur effect
    const inputs = document.querySelectorAll('.floating-input input');
    inputs.forEach(input => {
      input.addEventListener('focus', () => {
        input.parentElement.classList.add('focused');
        floatingLabel.classList.add('active');
      });
      input.addEventListener('blur', () => {
        input.parentElement.classList.remove('focused');
        if (input.value.trim() === '') {
          floatingLabel.classList.remove('active');
        }
      });
    });
  }
});
