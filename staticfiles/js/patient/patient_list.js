
function filterPatients() {
    let input = document.getElementById("searchInput").value.toLowerCase();
    let rows = document.querySelectorAll("#patientsTable tbody tr");

    rows.forEach(row => {
        let name = row.cells[1].textContent.toLowerCase();
        let mobile = row.cells[2].textContent.toLowerCase();
        if (name.includes(input) || mobile.includes(input)) {
            row.style.display = "";
        } else {
            row.style.display = "none";
        }
    });
}
