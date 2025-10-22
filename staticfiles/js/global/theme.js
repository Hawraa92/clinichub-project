// Theme switching functionality
document.addEventListener('DOMContentLoaded', function() {
  const themeToggle = document.querySelector('.btn-toggle-theme');
  const htmlElement = document.documentElement;

  // Check for saved theme preference in localStorage
  const savedTheme = localStorage.getItem('theme');
  
  // If a saved theme exists, apply it
  if (savedTheme) {
    htmlElement.setAttribute('data-bs-theme', savedTheme);
  } 
  // If no saved theme, apply system preference (dark mode)
  else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
    htmlElement.setAttribute('data-bs-theme', 'dark');
  }

  // Toggle theme on button click
  if (themeToggle) {
    themeToggle.addEventListener('click', function() {
      // Get current theme
      const currentTheme = htmlElement.getAttribute('data-bs-theme');
      
      // Toggle theme between light and dark
      const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
      
      // Apply new theme to the HTML element
      htmlElement.setAttribute('data-bs-theme', newTheme);
      
      // Save new theme preference to localStorage
      localStorage.setItem('theme', newTheme);
    });
  }
});
