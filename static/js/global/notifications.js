(function () {
    'use strict';
  
    const root = document.getElementById(
      'clinicNotificationRoot'
    );
  
    if (!root) {
      return;
    }
  
    const apiUrl = root.dataset.apiUrl;
    const listUrl = root.dataset.listUrl || '#';
  
    const badge = document.getElementById(
      'clinicNotificationBadge'
    );
  
    const summary = document.getElementById(
      'clinicNotificationSummary'
    );
  
    const list = document.getElementById(
      'clinicNotificationList'
    );
  
    const refreshInterval = 30000;
  
    let refreshTimer = null;
  
    function iconName(notificationType) {
      if (notificationType === 'pharmacy') {
        return 'bi-capsule-pill';
      }
  
      if (notificationType === 'booking_request') {
        return 'bi-calendar2-check';
      }
  
      return 'bi-bell';
    }
  
    function iconModifier(notificationType) {
      if (notificationType === 'pharmacy') {
        return 'is-pharmacy';
      }
  
      if (notificationType === 'booking_request') {
        return 'is-booking';
      }
  
      return 'is-system';
    }
  
    function formatDate(value) {
      if (!value) {
        return '';
      }
  
      const parsedDate = new Date(value);
  
      if (Number.isNaN(parsedDate.getTime())) {
        return '';
      }
  
      return new Intl.DateTimeFormat(
        document.documentElement.lang || 'en',
        {
          dateStyle: 'medium',
          timeStyle: 'short'
        }
      ).format(parsedDate);
    }
  
    function updateBadge(unreadCount) {
      if (!badge) {
        return;
      }
  
      const count = Number(unreadCount) || 0;
  
      badge.textContent = count > 99
        ? '99+'
        : String(count);
  
      badge.classList.toggle(
        'd-none',
        count === 0
      );
  
      if (summary) {
        summary.textContent = count === 0
          ? 'You are all caught up.'
          : `${count} unread notification${count === 1 ? '' : 's'}`;
      }
    }
  
    function createState(iconClass, message) {
      const state = document.createElement('div');
  
      state.className = 'notification-dropdown-state';
  
      const icon = document.createElement('i');
  
      icon.className = `bi ${iconClass}`;
  
      icon.setAttribute(
        'aria-hidden',
        'true'
      );
  
      const text = document.createElement('span');
  
      text.textContent = message;
  
      state.append(
        icon,
        text
      );
  
      return state;
    }
  
    function createNotificationItem(notification) {
      const item = document.createElement('a');
  
      item.className = 'notification-dropdown-item';
  
      item.href = notification.open_url || listUrl;
  
      item.setAttribute(
        'role',
        'listitem'
      );
  
      if (!notification.is_read) {
        item.classList.add('is-unread');
      }
  
      const iconWrapper = document.createElement('span');
  
      iconWrapper.className =
        `notification-dropdown-icon ${
          iconModifier(notification.notification_type)
        }`;
  
      const icon = document.createElement('i');
  
      icon.className =
        `bi ${iconName(notification.notification_type)}`;
  
      icon.setAttribute(
        'aria-hidden',
        'true'
      );
  
      iconWrapper.appendChild(icon);
  
      const content = document.createElement('span');
  
      content.className =
        'notification-dropdown-content';
  
      const title = document.createElement('span');
  
      title.className =
        'notification-dropdown-title';
  
      title.textContent =
        notification.title || 'Notification';
  
      const message = document.createElement('span');
  
      message.className =
        'notification-dropdown-message';
  
      message.textContent =
        notification.message || '';
  
      const time = document.createElement('span');
  
      time.className =
        'notification-dropdown-time';
  
      time.textContent = formatDate(
        notification.created_at
      );
  
      content.append(
        title,
        message,
        time
      );
  
      const status = document.createElement('span');
  
      if (!notification.is_read) {
        status.className =
          'notification-unread-dot';
  
        status.setAttribute(
          'aria-label',
          'Unread'
        );
      }
  
      item.append(
        iconWrapper,
        content,
        status
      );
  
      return item;
    }
  
    function renderNotifications(notifications) {
      if (!list) {
        return;
      }
  
      list.replaceChildren();
  
      if (
        !Array.isArray(notifications) ||
        notifications.length === 0
      ) {
        list.appendChild(
          createState(
            'bi-check2-circle',
            'No notifications yet.'
          )
        );
  
        return;
      }
  
      const fragment =
        document.createDocumentFragment();
  
      notifications.forEach(function (notification) {
        fragment.appendChild(
          createNotificationItem(notification)
        );
      });
  
      list.appendChild(fragment);
    }
  
    function renderError() {
      if (!list) {
        return;
      }
  
      list.replaceChildren(
        createState(
          'bi-exclamation-circle',
          'Could not load notifications.'
        )
      );
  
      if (summary) {
        summary.textContent =
          'Updates are temporarily unavailable.';
      }
    }
  
    async function loadNotifications() {
      if (!apiUrl) {
        return;
      }
  
      try {
        const response = await fetch(
          apiUrl,
          {
            method: 'GET',
            credentials: 'same-origin',
            headers: {
              'Accept': 'application/json',
              'X-Requested-With': 'XMLHttpRequest'
            }
          }
        );
  
        if (!response.ok) {
          throw new Error(
            `Notification request failed with ${response.status}`
          );
        }
  
        const data = await response.json();
  
        if (!data.success) {
          throw new Error(
            data.error ||
            'Notification request failed.'
          );
        }
  
        updateBadge(
          data.unread_count
        );
  
        renderNotifications(
          data.notifications
        );
  
      } catch (error) {
        renderError();
      }
    }
  
    function startPolling() {
      window.clearInterval(refreshTimer);
  
      refreshTimer = window.setInterval(
        loadNotifications,
        refreshInterval
      );
    }
  
    document.addEventListener(
      'visibilitychange',
      function () {
        if (document.visibilityState === 'visible') {
          loadNotifications();
          startPolling();
        }
      }
    );
  
    root.addEventListener(
      'show.bs.dropdown',
      loadNotifications
    );
  
    loadNotifications();
    startPolling();
  })();