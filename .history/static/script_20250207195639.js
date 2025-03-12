document.addEventListener("DOMContentLoaded", function () {
    const essayForm = document.getElementById("essay-form");

    if (essayForm) {
        essayForm.addEventListener("submit", function (event) {
            event.preventDefault(); // Prevent default form submission

            const essayText = document.getElementById("essay").value.trim();
            const contextText = document.getElementById("context").value.trim();
            const fileInput = document.querySelector('input[type="file"]');

            let isFromImage = false;

            // Check if an image was uploaded
            if (fileInput.files.length > 0) {
                isFromImage = true;
            }

            // Validate word count only if text is manually entered (not from OCR)
            if (!isFromImage && essayText.split(/\s+/).length < 20) {
                alert("Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 20 salita.");
                return;
            }

            // Ensure context is provided
            if (!contextText) {
                alert("Error: Please provide context for grading.");
                return;
            }

            // Prepare data to send
            const formData = {
                essay: essayText,
                context: contextText,
                is_from_image: isFromImage
            };

            fetch("/process_essay", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(formData),
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
