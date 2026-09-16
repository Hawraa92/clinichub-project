/* static/js/doctor/available_doctors.js */

// Utility functions
const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => Array.from(parent.querySelectorAll(selector));

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
  // Elements
  const searchInput = $('#doctorSearch');
  const clearSearchBtn = $('#clearSearch');
  const sortSelect = $('#sortSelect');
  const filterToggle = $('#filterToggle');
  const filterModal = $('#filterModal');
  const doctorsGrid = $('#doctorsGrid');
  const specialtyFilters = $$('.specialty-filter');
  const specialtyInput = $('#specialtyInput');
  const onlineInput = $('#onlineInput');
  const onlineCount = $('#onlineCount');
  
  // State
  let currentView = 'grid';
  let allDoctors = [];
  
  // Initialize
  init();
  
  function init() {
    // Collect all doctor cards
    allDoctors = $$('.doctor-card');
    
    // Update online count
    updateOnlineCount();
    
    // Setup event listeners
    setupEventListeners();
    
    // Setup star ratings
    setupStarRatings();
    
    // Check URL params and update UI
    updateUIFromURL();
  }
  
  function setupEventListeners() {
    // Search input
    if (searchInput) {
      searchInput.addEventListener('input', debounce(filterDoctors, 300));
    }
    
    // Clear search
    if (clearSearchBtn) {
      clearSearchBtn.addEventListener('click', clearSearch);
    }
    
    // Sort select
    if (sortSelect) {
      sortSelect.addEventListener('change', sortDoctors);
    }
    
    // Filter modal
    if (filterToggle) {
      filterToggle.addEventListener('click', openFilterModal);
    }
    
    // Close modal on backdrop click
    const backdrop = $('.modal-backdrop', filterModal);
    if (backdrop) {
      backdrop.addEventListener('click', closeFilterModal);
    }
    
    // Close modal on close button
    const closeBtn = $('.modal-close', filterModal);
    if (closeBtn) {
      closeBtn.addEventListener('click', closeFilterModal);
    }
    
    // Close modal on escape key
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && filterModal.style.display !== 'none') {
        closeFilterModal();
      }
    });
  }
  
  function setupStarRatings() {
    allDoctors.forEach(card => {
      const rating = parseFloat(card.dataset.rating) || 0;
      const stars = $$('.star', card);
      
      stars.forEach((star, index) => {
        if (index < Math.floor(rating)) {
          star.classList.add('filled');
        } else if (index < rating) {
          // Partial star (for half ratings)
          star.style.setProperty('--fill-percentage', `${(rating % 1) * 100}%`);
        }
      });
    });
  }
  
  function filterDoctors() {
    const searchTerm = searchInput.value.toLowerCase().trim();
    const selectedSpecialty = specialtyInput.value;
    const onlineOnly = onlineInput.value === '1';
    
    let visibleCount = 0;
    let onlineCountValue = 0;
    
    allDoctors.forEach(card => {
      const name = card.dataset.name.toLowerCase();
      const specialty = card.dataset.specialty.toLowerCase();
      const available = card.dataset.available === 'true';
      
      // Text search
      const matchesSearch = !searchTerm || 
        name.includes(searchTerm) || 
        specialty.includes(searchTerm);
      
      // Specialty filter
      const matchesSpecialty = !selectedSpecialty || 
        card.dataset.specialty === selectedSpecialty;
      
      // Online filter
      const matchesOnline = !onlineOnly || available;
      
      const shouldShow = matchesSearch && matchesSpecialty && matchesOnline;
      
      if (shouldShow) {
        card.style.display = '';
        visibleCount++;
        if (available) onlineCountValue++;
      } else {
        card.style.display = 'none';
      }
    });
    
    // Update online count
    if (onlineCount) {
      onlineCount.textContent = onlineCountValue;
    }
    
    // Show/hide empty state
    const emptyState = $('.empty-state');
    if (emptyState) {
      if (visibleCount === 0) {
        emptyState.style.display = 'flex';
      } else {
        emptyState.style.display = 'none';
      }
    }
  }
  
  function sortDoctors() {
    const sortBy = sortSelect.value;
    const container = doctorsGrid;
    const cards = Array.from(allDoctors.filter(card => card.style.display !== 'none'));
    
    cards.sort((a, b) => {
      switch (sortBy) {
        case 'experience':
          return parseFloat(b.dataset.experience) - parseFloat(a.dataset.experience);
        case 'availability':
          const aAvail = a.dataset.available === 'true' ? 1 : 0;
          const bAvail = b.dataset.available === 'true' ? 1 : 0;
          return bAvail - aAvail;
        case 'rating':
        default:
          return parseFloat(b.dataset.rating) - parseFloat(a.dataset.rating);
      }
    });
    
    // Reorder cards in DOM
    cards.forEach(card => {
      container.appendChild(card);
    });
  }
  
  function updateOnlineCount() {
    const onlineDoctors = allDoctors.filter(card => card.dataset.available === 'true');
    if (onlineCount) {
      onlineCount.textContent = onlineDoctors.length;
    }
  }
  
  function clearSearch() {
    if (searchInput) {
      searchInput.value = '';
      searchInput.focus();
      filterDoctors();
      clearSearchBtn.style.display = 'none';
    }
  }
  
  function openFilterModal() {
    if (filterModal) {
      filterModal.style.display = 'block';
      document.body.style.overflow = 'hidden';
    }
  }
  
  function closeFilterModal() {
    if (filterModal) {
      filterModal.style.display = 'none';
      document.body.style.overflow = '';
    }
  }
  
  function updateUIFromURL() {
    // Update search input from URL
    const urlParams = new URLSearchParams(window.location.search);
    const searchValue = urlParams.get('q');
    const specialtyValue = urlParams.get('specialty');
    const onlineValue = urlParams.get('online');
    
    if (searchValue && searchInput) {
      searchInput.value = searchValue;
      if (clearSearchBtn) clearSearchBtn.style.display = 'block';
    }
    
    if (specialtyValue) {
      // Find and activate the matching specialty filter
      const matchingFilter = Array.from(specialtyFilters).find(
        filter => filter.dataset.specialty === specialtyValue
      );
      if (matchingFilter) {
        filterSpecialty(matchingFilter);
      }
    }
    
    if (onlineValue === '1') {
      if (onlineInput) onlineInput.value = '1';
    }
    
    // Apply filters
    filterDoctors();
  }
  
  // Debounce function for search input
  function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  }
});

// Global functions for HTML onclick handlers
function filterSpecialty(button) {
  const filters = document.querySelectorAll('.specialty-filter');
  filters.forEach(filter => filter.classList.remove('active'));
  button.classList.add('active');
  
  const specialtyInput = document.getElementById('specialtyInput');
  if (specialtyInput) {
    specialtyInput.value = button.dataset.specialty;
  }
  
  // Trigger form submission
  const form = document.getElementById('filtersForm');
  if (form) {
    form.submit();
  }
}

function openModal() {
  const modal = document.getElementById('filterModal');
  if (modal) {
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden';
  }
}

function closeModal() {
  const modal = document.getElementById('filterModal');
  if (modal) {
    modal.style.display = 'none';
    document.body.style.overflow = '';
  }
}