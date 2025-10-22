document.addEventListener("DOMContentLoaded", function() {
  // ==========================
  // Digital Clock
  // ==========================
  function updateClock() {
    const now = new Date();
    const clockElem = document.getElementById("digital-clock");
    const dateElem = document.getElementById("digital-date");
    
    // Format time
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');
    
    if (clockElem) {
      clockElem.textContent = `${hours}:${minutes}:${seconds}`;
    }
    
    // Format date
    if (dateElem) {
      const options = { 
        weekday: 'long', 
        year: 'numeric', 
        month: 'long', 
        day: 'numeric' 
      };
      dateElem.textContent = now.toLocaleDateString('en-US', options);
    }
  }
  
  // Initialize and update every second
  updateClock();
  setInterval(updateClock, 1000);
  
  // ==========================
  // Chart.js - Weekly Appointments
  // ==========================
  const chartDataElement = document.getElementById("chart-data");
  const chartCanvas = document.getElementById("patientsWeekChart");
  
  if (chartDataElement && chartCanvas) {
    try {
      const chartData = JSON.parse(chartDataElement.textContent);
      
      // Pastel color palette for bars
      const pastelColors = [
        '#FFB4A2', '#A2D2FF', '#BDE0FE', '#FFAFCC', 
        '#CDB4DB', '#FFC8DD', '#B8E0D2', '#A2D2FF'
      ];
      
      const ctx = chartCanvas.getContext("2d");
      new Chart(ctx, {
        type: "bar",
        data: {
          labels: chartData.labels,
          datasets: [{
            label: "Appointments",
            data: chartData.data,
            backgroundColor: pastelColors,
            borderRadius: 8,
            borderSkipped: false,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: 'rgba(255, 255, 255, 0.9)',
              titleColor: '#333',
              bodyColor: '#555',
              borderColor: '#ddd',
              borderWidth: 1,
              padding: 12,
              callbacks: {
                label: ctx => ` ${ctx.parsed.y} appointments`
              }
            }
          },
          scales: {
            x: { 
              grid: { display: false },
              ticks: { color: '#666' }
            },
            y: {
              beginAtZero: true,
              grid: { color: "rgba(0, 0, 0, 0.05)" },
              ticks: { 
                color: '#666',
                stepSize: 1,
                precision: 0
              }
            }
          },
          animation: {
            duration: 1200,
            easing: "easeOutQuart"
          }
        }
      });
    } catch (err) {
      console.error("Error initializing chart:", err);
    }
  }
});