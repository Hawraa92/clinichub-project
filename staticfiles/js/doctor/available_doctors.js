// static/js/doctor/available_doctors.js
document.addEventListener('DOMContentLoaded', function() {
  // DOM Elements
  const filterBtn = document.querySelector('.filter-btn');
  const filterModal = document.getElementById('filter-modal');
  const closeModal = document.querySelector('.close-modal');
  const clearSearch = document.querySelector('.clear-search');
  const searchInput = document.getElementById('doctor-search');
  const viewOptions = document.querySelectorAll('.view-option');
  const doctorGrid = document.querySelector('.doctor-grid');
  const sortSelect = document.getElementById('sort');
  const doctorCards = document.querySelectorAll('.doctor-card');

  // Toggle filter modal
  filterBtn.addEventListener('click', () => {
    filterModal.classList.add('active');
    document.body.style.overflow = 'hidden';
  });

  closeModal.addEventListener('click', () => {
    filterModal.classList.remove('active');
    document.body.style.overflow = '';
  });

  // Close modal when clicking outside
  filterModal.addEventListener('click', (e) => {
    if (e.target === filterModal) {
      filterModal.classList.remove('active');
      document.body.style.overflow = '';
    }
  });

  // Clear search input
  clearSearch.addEventListener('click', () => {
    searchInput.value = '';
    searchInput.focus();
    filterDoctors();
  });

  // Search functionality
  searchInput.addEventListener('input', filterDoctors);

  // View toggle
  viewOptions.forEach(option => {
    option.addEventListener('click', () => {
      viewOptions.forEach(opt => opt.classList.remove('active'));
      option.classList.add('active');
      
      if (option.dataset.view === 'list') {
        doctorGrid.classList.add('list-view');
      } else {
        doctorGrid.classList.remove('list-view');
      }
    });
  });

  // Sorting functionality
  sortSelect.addEventListener('change', sortDoctors);

  // Filter doctors based on search input
  function filterDoctors() {
    const searchTerm = searchInput.value.toLowerCase();
    
    doctorCards.forEach(card => {
      const name = card.querySelector('h2').textContent.toLowerCase();
      const specialty = card.querySelector('.specialty').textContent.toLowerCase();
      const bio = card.querySelector('.bio') ? card.querySelector('.bio').textContent.toLowerCase() : '';
      
      if (name.includes(searchTerm) || specialty.includes(searchTerm) || bio.includes(searchTerm)) {
        card.style.display = 'flex';
      } else {
        card.style.display = 'none';
      }
    });
  }

  // Sort doctors based on selected criteria
  function sortDoctors() {
    const sortBy = sortSelect.value;
    const container = document.querySelector('.doctor-grid');
    const cards = Array.from(doctorCards);
    
    cards.sort((a, b) => {
      let aValue, bValue;
      
      switch(sortBy) {
        case 'rating':
          aValue = parseFloat(a.dataset.rating);
          bValue = parseFloat(b.dataset.rating);
          return bValue - aValue;
          
        case 'experience':
          aValue = parseInt(a.dataset.experience);
          bValue = parseInt(b.dataset.experience);
          return bValue - aValue;
          
        case 'fee':
          aValue = parseInt(a.dataset.fee);
          bValue = parseInt(b.dataset.fee);
          return aValue - bValue;
          
        case 'availability':
          aValue = a.dataset.available === 'true' ? 1 : 0;
          bValue = b.dataset.available === 'true' ? 1 : 0;
          return bValue - aValue;
          
        default:
          return 0;
      }
    });
    
    // Clear and re-append sorted cards
    container.innerHTML = '';
    cards.forEach(card => container.appendChild(card));
  }
  
  // Initialize functionality
  filterDoctors();
});