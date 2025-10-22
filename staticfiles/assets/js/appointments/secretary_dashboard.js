// Flatpickr Calendar
flatpickr("#calendar-inline", {
  inline: true,
  defaultDate: (new Date()).toISOString().split('T')[0],
  locale: 'en',
  dateFormat: "Y-m-d",
  minDate: "today",
  disableMobile: true
});

// كل شيء يتم بعد تحميل الصفحة بالكامل
document.addEventListener("DOMContentLoaded", function() {
  // --- Chart.js for Weekly Patients ---
  const chartDataElement = document.getElementById('chart-data');
  if (chartDataElement) {
    const chartData = JSON.parse(chartDataElement.textContent);
    const ctx = document.getElementById('patientsWeekChart');
    if (ctx && chartData) {
      new Chart(ctx, {
        type: 'bar',
        data: {
          labels: chartData.labels,
          datasets: [{
            label: 'Patients',
            data: chartData.data,
            backgroundColor: [
              '#64b5f6', '#5be0b3', '#ffb385', '#e885b4', '#55c8ed', '#c2d1fc', '#9fe4dc'
            ],
            borderRadius: 14,
            borderSkipped: false,
            maxBarThickness: 56
          }]
        },
        options: {
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: function(ctx) { return ` ${ctx.parsed.y} patients`; }
              }
            }
          },
          scales: {
            y: {
              beginAtZero: true,
              grid: { color: '#e6f2fa' },
              ticks: { stepSize: 1 }
            },
            x: { grid: { display: false } }
          },
          animation: { duration: 1200, easing: 'easeOutQuart' }
        }
      });
    }
  }

  // --- Digital Clock & Date ---
  function updateClock() {
    const now = new Date();
    let hours = now.getHours();
    let minutes = now.getMinutes();
    let seconds = now.getSeconds();
    hours = hours < 10 ? "0" + hours : hours;
    minutes = minutes < 10 ? "0" + minutes : minutes;
    seconds = seconds < 10 ? "0" + seconds : seconds;

    // تحديث الوقت الرقمي
    const clock = document.getElementById("digital-clock");
    if (clock) clock.textContent = `${hours}:${minutes}:${seconds}`;

    // تحديث التاريخ الرقمي
    const options = { weekday: 'short', year: 'numeric', month: 'short', day: '2-digit' };
    const date = document.getElementById("digital-date");
    if (date) date.textContent = now.toLocaleDateString('en-GB', options);
  }

  // تحديث الساعة كل ثانية
  setInterval(updateClock, 1000);
  updateClock();
});
