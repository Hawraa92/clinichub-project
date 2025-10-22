// File: static/js/prescription_list.js
$(document).ready(function(){
    const table = $('#prescTable').DataTable({
      language: { search: "", searchPlaceholder: "Search records..." },
      dom: '<"row"<"col-sm-12 col-md-6"l><"col-sm-12 col-md-6 d-flex justify-content-end"f>>rt<"row"<"col-sm-12 col-md-6"i><"col-sm-12 col-md-6"p>>',
      initComplete: function() {
        $('.dataTables_filter input').addClass('form-control form-control-sm');
        $('.dataTables_length select').addClass('form-select form-select-sm');
      }
    });
  
    // Live search by name
    $('#customSearch').on('keyup change', function(){
      table.search(this.value).draw();
    });
  
    // Custom filtering (doctor + date)
    $.fn.dataTable.ext.search.push(function(_, _, rowIndex){
      const doctorFilter = $('#doctorFilter').val();
      const dateFilter   = $('#dateFilter').val();
      const $row         = $(table.row(rowIndex).node());
      const rowDoctor    = $row.data('doctor-id').toString();
      const rowDate      = new Date($row.data('date'));
      const today        = new Date();
  
      if (doctorFilter && doctorFilter !== rowDoctor) return false;
  
      if (dateFilter) {
        let cutoff = new Date(today);
        if (dateFilter === 'today') {
          cutoff.setHours(0,0,0,0);
          if (rowDate < cutoff) return false;
        }
        if (dateFilter === 'week') {
          cutoff.setDate(cutoff.getDate() - 7);
          if (rowDate < cutoff) return false;
        }
        if (dateFilter === 'month') {
          cutoff.setMonth(cutoff.getMonth() - 1);
          if (rowDate < cutoff) return false;
        }
      }
      return true;
    });
  
    // Redraw on filter change
    $('#doctorFilter, #dateFilter').on('change', function(){
      table.draw();
    });
  
    // Toggle Table/Grid view
    $('.view-option').click(function(){
      $('.view-option').removeClass('active');
      $(this).addClass('active');
      if ($(this).data('view') === 'table') {
        $('#gridView').addClass('d-none');
        $('#tableView').removeClass('d-none');
      } else {
        $('#tableView').addClass('d-none');
        $('#gridView').removeClass('d-none');
      }
    });
  });
  