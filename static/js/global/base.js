/* File: static/js/global/base.js */

(() => {
    'use strict';
  
    document.addEventListener('DOMContentLoaded', () => {
      initializeApp();
    });
  
    function initializeApp() {
      if (window.AOS) {
        AOS.init({
          duration: 600,
          easing: 'ease-in-out',
          once: true,
          mirror: false
        });
      }
  
      handleLoadingOverlay();
      initializeTheme();
      initializeScrollEffects();
      initializeToasts();
      initializeMedicalAnimation();
    }
  
    // -----------------------
    // Loading Overlay
    // -----------------------
    function handleLoadingOverlay() {
      const loadingOverlay = document.getElementById('loadingOverlay');
  
      // If skip-loader already applied early in <head>
      if (document.documentElement.classList.contains('ch-skip-loader')) {
        if (loadingOverlay) loadingOverlay.classList.add('hidden');
        return;
      }
  
      if (loadingOverlay) {
        window.addEventListener('load', () => {
          setTimeout(() => {
            loadingOverlay.classList.add('hidden');
          }, 500);
        });
  
        if (document.readyState === 'complete') {
          loadingOverlay.classList.add('hidden');
        }
      }
  
      // ✅ set skip flag for GET forms (search/filter)
      document.addEventListener('submit', (e) => {
        const form = e.target;
        if (form && form.method && form.method.toLowerCase() === 'get') {
          try {
            sessionStorage.setItem('ch_skip_loader', '1');
          } catch (err) {
            console.warn('Could not access sessionStorage');
          }
        }
      });
    }
  
    // -----------------------
    // Theme Management
    // -----------------------
    function initializeTheme() {
      const themeToggle = document.getElementById('themeToggle');
      const html = document.documentElement;
      const themeKey = 'clinichub-theme';
  
      if (!themeToggle) return;
  
      function updateToggleState(isDark) {
        const icon = themeToggle.querySelector('.theme-icon i');
        if (icon) icon.className = isDark ? 'bi bi-sun' : 'bi bi-moon-stars';
      }
  
      function getCurrentTheme() {
        return html.getAttribute('data-theme') || 'light';
      }
  
      function setTheme(theme) {
        if (theme !== 'dark' && theme !== 'light') return;
        html.setAttribute('data-theme', theme);
        updateToggleState(theme === 'dark');
        try {
          localStorage.setItem(themeKey, theme);
        } catch (err) {}
        window.dispatchEvent(new CustomEvent('themechange', { detail: theme }));
      }
  
      function initTheme() {
        let theme = null;
  
        try {
          theme = localStorage.getItem(themeKey);
        } catch (err) {}
  
        if (!theme) {
          theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
  
        html.setAttribute('data-theme', theme);
        updateToggleState(theme === 'dark');
      }
  
      // System theme changes (with fallback)
      try {
        const mq = window.matchMedia('(prefers-color-scheme: dark)');
        const onChange = (e) => {
          try {
            if (!localStorage.getItem(themeKey)) {
              const newTheme = e.matches ? 'dark' : 'light';
              html.setAttribute('data-theme', newTheme);
              updateToggleState(newTheme === 'dark');
            }
          } catch (err) {}
        };
  
        if (mq.addEventListener) mq.addEventListener('change', onChange);
        else if (mq.addListener) mq.addListener(onChange);
      } catch (err) {}
  
      initTheme();
  
      themeToggle.addEventListener('click', () => {
        const currentTheme = getCurrentTheme();
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        setTheme(newTheme);
      });
  
      window.ClinicHub = window.ClinicHub || {};
      window.ClinicHub.theme = {
        get: () => getCurrentTheme(),
        set: (theme) => setTheme(theme),
        toggle: () => setTheme(getCurrentTheme() === 'dark' ? 'light' : 'dark'),
      };
    }
  
    // -----------------------
    // Scroll Effects
    // -----------------------
    function initializeScrollEffects() {
      const navbar = document.getElementById('mainNav');
      if (!navbar) return;
  
      let lastScroll = 0;
      const scrollThreshold = 100;
  
      function handleScroll() {
        const currentScroll = window.pageYOffset;
  
        if (currentScroll > 10) navbar.classList.add('scrolled');
        else navbar.classList.remove('scrolled');
  
        if (currentScroll > lastScroll && currentScroll > scrollThreshold) {
          navbar.style.transform = 'translateY(-100%)';
        } else {
          navbar.style.transform = 'translateY(0)';
        }
  
        lastScroll = currentScroll;
      }
  
      let ticking = false;
      window.addEventListener('scroll', () => {
        if (!ticking) {
          window.requestAnimationFrame(() => {
            handleScroll();
            ticking = false;
          });
          ticking = true;
        }
      });
  
      handleScroll();
    }
  
    // -----------------------
    // Toast Notifications
    // -----------------------
    function initializeToasts() {
      const toasts = document.querySelectorAll('.toast');
  
      toasts.forEach(toast => {
        const autoRemoveDelay = 5000;
  
        const closeBtn = toast.querySelector('.toast-close');
        if (closeBtn) {
          closeBtn.addEventListener('click', () => removeToast(toast));
        }
  
        setTimeout(() => {
          if (toast.parentNode) removeToast(toast);
        }, autoRemoveDelay);
      });
  
      function removeToast(toast) {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => {
          if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 300);
      }
    }
  
    // -----------------------
    // Medical Animation
    // -----------------------
    function initializeMedicalAnimation() {
      const animationContainer = document.querySelector('.medical-animation');
      if (!animationContainer) return;
  
      const medicalIcons = ['+', '❤️', '🩺', '💊', '🧪', '🧬', '🩸', '⚕️'];
      const iconCount = 12;
  
      for (let i = 0; i < iconCount; i++) {
        const icon = document.createElement('div');
        icon.className = 'floating-icon';
        icon.textContent = medicalIcons[Math.floor(Math.random() * medicalIcons.length)];
  
        icon.style.cssText = `
          position: absolute;
          font-size: ${Math.random() * 1.5 + 1}rem;
          left: ${Math.random() * 100}%;
          bottom: -${Math.random() * 50}px;
          opacity: ${Math.random() * 0.3 + 0.1};
          animation: floatUp ${Math.random() * 20 + 20}s linear infinite;
          animation-delay: ${Math.random() * 5}s;
          z-index: 1;
          pointer-events: none;
          user-select: none;
        `;
  
        animationContainer.appendChild(icon);
      }
  
      if (!document.querySelector('#medical-animation-style')) {
        const style = document.createElement('style');
        style.id = 'medical-animation-style';
        style.textContent = `
          @keyframes floatUp {
            0% { transform: translateY(0) rotate(0deg); opacity: 0; }
            10% { opacity: 0.3; }
            90% { opacity: 0.3; }
            100% { transform: translateY(-100vh) rotate(360deg); opacity: 0; }
          }
          [data-theme="dark"] .floating-icon {
            filter: drop-shadow(0 0 8px rgba(56, 189, 248, 0.3));
            text-shadow: 0 0 12px rgba(56, 189, 248, 0.4);
          }
        `;
        document.head.appendChild(style);
      }
    }
  
  })();
  