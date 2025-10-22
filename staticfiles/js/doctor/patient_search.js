// static/js/doctor/patient_search.js
// Features: CSV export, print, simple client-side pagination

(function () {
  const table = document.getElementById('patientsTable');
  if (!table) return;

  const exportBtn     = document.getElementById('exportCsvBtn');
  const printBtn      = document.getElementById('printBtn');
  const paginationBar = document.getElementById('paginationBar');

  const rows = Array.from(table.querySelectorAll('tbody tr'));
  const pageSize = 15; // عدد الصفوف لكل صفحة
  let currentPage = 1;

  /* ---------- CSV Export ---------- */
  if (exportBtn) {
    exportBtn.addEventListener('click', function () {
      const fullRows = [table.querySelector('thead tr'), ...rows];

      const csv = fullRows.map(row =>
        Array.from(row.querySelectorAll('th,td'))
          .map(td => `"${td.innerText.replace(/"/g, '""')}"`)
          .join(',')
      ).join('\n');

      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url;
      a.download = 'patients.csv';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    });
  }

  /* ---------- Print ---------- */
  if (printBtn) {
    printBtn.addEventListener('click', () => window.print());
  }

  /* ---------- Pagination ---------- */
  function renderPagination(totalPages) {
    if (!paginationBar) return;
    paginationBar.innerHTML = '';

    for (let i = 1; i <= totalPages; i++) {
      const btn = document.createElement('button');
      btn.textContent = i;
      btn.className = (i === currentPage) ? 'active' : '';
      btn.addEventListener('click', () => {
        currentPage = i;
        renderTable();
      });
      paginationBar.appendChild(btn);
    }
  }

  function renderTable() {
    rows.forEach(r => r.style.display = 'none');

    const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
    if (currentPage > totalPages) currentPage = totalPages;

    const start = (currentPage - 1) * pageSize;
    rows.slice(start, start + pageSize).forEach(r => r.style.display = '');

    renderPagination(totalPages);
  }

  // init
  renderTable();
})();
