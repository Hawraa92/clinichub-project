// static/js/prescription_create.js

document.addEventListener('DOMContentLoaded', function() {
  // 1) Front-end validation
  const form = document.getElementById('prescriptionForm');
  form.addEventListener('submit', function(e) {
    if (!form.checkValidity()) {
      e.preventDefault();
      e.stopPropagation();
      form.classList.add('was-validated');
    }
  });

  // 2) Dynamic medication fields
  const medsContainer = document.getElementById('medications');
  const addBtn        = document.getElementById('add-medication');
  const totalForms    = document.querySelector('input[name$="-TOTAL_FORMS"]');

  addBtn.addEventListener('click', function() {
    const count = parseInt(totalForms.value, 10);
    const template = document
      .getElementById('empty-form')
      .innerHTML
      .replace(/__prefix__/g, count);
    medsContainer.insertAdjacentHTML('beforeend', template);
    totalForms.value = count + 1;
  });

  medsContainer.addEventListener('click', function(e) {
    const rem = e.target.closest('.remove-medication');
    if (!rem) return;
    const entry = rem.closest('.medication-entry');
    const delInput = entry.querySelector('input[type="checkbox"][name$="-DELETE"]');
    if (delInput) {
      delInput.checked = true;
      entry.style.display = 'none';
    } else {
      entry.remove();
      totalForms.value = parseInt(totalForms.value, 10) - 1;
    }
  });
});
