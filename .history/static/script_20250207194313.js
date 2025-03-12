document.addEventListener("DOMContentLoaded", function () {
    const essayForm = document.getElementById("essay-form");

    if (essayForm) {
        essayForm.addEventListener("submit", function (event) {
            event.preventDefault(); // Prevent default form submission

            const essayText = document.getElementById("essay").value;
            const contextText = document.getElementById("context").value;

            if (essayText.trim().split(/\s+/).length < 20) {
                alert("Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 20 salita.");
                return;
            }

            if (!contextText.trim()) {
                alert("Error: Please provide context for grading.");
                return;
            }

            fetch("/process_essay", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ essay: essayText, context: contextText }),
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    alert("Error: " + data.error);
                } else {
                    document.getElementById("summary-output").innerText = "Summary: " + data.summary;
                    document.getElementById("grading-output").innerText = "Final Grade: " + data.final_grade + "%";
                }
            })
            .catch(error => {
                console.error("Error processing essay:", error);
                alert("An error occurred while processing the essay.");
            });
        });
    }
});