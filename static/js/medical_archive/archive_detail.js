// static/js/medical_archive/archive_detail.js

// Initialize Lightbox
lightbox.option({
    'resizeDuration': 200,
    'wrapAround': true,
    'albumLabel': 'Attachment %1 of %2',
    'fadeDuration': 300
  });
  
  // Print functionality
  document.querySelector('.btn-print')?.addEventListener('click', function() {
    window.print();
  });
  
  // Emergency access confirmation
  document.querySelector('.btn-emergency')?.addEventListener('click', function() {
    if(confirm('Emergency access will be logged and requires justification. Proceed?')) {
      // In real implementation: Trigger emergency access workflow
      alert('Emergency access granted. Auditing this action.');
    }
  });
  
  // Export functionality
  document.querySelector('.btn-export')?.addEventListener('click', function() {
    // In real implementation: Trigger export workflow
    alert('Export options: PDF, HL7 v2, FHIR JSON');
  });
  
  // Tab persistence
  document.addEventListener('DOMContentLoaded', function() {
    // Save tab state
    const tabLinks = document.querySelectorAll('[data-bs-toggle="tab"]');
    
    tabLinks.forEach(tab => {
      tab.addEventListener('shown.bs.tab', function(e) {
        localStorage.setItem('lastTab', e.target.getAttribute('id'));
      });
    });
    
    // Restore tab state
    const lastTab = localStorage.getItem('lastTab');
    if (lastTab) {
      const tabTrigger = new bootstrap.Tab(document.querySelector(`#${lastTab}`));
      tabTrigger.show();
    }
  });
  
  // Accessibility enhancements
  document.addEventListener('keydown', function(e) {
    // Close lightbox with ESC
    if(e.key === 'Escape' && document.getElementById('lightbox')) {
      lightbox.close();
    }
  });
  
  // Focus management for modals (if any)