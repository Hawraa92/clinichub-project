document.addEventListener('DOMContentLoaded', () => {

  /* =========================
     Grab Elements (safe lookups)
     ========================= */
  const els = {
    predictionBadge: document.getElementById('predictionBadge'),
    predictionModal: document.getElementById('predictionModal'),
    addNoteModal:    document.getElementById('addNoteModal'),
    historyModal:    document.getElementById('historyModal'),
    closeBtns:       document.querySelectorAll('.close'),
    reportBtn:       document.getElementById('generateReportBtn'),
    addNoteBtn:      document.getElementById('addNoteBtn'),
    viewHistoryBtn:  document.getElementById('viewHistoryBtn'),
    cancelNoteBtn:   document.getElementById('cancelNoteBtn'),
    noteForm:        document.getElementById('clinicalNoteForm'),
    toast:           document.getElementById('reportToast'),
    actionsBar:      document.querySelector('.pd-actions'),
    chartCanvas:     document.getElementById('healthMetricsChart')
  };

  /* =========================
     Helpers
     ========================= */

  // Modal show / hide
  const showModal = (modalEl) => {
    if (!modalEl) return;
    modalEl.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  };

  const hideModal = (modalEl) => {
    if (!modalEl) return;
    modalEl.style.display = 'none';
    document.body.style.overflow = 'auto';
  };

  // Toast
  const showToast = (toastEl, duration = 3000) => {
    if (!toastEl) return;
    toastEl.classList.add('show');
    setTimeout(() => toastEl.classList.remove('show'), duration);
  };

  // Simple fade hover for cards (optional, can be done in CSS)
  const initCardHover = () => {
    document.querySelectorAll('.glow-hover').forEach(card => {
      card.addEventListener('mouseenter', () => { card.style.transform = 'translateY(-5px)'; });
      card.addEventListener('mouseleave', () => { card.style.transform = 'translateY(0)'; });
    });
  };

  // Responsive tweaks
  const handleResponsive = () => {
    if (!els.actionsBar) return;
    if (window.innerWidth < 768) {
      els.actionsBar.classList.add('mobile-view');
    } else {
      els.actionsBar.classList.remove('mobile-view');
    }
  };

  // Chart init
  const initHealthChart = () => {
    if (!els.chartCanvas || typeof Chart === 'undefined') return;

    new Chart(els.chartCanvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
        datasets: [
          {
            label: 'Glucose (mg/dL)',
            data: [160, 152, 145, 142, 138, 136],
            borderColor: '#4e73df',
            backgroundColor: 'rgba(78, 115, 223, 0.1)',
            tension: 0.3,
            fill: true
          },
          {
            label: 'HbA1c (%)',
            data: [8.2, 7.9, 7.7, 7.5, 7.3, 7.1],
            borderColor: '#17bf7a',
            backgroundColor: 'rgba(23, 191, 122, 0.1)',
            tension: 0.3,
            fill: true
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'top' } },
        scales: {
          y: {
            beginAtZero: false,
            grid: { color: 'rgba(0, 0, 0, 0.05)' }
          },
          x: {
            grid: { display: false }
          }
        }
      }
    });
  };

  /* =========================
     Event bindings
     ========================= */

  // Prediction badge -> open prediction modal
  if (els.predictionBadge) {
    els.predictionBadge.addEventListener('click', () => showModal(els.predictionModal));
  }

  // Buttons that open modals
  if (els.addNoteBtn)     els.addNoteBtn.addEventListener('click', () => showModal(els.addNoteModal));
  if (els.viewHistoryBtn) els.viewHistoryBtn.addEventListener('click', () => showModal(els.historyModal));

  // Close buttons (x)
  els.closeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      [els.predictionModal, els.addNoteModal, els.historyModal].forEach(hideModal);
    });
  });

  // Click outside modal to close
  window.addEventListener('click', (e) => {
    [els.predictionModal, els.addNoteModal, els.historyModal].forEach(modalEl => {
      if (modalEl && e.target === modalEl) hideModal(modalEl);
    });
  });

  // Cancel note button
  if (els.cancelNoteBtn) {
    els.cancelNoteBtn.addEventListener('click', () => hideModal(els.addNoteModal));
  }

  // Generate report (fake)
  if (els.reportBtn) {
    els.reportBtn.addEventListener('click', () => {
      const originalHTML = els.reportBtn.innerHTML;
      els.reportBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';
      els.reportBtn.disabled = true;

      setTimeout(() => {
        els.reportBtn.innerHTML = originalHTML;
        els.reportBtn.disabled = false;
        showToast(els.toast);
      }, 2000);
    });
  }

  // Clinical note form
  if (els.noteForm) {
    els.noteForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const content = document.getElementById('noteContent');
      if (!content || !content.value.trim()) {
        alert('Please enter note content');
        return;
      }

      // TODO: send data to server via fetch/AJAX if needed
      hideModal(els.addNoteModal);
      alert('Clinical note added successfully!');
      els.noteForm.reset();
    });
  }

  /* =========================
     Init
     ========================= */
  initHealthChart();
  initCardHover();
  handleResponsive();
  window.addEventListener('resize', handleResponsive);
});
