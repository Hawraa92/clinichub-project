// static/js/appointments/appointment_ticket.js

(function () {
    const copyBtn = document.querySelector('.btn-copy');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        const code = copyBtn.getAttribute('data-copy');
        if (!code) return;
        navigator.clipboard.writeText(code).then(() => {
          const original = copyBtn.innerHTML;
          copyBtn.innerHTML = '<i class="fas fa-check"></i><span>Copied!</span>';
          setTimeout(() => (copyBtn.innerHTML = original), 1800);
        });
      });
    }
  })();
  